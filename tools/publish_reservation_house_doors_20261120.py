"""Publish the corrected Reservation house atlases at both HD densities."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_hd_map_textures_20261114 as publisher
from tools.build_hd_map_textures import hd_path

if __name__ == '__main__':
    sources = frozenset(f'base/setting/reservation_v2/rvhouse01_{sheet}.png'
                        for sheet in ('door1', 'door2', 'slice1', 'slice2', 'slice3'))
    publisher.OUT = ROOT / 'work/reservation-house-door-20261120'
    publisher.BUILD = publisher.OUT / 'atlases'
    publisher.PREVIOUS_VERSION, publisher.VERSION = '2026.11.20.16', '2026.11.20.17'
    publisher.MANIFEST_SHA = 'bb904a752ce584855fe4bf80fbdf5e61a17c8bf070fc0c43842a6b748495a91c'
    publisher.EXPECTED_FILES = publisher.EXPECTED_CHANGES = 10
    publisher.EXPECTED_PATHS = {hd_path(path, output_scale=scale) for path in sources for scale in (1, 2)}
    publisher.DOUBLE_DENSITY_SHEETS = sources
    publisher.REMOTE_PACKAGE = '/dev/shm/tio-reservation-house-door-20261120.zip'
    publisher.main()
