"""Actual encrypted city sessions must not receive unsolicited market UI lists."""
import unittest


class NativeTradeRefreshTests(unittest.TestCase):
    def setUp(self):
        import test_multi_account as multiplayer
        self.game=multiplayer.MultiAccountTests()
        self.game.addCleanup=self.addCleanup
        self.game.setUp()

    def collect(self,peer):
        peer.send(b'\x70')
        packets=[]
        for _ in range(2048):
            packet=peer.receive()
            if packet==b'\x9e':return packets
            packets.append(packet)
        self.fail('Missing native ping acknowledgement')

    def force_poll(self,peer,account):
        session=self.game.server.multi.active_accounts[account]
        session.private_market.next_refresh=0
        session._economy_refresh_at=0
        # The first pong releases an already pending read; the second also
        # observes the following city-loop poll, without waiting on a timer.
        return self.collect(peer)+self.collect(peer)

    def test_login_and_poll_after_market_close_keep_ui_query_driven_for_two_accounts(self):
        self.game.start()
        peers={}
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=self.game.handoff(self.game.begin(account))
            records=self.game.character_screen(peer)
            self.assertEqual([record.name_bytes for record in records],[name.encode()])
            peer.send(bytes.fromhex('1701000000'))
            self.assertTrue(peer.receive().startswith(b'\x18'))
            peer.send(b'\x19')
            # Wait until the server has consumed the single-packet 19 phase
            # before sending a city ping; TCP may otherwise batch 19 and 70.
            first=peer.until(b'\x1a')
            bootstrap=[first]+self.collect(peer)
            self.assertTrue(any(packet[:1]==b'\x66' for packet in bootstrap))
            self.assertFalse(any(packet[:1]==b'\xae' for packet in bootstrap))
            peers[account]=peer
        for account,peer in peers.items():
            for kind in (0,1):
                peer.send(bytes((0xae,1,kind))+bytes(4))
                requested=self.collect(peer)
                self.assertEqual([packet[:2] for packet in requested if packet[:1]==b'\xae'],
                                 [b'\xae\2',b'\xae\4',b'\xae\5'])
                # Stock Close sends no request. Subsequent city polling must
                # still refresh personal assets, without reopening the list.
                passive=self.force_poll(peer,account)
                self.assertTrue(any(packet[:2]==b'\xc8\x39' for packet in passive))
                self.assertTrue(any(packet[:1]==b'\x6a' for packet in passive))
                self.assertFalse(any(packet[:1]==b'\xae' for packet in passive))


if __name__=='__main__':unittest.main()
