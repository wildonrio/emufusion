import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'qa/make_rife_geometry_fixture.py'
spec = importlib.util.spec_from_file_location('fixture', SCRIPT)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class GeometryFixtureTest(unittest.TestCase):
    def test_midpoint_is_rendered_motion_not_endpoint_copy(self):
        frames = [fixture.render(128, 120, t) for t in range(3)]
        self.assertNotEqual(frames[1], frames[0])
        self.assertNotEqual(frames[1], frames[2])
        # Moving foreground begins at x=70,74,78. At x=75 only first two
        # frames contain it: the midpoint isn't an endpoint RGB average.
        pixel = (80 * 128 + 75) * 4
        self.assertEqual(frames[1][pixel:pixel+4], bytes((240,60,30,255)))
        self.assertNotEqual(frames[1][pixel:pixel+4], frames[2][pixel:pixel+4])

    def test_cli_adjacency_hashes_and_reference_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'fixture'
            subprocess.run([sys.executable, str(SCRIPT), str(out), '--width',
                            '128', '--height', '120', '--reference'], check=True)
            for index in range(2):
                root = out / str(index)
                manifest = json.loads((root / 'manifest.json').read_text())
                for name, record in manifest['inputs'].items():
                    self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),
                                     record['sha256'])
                reference = (root/'reference.rgba').read_bytes()
                self.assertEqual(reference, fixture.render(128,120,index*2+1))
                self.assertFalse(manifest['game_quality_qualified'])
                self.assertFalse(manifest['image_quality_reference'])
            self.assertEqual((out/'0/right.rgba').read_bytes(),
                             (out/'1/left.rgba').read_bytes())


if __name__ == '__main__':
    unittest.main()
