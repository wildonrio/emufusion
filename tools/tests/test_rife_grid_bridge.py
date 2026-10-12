import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bridge_rife_grid_to_warp import convert

# The converter accepts only exact reviewed graph hashes, so this local export
# cannot be synthesized; the cleanup-removed QA copy makes the check skip.
REVIEWED=Path(__file__).resolve().parents[2]/'docs/qa/rife-scale2-export-20260917/model_fixed.ncnn.param'


class GridBridgeTest(unittest.TestCase):
    def test_unreviewed_graph_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'unreviewed'):
            convert(b'7767517\n0 0\n')

    @unittest.skipUnless(REVIEWED.is_file(),'reviewed scale-2 export (local QA input) absent')
    def test_reviewed_graph_replaces_only_sampling_nodes(self):
        source=REVIEWED
        data=source.read_bytes();result,changes=convert(data)
        self.assertEqual(len(changes),8)
        before=data.decode().splitlines();after=result.decode().splitlines()
        self.assertEqual(len(before),len(after));self.assertEqual(before[:2],after[:2])
        changed=[(a,b) for a,b in zip(before,after) if a!=b]
        self.assertEqual(len(changed),8)
        for a,b in changed:
            self.assertTrue(a.startswith('GridSample'))
            self.assertTrue(b.startswith('rife.Warp'))
