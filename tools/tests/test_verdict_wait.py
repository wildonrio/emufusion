"""An arriving image's uniqueness check is waited for on a GPU fence, never
into the next callback (3.2.141).

Executes DisplayFrameGenerator.verdictWaitBudgetNs and checks that the wait
only replaces the first 1-ms poll, behind a QA switch that defaults on."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
GENERATOR = GAME / 'DisplayFrameGenerator.java'


class VerdictWaitTest(unittest.TestCase):
    def test_budget_ends_before_the_next_vsync(self):
        body = method(GENERATOR.read_text(), '    static long verdictWaitBudgetNs(')
        fixture = '''
public class VerdictWaitTest {
    static final long VERDICT_WAIT_MAX_NS = 1_000_000L;
    static final long VERDICT_WAIT_MARGIN_NS = 2_000_000L;
''' + body + '''
    static void expect(long got, long want) {
        if (got != want) throw new AssertionError(got + " != " + want);
    }
    public static void main(String[] args) {
        long p = 8_333_333L, v = 1_000_000_000L;
        expect(verdictWaitBudgetNs(v + 1_000_000L, v, p), 1_000_000L);   // 7.3 ms left: capped
        expect(verdictWaitBudgetNs(v + 5_833_333L, v, p), 500_000L);     // 2.5 ms left
        expect(verdictWaitBudgetNs(v + 6_500_000L, v, p), 0L);           // 1.8 ms left: no wait
        expect(verdictWaitBudgetNs(v + p + 5_833_333L, v, p), 500_000L); // a callback was skipped
        expect(verdictWaitBudgetNs(v - 3_000_000L, v, p), 1_000_000L);   // before the stamp
        expect(verdictWaitBudgetNs(v + 1_000_000L, 0L, p), 0L);          // no callback yet
        expect(verdictWaitBudgetNs(v + 1_000_000L, v, 0L), 0L);          // no refresh rate
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='verdict-wait-') as directory:
            out = Path(directory)
            (out / 'VerdictWaitTest.java').write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out),
                            str(out / 'VerdictWaitTest.java')], check=True)
            subprocess.run([str(JAVA / 'java'), '-cp', str(out), 'VerdictWaitTest'], check=True)

    def test_wait_replaces_only_the_first_poll(self):
        generator = GENERATOR.read_text()
        schedule = method(generator, '    private void scheduleSignatureEarlyPoll(')
        self.assertIn('if (TimelineSchedulerSwitch.verdictWait() && signatureVerdictSignaled()) {\n'
                      '                pollSignatureEarly();\n'
                      '                return;', schedule)
        # Retries keep the 1-ms poll; the wait sits in the first-arrival branch.
        self.assertLess(schedule.index('signatureVerdictSignaled()'),
                        schedule.index('} else if (++signatureEarlyPollTries'))
        wait = method(generator, '    private boolean signatureVerdictSignaled(')
        self.assertIn('GLES30.glClientWaitSync(fence, GLES30.GL_SYNC_FLUSH_COMMANDS_BIT, budget)', wait)
        self.assertIn('GLES30.glDeleteSync(fence);', wait)
        self.assertIn('" verdictWaits=" + verdictWaits + "/" + verdictWaitHits +', generator)
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('VERDICT_WAIT_GLOBAL = "emufusion_framegen_verdict_wait"', switch)
        self.assertIn('context.getContentResolver(), VERDICT_WAIT_GLOBAL, 1) != 0;', switch)


if __name__ == '__main__':
    unittest.main()
