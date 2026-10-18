"""Private bounded loopback HTTP owned by the live game router.

The handler never logs request bodies or PINs. It delegates typed operations
to the core process; no second process edits live gameplay inventories.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
import socket
import threading
import time

from .city_operations import CityError, CityOperations
from .ratings_public import RatingsPublic

MAX_REQUEST = 4096
MAX_RESPONSE = 65536
HOST = '127.0.0.1'
PORT = 8083


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self, *args):
        self.workers=threading.BoundedSemaphore(8)
        super().__init__(*args)
    def process_request(self, request, address):
        if not self.workers.acquire(blocking=False):
            try:
                request.settimeout(.5)
                body=b'{"error":"rate_limited"}'
                request.sendall(b'HTTP/1.0 429 Too Many Requests\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                # A POST writer may still send its bounded body after headers.
                # Half-close our response, then drain briefly so closing does
                # not reset the peer before it can read the 429 response.
                request.shutdown(socket.SHUT_WR)
                deadline=time.monotonic()+.5;remaining=8192
                while remaining and time.monotonic()<deadline:
                    request.settimeout(max(.001,deadline-time.monotonic()))
                    chunk=request.recv(min(4096,remaining))
                    if not chunk:break
                    remaining-=len(chunk)
            except OSError:pass
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request, address)
        except BaseException:
            self.workers.release();self.shutdown_request(request);raise
    def process_request_thread(self, request, address):
        try:super().process_request_thread(request, address)
        finally:self.workers.release()


def decode_json(raw):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise CityError('invalid_request')
            result[key]=value
        return result
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(CityError('invalid_request')))
    except (ValueError, UnicodeError):raise CityError('invalid_request') from None


class CityHTTP:
    def __init__(self, router, key, *, port=PORT, operations=None, ratings=None):
        if not isinstance(key, str) or not 32<=len(key)<=512:raise ValueError('Private city key requires 32..512 characters')
        if type(port) is not int or not 0<=port<=65535:raise ValueError('Invalid private city port')
        self.router=router;self.operations=operations or CityOperations(router)
        self.ratings=ratings or RatingsPublic(router)
        self.key=key;self.closed=threading.Event();self.slots=threading.BoundedSemaphore(8)
        self.close_lock=threading.Lock()
        service=self

        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.0'
            server_version='TIOCity'
            def log_message(self, *_):pass
            def setup(self):
                super().setup();self.connection.settimeout(3)
            def reply(self, status, body):
                raw=json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
                if len(raw)>MAX_RESPONSE:status=503;raw=b'{"error":"service_unavailable"}'
                self.send_response(status);self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)));self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff');self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                acquired=False
                try:
                    if self.client_address[0]!=HOST:raise CityError('unauthorized', 403)
                    supplied=self.headers.get('Authorization', '')
                    if len(supplied)>1024 or not hmac.compare_digest(supplied.encode(), ('Bearer '+service.key).encode()):
                        raise CityError('unauthorized', 401)
                    if service.closed.is_set() or service.router.server.stopping.is_set():raise CityError('service_unavailable', 503)
                    if self.path not in ('/v1/city/status', '/v1/city/action', '/v2/services/status', '/v2/services/action', '/v1/ratings/status'):raise CityError('invalid_request', 404)
                    if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':
                        raise CityError('invalid_request')
                    length=self.headers.get('Content-Length', '')
                    if not length.isascii() or not length.isdecimal():raise CityError('invalid_request')
                    length=int(length)
                    if not 0<length<=MAX_REQUEST:raise CityError('invalid_request', 413)
                    acquired=service.slots.acquire(blocking=False)
                    if not acquired:raise CityError('rate_limited', 429)
                    raw=self.rfile.read(length)
                    if len(raw)!=length:raise CityError('invalid_request')
                    data=decode_json(raw)
                    if self.path=='/v1/ratings/status':result=service.ratings.status(data)
                    elif self.path.startswith('/v2/services/'):
                        from .services_runtime import service as services
                        manager=services(service.router)
                        result=manager.status(data) if self.path.endswith('/status') else manager.action(data)
                    else:result=service.operations.status(data) if self.path=='/v1/city/status' else service.operations.action(data)
                    self.reply(409 if result.get('error')=='pin_rejected' else 200, result)
                except CityError as error:self.reply(error.status, dict(error=error.code))
                except (BrokenPipeError, ConnectionResetError):pass
                except Exception:
                    # No exception text, SQL details, operation args or PIN logs.
                    try:self.reply(503, dict(error='service_unavailable'))
                    except (OSError, TimeoutError):pass
                finally:
                    if acquired:service.slots.release()
            def do_GET(self):self.reply(405, dict(error='invalid_request'))
            do_PUT=do_DELETE=do_PATCH=do_HEAD=do_GET

        self.http=BoundedHTTPServer((HOST, port), Handler)
        self.thread=threading.Thread(target=self.http.serve_forever, kwargs=dict(poll_interval=.1),
                                     name='tio-city-http', daemon=True)
        self.watcher=threading.Thread(target=self._watch_stop, name='tio-city-http-stop', daemon=True)

    def start(self):
        self.thread.start();self.watcher.start();return self

    def _watch_stop(self):
        while not self.closed.is_set():
            if self.router.server.stopping.wait(.1):self.close();return

    def close(self):
        with self.close_lock:
            if self.closed.is_set():return
            self.closed.set()
        if self.thread.is_alive():self.http.shutdown()
        self.http.server_close()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:self.thread.join(5)


def ensure_server(economy, router):
    """Start once when the game process receives its existing private key."""
    if getattr(economy, '_city_http_attempted', False):return getattr(economy, '_city_http', None)
    key=os.environ.get('BANK_SERVICE_KEY')
    if not key:return None
    # One main-loop tick owns this transition. A failed bind disables this
    # adapter, preserving gameplay; the private gateway subsequently fails 503.
    economy._city_http_attempted=True
    try:economy._city_http=CityHTTP(router, key).start()
    except (OSError, ValueError):
        economy._city_http=None
        logging.getLogger('tio.server').warning('Private city adapter unavailable; portal operations disabled')
    return economy._city_http
