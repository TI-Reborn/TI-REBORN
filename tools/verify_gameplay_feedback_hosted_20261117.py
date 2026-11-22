"""Two disposable excluded accounts exercise published services over public TLS."""
import json
from pathlib import Path
import secrets
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
# Bind current packages before historical QA helpers prepend candidate directories.
import tio
import server
saved_path = list(sys.path)
from tools.verify_game_operations_hosted import CREATE, CLEANUP, remote
sys.path[:] = saved_path
from tools.verify_training_base_20261018_hosted import PREPARE
sys.path[:] = saved_path
from tools.verify_launcher_required_hosted_20261020 import Network as HostedNetwork
sys.path[:] = saved_path
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.item_list import decode_item_list
from tio.protocol.item_marks import metadata
from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import WarehouseTransfer, encode_warehouse_transfer

OUT = ROOT / 'reports/gameplay-20261117'
PRIVATE = ROOT / '.secrets/gameplay-feedback-20261117.json'


class Network(HostedNetwork):
    def command(self, i, packet=b'\x70', expected=None, notice=None):
        peer = self.peers[i]
        if packet != b'\x70':
            peer.send(packet)
        peer.send(b'\x70')
        rows = []
        fenced = False
        notified = notice is None
        deadline = time.monotonic() + 30
        for _ in range(4096):
            peer.sock.settimeout(max(.001, deadline-time.monotonic()))
            row = peer.receive()
            rows.append(row)
            if row.startswith(b'\xf0\x8a\x01\0\0'):
                message = row[13:-2].decode('utf-16-le')
                # The native bank uses the same dialog packet for success and errors.
                assert message in ('Метка установлена. Списано 100 кр.',
                                   'Предмет возвращён владельцу.'), message
                notified |= message == notice
            fenced |= row == b'\x9e'
            if fenced and notified and (expected is None or any(r.startswith(expected) for r in rows)):
                return rows
        raise AssertionError('Missing native response')

    def warehouse(self, i, accepts):
        # Passive clan snapshots can precede the explicit query's response.
        observed = []
        for _ in range(10):
            rows = self.command(i, b'\x69\x01', expected=b'\x6a')
            for packet in rows:
                if packet[:5] == b'\x6a\x01\0\0\0':
                    observed.append(packet.hex())
                    if accepts(packet):
                        return packet
        raise AssertionError('Expected shared warehouse state missing: '+repr(observed))


def cleanup(data):
    code = CLEANUP
    if data.get('clan'):
        code = code.replace("tables=[r[0]", "cid=request['clan'];assert db.execute('SELECT leader FROM clans WHERE id=?',(cid,)).fetchone()==(names[0],)\n assert {r[0] for r in db.execute('SELECT account FROM clan_members WHERE clan_id=?',(cid,))}<=set(names)\n tables=[r[0]")
        old = "condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
        new = "\n  if 'clan_id' in columns:parts.append(quote('clan_id')+'=?');args.append(cid)\n  if table=='clans':parts.append('id=?');args.append(cid)\n  condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
        assert old in code
        code = code.replace(old, new)
    result = remote(code, dict(names=data['names'], clan=data.get('clan'),
                              protected_before=data['provision']['protected_before'], require_unchanged_players=False))
    (OUT / 'hosted-fixture-cleanup.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    PRIVATE.unlink()
    return result


def main():
    assert not PRIVATE.exists(), 'Inspect and clean up the previous owned fixtures first'
    prefix = 'qt' + secrets.token_hex(4)
    data = dict(names=[prefix+'a', prefix+'b'], passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision'] = remote(CREATE, list(zip(data['names'], data['passwords'])))
    PRIVATE.write_text(json.dumps(data), encoding='utf-8')
    net = Network(data)
    report = dict(passed=False, public_tls=True, graphical_clients=False, checks=[])
    try:
        prep = PREPARE.replace('19,*center(19)', '2,*center(2)')
        prep = prep[:prep.index('print(json.dumps')]+r"""
from tio.wallets import WalletStore
from tio.crystal_market import CrystalMarket
from tio.protocol.item_list import ItemRecord
CrystalMarket(path)
for name in request:
 WalletStore(path).ensure(name)
 with sqlite3.connect(path) as db:
  db.execute('UPDATE wallets SET credits=250000 WHERE account=?',(name,))
  db.execute('INSERT INTO crystal_wallets VALUES (?,1000)',(name,))
  item=ItemRecord(91001,306,bytes(2),1,0,0,(300,300,300),bytes(4),None,bytes(3))
  db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,(item,)),name))
print(json.dumps(dict(ranking_excluded=True,owned_fixtures_only=True)))
"""
        remote(prep, data['names'])
        for i in (0, 1):
            net.connect(i)
            rows = net.command(i, b'\xb0\x21', expected=b'\xb0\x20')
            quote = next(p for p in rows if p[:2] == b'\xb0\x20')
            assert struct.unpack_from('<f', quote, 2)[0] == 50
            net.command(i, b'\xb0\x1d' + struct.pack('<i', 1000), expected=b'\xb0\x1f')
            rows = net.command(i, b'\x73\0', expected=b'\x74')
            offers = decode_item_shop(next(p for p in rows if p[:1] == b'\x74'))[1]
            offer = next(o for o in offers if o.item_id == 129)
            rows = net.command(i, encode_shop_purchase(ShopPurchase(1, 0, offer.unknown_u32_01, 2)), expected=b'\x30')
            bags = [decode_item_list(p)[1] for p in rows if p[:1] == b'\x30']
            assert any(sum(item.count for item in bag if item.template_id == 129) == 2 for bag in bags)
        report['checks'].append('Both accounts see 50 credits and buy LE kits in the shared shop')
        sales = remote("import sqlite3,json\nwith sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:\n print(json.dumps([db.execute('SELECT amount,credits,rate FROM crystal_sales WHERE account=?',(n,)).fetchall() for n in request]))", data['names'])
        assert sales == [[[1000, 50000, 500000000]], [[1000, 50000, 500000000]]]
        report['checks'].append('Each 1000-crystal sale credits exactly 50000 credits')
        rows = net.command(0, b'\x52' + ('QA'+prefix[2:]).encode() + b'\0', expected=b'\x5e')
        data['clan'] = struct.unpack_from('<I', next(p for p in rows if p[:1] == b'\x5e'), 1)[0]
        PRIVATE.write_text(json.dumps(data), encoding='utf-8')
        net.command(0, b'\x5b' + data['names'][1].encode() + b'\0')
        net.command(1, expected=b'\x5c')
        net.command(1, b'\x5d\x01', expected=b'\x5e')
        net.command(0, b'\xb8\x01'+struct.pack('<IH', 91001, 1)+b'57163809\0',
                    expected=b'\xc8\x29', notice='Метка установлена. Списано 100 кр.')
        net.command(0, encode_warehouse_transfer(WarehouseTransfer(1, 1, ((91001, 1),), ())), expected=b'\x6a')
        packet = net.warehouse(1, lambda p: any(name == data['names'][0]
                                               for name, seconds in metadata(p).values()))
        packets = [packet]
        (OUT / 'hosted-mark-projection.json').write_text(json.dumps(dict(
            packets=[p.hex() for p in packets],
            ledger=remote("import sqlite3,json\nwith sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:\n print(json.dumps(db.execute('SELECT owner,holder,current_instance,state FROM bank_item_marks WHERE owner=?',(request,)).fetchall()))", data['names'][0])), indent=2), encoding='utf-8')
        assert struct.unpack_from('<I', packet, 9)[0] == 1
        instance, template, quantity = struct.unpack_from('<III', packet, 13)
        assert (template, quantity, packet[34]) == (306, 1, 1)
        assert metadata(packet)[instance][0] == data['names'][0]
        rows = net.command(0, b'\xb8\x04', expected=b'\xc8\x29')
        listing = next(p for p in rows if p[:2] == b'\xc8\x29')
        count, reference = struct.unpack_from('<II', listing, 2)
        assert count == 1
        net.command(0, b'\xb8\x03'+struct.pack('<IB', reference, 1), notice='Предмет возвращён владельцу.')
        net.warehouse(1, lambda p: not decode_warehouse_list(p)[3])
        report['checks'].append('Native clan deposit, peer owner-mark projection and owner recall from clan storage')
        report['passed'] = True
    finally:
        net.close()
        report['cleanup'] = cleanup(data)
        (OUT / 'hosted-two-account.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
