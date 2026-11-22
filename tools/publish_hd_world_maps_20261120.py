"""Publish the reviewed world map HD art."""
import json
from pathlib import Path
import sys
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402
from tools.build_hd_map_textures import hd_path  # noqa: E402


if __name__ == '__main__':
    work = ROOT / 'work/hd-upscale-client-20261120'
    publisher.OUT = work
    publisher.BUILD = work / 'map-atlases'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.20.5', '2026.11.20.6'
    publisher.MANIFEST_SHA = '10501f7f880802a360e4f00ba647db6f83afa987fdf1f4a2cb122d370233a609'
    publisher.EXPECTED_FILES = publisher.EXPECTED_CHANGES = 158
    publisher.REMOTE_PACKAGE = '/dev/shm/tio-world-map-2x-20261120.zip'
    selection = (work / 'authored-map-paths.json').read_bytes()
    selection_sha = 'c9e9329c65a618c7d48d84bb00560f9b6e5e787d3494f3feff4d09e107899c71'
    if publisher.sha(selection) != selection_sha:
        raise ValueError('The reviewed source list changed')
    publisher.DOUBLE_DENSITY_SHEETS = frozenset(json.loads(selection))
    publisher.EXPECTED_PATHS = {hd_path(path, output_scale=2) for path in publisher.DOUBLE_DENSITY_SHEETS}
    if sys.argv[1:] == ['apply']:
        launcher = json.loads(publisher.fetch(urljoin(publisher.ORIGINS[1], '/downloads/launcher-manifest.json')))
        if (launcher['version'], launcher['sha256']) != (
            '0.1.60', '7bf28911e01af2c4add223543d3bcc0fc29c09877b24794f01565ebda755090a'
        ):
            raise RuntimeError('Hosted launcher differs from the tested double-density release')
    publisher.main()
