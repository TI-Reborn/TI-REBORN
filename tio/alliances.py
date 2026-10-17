"""Account-authorized clan alliances; manual pp20–21, additive SQLite authority.

Costs come from clan treasury and influence, never a leader's personal wallet.
Leaders are derived from the leading clan on every request. Pending dissolution
retains its identity/roster for the documented three-day free cancellation, but
does not grant active allied combat/chat rights. Invitation expiry (five minutes)
and mutation blocking during registered warfare are explicit emulator policy.
No packets, accounts, clans, money or territory ownership are fabricated here.
"""
from contextlib import closing
import json
import struct
import time
import unicodedata
from .db_transaction import connect
from .clans import ClanRejected,require,record as clan_record,schema as clan_schema

CREATE_COST=(50_000,10_000)
JOIN_COST=(25_000,5_000)
UPGRADE_COST=(100_000,20_000)
COOLDOWN=3*24*60*60
INVITE_TTL=300
MAX_U32=0xffffffff
# Original russian.lng m471 confirms1000 credits for installation; payer and
# no-charge identical/removal are explicit emulator policy, see research doc.
CREST_COST=1000


class AllianceRejected(ClanRejected):pass


def present(db,table):return bool(db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone())


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS alliances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,name BLOB NOT NULL,name_key TEXT NOT NULL,
        leading_clan INTEGER NOT NULL,level INTEGER NOT NULL DEFAULT 1 CHECK(level IN (1,2)),
        state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','dissolving','dissolved')),
        dissolution_until REAL,revision INTEGER NOT NULL DEFAULT 0 CHECK(revision BETWEEN 0 AND 4294967295),
        created REAL NOT NULL)''')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS alliance_current_name ON alliances(name_key) WHERE state!='dissolved'")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS alliance_current_leader ON alliances(leading_clan) WHERE state!='dissolved'")
    db.execute('''CREATE TABLE IF NOT EXISTS alliance_members (
        clan_id INTEGER PRIMARY KEY,alliance_id INTEGER NOT NULL,joined REAL NOT NULL,
        FOREIGN KEY(alliance_id) REFERENCES alliances(id),FOREIGN KEY(clan_id) REFERENCES clans(id))''')
    db.execute('CREATE INDEX IF NOT EXISTS alliance_member_groups ON alliance_members(alliance_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS alliance_invites (
        target_clan INTEGER PRIMARY KEY,alliance_id INTEGER NOT NULL,inviter TEXT NOT NULL,
        expires REAL NOT NULL,FOREIGN KEY(alliance_id) REFERENCES alliances(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS alliance_cooldowns (
        clan_id INTEGER PRIMARY KEY,until REAL NOT NULL,alliance_id INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS alliance_crests (
        alliance_id INTEGER PRIMARY KEY CHECK(alliance_id>0),crest_id INTEGER NOT NULL CHECK(crest_id>0),
        FOREIGN KEY(alliance_id) REFERENCES alliances(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS alliance_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,alliance_id INTEGER NOT NULL,revision INTEGER NOT NULL,
        actor TEXT NOT NULL,operation TEXT NOT NULL,detail TEXT NOT NULL,created REAL NOT NULL,
        UNIQUE(alliance_id,revision))''')
    for operation in ('UPDATE','DELETE'):
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS alliance_ledger_no_{operation.lower()}
            BEFORE {operation} ON alliance_ledger BEGIN SELECT RAISE(ABORT,'Alliance audit is immutable'); END''')


def warfare_locked(db,clan_ids):
    ids=tuple(sorted(set(clan_ids)))
    if not ids or not present(db,'warfare_clan_locks'):return False
    return bool(db.execute('SELECT 1 FROM warfare_clan_locks WHERE clan_id IN ('+','.join('?' for _ in ids)+') LIMIT 1',ids).fetchone())


def _row(db,clan_id):
    if not present(db,'alliances'):return None
    row=db.execute('''SELECT a.id,a.name,a.leading_clan,a.level,a.state,a.dissolution_until,a.revision
        FROM alliances a JOIN alliance_members m ON m.alliance_id=a.id WHERE m.clan_id=?''',(clan_id,)).fetchone()
    if row is None:return None
    result=dict(zip(('id','name','leading_clan','level','state','dissolution_until','revision'),row))
    result['crest_id']=alliance_crest_id(db,result['id']);return result


def alliance_crest_id(db,alliance_id):
    """Pure typed pointer read; positive blob owners are clans, negative allies."""
    if type(alliance_id)is not int or not 0<alliance_id<=MAX_U32:raise AllianceRejected('Invalid alliance identity')
    if not present(db,'alliance_crests'):return 0
    row=db.execute('SELECT crest_id FROM alliance_crests WHERE alliance_id=?',(alliance_id,)).fetchone()
    if row is None:return 0
    if type(row[0])is not int or not 0<row[0]<=MAX_U32:raise AllianceRejected('Invalid alliance crest identity')
    owner=db.execute('SELECT clan_id FROM clan_crest_blobs WHERE id=?',(row[0],)).fetchone() if present(db,'clan_crest_blobs') else None
    if owner!=(-alliance_id,):raise AllianceRejected('Alliance crest pointer has an invalid owner')
    return row[0]


def _clans(db,alliance):
    ids=tuple(r[0] for r in db.execute('SELECT clan_id FROM alliance_members WHERE alliance_id=? ORDER BY clan_id',(alliance['id'],)))
    if alliance['leading_clan'] not in ids or not 1<=len(ids)<=alliance['level']+1:
        raise AllianceRejected('Некорректный состав альянса')
    result=[]
    for cid in (alliance['leading_clan'],*(i for i in ids if i!=alliance['leading_clan'])):
        row=db.execute('SELECT name,leader,level,influence FROM clans WHERE id=?',(cid,)).fetchone()
        if row is None:raise AllianceRejected('Клан альянса больше не существует')
        result.append(dict(id=cid,name=bytes(row[0]),leader=row[1],level=row[2],influence=row[3]))
    return tuple(result)


def alliance_for_clan(db,clan_id):
    """Active combat/chat affiliation; no new influence is minted or duplicated."""
    alliance=_row(db,clan_id)
    if alliance is None or alliance['state']!='active':return None
    clans=_clans(db,alliance)
    return dict(id=alliance['id'],name=bytes(alliance['name']),leading_clan=alliance['leading_clan'],
        level=alliance['level'],clans=tuple(c['id'] for c in clans),influence=sum(c['influence'] for c in clans),crest_id=alliance['crest_id'])


def configured_member(db,clan_id,*,now=None):
    """Prevent deleting a live or cancellable alliance's constituent clan."""
    alliance=_row(db,clan_id)
    return bool(alliance and (alliance['state']=='active' or alliance['state']=='dissolving' and alliance['dissolution_until']>(time.time() if now is None else now)))


class AlliancesStore:
    def __init__(self,path,*,clock=time.time,warfare_guard=None):
        self.path,self.clock,self.warfare_guard=path,clock,warfare_guard
        with closing(connect(path)) as db,db:clan_schema(db);schema(db)

    def _guard(self,db,clan_ids):
        ids=tuple(sorted(set(clan_ids)))
        if warfare_locked(db,ids):raise AllianceRejected('Состав альянса нельзя менять во время заявки или штурма')
        if self.warfare_guard is not None and self.warfare_guard(db,ids):
            raise AllianceRejected('Состав альянса нельзя менять во время заявки или штурма')

    def _audit(self,db,alliance_id,account,operation,detail,clan_ids,now):
        cursor=db.execute('UPDATE alliances SET revision=revision+1 WHERE id=? AND revision<?',(alliance_id,MAX_U32))
        if cursor.rowcount!=1:raise AllianceRejected('Исчерпана последовательность альянса')
        revision=db.execute('SELECT revision FROM alliances WHERE id=?',(alliance_id,)).fetchone()[0]
        text=json.dumps(detail,sort_keys=True,separators=(',',':'))
        db.execute('INSERT INTO alliance_ledger(alliance_id,revision,actor,operation,detail,created) VALUES (?,?,?,?,?,?)',
            (alliance_id,revision,account,operation,text,now))
        for cid in sorted(set(clan_ids)):clan_record(db,cid,account,'alliance:'+operation,text)

    def _expire(self,db,now):
        # Pure reads never finalize a dissolution. Any subsequent mutation
        # atomically releases expired identity reservations and memberships.
        for aid in [r[0] for r in db.execute("SELECT id FROM alliances WHERE state='dissolving' AND dissolution_until<=?",(now,))]:
            db.execute('DELETE FROM alliance_members WHERE alliance_id=?',(aid,))
            db.execute('DELETE FROM alliance_invites WHERE alliance_id=?',(aid,))
            db.execute("UPDATE alliances SET state='dissolved' WHERE id=?",(aid,))
            self._audit(db,aid,'server','dissolved',{},(),now)
        db.execute('DELETE FROM alliance_cooldowns WHERE until<=?',(now,))

    @staticmethod
    def _charge(db,clan_id,cost):
        credits,influence=cost
        row=db.execute('SELECT credits,influence FROM clans WHERE id=?',(clan_id,)).fetchone()
        if row is None or row[0]<credits or row[1]<influence:raise AllianceRejected('В казне клана недостаточно кредитов или влияния')
        db.execute('UPDATE clans SET credits=credits-?,influence=influence-? WHERE id=?',(credits,influence,clan_id))
        return dict(clan_id=clan_id,credits=credits,influence=influence,before=list(row),after=[row[0]-credits,row[1]-influence])

    @staticmethod
    def _eligible(db,clan_id,now):
        row=db.execute('SELECT level FROM clans WHERE id=?',(clan_id,)).fetchone()
        if row is None or row[0]<1:raise AllianceRejected('Для альянса нужен клан уровня 1 или выше')
        if _row(db,clan_id) is not None:raise AllianceRejected('Клан уже состоит в альянсе')
        cooldown=db.execute('SELECT until FROM alliance_cooldowns WHERE clan_id=?',(clan_id,)).fetchone()
        if cooldown and cooldown[0]>now:raise AllianceRejected('Действует трёхдневная отсрочка вступления в альянс')

    def _owned(self,db,account,*,pending=False):
        clan=require(db,account,leader=True);alliance=_row(db,clan['id'])
        if alliance is None or alliance['leading_clan']!=clan['id']:raise AllianceRejected('Действие доступно главе ведущего клана альянса')
        if alliance['state']!=('dissolving' if pending else 'active'):raise AllianceRejected('Альянс сейчас недоступен для этой операции')
        return clan,alliance,_clans(db,alliance)

    def set_crest(self,account,bmp,identity):
        """Active leading head only;1000 personal credits, None removes for0.

        The shared global blob sequence prevents original ti.exe cache collision.
        Negative owner encoding keeps alliance and clan digest namespaces typed.
        Historical blobs remain fetchable by immutable ID after removal/change.
        """
        from . import clan_benefits as b
        if bmp is not None:
            try:
                digest=b.validate_crest(bmp)
                if struct.unpack_from('<i',bmp,22)[0]!=16:raise ClanRejected('Native crest requires bottom-up BMP')
            except ClanRejected:raise AllianceRejected('Invalid canonical alliance crest') from None
        else:digest=None
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');clan,alliance,cohort=self._owned(db,account);b.write(db)
            request=b.canonical(dict(alliance=alliance['id'],digest=digest));old=b.prior(db,'alliance_crest',identity,account,request)
            if old is not None:return old
            current=alliance_crest_id(db,alliance['id']);row=db.execute('SELECT digest FROM clan_crest_blobs WHERE id=?',(current,)).fetchone() if current else None
            charged=0;crest=current
            if bmp is None:
                if current:db.execute('DELETE FROM alliance_crests WHERE alliance_id=?',(alliance['id'],));crest=0
            elif row is None or row[0]!=digest:
                if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',(CREST_COST,account,CREST_COST)).rowcount!=1:raise AllianceRejected('Недостаточно личных кредитов для знака альянса')
                db.execute('INSERT OR IGNORE INTO clan_crest_blobs(clan_id,digest,bmp) VALUES (?,?,?)',(-alliance['id'],digest,bmp))
                crest=db.execute('SELECT id FROM clan_crest_blobs WHERE clan_id=? AND digest=?',(-alliance['id'],digest)).fetchone()[0];b.integer(crest)
                db.execute('INSERT INTO alliance_crests VALUES (?,?) ON CONFLICT(alliance_id) DO UPDATE SET crest_id=excluded.crest_id',(alliance['id'],crest));charged=CREST_COST
            result=dict(alliance_id=alliance['id'],crest_id=crest,charged=charged)
            if crest!=current:self._audit(db,alliance['id'],account,'crest',dict(crest_id=crest,digest=digest,charged=charged,payer='personal',policy='1000 changed,0 identical/remove'),[c['id'] for c in cohort],now)
            return b.receipt(db,'alliance_crest',identity,account,request,result)

    def info(self,account):return self.snapshot(account)[0]

    def snapshot(self,account,*,db=None):
        if db is not None:
            row=db.execute('SELECT clan_id FROM clan_members WHERE account=?',(account,)).fetchone()
            alliance=_row(db,row[0]) if row else None
            if alliance is None or alliance['state']=='dissolved' or alliance['state']=='dissolving' and alliance['dissolution_until']<=self.clock():return None,()
            clans=_clans(db,alliance)
            return dict(alliance,name=bytes(alliance['name']),leader=clans[0]['leader'],
                clans=tuple(c['id'] for c in clans),influence=sum(c['influence'] for c in clans)),clans
        with closing(connect(self.path)) as db:
            db.execute('BEGIN')
            return self.snapshot(account,db=db)

    def create(self,account,name):
        try:text=name.decode('cp1251')
        except (UnicodeError,AttributeError):raise AllianceRejected('Некорректное название альянса')
        if not 3<=len(name)<=32 or text!=text.strip() or any(unicodedata.category(c)[0]=='C' for c in text):raise AllianceRejected('Название альянса должно содержать от 3 до 32 символов')
        key=unicodedata.normalize('NFKC',text).casefold();now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);clan=require(db,account,leader=True)
            self._eligible(db,clan['id'],now);self._guard(db,(clan['id'],))
            if db.execute("SELECT 1 FROM alliances WHERE name_key=? AND state!='dissolved'",(key,)).fetchone():raise AllianceRejected('Название альянса уже занято')
            cost=self._charge(db,clan['id'],CREATE_COST)
            aid=db.execute('INSERT INTO alliances(name,name_key,leading_clan,created) VALUES (?,?,?,?)',(name,key,clan['id'],now)).lastrowid
            if aid>MAX_U32:raise AllianceRejected('Исчерпана последовательность ID альянсов')
            db.execute('INSERT INTO alliance_members VALUES (?,?,?)',(clan['id'],aid,now))
            db.execute('DELETE FROM alliance_invites WHERE target_clan=?',(clan['id'],))
            self._audit(db,aid,account,'create',dict(name_hex=name.hex(),charge=cost),(clan['id'],),now)
            return aid

    def invite(self,account,target_clan_id):
        if type(target_clan_id)is not int or not 0<target_clan_id<=MAX_U32:raise AllianceRejected('Некорректный ID клана')
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);_,alliance,clans=self._owned(db,account)
            self._eligible(db,target_clan_id,now);self._guard(db,(*[c['id'] for c in clans],target_clan_id))
            if len(clans)>=alliance['level']+1:raise AllianceRejected('В альянсе нет свободных мест')
            prior=db.execute('SELECT expires FROM alliance_invites WHERE target_clan=?',(target_clan_id,)).fetchone()
            if prior and prior[0]>now:raise AllianceRejected('У клана уже есть действующее приглашение')
            db.execute('INSERT OR REPLACE INTO alliance_invites VALUES (?,?,?,?)',(target_clan_id,alliance['id'],account,now+INVITE_TTL))
            self._audit(db,alliance['id'],account,'invite',dict(target_clan=target_clan_id),[c['id'] for c in clans],now)

    def accept(self,account,decision):
        if type(decision)is not int or decision not in (0,1):raise AllianceRejected('Некорректный ответ на приглашение')
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);clan=require(db,account,leader=True)
            row=db.execute('SELECT alliance_id,inviter,expires FROM alliance_invites WHERE target_clan=?',(clan['id'],)).fetchone()
            if row is None:raise AllianceRejected('Приглашение больше не действует')
            aid,inviter,expiry=row
            _,alliance,clans=self._owned(db,inviter)
            if alliance['id']!=aid or expiry<=now:raise AllianceRejected('Приглашение больше не действует')
            cohort=(*[c['id'] for c in clans],clan['id']);self._guard(db,cohort)
            if not decision:
                db.execute('DELETE FROM alliance_invites WHERE target_clan=?',(clan['id'],))
                self._audit(db,aid,account,'decline',dict(target_clan=clan['id']),cohort,now);return 0
            self._eligible(db,clan['id'],now)
            if len(clans)>=alliance['level']+1:raise AllianceRejected('В альянсе нет свободных мест')
            cost=self._charge(db,clan['id'],JOIN_COST)
            db.execute('INSERT INTO alliance_members VALUES (?,?,?)',(clan['id'],aid,now))
            db.execute('DELETE FROM alliance_invites WHERE target_clan=?',(clan['id'],))
            self._audit(db,aid,account,'join',dict(target_clan=clan['id'],charge=cost),cohort,now);return aid

    def upgrade(self,account):
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);clan,alliance,clans=self._owned(db,account)
            if alliance['level']>=2:raise AllianceRejected('Достигнут максимальный уровень альянса')
            cohort=[c['id'] for c in clans];self._guard(db,cohort)
            cost=self._charge(db,clan['id'],UPGRADE_COST)
            db.execute('UPDATE alliances SET level=2 WHERE id=?',(alliance['id'],))
            self._audit(db,alliance['id'],account,'upgrade',dict(charge=cost),cohort,now)

    def transfer_leading(self,account,target_clan_id):
        """Native AF09 chooses a current clan; its current head leads automatically."""
        if type(target_clan_id)is not int or not 0<target_clan_id<=MAX_U32:raise AllianceRejected('Некорректный ID клана')
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);_,alliance,clans=self._owned(db,account)
            cohort=[c['id'] for c in clans]
            if target_clan_id not in cohort:raise AllianceRejected('Клан не состоит в вашем альянсе')
            if target_clan_id==alliance['leading_clan']:raise AllianceRejected('Этот клан уже является ведущим')
            self._guard(db,cohort)
            db.execute('UPDATE alliances SET leading_clan=? WHERE id=?',(target_clan_id,alliance['id']))
            self._audit(db,alliance['id'],account,'transfer_leading',
                dict(previous_clan=alliance['leading_clan'],leading_clan=target_clan_id),cohort,now)

    def _remove(self,account,target_clan_id=None):
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now)
            if target_clan_id is None:
                clan=require(db,account,leader=True);target_clan_id=clan['id'];alliance=_row(db,target_clan_id)
                if alliance is None or alliance['state']!='active':raise AllianceRejected('Вы не состоите в действующем альянсе')
                clans=_clans(db,alliance);operation='leave'
            else:
                if type(target_clan_id)is not int or not 0<target_clan_id<=MAX_U32:raise AllianceRejected('Некорректный ID клана')
                _,alliance,clans=self._owned(db,account);operation='kick'
            cohort=[c['id'] for c in clans]
            if target_clan_id==alliance['leading_clan']:raise AllianceRejected('Ведущий клан не может покинуть альянс')
            if target_clan_id not in cohort:raise AllianceRejected('Клан не состоит в вашем альянсе')
            self._guard(db,cohort)
            db.execute('DELETE FROM alliance_members WHERE clan_id=?',(target_clan_id,))
            db.execute('INSERT INTO alliance_cooldowns VALUES (?,?,?) ON CONFLICT(clan_id) DO UPDATE SET until=excluded.until,alliance_id=excluded.alliance_id',
                (target_clan_id,now+COOLDOWN,alliance['id']))
            self._audit(db,alliance['id'],account,operation,dict(target_clan=target_clan_id,cooldown_until=now+COOLDOWN),cohort,now)

    def leave(self,account):return self._remove(account)
    def kick(self,account,target_clan_id):return self._remove(account,target_clan_id)

    def dissolve(self,account):
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);_,alliance,clans=self._owned(db,account)
            cohort=[c['id'] for c in clans];self._guard(db,cohort);until=now+COOLDOWN
            db.execute("UPDATE alliances SET state='dissolving',dissolution_until=? WHERE id=?",(until,alliance['id']))
            for cid in cohort:
                db.execute('INSERT INTO alliance_cooldowns VALUES (?,?,?) ON CONFLICT(clan_id) DO UPDATE SET until=excluded.until,alliance_id=excluded.alliance_id',(cid,until,alliance['id']))
            db.execute('DELETE FROM alliance_invites WHERE alliance_id=?',(alliance['id'],))
            self._audit(db,alliance['id'],account,'dissolve',dict(clans=cohort,cooldown_until=until),cohort,now)

    def restore(self,account):
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);_,alliance,clans=self._owned(db,account,pending=True)
            if alliance['dissolution_until']<=now:raise AllianceRejected('Срок отмены роспуска истёк')
            cohort=[c['id'] for c in clans];self._guard(db,cohort)
            for cid in cohort:
                row=db.execute('SELECT until,alliance_id FROM alliance_cooldowns WHERE clan_id=?',(cid,)).fetchone()
                if row!=(alliance['dissolution_until'],alliance['id']):raise AllianceRejected('Отсрочка клана изменилась после роспуска')
            db.execute("UPDATE alliances SET state='active',dissolution_until=NULL WHERE id=?",(alliance['id'],))
            db.execute('DELETE FROM alliance_cooldowns WHERE alliance_id=?',(alliance['id'],))
            self._audit(db,alliance['id'],account,'restore',dict(clans=cohort),cohort,now)
