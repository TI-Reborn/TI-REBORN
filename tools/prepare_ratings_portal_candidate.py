"""Prepare only the two scoped published HTTP adapters for ratings review."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / 'reports/gameplay-completion/stage9-city/runtime'
TARGET = ROOT / 'reports/gameplay-followup/stage4-ratings/portal/runtime'
PINS = {
    'server/city_http.py': '21da093cd878b72fd4c0ed7d8758337636ca14b350d61ebd00ca4fdce75a98da',
    'server/bank_gateway.py': '3572b1f5fa23d3c39cf9e5ff79e8c8647b0ba1ec32b6bd3297f11608c6f4d058',
}


def replace(text, before, after):
    if text.count(before) != 1: raise ValueError('Unexpected published HTTP adapter')
    return text.replace(before, after)


def main():
    if TARGET.exists(): raise ValueError('Preserve scoped portal work')
    for name, pin in PINS.items():
        raw = (PUBLISHED / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin: raise ValueError('Published city source changed')
        text = raw.decode('utf-8').replace('\r\n', '\n')
        if name.endswith('city_http.py'):
            text = replace(text, 'from .city_operations import CityError, CityOperations\n',
                'from .city_operations import CityError, CityOperations\nfrom .ratings_public import RatingsPublic\n')
            text = replace(text, 'port=PORT, operations=None):', 'port=PORT, operations=None, ratings=None):')
            text = replace(text, 'self.router=router;self.operations=operations or CityOperations(router)\n',
                'self.router=router;self.operations=operations or CityOperations(router)\n        self.ratings=ratings or RatingsPublic(router)\n')
            text = replace(text, "('/v1/city/status', '/v1/city/action')", "('/v1/city/status', '/v1/city/action', '/v1/ratings/status')")
            text = replace(text, "result=service.operations.status(data) if self.path=='/v1/city/status' else service.operations.action(data)",
                "if self.path=='/v1/ratings/status':result=service.ratings.status(data)\n                    else:result=service.operations.status(data) if self.path=='/v1/city/status' else service.operations.action(data)")
        else:
            marker = "    def order_dto(data,order):\n"
            addition = '''    @app.post('/v1/ratings/status')
    def ratings_status():
        from .ratings_public import validate_payload,validate_response
        from .city_operations import CityError
        from .city_http import decode_json
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        if request.content_length is not None and request.content_length>4096:raise GatewayError('invalid_request',413)
        raw=request.get_data(cache=True)
        if len(raw)>4096:raise GatewayError('invalid_request',413)
        if request.mimetype!='application/json':raise GatewayError('invalid_request',415)
        try:data=validate_payload(decode_json(raw))
        except CityError as error:raise GatewayError(error.code,error.status) from None
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            if not db.execute('SELECT 1 FROM accounts WHERE login=?',(data['username'],)).fetchone():
                raise GatewayError('account_not_found',404)
        message=Request('http://127.0.0.1:8083/v1/ratings/status',
            data=json.dumps(data,separators=(',',':')).encode('utf-8'),
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        try:
            try:response=urlopen(message,timeout=3)
            except HTTPError as error:response=error
            with response:
                status=response.status
                if response.headers.get_content_type()!='application/json':raise ValueError('Invalid core reply')
                reply=response.read(65537)
            if len(reply)>65536 or status not in (200,400,404,413,429,503):raise ValueError('Invalid core reply')
            result=decode_json(reply)
            if status==200:validate_response(result,data)
            elif (not isinstance(result,dict) or set(result)!={'error'}
                  or result['error'] not in ('invalid_request','account_not_found','rate_limited','service_unavailable')):
                raise ValueError('Invalid core reply')
            return Response(reply,status=status,mimetype='application/json')
        except Exception:raise GatewayError('service_unavailable',503) from None

'''
            text = replace(text, marker, addition + marker)
        compile(text, name, 'exec')
        destination = TARGET / name; destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding='utf-8', newline='\n')
    print('Prepared two scoped city HTTP adapters; shared runtime untouched')


if __name__ == '__main__': main()
