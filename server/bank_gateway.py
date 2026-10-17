"""Loopback-only portal bank adapter; Stripe secrets never leave this process.

The portal supplies its verified linked game login, never an arbitrary save
owner. Slots resolve through authoritative character ownership mappings. Every
route, including raw webhook relay, requires the private service bearer key.
"""
from collections import deque
from contextlib import closing
from ipaddress import ip_address
from pathlib import Path
import hmac
import json
import os
import re
import sqlite3
import struct
import threading
import time

from flask import Flask,jsonify,request,Response
from werkzeug.exceptions import HTTPException
from server.accounts import Accounts,identity
from tio.bank_economy import BankStore,BankRejected,StripeCheckout
from tio.character_identity import owner_for_slot,MAX_CHARACTERS
from tio.db_transaction import transaction
from tio.clans import membership,CREST,ClanRejected
from tio.clan_benefits import set_crest,crest_id,crest_content,validate_crest
from tio.alliances import AlliancesStore,alliance_for_clan

REQUEST_ID=re.compile(r'[A-Za-z0-9_-]{16,128}\Z')
ORDER_ID=re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}\Z')


class GatewayError(Exception):
    def __init__(self,code,status=400):self.code,self.status=code,status


class Budget:
    def __init__(self):self.lock=threading.Lock();self.times={};self.checkout_slots=threading.BoundedSemaphore(4)
    def allow(self,scope,limit):
        now=time.monotonic()
        with self.lock:
            times=self.times.setdefault(scope,deque())
            while times and now-times[0]>=60:times.popleft()
            if len(times)>=limit:return False
            times.append(now);return True


def merchant_config(environ=None):
    env=os.environ if environ is None else environ;path=env.get('TIO_BANK_MERCHANT_CONFIG')
    if not path:return {}
    raw=Path(path).read_bytes()
    if len(raw)>4096:raise ValueError('Merchant configuration is too large')
    values=json.loads(raw)
    if not isinstance(values,dict) or set(values)-{'enabled','type','currency','minor_units_per_gold','success_url','cancel_url','require_livemode','minimum_gold','maximum_gold','signature_tolerance_seconds'}:raise ValueError('Invalid merchant configuration')
    return values


def create_app(database,key,*,bank=None):
    if not isinstance(key,str) or not 32<=len(key)<=512:raise ValueError('Bank service key requires 32..512 characters')
    path=Path(database).resolve();Accounts(path).check()
    bank=BankStore(path,provider=StripeCheckout(merchant_config())) if bank is None else bank
    if Path(bank.path).resolve()!=path:raise ValueError('Bank gateway cannot span databases')
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=262144;budget=Budget()

    @app.before_request
    def authorize():
        try:loopback=ip_address(request.remote_addr or '').is_loopback
        except ValueError:loopback=False
        if not loopback:raise GatewayError('unauthorized',403)
        supplied=request.headers.get('Authorization','');expected='Bearer '+key
        if len(supplied)>1024 or not hmac.compare_digest(supplied.encode(),expected.encode()):raise GatewayError('unauthorized',401)
        if not budget.allow('webhook' if request.path=='/v1/bank/stripe/webhook' else 'private',600 if request.path=='/v1/bank/stripe/webhook' else 240):raise GatewayError('rate_limited',429)

    @app.after_request
    def security_headers(response):
        if not (request.method=='GET' and request.path.startswith('/v1/clan/crests/') and response.status_code==200):
            response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff';return response

    @app.errorhandler(GatewayError)
    def controlled(error):return jsonify(error=error.code),error.status

    @app.errorhandler(HTTPException)
    def http_error(error):return jsonify(error='invalid_request'),error.code

    @app.errorhandler(Exception)
    def unavailable(error):
        app.logger.warning('Bank gateway unavailable: %s',type(error).__name__)
        return jsonify(error='service_unavailable'),503

    def payload(fields):
        if request.content_length is not None and request.content_length>4096:raise GatewayError('invalid_request',413)
        raw=request.get_data(cache=True)
        if len(raw)>4096:raise GatewayError('invalid_request',413)
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or set(data)!=set(fields):raise GatewayError('invalid_request')
        try:identity(data['username'])
        except (KeyError,ValueError):raise GatewayError('invalid_request') from None
        if type(data['slot']) is not int or not 1<=data['slot']<=MAX_CHARACTERS:raise GatewayError('invalid_request')
        return data

    def linked(db,data,*,optional=False):
        if not db.execute('SELECT 1 FROM accounts WHERE login=?',(data['username'],)).fetchone():raise GatewayError('account_not_found',404)
        try:return owner_for_slot(db,data['username'],data['slot'])
        except ValueError:
            if optional:return None
            raise GatewayError('character_required',409) from None

    def order_dto(data,order):
        return dict(username=data['username'],slot=data['slot'],order={k:order[k] for k in ('id','gold','amount_minor','currency','state','url','created')})

    def clan_dto(db,data,owner):
        clan=membership(db,owner) if owner else None
        alliance=alliance_for_clan(db,clan['id']) if clan else None
        wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(owner,)).fetchone() if owner and db.execute("SELECT 1 FROM sqlite_master WHERE name='wallets'").fetchone() else None
        characters=[]
        for slot in range(1,MAX_CHARACTERS+1):
            try:save_owner=owner_for_slot(db,data['username'],slot)
            except ValueError:continue
            row=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(save_owner,)).fetchone()
            if row:characters.append(dict(slot=slot,name=bytes(row[0]).decode('cp1251')))
        return dict(username=data['username'],slot=data['slot'],characters=characters,
            character=next((c['name'] for c in characters if c['slot']==data['slot']),None),credits=wallet[0] if wallet else None,
            clan=dict(id=clan['id'],name=clan['name'].decode('cp1251'),crestId=crest_id(db,clan['id'])) if clan else None,
            alliance=dict(id=alliance['id'],name=alliance['name'].decode('cp1251'),crestId=alliance['crest_id'],
                canUpload=bool(wallet and clan['id']==alliance['leading_clan'] and clan['leader']==owner)) if alliance else None,
            canUpload=bool(clan and wallet and (clan['leader']==owner or clan['permissions']&CREST)),cost=1000)

    @app.post('/v1/clan/status')
    def clan_status():
        data=payload(('username','slot'))
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN');owner=linked(db,data,optional=True);result=clan_dto(db,data,owner)
        return jsonify(result)

    @app.post('/v1/clan/assault')
    def clan_assault():
        from .assault_public import snapshot,MAX_MEDAL_PAGE
        data=payload(('username','slot','page'))
        if type(data['page']) is not int or not 1<=data['page']<=MAX_MEDAL_PAGE:
            raise GatewayError('invalid_request')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            owner=linked(db,data);character=clan_dto(db,data,owner)
            result=dict(username=data['username'],slot=data['slot'],
                characters=character['characters'],character=character['character'],
                assault=snapshot(db,owner,medal_page=data['page']))
        return jsonify(result)

    @app.post('/v1/clan/crest')
    def clan_crest():
        if request.mimetype!='image/bmp':raise GatewayError('invalid_request',415)
        if request.content_length is not None and request.content_length>824:raise GatewayError('invalid_request',413)
        raw=request.stream.read(825)
        if len(raw)>824:raise GatewayError('invalid_request',413)
        username=request.headers.get('X-Game-Username','');slot=request.headers.get('X-Character-Slot','');operation=request.headers.get('X-Request-ID','')
        kind=request.headers.get('X-Crest-Kind','clan');remove=request.headers.get('X-Crest-Remove','0')
        try:identity(username)
        except ValueError:raise GatewayError('invalid_request') from None
        if not re.fullmatch('[1-5]',slot) or not REQUEST_ID.fullmatch(operation) or kind not in ('clan','alliance') or remove not in ('0','1') or remove=='1' and (kind!='alliance' or raw):raise GatewayError('invalid_request')
        try:
            if remove!='1':
                validate_crest(raw)
                if struct.unpack_from('<i',raw,22)[0]!=16:raise ClanRejected('Native crest requires bottom-up BMP')
        except ClanRejected:raise GatewayError('invalid_crest') from None
        data=dict(username=username,slot=int(slot))
        try:
            with transaction(path) as db:
                owner=linked(db,data)
                result=AlliancesStore(path).set_crest(owner,None if remove=='1' else raw,operation) if kind=='alliance' else set_crest(db,owner,raw,operation)
                status=clan_dto(db,data,owner)
        except ClanRejected:raise GatewayError('crest_rejected',409) from None
        return jsonify(**status,receipt=dict(crestId=result['crest_id'],charged=result['charged']))

    @app.get('/v1/clan/crests/<crest>')
    def clan_crest_content(crest):
        if not re.fullmatch('[1-9][0-9]{0,9}',crest) or int(crest)>0xffffffff:raise GatewayError('invalid_request')
        try:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('BEGIN');raw=crest_content(db,int(crest));digest=validate_crest(raw)
        except ClanRejected:raise GatewayError('crest_not_found',404) from None
        return Response(raw,mimetype='image/bmp',headers={'Cache-Control':'public, max-age=31536000, immutable','ETag':'"'+digest+'"','Content-Disposition':'inline'})

    @app.post('/v1/bank/status')
    def status():
        data=payload(('username','slot'))
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN');owner=linked(db,data,optional=True);wallet=None;character=None;payable='0';characters=[]
            for slot in range(1,MAX_CHARACTERS+1):
                try:save_owner=owner_for_slot(db,data['username'],slot)
                except ValueError:continue
                name=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(save_owner,)).fetchone()
                characters.append(dict(slot=slot,name=bytes(name[0]).decode('cp1251')))
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if owner:
                character=next((c['name'] for c in characters if c['slot']==data['slot']),None)
                wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(owner,)).fetchone() if 'wallets' in tables else None
                if 'bank_gold_payables' in tables:
                    row=db.execute('SELECT gold FROM bank_gold_payables WHERE account=?',(owner,)).fetchone()
                    if row:payable=str(row[0])
        configured=bank.status()['configured'];p=bank.provider.config if bank.provider else {}
        return jsonify(username=data['username'],slot=data['slot'],character=character,characters=characters,
            balances=dict(credits=wallet[0],gold=wallet[1],payable=payable) if wallet else None,
            configured=configured,canPurchase=bool(configured and wallet),reason=None if configured and wallet else 'not_configured' if not configured else 'character_required',
            currency=p.get('currency'),minorUnitsPerGold=p.get('minor_units_per_gold'),minimumGold=p.get('minimum_gold',1),maximumGold=p.get('maximum_gold'))

    @app.post('/v1/bank/orders')
    def create_order():
        data=payload(('username','slot','gold','requestId'))
        if type(data['gold']) is not int or not 1<=data['gold']<=100000 or not isinstance(data['requestId'],str) or not REQUEST_ID.fullmatch(data['requestId']):raise GatewayError('invalid_request')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:owner=linked(db,data)
        if not bank.status()['configured']:raise GatewayError('bank_not_configured',503)
        if not budget.allow('checkout',20) or not budget.checkout_slots.acquire(blocking=False):raise GatewayError('rate_limited',429)
        try:
            try:order=bank.create_order(owner,data['gold'],data['requestId'])
            except BankRejected:raise GatewayError('order_rejected',409) from None
            return jsonify(order_dto(data,order))
        finally:budget.checkout_slots.release()

    @app.post('/v1/bank/order')
    def order_status():
        data=payload(('username','slot','orderId'))
        if not isinstance(data['orderId'],str) or not ORDER_ID.fullmatch(data['orderId']):raise GatewayError('invalid_request')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:owner=linked(db,data)
        try:order=bank.order(owner,data['orderId'])
        except BankRejected:raise GatewayError('order_not_found',404) from None
        return jsonify(order_dto(data,order))

    @app.post('/v1/bank/stripe/webhook')
    def webhook():
        if not bank.status()['configured']:raise GatewayError('bank_not_configured',503)
        try:bank.callback(request.get_data(cache=False),{'Stripe-Signature':request.headers.get('Stripe-Signature','')})
        except BankRejected:raise GatewayError('invalid_webhook') from None
        return jsonify(received=True)

    return app


def main():
    from waitress import serve
    from server.config import ServerConfig
    config=ServerConfig.load(os.environ.get('TIO_CONFIG','/etc/tio-server/server.toml'))
    if not config.multi_account:raise ValueError('Bank gateway requires multi_account=true')
    app=create_app(config.database,os.environ.get('BANK_SERVICE_KEY'))
    serve(app,listen='127.0.0.1:8082',threads=4,connection_limit=24,channel_timeout=30,
        max_request_body_size=262144,clear_untrusted_proxy_headers=True)


if __name__=='__main__':main()
