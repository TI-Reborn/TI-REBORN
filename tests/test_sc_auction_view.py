import hashlib
import struct
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from deploy import client_sc_auction as client
from tio.protocol import sc_auction_view as wire
from tio.protocol.binary import PacketError
from verify_sc_view_native import NativeScene, BASE_CLIENT, sample_lot
from unicorn.x86_const import UC_X86_REG_EAX


class SCViewTests(unittest.TestCase):
    def test_catalogue_projection_exact_model(self):
        row=sample_lot(42);packet=wire.encode_catalogue((row,));op,rows=wire.decode(packet)
        self.assertEqual(op,1);raw,text,prizes=rows[0]
        self.assertEqual(len(raw),88);self.assertEqual(text,('SC 42','Alice','Фановый за кредиты'))
        self.assertEqual(prizes,((9,5,0),));self.assertEqual(struct.unpack_from('<I',raw)[0],42)
        self.assertEqual(struct.unpack_from('<III',raw,12),(100,101,101))
        self.assertEqual(struct.unpack_from('<II',raw,40),(290000,290000))
        self.assertEqual(raw[60:62],b'\1\0')

    def test_tab_category_and_cabinet_fields(self):
        row=sample_lot(2,state='delivered',enhanced=True)
        self.assertEqual(row['group'],'Дорогой за кредиты');self.assertTrue(row['bought'])
        self.assertEqual(row['state'],2);self.assertTrue(row['personal'])

    def test_history_maps_original_draw_switch(self):
        for action,opcode in (('created',1),('closed',2),('bid',4),('claim',7)):
            value=wire.history_view(dict(action=action,occurred=1791446500,amount=5,automatic=True),public_name='Алиса')
            self.assertEqual(value['action'],opcode)
            packet=wire.encode_history(42,(value,),page=2,pages=3,remaining_ms=9876)
            op,body=wire.decode(packet);self.assertEqual(op,2);self.assertEqual(body[:4],(42,2,3,9876))
            self.assertEqual(body[4][0][1],'Алиса')
        self.assertIsNone(wire.history_view({'action':'bot_refund'}))

    def test_bot_claim_clear(self):
        self.assertEqual(wire.decode(wire.encode_bot(42,5,100,200,7)),(3,(42,5,100,200,7)))
        op,fields=wire.decode(wire.encode_claim(42,101,0,1792051300,can_pay=True))
        self.assertEqual(op,4);self.assertEqual(fields,(42,wire.datetime_days(1792051300),101,0,1))
        self.assertEqual(wire.encode_clear(),b'\xf8\1\0')

    def test_counts_ids_pointer_padding_and_text_bounds(self):
        row=sample_lot()
        for rows in ((row,row),tuple(dict(row,id=i+1) for i in range(201))):
            with self.assertRaises(PacketError):wire.encode_catalogue(rows)
        for text in ('a'*257,'a\0b','\ud800','\U0001f680'):
            with self.assertRaises(PacketError):wire.encode_catalogue((dict(row,notes=text),))
        good=wire.encode_catalogue((row,))
        for offset in (5+52,5+10):
            bad=bytearray(good);bad[offset]=1
            with self.assertRaises(PacketError):wire.decode(bad)
        bad=bytearray(good);bad[-1]=1
        with self.assertRaises(PacketError):wire.decode(bad)

    def test_numerical_policy_guard(self):
        row=sample_lot()
        for field,value in (('price',-1),('price',2**31),('start_date',float('nan')),
                            ('weight',float('inf')),('can_bot',1),('currency',2)):
            with self.assertRaises(PacketError):wire.encode_catalogue((dict(row,**{field:value}),))
        with self.assertRaises(PacketError):wire.encode_claim(0,101,0,1792051300,can_pay=True)
        with self.assertRaises(PacketError):wire.encode_bot(1,5,0,0,-1)

    def test_snapshot_respects_two_byte_transport_prefix(self):
        self.assertEqual(wire.MAX_PACKET,65533)
        row=sample_lot()
        with self.assertRaises(PacketError):
            wire.encode_catalogue(tuple(dict(row,id=i+1,notes='x'*256) for i in range(110)))

    def test_all_truncation_boundaries_and_trailing_bytes(self):
        packets=(wire.encode_clear(),wire.encode_catalogue((sample_lot(),)),
            wire.encode_history(1,(),remaining_ms=100),wire.encode_bot(1,5,0,0,7),
            wire.encode_claim(1,101,0,1792051300,can_pay=False))
        for packet in packets:
            for length in range(len(packet)):
                with self.assertRaises(PacketError):wire.decode(packet[:length])
            with self.assertRaises(PacketError):wire.decode(packet+b'\0')


class SCPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=BASE_CLIENT.read_bytes();cls.updated=client.patch(cls.original)

    def test_exact_base_idempotence_preserved_hooks(self):
        self.assertEqual(hashlib.sha256(self.original).hexdigest(),client.BASE_SHA)
        self.assertEqual(client.patch(self.updated),self.updated)
        plan=client.patch_plan(self.original,self.updated)
        self.assertEqual(plan['appended_bytes'],8192);self.assertEqual(len(plan['changes']),4)
        self.assertTrue(plan['existing_f6_f7_and_four_other_item_hooks_preserved'])
        self.assertTrue(plan['all_stock_bd_builders_preserved'])

    def test_tampered_candidate_and_base_rejected(self):
        for value in (self.original,self.updated):
            bad=bytearray(value);bad[2000]^=1
            with self.assertRaises(ValueError):client.patch(bytes(bad))
        bad=bytearray(self.updated);bad[-100]^=1
        with self.assertRaises(ValueError):client.patch(bytes(bad))

    def test_native_invalid_snapshot_no_state_mutation(self):
        scene=NativeScene(candidate=self.updated);good=wire.encode_catalogue((sample_lot(),))
        scene.receive(good);saved=scene.get(0xacf418)
        for at,value in ((5+52,1),(5+8,3),(5+9,2),(5+60,2),(5+10,1),(5+44+3,255),(5+68+3,255)):
            bad=bytearray(good);bad[at]=value
            self.assertEqual(scene.receive(bad),0);self.assertEqual(scene.get(0xacf418),saved)
        for length in range(len(good)):
            if length==0:continue
            self.assertEqual(scene.receive(good[:length]),0);self.assertEqual(scene.get(0xacf418),saved)

    def test_native_entry_preserves_other_receivers(self):
        scene=NativeScene(candidate=self.updated)
        scene.u.mem_write(0xac64a0,struct.pack('<I',0x02004000))
        # F8 wrapper delegates to exact existing F7, including its cells state.
        scene.u.mem_write(0x02000000,b'\1\1\0\x05\x06\x02')
        scene.run(client.READER_ENTRY,eax=0xf7,edx=0x02000000,ecx=7)
        self.assertEqual(scene.get(0x400000+client.RVA+0x1bf8),1)
        self.assertEqual(bytes(scene.u.mem_read(0x400000+client.RVA+0x1c00,3)),b'\5\6\2')
        scene.run(client.READER_ENTRY,eax=0xbd,edx=0x02000000,ecx=7)
        self.assertEqual(scene.u.reg_read(UC_X86_REG_EAX),0)


if __name__=='__main__':unittest.main()
