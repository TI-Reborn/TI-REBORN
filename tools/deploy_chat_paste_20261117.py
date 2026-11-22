"""Deploy the chat paste fix with the established data-preserving guards."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployment

deployment.WORK = ROOT / 'work/chat-paste-20261117'
deployment.OUT = ROOT / 'reports/chat-paste-20261117'
deployment.SCOPE = 'chat-paste-20261117'
deployment.TEMPLATE = deployment.TEMPLATE.replace('20261018', '20261117')
deployment.FILES = ('tio/protocol/chat.py', 'tools/loopback_exchange.py')
deployment.MODULES = ['test_chat_paste', 'test_presence',
    'test_contracts_service.ContractsServiceTests.test_commands_private_invitation_consent_and_frozen_edits',
    'test_multi_account.MultiAccountTests.test_private_chat_waits_for_town_after_battle']

if __name__ == '__main__':
    deployment.main()
