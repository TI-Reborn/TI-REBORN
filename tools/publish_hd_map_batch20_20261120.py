"""Publish the HD village barrack house (2026.11.19.3 -> 2026.11.20.1).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 7 new .hd
records: village_house_02 walls, doors and floor (its roof stays client art).

Usage: python tools/publish_hd_map_batch20_20261120.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch20-20261120'
    publisher.BUILD = ROOT/'work/hd-map-batch20-20261120/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.19.3', '2026.11.20.1'
    publisher.MANIFEST_SHA = '12c782ac6ea93f4cb6cdfd2bda0194f90062c002d37a81e91ebcd87c62bb83da'
    publisher.EXPECTED_FILES = 241
    publisher.EXPECTED_CHANGES = 7
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch20-20261120.zip'
    publisher.main()
