"""Versioned server-owned learned-skill snapshots, not a learning policy.

Only a future validated learning transaction may update these snapshots from
game requests. Never copy a client-supplied list into this store.
"""

from .db_transaction import connect
from contextlib import closing
import sqlite3
from .owned_pets import OwnedPetStore
from .protocol.abilities import encode_abilities,decode_abilities


class AbilityStateStore:
    def __init__(self,path,catalog):
        self.path=path;self.catalog=catalog
        OwnedPetStore(path)
        with closing(connect(path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS ability_states (account TEXT NOT NULL,pet_id INTEGER NOT NULL,revision INTEGER NOT NULL,packet BLOB NOT NULL,PRIMARY KEY(account,pet_id))')

    @staticmethod
    def _owned(db,account,owner):
        if not isinstance(account,str) or not account:raise ValueError('Account required')
        if db.execute('SELECT 1 FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone() is None:
            raise ValueError('Owned actor required')

    def _read(self,db,account,owner):
        self._owned(db,account,owner)
        row=db.execute('SELECT revision,packet FROM ability_states WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        if row is None:return 0,()
        actor,entries,learning=decode_abilities(row[1])
        if actor!=owner or learning:raise ValueError('Invalid saved ability profile')
        return row[0],entries

    def read(self,account,owner):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN')
            return self._read(db,account,owner)

    def replace(self,account,owner,entries,*,expected_revision):
        """CAS snapshot update for trusted server code; no resource spending.

        Eligibility, price and passive-stat changes must be established before
        wiring a learning request. Revision prevents stale snapshot overwrites.
        """
        if type(expected_revision) is not int or expected_revision<0:
            raise ValueError('Nonnegative revision required')
        entries=tuple(entries)
        if len({e.ability_id for e in entries})!=len(entries):raise ValueError('Duplicate skill')
        for entry in entries:
            if entry.ability_id==0 or (entry.ability_id,entry.level) not in self.catalog.by_key:
                raise ValueError('Unknown explicit ability level')
        packet=encode_abilities(owner,entries)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            revision,_=self._read(db,account,owner)
            if revision!=expected_revision:raise ValueError('Stale ability revision')
            db.execute('INSERT INTO ability_states VALUES (?,?,?,?) ON CONFLICT(account,pet_id) DO UPDATE SET revision=excluded.revision,packet=excluded.packet',
                       (account,owner,revision+1,packet))
        return revision+1
