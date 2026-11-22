"""Publish the HD Reservation steel fences with doors (2026.11.14.10 -> 2026.11.14.11).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 4 new .hd
records: rveel_fence_02*, rveel_fence_02b* sheets and their doors.

Usage: python tools/publish_hd_map_batch7_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch7-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch7-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.10', '2026.11.14.11'
    publisher.MANIFEST_SHA = '93afc3fce97c77074878118190c33c6eed658ccc33f2a260aa794b3cf5aedfc1'
    publisher.EXPECTED_FILES = 193
    publisher.EXPECTED_CHANGES = 4
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch7-20261114.zip'
    publisher.main()
