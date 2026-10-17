from contextlib import closing
from types import SimpleNamespace
import threading
import unittest

import test_clan_benefits as fixture
import test_clan_benefits_integration as integration
from tio import clan_benefits as benefits
from tio.db_transaction import transaction
from tio.battle_item_effects import freeze_rank_kills
from tio.battle_snapshot import dumps,loads
from tio.protocol.clan_crests import decode_content,encode_request
from tio.protocol.clans import encode_info
from tio.protocol.binary import Reader
from server import clan_gameplay,clan_service


class ClanGameplayTests(unittest.TestCase):
    setUp=fixture.ClanBenefitTests.setUp
    read=fixture.ClanBenefitTests.read
    call=fixture.ClanBenefitTests.call
    event=fixture.ClanBenefitTests.event

    def test_private_fund_replay_and_leader_city_gates(self):
        self.event(finalized=False)
        args=('alice','!base fund event1 101 request_12345678')
        with transaction(self.path) as db:
            first=clan_gameplay.command(db,*args,city_idle=True)
            self.assertEqual(first,clan_gameplay.command(db,*args,city_idle=True))
        self.assertEqual(self.read('SELECT credits FROM clans WHERE id=1'),[(9899,)])
        self.assertEqual(self.read('SELECT credits FROM clan_defense_funds'),[(101,)])
        self.assertIn('101 кредитов'.encode('utf-16le'),first[0])
        for account,allowed in (('alice',False),('bob',True)):
            with self.assertRaises(ValueError),transaction(self.path) as db:
                clan_gameplay.command(db,account,args[1],city_idle=allowed)
        self.assertEqual(self.read('SELECT credits FROM clan_defense_funds'),[(101,)])

    def test_week_poll_pending_event_and_closed_history_does_not_starve(self):
        self.event(finalized=False,ends=self.week+100)
        with transaction(self.path) as db:
            for n in range(1,12):
                week=self.week-n*benefits.WEEK
                db.execute('INSERT INTO clan_weeks VALUES (?,?)',(week,'[]'))
                db.execute('INSERT INTO clan_assault_totals VALUES (?,?,?,?)',(str(n),1,week,10))
            clan_gameplay.maintenance(db,now=self.week+benefits.WEEK+10)
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_weekly_badges'),[(0,)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_weeks WHERE week_start=?',(self.week,)),[(0,)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_assault_prizes'),[(0,)])

    def test_real_badge_expiry_unique_death_and_snapshot(self):
        combat=integration.WeeklyRankIntegrationTests().combat()
        combat.persistence={1:(self.path,'alice')}
        start=self.week+benefits.WEEK;expires=start+benefits.WEEK
        with transaction(self.path) as db:
            db.execute('INSERT INTO clan_weekly_badges VALUES (?,?,?,?,?,?)',(self.week,1,1,5,start,expires))
            freeze_rank_kills(combat,[(1,2)],now=expires-1)
        self.assertEqual(combat.item_effects['weekly_rank'],{2:5})
        freeze_rank_kills(combat,[(1,2)],now=expires+1)
        restored,_=loads(dumps(combat));self.assertEqual(restored.item_effects['weekly_rank'],{2:5})
        from tio.battle_state import BattleActor
        combat.field._actors[3]=BattleActor(3,8,5,5,15,0,100);combat.resources[3]=1
        freeze_rank_kills(combat,[(1,3)],now=expires)
        self.assertEqual(combat.item_effects['weekly_rank'],{2:5,3:0})
        combat.wager=True
        combat.item_effects['rank_bonus'].pop(3);combat.item_effects['weekly_rank'].pop(3)
        freeze_rank_kills(combat,[(1,3)],now=expires-1)
        self.assertEqual(combat.item_effects['weekly_rank'][3],0)

    def test_native_54_projects_stored_id_and_59_returns_exact_bmp(self):
        result=self.call(benefits.set_crest,'alice',fixture.bmp(),'crest-native')
        from tio.clans import membership
        with closing(__import__('sqlite3').connect(self.path)) as db:packet=encode_info(membership(db,'alice'))
        r=Reader(packet);self.assertEqual(r.u8(),0x54);r.u32()
        for _ in range(2):
            while r.u8():pass
        r.u8();self.assertEqual(r.u32(),result['crest_id'])
        presence=SimpleNamespace(lock=threading.RLock(),messages={})
        # A normal hashable session, as used by Presence queues.
        class Session:pass
        session=Session();session.database=self.path;presence.messages[session]=[]
        self.assertTrue(clan_service.handle(presence,session,encode_request(result['crest_id'])))
        content=decode_content(presence.messages[session][0]);self.assertEqual(content.bmp,fixture.bmp())
        self.assertEqual(content.crest_id,result['crest_id'])
        self.assertTrue(clan_service.handle(presence,session,encode_request(9999)))
        self.assertEqual(presence.messages[session][-1][:1],b'\xf0')


if __name__=='__main__':unittest.main()
