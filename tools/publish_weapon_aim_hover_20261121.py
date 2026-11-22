"""Publish the reviewed hover animation over the hosted Shooting Range update."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy.client_weapon_aim_hover import SHOOTING_RANGE_AP_SHA, patch
from tools import publish_player_feedback_20261104 as publisher


if __name__ == '__main__':
    publisher.OUT = ROOT / 'work/weapon-aim-hover-20261121/release'
    publisher.VERSION = '2026.11.21.89'
    publisher.SOURCE_SHA = SHOOTING_RANGE_AP_SHA
    publisher.patch = patch
    publisher.main()
