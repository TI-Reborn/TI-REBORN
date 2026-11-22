"""Publish the HD Reservation army jeeps (2026.11.14.13 -> 2026.11.14.14).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 2 .hd
records: rvmy_car_01a and rvmy_car_01b, now with the jeep frames too.

Usage: python tools/publish_hd_map_batch10_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch10-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch10-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.13', '2026.11.14.14'
    publisher.MANIFEST_SHA = '3669ae432be988179875eb79b91b7fef429f92dcb3c2276244648096e7658495'
    publisher.EXPECTED_FILES = 195
    publisher.EXPECTED_CHANGES = 2
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch10-20261114.zip'
    publisher.main()
