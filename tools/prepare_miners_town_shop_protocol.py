"""Apply one catalogue rejection boundary to the exact inspected host runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/gameplay-completion/miners-town-shop-20261010'
SOURCE = REPORT / 'baseline/runtime/tools/loopback_exchange.py'
TARGET = REPORT / 'runtime/tools/loopback_exchange.py'
SOURCE_SHA256 = '77faef28e94471cd24deb7397c72cb45a6788a92e408f00594a4aa8359da89b6'

BEFORE = r"""                    reply=city_service_reply(packet,self.catalogs)
                    if reply is not None and packet[:1] in (b'\x73',b'\x76') and self.database is not None:
                        from tio.premium import current
                        discounted=bool(current(self.database,self.account)[0])
                        if packet[:1]==b'\x73':reply=ShopStore(self.database,self.catalogs).catalog(self.account,packet[1],discounted=discounted)
                        else:
                            from tio.protocol.premium_shop import decode_premium_request
                            reply=ShopStore(self.database,self.catalogs).catalog(self.account,decode_premium_request(packet),gold=True,discounted=discounted)
""".encode()
AFTER = r"""                    try:
                        reply=city_service_reply(packet,self.catalogs)
                        if reply is not None and packet[:1] in (b'\x73',b'\x76') and self.database is not None:
                            from tio.premium import current
                            discounted=bool(current(self.database,self.account)[0])
                            if packet[:1]==b'\x73':reply=ShopStore(self.database,self.catalogs).catalog(self.account,packet[1],discounted=discounted)
                            else:
                                from tio.protocol.premium_shop import decode_premium_request
                                reply=ShopStore(self.database,self.catalogs).catalog(self.account,decode_premium_request(packet),gold=True,discounted=discounted)
                    except ValueError as error:
                        if packet[:1] not in (b'\x73',b'\x76'):raise
                        self.events.append({'event':'shop_catalog_rejected','reason':str(error),'request_hex':packet.hex()})
                        reply=shop_error_reply(error)
""".encode()


def patch_source(raw):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256 or raw.count(BEFORE) != 1:
        raise ValueError('Exact fresh inspected hosted catalogue boundary required')
    start = raw.index(BEFORE)
    result = raw[:start] + AFTER + raw[start + len(BEFORE):]
    assert result[:start] == raw[:start]
    assert result[start + len(AFTER):] == raw[start + len(BEFORE):]
    compile(result, 'tools/loopback_exchange.py', 'exec')
    return result, start


def main():
    source = SOURCE.read_bytes()
    candidate, start = patch_source(source)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        if TARGET.read_bytes() != candidate:
            raise ValueError('Preserve a different existing scoped candidate')
    else:
        with TARGET.open('xb') as output:
            output.write(candidate)
    proof = dict(source=str(SOURCE.resolve()), source_sha256=SOURCE_SHA256,
                 source_size=len(source), path=str(TARGET.resolve()),
                 sha256=hashlib.sha256(candidate).hexdigest(), size=len(candidate),
                 changed_boundary=dict(offset=start, before_bytes=len(BEFORE), after_bytes=len(AFTER)),
                 all_bytes_outside_catalogue_boundary_preserved=True,
                 catches_only_value_errors_for_opcodes=['73', '76'],
                 other_errors_and_other_services_unchanged=True, remote_mutations=0)
    destination = REPORT / 'protocol-scope.json'
    raw = (json.dumps(proof, indent=2) + '\n').encode()
    if destination.exists():
        if destination.read_bytes() != raw:
            raise ValueError('Preserve earlier protocol scope evidence')
    else:
        with destination.open('xb') as output:
            output.write(raw)
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
