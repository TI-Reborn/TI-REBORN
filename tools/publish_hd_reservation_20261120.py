"""Publish the reviewed Reservation 2x texture set for launcher 0.1.60."""
import json
from pathlib import Path
import sys
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402
from tools.build_hd_map_textures import HD_PREFIX, HD_SUFFIX, RESERVATION_GROUND, RESERVATION_PREFIX, hd_path  # noqa: E402


if __name__ == '__main__':
    publisher.OUT = ROOT / 'work/hd-upscale-reservation-20261120'
    publisher.BUILD = publisher.OUT / 'atlases'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.20.4', '2026.11.20.5'
    publisher.MANIFEST_SHA = 'f38514b4c6b904e66c1459c2ac33f3b022a17dc00640c949f58298fb76df79ac'
    publisher.EXPECTED_FILES = publisher.EXPECTED_CHANGES = 85
    publisher.REMOTE_PACKAGE = '/root/tio-reservation-2x-20261120.zip'
    manifest = json.loads((publisher.OUT / 'manifest-before.json').read_bytes())
    prefix = HD_PREFIX + RESERVATION_PREFIX.removeprefix('base/')
    sources = {'base/' + row['path'].removeprefix(HD_PREFIX).removesuffix(HD_SUFFIX)
               for row in manifest['files'] if row['path'].startswith(prefix) and row['path'].endswith(HD_SUFFIX)}
    publisher.DOUBLE_DENSITY_SHEETS = frozenset(sources | RESERVATION_GROUND.keys())
    publisher.EXPECTED_PATHS = {hd_path(path, output_scale=2) for path in publisher.DOUBLE_DENSITY_SHEETS}
    if sys.argv[1:] == ['apply']:
        launcher = json.loads(publisher.fetch(urljoin(publisher.ORIGINS[1], '/downloads/launcher-manifest.json')))
        if (launcher['version'], launcher['sha256']) != (
            '0.1.60', '7bf28911e01af2c4add223543d3bcc0fc29c09877b24794f01565ebda755090a'
        ):
            raise RuntimeError('Hosted launcher differs from the tested double-density release')
    publisher.main()
