import json
"""Concurrent sessions and shared authoritative matches on legacy wire fields.

Login and game listeners are separate because both protocols are server-first.
The mode1 echo binds to a one-use pending login, never merely to an IP address.
Match/session errors are isolated; shared storage failures stop the service.
"""
from contextlib import ExitStack
import logging
import queue
import secrets
import selectors
import socket
import sqlite3
import threading
import time
from typing import TYPE_CHECKING

from .accounts import Accounts, identity
from .auth_errors import LoginRejected
from tio.protocol.login import LoginFailureStatus
from .failure_policy import storage_failure
from .login_guard import LoginGuard,LoginThrottled
from tio import battle_settlement

if TYPE_CHECKING:
    from tools.loopback_exchange import LoopbackExchange

LOG = logging.getLogger('tio.server')
MAX_SESSIONS = 16
MAX_HANDOFFS = 8


def configure_keepalive(connection: socket.socket) -> None:
    """Deliver small game replies promptly and detect vanished idle peers."""
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, 'TCP_KEEPIDLE'):
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4)
    elif hasattr(socket, 'SIO_KEEPALIVE_VALS'):
        connection.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 60000, 15000))
    else:
        raise RuntimeError('Bounded TCP keepalive is unavailable on this platform')
    if hasattr(socket, 'TCP_USER_TIMEOUT'):
        # Bound unacknowledged outgoing data too (keepalive only probes idle TCP).
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 120000)


class MultiServer:
    def __init__(self, server):
        self.server, self.config = server, server.config
        from .tls import TLSContexts
        self.tls = TLSContexts(self.config.tls) if self.config.tls.enabled else None
        self.accounts = Accounts(self.config.database)
        self.lock = threading.Lock()
        self.sessions = set()
        self.active_accounts = {}
        self.game_listeners = ()
        self.pending = {}
        self.routes = {}  # thread -> socket, including workers awaiting cleanup
        self.route_ips={}
        self.login_requests = queue.Queue(maxsize=MAX_SESSIONS + LoginGuard.MAX_UNAUTHENTICATED)
        self.login_pending = {}
        self.login_constructor_thread = None
        self.tls_ready = queue.Queue()
        self.tls_workers = {}
        self.tls_connections = {}
        self.tls_pending = {}  # token -> (kind, real peer IP), including queued sockets
        self.failures = queue.Queue()
        self.login_guard=LoginGuard()
        from .team_arena import TeamArena
        self.team_arena = TeamArena(survival_duels=self.config.survival_duels)
        self.team_arena.init_assault(self.config.database)
        self.team_arena.init_training(self.config.database)
        from .presence import Presence
        self.presence = Presence()
        from tio.player_auction import AuctionStore
        self.player_auction = AuctionStore(self.config.database, pledge_percent=5)
        from tio.mail import MailStore
        self.mail_store=MailStore(self.config.database)
        from .economy_runtime import SharedEconomy
        self.economy=SharedEconomy(self.config.database)
        battle_settlement.initialise(self.config.database)
        from tio.db_transaction import transaction
        from tio.reservation_quests import schema as reservation_quest_schema
        with transaction(self.config.database) as db:
            reservation_quest_schema(db)
        from .battle_journal import BattleJournal
        self.team_arena.journal=BattleJournal(self.team_arena,self.config.database)
        self.team_arena.journal.recover()
        from .tournament_arena import TournamentArena
        self.team_arena.tournaments = TournamentArena(self.team_arena, self.config.database)
        from tio.wagers import WagerStore
        from tio.db_transaction import connect as wager_connect
        from contextlib import closing as wager_closing
        with wager_closing(wager_connect(self.config.database)) as db:
            wager_retained={r[0] for r in db.execute('SELECT match_id FROM battle_checkpoints')}
            wager_retained.update(r[0] for r in db.execute('SELECT match_id FROM battle_settlement_jobs'))
        WagerStore(self.config.database).recover(wager_retained)
        self.team_arena.recover_assault_bindings()
        self.team_arena.recover_training_events()
        from .team_ranked import reconcile_pending
        from contextlib import closing
        from tio.db_transaction import connect
        with closing(connect(self.config.database)) as db:
            retained={r[0] for r in db.execute("SELECT match_id FROM battle_checkpoints WHERE status!='quarantined'")}
            retained.update(r[0] for r in db.execute('SELECT match_id FROM battle_settlement_jobs'))
        reconcile_pending(self.config.database,retained)
        from .player_trade import PlayerTrade
        self.player_trade = PlayerTrade(self, self.config.database)
        self.contracts = None
        if getattr(self.config, 'contracts_enabled', False):
            from .contracts_service import ContractsService
            self.contracts = ContractsService(self.team_arena, self.config.database)
            self.team_arena.contracts_service = self.contracts

    def server_population(self):
        """Unique live game accounts; login reservations are not online players."""
        with self.lock:
            return self._online_players(), MAX_SESSIONS

    def _online_players(self):
        # The caller holds self.lock. Character aliases and transports cannot
        # make a single authenticated login occupy multiple online places.
        return len({exchange.authenticated_account for exchange in self.active_accounts.values()
            if getattr(exchange,'game_authenticated',False) and not exchange.stopping.is_set()})

    def server_status(self):
        """Fresh list06 status, independent of cached load or website snapshots."""
        with self.lock:
            available=(not self.server.stopping.is_set() and bool(self.game_listeners)
                and all(listener.fileno()>=0 for listener in self.game_listeners))
            return self._online_players() if available else 0, MAX_SESSIONS, available

    def game_authenticated(self, exchange):
        """Auth2 success promotes the one-use login handoff to an online game."""
        with self.lock:
            account=getattr(exchange,'authenticated_account',None)
            if (self.server.stopping.is_set() or exchange.stopping.is_set()
                    or self.active_accounts.get(account) is not exchange):
                raise ValueError('Game account is no longer active')
            exchange.game_authenticated=True

    def authorize(self, exchange, login):
        with self.login_guard.hash_slot(exchange.login_peer_address,login.login_bytes):
            account = self.accounts.verify(login.login_bytes, login.password_bytes)
        with self.team_arena.lock:
            self.accounts.require_access(account)
            from tio.battle_checkpoints import blocked
            from tio.character_identity import owners
            # Authentication remains one claim per human login. A new slot
            # cannot bypass another slot's quarantined or unpaid battle.
            for save_owner in owners(self.config.database,account):
                owner=self.team_arena.account_owners.get(save_owner)
                private=self.team_arena.private.get(save_owner)
                if (self.team_arena.battles.get(owner,{}).get('faulted')
                        or private and getattr(private[0].arena,'_faulted',False)
                        or battle_settlement.blocked(self.config.database,save_owner)):
                    raise LoginRejected('battle-recovery', LoginFailureStatus.MAINTENANCE, 'Battle result is awaiting recovery')
                if blocked(self.config.database,save_owner):
                    raise LoginRejected('checkpoint-recovery', LoginFailureStatus.MAINTENANCE, 'Battle checkpoint is awaiting recovery')
            with self.lock:
                if len(self.active_accounts)>=MAX_SESSIONS:
                    raise LoginRejected('capacity', LoginFailureStatus.OVERLOADED, 'Authenticated account capacity reached')
                if account in self.active_accounts:
                    raise LoginRejected('already-connected', LoginFailureStatus.ACCOUNT_IN_USE, 'Account is already connected')
                self.active_accounts[account] = exchange
                exchange.authenticated_account = account
        if getattr(getattr(exchange, 'login_socket', None), 'trace_id', None) is not None:
            exchange.login_socket.trace_account = account
        LOG.info('Login authorized requested_login=%s transport=%s',
            account, 'tls' if getattr(exchange,'login_tls',False) else 'direct')
        return account

    def disconnect_banned(self, login: str) -> None:
        with self.lock:
            exchange = self.active_accounts.get(login)
        if exchange is not None:
            exchange.stop()

    def select_character(self,exchange,owner):
        """Bind the private journal only after an authenticated owned selection."""
        from tio.character_identity import owners
        from tio.battle_checkpoints import blocked
        from .battle_journal import PrivateJournal
        login=getattr(exchange,'authenticated_account',None)
        if login is None:raise ValueError('Сначала войдите в аккаунт')
        with self.team_arena.lock:
            allowed=owners(self.config.database,login)
            if owner not in allowed:raise ValueError('Этот персонаж не принадлежит аккаунту')
            contracts = getattr(self, 'contracts', None)
            grouped = contracts.selected_owner(login) if contracts else None
            if grouped is not None and grouped != owner:
                raise ValueError('Сначала выйдите из группы другим персонажем этого аккаунта')
            retained=[candidate for candidate in allowed if self.team_arena.retained(candidate)]
            if any(candidate!=owner for candidate in retained):
                raise ValueError('Сначала завершите бой другим персонажем этого аккаунта')
            if blocked(self.config.database,owner) or battle_settlement.blocked(self.config.database,owner):
                raise ValueError('Результат предыдущего боя ещё сохраняется')
            manager=getattr(exchange.arena,'_durable',None)
            if manager is not None and manager.account!=owner:
                if manager.known or exchange.arena._fields:
                    raise ValueError('Сначала завершите текущий бой')
            if manager is None or manager.account!=owner:
                PrivateJournal(exchange.arena,self.config.database,owner,session=exchange)

    def detach_character_social(self, exchange: 'LoopbackExchange') -> None:
        if self.contracts is not None:
            self.contracts.disconnect(exchange)
        self.player_trade.disconnect(exchange)
        self.presence.disconnect(exchange)

    def detach_character_play(self, exchange: 'LoopbackExchange') -> None:
        retained = self.team_arena.disconnect(exchange)
        if hasattr(exchange, 'probe_character_id'):
            exchange.survival.disconnected(exchange.probe_character_id)
            if not retained:
                exchange.arena.disconnect(exchange.probe_character_id)

    def return_to_character_select(self, exchange: 'LoopbackExchange') -> bool:
        with self.team_arena.lock:
            if (self.team_arena.in_battle(exchange, include_results=True)
                    or exchange.arena._fields):
                return False
            self.detach_character_social(exchange)
            self.detach_character_play(exchange)
            for field in ('probe_character_id', 'probe_character_name', 'selected_character_slot',
                          'private_resume_packets', '_contract_markers', '_travel_party_revision',
                          '_prison_announced_town', '_team_heartbeat_at', '_next_city_listing',
                          '_economy_refresh_at', '_treatment_rate'):
                vars(exchange).pop(field, None)
            exchange._achievement_city_confirmed = False
            exchange._private_chat_map_confirmed = False
            exchange.account = exchange.authenticated_account
        return True

    def login_rejected(self, exchange, login, rejection):
        # A validated, bounded ASCII identifier cannot inject lines into logs.
        # Never include password, hash, raw packet or exception text here.
        try: name = identity(login.login_bytes.decode('ascii'))
        except (ValueError, UnicodeError): name = '<invalid>'
        LOG.warning('Login rejected category=%s requested_login=%s status=%d transport=%s',
            rejection.category, name, rejection.status,
            'tls' if getattr(exchange,'login_tls',False) else 'direct')

    def login_protocol_rejected(self, exchange, opcode):
        LOG.warning('Login rejected category=protocol requested_login=<unparsed> opcode=%d transport=%s',
            opcode, 'tls' if getattr(exchange,'login_tls',False) else 'direct')

    def expect_game(self, exchange, previous):
        key = (previous, exchange.completion_token)
        with self.lock:
            if self.server.stopping.is_set():raise InterruptedError('Server stopping')
            if key in self.pending:raise RuntimeError('Duplicate handoff token')
            self.pending[key] = (exchange, time.monotonic()+10)
            exchange.handoff_key = key

    def accept(self, exchange):
        if not exchange.connections:return exchange.login_socket
        deadline = time.monotonic()+10
        while not self.server.stopping.is_set() and not exchange.stopping.is_set():
            if time.monotonic() >= deadline:raise TimeoutError('Game connection timed out')
            try:
                connection, state = exchange.handoff_queue.get(timeout=.1)
            except queue.Empty:continue
            exchange.mode1_handoff = state
            return connection
        raise InterruptedError('Server stopping')

    def route(self, connection, address, *, secure=False):
        from tools.loopback_exchange import LoopbackExchange
        from tio.protocol.mode1 import encode_mode1_challenge_frame, derive_mode1_key, decode_mode1_reply
        from tio.protocol.transport import InitialFrameReader, InitialCipher
        delivered = False
        try:
            configure_keepalive(connection)
            seed = secrets.token_bytes(8)
            connection.settimeout(5)
            connection.sendall(encode_mode1_challenge_frame(seed))
            reader = InitialFrameReader(InitialCipher('C2S', derive_mode1_key(seed)))
            raw, packets = LoopbackExchange.receive_frame(connection,reader)
            result = decode_mode1_reply(packets[0])
            key = (result.previous_transport_u32,result.completion_u32)
            with self.lock:
                found = self.pending.get(key)
                if not found:raise ValueError('Unknown or consumed game handoff')
                exchange, deadline = found
                if time.monotonic() >= deadline or exchange.stopping.is_set() or self.server.stopping.is_set():
                    raise ValueError('Expired game handoff')
                if address[0] != exchange.login_peer_address:
                    raise ValueError('Game handoff source mismatch')
                if bool(getattr(exchange,'login_tls',False)) != secure:
                    raise ValueError('Game handoff transport mismatch')
                if getattr(connection, 'trace_id', None) is not None:
                    connection.trace_account = exchange.authenticated_account
                del self.pending[key]
                exchange.handoff_queue.put_nowait((connection,(seed,reader,raw,packets)))
                delivered = True
                # Ownership has transferred to the login worker.
                self.routes[threading.current_thread()] = None
                self.route_ips.pop(threading.current_thread(),None)
        except (OSError, ValueError, EOFError) as error:
            if isinstance(error, TimeoutError) and getattr(connection, 'trace_id', None) is not None:
                connection.record_error('handoff', error)
            LOG.warning('Rejected incomplete or invalid game handoff')
        except Exception as exc:
            if storage_failure(exc):self.failures.put(exc)
            else:LOG.exception('Game handoff failed')
        finally:
            if not delivered:connection.close()

    def worker(self, exchange):
        try:
            exchange.run()
            failure = exchange.failure
            if storage_failure(failure):
                raise failure
            if failure is not None and not isinstance(failure,(ValueError,OSError,EOFError)):
                raise failure
        except Exception as exc:
            self.session_failure(exchange,exc)
        finally:
            exchange.stopping.set()
            # Remove tokens first. Account remains claimed until settlement ends.
            with self.lock:
                exchange.game_authenticated=False
                self.pending.pop(getattr(exchange,'handoff_key',None),None)
            try:
                self.detach_character_social(exchange)
            except Exception as exc:
                if storage_failure(exc):self.failures.put(exc)
                else:LOG.exception('Presence disconnect failed')
            try:
                self.detach_character_play(exchange)
            except Exception as exc:
                self.session_failure(exchange,exc)
            finally:
                for connection in exchange.connections:connection.close()
                exchange.login_socket.close()
                while True:
                    try:exchange.handoff_queue.get_nowait()[0].close()
                    except queue.Empty:break
                with self.lock:
                    account = getattr(exchange,'authenticated_account',None)
                    if self.active_accounts.get(account) is exchange:
                        del self.active_accounts[account]

    def session_failure(self,exchange,error):
        if storage_failure(error):
            self.failures.put(error)
            return
        LOG.error('Session failed account=%s error=%s',
                  getattr(exchange,'authenticated_account',None),type(error).__name__,
                  exc_info=(type(error),error,error.__traceback__))
        try:self.team_arena.fail_session(exchange,error)
        except Exception as recovery_error:
            if storage_failure(recovery_error):self.failures.put(recovery_error)
            else:LOG.exception('Session recovery deferred')

    def recover_settlements(self,*,force=False):
        try:
            with self.team_arena.lock:
                battle_settlement.retry(self.config.database,force=force)
        except Exception as error:
            if storage_failure(error):raise
            LOG.exception('Battle settlement recovery deferred')

    def new_login(self, connection, address, *, secure=False, bridge_port=None, reservation=None):
        # Reserve admission before queueing so slow SQLite schema setup cannot
        # create an unbounded backlog of unauthenticated login constructors.
        token = None
        try:
            with self.lock:
                if reservation is None:
                    self.admit_login(address[0])
                elif self.tls_pending.get(reservation) != ('login', address[0]):
                    raise ValueError('Missing TLS login reservation')
                if self.login_constructor_thread is None or not self.login_constructor_thread.is_alive():
                    raise RuntimeError('Login constructor worker is not running')
                token = object()
                self.login_pending[token] = address[0]
                if reservation is not None:
                    self.tls_pending.pop(reservation, None)
                    self.tls_connections.pop(reservation, None)
                try:
                    self.login_requests.put_nowait((token, connection, address, secure, bridge_port))
                except queue.Full:
                    self.login_pending.pop(token, None)
                    raise LoginThrottled('constructor-capacity')
        except LoginThrottled:
            connection.close()
            return
        except BaseException:
            if token is not None:
                with self.lock:
                    self.login_pending.pop(token, None)
            connection.close()
            raise

    def construct_logins(self):
        """Build sessions serially outside the selector/accept thread."""
        from tools.loopback_exchange import LoopbackExchange
        from tio.protocol.transport import InitialChallenge
        from .runtime import Events

        while True:
            request = self.login_requests.get()
            try:
                if request is None:
                    return
                token, connection, address, secure, bridge_port = request
                exchange = None
                try:
                    if self.server.stopping.is_set():
                        with self.lock:
                            self.login_pending.pop(token, None)
                        connection.close()
                        continue
                    configure_keepalive(connection)
                    exchange = LoopbackExchange(None, completion=True, login_result=True,
                        server_list=True, server_entry=True, server_login=True,
                        mode1_challenge=True, mode1_complete=True, auth2_result=True,
                        empty_characters=True, shared_config=True, create_probe=False,
                        create_success_probe=False, select_probe=True, mychar_probe=True,
                        town_probe=True, enter_town_probe=True, open_town_probe=True,
                        observation_seconds=0, database=self.config.database,
                        owned_pet_probe=True, listener=self.server.listener,
                        advertised_address='127.0.0.1' if secure else self.config.advertised_address, router=self)
                    exchange.login_socket = connection
                    exchange.login_peer_address = address[0]
                    exchange.login_tls = secure
                    exchange.language = getattr(bridge_port,'language','russian')
                    exchange.interface = getattr(bridge_port,'interface','new')
                    exchange.contracts_ui_token = getattr(bridge_port,'control_token',None)
                    exchange.port = int(bridge_port) if secure else self.config.session_port
                    exchange.completion_token = secrets.randbits(32)
                    exchange.initial_challenge = InitialChallenge(0,secrets.randbits(32),0,secrets.randbits(32))
                    exchange.handoff_queue = queue.Queue(maxsize=1)
                    exchange.events = Events()
                    exchange.quiet = True
                    exchange.thread = threading.Thread(target=self.worker,args=(exchange,),name='tio-session')
                    with self.lock:
                        self.login_pending.pop(token, None)
                        if self.server.stopping.is_set():
                            connection.close()
                        else:
                            self.sessions.add(exchange)
                            exchange.start()
                except BaseException as error:
                    with self.lock:
                        self.login_pending.pop(token, None)
                        if exchange is not None:
                            self.sessions.discard(exchange)
                    connection.close()
                    if storage_failure(error) or not isinstance(error, Exception):
                        self.failures.put(error)
                    else:
                        LOG.exception('Login session construction failed')
            finally:
                self.login_requests.task_done()

    def admit_login(self, ip):
        """Caller holds self.lock, so reserved TLS and direct slots are shared."""
        waiting=[peer for kind,peer in self.tls_pending.values() if kind=='login']
        unauthenticated=[e.login_peer_address for e in self.sessions
            if getattr(e,'authenticated_account',None) is None]
        constructing=list(self.login_pending.values())
        self.login_guard.admit_connection(ip,unauthenticated=unauthenticated+constructing+waiting,
            total=len(self.sessions)+len(constructing)+len(waiting),max_sessions=MAX_SESSIONS)

    def admit_route(self, ip):
        waiting=[peer for kind,peer in self.tls_pending.values() if kind=='game']
        self.login_guard.admit_handoff(ip,addresses=tuple(self.route_ips.values())+tuple(waiting),
            max_handoffs=MAX_HANDOFFS)

    def start_route(self, connection, address, *, secure=False, reservation=None):
        with self.lock:
            if reservation is None:self.admit_route(address[0])
            elif self.tls_pending.get(reservation) != ('game', address[0]):
                raise ValueError('Missing TLS game reservation')
            thread=threading.Thread(target=self.route,args=(connection,address),
                kwargs={'secure':secure},name='tio-handoff')
            self.routes[thread]=connection
            self.route_ips[thread]=address[0]
            if reservation is not None:
                self.tls_pending.pop(reservation)
                self.tls_connections.pop(reservation)
            thread.start()

    def start_tls(self, connection, address, kind):
        """Reserve normal admission and a dedicated worker before cryptography."""
        with self.lock:
            if len(self.tls_workers)>=self.config.tls.max_handshakes:
                connection.close()
                return
            try:
                if kind=='login':self.admit_login(address[0])
                else:self.admit_route(address[0])
            except LoginThrottled:
                connection.close()
                return
            token=object()
            thread=threading.Thread(target=self.tls_handshake,
                args=(token,connection,address,kind),name='tio-tls-handshake')
            self.tls_workers[thread]=token
            self.tls_connections[token]=connection
            self.tls_pending[token]=(kind,address[0])
            thread.start()

    def tls_handshake(self, token, connection, address, kind):
        from .tls import read_bridge_preface, ContractsControl
        queued=False
        try:
            deadline=time.monotonic()+self.config.tls.handshake_timeout_seconds
            connection.settimeout(max(.001,deadline-time.monotonic()))
            # Socket wrapping detaches the original file descriptor. Keep the
            # ownership replacement atomic with the shutdown socket snapshot;
            # the actual handshake still runs outside this lock.
            with self.lock:
                if self.server.stopping.is_set():raise InterruptedError('Server stopping')
                connection=self.tls.current().wrap_socket(connection,server_side=True,do_handshake_on_connect=False)
                self.tls_connections[token]=connection
            connection.do_handshake()
            policy=self.config.tls.launch_manifests
            bridge_port=read_bridge_preface(connection,deadline,policy) if kind=='login' or policy is not None else None
            if isinstance(bridge_port, ContractsControl):
                # Same authoritative hub lock as native actions. Network writes
                # remain in this bounded worker, outside the selector.
                from .contracts_ui import handle
                reply=handle(self,bridge_port.token,bridge_port.request)
                raw=json.dumps(reply,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                if len(raw)>65536: raise ValueError('Control reply exceeds bound')
                connection.settimeout(2)
                connection.sendall(len(raw).to_bytes(4,'big')+raw)
                return
            if getattr(bridge_port, 'trace_id', None) is not None:
                connection.start_trace(bridge_port.trace_id, kind)
            connection.settimeout(5)
            with self.lock:
                if self.server.stopping.is_set():raise InterruptedError('Server stopping')
                self.tls_ready.put_nowait((token,connection,address,kind,bridge_port))
                queued=True
        except (OSError,ValueError,EOFError):
            LOG.warning('Rejected TLS bootstrap kind=%s',kind)
        except Exception:
            LOG.exception('TLS bootstrap worker failed kind=%s',kind)
        finally:
            if not queued:
                connection.close()
                with self.lock:
                    self.tls_pending.pop(token,None)
                    self.tls_connections.pop(token,None)

    def accept_tls_ready(self):
        while True:
            try:token,connection,address,kind,bridge_port=self.tls_ready.get_nowait()
            except queue.Empty:return
            try:
                if kind=='login':self.new_login(connection,address,secure=True,
                    bridge_port=bridge_port,reservation=token)
                else:self.start_route(connection,address,secure=True,reservation=token)
            except Exception as exc:
                connection.close()
                if storage_failure(exc):raise
                LOG.exception('TLS session construction failed kind=%s',kind)
            finally:
                with self.lock:
                    self.tls_pending.pop(token,None)
                    self.tls_connections.pop(token,None)

    @staticmethod
    def bind(address, port):
        listener = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            option = socket.SO_EXCLUSIVEADDRUSE if hasattr(socket,'SO_EXCLUSIVEADDRUSE') else socket.SO_REUSEADDR
            listener.setsockopt(socket.SOL_SOCKET,option,1)
            listener.bind((address,port))
            listener.listen(32)
            return listener
        except BaseException:
            listener.close()
            raise

    def serve(self):
        from .web_status import StatusPublisher
        web_status = StatusPublisher(self.config.data_directory / 'web-status.json')
        self.accounts.check()
        self.recover_settlements(force=True)
        with ExitStack() as stack:
            direct_bind='127.0.0.1' if self.config.tls.launch_manifests is not None else self.config.bind_address
            login_listener = stack.enter_context(self.bind(direct_bind,self.config.game_port))
            game_listener = stack.enter_context(self.bind(direct_bind,self.config.session_port))
            game_listeners=[game_listener]
            selector = stack.enter_context(selectors.DefaultSelector())
            selector.register(login_listener,selectors.EVENT_READ,'login')
            selector.register(game_listener,selectors.EVENT_READ,'game')
            if self.tls is not None:
                for port,kind in ((self.config.tls.login_port,'login'),(self.config.tls.session_port,'game')):
                    listener=stack.enter_context(self.bind(self.config.bind_address,port))
                    if kind=='game':game_listeners.append(listener)
                    selector.register(listener,selectors.EVENT_READ,'tls-'+kind)
                LOG.info('TLS listeners enabled: login %d, game %d, minimum TLS 1.2',
                    self.config.tls.login_port,self.config.tls.session_port)
            self.server.listener = login_listener
            with self.lock:self.game_listeners=tuple(game_listeners)
            LOG.info('Multi-account listeners: login TCP %d, game TCP %d; shared team arena enabled',
                     self.config.game_port,self.config.session_port)
            self.login_constructor_thread=threading.Thread(target=self.construct_logins,
                name='tio-login-constructor')
            self.login_constructor_thread.start()
            try:
                auction_tick=recovery_tick=status_tick=mail_tick=0
                while not self.server.stopping.is_set():
                    if self.server.tls_reload_requested.is_set():
                        self.server.tls_reload_requested.clear()
                        if self.tls is not None:
                            try:LOG.info('TLS credentials reloaded generation=%d',self.tls.reload())
                            except Exception as exc:
                                LOG.error('TLS credential reload rejected; current context retained error=%s',type(exc).__name__)
                    self.accept_tls_ready()
                    if time.monotonic()>=status_tick:
                        web_status.publish(self.server_population())
                        status_tick=time.monotonic()+5
                    self.team_arena.tick()
                    self.economy.tick(self)
                    if time.monotonic()>=mail_tick:
                        try:
                            self.mail_store.expire()
                        except sqlite3.OperationalError as error:
                            if storage_failure(error):raise
                            LOG.warning('Mail expiration deferred: SQLite is busy')
                        mail_tick=time.monotonic()+60
                    if time.monotonic()>=auction_tick:
                        try:self.player_auction.settle()
                        except Exception as exc:
                            if storage_failure(exc):raise
                            LOG.exception('Auction settlement deferred')
                        auction_tick=time.monotonic()+2
                    if time.monotonic()>=recovery_tick:
                        self.recover_settlements()
                        recovery_tick=time.monotonic()+5
                    try:failure = self.failures.get_nowait()
                    except queue.Empty:pass
                    else:raise failure
                    # Reap only completed workers; no lost shutdown joins.
                    with self.lock:
                        for thread in tuple(self.tls_workers):
                            if not thread.is_alive():
                                thread.join()
                                del self.tls_workers[thread]
                        for exchange in tuple(self.sessions):
                            if not exchange.thread.is_alive():
                                exchange.thread.join()
                                self.sessions.remove(exchange)
                        for thread in tuple(self.routes):
                            if not thread.is_alive():
                                thread.join()
                                del self.routes[thread]
                                self.route_ips.pop(thread,None)
                    for key, _ in selector.select(.1):
                        connection, address = key.fileobj.accept()
                        if key.data.startswith('tls-'):
                            self.start_tls(connection,address,key.data[4:])
                        elif key.data == 'login':
                            try:self.new_login(connection,address)
                            except Exception as exc:
                                if storage_failure(exc):raise
                                LOG.exception('Login session construction failed')
                        else:
                            try:self.start_route(connection,address)
                            except LoginThrottled:connection.close()
            finally:
                with self.lock:self.game_listeners=()
                web_status.publish(status='offline')
                self.server.stopping.set()
                self.login_requests.put(None)
                self.login_constructor_thread.join()
                with self.lock:
                    sessions, routes = tuple(self.sessions), tuple(self.routes.items())
                    tls_workers,tls_connections=tuple(self.tls_workers),tuple(self.tls_connections.values())
                for connection in tls_connections:
                    try:connection.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                    connection.close()
                for thread in tls_workers:thread.join()
                with self.lock:
                    self.tls_workers.clear()
                    self.tls_connections.clear()
                    self.tls_pending.clear()
                while not self.tls_ready.empty():
                    self.tls_ready.get_nowait()[1].close()
                if self.server.update_restart:
                    # The session worker owns its encryption state and final send.
                    for exchange in sessions:
                        exchange.stopping.set()
                    deadline = time.monotonic() + 2.0
                    for exchange in sessions:
                        exchange.thread.join(max(0.0, deadline - time.monotonic()))
                for exchange in sessions:exchange.stop()
                for _, connection in routes:
                    if connection is not None:
                        try:connection.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                for exchange in sessions:exchange.thread.join()
                for thread, _ in routes:thread.join()
                self.team_arena.shutdown_battles()
                if not self.failures.empty():raise self.failures.get_nowait()
        LOG.info('Multi-account server stopped; session settlement complete; login_guard=%s',self.login_guard.snapshot())
