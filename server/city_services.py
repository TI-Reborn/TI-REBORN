"""Separate services V2 operations in the authoritative city process."""
import json,re
from .city_operations import CityError,CityOperations,REQUEST_ID,number,public_name,validate_payload
from .economy_runtime import busy_accounts
from tio.services_completion import ServicesCompletion,ServiceRejected
from tio.db_transaction import transaction
from tio import warehouse_completion as warehouse
from tio.clans import membership
from .service_operations import CITY_SERVICE_FIELDS,prepare_service,execute_service

FIELDS=CITY_SERVICE_FIELDS
SERVICE_REQUEST_ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{15,63}')

def validate(data,*,action=False):
    if not action:return validate_payload(data)
    if not isinstance(data,dict) or not isinstance(data.get('action'),str) or data['action'] not in FIELDS:raise CityError('invalid_request')
    kind=data['action']
    if set(data)!={'username','slot','action','requestId'}|FIELDS[kind]:raise CityError('invalid_request')
    validate_payload({key:data[key] for key in ('username','slot')})
    if not isinstance(data['requestId'],str) or not SERVICE_REQUEST_ID.fullmatch(data['requestId']):raise CityError('invalid_request')
    for key in FIELDS[kind]-{'newName'}:number(data[key],0xffffffff)
    if kind=='warehouse_purchase' and (data['service'] not in (3,4) or data['wanted'] not in (1,2)):raise CityError('invalid_request')
    if kind=='service_rename' and (not isinstance(data['newName'],str) or not 1<=len(data['newName'])<=16):raise CityError('invalid_request')
    return data

class CityServices:
    def __init__(self,router,*,operations=None,helper=None):
        self.router=router;self.operations=operations or CityOperations(router);self.path=self.operations.path
        self.helper=helper or ServicesCompletion(self.path)
        from tio.warehouse import WarehouseStore
        WarehouseStore(self.path)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS services_v2_receipts(account TEXT NOT NULL,identity TEXT NOT NULL,request TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(account,identity))')
            for verb in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS services_v2_receipts_no_{verb.lower()} BEFORE {verb} ON services_v2_receipts BEGIN SELECT RAISE(ABORT,'Services receipts are immutable'); END")
    def _status(self,db,data,owner,blocked):
        base=self.operations._status(db,data,owner,blocked,int(self.operations.clock()))
        allowed=base['canOperate']
        clan=membership(db,owner) if owner else None
        return dict(version=2,**{key:base[key] for key in ('username','slot','characters','character','canOperate','balances')},
            services=self.helper.status(owner,allowed=allowed) if owner and base['balances'] else None,
            personalWarehouse=warehouse.status(db,owner) if owner and base['balances'] else None,
            clanWarehouse=warehouse.clan_status(db,owner) if clan and base['balances'] else None)
    def status(self,data):
        validate(data);self.operations._running()
        with self.router.team_arena.lock,transaction(self.path) as db:
            self.operations._running();owner=self.operations._resolve(db,data,optional=True)
            return self._status(db,data,owner,busy_accounts(self.router,db))
    def invalidate(self,owner):
        with self.router.lock:
            for session in self.router.active_accounts.values():
                if getattr(session,'account',None)==owner:
                    session._economy_inventory_digest=None
                    with transaction(self.path) as db:name=public_name(db,owner)
                    if name:session.probe_character_name=name.encode('cp1251')
    def action(self,data):
        validate(data,action=True);self.operations._running()
        with self.router.team_arena.lock:
            try:
                with transaction(self.path) as db:
                    self.operations._running();owner=self.operations._resolve(db,data);blocked=busy_accounts(self.router,db)
                    if not self.operations._available(db,owner,blocked)[0]:raise CityError('city_unavailable',409)
                    request=json.dumps({key:data[key] for key in ('action',*sorted(FIELDS[data['action']]))},sort_keys=True,separators=(',',':'),ensure_ascii=False)
                    prior=db.execute('SELECT request,receipt FROM services_v2_receipts WHERE account=? AND identity=?',(owner,data['requestId'])).fetchone()
                    if prior:
                        if prior[0]!=request:raise CityError('operation_rejected',409)
                        return dict(status=self._status(db,data,owner,blocked),receipt=json.loads(prior[1]),replayed=True)
                    kind=data['action']
                    command=prepare_service(kind,data['requestId'],{key:data[key] for key in FIELDS[kind]})
                    outcome=execute_service(command,db=db,path=self.path,helper=self.helper,owner=owner,allowed=True)
                    result=outcome.as_dict()
                    receipt={key:result['receipt'][key] for key in ('requestId','action','creditsDelta','goldDelta')}
                    db.execute('INSERT INTO services_v2_receipts VALUES (?,?,?,?)',(owner,data['requestId'],request,json.dumps(receipt,sort_keys=True)))
                    response=dict(status=self._status(db,data,owner,blocked),receipt=receipt,replayed=result['replayed'])
                if outcome.changed_owners:self.invalidate(owner)
                return response
            except (ServiceRejected,ValueError):raise CityError('operation_rejected',409) from None
