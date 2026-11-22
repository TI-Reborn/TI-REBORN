"""Clan crest IDs in the native battle member list (left of the turn-timer name).

The original renderer at Silver 9576a8 draws the crest from member field +0x114,
which the 25 reader (85fe74) fills from the u32 after the name and queues for
download (59/5A). The server must therefore send each account's clan crest ID.
"""
from contextlib import closing
import sqlite3
import unittest

import test_shared_team_arena as fixture
from test_clan_benefits import bmp
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio.clan_benefits import account_crests, path_crest, schema as benefits_schema, set_crest
from tio.clans import schema as clan_schema
from tio.db_transaction import transaction
from tio.protocol.battle_members import decode_battle_members


def install_clans(path, members):
    """Each leader account founds its own clan; returns {account: crest ID}."""
    crests = {}
    with transaction(path) as db:
        clan_schema(db);benefits_schema(db)
        db.execute('CREATE TABLE IF NOT EXISTS characters(account TEXT,slot INTEGER,name BLOB)')
        for index, account in enumerate(members, 1):
            db.execute('INSERT INTO characters VALUES (?,1,?)', (account, account.encode()))
            db.execute('INSERT INTO clans(name,name_key,leader,influence,credits) VALUES (?,?,?,0,0)',
                       (account.encode()+b'Clan', account+'clan', account))
            clan = db.execute('SELECT id FROM clans WHERE leader=?', (account,)).fetchone()[0]
            db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,?,0)', (account, clan))
            crests[account] = set_crest(db, account, bmp(index), 'crest-'+account)['crest_id']
    return crests


def crests_by_name(packet):
    return {record.name: record.crest_id for record in decode_battle_members(packet)[2]}


class AccountCrestTests(unittest.TestCase):
    def setUp(self):
        case = fixture.SharedTeamTests();case.setUp();self.addCleanup(case.doCleanups)
        self.path = case.path

    def read(self, accounts):
        with closing(sqlite3.connect(self.path)) as db:return account_crests(db, accounts)

    def test_database_without_clans_gives_zero_for_everyone(self):
        self.assertEqual(self.read(('alice', 'bob')), {'alice': 0, 'bob': 0})

    def test_clan_members_get_their_clan_crest_and_others_zero(self):
        crests = install_clans(self.path, ('alice', 'bob'))
        self.assertNotEqual(crests['alice'], crests['bob'])
        self.assertEqual(self.read(('alice', 'bob', 'carol')), {**crests, 'carol': 0})

    def test_single_account_read_from_its_database_file(self):
        crests = install_clans(self.path, ('alice',))
        self.assertEqual((path_crest(self.path, 'alice'), path_crest(self.path, 'bob')), (crests['alice'], 0))

    def test_clan_without_uploaded_crest_gives_zero(self):
        install_clans(self.path, ('alice',))
        with transaction(self.path) as db:db.execute('DELETE FROM clan_crests')
        self.assertEqual(self.read(('alice',)), {'alice': 0})


class BattleMemberCrestTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.hub = self.case.hub;self.path = self.case.path
        self.crests = install_clans(self.path, ('alice', 'bob'))
        self.wall = 1000.;self.hub.journal = BattleJournal(self.hub, self.path, wall=lambda:self.wall)
        self.started = {}
        for packet in (b'\xba\3\0\1', b'\x36'):
            for index in (0, 1):
                replies = self.case.send(index, packet)
                owner = self.hub.identities[self.case.sessions[index]]
                self.started[owner] = (*self.started.get(owner, ()), *replies)
        self.hub.tick()
        self.owners = tuple(self.hub.identities[s] for s in self.case.sessions[:2])
        self.battle = self.hub.battles[self.owners[0]]

    def expected(self):
        return {b'alice': self.crests['alice'], b'bob': self.crests['bob']}

    def member_lists(self, owner):
        packets = (*self.started[owner], *self.hub.queues[owner])
        return [p for p in packets if p[:1] == b'\x25']

    def test_both_accounts_see_every_clan_crest_when_battle_starts(self):
        for owner in self.owners:
            lists = self.member_lists(owner)
            self.assertTrue(lists)
            self.assertEqual(crests_by_name(lists[-1]), self.expected())

    def test_reconnect_member_list_keeps_crests(self):
        for owner in self.owners:
            packet = self.hub.battle_members_packet(self.battle, owner)
            self.assertEqual(crests_by_name(packet), self.expected())

    def test_crests_survive_checkpoint_recovery(self):
        restored = TeamArena(clock=lambda:self.case.now)
        restored.journal = BattleJournal(restored, self.path, wall=lambda:self.wall)
        restored.journal.recover()
        battle = restored.battles[self.owners[0]]
        self.assertEqual(crests_by_name(restored.battle_members_packet(battle, self.owners[1])), self.expected())


class PrivateBattleCrestTests(unittest.TestCase):
    def test_private_scene_shows_only_the_player_crest(self):
        import json, tempfile
        from pathlib import Path
        from wallet_fixture import fund_wallet
        from tio.abilities import AbilityCatalog, AbilityLevel
        from tio.arena_service import ArenaService
        from tio.city_catalogs import CityCatalogs
        from tio.hiring import HireStore
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from tools.survival_scene import prepare_survival
        root = Path(__file__).resolve().parents[1]
        source = json.loads((root/'config/abilities.json').read_text())
        catalog = AbilityCatalog(AbilityLevel(r['id'], r['level'], r['fields']) for r in source['records'])
        template = bytes.fromhex(json.loads((root/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'state.db'
            fund_wallet(path, 'alice', credits=10_000, gold=10_000)
            HireStore(path, CityCatalogs(root/'config/city_catalogs.json'), template).hire('alice', 1)
            from tio.squad import SquadStore
            SquadStore(path).assign('alice', OwnedPetStore(path).list('alice')[0][0], 1)
            ticket = SurvivalQueue().join(42, OwnedPetStore(path).list('alice'))
            scene = prepare_survival(path, 'alice', ticket, catalog)
            _, packets = ArenaService().start_survival(42, b'Alice', scene, crest_id=7)
        members = next(p for p in packets if p[:1] == b'\x25')
        rows = {r.character_id: r.crest_id for r in decode_battle_members(members)[2]}
        self.assertEqual(rows.pop(42), 7)
        self.assertTrue(rows and set(rows.values()) == {0})


if __name__ == '__main__':unittest.main()
