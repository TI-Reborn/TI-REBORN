"""Publish HD containers and the Reservation hangar / water tower (2026.11.14.5 -> 2026.11.14.6).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 15 new .hd
records (military containers 04-07, Reservation rvngar_* and rvter_tower_*).

Usage: python tools/publish_hd_map_batch3_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch3-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch3-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.5', '2026.11.14.6'
    publisher.MANIFEST_SHA = '16ebb13a2ab9fabf137bd4153d809a47bbeef88f041e6437c65c675067c8b097'
    publisher.EXPECTED_FILES = 174
    publisher.EXPECTED_CHANGES = 15
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch3-20261114.zip'
    publisher.main()
