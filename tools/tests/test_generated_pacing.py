import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyze_generated_pacing import analyze


class PacingTest(unittest.TestCase):
    def test_overlap_dedup_and_real_gap(self):
        s='100\n1 1000 1\n1 1100 1\n1 1300 1\n---capture---\n100\n1 1100 1\n1 1300 1\n1 1400 1'
        r=analyze(s);self.assertEqual(r['observed_intervals'],3)
        self.assertEqual(r['scan_slot_histogram'],{'1':2,'2':1})
        self.assertEqual(r['nonoverlapping_window_boundaries'],0)

    def test_does_not_invent_collection_gap_as_game_gap(self):
        r=analyze('100\n1 1000 1\n1 1100 1\n---capture---\n100\n1 9000 1\n1 9100 1')
        self.assertEqual(r['observed_intervals'],2)
        self.assertEqual(r['nonoverlapping_window_boundaries'],1)
        self.assertEqual(r['intervals_over_one_and_half_scans'],0)

    def test_invalid_evidence_rejected(self):
        with self.assertRaises(ValueError):analyze('100\n0 0 0\n0 9223372036854775807 0')


if __name__=='__main__':unittest.main()
