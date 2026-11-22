from pathlib import Path
import json, socket, time, unittest
from xml.etree import ElementTree as ET
from tools.build_english_localization import language, TOKENS, CYR
from tio.localization import english
from tio.protocol.chat import encode_message,encode_system_message
from tio.protocol.system_message import encode_shop_error
from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
from server.tls import read_bridge_preface,bridge_preface

ROOT=Path(__file__).resolve().parents[1]

def received(packet,locale):
    cipher=InitialCipher('S2C');cipher.language=locale
    return InitialFrameReader(InitialCipher('S2C')).feed(encode_initial_frame(packet,cipher))[0]

class EnglishLocalizationTests(unittest.TestCase):
    def test_every_original_key_and_placeholder(self):
        ru=language((ROOT/'reports/english-localization/baseline/base/russian.lng').read_bytes(),'cp1251')
        en=language((ROOT/'assets/english-localization/runtime/base/english.lng').read_bytes(),'cp1251')
        self.assertTrue(ru.keys()<=en.keys())
        for key,value in ru.items():
            with self.subTest(key=key):
                self.assertFalse(CYR.search(en[key]));self.assertEqual(TOKENS.findall(value),TOKENS.findall(en[key]))

    def test_resource_overlays_have_same_native_schema(self):
        base=ROOT/'assets/english-localization/runtime/base/locales'
        for name in ('battlelog.xml','quest/00000.xml','quest/tut_1000.xml'):
            a,b=(ET.fromstring((base/locale/name).read_bytes()) for locale in ('ru','en'))
            self.assertEqual([(n.tag,set(n.attrib)) for n in a.iter()],[(n.tag,set(n.attrib)) for n in b.iter()])
            self.assertFalse(CYR.search(ET.tostring(b,encoding='unicode')))
            self.assertEqual(TOKENS.findall(ET.tostring(a,encoding='unicode')),TOKENS.findall(ET.tostring(b,encoding='unicode')))

    def test_two_recipient_languages_share_the_same_canonical_packet(self):
        text='Боец не принадлежит вашему аккаунту'
        packet=encode_shop_error(text)
        self.assertIn(text.encode('utf-16-le'),received(packet,'russian'))
        self.assertIn(english(text).encode('utf-16-le'),received(packet,'english'))
        self.assertIn(text.encode('utf-16-le'),bytes(packet))

    def test_user_chat_and_cyrillic_names_are_opaque(self):
        name='Акции'.encode('cp1251');text='Боец не принадлежит вашему аккаунту'
        packet=encode_message(0,name,text)
        self.assertEqual(received(packet,'english'),packet)
        template=next(k for k in json.loads((ROOT/'config/english_translations.json').read_text(encoding='utf-8')) if '{0}' in k and 'приглашает в группу' in k)
        self.assertIn('Акции',english(template.replace('{0}','Акции').replace('{1}','42')))

    def test_system_chat_translates_per_recipient_only(self):
        packet=encode_system_message(3,b'Training','Тренировку можно продолжить командой /tutorial.')
        self.assertIn(b'/\x00t\x00u\x00t\x00o\x00r\x00i\x00a\x00l\x00',received(packet,'english'))
        self.assertNotEqual(received(packet,'english'),received(packet,'russian'))

    def test_status_fields_translate_without_translating_a_player_name(self):
        self.assertEqual(english('Группа — в бою; лидер Акции.'),'Group - in battle; leader of Акции.')
        self.assertNotIn('Штурм',english('Штурм назначен на 2026-10-20 12:00 UTC.'))
        self.assertNotIn('идёт',english('2026-10: идёт, конец 2026-11-01.'))

    def test_old_and_new_bootstrap_keep_native_bytes_and_reject_unknown_flags(self):
        for flag,locale in ((0,'russian'),(1,'english')):
            a,b=socket.socketpair()
            with a,b:
                raw=bytearray(bridge_preface(31001));raw[5]=flag;a.sendall(raw+b'native')
                port=read_bridge_preface(b,time.monotonic()+1)
                self.assertEqual(port,31001);self.assertEqual(port.language,locale);self.assertEqual(b.recv(6),b'native')
        a,b=socket.socketpair()
        with a,b:
            raw=bytearray(bridge_preface(31001));raw[5]=2;a.sendall(raw)
            with self.assertRaises(ValueError):read_bridge_preface(b,time.monotonic()+1)
