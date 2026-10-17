import unittest
from tio.protocol.binary import PacketError
from tio.protocol.transport import *

CHALLENGE=InitialChallenge(0,0x12345678,0,0xabcdef01)
WIRE=bytes.fromhex('0d005075925e7bf8c2ca759da9')
REPLY=bytes.fromhex('120008b2f8dcbfb8bd94b1b522f408acc785')

class TransportTests(unittest.TestCase):
    def test_live_golden_challenge(self):
        plain=bytes.fromhex('0000785634120001efcdab')
        self.assertEqual(encode_initial_challenge(CHALLENGE),plain)
        self.assertEqual(decode_initial_challenge(plain),CHALLENGE)
        self.assertEqual(encode_initial_frame(plain,InitialCipher('S2C')),WIRE)

    def test_live_golden_reply(self):
        reader=InitialFrameReader(InitialCipher('C2S'))
        plain=reader.feed(REPLY)[0]; reader.finish()
        self.assertEqual(plain.hex(),'0180db35f99820792c3e06c7663b4e12')
        p=decode_initial_reply(plain)
        self.assertEqual((p.transformed_u32_01,p.transformed_u32_02),expected_reply_fields(CHALLENGE))
        self.assertEqual(encode_initial_reply(p),plain)
        self.assertEqual(encode_initial_frame(plain,InitialCipher('C2S')),REPLY)

    def test_every_tcp_split(self):
        for split in range(len(WIRE)+1):
            r=InitialFrameReader(InitialCipher('S2C'))
            result=r.feed(WIRE[:split])+r.feed(WIRE[split:]); r.finish()
            self.assertEqual(result,[encode_initial_challenge(CHALLENGE)])

    def test_coalesced_and_state(self):
        for direction in ('S2C','C2S'):
            cipher=InitialCipher(direction)
            messages=[bytes(range(255)),b'\x02\xff',b'\x00']
            wire=b''.join(encode_initial_frame(p,cipher) for p in messages)
            reader=InitialFrameReader(InitialCipher(direction))
            self.assertEqual(reader.feed(wire),messages); reader.finish()

    def test_boundaries_and_invalid(self):
        for size in (1,65533):
            data=b'\xaa'*size
            self.assertEqual(InitialFrameReader(InitialCipher('S2C')).feed(encode_initial_frame(data,InitialCipher('S2C'))),[data])
        for size in (0,65534):
            with self.assertRaises(PacketError): encode_initial_frame(b'x'*size,InitialCipher('S2C'))
        for length in (0,1,2):
            r=InitialFrameReader(InitialCipher('S2C'))
            with self.assertRaises(PacketError): r.feed(length.to_bytes(2,'little'))
            with self.assertRaises(PacketError): r.feed(WIRE)
        r=InitialFrameReader(InitialCipher('S2C')); r.feed(WIRE[:-1])
        with self.assertRaises(PacketError): r.finish()

    def test_packet_invalid(self):
        for decoder,valid in [(decode_initial_challenge,encode_initial_challenge(CHALLENGE)),(decode_initial_reply,bytes.fromhex('0180db35f99820792c3e06c7663b4e12'))]:
            for data in [valid[:i] for i in range(len(valid))]+[valid+b'\0',b'\xff'+valid[1:]]:
                with self.assertRaises(PacketError): decoder(data)
        with self.assertRaises(PacketError): encode_initial_reply(InitialReply(0,0,0,b'xx'))
        with self.assertRaises(PacketError): encode_initial_challenge(InitialChallenge(256,0,0,0))
