import io
import json
import unittest
from tio.protocol.trace import TraceWriter, link_packets


class TraceTests(unittest.TestCase):
    def test_unknown_and_adjacency(self):
        stream = io.StringIO()
        trace = TraceWriter(stream, 'probe')
        for payload in (b'\xfa\x00', b'\x02\x00\x78\x56\x34\x12'):
            trace.record(direction='S2C',state='UNKNOWN',payload=payload,timestamp='2026-09-11T00:00:00Z')
        rows = link_packets([json.loads(line) for line in stream.getvalue().splitlines()])
        self.assertEqual(rows[0]['opcode'], '0xFA')
        self.assertEqual(rows[0]['payload_hex'], 'fa00')
        self.assertEqual(rows[0]['following_packet'], 1)
        self.assertEqual(rows[1]['preceding_packet'], 0)
        self.assertIsNone(rows[1]['following_packet'])

    def test_raw_transport_does_not_invent_opcode(self):
        stream = io.StringIO()
        r = TraceWriter(stream,'raw').record(direction='C2S',state='UNKNOWN',payload=b'\x01\x02',layer='transport_unknown')
        self.assertIsNone(r['opcode'])
