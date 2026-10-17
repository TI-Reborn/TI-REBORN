"""Read original candidate fragments without changing gameplay configuration."""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(r'C:\Program Files (x86)\TIOnline\base\maps')


def main():
    result = []
    for pattern in ('oiltank_v*.s', 'concrete_wall_v*.s', 'treepack_v*.s', 'vhouse1_v*.s'):
        for path in sorted(BASE.glob(pattern)):
            raw = path.read_bytes()
            if raw[:8] != b'TI SET\0\2':
                raise ValueError(f'Unsupported header: {path}')
            width, height, count = struct.unpack_from('<3H', raw, 12)
            end = 32 + 2 * width * height
            if not width or not height or end + count * 72 > len(raw):
                raise ValueError(f'Truncated fragment: {path}')
            models = []
            for index in range(count):
                record = raw[end + index * 72:end + (index + 1) * 72]
                if record[0] > 63:
                    raise ValueError('Invalid model name')
                models.append(dict(name=record[1:1 + record[0]].decode('ascii'),
                                   position=list(struct.unpack_from('<ii', record, 64))))
            tiles = list(raw[32:end:2])
            result.append(dict(file=path.name, sha256=hashlib.sha256(raw).hexdigest(),
                               width=width, height=height, tiles=tiles, models=models,
                               blocked_cells_2_3_4=sum(t in (2, 3, 4) for t in tiles),
                               container_models=[m for m in models if m['name'] in
                                                 ('item_steel_box_01.t', 'item_steel_box_01b.t')]))
    target = ROOT / 'evidence/reservation-candidate-fragments.json'
    target.write_text(json.dumps(dict(note='Candidate resources, not proof of city assignment. Doors not decoded here.',
                                      fragments=result), indent=2) + '\n', encoding='utf-8')
    print(f'Audited {len(result)} original fragments: {target}')


if __name__ == '__main__':
    main()
