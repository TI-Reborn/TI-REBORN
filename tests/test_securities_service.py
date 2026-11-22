from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import struct
import tempfile
import threading
import unittest

from server.presence import Presence
from server import securities_service as service
from tio.characters import CharacterStore
from tio.onboarding import prepare
from tio.protocol import securities as wire
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.character_create import CharacterCreateRequest
from tio.wallets import NEW_CHARACTER_CREDITS, WalletStore

SALE_DAY = int(datetime(2026, 10, 8, 12, tzinfo=timezone.utc).timestamp())
REDEMPTION_DAY = int(datetime(2026, 10, 25, 12, tzinfo=timezone.utc).timestamp())


class Session:
    pass


class SecuritiesServiceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'state.db'; self.now = SALE_DAY
        characters = CharacterStore(self.path); self.presence = Presence(); self.sessions = {}
        hub = SimpleNamespace(lock=threading.RLock(), busy=lambda session: False, retained=lambda account: False,
                              private={}, account_owners={})
        router = SimpleNamespace(team_arena=hub, lock=threading.RLock(), active_accounts={})
        for owner, name in (('alice-login', 'Alice'), ('bobby-login', 'Bobby')):
            characters.create(owner, CharacterCreateRequest(name.encode(), 0, (1, 0, 0, 0)))
            prepare(self.path, owner)
            session = Session(); session.__dict__.update(database=self.path, account=owner, owned_pet_probe=True, probe_character_id=1,
                arena=SimpleNamespace(_fields={}, rooms=SimpleNamespace(snapshot=lambda: ())),
                survival=SimpleNamespace(searching=lambda actor: False), router=router,
                locations=SimpleNamespace(current=lambda account: 3, travelling=lambda account: False))
            self.sessions[owner] = session; router.active_accounts[owner] = session
            self.presence.players[session] = (3, None); self.presence.messages[session] = deque()

    def send(self, owner, packet):
        session = self.sessions[owner]; self.presence.messages[session].clear()
        self.assertTrue(service.handle(self.presence, session, packet, clock=lambda: self.now))
        return tuple(self.presence.messages[session])

    @staticmethod
    def find(replies, prefix):
        return next(packet for packet in replies if packet[:len(prefix)] == prefix)

    def credits(self, owner):
        return WalletStore(self.path).ensure(owner).credits

    def test_other_packets_are_not_consumed(self):
        self.assertFalse(service.handle(self.presence, self.sessions['alice-login'], b'\xb7\x0b'))

    def test_enter_world_queries_return_the_shared_server_calendar_and_quote(self):
        bond = self.find(self.send('alice-login', b'\xc1\x01'), b'\xc1\x02')
        sale_from, sale_until, redemption_from, redemption_until, redemption, price = struct.unpack('<qqqqII', bond[3:])
        self.assertEqual(bond[2], 1)
        self.assertEqual((sale_from, sale_until), (int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()),
                                                   int(datetime(2026, 10, 21, tzinfo=timezone.utc).timestamp())-1))
        self.assertEqual((redemption_from, redemption_until), (int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp()),
                                                               int(datetime(2026, 10, 26, tzinfo=timezone.utc).timestamp())-1))
        self.assertEqual((redemption, price), (150, 150))
        pyramid = self.find(self.send('bobby-login', b'\xc1\x05'), b'\xc1\x06')
        self.assertEqual(pyramid, wire.encode_pyramid_config(wire.PyramidConfig(100, 100, 100)))

    def test_stock_trades_use_the_echoed_quote_and_update_native_assets(self):
        packet = b'\xc1\x07' + struct.pack('<II', 100, 3)
        assets = decode_asset_count(self.find(self.send('alice-login', packet), b'\xc8\x39'))
        self.assertEqual((assets.credits, assets.spectra_stock), (NEW_CHARACTER_CREDITS - 300, 3))
        self.now += 86400  # One UTC day raises the shared quote to 101.
        stale = self.send('bobby-login', packet)
        self.assertEqual(stale[0][:1], b'\xf0')
        self.assertEqual(self.find(stale, b'\xc1\x06'), wire.encode_pyramid_config(wire.PyramidConfig(101, 101, 101)))
        self.assertEqual(self.credits('bobby-login'), NEW_CHARACTER_CREDITS)
        sold = self.send('alice-login', b'\xc1\x08' + struct.pack('<II', 101, 3))
        self.assertEqual(decode_asset_count(self.find(sold, b'\xc8\x39')).spectra_stock, 0)
        self.assertEqual(self.credits('alice-login'), NEW_CHARACTER_CREDITS + 3)

    def test_bond_purchase_and_redemption_follow_the_monthly_windows(self):
        bought = self.send('alice-login', b'\xc1\x09' + struct.pack('<I', 2))
        self.assertEqual(decode_asset_count(self.find(bought, b'\xc8\x39')).spectra_bonds, 2)
        early = self.send('alice-login', b'\xc1\x03' + struct.pack('<II', 0, 2))
        self.assertEqual(early[0][:1], b'\xf0')
        self.now = REDEMPTION_DAY
        self.assertEqual(self.send('bobby-login', b'\xc1\x09' + struct.pack('<I', 1))[0][:1], b'\xf0')
        redeemed = self.send('alice-login', b'\xc1\x03' + struct.pack('<II', 0, 2))
        self.assertEqual(decode_asset_count(self.find(redeemed, b'\xc8\x39')).spectra_bonds, 0)
        self.assertEqual(self.credits('alice-login'), NEW_CHARACTER_CREDITS)
        self.assertEqual(self.credits('bobby-login'), NEW_CHARACTER_CREDITS)

    def test_redeeming_for_another_holder_is_refused(self):
        self.send('alice-login', b'\xc1\x09' + struct.pack('<I', 1)); self.now = REDEMPTION_DAY
        reply = self.send('bobby-login', b'\xc1\x03' + struct.pack('<II', 7, 1))
        self.assertEqual(reply[0][:1], b'\xf0')
        self.assertEqual(decode_asset_count(self.find(reply, b'\xc8\x39')).spectra_bonds, 0)
        self.assertEqual(WalletStore(self.path).ensure('alice-login').spectra_bonds, 1)

    def test_trades_require_an_idle_city_but_queries_do_not(self):
        session = self.sessions['alice-login']; session.survival.searching = lambda actor: True
        self.assertEqual(self.send('alice-login', b'\xc1\x09' + struct.pack('<I', 1))[0][:1], b'\xf0')
        self.assertEqual(self.credits('alice-login'), NEW_CHARACTER_CREDITS)
        self.assertTrue(self.find(self.send('alice-login', b'\xc1\x0c'), b'\xc1\x0d'))

    def test_histories_project_the_recorded_quotes(self):
        self.send('alice-login', b'\xc1\x05'); self.now += 86400
        history = self.find(self.send('alice-login', b'\xc1\x0a'), b'\xc1\x0b')
        count, = struct.unpack_from('<h', history, 2)
        points = [struct.unpack_from('<q4i', history, 4 + 24*i) for i in range(count)]
        self.assertEqual(points, [(SALE_DAY, 100, 100, 100, 100), (SALE_DAY+86400, 101, 101, 101, 101)])
        bonds = self.find(self.send('bobby-login', b'\xc1\x0c'), b'\xc1\x0d')
        self.assertEqual(bonds, wire.encode_bond_history(((self.now, 150),)))

    def test_malformed_requests_get_an_error_without_mutation(self):
        self.assertEqual(self.send('alice-login', b'\xc1\x09\x01')[0][:1], b'\xf0')
        self.assertEqual(self.send('alice-login', b'\xc1\x04')[0][:1], b'\xf0')
        self.assertEqual(self.credits('alice-login'), NEW_CHARACTER_CREDITS)


if __name__ == '__main__':
    unittest.main()
