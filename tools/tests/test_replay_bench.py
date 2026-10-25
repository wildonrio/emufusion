"""The replay quality bench scores the real generator without touching the product.

tools/qa/replay_bench.py plays saved hold-out triplets (two real frames and
the real one between) through DisplayFrameGenerator in its own shell process
(app_process, HoldoutReplay.main), so a generator change is scored on the same
frames every time with no emulator running and no app install. Its hooks are
inert in the product: nothing sets them outside that process.
"""
import re
import unittest

from tools.tests.test_first_install_startup import ROOT

GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
GENERATOR = GAME / 'DisplayFrameGenerator.java'
REPLAY = GAME / 'HoldoutReplay.java'
SWITCH = GAME / 'TimelineSchedulerSwitch.java'
MANIFEST = ROOT / 'android-companion/AndroidManifest.xml'
BUILD = ROOT / 'unified-android/build.sh'
DEX = ROOT / 'tools/qa/build_replay_dex.sh'
BENCH = ROOT / 'tools/qa/replay_bench.py'


def body(source, start, end='\n    }\n'):
    begin = source.index(start)
    return source[begin:source.index(end, begin + len(start))]


class ReplayHooksTest(unittest.TestCase):
    def setUp(self):
        self.generator = GENERATOR.read_text()
        self.replay = REPLAY.read_text()

    def test_hooks_are_off_unless_the_replay_process_sets_them(self):
        self.assertIn('static volatile boolean replayOffscreen;', self.generator)
        self.assertIn('static volatile java.io.File replayDumpDirectory;', self.generator)
        for name in ('replayOffscreen = true', 'replayDumpDirectory = new File',
                     'replayReferences.put('):
            users = [p.name for p in GAME.rglob('*.java') if name in p.read_text()]
            self.assertEqual(['HoldoutReplay.java'], users, name)
        self.assertIn('if (replayOffscreen) return refreshHz;',
                      body(self.generator, '    private double admissionPanelHz() {'))

    def test_only_a_triplets_own_pair_is_scored(self):
        withhold = body(self.generator, '    private boolean withholdForHoldout(')
        self.assertIn('replayOffscreen ? replayReferences.containsKey(timestampNs) :', withhold)
        evaluate = body(self.generator, '    private void evaluateHoldoutPair() {',
                        '        pollHoldout();')
        self.assertIn('ends[0] != activeLeftTimestampNs', evaluate)
        self.assertIn('ends[1] != activeRightTimestampNs', evaluate)
        self.assertIn('"Hold-out pair referenceNs="', self.generator)

    def test_replay_feeds_a_display_zero_dense_generator_at_a_steady_rate(self):
        self.assertIn('public static void main(String[] args)', self.replay)
        self.assertIn('"qa-replay", 0, () -> false, () -> true);', self.replay)
        self.assertIn('TimelineSchedulerSwitch.configureForReplay(levels);', self.replay)
        self.assertIn('EGLExt.eglPresentationTimeANDROID(display, surface, timestampNs);', self.replay)
        self.assertIn('static final int[] DEFAULT_LEVELS = {24, 21, 115};', self.replay)
        configure = body(SWITCH.read_text(), '    static void configureForReplay(int[] levels) {')
        self.assertIn('refresh(null, FrameGenerationSettings.Mode.AUTO);', configure)

    def test_no_product_entry_point(self):
        # The product boundary keeps no exported receiver; the bench starts its
        # own process through adb instead.
        self.assertNotIn('HoldoutReplay', MANIFEST.read_text())
        self.assertIn("app_process -Djava.library.path=", BENCH.read_text())


class ReplayDexTest(unittest.TestCase):
    def test_the_bench_dex_compiles_what_a_build_ships(self):
        exclusions = lambda text: sorted(re.findall(r"! -path '([^']+)'", text))
        build = BUILD.read_text()
        sources = build[build.index('SOURCES=$(find "$ROOT_DIR/android-companion/src"'):]
        sources = sources[:sources.index('-print)')]
        dex = DEX.read_text()
        self.assertEqual(exclusions(sources), exclusions(dex))
        self.assertIn('"$PROJECT_DIR/src" "$PROJECT_DIR/stubs" -name \'*.java\'', dex)


class ReplayScoringTest(unittest.TestCase):
    def test_held_triplets_are_reported_apart_from_moving_ones(self):
        bench = BENCH.read_text()
        self.assertIn("parser.add_argument('--kind', default='moving'", bench)
        self.assertIn("'held' if min(np.abs(b - a).mean(), np.abs(b - c).mean()) < 0.25 * span", bench)
        self.assertIn("p['triplet'] != '?'", bench)


if __name__ == '__main__':
    unittest.main()
