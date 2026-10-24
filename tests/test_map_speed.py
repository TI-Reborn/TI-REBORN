"""The requested 6 -> 12 map speed governs arrival, resume and interpolation."""
from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.locations import LocationStore, MAP_SPEED, center


class MapSpeedTests(unittest.TestCase):
    def test_twice_previous_speed_and_durable_resume_agree(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'map.sqlite3'
            now=[1000.0]
            store=LocationStore(path,clock=lambda:now[0])
            start=center(3)
            target=(start[0]-46,start[1])
            with closing(sqlite3.connect(path)) as db,db:
                LocationStore._save(db,'alice',3,*start)
            packets=store.travel('alice',struct.pack('<Bii',0x1b,*target),42)
            self.assertEqual(packets[-1][0],0x1d)
            with closing(sqlite3.connect(path)) as db:
                row=db.execute('SELECT started,arrives FROM map_journeys WHERE account=?',('alice',)).fetchone()
            self.assertEqual(MAP_SPEED,12)
            self.assertAlmostEqual(row[1]-row[0],46/6/2)
            now[0]+=1
            resumed=LocationStore(path,clock=lambda:now[0])
            self.assertEqual(resumed.position('alice'),(start[0]-12,start[1]))
            self.assertEqual(resumed.resume('alice',42)[-1][0],0x1d)
            now[0]=row[1]
            self.assertEqual(resumed.refresh('alice',42)[0][0],0x1e)
            self.assertEqual(resumed.position('alice'),target)
            self.assertFalse(resumed.travelling('alice'))


if __name__=='__main__':unittest.main()
