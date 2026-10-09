import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_native_rife_device_probe import verify_changing_content


class ChangingContentTest(unittest.TestCase):
    def rows(self):
        return [f'CONTENT,{seq},{(seq-1)%2},{(seq-1)//2%2},10,20,{30+(seq-1)//2%2}'
                for seq in range(1,141)]

    def test_good_and_fail_closed(self):
        rows=self.rows()
        self.assertTrue(verify_changing_content('\n'.join(rows))['stable_per_pair'])
        self.assertFalse(verify_changing_content('\n'.join(rows))['presentation_qualified'])
        bad=rows.copy(); bad[-1]=bad[0]
        with self.assertRaisesRegex(ValueError,'sequence'): verify_changing_content('\n'.join(bad))
        bad=rows.copy(); bad[-1]=bad[-1].rsplit(',',1)[0]+',99'
        with self.assertRaisesRegex(ValueError,'unstable'): verify_changing_content('\n'.join(bad))
        bad=[row.rsplit(',',1)[0]+',30' for row in rows]
        with self.assertRaisesRegex(ValueError,'identical output'): verify_changing_content('\n'.join(bad))
        with self.assertRaisesRegex(ValueError,'missing'): verify_changing_content('\n'.join(rows[:-1]))

    def test_single_context(self):
        rows=[row.split(',') for row in self.rows()]
        for row in rows: row[2]='0'
        log='\n'.join(','.join(row) for row in rows)
        self.assertTrue(verify_changing_content(log,1)['both_pairs_per_context'])
        with self.assertRaisesRegex(ValueError,'each context'): verify_changing_content(log,2)

    def test_adjacent_three_pair_stream(self):
        rows=[f'CONTENT,{seq},{(seq-1)%2},{(seq-1)%3},10,20,{30+(seq-1)%3}' for seq in range(1,141)]
        self.assertTrue(verify_changing_content('\n'.join(rows),2,True)['stable_per_pair'])
        rows[-1]=rows[-1].rsplit(',',1)[0]+',99'
        with self.assertRaisesRegex(ValueError,'unstable'): verify_changing_content('\n'.join(rows),2,True)


if __name__=='__main__': unittest.main()
