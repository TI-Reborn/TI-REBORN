"""Publish the HD mine walls (2026.11.14.18 -> 2026.11.15.1).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 2 new .hd
records: mines/walls/walls_v00.png and walls_v01.png (30 wall tiles).

Usage: python tools/publish_hd_map_batch15_20261115.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch15-20261115'
    publisher.BUILD = ROOT/'work/hd-map-batch15-20261115/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.18', '2026.11.15.1'
    publisher.MANIFEST_SHA = '40254e6dc1938f59a597c056a53829b784090df88ed961e05db2ea39025ab718'
    publisher.EXPECTED_FILES = 213
    publisher.EXPECTED_CHANGES = 2
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch15-20261115.zip'
    publisher.main()
