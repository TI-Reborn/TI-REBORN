"""Publish the verified native HUD portrait sizing follow-up."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_player_feedback_20261104 as publisher
from deploy.client_battle_portrait_size_20261105 import patch, SOURCE_SHA

if __name__ == '__main__':
    publisher.patch = patch
    publisher.SOURCE_SHA = SOURCE_SHA
    publisher.VERSION = '2026.11.05.2'
    publisher.OUT = ROOT/'reports/player-feedback-20261104/battle-portraits'
    publisher.main()
