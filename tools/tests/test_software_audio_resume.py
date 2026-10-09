"""Run actual software-session lifecycle/PCM methods against deterministic sinks."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_hardware_audio_resume import JAVA, ROOT, method

SOURCE = ROOT / "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java"


class SoftwareAudioResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        signatures = ["@Override public void resume()",
                      "@Override public void pause(PauseReason reason)",
                      "private void resumeAfterAudioFocusGain()",
                      "private void presentAudio(short[] samples)",
                      "private void applySteadyAudioBuffer(AudioTrack audio)"]
        if "private void prepareAudioResume()" in source:
            signatures.append("private void prepareAudioResume()")
        if "private void finishDisplayResume(long revision)" in source:
            signatures.extend(("private void finishDisplayResume(long revision)",
                               "private void cancelPendingDisplayResume()"))
        bodies = "\n".join(method(source, s) for s in signatures)
        harness = r'''
import java.util.concurrent.atomic.AtomicBoolean;
import com.thorium.lucent.audio.PcmAudioQueue;
public class SoftwareAudioResumeTest {
    static final String TAG="test";
    static final class Build { static final class VERSION { static final int SDK_INT=35; } }
    static final class SystemClock { static long now=1000; static long elapsedRealtime(){return now;} }
    static final class Log { static void i(String t,String m){} }
    static final class Entry { String id="mesen-s"; }
    static final class FrameGenerationSettings {enum Mode {OFF}}
    static final class Request {FrameGenerationSettings.Mode frameGenerationMode;}
    static final class Focus {
        boolean suppressed;
        void request(){} void abandon(){}
        boolean isSuppressed(){return suppressed;}
    }
    static final class LibretroHost { int resumes; void resume(){resumes++;} void pause(){} }
    static final class DirectDisplayVsync { void suspend(){} }
    static final class PcmSignalTelemetry { void accept(short[] samples){} }
    enum PauseReason { ANDROID_BACKGROUND, LUCENT_MENU }
    static final class AudioTrack {
        static final int WRITE_NON_BLOCKING=1, PLAYSTATE_PLAYING=3;
        int state=2, plays, writes, queuedSamples, capacity=12800;
        int writeLimit=Integer.MAX_VALUE;
        boolean failResize;
        int getPlayState(){return state;} int getSampleRate(){return 32000;}
        int setBufferSizeInFrames(int frames){
            if(failResize)throw new IllegalStateException("released track");
            capacity=frames*2;return frames;
        }
        void play(){state=PLAYSTATE_PLAYING;plays++;} void pause(){state=2;}
        int write(short[] data,int offset,int requested,int mode){
            writes++;
            int count=Math.min(Math.min(requested,capacity-queuedSamples),writeLimit);
            queuedSamples+=count;return count;
        }
        int write(short[] data,int offset,int requested){return write(data,offset,requested,1);}
    }
    final Object runLock=new Object(),audioTelemetryLock=new Object();
    final AtomicBoolean stopping=new AtomicBoolean(),released=new AtomicBoolean();
    final Entry entry=new Entry(); final Focus audioFocus=new Focus();
    final LibretroHost host=new LibretroHost();
    final AudioTrack audioTrack=new AudioTrack();
    final PcmAudioQueue audioQueue=new PcmAudioQueue(38400);
    DirectDisplayVsync directDisplayVsync;
    PcmSignalTelemetry audioSignalTelemetry;
    boolean prepared=true,running,audioStartedOnce,steadyAudioBufferApplied;
    long resumeRevision; boolean displayResumeNeeded,resumeWarmupPending;
    Request request; Object netplayRelay;
    final java.util.concurrent.Executor lifecycle=command->{
        throw new AssertionError("audio-only fixture unexpectedly queued display work");};
    void warmUpDisplayForResume(long revision){throw new AssertionError("unexpected display warm-up");}
    int primedAudioSamples,audioPrimeSamplesTarget=12800,errors,focusDropped;
    long activeTickMillis,audioStartedAtMillis,qualificationAudioSamplesWritten;
    long audioPartialWrites,audioZeroWrites;
    int startupAudioBufferBytes(double rate){return 25600;}
    int steadyAudioBufferBytes(double rate){return 6400;}
    void recordProducedSamples(int n){}
    void recordDroppedSamples(int n,String why){throw new AssertionError(why);}
    void recordFocusDroppedSamples(int n){focusDropped+=n;}
    void recordAudioWriteError(String op,Throwable e){errors++;}
    void saveQuickResume(boolean b,Object o){}
    int touchReleases;
    void releaseDsTouch(){touchReleases++;}
    static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
    METHODS
    public static void main(String[] args){
        SoftwareAudioResumeTest s=new SoftwareAudioResumeTest();
        switch(args[0]){
        case "wake":
            s.audioStartedOnce=true;s.audioTrack.capacity=3200;s.audioTrack.queuedSamples=1600;
            s.steadyAudioBufferApplied=true;
            s.resume();
            check(s.host.resumes==1 && s.running,"wake must resume the core");
            check(s.audioTrack.plays==0,"lifecycle wake played before fresh PCM");
            check(s.audioTrack.capacity==12800,"wake did not restore bounded startup capacity");
            s.presentAudio(null);s.presentAudio(new short[1066]);
            check(s.audioTrack.plays==0,"one PCM block is insufficient");
            check(s.audioTrack.queuedSamples==2666,"retained PCM was discarded");
            s.presentAudio(new short[10136]);
            check(s.audioTrack.plays==0,"partial write is not proof of a filled track");
            s.presentAudio(null);
            check(s.audioTrack.plays==1 && s.audioQueue.queuedSamples()==2,"full refill did not preserve tail/restart");
            s.presentAudio(new short[1066]);
            check(s.audioTrack.plays==1,"playing stream was repeatedly restarted");
            break;
        case "full":
            s.audioStartedOnce=true;s.audioTrack.queuedSamples=12800;s.resume();
            s.presentAudio(new short[1066]);
            check(s.audioTrack.plays==1 && s.audioQueue.queuedSamples()==1066,"full retained buffer must restart without dropping new PCM");
            break;
        case "focus":
            s.audioStartedOnce=true;s.running=true;s.resumeAfterAudioFocusGain();
            check(s.audioTrack.plays==0,"focus gain played before refill");
            s.audioFocus.suppressed=true;s.presentAudio(new short[1066]);
            check(s.audioTrack.writes==0 && s.focusDropped==1066,"suppressed focus was not silent");
            s.audioFocus.suppressed=false;s.presentAudio(new short[12802]);s.presentAudio(null);
            check(s.audioTrack.plays==1,"focus recovery failed to restart full buffer");
            s.pause(PauseReason.LUCENT_MENU);s.resumeAfterAudioFocusGain();s.presentAudio(new short[1066]);
            check(s.audioTrack.plays==1 && s.audioTrack.state==2,"late PCM/focus played over paused menu");
            check(s.touchReleases==1,"pause must retain the DS touch-release lifecycle hook");
            break;
        case "startup":
            s.resume();s.presentAudio(new short[6400]);
            check(s.audioTrack.plays==0,"startup prime changed");
            s.presentAudio(new short[6400]);
            check(s.audioTrack.plays==1 && s.audioStartedOnce,"startup no longer starts at existing target");
            break;
        case "partial":
            s.audioStartedOnce=true;s.resume();s.audioTrack.writeLimit=100;
            s.presentAudio(new short[1066]);
            check(s.qualificationAudioSamplesWritten==100 && s.audioQueue.queuedSamples()==966,"partial FIFO accounting changed");
            check(s.audioTrack.plays==0,"partial write prematurely started refill");
            SystemClock.now=10000;s.applySteadyAudioBuffer(s.audioTrack);
            check(s.audioTrack.capacity==12800,"paused refill shrank its own target");
            s.audioTrack.state=3;s.audioStartedAtMillis=SystemClock.now;
            s.applySteadyAudioBuffer(s.audioTrack);
            check(s.audioTrack.capacity==12800,"resumed warm-up was skipped");
            SystemClock.now+=5001;s.applySteadyAudioBuffer(s.audioTrack);
            check(s.audioTrack.capacity==3200 && s.steadyAudioBufferApplied,"steady capacity was permanently enlarged");
            break;
        case "released":
            s.audioStartedOnce=true;s.audioTrack.failResize=true;s.resume();
            check(s.running && s.host.resumes==1 && s.audioTrack.plays==0,"released track threw/restarted in lifecycle callback");
            check(s.errors==1,"resume resize failure was hidden");
            s.stopping.set(true);s.resume();check(s.host.resumes==1,"stopped session resumed");
            break;
        default:throw new AssertionError(args[0]);
        }
        System.out.println("PASS "+args[0]);
    }
}
'''.replace("    METHODS", bodies)
        cls.temp = tempfile.TemporaryDirectory(prefix="software-audio-resume-")
        cls.addClassCleanup(cls.temp.cleanup)
        java_file = Path(cls.temp.name) / "SoftwareAudioResumeTest.java"
        java_file.write_text(harness)
        subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", cls.temp.name,
                        str(java_file), str(ROOT / "unified-android/src/com/thorium/lucent/audio/PcmAudioQueue.java")], check=True)

    def test_actual_software_audio_lifecycle(self):
        for scenario in ("wake", "full", "focus", "startup", "partial", "released"):
            with self.subTest(scenario=scenario):
                run = subprocess.run([str(JAVA / "java"), "-cp", self.temp.name,
                                      "SoftwareAudioResumeTest", scenario], text=True, capture_output=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
