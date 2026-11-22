"""Two disposable excluded accounts buy warehouse tiers over public TLS.

Fixtures alone receive credits/items. No ordinary player rows are rewritten.
This verifies native packets, not graphical interaction.
"""
import argparse
import json
from pathlib import Path
import secrets
import struct
import sys
from xml.etree import ElementTree
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
saved = list(sys.path)
from tools import verify_mine_warehouses_hosted_20261023 as qa
sys.path[:] = saved
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.city_catalogs import decode_service_shop
from tio.protocol.shared_config import decode_shared_config_data
from tio.protocol.warehouse_capacity import OPT_IN, decode as decode_capacity
from tio.protocol.warehouse_transfer import WarehouseTransfer, encode_warehouse_transfer
from test_services import request

OUT = ROOT / 'reports/warehouse-expansion-20261101'
PRIVATE = ROOT / '.secrets/warehouse-expansion-20261101.json'
qa.OUT = OUT
TIERS = ((8, 5000), (16, 15000), (32, 30000), (64, 60000),
         (128, 120000), (256, 240000))

SEED = r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.item_list import ItemRecord,encode_item_list
names=request
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for name in names:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  assert not db.execute('SELECT 1 FROM paid_services WHERE account=?',(name,)).fetchone()
  db.execute('UPDATE wallets SET credits=1000000 WHERE account=?',(name,))
 for i in range(48):
  item=ItemRecord(1000+i,301,bytes(2),1,0,0,(300,)*3,bytes(4),None,bytes(3))
  db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',(names[0],1000+i,encode_item_list(0,(item,))))
  db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?)',(names[0],1000+i,'city',13,'owned-expansion-qa'))
print(json.dumps(dict(passed=True,ranking_excluded=True,fixture_only=True)))
'''


def provision() -> None:
    assert not PRIVATE.exists()
    prefix = 'qt' + secrets.token_hex(4)
    data = dict(names=[prefix + 'a', prefix + 'b'],
                passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision'] = qa.remote(qa.CREATE, list(zip(data['names'], data['passwords'])))
    PRIVATE.parent.mkdir(exist_ok=True)
    PRIVATE.write_text(json.dumps(data), encoding='utf-8')
    qa.remote(qa.PREPARE, data['names'])
    report = qa.remote(SEED, data['names'])
    (OUT / 'fixture-provisioning.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


class Network(qa.Network):
    def request(self, index: int, packet: bytes, *, reject: bool = False):
        rows = super().request(index, packet, reject=reject)
        if reject or packet[:2] not in (b'\xb1\2', b'\xb1\4'):
            return rows
        # Service replies can follow the transport ping from the command queue.
        for _ in range(4096):
            catalog = any(p[:2] == b'\xb1\3' for p in rows)
            statuses = [n for n, p in enumerate(rows) if p[:3] == b'\xb1\1\0']
            committed = statuses and any(p[:2] == b'\xc8\x39' for p in rows[statuses[-1] + 1:])
            if catalog and (packet[:2] == b'\xb1\2' or committed):
                return rows
            reply = self.peers[index].receive()
            assert reply[:5] != b'\xf0\x8a\1\0\0', 'Service rejected'
            rows.append(reply)
        raise AssertionError('Service reply missing after transport fence')

    def connect(self, index: int):
        captured = []
        handoff = self.tls.handoff

        def capture(*args, **kwargs):
            peer = handoff(*args, **kwargs)
            receive = peer.receive

            def record():
                packet = receive()
                captured.append(packet)
                return packet

            peer.receive = record
            return peer

        self.tls.handoff = capture
        try:
            super().connect(index)
        finally:
            self.tls.handoff = handoff
        packet = next(p for p in captured if p.startswith(b'\xb9\x03services\0'))
        data = decode_shared_config_data(packet)
        xml = zlib.decompress(data.compressed_bytes)
        assert len(xml) == data.decompressed_size
        node = ElementTree.fromstring(xml).find("service[@id='1']")
        assert [(int(n.get('val')), int(n.get('power'))) for n in node] == [
            (n, power) for n, (power, _) in enumerate(TIERS, 1)]
        assert [int(n.find("value[@key='power']").get('val')) for n in node] == [
            power for power, _ in TIERS]
        self.request(index, OPT_IN)
        return captured

    def capacity(self, index: int) -> int:
        rows = self.request(index, b'\x69\0')
        values = [decode_capacity(p) for p in rows if p.startswith(b'\xfa\1\1')]
        return next(v.capacity for v in reversed(values) if v.kind == 0)


def run() -> None:
    data = json.loads(PRIVATE.read_text())
    report = dict(passed=False, public_tls=True, graphical_clients=False, accounts=2,
                  shared_xml_delivered=True, tiers=[])
    net = Network(data)
    try:
        for index in (0, 1):
            net.connect(index)
        assert net.capacity(1) == 32
        rows = net.request(0, b'\xb8\x11')
        balance = decode_asset_count([p for p in rows if p[:2] == b'\xc8\x39'][-1]).credits
        report['initial_credits'] = balance
        for tier, (power, price) in enumerate(TIERS, 1):
            rows = net.request(0, b'\xb1\2')
            offer = next(o for o in decode_service_shop(next(p for p in rows if p[:2] == b'\xb1\3'))
                         if o.unknown_u32 == 1)
            assert offer.options[0].unknown_u8 == tier
            net.request(0, request(level=tier + 1), reject=True)
            if tier == 3:
                net.request(0, encode_warehouse_transfer(WarehouseTransfer(0, 1, ((300, 1),), ())), reject=True)
            rows = net.request(0, request(level=tier))
            balance -= price
            assert decode_asset_count([p for p in rows if p[:2] == b'\xc8\x39'][-1]).credits == balance
            # Retries over the genuine stream must neither spend again nor increase capacity.
            rows = net.request(0, request(level=tier))
            assert decode_asset_count([p for p in rows if p[:2] == b'\xc8\x39'][-1]).credits == balance
            assert net.capacity(0) == 32 + power and net.capacity(1) == 32
            if tier == 3:
                net.request(0, encode_warehouse_transfer(WarehouseTransfer(0, 1, ((300, 1),), ())))
            report['tiers'].append(dict(level=tier, capacity=32 + power, price=price, balance=balance))
        rows = net.request(0, b'\xb1\2')
        assert all(o.unknown_u32 != 1 for o in decode_service_shop(next(p for p in rows if p[:2] == b'\xb1\3')))
        net.request(1, request(level=1))
        assert net.capacity(1) == 40 and net.capacity(0) == 288
    finally:
        net.close()
    net = Network(data)
    try:
        for index in (0, 1):
            captured = net.connect(index)
            paid = [p for p in captured if p[:3] == b'\xb1\1\0' and struct.unpack_from('<I', p, 3)[0] == 1]
            assert paid[-1][11] == (6 if index == 0 else 1)
        assert [net.capacity(i) for i in (0, 1)] == [288, 40]
        report.update(passed=True, reconnect_preserved=True, retries_free=True,
                      skipped_levels_rejected=True, account_isolation=True, slot49_deposited=True)
    finally:
        net.close()
        (OUT / 'hosted-two-account.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


def cleanup() -> None:
    data = json.loads(PRIVATE.read_text())
    result = qa.remote(qa.CLEANUP, dict(names=data['names'],
                       protected_before=data['provision']['protected_before'],
                       require_unchanged_players=False))
    (OUT / 'fixture-cleanup.json').write_text(json.dumps(result, indent=2))
    PRIVATE.unlink()
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('provision', 'run', 'cleanup'))
    mode = parser.parse_args().mode
    {'provision': provision, 'run': run, 'cleanup': cleanup}[mode]()
