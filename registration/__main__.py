import os
from pathlib import Path
from waitress import serve
from server.config import ServerConfig
from .app import create_app

config = ServerConfig.load(os.environ.get('TIO_CONFIG', '/etc/tio-server/server.toml'))
if not config.multi_account:
    raise ValueError('Self-registration requires multi_account=true')
secret = Path(os.environ['TIO_WEB_SECRET_FILE']).read_text().strip()
app = create_app(config.database, secret, os.environ['TIO_WEB_ORIGIN'])
serve(app, listen='127.0.0.1:8080', threads=2, connection_limit=32,
      channel_timeout=20, max_request_body_size=4096,
      trusted_proxy='127.0.0.1', trusted_proxy_count=1,
      trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto'},
      clear_untrusted_proxy_headers=True)
