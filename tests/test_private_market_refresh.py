"""A native locally closed window must stay closed during an asset poll."""
import unittest
from unittest.mock import patch

import test_private_market as fixtures
from server.private_market import PrivateMarketSession
from tio.protocol import sc_auction_view as sc
from tio.protocol.asset_count import decode_asset_count


class NativeMarketRefreshTests(unittest.TestCase):
    def test_sc_local_close_does_not_allow_passive_f8_reopen_or_advance_quote(self):
        f=fixtures.MarketTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        from tio.sc_auction import SCAuctionStore,policy
        now=1791600000;auction=SCAuctionStore(f.path,rules=policy());auction.tick(now=now)
        session=PrivateMarketSession(f.shops,auction,'Alice',clock=lambda:now)
        initial=session.handle_sc(b'\xbd\x01\0\0\0')
        self.assertEqual(sc.decode(initial[0])[0],1)
        quotes=dict(session.sc_quotes)
        # Native Close has no outgoing packet. The server retains sc_open=True,
        # but that stale observation must not display a window on its next poll.
        with patch('server.private_market.time.monotonic',return_value=10):passive=session.refresh()
        self.assertFalse(any(p[:1] in (b'\xae',b'\xf8') for p in passive))
        self.assertEqual(session.sc_quotes,quotes)
        self.assertEqual(decode_asset_count(passive[0]).credits,f.balance('Alice'))
        refreshed=session.handle_sc(b'\xbd\x12')
        self.assertEqual(sc.decode(refreshed[0])[0],1)


if __name__=='__main__':unittest.main()
