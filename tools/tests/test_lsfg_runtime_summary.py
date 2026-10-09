import unittest
from tools.qa.summarize_lsfg_runtime import summarize


class RuntimeSummaryTest(unittest.TestCase):
    def test_enabled_switch_and_real_output_do_not_prove_generation(self):
        result = summarize([
            "Qualification proof generator=1 enabled=true proofContract=test",
            "Private output activated presentId=1 generated=0 leftSequence=1",
            "External presentation not ready; slot dropped generated=0 left=2",
        ])
        self.assertTrue(result["qualificationSwitchObservedEnabled"])
        self.assertFalse(result["generatedActivationObserved"])
        self.assertEqual(result["loggedRealNotReadyDrops"], 1)

    def test_generated_activation_is_not_acceptance(self):
        result = summarize(["Private output activated presentId=2 generated=1 leftSequence=1"])
        self.assertTrue(result["generatedActivationObserved"])
        self.assertFalse(result["cadenceQualified"])
        self.assertFalse(result["imageQualityQualified"])

    def test_cumulative_counters_are_not_summed(self):
        result = summarize([
            "Native endpoint provenance generator=1 admissionRealAbsent=10",
            "Native endpoint provenance generator=1 admissionRealAbsent=12",
        ])
        self.assertEqual(result["lastAdmissionCounters"]["RealAbsent"], 12)
