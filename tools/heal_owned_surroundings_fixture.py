"""Heal only the existing randomly named surroundings QA fixture while offline.

Fixture level changes intentionally set a test level. Keep its XP at the
canonical floor for that level before normalization, then heal to the derived
maximum through the same projection/save APIs used by normal treatment. Rank
points, abilities, inventories, wallets and every other account are preserved.
Import and --self-test perform no network operation.
"""
import argparse
from contextlib import closing
import inspect
import json
from pathlib import Path
import re
import sys
import tempfile
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP, PROFILES, require


def heal_rows(db, names, expected_level):
    """Caller owns the transaction and has proven every recipient is fresh QA."""
    from tio.level_progression import FLOORS, sync as sync_levels
    from tio.ranks import sync as sync_ranks
    from tio.passive_stats import project_saved_pet
    from tio.battle_recovery import save_wounds
    from tio.protocol.pet_info import decode_pet_info, encode_pet_info
    from dataclasses import replace
    assert expected_level in (1, 4)
    results = []
    for account in names:
        rows = db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id', (account,)).fetchall()
        assert len(rows) == 1 and rows[0][:2] == (1, 1), 'Only the single fresh fixture avatar may be adjusted'
        pet = decode_pet_info(rows[0][2], human_equipment=True)
        assert pet.fields['0x8c4aef'] == expected_level, 'Call set_city before healing the intended fixture level'
        old_xp = pet.fields['0x8c4b05']
        xp = FLOORS[expected_level-1]
        # A retained higher-city XP value otherwise promotes Reservation's
        # intentionally lowered fixture level back to4 and adds15 maximumHP.
        if old_xp != xp:
            packet = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4b05': xp}))
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1', (packet, account))
        sync_levels(db, account)
        sync_ranks(db, account)
        raw = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1', (account,)).fetchone()[0]
        derived = decode_pet_info(project_saved_pet(db, account, 1, raw, True), human_equipment=True)
        current, maximum = derived.fields['0x8c4ab1'], derived.fields['0x8c4a07']
        assert derived.fields['0x8c4aef'] == expected_level and 0 < maximum <= 65535
        save_wounds(db, account, {1: maximum})
        raw_after = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1', (account,)).fetchone()[0]
        verified = decode_pet_info(project_saved_pet(db, account, 1, raw_after, True), human_equipment=True)
        assert verified.fields['0x8c4ab1'] == verified.fields['0x8c4a07'] == maximum, 'Canonical heal is incomplete'
        results.append(dict(account=account, pet_id=1, fixture_level=expected_level,
            fixture_xp_before=old_xp, fixture_xp_after=xp, health_before=current,
            health_after=maximum, derived_maximum=maximum))
    return results


HEAL_OWNED = OWNERSHIP + '\n' + inspect.getsource(heal_rows) + r'''
import subprocess
from tio.locations import LocationStore
town=data['town'];level=data['level'];assert (town,level) in ((2,4),(5,4),(8,4),(3,1))
def exclusive():
 assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
 assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).strip(),'Another real/native client is online'
 assert db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0]==0,'A retained match exists'
 assert db.execute('SELECT COUNT(*) FROM battle_checkpoint_members').fetchone()[0]==0,'Retained participants exist'
 assert db.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0]==0,'A settlement is pending'
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE')
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 exclusive()
 for n in names:
  assert db.execute('SELECT town_id FROM character_locations WHERE account=?',(n,)).fetchone()==(town,),'Call owned set_city first'
 healed=heal_rows(db,names,level)
 exclusive()
print(json.dumps(dict(passed=True,town=town,fixture_level=level,own_accounts=len(names),healed=healed,
 canonical_apis=['level_progression.sync','ranks.sync','passive_stats.project_saved_pet','battle_recovery.save_wounds'],
 fixture_xp_normalized_to_intended_level=True,other_accounts_touched=False)))
'''


def heal_owned_fixture(fixture, city):
    require(fixture.host == '185.184.42.88' and re.fullmatch(r'qs[0-9a-f]{8}', fixture.prefix), 'Only the known hosted own QA fixture is permitted')
    require(fixture.names == [fixture.prefix+chr(97+i) for i in range(len(fixture.names))] and
            len(fixture.names) in (2, 4, 8) and city in PROFILES, 'Invalid owned fixture/city')
    rule = PROFILES[city]
    return fixture.remote(HEAL_OWNED, {**fixture.ownership_payload(), 'town': rule['town'], 'level': rule['level']})


def self_test():
    from tio.owned_pets import OwnedPetStore
    from tio.protocol.pet_info import decode_pet_info, encode_pet_info
    from tio.level_progression import FLOORS
    from dataclasses import replace
    compile(HEAL_OWNED, '<ownership checked remote canonical heal>', 'exec')
    source = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
    checks = 1
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'local-test.sqlite3'
        store = OwnedPetStore(path)
        for account in ('qs01234567a', 'untouched'):
            store.ensure(account, bytes.fromhex(source['packet_hex']), bytes.fromhex(source['inventory_packet_hex']), human=True)
        with closing(sqlite3.connect(path)) as db, db:
            foreign_before = list(db.execute("SELECT * FROM owned_pets WHERE account='untouched'"))
            raw = db.execute("SELECT pet_packet FROM owned_pets WHERE account='qs01234567a'").fetchone()[0]
            pet = decode_pet_info(raw, human_equipment=True)
            packet = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4aef':1, '0x8c4b05':FLOORS[3],
                '0x8c4a07':1000, '0x8c4ab1':1000}))
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='qs01234567a'", (packet,))
            first = heal_rows(db, ['qs01234567a'], 1)
            require(first[0]['fixture_xp_before'] == FLOORS[3] and first[0]['fixture_xp_after'] == FLOORS[0], 'Higher-city XP was retained')
            checks += 1
            require(first[0]['health_after'] == first[0]['derived_maximum'] == 1000, 'Fixture level normalization added the old15HP')
            checks += 1
            second = heal_rows(db, ['qs01234567a'], 1)
            require(second[0]['health_after'] == 1000, 'Repeated healing accumulated health bonuses')
            checks += 1
            from tio.protocol.abilities import AbilityEntry, encode_abilities
            db.execute('CREATE TABLE ability_states(account TEXT,pet_id INTEGER,packet BLOB)')
            learned = encode_abilities(1, (AbilityEntry(1, 1, 0, 0),))
            db.execute('INSERT INTO ability_states VALUES (?,?,?)', ('qs01234567a', 1, learned))
            projected = heal_rows(db, ['qs01234567a'], 1)
            require(projected[0]['health_after'] == projected[0]['derived_maximum'] == 1005,
                    'Learned health maximum was not included in canonical healing')
            require(heal_rows(db, ['qs01234567a'], 1)[0]['health_after'] == 1005,
                    'Repeated derived-health healing accumulated the passive bonus')
            checks += 2
            require(foreign_before == list(db.execute("SELECT * FROM owned_pets WHERE account='untouched'")), 'Another account changed')
            checks += 1
            try:
                heal_rows(db, ['qs01234567a'], 4)
            except AssertionError:
                checks += 1
            else:
                raise AssertionError('Wrong intended city level was accepted')
    print(json.dumps(dict(offline_self_test='passed', checks=checks, server_contacted=False, accounts_created=0)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--city', choices=tuple(PROFILES))
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        require(args.fixture and args.city, 'An existing private owned fixture and intended city are required')
        fixture = FreshSurroundingsQA.load_private(args.fixture)
        print(json.dumps(heal_owned_fixture(fixture, args.city)))
