"""Run the real Silver clip stack used by auction rows at each UI scale."""
from pathlib import Path
import struct
import sys

from verify_client_ui_scale_native import Fixture, divide, put


def verify(data: bytes) -> None:
    outer = (400, 200, 1300, 620)
    row = (420, 220, 1050, 238)
    for base in (0x400000, 0x10400000):
        for percent in (100, 125, 150):
            fixture = Fixture(data, base)
            width, height = 2560, 1440
            logical = (width * 100 // percent, height * 100 // percent)
            for offset, value in zip((0, 4, 8, 12, 16, 20), (percent, width, height, *logical, 1)):
                fixture.state(offset, value)
            put(fixture.u, fixture.renderer + 0x299, width)
            put(fixture.u, fixture.renderer + 0x29d, height)
            for address, rect in ((fixture.rect, outer), (fixture.rect + 16, row)):
                fixture.u.mem_write(address, struct.pack('<4i', *rect))
                fixture.run(0x4f2d1c, eax=address)
            fixture.run(0x4f2e68)
            assert fixture.clip_rects == [
                tuple(divide(v, (width, height)[i % 2], logical[i % 2])
                      for i, v in enumerate(rect))
                for rect in (outer, row, outer)
            ], (base, percent, fixture.clip_rects)
            assert bytes(fixture.u.mem_read(fixture.va(0xacc530), 32)) == struct.pack('<8i', *outer, *row)


if __name__ == '__main__':
    verify(Path(sys.argv[1]).read_bytes())
    print('Nested clip and restore passed at 100%, 125%, 150%, at both image bases.')
