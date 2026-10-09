"""Execute the real hardware listener body; PCM must not wait for an image.

The render-loop's own executed/not-executed branching is separately exercised
by ExperimentalGlesRenderLoopTest. This guards the session-side engine filter
that previously discarded those notifications for every core except PSP.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_hardware_audio_resume import method

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java'
JAVA = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')
ENV = dict(os.environ, JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true')


class HardwareAudioWithoutPresentationTest(unittest.TestCase):
    def test_real_callback_drains_all_hardware_engines_before_first_image(self):
        callback = method(SOURCE.read_text(), '@Override public void onFrameExecutedWithoutPresentation()')
        harness = r'''
public final class HardwareAudioWithoutPresentationTest {
    static final class Entry { String id; Entry(String id) { this.id = id; } }
    static final class ExperimentalGlesRenderLoop {
        int queued, drained, calls;
        short[] drainAudio(int frames) {
            calls++;
            int count = Math.min(frames, queued);
            queued -= count; drained += count;
            return new short[count * 2];
        }
    }
    final Entry entry;
    ExperimentalGlesRenderLoop renderLoop = new ExperimentalGlesRenderLoop();
    int received, progress;
    HardwareAudioWithoutPresentationTest(String engine) { entry = new Entry(engine); }
    void presentAudio(short[] pcm) { received += pcm.length / 2; }
    void recordActiveProgress(ExperimentalGlesRenderLoop active) { progress++; }
    CALLBACK
    public static void main(String[] args) {
        for (String engine : new String[]{"mupen64plus-next", "flycast", "dolphin", "play", "armsx2", "ppsspp"}) {
            HardwareAudioWithoutPresentationTest session = new HardwareAudioWithoutPresentationTest(engine);
            for (int frame = 0; frame < 134; frame++) {
                session.renderLoop.queued += 735; // 44.1kHz PCM at60 guest steps/s; no displayed image yet.
                session.onFrameExecutedWithoutPresentation();
                if (session.renderLoop.queued != 0)
                    throw new AssertionError(engine + ": non-presenting guest PCM was stranded");
            }
            if (session.received != 134 * 735 || session.renderLoop.calls != 134 || session.progress != 134)
                throw new AssertionError(engine + ": actual guest progress was lost");
            session.renderLoop = null;
            session.onFrameExecutedWithoutPresentation();
            if (session.progress != 134) throw new AssertionError("retired owner delivered PCM");
        }
        System.out.println("PASS:6 hardware-engine callback routes,134 non-presenting steps each,retired owner inert");
    }
}
'''.replace('    CALLBACK', callback)
        with tempfile.TemporaryDirectory(prefix='emufusion-unpresented-pcm-') as folder:
            source = Path(folder) / 'HardwareAudioWithoutPresentationTest.java'
            source.write_text(harness)
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', folder, str(source)],
                           env=ENV, check=True, capture_output=True, timeout=60)
            result = subprocess.run([str(JAVA / 'java'), '-cp', folder, source.stem],
                                    env=ENV, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
