"""An engine's own picture size reaches the generator's input only where it fits.

Executes GameSurfaceView.generatorInputSize, and checks that the host gives
Eden its handheld 1280x720 and that every generator creation or resize takes
the input size from that rule (3.2.136)."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'


class EngineSourceSizeTest(unittest.TestCase):
    def test_source_size_fits_panel_or_falls_back(self):
        body = method((GAME / 'GameSurfaceView.java').read_text(),
                      '    private int[] generatorInputSize(')
        fixture = '''
public class SourceSizeTest {
    static class TimelineSchedulerSwitch {
        static boolean on = true;
        static boolean engineSourceSize() { return on; }
    }
    int sourceWidth, sourceHeight;
''' + body + '''
    static void expect(int[] got, int w, int h) {
        if (got[0] != w || got[1] != h)
            throw new AssertionError(got[0] + "x" + got[1] + " != " + w + "x" + h);
    }
    public static void main(String[] args) {
        SourceSizeTest t = new SourceSizeTest();
        expect(t.generatorInputSize(1920, 1080), 1920, 1080);   // no source size
        t.sourceWidth = 1280; t.sourceHeight = 720;
        expect(t.generatorInputSize(1920, 1080), 1280, 720);    // Thor
        expect(t.generatorInputSize(2400, 1080), 1280, 720);    // 20:9 phone
        expect(t.generatorInputSize(1280, 720), 1280, 720);     // equal
        expect(t.generatorInputSize(1240, 1080), 1240, 1080);   // narrower panel
        expect(t.generatorInputSize(1080, 1920), 1080, 1920);   // portrait
        TimelineSchedulerSwitch.on = false;                    // QA off
        expect(t.generatorInputSize(1920, 1080), 1920, 1080);
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='engine-source-size-') as directory:
            out = Path(directory)
            (out / 'SourceSizeTest.java').write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out),
                            str(out / 'SourceSizeTest.java')], check=True)
            subprocess.run([str(JAVA / 'java'), '-cp', str(out), 'SourceSizeTest'], check=True)

    def test_every_generator_input_comes_from_the_rule(self):
        view = (GAME / 'GameSurfaceView.java').read_text()
        # Creation and both resize paths; none hands the panel size directly.
        self.assertEqual(view.count('generatorInputSize('), 4)
        self.assertNotRegex(view, r'resize\((\w+), (\w+), \1, \2,')
        self.assertNotIn('width, height, width, height, refreshRate()', view)
        host = (GAME / 'InWindowGameHost.java').read_text()
        self.assertRegex(host, r'"eden"\.equals\(request\.engineId\)\) layer\.setSourceSize\(1280, 720\)')

    def test_prepared_image_takes_the_input_size_only_for_a_smaller_source(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        rule = method(generator, '    private boolean preparedAtInputSize(')
        self.assertIn('!discreteContent', rule)
        self.assertIn('inputWidth < outputWidth && inputHeight < outputHeight', rule)
        prerender = method(generator, '    private void prerenderGeneratedFrame(')
        self.assertIn('allocateTexture(preparedFrameTexture, width, height)', prerender)
        self.assertTrue(re.search(r'if \(!atInput\) setPresentationViewport\(\);', prerender))


if __name__ == '__main__':
    unittest.main()
