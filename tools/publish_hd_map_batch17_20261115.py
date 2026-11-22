"""Publish the HD forest firs and their biome recolours (2026.11.15.2 -> 2026.11.15.3).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 12 new .hd
records: forest_tree_v1-v3 and autfor/ashfor/wetfor_tree_v1-v3.

Usage: python tools/publish_hd_map_batch17_20261115.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch17-20261115'
    publisher.BUILD = ROOT/'work/hd-map-batch17-20261115/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.15.2', '2026.11.15.3'
    publisher.MANIFEST_SHA = '93e912e7dbef04bfae941734f0429f2ed6f236c81db5add5e8c3c9984d515818'
    publisher.EXPECTED_FILES = 225
    publisher.EXPECTED_CHANGES = 12
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch17-20261115.zip'
    publisher.main()
