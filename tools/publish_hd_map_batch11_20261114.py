"""Publish the HD Reservation fuel tanks (2026.11.14.14 -> 2026.11.14.15).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 2 .hd
records, both new: rvl_tank_01 and rvl_tank_01b.

Usage: python tools/publish_hd_map_batch11_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch11-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch11-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.14', '2026.11.14.15'
    publisher.MANIFEST_SHA = 'f6d22707786b70f745645a6c6f63e425bcdb7852912a543f7278c463138181a4'
    publisher.EXPECTED_FILES = 197
    publisher.EXPECTED_CHANGES = 2
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch11-20261114.zip'
    publisher.main()
