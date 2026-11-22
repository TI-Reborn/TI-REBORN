"""Publish the HD deck tents, Reservation rvnt and military tent (2026.11.14.6 -> 2026.11.14.7).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 8 new .hd
records (military tent_slice_0..3, Reservation rvnt_slice_0..3).

Usage: python tools/publish_hd_map_batch4_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch4-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch4-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.6', '2026.11.14.7'
    publisher.MANIFEST_SHA = '8ff2b3ac091d8463cb868833a62decbe2b1165a5dae18b6f519ba5263e5535a1'
    publisher.EXPECTED_FILES = 182
    publisher.EXPECTED_CHANGES = 8
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch4-20261114.zip'
    publisher.main()
