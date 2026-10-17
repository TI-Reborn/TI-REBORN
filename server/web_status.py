"""Publish only aggregate runtime state for the private website adapter."""
import json
import logging
import os
from pathlib import Path
import tempfile
import time

LOG = logging.getLogger('tio.server')


class StatusPublisher:
    def __init__(self, default_path):
        self.path = Path(os.environ.get('TIO_WEB_STATUS_FILE', str(default_path)))
        self.version = os.environ.get('TIO_GAME_VERSION', 'unknown')

    def publish(self, population=None, *, status='online'):
        """Atomic heartbeat; a failed website status write never stops gameplay."""
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            players, capacity = population if population is not None else (None, None)
            snapshot = dict(status=status, playersOnline=players, maxPlayers=capacity,
                            serverVersion=self.version, observedAt=time.time())
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    dir=self.path.parent, prefix='.web-status-', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(snapshot, stream, ensure_ascii=False, separators=(',', ':'))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o640)
            os.replace(temporary, self.path)
        except OSError:
            LOG.warning('Website runtime status snapshot unavailable')
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
