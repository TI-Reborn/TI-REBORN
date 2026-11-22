"""Clipboard whitespace and rejected chat packets must not close a session."""
import unittest

from tio.protocol.binary import PacketError
from tio.protocol.chat import decode_send, encode_message
import test_multi_account as fixture

PASTED_TEXT = '''Вернуть курс кристаллов как было, можно начать с цены 50 кредитов за кристалл.
Для оружия P90 изменить цену применения с 5 ОД на 4 ОД.
При внутрибоевой обмене между наёмниками, добавить подтверждение клавишей Enter.  (например при передачи количества патронов, чтобы вместо ОК нажать Enter и передача удалась).
Реализовать возможность переноса вещей с "Меткой" владельца на клан склад.
Реазиловать возможность выхода "Добытчика" из шахты через клавишу Esc и выбора "Покинуть битву". То же самое и у рейдера. Только в том случае если у них в инвентаре есть бур.
Реализовать блокировку выхода из боя шахты на 5 ходов, в случае если к бою подключается "Рейдер", после истечения 5 ходов выход не возможет через Esc - "покинуть битву" пока в бою находится "Рейдер" - противник. Через 5 ходов открывается главных вход/выход, через который можно выйти, в случае если "Рейдер" ещё в бою.
Снять лимит на количесво доступных товаров в магазине. (Например сейчас кол-во конфет ограниченно).
Уменьшить броню монстров на 20% ТОЛЬКО в шахте 4-6.'''


def request(text: str) -> bytes:
    return b'\x21\x01' + text.encode('utf-16-le') + b'\0\0Bob\0'


class ChatPasteCodecTests(unittest.TestCase):
    def test_clipboard_line_breaks_and_tabs_become_spaces(self):
        self.assertEqual(decode_send(request('Первая\r\nвторая\nтретья\rчетвёртая\tстрока')),
                         (1, 'Первая вторая третья четвёртая строка', b'Bob'))

    def test_long_paste_has_a_clear_limit_error(self):
        with self.assertRaisesRegex(PacketError, '200'):
            decode_send(request(PASTED_TEXT))

    def test_other_controls_remain_invalid(self):
        with self.assertRaises(PacketError):
            decode_send(request('bad\x1btext'))


class ChatPasteNetworkTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.MultiAccountTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.start()
        self.alice = self.case.handoff(self.case.begin('alice'))
        self.case.enter(self.alice, 'Alice')
        self.bob = self.case.handoff(self.case.begin('bob'))
        self.case.enter(self.bob, 'Bob')

    def assert_still_connected(self):
        self.case.ping(self.alice)
        self.alice.send(request('После вставки'))
        self.assertEqual(self.bob.until(b'\x22', max_packets=512),
                         encode_message(1, b'Alice', 'После вставки'))
        self.case.ping(self.bob)
        self.assertFalse(self.case.errors)

    def test_short_multiline_paste_delivered_without_disconnect(self):
        self.alice.send(request('Привет\r\nдругу\tиз чата'))
        self.assertEqual(self.bob.until(b'\x22', max_packets=512),
                         encode_message(1, b'Alice', 'Привет другу из чата'))
        self.assert_still_connected()

    def test_original_long_paste_rejected_without_disconnect(self):
        self.alice.send(request(PASTED_TEXT))
        error = self.alice.until(b'\xf0\x8a\x01\0\0', max_packets=512)
        self.assertIn('200', error[13:-2].decode('utf-16-le'))
        self.assert_still_connected()

    def test_invalid_control_rejected_without_disconnect(self):
        self.alice.send(request('bad\x1btext'))
        self.alice.until(b'\xf0\x8a\x01\0\0', max_packets=512)
        self.assert_still_connected()

    def test_truncated_chat_rejected_without_disconnect(self):
        self.alice.send(b'\x21\x01a')
        self.alice.until(b'\xf0\x8a\x01\0\0', max_packets=512)
        self.assert_still_connected()


if __name__ == '__main__':
    unittest.main()
