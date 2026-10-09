import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('layers',Path(__file__).resolve().parents[1]/'qa/analyze_rife_layers.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LayersTest(unittest.TestCase):
    parameters='7767517\n2 2\nInput input 0 1 a\nConvolution conv 1 1 a b\n'
    def test_maps_index_and_units(self):
        result=module.analyze('RIFE_GPU_LAYER,1,2000000',self.parameters)
        self.assertEqual(result['slowest_layers'][0]['name'],'conv')
        self.assertEqual(result['sum_measured_ms'],2)
        self.assertFalse(result['performance_qualified'])
    def test_rejects_duplicate(self):
        with self.assertRaises(ValueError):
            module.analyze('RIFE_GPU_LAYER,1,1\nRIFE_GPU_LAYER,1,2',self.parameters)
