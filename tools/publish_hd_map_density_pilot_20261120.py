"""Publish the two reviewed double-density atlas files after launcher 0.1.60."""
import json
from pathlib import Path
import sys
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402


if __name__ == '__main__':
    publisher.OUT = ROOT / 'work/hd-upscale-pilot-20261120'
    publisher.BUILD = publisher.OUT / 'atlases'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.20.2', '2026.11.20.3'
    publisher.MANIFEST_SHA = 'c57661feeb68dc537bf69381bf175afcb9936536d4da35bf4dca42fd305718ec'
    publisher.EXPECTED_FILES = publisher.EXPECTED_CHANGES = 2
    publisher.REMOTE_PACKAGE = '/root/tio-hd-density-pilot-20261120.zip'
    if len(sys.argv) == 2 and sys.argv[1] == 'apply':
        launcher = json.loads(publisher.fetch(urljoin(publisher.ORIGINS[1], '/downloads/launcher-manifest.json')))
        expected = json.loads((publisher.OUT / 'launcher-publication/package.json').read_bytes())
        if any(launcher[key] != expected[key] for key in ('version', 'sha256', 'size')):
            raise RuntimeError('The tested 2x HD launcher must be published first')
    publisher.main()
