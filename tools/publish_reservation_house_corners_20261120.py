"""Publish the two corrected corner frames of the HD Reservation house."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher
from tools.build_hd_map_textures import hd_path

if __name__ == '__main__':
    source = 'base/setting/reservation_v2/rvhouse01_slice3.png'
    publisher.OUT = ROOT / 'work/reservation-house-corners-20261120'
    publisher.BUILD = publisher.OUT / 'atlases'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.20.17', '2026.11.20.18'
    publisher.MANIFEST_SHA = '7041b07070ff512b0775ffbd7a4a0d929c1e7e174f3ef287decb95d6039af379'
    publisher.EXPECTED_FILES = publisher.EXPECTED_CHANGES = 2
    publisher.EXPECTED_PATHS = {hd_path(source, output_scale=scale) for scale in (1, 2)}
    publisher.DOUBLE_DENSITY_SHEETS = frozenset({source})
    publisher.REMOTE_PACKAGE = '/dev/shm/tio-reservation-house-corners-20261120.zip'
    publisher.main()
