"""Publish the mine menu fix through the existing guarded client publisher."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy.client_mine_menu_exit import patch, SOURCE_SHA
from tools import publish_player_feedback_20261104 as publisher


if __name__ == '__main__':
    publisher.patch = patch
    publisher.SOURCE_SHA = SOURCE_SHA
    publisher.OUT = ROOT / 'reports/mine-menu-client-20261117'
    publisher.VERSION = '2026.11.17.3'
    publisher.main()
