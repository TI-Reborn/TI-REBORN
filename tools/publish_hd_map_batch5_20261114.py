"""Publish the HD Reservation brick house and the fixed container shadows (2026.11.14.8 -> 2026.11.14.9).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 11 .hd records:
seven new rvhouse01_* sheets and the four container sheets re-rendered without
their labels leaking into the shadow layer.

Usage: python tools/publish_hd_map_batch5_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch5-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch5-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.8', '2026.11.14.9'
    publisher.MANIFEST_SHA = 'b79050430821ddb09dc148cbebeac451ebea956c92abed69b8ad81f66d540420'
    publisher.EXPECTED_FILES = 189
    publisher.EXPECTED_CHANGES = 11
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch5-20261114.zip'
    publisher.main()
