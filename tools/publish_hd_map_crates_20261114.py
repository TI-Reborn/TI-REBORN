"""Publish the opened / enlarged loot-crate HD sheets (2026.11.14.4 -> 2026.11.14.5).

Same guarded path as tools/publish_hd_map_textures_20261114.py; only the three
crate .hd records change (military steel_box_01, Reservation rveel_box_01/01b).

Usage: python tools/publish_hd_map_crates_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-crates-20261114'
    publisher.BUILD = ROOT/'work/hd-map-crates-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.4', '2026.11.14.5'
    publisher.MANIFEST_SHA = '022c48c50da2de56bdaa95631d851db246abfa963d367e6e40cf0e1072c91e98'
    publisher.EXPECTED_CHANGES = 3
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-crates-20261114.zip'
    publisher.main()
