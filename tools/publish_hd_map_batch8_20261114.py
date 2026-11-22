"""Publish the HD Reservation wire fences and fence signs (2026.11.14.11 -> 2026.11.14.12).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 3 .hd
records: rvre_fence_01 (signs), rvre_fence_01b and rvre_fence_01c sheets.

Usage: python tools/publish_hd_map_batch8_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch8-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch8-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.11', '2026.11.14.12'
    publisher.MANIFEST_SHA = '7965f1019b448f42609b3292bcf2ebfddb07ebbd3e9dda7a37f4fe5525a04e2d'
    publisher.EXPECTED_FILES = 193
    publisher.EXPECTED_CHANGES = 3
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch8-20261114.zip'
    publisher.main()
