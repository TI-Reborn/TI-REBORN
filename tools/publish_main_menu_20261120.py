"""Publish the reviewed Main menu fix with the existing client safeguards."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy.client_main_menu import patch, SOURCE_SHA
from tools import publish_player_feedback_20261104 as publisher


if __name__ == '__main__':
    publisher.patch = patch
    publisher.SOURCE_SHA = SOURCE_SHA
    publisher.OUT = ROOT / 'reports/main-menu-20261119'
    publisher.VERSION = '2026.11.20.2'
    publisher.main()
