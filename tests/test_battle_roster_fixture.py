from wallet_fixture import fund_wallet
import json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from tio.abilities import AbilityCatalog,AbilityLevel
from tio.ability_state import AbilityStateStore
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.wallets import WalletStore
from tio.protocol.abilities import AbilityEntry,decode_abilities
from tio.protocol.ability_cast import AbilityCast
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo
from tio.protocol.battle_soldier import decode_battle_soldier
from tools.battle_roster_fixture import prepare_actor

ROOT=Path(__file__).resolve().parents[1]


class BattleRosterFixtureTests(unittest.TestCase):
    def test_saved_dog_health_learned_rules_and_isolation(self):
        source=json.loads((ROOT/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'state.db';fund_wallet(db, 'alice', credits=10_000, gold=10_000)
            hire=HireStore(db,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
            pet,inventory,_=hire.hire('alice',3)
            dog=decode_pet_info(pet,human_equipment=False);actor=dog.fields['0x8c43eb']
            injured=encode_pet_info(PetInfo(False,{**dog.fields,'0x8c4ab1':73}))
            with closing(sqlite3.connect(db)) as connection,connection:
                connection.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(injured,'alice',actor))
            state=AbilityStateStore(db,catalog)
            state.replace('alice',actor,[AbilityEntry(23,1,0,1)],expected_revision=0)
            prepared=prepare_actor(db,'alice',actor,42,catalog)
            wire=decode_battle_soldier(prepared.packets[0],human_equipment=False)
            self.assertEqual((wire.soldier_id,wire.owner_id,wire.fields['0x8c57bb']),(actor,42,73))
            self.assertEqual(decode_abilities(prepared.packets[1])[1][0].ability_id,23)
            prepared.field.prepare_turn(42,[actor])
            updated=prepared.field.cast_healing(42,AbilityCast(23,actor,0,2,2))
            self.assertEqual((updated.health,updated.action_points),(85,33))
            # Battle mutations never rewrite persistent baseline or learned rank.
            reopened=prepare_actor(db,'alice',actor,42,catalog)
            self.assertEqual(reopened.field.actor(actor).health,73)
            self.assertEqual(state.read('alice',actor)[0],1)
            with self.assertRaises(ValueError):prepare_actor(db,'bob',actor,42,catalog)
            state.replace('alice',actor,[],expected_revision=1)
            no_skill=prepare_actor(db,'alice',actor,42,catalog)
            with self.assertRaises(ValueError):no_skill.field.cast_healing(42,AbilityCast(23,actor,0,2,2))
            state.replace('alice',actor,[AbilityEntry(23,2,0,1)],expected_revision=2)
            rank2=prepare_actor(db,'alice',actor,42,catalog)
            rank2.field.prepare_turn(42,[actor])
            updated=rank2.field.cast_healing(42,AbilityCast(23,actor,0,2,2))
            self.assertEqual((updated.health,updated.action_points),(85,33)) # Original new dog HP cap.
