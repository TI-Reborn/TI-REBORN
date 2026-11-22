"""Publish the military twins of the finished Reservation props (2026.11.14.16 -> 2026.11.14.17).

Same guarded path as tools/publish_hd_map_textures_20261114.py; 16 .hd
records: 13 new (M_House01 slices and doors, army_car_01a/01b, oil_tank_01/01b,
steel_fence_02b and its door) and 3 replaced (wire_fence_01/01b/01c gain the
gate, end and sign frames).

Usage: python tools/publish_hd_map_batch13_20261114.py {inspect|apply|verify}
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher  # noqa: E402

if __name__ == '__main__':
    publisher.OUT = ROOT/'reports/hd-map-batch13-20261114'
    publisher.BUILD = ROOT/'work/hd-map-batch13-20261114/out'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.14.16', '2026.11.14.17'
    publisher.MANIFEST_SHA = '5c893aeb9e0a2c73bb5251204a167df47b51771897c54a5f6e59d35afcf96b7c'
    publisher.EXPECTED_FILES = 210
    publisher.EXPECTED_CHANGES = 16
    publisher.REMOTE_PACKAGE = '/root/tio-hd-map-batch13-20261114.zip'
    publisher.main()
