"""The OCR helper must not retain derived images, including on failure."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageOps

TOOLS = Path(__file__).resolve().parents[2] / 'unified-android/tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('ocr_scratch_runtime', TOOLS / 'run_runtime_acceptance_qa.py')
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class OcrScratchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'original.png'
        Image.new('RGB', (8, 8), 'navy').save(self.path)
        self.original = self.path.read_bytes()

    def test_same_four_passes_and_boosted_pixels_without_disk_cache(self):
        with mock.patch.object(Path, 'is_file', return_value=True), mock.patch.object(
                MOD.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'text')) as run:
            self.assertEqual(MOD.ocr(self.path), 'text\ntext\ntext\ntext')
        self.assertEqual(run.call_count, 4)
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], ['6', '11', '6', '11'])
        for call in run.call_args_list[:2]:
            self.assertEqual(call.args[0][1], str(self.path))
            self.assertIsNone(call.kwargs['input'])
        expected = ImageOps.autocontrast(Image.open(self.path).convert('L'), cutoff=1)
        for call in run.call_args_list[2:]:
            self.assertEqual(call.args[0][1], 'stdin')
            self.assertEqual(Image.open(io.BytesIO(call.kwargs['input'])).tobytes(), expected.tobytes())
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_process_failure_leaves_no_scratch(self):
        with mock.patch.object(Path, 'is_file', return_value=True), mock.patch.object(
                MOD.subprocess, 'run', side_effect=OSError('failed')):
            with self.assertRaises(OSError):
                MOD.ocr(self.path)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
