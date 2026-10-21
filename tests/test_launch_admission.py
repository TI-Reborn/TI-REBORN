"""Current publication identity, bounded reads and official-launcher admission."""
import hashlib,json,socket,struct,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from server.tls import read_bridge_preface,validate_launch_identity

class LaunchAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        for d in ('updates','downloads'):(self.root/d).mkdir()
        self.raw=b'{"version":"test-v1","files":[]}'
        (self.root/'updates/manifest.json').write_bytes(self.raw)
        (self.root/'downloads/launcher-manifest.json').write_text(json.dumps(dict(version='0.1.24')))
        self.identity=hashlib.sha256(self.raw).digest()+struct.pack('!HHH',0,1,24)
    def read(self,raw,policy=True):
        a,b=socket.socketpair();self.addCleanup(a.close);self.addCleanup(b.close)
        b.sendall(raw);b.shutdown(socket.SHUT_WR)
        return read_bridge_preface(a,time.monotonic()+1,self.root if policy else None)
    def test_current_identity_and_language(self):
        result=self.read(struct.pack('!4sBBH',b'TIOT',2,1,31001)+self.identity)
        self.assertEqual(result,31001);self.assertEqual(result.language,'english')
    def test_legacy_allowed_only_when_policy_not_configured(self):
        old=struct.pack('!4sBBH',b'TIOT',1,0,31001)
        self.assertEqual(self.read(old,False),31001)
        with self.assertRaises(ValueError):self.read(old)
    def test_old_client_or_launcher_rejected(self):
        for identity in (bytes(32)+self.identity[32:],self.identity[:32]+struct.pack('!HHH',0,1,22)):
            with self.assertRaises(ValueError):validate_launch_identity(identity,self.root)
    def test_later_publication_invalidates_previous_start_identity(self):
        validate_launch_identity(self.identity,self.root)
        (self.root/'updates/manifest.json').write_bytes(b'{"version":"test-v2","files":[]}')
        with self.assertRaises(ValueError):validate_launch_identity(self.identity,self.root)
    def test_launcher_publication_invalidates_previous_launcher(self):
        (self.root/'downloads/launcher-manifest.json').write_text('{"version":"0.1.25"}')
        with self.assertRaises(ValueError):validate_launch_identity(self.identity,self.root)
    def test_truncated_or_malformed_frames_rejected(self):
        valid=struct.pack('!4sBBH',b'TIOT',2,0,31001)+self.identity
        for raw in (valid[:7],valid[:-1],b'BAD!'+valid[4:],valid[:5]+b'\x02'+valid[6:],valid[:6]+b'\0\0'+valid[8:]):
            with self.assertRaises((ValueError,EOFError)):self.read(raw)
    def test_payload_is_left_for_native_transport(self):
        a,b=socket.socketpair();self.addCleanup(a.close);self.addCleanup(b.close)
        b.sendall(struct.pack('!4sBBH',b'TIOT',2,0,31001)+self.identity+b'ORANGE')
        self.assertEqual(read_bridge_preface(a,time.monotonic()+1,self.root),31001)
        self.assertEqual(a.recv(6),b'ORANGE')
    def test_missing_policy_file_fails_closed(self):
        (self.root/'downloads/launcher-manifest.json').unlink()
        with self.assertRaises(OSError):validate_launch_identity(self.identity,self.root)

    def test_actual_tls_two_accounts_and_both_routes_require_current_release(self):
        import test_game_tls as fixture
        from tls_test_certificates import create
        from unittest.mock import patch
        certificates=self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(fixture,'FIXTURES',create(certificates)))
        tls=fixture.GameTLSTests();tls.setUp();self.addCleanup(tls.doCleanups)
        tls.case.config=replace(tls.case.config,bind_address='0.0.0.0',tls=replace(tls.case.config.tls,launch_manifests=self.root))
        original=tls.connect
        def connect(kind,*,preface=None,context=None):
            port=int.from_bytes(preface[6:8],'big') if preface else 31001
            language=preface[5] if preface else 0
            c=original(kind,context=context)
            c.sendall(struct.pack('!4sBBH',b'TIOT',2,language,port)+self.identity)
            return c
        tls.connect=connect;tls.case.start()
        self.assertEqual(tls.case.server.listener.getsockname()[0],'127.0.0.1')
        # Legacy login and legacy session routes receive no native challenge.
        for kind in ('login','session'):
            c=original(kind,preface=struct.pack('!4sBBH',b'TIOT',1,0,31001) if kind=='login' else None)
            if kind=='session':c.sendall(b'old-mode1')
            try:self.assertEqual(c.recv(1),b'')
            except (ConnectionResetError,ConnectionAbortedError):pass
        a=tls.handoff(tls.begin('alice',31001));tls.case.enter(a,'Alice')
        b=tls.handoff(tls.begin('bob',31002,language='english'));tls.case.enter(b,'Bob')
        tls.case.ping(a);tls.case.ping(b)
        self.assertEqual(tls.case.server.multi.server_population()[0],2)

if __name__=='__main__':unittest.main()
