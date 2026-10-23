"""Fast builtin dispatch retains the v1 wire representation and fallback rules."""
from collections import deque
from fractions import Fraction
import json
from pathlib import Path
import random
from types import MappingProxyType
import unittest

from tio import battle_snapshot as codec


class SnapshotFastTypesTests(unittest.TestCase):
    def dump(self,value):return codec.dumps(value,clock=lambda:100.,wall=lambda:200.)

    def test_exact_container_tags_and_order(self):
        value={(1,2):[True,None,3,4.5,'x',b'a'], 'set':{2,10},
               'frozen':frozenset((3,1)),'queue':deque((4,5))}
        expected={'d':[[{'t':[1,2]},{'l':[True,None,3,4.5,'x',{'b':'61'}]}],
                       ['set',{'s':[10,2]}],['frozen',{'z':[1,3]}],['queue',{'q':[4,5]}]]}
        encoded=self.dump(value)
        self.assertEqual(json.loads(encoded)['root'],expected)
        restored,_=codec.loads(encoded,rebase=False)
        self.assertEqual(restored,value)
        self.assertEqual(self.dump(restored),encoded)

    def test_container_subclasses_keep_original_fallback(self):
        for base,value in ((bytes,b'a'),(dict,{'x':1}),(tuple,(1,2)),(list,[1,2]),
                           (set,{1,2}),(frozenset,frozenset((1,2))),(deque,deque((1,2)))):
            derived=type('Derived',(base,),{})
            with self.subTest(base=base):self.assertEqual(self.dump(derived(value)),self.dump(value))

    def test_fraction_path_proxy_and_shared_rng_survive(self):
        rng=random.Random(17)
        value=[Fraction(2,3),Path('relative'),MappingProxyType({'x':(1,2)}),rng,rng]
        encoded=self.dump(value);restored,_=codec.loads(encoded,rebase=False)
        self.assertEqual(restored[:3],value[:3]);self.assertIs(restored[3],restored[4])
        self.assertEqual(restored[3].getstate(),rng.getstate())
        self.assertEqual(self.dump(restored),encoded)

    def test_invalid_values_still_rejected(self):
        class FloatSubclass(float):pass
        for value in (float('nan'),float('inf'),FloatSubclass(1),object()):
            with self.subTest(kind=type(value)),self.assertRaises(ValueError):self.dump(value)
