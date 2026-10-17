"""Bounded TLS bootstrap and replaceable credentials for the shared backend.

Only login accepts a bridge preface. Its port is used with a fixed loopback
address; no client-provided address or IP replaces the actual network peer.
"""
import ssl
import struct
import threading
import time
from pathlib import Path

BRIDGE_MAGIC = b'TIOT'
BRIDGE_VERSION = 1
BRIDGE_PREFACE_SIZE = 8


def bridge_preface(port):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Bridge session port must be between 1024 and 65535')
    return struct.pack('!4sBBH', BRIDGE_MAGIC, BRIDGE_VERSION, 0, port)


def read_bridge_preface(connection, deadline):
    data = bytearray()
    while len(data) < BRIDGE_PREFACE_SIZE:
        remaining = deadline-time.monotonic()
        if remaining <= 0:raise TimeoutError('TLS bridge bootstrap timed out')
        connection.settimeout(remaining)
        chunk = connection.recv(BRIDGE_PREFACE_SIZE-len(data))
        if not chunk:raise EOFError('TLS bridge bootstrap disconnected')
        data.extend(chunk)
    magic, version, flags, port = struct.unpack('!4sBBH', data)
    if (magic, version) != (BRIDGE_MAGIC, BRIDGE_VERSION) or flags not in (0,1):
        raise ValueError('Invalid TLS bridge preface')
    bridge_preface(port)
    result=BridgePort(port)
    result.language='english' if flags==1 else 'russian'
    return result


class BridgePort(int):
    """Integer-compatible login route carrying this connection's UI locale."""
    language='russian'


def build_context(config):
    """Validate a complete key/certificate pair before making it available."""
    config.validate()
    # Resolve a shared renewal-directory symlink once, avoiding a certificate
    # from one generation and a key from another during an atomic rotation.
    cert_path,key_path=Path(config.certificate),Path(config.private_key)
    if cert_path.parent==key_path.parent:
        parent=cert_path.parent.resolve(strict=True)
        cert_path,key_path=parent/cert_path.name,parent/key_path.name
    else:
        cert_path,key_path=cert_path.resolve(strict=True),key_path.resolve(strict=True)
    def stamps():
        return tuple((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns) for s in (cert_path.stat(),key_path.stat()))
    before=stamps()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= ssl.OP_NO_COMPRESSION
    context.load_cert_chain(str(cert_path), str(key_path))
    # CPython's PEM decoder supplies certificate validity without third-party
    # runtime dependencies. Never decode or log private-key bytes.
    certificate = ssl._ssl._test_decode_cert(str(cert_path))
    now = time.time()
    if not ssl.cert_time_to_seconds(certificate['notBefore']) <= now < ssl.cert_time_to_seconds(certificate['notAfter']):
        raise ValueError('TLS certificate is not currently valid')
    if before!=stamps():raise ValueError('TLS credentials changed during validation')
    return context


class TLSContexts:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.context = build_context(config)
        self.generation = 1

    def current(self):
        with self.lock:return self.context

    def reload(self):
        candidate = build_context(self.config)
        with self.lock:
            self.context = candidate
            self.generation += 1
            return self.generation
