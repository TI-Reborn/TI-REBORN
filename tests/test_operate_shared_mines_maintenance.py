"""Operator proof routing only: no SSH, firewall, server or real socket binding."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch,MagicMock

from tools import operate_shared_mines_maintenance as operate


class MaintenanceOperatorArgumentsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.folder=self.root/'reports'/'shared-mines';self.folder.mkdir(parents=True)
        tools=self.root/'tools';tools.mkdir();(tools/'shared_mines_maintenance.py').write_bytes(b'public reviewed helper fixture')
        self.old=dict(prepared_local_only=True,passed=True,accounts=['oldqaa','oldqab','oldqac'])
        self.new=dict(prepared_local_only=True,passed=True,accounts=['newqaa','newqab','newqac'])
        (self.folder/'owned-prepare.json').write_text(json.dumps(self.old))
        self.public=self.folder/'post-fix-owned-prepare.json';self.public.write_text(json.dumps(self.new))

    def invoke(self,extra=()):
        target=self.folder/'post-fix-maintenance-proof.json'
        with patch.object(operate,'ROOT',self.root),patch.object(operate,'FOLDER',self.folder),\
             patch('sys.argv',['maintenance','activate','--output',str(target),*extra]),\
             patch('socket.socket',return_value=MagicMock()) as sockets,\
             patch.object(operate,'remote',return_value=dict(status='isolated',deadline_utc='fixture')) as remote,\
             redirect_stdout(io.StringIO()):
            operate.main()
        return remote.call_args.args[1],target,sockets

    def test_default_public_preparation_keeps_existing_accounts_contract(self):
        payload,_,sockets=self.invoke()
        self.assertEqual(payload['accounts'],self.old['accounts']);self.assertEqual(sockets.call_count,2)

    def test_explicit_public_preparation_selects_second_trio_without_overwriting_old(self):
        old=(self.folder/'owned-prepare.json').read_bytes()
        payload,target,_=self.invoke(['--prepare-proof',str(self.public)])
        self.assertEqual(payload['accounts'],self.new['accounts']);self.assertTrue(target.is_file())
        self.assertEqual((self.folder/'owned-prepare.json').read_bytes(),old)

    def test_outside_preparation_rejected_before_forward_or_remote_action(self):
        outside=self.root/'private.json';outside.write_text(json.dumps(self.new))
        with patch.object(operate,'ROOT',self.root),patch.object(operate,'FOLDER',self.folder),\
             patch('sys.argv',['maintenance','activate','--output',str(self.folder/'fresh.json'),'--prepare-proof',str(outside)]),\
             patch('socket.socket') as sockets,patch.object(operate,'remote') as remote,\
             patch('sys.stderr',new=io.StringIO()):
            with self.assertRaises(SystemExit) as error:operate.main()
            self.assertEqual(error.exception.code,2);sockets.assert_not_called();remote.assert_not_called()


if __name__=='__main__':unittest.main()
