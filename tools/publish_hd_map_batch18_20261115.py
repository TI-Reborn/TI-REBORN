"""Publish the HD forest bushes (2026.11.15.3 -> 2026.11.15.4).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 1 new .hd
record: forest/forest_tree/forest_bush_v1.png (forest_bush_v1-v3.t).

Usage: python tools/publish_hd_map_batch18_20261115.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch18-20261115'
    publisher.BUILD = ROOT/'work/hd-map-batch18-20261115/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.15.3', '2026.11.15.4'
    publisher.MANIFEST_SHA = '9601b4cb7fee89c1869e6b11d585293b86e5ae8f51cb68242b06f3586be50936'
    publisher.EXPECTED_FILES = 226
    publisher.EXPECTED_CHANGES = 1
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch18-20261115.zip'
    publisher.main()
