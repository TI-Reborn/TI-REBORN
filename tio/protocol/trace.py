"""Append-only JSONL records. Packet adjacency is linked without editing history."""
import json
from datetime import datetime, timezone


class TraceWriter:
    def __init__(self, stream, session_id: str):
        self.stream = stream
        self.session_id = session_id
        self.sequence = 0

    def record(self, *, direction, state, payload, layer='application', known_header_fields=None, timestamp=None):
        if direction not in ('C2S', 'S2C'):
            raise ValueError('direction must be C2S or S2C')
        data = bytes(payload)
        number = self.sequence
        event = {
            'timestamp': timestamp or datetime.now(timezone.utc).isoformat(),
            'session_id': self.session_id, 'sequence': number,
            'direction': direction, 'state': state, 'layer': layer,
            'opcode': f'0x{data[0]:02X}' if data and layer == 'application' else None,
            'length': len(data), 'payload_hex': data.hex(),
            'known_header_fields': known_header_fields or {},
            'preceding_packet': number - 1 if number else None,
            'following_packet': None,
        }
        self.stream.write(json.dumps(event, sort_keys=True) + '\n')
        self.stream.flush()
        self.sequence += 1
        return event


def link_packets(records):
    """Return enriched records, linking only packets in the same session."""
    result = [dict(r) for r in records]
    previous = {}
    for row in result:
        prior = previous.get(row['session_id'])
        if prior is not None:
            prior['following_packet'] = row['sequence']
        previous[row['session_id']] = row
    return result
