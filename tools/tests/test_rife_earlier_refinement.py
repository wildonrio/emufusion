import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_native_rife_device_probe import earlier_refinement_param


class EarlierRefinementTest(unittest.TestCase):
    source = (b'7767517\n3 4\n'
              b'BinaryOp add_73 2 1 247 326 327\n'
              b'BinaryOp add_74 2 1 254 330 331\n'
              b'Sigmoid sigmoid_8 1 1 331 332\n')

    def test_preserves_logits_conversion_and_flow_units(self):
        result = earlier_refinement_param(self.source)
        self.assertIn(b'BinaryOp add_73 1 1 247 327 0=2 1=1 2=1.000000e+00', result)
        self.assertIn(b'BinaryOp add_74 1 1 254 331 0=2 1=1 2=1.000000e+00', result)
        self.assertTrue(result.endswith(b'Sigmoid sigmoid_8 1 1 331 332\n'))
        self.assertEqual(len(result.splitlines()), len(self.source.splitlines()))

    def test_rejects_changed_graph_and_repeated_patch(self):
        for data in (self.source.replace(b'247', b'248'),
                     self.source.replace(b'Sigmoid', b'ReLU'),
                     earlier_refinement_param(self.source)):
            with self.assertRaises(ValueError):
                earlier_refinement_param(data)


if __name__ == '__main__':
    unittest.main()
