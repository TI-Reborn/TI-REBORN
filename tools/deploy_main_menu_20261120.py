"""Deploy character selection on the authenticated game connection."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import deploy_player_feedback_20261104 as deployment


if __name__ == '__main__':
    deployment.WORK = ROOT / 'work/main-menu-switch-20261120'
    deployment.OUT = ROOT / 'reports/main-menu-20261119'
    deployment.SCOPE = 'main-menu-character-select-20261120'
    deployment.FILES = ('server/multi.py', 'tools/loopback_exchange.py',
                        'tio/protocol/character_select.py')
    deployment.MODULES = [
        'test_character_slots',
        'test_multi_account.MultiAccountTests.test_bad_password_duplicate_login_and_reconnect_do_not_affect_other_player',
        'test_multi_account.MultiAccountTests.test_update_disconnect_reaches_world_and_character_selection_before_eof',
        'test_multi_account.MultiAccountTests.test_normal_stop_does_not_send_update_disconnect',
    ]
    deployment.main()
