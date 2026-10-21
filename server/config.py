"""Deployment settings; gameplay and wire formats remain in tio/."""
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class TLSConfig:
    enabled: bool = False
    login_port: int = 29512
    session_port: int = 29513
    certificate: Path | None = None
    private_key: Path | None = None
    handshake_timeout_seconds: float = 5
    max_handshakes: int = 4
    launch_manifests: Path | None = None

    @classmethod
    def load(cls, data, root):
        allowed = set(cls.__dataclass_fields__)
        if not isinstance(data, dict) or set(data)-allowed:
            raise ValueError('Invalid TLS configuration keys')
        values = dict(data)
        for key in ('certificate', 'private_key', 'launch_manifests'):
            value = values.get(key)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError('TLS certificate/private_key must be nonempty paths')
                value = Path(value).expanduser()
                # Keep a renewal-directory symlink in the configured path;
                # each context build resolves its current generation once.
                values[key] = (value if value.is_absolute() else root / value).absolute()
        result = cls(**values)
        result.validate()
        return result

    def validate(self):
        if type(self.enabled) is not bool:
            raise ValueError('tls.enabled must be boolean')
        for port in (self.login_port, self.session_port):
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError('TLS ports must be integers between 1024 and 65535')
        if self.login_port == self.session_port:
            raise ValueError('TLS login and session ports must differ')
        if (type(self.handshake_timeout_seconds) not in (int, float)
                or not .1 <= self.handshake_timeout_seconds <= 30):
            raise ValueError('TLS handshake timeout must be between 0.1 and 30 seconds')
        if type(self.max_handshakes) is not int or not 1 <= self.max_handshakes <= 8:
            raise ValueError('TLS max_handshakes must be an integer between 1 and 8')
        if self.enabled and (self.certificate is None or self.private_key is None):
            raise ValueError('Enabled TLS requires certificate and private_key')
        if self.launch_manifests is not None and (not self.enabled or not isinstance(self.launch_manifests,Path)):
            raise ValueError('Launcher admission requires TLS and a manifest directory')


@dataclass(frozen=True)
class ServerConfig:
    bind_address: str
    advertised_address: str
    game_port: int
    data_directory: Path
    log_level: str
    multi_account: bool = False
    session_port: int = 28513
    tls: TLSConfig = TLSConfig()
    contracts_enabled: bool = False

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        with path.open('rb') as stream:
            data = tomllib.load(stream)
        required = {'bind_address', 'advertised_address', 'game_port', 'data_directory', 'log_level'}
        if not required <= set(data) or set(data)-required-{'multi_account','session_port','tls','contracts_enabled'}:
            raise ValueError('Invalid configuration keys; required: ' + ', '.join(sorted(required)))
        bind = IPv4Address(data['bind_address'])
        advertised = IPv4Address(data['advertised_address'])
        if bind.is_multicast or advertised.is_multicast or advertised.is_unspecified or int(advertised) == 0xffffffff:
            raise ValueError('Expected unicast advertised IPv4 and a valid IPv4 bind address')
        if not bind.is_loopback and advertised.is_loopback:
            raise ValueError('External bind requires a non-loopback advertised_address')
        port = data['game_port']
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('game_port must be an integer between 1024 and 65535')
        directory = data['data_directory']
        if not isinstance(directory, str) or not directory.strip():
            raise ValueError('data_directory must be a nonempty path')
        directory = Path(directory).expanduser()
        if not directory.is_absolute():
            directory = path.parent / directory
        level = data['log_level']
        if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
            raise ValueError('Invalid log_level')
        multi = data.get('multi_account', False)
        session_port = data.get('session_port', 28513)
        if type(multi) is not bool or type(session_port) is not int or not 1024 <= session_port <= 65535:
            raise ValueError('Invalid multi_account/session_port setting')
        if multi and session_port == port:raise ValueError('Login and session ports must differ')
        tls = TLSConfig.load(data.get('tls', {}), path.parent)
        contracts = data.get('contracts_enabled', False)
        if type(contracts) is not bool or contracts and not multi:
            raise ValueError('contracts_enabled must be boolean and requires multi_account')
        if tls.enabled:
            if not multi:raise ValueError('TLS requires multi_account = true')
            if len({port, session_port, tls.login_port, tls.session_port}) != 4:
                raise ValueError('Direct and TLS listener ports must all differ')
        return cls(str(bind), str(advertised), port, directory.resolve(), level, multi, session_port, tls, contracts)

    @property
    def database(self):
        return self.data_directory / 'reservation.sqlite3'
