"""Native mail shapes, distinct string encodings and hostile frame rejection."""
import importlib.util
from pathlib import Path
import struct
import unittest

from tio.protocol import mail
from tio.protocol.binary import PacketError


class MailProtocolTests(unittest.TestCase):
    def setUp(self):
        self.item=mail.PostItem(17,101,3,(20,30,40),2,1,True,True,'Маркер',123)
        self.body=mail.MailBody(77,'Alice','Тема',1800000000,10,True,True,'Письмо 💌',100,(self.item,))

    def cases(self):
        return (
            (mail.encode_draft(mail.DraftRequest(0,b'Bob','Тема','Письмо',((17,3),))),mail.decode_draft),
            (mail.encode_recalculate(),mail.decode_recalculate),
            (mail.encode_money(mail.MoneyRequest(b'Bob',10)),mail.decode_money),
            (mail.encode_page(2),mail.decode_page),
            (mail.encode_body_request(mail.BodyRequest(0,77)),mail.decode_body_request),
            (mail.encode_body_request(mail.BodyRequest(2,77)),mail.decode_body_request),
            (mail.encode_body_request(mail.BodyRequest(1,77,'Тема','Письмо',0,(mail.ClaimItem(17,101,3,(20,30,40),2,b'Alice',123),))),mail.decode_body_request),
            (mail.encode_list((mail.MailSummary(77,'Alice','Тема',1800000000,1,True,0),),pages=2,page=1),mail.decode_list),
            (mail.encode_body(self.body),mail.decode_body),
            (mail.encode_notification('Alice','Тема',True),mail.decode_notification),
            (mail.encode_post_warehouse((mail.PostWarehouseItem(77,'Alice','Тема',1800000000,self.item),)),mail.decode_post_warehouse),
        )

    def test_incoming_shapes_roundtrip(self):
        request=mail.DraftRequest(0,b'Bob','Тема','Текст 💌',((17,3),(19,4)))
        self.assertEqual(mail.decode_draft(mail.encode_draft(request)),request)
        self.assertEqual(mail.decode_recalculate(mail.encode_recalculate(77)),(True,77))
        money=mail.MoneyRequest(b'Bob',10,False)
        self.assertEqual(mail.decode_money(mail.encode_money(money)),money)
        self.assertEqual(mail.decode_page(mail.encode_page(2)),2)
        for action in (0,1,2):
            request=mail.BodyRequest(action,77) if action!=1 else mail.BodyRequest(1,77,'Тема','Текст',0,(mail.ClaimItem(17,101,3),))
            self.assertEqual(mail.decode_body_request(mail.encode_body_request(request)),request)

    def test_server_shapes_and_native_unread_kind_order(self):
        rows=(mail.MailSummary(77,'Alice','Тема',1800000000,1,True,0),mail.MailSummary(78,'Bob','',1800000001,0,False,1))
        packet=mail.encode_list(rows,pages=2,page=1)
        self.assertEqual(mail.decode_list(packet),(2,1,rows))
        self.assertEqual(packet[-2:],b'\0\1')
        self.assertEqual(mail.decode_body(mail.encode_body(self.body)),self.body)
        self.assertEqual(mail.decode_notification(mail.encode_notification('Alice','Тема',True)),('Alice','Тема',True))
        warehouse=(mail.PostWarehouseItem(77,'Alice','Тема',1800000000,self.item),)
        self.assertEqual(mail.decode_post_warehouse(mail.encode_post_warehouse(warehouse)),warehouse)

    def test_ui_utf16_and_generated_utf8_are_distinct(self):
        draft=mail.encode_draft(mail.DraftRequest(0,b'Bob','Я','Ё'))
        self.assertEqual(draft,b'\xb7\x07\0Bob\0'+ 'Я\0Ё\0'.encode('utf-16le')+b'\0\0')
        packet=mail.encode_body(mail.MailBody(77,'Я','Ё',1800000000,10,False,False,'',100))
        self.assertEqual(packet[6:10],b'\x02\0'+ 'Я'.encode('utf-8'))
        packet=mail.encode_body(mail.MailBody(77,'Bob','A',1800000000,10,False,False,'OK!',100))
        self.assertEqual(packet[6:14],b'\x03\0Bob\x01\0A')
        self.assertEqual(mail.decode_body(packet).body, 'OK!')
        self.assertEqual(mail.encode_post_warehouse()[:6],b'\xb7\x75\0\0\0\0')

    def test_all_truncations_and_trailing_bytes_rejected(self):
        for packet,decoder in self.cases():
            with self.subTest(packet=packet[:2].hex()):
                for size in range(len(packet)):
                    with self.assertRaises(PacketError):decoder(packet[:size])
                with self.assertRaises(PacketError):decoder(packet+b'\0')
                with self.assertRaises(PacketError):decoder(b'\0'+packet[1:])

    def test_noncanonical_flags_and_unsupported_actions_rejected(self):
        with self.assertRaises(PacketError):mail.decode_recalculate(b'\xb7\x08\x02'+bytes(4))
        with self.assertRaises(PacketError):mail.decode_money(b'\xb7\x09\x01Bob\0'+bytes(5))
        with self.assertRaises(PacketError):mail.decode_money(b'\xb7\x09\x02Bob\0'+bytes(4)+b'\x02')
        with self.assertRaises(PacketError):mail.decode_body_request(b'\xb7\x0e\x03'+bytes(4))

    def test_malformed_lengths_attachment_counts_and_text_rejected(self):
        with self.assertRaises(PacketError):mail.decode_body(b'\xb7\x7a'+bytes(4)+b'\x01\0\xff')
        with self.assertRaises(PacketError):mail.decode_draft(b'\xb7\x07\0Bob\0'+bytes(4)+struct.pack('<H',65))
        with self.assertRaises(PacketError):mail.decode_post_warehouse(b'\xb7\x75'+struct.pack('<I',1001))
        for text in ('x\0y','\ud800','x'*8001):
            with self.assertRaises(PacketError):mail.encode_draft(mail.DraftRequest(0,b'Bob',text))
        with self.assertRaises(PacketError):mail.encode_draft(mail.DraftRequest(0,b'x\0y'))

    def test_original_numeric_builders_and_readers(self):
        native=Path(r'C:\Program Files (x86)\TIOnline\silver.dll')
        if not native.exists():self.skipTest('Original Silver client not installed on this test host')
        root=Path(__file__).resolve().parents[1]
        specification=importlib.util.spec_from_file_location('verify_mail_native',root/'tools/verify_mail_native.py')
        module=importlib.util.module_from_spec(specification);specification.loader.exec_module(module)
        report=module.run()
        self.assertGreaterEqual(len(report['cases']),12)


if __name__=='__main__':unittest.main()
