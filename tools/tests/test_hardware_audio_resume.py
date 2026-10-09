"""Execute the hardware session's real method bodies with deterministic sinks.

This is a JVM behavior test, not a source-string pass: resume, focus gain and
PCM delivery methods are extracted unchanged from the production Java source.
Android focus, the render-loop scheduler and AudioTrack are test doubles.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    # All selected methods have balanced braces in strings/comments as well.
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end].replace("@Override ", "")


class HardwareAudioResumeTests(unittest.TestCase):
    def test_actual_session_audio_start_and_resume_methods(self):
        source = SOURCE.read_text()
        methods = "\n".join(method(source, signature) for signature in [
            "@Override public void resume()",
            "private void resumeAfterAudioFocusGain()",
            "private void prepareAudioResume()",
            "private void presentAudio(short[] samples)",
            "private void applySteadyAudioBuffer(AudioTrack audio)",
        ])
        harness = r'''
import java.util.concurrent.atomic.AtomicBoolean;
import com.thorium.lucent.audio.PcmAudioQueue;

public class HardwareAudioResumeTest {
    static final String TAG = "test";
    static final class Build { static final class VERSION { static final int SDK_INT = 35; } }
    static final class SystemClock { static long now = 1000; static long elapsedRealtime() { return now; } }
    static final class Log {
        static void i(String tag, String message) {}
        static void e(String tag, String message) { throw new AssertionError(message); }
        static void e(String tag, String message, Throwable error) { throw new AssertionError(message, error); }
    }
    static final class Entry { String id = "dolphin"; }
    static final class Focus {
        boolean suppressed;
        void request() {}
        boolean isSuppressed() { return suppressed; }
    }
    static final class ExperimentalGlesRenderLoop {
        int resumes;
        void resume() { resumes++; } // Schedules work; it does not instantly deliver PCM.
    }
    interface Listener { void onSessionError(String text, Throwable error); }
    static final class AudioTrack {
        static final int WRITE_NON_BLOCKING = 1, PLAYSTATE_PLAYING = 3;
        int state = 2, plays, writes, queuedSamples, capacity = 12800, writeLimit = Integer.MAX_VALUE;
        boolean failResize;
        int getPlayState() { return state; }
        int getSampleRate() { return 32000; }
        int setBufferSizeInFrames(int frames) {
            if (failResize) throw new IllegalStateException("released track");
            capacity = frames * 2; return frames;
        }
        void play() { state = PLAYSTATE_PLAYING; plays++; }
        void pause() { state = 2; }
        int write(short[] data, int offset, int requested, int mode) {
            writes++;
            int accepted = Math.min(Math.min(requested, capacity - queuedSamples), writeLimit);
            queuedSamples += accepted;
            return accepted;
        }
        int write(short[] data, int offset, int requested) { return write(data, offset, requested, 1); }
    }
    final AtomicBoolean backgroundCaptureRequested = new AtomicBoolean();
    final AtomicBoolean audioFailureReported = new AtomicBoolean();
    final Focus audioFocus = new Focus();
    final Entry entry = new Entry();
    final AudioTrack audioTrack = new AudioTrack();
    final PcmAudioQueue audioQueue = new PcmAudioQueue(38400);
    final ExperimentalGlesRenderLoop renderLoop = new ExperimentalGlesRenderLoop();
    boolean prepared = true, resumeRequested, audioStartedOnce, audioDropLogged, steadyAudioBufferApplied;
    int primedAudioSamples, audioPrimeSamplesTarget = 12800;
    long activeStartedMillis, activeFrameTickMillis, receivedAudioFrames, writtenAudioFrames;
    long droppedAudioFrames, audioStartedAtMillis;
    Listener listener;
    int startupAudioBufferBytes(double rate) { return 25600; }
    int steadyAudioBufferBytes(double rate) { return 6400; }
    static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    METHODS

    public static void main(String[] args) {
        HardwareAudioResumeTest wake = new HardwareAudioResumeTest();
        wake.audioStartedOnce = true;
        wake.audioTrack.queuedSamples = 3200; // Existing steady PCM survives pause.
        wake.resume();
        require(wake.renderLoop.resumes == 1, "wake must schedule rendering");
        require(wake.audioTrack.plays == 0, "wake must not play before renderer/PCM delivery");
        wake.presentAudio(null);
        require(wake.audioTrack.plays == 0, "a frame without fresh PCM must not restart audio");
        wake.presentAudio(new short[1066]);
        require(wake.audioTrack.plays == 0, "one fresh block is insufficient during wake warm-up");
        require(wake.audioTrack.queuedSamples == 4266, "wake retains existing and new PCM");
        wake.presentAudio(new short[8536]);
        require(wake.audioTrack.plays == 1, "refilled track resumes at producer boundary");
        require(wake.audioTrack.queuedSamples == 12800 && wake.audioQueue.queuedSamples() == 2,
                "refill retains the prefix and the unwritten tail without duplication");
        wake.presentAudio(new short[1066]);
        require(wake.audioTrack.plays == 1, "ordinary frames do not repeatedly call play");

        HardwareAudioResumeTest full = new HardwareAudioResumeTest();
        full.audioStartedOnce = true;
        full.audioTrack.queuedSamples = full.audioTrack.capacity;
        full.resume();
        full.presentAudio(new short[1066]);
        require(full.audioTrack.plays == 1, "full paused track must resume despite a zero-byte write");
        require(full.audioQueue.queuedSamples() == 1066, "unwritten new PCM stays in FIFO");

        HardwareAudioResumeTest first = new HardwareAudioResumeTest();
        first.resume();
        first.presentAudio(new short[6400]);
        require(first.audioTrack.plays == 0, "initial playback still waits for the full startup prime");
        first.presentAudio(new short[6400]);
        require(first.audioTrack.plays == 1 && first.audioStartedOnce, "startup prime starts once");

        HardwareAudioResumeTest focus = new HardwareAudioResumeTest();
        focus.audioStartedOnce = true;
        focus.resumeRequested = true;
        focus.resumeAfterAudioFocusGain();
        require(focus.audioTrack.plays == 0, "focus gain must wait for PCM, just like wake");
        focus.audioFocus.suppressed = true;
        focus.presentAudio(new short[1066]);
        require(focus.audioTrack.plays == 0 && focus.audioTrack.writes == 0,
                "suppressed focus never plays or queues new sound");
        focus.audioFocus.suppressed = false;
        focus.presentAudio(new short[12802]);
        require(focus.audioTrack.plays == 1, "focus recovery starts after PCM delivery");
        focus.audioTrack.pause();
        focus.resumeRequested = false;
        focus.resumeAfterAudioFocusGain();
        focus.presentAudio(new short[1066]);
        require(focus.audioTrack.plays == 1, "focus or a late PCM callback cannot play over a paused menu");

        HardwareAudioResumeTest partial = new HardwareAudioResumeTest();
        partial.audioStartedOnce = true;
        partial.resume();
        partial.audioTrack.writeLimit = 100;
        partial.presentAudio(new short[1066]);
        require(partial.writtenAudioFrames == 400 && partial.audioQueue.queuedSamples() == 266,
                "eight bounded partial writes retain all remaining PCM");
        require(partial.audioTrack.plays == 0, "partial fresh PCM cannot start an unfilled wake buffer");
        SystemClock.now = 10000;
        partial.applySteadyAudioBuffer(partial.audioTrack);
        require(partial.audioTrack.capacity == 12800, "long paused refill cannot shrink its own target");
        wake.applySteadyAudioBuffer(wake.audioTrack);
        require(wake.audioTrack.capacity == 3200 && wake.steadyAudioBufferApplied,
                "playing track returns to unchanged steady capacity after warm-up");
        HardwareAudioResumeTest released = new HardwareAudioResumeTest();
        released.audioStartedOnce = true;
        released.audioTrack.failResize = true;
        released.resume();
        require(released.renderLoop.resumes == 1 && released.audioTrack.plays == 0,
                "released/invalid track must not throw from the lifecycle resume callback");
        System.out.println("PASS: wake/focus refill, retained PCM, full-buffer recovery, startup prime, paused silence, partial-write retention");
    }
}
'''.replace("    METHODS", methods)
        with tempfile.TemporaryDirectory(prefix="emufusion-audio-resume-") as temp:
            path = Path(temp) / "HardwareAudioResumeTest.java"
            path.write_text(harness)
            subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", temp,
                            str(path), str(ROOT / "unified-android/src/com/thorium/lucent/audio/PcmAudioQueue.java")], check=True)
            result = subprocess.run([str(JAVA / "java"), "-cp", temp, "HardwareAudioResumeTest"],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
