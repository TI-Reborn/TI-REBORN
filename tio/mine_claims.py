"""Explicit checkpoint ownership, frozen battle claims and operator audit.

Claims are never inferred from a player or created by a mining request. Native
checkpoint assaults are not implemented; this store is an idle-only operator
configuration entry point. A battle retains its claim even after configuration
changes. An active alliance authorizes admission alongside the owner's clan;
the frozen owner and tax recipients remain the actual checkpoint owner.
"""
from contextlib import closing
import json
from pathlib import Path
import time
from .db_transaction import connect

POLICY=json.loads((Path(__file__).resolve().parents[1]/'config/mining.json').read_text())
LOCATIONS={v['id']:v for v in POLICY['locations']}
CLAIM_FIELDS={'location','owner_clan','tax_percent','revision'}


class MineClaimRejected(ValueError):pass


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS mine_claims (
        location INTEGER PRIMARY KEY,owner_clan INTEGER,
        tax_percent INTEGER NOT NULL CHECK(tax_percent BETWEEN 0 AND 10),
        revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 4294967295),
        CHECK(owner_clan IS NOT NULL OR tax_percent=0))''')
    db.execute('''CREATE TABLE IF NOT EXISTS mine_claim_history (
        location INTEGER NOT NULL,revision INTEGER NOT NULL,owner_clan INTEGER,
        tax_percent INTEGER NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,
        created REAL NOT NULL,PRIMARY KEY(location,revision))''')
    db.execute('''CREATE TABLE IF NOT EXISTS clan_crystals (
        clan_id INTEGER PRIMARY KEY,amount INTEGER NOT NULL
        CHECK(amount BETWEEN 0 AND 4294967295))''')
    db.execute('''CREATE TABLE IF NOT EXISTS mine_claim_leases (
        match_id TEXT PRIMARY KEY,owner_clan INTEGER NOT NULL,
        location INTEGER NOT NULL,revision INTEGER NOT NULL)''')


def validate_claim(claim):
    if not isinstance(claim,dict) or set(claim)!=CLAIM_FIELDS:
        raise MineClaimRejected('Invalid frozen checkpoint claim')
    location,owner,tax,revision=(claim[k] for k in ('location','owner_clan','tax_percent','revision'))
    if type(location) is not int or location not in LOCATIONS:
        raise MineClaimRejected('Unknown mine checkpoint')
    if owner is not None and (type(owner) is not int or not 0<owner<=0xffffffff):
        raise MineClaimRejected('Invalid checkpoint owner')
    if type(tax) is not int or not 0<=tax<=10 or owner is None and tax:
        raise MineClaimRejected('Invalid checkpoint tax')
    if type(revision) is not int or not 0<=revision<=0xffffffff or revision==0 and owner is not None:
        raise MineClaimRejected('Invalid checkpoint revision')
    return dict(claim)


def validate_frozen(db,claim,*,require_owner=True):
    claim=validate_claim(claim)
    if claim['revision']:
        row=db.execute('SELECT owner_clan,tax_percent FROM mine_claim_history WHERE location=? AND revision=?',
                       (claim['location'],claim['revision'])).fetchone()
        if row!=(claim['owner_clan'],claim['tax_percent']):
            raise MineClaimRejected('Frozen checkpoint claim is not in ownership history')
    owner=claim['owner_clan']
    if require_owner and owner is not None and not db.execute('SELECT 1 FROM clans WHERE id=?',(owner,)).fetchone():
        raise MineClaimRejected('Frozen checkpoint owner clan no longer exists')
    return claim


def frozen_claim(db,location):
    if type(location) is not int or location not in LOCATIONS:
        raise MineClaimRejected('Unknown mine checkpoint')
    row=db.execute('SELECT owner_clan,tax_percent,revision FROM mine_claims WHERE location=?',(location,)).fetchone()
    claim=dict(location=location,owner_clan=row[0] if row else None,
               tax_percent=row[1] if row else 0,revision=row[2] if row else 0)
    return validate_frozen(db,claim)


def authorize_defender(db,account,claim):
    """Check current real membership at admission; the battle freezes that pair."""
    claim=validate_frozen(db,claim)
    owner=claim['owner_clan']
    row=db.execute('SELECT clan_id FROM clan_members WHERE account=?',(account,)).fetchone()
    if owner is None or row is None:
        raise MineClaimRejected('Защита доступна участникам клана-владельца блокпоста и его действующего альянса')
    if row[0]!=owner:
        from .alliances import alliance_for_clan
        allied=alliance_for_clan(db,owner)
        if allied is None or row[0] not in allied['clans']:
            raise MineClaimRejected('Защита доступна участникам клана-владельца блокпоста и его действующего альянса')
    return owner


def configured_owner(db,clan_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='mine_claims'").fetchone():return False
    if db.execute('SELECT 1 FROM mine_claims WHERE owner_clan=?',(clan_id,)).fetchone():return True
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='mine_claim_leases'").fetchone():
        return bool(db.execute('SELECT 1 FROM mine_claim_leases WHERE owner_clan=?',(clan_id,)).fetchone())
    return False


class MineClaimsStore:
    def __init__(self,path,*,clock=time.time):
        self.path,self.clock=path,clock
        with closing(connect(path)) as db,db:
            from .clans import schema as clan_schema
            clan_schema(db);schema(db)

    def freeze(self,location):
        with closing(connect(self.path)) as db:
            db.execute('BEGIN');return frozen_claim(db,location)

    def authorize_defender(self,account,claim):
        with closing(connect(self.path)) as db:
            db.execute('BEGIN');return authorize_defender(db,account,claim)

    def admin_set_claim(self,location,owner_clan,*,tax_percent=10,expected_revision,
                        actor,reason):
        """Operator-only setup. Caller must authorize the operator, never C2S.

        An explicit expected revision prevents an unnoticed takeover. Ownership
        configuration cannot change while a durable battle or outbox is pending.
        Clearing ownership requires owner_clan=None and tax_percent=0.
        """
        if not isinstance(actor,str) or not actor.strip() or not isinstance(reason,str) or not reason.strip():
            raise MineClaimRejected('Ownership changes require an operator and reason')
        if type(expected_revision) is not int or not 0<=expected_revision<0xffffffff:
            raise MineClaimRejected('Invalid expected checkpoint revision')
        claim=validate_claim(dict(location=location,owner_clan=owner_clan,tax_percent=tax_percent,
                                 revision=expected_revision+1))
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            for table in ('battle_checkpoints','battle_settlement_jobs'):
                if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() and db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                    raise MineClaimRejected('Checkpoint ownership changes require no pending battles')
            row=db.execute('SELECT revision FROM mine_claims WHERE location=?',(location,)).fetchone()
            if (row[0] if row else 0)!=expected_revision:
                raise MineClaimRejected('Checkpoint ownership revision changed')
            if owner_clan is not None and not db.execute('SELECT 1 FROM clans WHERE id=?',(owner_clan,)).fetchone():
                raise MineClaimRejected('Checkpoint owner must be an existing clan')
            db.execute('INSERT INTO mine_claim_history VALUES (?,?,?,?,?,?,?)',
                       (location,claim['revision'],owner_clan,tax_percent,actor.strip(),reason.strip(),self.clock()))
            db.execute('''INSERT INTO mine_claims VALUES (?,?,?,?) ON CONFLICT(location)
                DO UPDATE SET owner_clan=excluded.owner_clan,tax_percent=excluded.tax_percent,revision=excluded.revision''',
                       (location,owner_clan,tax_percent,claim['revision']))
        return claim
