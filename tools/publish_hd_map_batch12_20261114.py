"""Publish the HD pipe elbows and the second Reservation straight pipe (2026.11.14.15 -> 2026.11.14.16).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 2 .hd
records, both replaced: metal_pipe.png (elbow lies on its side, frame 3
added) and rvtal_pipe.png (rvtal_pipe_01b, rvtal_pipe_02 and 02b added).

Usage: python tools/publish_hd_map_batch12_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch12-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch12-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.15', '2026.11.14.16'
    publisher.MANIFEST_SHA = '93c99b2f4308bb3387bd587775488a9c5f1eb72c5d03051048461563fb90501f'
    publisher.EXPECTED_FILES = 197
    publisher.EXPECTED_CHANGES = 2
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch12-20261114.zip'
    publisher.main()
