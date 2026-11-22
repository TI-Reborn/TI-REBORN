"""Publish the mine rails without their grey gravel bed (2026.11.15.1 -> 2026.11.15.2).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 1 replaced
.hd record: mines/rails/mine_rails_v01.png (the track lies on the mine floor).

Usage: python tools/publish_hd_map_batch16_20261115.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch16-20261115'
    publisher.BUILD = ROOT/'work/hd-map-batch16-20261115/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.15.1', '2026.11.15.2'
    publisher.MANIFEST_SHA = '41e28dc5d6d1d65da2872911d08b37b0af9572638553bf893945619653ff906a'
    publisher.EXPECTED_FILES = 213
    publisher.EXPECTED_CHANGES = 1
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch16-20261115.zip'
    publisher.main()
