"""Publish the HD Reservation army cargo trucks (2026.11.14.12 -> 2026.11.14.13).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 2 .hd
records: rvmy_car_01a and rvmy_car_01b (truck frames; the jeep frames stay the client's).

Usage: python tools/publish_hd_map_batch9_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch9-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch9-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.12', '2026.11.14.13'
    publisher.MANIFEST_SHA = '83f5126459c0bb99016cb8c8fcc21c501a37d22f0e07907a134e5cb2925c8532'
    publisher.EXPECTED_FILES = 195
    publisher.EXPECTED_CHANGES = 2
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch9-20261114.zip'
    publisher.main()
