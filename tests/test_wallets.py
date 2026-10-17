import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from tio.wallets import WalletStore
from tio.protocol.asset_count import AssetCount, encode_asset_count, decode_asset_count
from tio.protocol.binary import PacketError


class WalletTests(unittest.TestCase):
    def test_starting_funds_and_no_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wallet.sqlite3'
            self.assertEqual(WalletStore(path).ensure('alice'), AssetCount(3000, 0))
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE wallets SET credits=9900,gold=9999 WHERE account=?', ('alice',))
            self.assertEqual(WalletStore(path).ensure('alice'), AssetCount(9900, 9999))
            self.assertEqual(WalletStore(path).ensure('bob'), AssetCount(3000, 0))
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE wallets SET credits=0,gold=0 WHERE account=?', ('alice',))
            self.assertEqual(WalletStore(path).ensure('alice'), AssetCount(0, 0))
            with self.assertRaises(ValueError):
                WalletStore(path).ensure('')

    def test_wire_and_invalid_packets(self):
        for value in (AssetCount(3000, 0), AssetCount(0xffffffff, 0, optional_raw=(2**64-1, 2**32-1))):
            packet = encode_asset_count(value)
            self.assertEqual(decode_asset_count(packet), value)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):
                    decode_asset_count(packet[:end])
            with self.assertRaises(PacketError):
                decode_asset_count(packet + b'\0')
        with self.assertRaises(PacketError):
            decode_asset_count(encode_asset_count(AssetCount(1, 2))[:-1] + b'\x02')
        with self.assertRaises(PacketError):
            encode_asset_count(AssetCount(-1, 2))
