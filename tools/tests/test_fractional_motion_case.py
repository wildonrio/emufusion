import sys
from pathlib import Path
import tempfile
import json
import hashlib
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from create_fractional_motion_case import render,create


class FractionalMotionCaseTest(unittest.TestCase):
    def test_exact_midpoint_is_not_a_hold_or_blend(self):
        a=render(0,'camera',2).astype(float)
        b=render(1,'camera',2).astype(float)
        middle=render(.5,'camera',2).astype(float)
        self.assertFalse(np.array_equal(middle,a))
        self.assertFalse(np.array_equal(middle,b))
        self.assertGreater(abs(middle-(a+b)/2).max(),20)
        np.testing.assert_array_equal(a[::-1][15,20],middle[::-1][15,20])

    def test_reference_excluded_from_endpoint_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'case';create(out,'occlusion')
            m=json.loads((out/'inputs/manifest.json').read_text())
            self.assertFalse(m['reference_included'])
            self.assertEqual(set(m['inputs']),{'left.rgba','right.rgba'})
            self.assertFalse((out/'inputs/withheld-reference.rgba').exists())
            for name,data in m['inputs'].items():
                self.assertEqual(hashlib.sha256((out/'inputs'/name).read_bytes()).hexdigest(),data['sha256'])
