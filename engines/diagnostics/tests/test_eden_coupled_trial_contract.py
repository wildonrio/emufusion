"""Check generated trial API claims without compiling or modifying normal Eden."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_eden_coupled_clock_trial as trial


class CoupledTrialContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = trial.TREE / 'src/android/app/src/main/jni/lucent_adapter.cpp'
        if not cls.path.exists() or not (trial.DIRECT / 'source-identity.json').exists():
            raise unittest.SkipTest('requires the pinned local Eden trial inputs')
        cls.original = cls.path.read_bytes()
        generated = trial.sources()
        cls.adapter = next(text for path, text, _ in generated if path == cls.path)
        cls.swapchain = next(text for path, text, _ in generated if path.name == 'vk_swapchain.cpp')

    def body(self, signature):
        return self.adapter.split(signature + ' {', 1)[1].split('\n}', 1)[0]

    def test_external_setter_and_capability_agree(self):
        setter = self.body('bool lucent_native_adapter_set_paced_video_hz(double hz)')
        caps = self.body('uint32_t lucent_native_adapter_timing_capabilities_v1(void)')
        self.assertIn('if (hz != 0.0) return false;', setter)
        self.assertIn('return Lucent::SetPacedVsyncHz(0.0);', setter)
        self.assertNotIn('LUCENT_NATIVE_TIMING_BASE_CLOCK_CORRECTION', caps)
        self.assertIn('return LUCENT_NATIVE_TIMING_SUBMISSION_TIMESTAMPS;', caps)

    def test_internal_clock_and_fractional_audio_retained(self):
        self.assertIn('Lucent::Trial::g_coupled_clock.Reset();', self.adapter)
        self.assertIn('output->RenderClocked(pulled, kBlockFrames, &pull)', self.adapter)
        self.assertIn('Lucent::Trial::g_coupled_clock.Rate()', self.adapter)

    def test_normal_adapter_not_mutated(self):
        self.assertEqual(self.original, self.path.read_bytes())

    def test_feedback_loss_releases_correction(self):
        for signature in ('void TrialDirectCreate(', 'void TrialDirectDestroy('):
            body = self.swapchain.split(signature, 1)[1].split('}', 1)[0]
            self.assertIn('Lucent::Trial::ResetDisplayClock();', body)
        for condition in ('if (result != VK_SUCCESS && result != VK_INCOMPLETE) {',
                          'if (!state.pacer.HasRecentFeedback(id, now)) {'):
            body = self.swapchain.split(condition, 1)[1].split('}', 1)[0]
            self.assertIn('Lucent::Trial::ResetDisplayClock();', body)


if __name__ == '__main__':
    unittest.main()
