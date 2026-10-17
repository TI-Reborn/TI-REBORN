"""CityV1 account/request identity fence over original helper namespaces.

Financial/base safe receipts use one immutable journal. Item-mark operations
retain their original accepted receipts and PIN budgets; only their non-PIN
arguments enter this namespace. Failed PIN attempts commit the existing budget
and namespace, but never an accepted safe receipt. No historical backfill.
"""
import json
from tio import bank_economy as bank

MARK_ACTIONS=frozenset(('mark','lend','reclaim'))


def schema(db):
    if not db.in_transaction:raise RuntimeError('City nonce requires authoritative transaction')
    db.execute('''CREATE TABLE IF NOT EXISTS city_v1_requests(account TEXT NOT NULL,identity TEXT NOT NULL,
        action TEXT NOT NULL,request TEXT NOT NULL,PRIMARY KEY(account,identity))''')
    db.execute('''CREATE TABLE IF NOT EXISTS city_v1_receipts(account TEXT NOT NULL,identity TEXT NOT NULL,
        receipt TEXT NOT NULL,PRIMARY KEY(account,identity))''')
    for table in ('city_v1_requests','city_v1_receipts'):
        for verb in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'City receipts are immutable'); END")


def request(data):
    return bank.canonical({key:value for key,value in data.items() if key not in ('username','slot','requestId','pin')})


def original_actions(db,owner,identity):
    """Reject old cross-helper/action collisions without rewriting their rows."""
    actions=[]
    if bank.table(db,'bank_economy_receipts'):
        for operation,raw in db.execute('SELECT operation,request FROM bank_economy_receipts WHERE account=? AND identity=?',(owner,identity)):
            if operation=='securities':
                payload=json.loads(raw);actions.append(payload['kind']+'_'+payload['operation'])
            else:actions.append(operation)
    if bank.table(db,'clan_benefit_receipts'):
        for operation, in db.execute('SELECT operation FROM clan_benefit_receipts WHERE account=? AND identity=?',(owner,identity)):
            actions.append({'fund':'base_fund','city_base_tax':'base_tax','city_base_time':'base_time'}.get(operation,operation))
    return actions


def before(db,owner,data):
    schema(db);identity=data['requestId'];action=data['action'];canonical=request(data)
    old=db.execute('SELECT action,request FROM city_v1_requests WHERE account=? AND identity=?',(owner,identity)).fetchone()
    if old and old!=(action,canonical):raise bank.BankRejected('ID уже относится к другой городской операции')
    original=original_actions(db,owner,identity)
    if len(original)>1 or any(kind!=action for kind in original):raise bank.BankRejected('ID уже принят другой операцией')
    if not old:db.execute('INSERT INTO city_v1_requests VALUES (?,?,?,?)',(owner,identity,action,canonical))
    accepted=db.execute('SELECT receipt FROM city_v1_receipts WHERE account=? AND identity=?',(owner,identity)).fetchone()
    if accepted:
        if action in MARK_ACTIONS:raise bank.BankRejected('Недопустимая квитанция предметной операции')
        return json.loads(accepted[0])


def accept(db,owner,data,receipt):
    if data['action'] in MARK_ACTIONS:return
    schema(db)
    db.execute('INSERT INTO city_v1_receipts VALUES (?,?,?)',(owner,data['requestId'],bank.canonical(receipt)))
