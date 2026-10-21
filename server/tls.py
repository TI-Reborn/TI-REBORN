"""Bounded TLS bootstrap and replaceable credentials for the shared backend.

Only login accepts a bridge preface. Its port is used with a fixed loopback
address; no client-provided address or IP replaces the actual network peer.
"""
import ssl
import struct
import threading
import time
import hashlib
import json
import hmac
from pathlib import Path

BRIDGE_MAGIC = b'TIOT'
BRIDGE_VERSION = 1
BRIDGE_PREFACE_SIZE = 8


def bridge_preface(port):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Bridge session port must be between 1024 and 65535')
    return struct.pack('!4sBBH', BRIDGE_MAGIC, BRIDGE_VERSION, 0, port)


def read_bridge_preface(connection, deadline, launch_manifests=None):
    data = bytearray()
    while len(data) < BRIDGE_PREFACE_SIZE:
        remaining = deadline-time.monotonic()
        if remaining <= 0:raise TimeoutError('TLS bridge bootstrap timed out')
        connection.settimeout(remaining)
        chunk = connection.recv(BRIDGE_PREFACE_SIZE-len(data))
        if not chunk:raise EOFError('TLS bridge bootstrap disconnected')
        data.extend(chunk)
    magic, version, flags, port = struct.unpack('!4sBBH', data)
    if magic != BRIDGE_MAGIC or version not in (1,2) or flags not in (0,1):
        raise ValueError('Invalid TLS bridge preface')
    if launch_manifests is not None and version!=2:
        raise ValueError('Current launcher update verification is required')
    if version==2:
        identity=bytearray()
        while len(identity)<38:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Launcher admission timed out')
            connection.settimeout(remaining)
            chunk=connection.recv(38-len(identity))
            if not chunk:raise EOFError('Launcher admission disconnected')
            identity.extend(chunk)
        if launch_manifests is not None:
            validate_launch_identity(identity,launch_manifests)
    bridge_preface(port)
    result=BridgePort(port)
    result.language='english' if flags==1 else 'russian'
    return result


def validate_launch_identity(identity,root):
    """Compare with live publication pointers, including later releases.

    This is version admission for the official launcher, not remote attestation
    against a deliberately modified executable or a custom protocol client.
    """
    root=Path(root)
    current=(root/'updates/manifest.json').read_bytes()
    launcher=json.loads((root/'downloads/launcher-manifest.json').read_bytes())
    version=tuple(map(int,launcher['version'].split('.')))
    if (len(identity)!=38 or len(version)!=3 or
            not hmac.compare_digest(identity[:32],hashlib.sha256(current).digest()) or
            struct.unpack('!HHH',identity[32:])!=version):
        raise ValueError('Client or launcher release is obsolete; update through TIO Launcher')


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
