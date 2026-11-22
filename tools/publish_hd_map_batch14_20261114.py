"""Publish the HD mine floor (2026.11.14.17 -> 2026.11.14.18).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 1 new .hd
record: mines/mine_ground.png (seamless dirt with pebbles and coal crumbs).

Usage: python tools/publish_hd_map_batch14_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch14-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch14-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.17', '2026.11.14.18'
    publisher.MANIFEST_SHA = 'c54cdbe2447d88fec11e01535b875af65ae35d9045d34aa782d40d901d3472d6'
    publisher.EXPECTED_FILES = 211
    publisher.EXPECTED_CHANGES = 1
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch14-20261114.zip'
    publisher.main()
