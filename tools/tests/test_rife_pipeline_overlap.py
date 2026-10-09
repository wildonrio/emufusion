import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'qa/analyze_rife_pipeline_overlap.py'
spec = importlib.util.spec_from_file_location('overlap', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OverlapTest(unittest.TestCase):
    def test_backlog_windows_detect_growth(self):
        result=module.analyze('PIPE,20,0,0,1,1,1\nPIPE,21,0,1,1,70000000,1\n'
                              'PIPE,22,1,2,1,90000000,1\n'
                              'ARRIVAL,21,0\nARRIVAL,22,10000000\n')
        window=result['backlog_windows'][0]
        self.assertEqual(window['first_latency_ms'],70)
        self.assertEqual(window['last_latency_ms'],80)
        self.assertEqual(window['late_at_66_667_ms'],2)
        self.assertEqual(window['completion_fps'],50)

    def test_gpu_stage_units(self):
        result = module.analyze('PIPE,20,0,100,10,200,40\nPIPE,21,1,150,10,250,40\n'
                                'RIFE_GPU_PHASES,21,100000,12000000,200000\n')
        self.assertEqual(result['gpu_stage_sample_count'],1)
        self.assertEqual(result['gpu_stage_median_ms']['model'],12)

    def test_adjacent_and_warmup_filter(self):
        result = module.analyze('PIPE,20,0,100,10,200,40\n'
                                'PIPE,21,1,150,10,250,40\n'
                                'PIPE,22,0,300,10,400,40\n')
        self.assertEqual(result['adjacent_pairs'], 2)
        self.assertEqual(result['prepare_before_previous_retirement'], 1)
        self.assertEqual(result['median_start_minus_previous_retirement_ms'], 0)
        self.assertFalse(result['physical_presentation_qualified'])

    def test_missing_sequence_not_treated_as_adjacent(self):
        with self.assertRaises(ValueError):
            module.analyze('PIPE,21,0,100,10,200,40\nPIPE,23,1,150,10,250,40\n')

    def test_input_readiness_excludes_warmup(self):
        result = module.analyze('PIPE,20,0,100,10,200,40\nPIPE,21,1,150,10,250,40\n'
                                'INPUT_READINESS,20,0,10,999999999\n'
                                'INPUT_READINESS,21,1,3,2000000\n')
        self.assertEqual(result['input_readiness']['samples'], 1)
        self.assertEqual(result['input_readiness']['retry_count'], 3)
        self.assertEqual(result['input_readiness']['median_elapsed_ms'], 2)

    def test_input_stages_keep_import_separate(self):
        result = module.analyze('PIPE,20,0,100,10,200,40\nPIPE,21,1,150,10,250,40\n'
                                'INPUT_STAGES,21,10000000,100000,900000\n')
        self.assertEqual(result['input_stages']['upload_to_acquired']['median_ms'], 10)
        self.assertEqual(result['input_stages']['import']['median_ms'], .1)
        self.assertEqual(result['input_stages']['acquired_to_prepare']['median_ms'], .9)
