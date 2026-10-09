"""Execute software-libretro stop/release ownership code with delayed fake peers.

The lifecycle methods are extracted unchanged from production Java. Android,
checkpoint storage and native-close boundaries are fakes; real Java threads and
latches make acknowledgement ordering deterministic without an Android build.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java"
HOST = ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
FIRMWARE = ROOT / "unified-android/src/com/thorium/preview/game/PcEngineCdFirmware.java"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


def member(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                    lambda match: " " * len(match.group()), source, flags=re.S)
    depth = 0
    for index in range(opening, len(source)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("Unclosed Java member: " + signature)


def method(source, name):
    found = re.search(r"(?:public|private)\s+(?:static\s+)?(?:synchronized\s+)?"
                      r"(?:void|boolean)\s+" + re.escape(name) + r"\(", source)
    if found is None:
        raise AssertionError("Missing actual session method: " + name)
    return member(source, found.group())


def prepare_failure_catches(source):
    prepare = method(source, "prepare")
    after_ready = prepare[prepare.index("callback.onSessionReady();"):]
    inner = member(after_ready, "catch (Throwable failure)")
    after_inner = after_ready[after_ready.index(inner) + len(inner):]
    return inner, member(after_inner, "catch (Throwable failure)")


SHELL = r'''
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
public class LibretroEngineSession {
    static class PcEngineCdFirmware { // ACTUAL_SETUP_EXCEPTION
    }
    interface Completion {void complete();}
    interface Listener {
        void onSessionStopRejected(String message,Throwable failure);
        default void onSessionError(String message,Throwable failure){}
    }
    enum StopReason {EXIT_TO_LUCENT,ACTIVITY_DESTROYED}
    static final String TAG="test";
    final Object appContext=new Object();
    final Object lifecycleSubmissionLock=new Object(),runLock=new Object();
    final AtomicBoolean stopping=new AtomicBoolean(),released=new AtomicBoolean();
    final List<Completion> stopCompletions=new ArrayList<>(),releaseCompletions=new ArrayList<>();
    boolean stopCompleted,releaseCompleted,destroyStopRequested;
    volatile Thread lifecycleThread;
    final ExecutorService lifecycle=Executors.newSingleThreadExecutor(r->{
        Thread worker=new Thread(r,"actual-lifecycle-fixture");worker.setDaemon(true);lifecycleThread=worker;return worker;
    });
    volatile LibretroHost host=new LibretroHost();
    volatile StateVaultWorker vaultWorker;
    volatile AudioTrack audioTrack;
    volatile Thread frameThread,renderThread;
    volatile DirectDisplayVsync directDisplayVsync;
    static class DirectDisplayVsync {void close(){}}
    void closeDirectCanvases(){
        check(renderThread==null || !renderThread.isAlive(),
              "direct renderer destroyed before render worker joined");
    }
    volatile boolean running,prepared,secondaryGameplayRequested;
    volatile Object secondarySurface;
    final Focus audioFocus=new Focus();
    final Mailbox videoMailbox=new Mailbox();
    final Entry entry=new Entry();
    Listener listener;
    final CountDownLatch checkpointEntered=new CountDownLatch(1),checkpointPermit=new CountDownLatch(1);
    final AtomicInteger checkpointCalls=new AtomicInteger(),saveFailures=new AtomicInteger();
    boolean checkpointFail;
    static class Entry {String id="test";}
    static class Focus {
        int abandons;boolean fail;
        void abandon(){abandons++;if(fail)throw new IllegalStateException("focus release failed");}
    }
    static class GameLaunchRequest {String engineId="test",systemId="test",gameTitle="test game";}
    static class Mailbox {void close(java.util.function.Consumer<LibretroHost.VideoFrame> disposer){}}
    static class SecondaryGameplaySurfaceRouter {static void release(Object context,Object session){}}
    static class AudioTrack {void stop(){}void release(){}}
    static class AppVolumeController {static void unregisterTrack(AudioTrack track){}}
    static class Log {
        static void i(String tag,String message){}
        static void w(String tag,String message){}
        static void w(String tag,String message,Throwable failure){}
        static void e(String tag,String message,Throwable failure){}
    }
    static class LibretroHost {
        static class VideoFrame {void release(){}}
        final CountDownLatch closeEntered=new CountDownLatch(1),closePermit=new CountDownLatch(1);
        final CountDownLatch unloadEntered=new CountDownLatch(1),unloadPermit=new CountDownLatch(1);
        volatile boolean failClose,failUnload,closed;
        final AtomicInteger closes=new AtomicInteger(),unloads=new AtomicInteger();
        void pause(){} void resume(){}
        void unloadGame(){
            unloads.incrementAndGet();unloadEntered.countDown();uninterruptibly(unloadPermit);
            if(failUnload)throw new IllegalStateException("unload failure");
        }
        void close(){
            closes.incrementAndGet();closeEntered.countDown();uninterruptibly(closePermit);
            if(failClose)throw new IllegalStateException("native close failure");
            closed=true;
        }
    }
    static class StateVaultWorker {
        final CountDownLatch waiting=new CountDownLatch(1),permit=new CountDownLatch(1);
        final AtomicInteger polls=new AtomicInteger();
        boolean falseFirstPoll;
        int closes;final AtomicInteger interrupted=new AtomicInteger();
        void close(){closes++;}
        boolean awaitTermination(long timeout,TimeUnit unit)throws InterruptedException{
            if(polls.incrementAndGet()==1 && falseFirstPoll)return false;
            waiting.countDown();
            try{return permit.await(timeout,unit);}
            catch(InterruptedException failure){interrupted.incrementAndGet();throw failure;}
        }
    }
    void saveQuickResume(boolean waitForCommit,Completion completion){
        checkpointCalls.incrementAndGet();
        lifecycle.execute(()->{
            checkpointEntered.countDown();uninterruptibly(checkpointPermit);
            if(checkpointFail)saveFailures.incrementAndGet();
            completion.complete();
        });
    }
    // ACTUAL_METHODS
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void await(CountDownLatch latch,String message){
        try{check(latch.await(5,TimeUnit.SECONDS),message);}
        catch(InterruptedException failure){throw new AssertionError(failure);}
    }
    static void uninterruptibly(CountDownLatch latch){
        boolean interrupted=false;
        for(;;)try{latch.await();break;}catch(InterruptedException failure){interrupted=true;}
        if(interrupted)Thread.currentThread().interrupt();
    }
    static void join(Thread thread){
        try{thread.join(5000);check(!thread.isAlive(),"fixture worker did not finish");}
        catch(InterruptedException failure){throw new AssertionError(failure);}
    }
    static void awaitJoinWait(Thread thread){
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
        do{
            if(thread!=null && thread.getState()==Thread.State.WAITING){
                for(StackTraceElement frame:thread.getStackTrace())
                    if(frame.getMethodName().equals("joinReleaseThread"))return;
            }
            Thread.yield();
        }while(thread!=null && thread.isAlive() && System.nanoTime()<deadline);
        throw new AssertionError("actual release join did not wait for a live owner");
    }
    static void terminated(LibretroEngineSession session){
        try{check(session.lifecycle.awaitTermination(5,TimeUnit.SECONDS),"release worker did not terminate");}
        catch(InterruptedException failure){throw new AssertionError(failure);}
    }
    static Thread blockedThread(CountDownLatch permit){
        CountDownLatch entered=new CountDownLatch(1);
        Thread result=new Thread(()->{entered.countDown();uninterruptibly(permit);});
        result.setDaemon(true);result.start();await(entered,"frame fixture did not start");return result;
    }
    static void delayedClose(){
        LibretroEngineSession s=new LibretroEngineSession();LibretroHost original=s.host;
        AtomicInteger first=new AtomicInteger(),second=new AtomicInteger();CountDownLatch ack=new CountDownLatch(2);
        s.releaseWhenComplete(()->{check(original.closed,"first acknowledged before native close");first.incrementAndGet();ack.countDown();});
        await(original.closeEntered,"native close was not queued");
        s.release();s.releaseWhenComplete(()->{second.incrementAndGet();ack.countDown();});
        check(first.get()==0 && second.get()==0 && s.host==original,"delayed close lost ownership/ack gate");
        original.closePermit.countDown();await(ack,"release listeners not drained");terminated(s);
        check(original.closes.get()==1 && first.get()==1 && second.get()==1 && s.host==null,
              "native close/callbacks not exactly once");
        AtomicInteger late=new AtomicInteger();s.releaseWhenComplete(late::incrementAndGet);
        check(late.get()==1,"already-completed release did not acknowledge new listener");
    }
    static void delayedPeers(){
        LibretroEngineSession s=new LibretroEngineSession();LibretroHost original=s.host;
        CountDownLatch frames=new CountDownLatch(1),renderer=new CountDownLatch(1),ack=new CountDownLatch(1);
        s.frameThread=blockedThread(frames);s.renderThread=blockedThread(renderer);
        StateVaultWorker vault=new StateVaultWorker();vault.falseFirstPoll=true;s.vaultWorker=vault;
        s.releaseWhenComplete(ack::countDown);
        awaitJoinWait(s.lifecycleThread);
        check(ack.getCount()==1 && original.closeEntered.getCount()==1,"release bypassed frame/render owners");
        frames.countDown();join(s.frameThread);
        awaitJoinWait(s.lifecycleThread);
        check(ack.getCount()==1 && original.closeEntered.getCount()==1,"release bypassed renderer");
        renderer.countDown();join(s.renderThread);await(vault.waiting,"vault drain not awaited");
        check(vault.polls.get()==2,"false vault poll was treated as completion");
        check(ack.getCount()==1 && original.closeEntered.getCount()==1,"release bypassed pending vault writes");
        vault.permit.countDown();await(original.closeEntered,"native close not reached after peers drained");
        check(ack.getCount()==1,"native close completion bypassed");
        original.closePermit.countDown();await(ack,"release never acknowledged");terminated(s);
        check(vault.closes==1 && original.closes.get()==1,"peer drain repeated teardown");
    }
    static void closeFailure(){
        LibretroEngineSession s=new LibretroEngineSession();LibretroHost original=s.host;
        original.failClose=true;original.closePermit.countDown();AtomicInteger ack=new AtomicInteger();
        s.releaseWhenComplete(ack::incrementAndGet);terminated(s);
        s.releaseWhenComplete(ack::incrementAndGet);s.release();
        check(ack.get()==0 && s.host==original && original.closes.get()==1,
              "failed native close lost ownership, retried or acknowledged success");
    }
    static void duplicateStops(boolean fail){
        LibretroEngineSession s=new LibretroEngineSession();s.checkpointFail=fail;
        CountDownLatch stopped=new CountDownLatch(2);AtomicInteger callbacks=new AtomicInteger();
        Completion complete=()->{callbacks.incrementAndGet();stopped.countDown();};
        s.stop(StopReason.EXIT_TO_LUCENT,complete);await(s.checkpointEntered,"checkpoint not started");
        s.stop(StopReason.EXIT_TO_LUCENT,complete);
        check(callbacks.get()==0 && s.checkpointCalls.get()==1,"duplicate stop completed before checkpoint");
        CountDownLatch releasedAck=new CountDownLatch(1);LibretroHost original=s.host;
        s.releaseWhenComplete(releasedAck::countDown);
        check(original.closeEntered.getCount()==1,"native close overtook checkpoint");
        s.checkpointPermit.countDown();await(stopped,"stop callbacks not drained");
        await(original.closeEntered,"native close not queued after checkpoint");
        check(callbacks.get()==2 && releasedAck.getCount()==1,"stop success mistaken for release success");
        check(s.saveFailures.get()==(fail?1:0),"checkpoint failure outcome lost");
        original.closePermit.countDown();await(releasedAck,"post-stop release missing");terminated(s);
    }
    static void latePrepare(){
        LibretroEngineSession s=new LibretroEngineSession();s.host=null;
        CountDownLatch prepareEntered=new CountDownLatch(1),preparePermit=new CountDownLatch(1);
        CountDownLatch published=new CountDownLatch(1),framePermit=new CountDownLatch(1),ack=new CountDownLatch(1);
        LibretroHost createdLater=new LibretroHost();
        s.lifecycle.execute(()->{
            prepareEntered.countDown();uninterruptibly(preparePermit);
            s.host=createdLater;s.frameThread=blockedThread(framePermit);published.countDown();
        });
        await(prepareEntered,"prepare did not enter");
        s.releaseWhenComplete(ack::countDown);
        check(ack.getCount()==1,"release acknowledged before in-flight preparation");
        preparePermit.countDown();await(published,"prepare owners not published");
        awaitJoinWait(s.lifecycleThread);
        check(ack.getCount()==1 && createdLater.closeEntered.getCount()==1,
              "release sampled frame/host before preparation barrier");
        framePermit.countDown();join(s.frameThread);await(createdLater.closeEntered,"late-created host never closed");
        createdLater.closePermit.countDown();await(ack,"late-prepared release not acknowledged");terminated(s);
    }
    static void prepareFailure(boolean setup){
        LibretroEngineSession s=new LibretroEngineSession();LibretroHost opened=s.host;s.host=null;
        Throwable originalFailure=setup?new PcEngineCdFirmware.SetupException("System Card required"):
            new IllegalStateException("ready callback failed");
        CountDownLatch framePermit=new CountDownLatch(1),renderPermit=new CountDownLatch(1);
        CountDownLatch reported=new CountDownLatch(1),ack=new CountDownLatch(1);
        s.frameThread=blockedThread(framePermit);s.renderThread=blockedThread(renderPermit);
        // Even failed focus cleanup must not skip release submission or the
        // original error callback. The queued release repeats cleanup safely.
        s.audioFocus.fail=true;
        Listener callback=new Listener(){
            public void onSessionStopRejected(String message,Throwable failure){}
            public void onSessionError(String message,Throwable failure){
                check(failure==originalFailure,"original preparation failure lost");
                check(message.equals(setup?"System Card required":"EmuFusion could not start test game."),
                      "preparation error message lost");
                check(s.host==opened && s.released.get(),"error reported before retained owner was queued for release");
                reported.countDown();
            }
        };
        s.lifecycle.execute(()->s.prepareFailureFixture(opened,new GameLaunchRequest(),callback,originalFailure));
        await(reported,"preparation error callback suppressed by cleanup failure");
        awaitJoinWait(s.lifecycleThread);
        s.releaseWhenComplete(ack::countDown);
        check(s.host==opened && opened.closes.get()==0 && ack.getCount()==1,
              "preparation failure closed a live frame/render owner or acknowledged early");
        framePermit.countDown();join(s.frameThread);
        check(opened.closes.get()==0,"preparation cleanup bypassed live renderer");
        renderPermit.countDown();join(s.renderThread);
        await(opened.closeEntered,"preparation failure never reached queued native close");
        check(ack.getCount()==1,"preparation failure acknowledged before native close returned");
        opened.closePermit.countDown();await(ack,"preparation failure release was not acknowledged");terminated(s);
        check(s.host==null && opened.closes.get()==1,"failed preparation ownership was not retired exactly once");
    }
    static void interruptedJoin(){
        CountDownLatch ownerPermit=new CountDownLatch(1),entered=new CountDownLatch(1),done=new CountDownLatch(1);
        Thread owner=blockedThread(ownerPermit);AtomicBoolean interrupted=new AtomicBoolean();
        Thread joining=new Thread(()->{
            Thread.currentThread().interrupt();entered.countDown();
            interrupted.set(joinReleaseThread(owner));done.countDown();
        });
        joining.setDaemon(true);joining.start();await(entered,"join worker not started");
        awaitJoinWait(joining);
        check(done.getCount()==1,"interrupted join acknowledged a live worker");
        ownerPermit.countDown();await(done,"interrupted join did not finish after owner");join(joining);join(owner);
        check(interrupted.get(),"join lost interruption state");
    }
    static void scummFailure(boolean destroyed){
        LibretroEngineSession s=new LibretroEngineSession();s.entry.id="scummvm";
        LibretroHost original=s.host;original.failUnload=true;
        CountDownLatch rejected=new CountDownLatch(1),completed=new CountDownLatch(2);
        AtomicInteger callbacks=new AtomicInteger();s.listener=(message,failure)->rejected.countDown();
        Completion callback=()->{callbacks.incrementAndGet();completed.countDown();};
        s.stop(StopReason.EXIT_TO_LUCENT,callback);await(original.unloadEntered,"ScummVM unload not entered");
        s.stop(destroyed?StopReason.ACTIVITY_DESTROYED:StopReason.EXIT_TO_LUCENT,callback);
        check(callbacks.get()==0,"duplicate stop acknowledged in-flight ScummVM unload");
        original.unloadPermit.countDown();
        if(destroyed){await(completed,"destroy-upgraded failed stop stranded retirement");check(callbacks.get()==2,"destroy stop fanout lost");}
        else {
            await(rejected,"ordinary ScummVM failure not rejected");
            check(callbacks.get()==0 && s.running && !s.stopping.get() && s.stopCompletions.isEmpty(),
                  "ordinary ScummVM failure acknowledged success or lost playable ownership");
        }
        CountDownLatch ack=new CountDownLatch(1);s.releaseWhenComplete(ack::countDown);
        await(original.closeEntered,"ScummVM native close missing after release");
        check(ack.getCount()==1,"ScummVM stop failure mistaken for native-close success");
        original.closePermit.countDown();await(ack,"ScummVM native release missing");terminated(s);
    }
    public static void main(String[] args){
        switch(args[0]){
            case "close":delayedClose();break;
            case "peers":delayedPeers();break;
            case "close_failure":closeFailure();break;
            case "stops":duplicateStops(false);break;
            case "save_failure":duplicateStops(true);break;
            case "late_prepare":latePrepare();break;
            case "prepare_failure":prepareFailure(false);break;
            case "prepare_setup_failure":prepareFailure(true);break;
            case "interrupted_join":interruptedJoin();break;
            case "scumm_failure":scummFailure(false);break;
            case "scumm_destroy":scummFailure(true);break;
            default:throw new AssertionError(args[0]);
        }
    }
}
'''


class LibretroReleaseCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (JAVA / "javac").exists():
            raise unittest.SkipTest("Local JDK 17 unavailable")
        source = SESSION.read_text()
        names = ("stop", "completeStop", "saveScummvmExit", "rejectScummvmStop", "release", "releaseWhenComplete",
                 "completeRelease", "joinReleaseThread")
        actual = "\n".join(method(source, name) for name in names)
        inner, outer = prepare_failure_catches(source)
        actual += ("\nvoid prepareFailureFixture(LibretroHost opened, GameLaunchRequest launch, Listener callback, Throwable originalFailure) {"
                   "\ntry { try { throw originalFailure; }\n" +
                   inner + "\n} " + outer + "\n}")
        cls.temp = tempfile.TemporaryDirectory(prefix="libretro-release-completion-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        java = directory / "LibretroEngineSession.java"
        java.write_text(SHELL.replace("// ACTUAL_METHODS", actual).replace(
            "// ACTUAL_SETUP_EXCEPTION", member(FIRMWARE.read_text(), "static final class SetupException")))
        result = subprocess.run([str(JAVA / "javac"), "-d", str(directory), str(java)],
                                text=True, capture_output=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, case):
        result = subprocess.run([str(JAVA / "java"), "-cp", self.temp.name,
                                 "LibretroEngineSession", case],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_delayed_native_close_and_duplicate_release(self):
        self.run_case("close")

    def test_release_waits_frame_renderer_vault_and_native_owners(self):
        self.run_case("peers")

    def test_close_error_never_clears_host_or_acknowledges(self):
        self.run_case("close_failure")

    def test_duplicate_stops_wait_original_checkpoint(self):
        self.run_case("stops")

    def test_checkpoint_error_is_not_native_release_success(self):
        self.run_case("save_failure")

    def test_release_waits_owners_published_by_inflight_prepare(self):
        self.run_case("late_prepare")

    def test_actual_prepare_failure_queues_release_and_preserves_error_notification(self):
        self.run_case("prepare_failure")

    def test_actual_firmware_setup_failure_preserves_specific_error_and_queues_release(self):
        self.run_case("prepare_setup_failure")

    def test_prepare_failure_binding_retains_owner_and_never_closes_inline(self):
        source = SESSION.read_text()
        prepare = method(source, "prepare")
        inner, outer = prepare_failure_catches(source)
        self.assertLess(prepare.index("startFrameThread();"),
                        prepare.index("callback.onSessionReady();"))
        self.assertIn("host = opened;", inner)
        self.assertIn("throw failure;", inner)
        self.assertIn("releaseWhenComplete(() -> {});", outer)
        self.assertIn("callback.onSessionError(", outer)
        for catch in (inner, outer):
            self.assertNotIn(".close();", catch)
            self.assertNotIn("SecondaryGameplaySurfaceRouter.release", catch)

    def test_interrupted_real_join_waits_owner_and_retains_interrupt_result(self):
        self.run_case("interrupted_join")

    def test_scummvm_stop_failure_rejects_without_premature_completion(self):
        self.run_case("scumm_failure")

    def test_destroy_upgrade_retires_after_scummvm_stop_failure(self):
        self.run_case("scumm_destroy")


if __name__ == "__main__":
    unittest.main()
