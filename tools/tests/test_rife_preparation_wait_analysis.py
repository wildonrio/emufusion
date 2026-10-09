import unittest
from tools.analyze_rife_preparation_waits import analyze


class PreparationWaitAnalysisTest(unittest.TestCase):
    def test_ready_observation_is_never_counted_as_pending_or_exact_completion(self):
        text = ('RIFE preparation ready epoch=28 left=320 readyCache=2 gpuWorkNs=13000000 '
                'readinessTiming=proof:64,observedNs:23000000,deadlineNs:0,'
                'dispatchedNs:1000000,nativeCallNs:2000000')
        report = analyze(text, 8333333)
        self.assertEqual(report['jobs'], [])
        ready = report['readyJobs'][0]
        self.assertEqual(ready['epoch'], 28)
        self.assertEqual(ready['readyObservedAfterDispatchNs'], 22000000)
        self.assertFalse(ready['observationIsExactGpuCompletion'])
        self.assertFalse(report['qualificationPassed'])

    def test_sampling_identity_cutoff_and_no_false_pass(self):
        def row(dispatch, observed):
            return ('09-16 23:09:35.349 7065 7476 I Tag: jobTiming=proof:15,'
                    f'observedNs:{observed},deadlineNs:50000000,dispatchedNs:{dispatch},'
                    'queueNs:31927,dependencyWaitNs:12141875,nativeCallNs:2158229 rest')
        result = analyze('\n'.join([row(10000000, 42000000),
                                    row(10000000, 41000000),
                                    row(20000000, 43000000)]), 8333333)
        self.assertFalse(result['qualificationPassed'])
        self.assertEqual(len(result['jobs']), 2)
        first = result['jobs'][0]
        self.assertEqual(first['pendingAfterDispatchNs'], 32000000)
        self.assertEqual(first['pendingPastAdmissionNs'], 6333333)
        self.assertEqual(first['dependencyWaitNs'], 12141875)
        self.assertEqual(analyze('nothing', 8333333)['jobs'], [])
