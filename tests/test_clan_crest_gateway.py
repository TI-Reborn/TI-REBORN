from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import hashlib,importlib.util,sqlite3,struct,tempfile,unittest

from server.accounts import Accounts
from tio.character_identity import initialise,alias
from tio.clans import schema,CREST
from tio.clan_benefits import schema as benefits_schema
from tio.db_transaction import transaction
from tio.alliances import AlliancesStore

AVAILABLE=importlib.util.find_spec('flask') is not None
if AVAILABLE:from server.bank_gateway import create_app


def bmp(color=7):
    return b'BM'+struct.pack('<III',822,0,54)+struct.pack('<IiiHHIIiiII',40,16,16,1,24,0,768,0,0,0,0)+bytes([color])*768


@unittest.skipUnless(AVAILABLE,'Flask gateway runtime')
class ClanCrestGatewayTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'players.db'
        for name in ('alice','bob'):Accounts(self.path).create(name,'FixturePassword123!',character=name.title())
        Accounts(self.path).create('newplayer','FixturePassword123!')
        self.owner=alias('alice',2)
        with transaction(self.path) as db:
            initialise(db);schema(db);benefits_schema(db)
            db.execute('INSERT INTO character_identities VALUES (?,2,?)',('alice',self.owner))
            db.execute('INSERT INTO characters VALUES (?,1,?,?,?)',(self.owner,b'AliceTwo','alicetwo',b'fixture'))
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER)')
            db.executemany('INSERT INTO wallets VALUES (?,3000,0)',(('alice',),('bob',),(self.owner,)))
            db.execute('INSERT INTO clans(id,name,name_key,leader) VALUES (1,?,?,?)',(b'Alpha','alpha','bob'))
            db.executemany('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,1,?)',((self.owner,CREST),('bob',0)))
        self.key='fixture_bank_private_service_key_64_chars_only';self.app=create_app(self.path,self.key);self.client=self.app.test_client()

    def read(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def upload(self,*,client=None,username='alice',slot='2',operation='fixture-crest-request-0001',raw=None,auth=True,remote='127.0.0.1',kind='clan',remove='0'):
        return (client or self.client).post('/v1/clan/crest',data=bmp() if raw is None else raw,headers={'Content-Type':'image/bmp','X-Game-Username':username,'X-Character-Slot':slot,'X-Request-ID':operation,'X-Crest-Kind':kind,'X-Crest-Remove':remove,**({'Authorization':'Bearer '+self.key} if auth else {})},environ_overrides={'REMOTE_ADDR':remote})

    def alliance(self):
        current=AlliancesStore(self.path)
        with transaction(self.path) as db:db.execute('UPDATE clans SET level=1,credits=50000,influence=10000 WHERE id=1')
        return current.create('bob',b'Alliance One')

    def test_owned_slot_status_no_mutation_or_internal_account(self):
        before=self.path.read_bytes()
        result=self.client.post('/v1/clan/status',json=dict(username='alice',slot=2),headers={'Authorization':'Bearer '+self.key})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json['clan'],dict(id=1,name='Alpha',crestId=0));self.assertTrue(result.json['canUpload'])
        self.assertEqual(result.json['character'],'AliceTwo');self.assertNotIn(self.owner,result.text);self.assertNotIn(self.key,result.text)
        self.assertEqual(self.path.read_bytes(),before)

    def test_real_slot_rights_cost_reconnect_receipt_and_identical_image_no_charge(self):
        first=self.upload();self.assertEqual(first.status_code,200);self.assertEqual(first.json['receipt'],dict(crestId=1,charged=1000));self.assertEqual(first.json['credits'],2000)
        restarted=create_app(self.path,self.key).test_client();again=self.upload(client=restarted)
        self.assertEqual(again.json,first.json)
        same=self.upload(operation='fixture-crest-request-0002');self.assertEqual(same.json['receipt'],dict(crestId=1,charged=0))
        self.assertEqual(self.read('SELECT account,credits,gold FROM wallets ORDER BY account'),[(self.owner,2000,0),('alice',3000,0),('bob',3000,0)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_ledger')[0][0],1)

    def test_concurrent_request_charges_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:responses=list(pool.map(lambda _:self.upload(client=self.app.test_client()),range(4)))
        self.assertTrue(all(r.status_code==200 for r in responses));self.assertTrue(all(r.json==responses[0].json for r in responses))
        self.assertEqual(self.read('SELECT credits FROM wallets WHERE account=?',(self.owner,)),[(2000,)])

    def test_no_arbitrary_owner_unowned_slot_rights_revoked_or_conflicting_replay(self):
        for username,slot in ((self.owner,'1'),('alice','3'),('alice','1')):
            self.assertIn(self.upload(username=username,slot=slot).status_code,(400,409))
        self.assertEqual(self.upload().status_code,200)
        self.assertEqual(self.upload(raw=bmp(8)).status_code,409)
        with transaction(self.path) as db:db.execute('UPDATE clan_members SET permissions=0 WHERE account=?',(self.owner,))
        self.assertEqual(self.upload().status_code,409)
        self.assertEqual(self.read('SELECT credits FROM wallets WHERE account=?',(self.owner,)),[(2000,)])

    def test_gateway_authorization_and_body_format_boundaries(self):
        self.assertEqual(self.upload(auth=False).status_code,401);self.assertEqual(self.upload(remote='203.0.113.9').status_code,403)
        for raw in (bmp()+b'x',bmp()[:700],bmp()[:28]+b'\x08\x00'+bmp()[30:],b'not a bitmap',bmp()[:22]+struct.pack('<i',-16)+bmp()[26:]):
            self.assertEqual(self.upload(raw=raw).status_code,400)
        self.assertEqual(self.upload(raw=b'x'*825).status_code,413)
        self.assertEqual(self.upload(operation='short').status_code,400);self.assertEqual(self.upload(slot='02').status_code,400)
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_crest_blobs'),[(0,)])

    def test_insufficient_funds_and_storage_fault_rollback_all(self):
        with transaction(self.path) as db:db.execute('UPDATE wallets SET credits=999 WHERE account=?',(self.owner,))
        self.assertEqual(self.upload().status_code,409)
        with transaction(self.path) as db:
            db.execute('UPDATE wallets SET credits=3000 WHERE account=?',(self.owner,));db.execute("CREATE TRIGGER failcrest BEFORE INSERT ON clan_crests BEGIN SELECT RAISE(ABORT,'private_fixture_fault'); END")
        failed=self.upload();self.assertEqual(failed.status_code,503);self.assertEqual(failed.json,dict(error='service_unavailable'))
        self.assertEqual(self.read('SELECT credits FROM wallets WHERE account=?',(self.owner,)),[(3000,)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_crest_blobs'),[(0,)]);self.assertEqual(self.read('SELECT COUNT(*) FROM clan_benefit_receipts'),[(0,)])

    def test_public_bytes_are_service_authenticated_validated_immutable_and_no_db_mutation(self):
        self.assertEqual(self.upload().status_code,200);before=self.path.read_bytes();url='/v1/clan/crests/1'
        self.assertEqual(self.client.get(url).status_code,401)
        result=self.client.get(url,headers={'Authorization':'Bearer '+self.key})
        self.assertEqual(result.data,bmp());self.assertEqual(result.content_type,'image/bmp');self.assertEqual(result.headers['Cache-Control'],'public, max-age=31536000, immutable')
        self.assertEqual(result.headers['ETag'],'"'+hashlib.sha256(bmp()).hexdigest()+'"');self.assertEqual(self.path.read_bytes(),before)
        with transaction(self.path) as db:db.execute('UPDATE clan_crest_blobs SET digest=? WHERE id=1',('0'*64,))
        failed=self.client.get(url,headers={'Authorization':'Bearer '+self.key});self.assertEqual(failed.status_code,404);self.assertEqual(failed.headers['Cache-Control'],'no-store')

    def test_public_identity_rejects_unsafe_ranges_and_unknown_ids(self):
        headers={'Authorization':'Bearer '+self.key}
        for value in ('0','01','4294967296','9999999999999999999999999','-1','1.bmp'):
            self.assertEqual(self.client.get('/v1/clan/crests/'+value,headers=headers).status_code,400)
        self.assertEqual(self.client.get('/v1/clan/crests/17',headers=headers).status_code,404)

    def test_alliance_status_rights_and_upload_are_bound_to_current_leading_head(self):
        identity=self.alliance();headers={'Authorization':'Bearer '+self.key}
        delegated=self.client.post('/v1/clan/status',json=dict(username='alice',slot=2),headers=headers).json
        self.assertTrue(delegated['canUpload']);self.assertFalse(delegated['alliance']['canUpload']);self.assertEqual(delegated['alliance']['id'],identity)
        self.assertEqual(self.upload(kind='alliance').status_code,409)
        head=self.client.post('/v1/clan/status',json=dict(username='bob',slot=1),headers=headers).json;self.assertTrue(head['alliance']['canUpload'])
        first=self.upload(username='bob',slot='1',kind='alliance');self.assertEqual(first.status_code,200)
        self.assertEqual(first.json['credits'],2000);self.assertEqual(first.json['alliance']['crestId'],first.json['receipt']['crestId'])
        self.assertEqual(self.upload(username='bob',slot='1',kind='alliance').json,first.json)
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='bob'"),[(2000,0)])
        self.assertEqual(self.read('SELECT credits,influence FROM clans WHERE id=1'),[(0,0)])

    def test_alliance_remove_free_exact_empty_body_and_global_immutable_image(self):
        self.alliance();first=self.upload(username='bob',slot='1',kind='alliance').json;identity=first['receipt']['crestId']
        self.assertEqual(self.upload(username='bob',slot='1',kind='alliance',remove='1',operation='remove-with-image-0001').status_code,400)
        removed=self.upload(username='bob',slot='1',kind='alliance',remove='1',raw=b'',operation='remove-empty-body-0001')
        self.assertEqual(removed.status_code,200);self.assertEqual(removed.json['receipt'],dict(crestId=0,charged=0));self.assertEqual(removed.json['alliance']['crestId'],0)
        self.assertEqual(self.upload(username='bob',slot='1',kind='alliance',remove='1',raw=b'',operation='remove-empty-body-0001').json,removed.json)
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='bob'"),[(2000,0)])
        content=self.client.get('/v1/clan/crests/'+str(identity),headers={'Authorization':'Bearer '+self.key});self.assertEqual(content.data,bmp());self.assertEqual(content.status_code,200)
        for kind,remove in (('clan','1'),('unknown','0'),('alliance','2')):self.assertEqual(self.upload(kind=kind,remove=remove,raw=b'').status_code,400)


if __name__=='__main__':unittest.main()
