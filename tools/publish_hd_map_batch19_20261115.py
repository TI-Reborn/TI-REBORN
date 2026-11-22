"""Publish the HD forest houses (2026.11.15.4 -> 2026.11.15.5).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 8 new .hd
records: forest_house01_a-e.png (log cabin) and forest_house_02a-c.png (plank house).

Usage: python tools/publish_hd_map_batch19_20261115.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch19-20261115'
    publisher.BUILD = ROOT/'work/hd-map-batch19-20261115/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.15.4', '2026.11.15.5'
    publisher.MANIFEST_SHA = 'dd82a14745053b688f7ce2ecaa8aca471f9ef8e2b003e4f0fa2f2151299a0d49'
    publisher.EXPECTED_FILES = 234
    publisher.EXPECTED_CHANGES = 8
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch19-20261115.zip'
    publisher.main()
