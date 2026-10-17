"""Host the existing exchange with a stable listener and orderly disconnect.

Legacy diagnostic mode or opt-in independent authenticated sessions.
The recovered client transport remains experimental; restrict test access.
"""
import argparse
from collections import deque
from contextlib import closing
import logging
from pathlib import Path
import signal
import socket
import sqlite3
import threading

from .config import ServerConfig

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger('tio.server')
RUNTIME_TOOLS = ('loopback_exchange', 'survival_scene', 'battle_actor_fixture',
                 'battle_roster_fixture', 'mining_scene', 'shooting_range_scene', 'encounter_scene')
RUNTIME_ASSETS = ('items_diagnostic.xml', 'skills_diagnostic.xml',
                  'zones_diagnostic.xml', 'customization_diagnostic.xml', 'owned_pet_trial.json')


def preflight(config):
    """Check assets/imports before creating data or opening the game listener."""
    import importlib
    import json
    from xml.etree import ElementTree
    config.tls.validate()
    if config.tls.enabled:
        if not config.multi_account:raise ValueError('TLS requires multi_account = true')
        if len({config.game_port,config.session_port,config.tls.login_port,config.tls.session_port}) != 4:
            raise ValueError('Direct and TLS listener ports must all differ')
        from .tls import build_context
        build_context(config.tls)
    for name in RUNTIME_ASSETS:
        path = ROOT / 'evidence' / name
        if path.suffix == '.xml':
            ElementTree.parse(path)
        else:
            json.loads(path.read_text(encoding='utf-8'))
    for path in (ROOT / 'config').glob('*.json'):
        json.loads(path.read_text(encoding='utf-8'))
    for name in RUNTIME_TOOLS:
        importlib.import_module('tools.' + name)
    # Instantiate readers for required configuration and imported geometry.
    from tio.weapons import WeaponCatalog
    from tio.city_catalogs import CityCatalogs
    from tio.map_generation import generate_map
    WeaponCatalog()
    CityCatalogs(ROOT / 'config/city_catalogs.json')
    from tio.cities import CITIES
    for city in CITIES.values():generate_map(city.profile,seed=0)
    from tio.world_encounters import POLICY
    for biome in POLICY['biomes']:
        scene=generate_map('encounter_'+biome,seed=0,deployment_size=4)
        if scene.arena.containers:raise ValueError('Encounter biome contains equipment crates')
    if config.contracts_enabled:
        from tio.pve_contracts import load_catalog
        from tio.contract_scene import freeze_policy
        for template in load_catalog()['templates']:
            frozen = freeze_policy(template)
            generate_map(template['map_profile'], seed=0, mode=7, deployment_size=8,
                         profiles_data={'profiles': {template['map_profile']: frozen['profile']}})
    if config.database.exists():
        with closing(sqlite3.connect(config.database.as_uri() + '?mode=ro', uri=True)) as db:
            result = db.execute('PRAGMA quick_check').fetchone()[0]
            if result != 'ok':
                raise ValueError('Database quick_check failed: ' + result)
    if config.multi_account:
        from .accounts import Accounts
        Accounts(config.database).check()


class Events(deque):
    """Keep phase lookbacks bounded; never send packet/credential bytes to logs."""
    def __init__(self):
        super().__init__(maxlen=128)

    def append(self, value):
        super().append(value)
        if 'error' in value:
            LOG.warning('Session ended: %s', value['error'])
        elif 'event' in value:
            name = value['event']
            level = logging.INFO if name in ('accepted', 'second_connection_accepted',
                'city_session_started', 'client_disconnected', 'session_stopped') else logging.DEBUG
            LOG.log(level, '%s', name)


class Server:
    def __init__(self, config):
        self.config = config
        self.stopping = threading.Event()
        self.tls_reload_requested = threading.Event()
        self.exchange = None
        self.listener = None

    def stop(self, *_):
        # Signal handler only requests shutdown. The main thread closes sockets
        # and waits for SQLite work/settlement to finish in the worker.
        self.stopping.set()

    def reload_tls(self, *_):
        # Signal callbacks do no certificate I/O; the serving loop validates
        # and swaps the context without touching active SSLSockets.
        self.tls_reload_requested.set()

    def serve(self):
        if self.config.multi_account:
            from .multi import MultiServer
            self.multi = MultiServer(self)
            return self.multi.serve()
        from tools.loopback_exchange import LoopbackExchange
        self.config.data_directory.mkdir(parents=True, exist_ok=True)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            # Exclusive ownership on Windows; reusable TIME_WAIT bind on Linux.
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.config.bind_address, self.config.game_port))
            listener.listen(4)
            self.listener = listener
            LOG.warning('Single diagnostic account only; restrict TCP access to your client IPv4')
            LOG.info('Listening on %s:%d TCP; advertised %s:%d; database %s',
                self.config.bind_address, self.config.game_port,
                self.config.advertised_address, self.config.game_port, self.config.database)
            while not self.stopping.is_set():
                exchange = LoopbackExchange(None, completion=True, login_result=True,
                    server_list=True, server_entry=True, server_login=True,
                    mode1_challenge=True, mode1_complete=True, auth2_result=True,
                    empty_characters=True, shared_config=True, create_probe=True,
                    create_success_probe=True, select_probe=True, mychar_probe=True,
                    town_probe=True, enter_town_probe=True, open_town_probe=True,
                    observation_seconds=0, database=self.config.database,
                    owned_pet_probe=True, listener=listener,
                    advertised_address=self.config.advertised_address)
                exchange.events = Events()
                exchange.quiet = True
                self.exchange = exchange
                exchange.start()
                try:
                    while exchange.thread.is_alive() and not self.stopping.wait(0.1):
                        pass
                finally:
                    if self.stopping.is_set():
                        exchange.stop()
                    # finish applies the existing disconnect/forfeit transaction.
                    try:
                        exchange.finish()
                    finally:
                        for connection in exchange.connections:
                            connection.close()
                        self.exchange = None
                if isinstance(exchange.failure, (sqlite3.Error, FileNotFoundError, PermissionError)):
                    raise exchange.failure
                if exchange.failure is not None and not isinstance(exchange.failure, (ValueError, OSError, EOFError)):
                    raise exchange.failure
        LOG.info('Server stopped; committed player state retained')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/server.toml')
    parser.add_argument('--check', action='store_true', help='Validate config, assets, imports and existing DB without listening')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = ServerConfig.load(args.config)
        logging.getLogger().setLevel(config.log_level)
        preflight(config)
        if args.check:
            LOG.info('Preflight OK; database %s; no listener opened', config.database)
            return 0
        server = Server(config)
        previous = {sig: signal.signal(sig, server.stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        if hasattr(signal,'SIGHUP'):
            previous[signal.SIGHUP]=signal.signal(signal.SIGHUP,server.reload_tls)
        try:
            server.serve()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return 0
    except Exception:
        LOG.exception('Server startup/runtime failure')
        return 1
