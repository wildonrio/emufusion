import unittest
from tools.qa_owner_trace_summary import summarize


class OwnerTraceSummaryTest(unittest.TestCase):
    def test_nested_owner_and_foreign_events(self):
        def event(tid, time, payload):
            return f" worker-{tid} ( 42) [001] ..... {time}: tracing_mark_write: {payload}"
        lines = [event(7, '1.000', 'B|42|render'),
                 event(8, '1.001', 'B|42|foreign'),
                 event(7, '1.002', 'B|42|acquire'),
                 event(7, '1.015', 'E|42'),
                 event(7, '1.016', 'E'),
                 event(7, '1.017', 'E'),
                 event(7, '1.018', 'B|42|unfinished')]
        result = summarize(lines, 7)
        self.assertEqual(set(result['spans']), {'render', 'acquire'})
        self.assertAlmostEqual(result['spans']['acquire']['maxMs'], 13)
        self.assertAlmostEqual(result['spans']['render']['maxMs'], 16)
        self.assertEqual(result['spans']['acquire']['overOne120HzScan'], 1)
        self.assertEqual(result['unmatchedEnds'], 1)
        self.assertEqual(result['unfinishedSpans'], 1)

    def test_empty(self):
        self.assertEqual(summarize([], 7)['spans'], {})
