"""Publish see-through windows for the HD Reservation house (2026.11.14.9 -> 2026.11.14.10).

Same guarded path as tools/publish_hd_map_textures_20261114.py; the seven
rvhouse01_* .hd records: window openings, interior plaster, lighter floor.

Usage: python tools/publish_hd_map_batch6_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch6-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch6-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.9', '2026.11.14.10'
    publisher.MANIFEST_SHA = 'f19756aecc28d3ea186bd678ac445bec1bf39f70f2b3799a3c712a7f9e6135ad'
    publisher.EXPECTED_FILES = 189
    publisher.EXPECTED_CHANGES = 7
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch6-20261114.zip'
    publisher.main()
