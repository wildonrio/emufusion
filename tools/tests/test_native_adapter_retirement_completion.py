"""Execute current native-adapter retirement methods with real threads and fake JNI."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java"
POLICY = ROOT / "unified-android/src/com/thorium/lucent/emulators/NativeAdapterStopPolicy.java"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


def member(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                    lambda match: " " * len(match.group()), source, flags=re.S)
    depth = 0
    for end in range(opening, len(source)):
        depth += (masked[end] == "{") - (masked[end] == "}")
        if not depth:
            return source[start:end + 1]
    raise AssertionError("Unclosed member: " + signature)


HARNESS = r'''
import java.io.File;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import com.thorium.lucent.emulators.NativeAdapterStopPolicy;
import com.thorium.preview.game.DiscImagePreflight;
interface EngineSession {
    enum StopReason { EXIT_TO_LUCENT, ACTIVITY_DESTROYED }
    interface Completion { void complete(); }
    interface Listener {
        void onSessionStopRejected(String message,Throwable failure);
        void onRestoreAvailabilityChanged(boolean available);
        default void onSessionError(String message,Throwable failure){}
    }
    void stop(StopReason reason,Completion completion);
    void release();
}
final class Log {
    static final List<String> info=new CopyOnWriteArrayList<>();
    static final List<String> errors=new CopyOnWriteArrayList<>();
    static void i(String tag,String message){info.add(message);}
    static void w(String tag,String message){}
    static void w(String tag,String message,Throwable failure){}
    static void e(String tag,String message,Throwable failure){errors.add(message);}
}
final class DurableBlobStore {
    static volatile boolean fail;
    static final AtomicInteger writes=new AtomicInteger();
    static void write(File file,byte[] value,int limit){
        if(fail)throw new IllegalStateException("commit failed");
        writes.incrementAndGet();
    }
}
// Formatting has its own filesystem tests; retirement must preserve the
// original callback while it exercises the real preparation catch block.
final class NativeAdapterSystemDirectory {
    static String prerequisiteHelp(String engine, String system, Throwable failure) { return ""; }
}
final class NativeAdapterHost {
    static class Capabilities { boolean hasQuickResume,hasPersistentSave; }
    final AtomicInteger stops=new AtomicInteger(),closes=new AtomicInteger(),flushes=new AtomicInteger();
    final AtomicInteger serializes=new AtomicInteger();
    final CountDownLatch closeEntered=new CountDownLatch(1),closeAllowed=new CountDownLatch(1);
    volatile boolean stopFailure,closeFailure,blockClose,flushFailure;
    byte[] state=new byte[]{1};
    Runnable beforeStop=()->{};
    void stop(){
        beforeStop.run();stops.incrementAndGet();
        if(stopFailure)throw new IllegalStateException("native stop failed");
    }
    void close(){
        closes.incrementAndGet();closeEntered.countDown();
        if(blockClose)NativeAdapterEngineSession.waitUninterruptibly(closeAllowed);
        if(closeFailure)throw new IllegalStateException("native close failed");
    }
    void flushSave(){flushes.incrementAndGet();if(flushFailure)throw new IllegalStateException("flush failed");}
    byte[] serialize(){serializes.incrementAndGet();return state;}
}
public class NativeAdapterEngineSession implements EngineSession {
    static final String TAG="test";
    static final int MAX_QUICK_RESUME_BYTES=1024;
    static final long RENDER_TASK_TIMEOUT_MS=20;
    static final long QUICK_RESUME_TASK_TIMEOUT_MS=2000;
    static class Entry { String id="eden"; }
    static class Request { String systemId="switch"; }
    static class AudioFocus {
        final AtomicInteger abandons=new AtomicInteger();
        boolean fail;
        void abandon(){abandons.incrementAndGet();if(fail)throw new IllegalStateException("focus failed");}
    }
    final Entry entry=new Entry();
    final Request request=new Request();
    final AudioFocus audioFocus=new AudioFocus();
    final AtomicReference<Thread> lifecycleThread=new AtomicReference<>();
    final ExecutorService lifecycle=Executors.newSingleThreadExecutor(task->{
        Thread thread=new Thread(task,"fake-native-lifecycle");thread.setDaemon(true);
        lifecycleThread.set(thread);return thread;
    });
    final BlockingQueue<RenderTask> renderTasks=new LinkedBlockingQueue<>();
    volatile NativeAdapterHost host=new NativeAdapterHost();
    volatile NativeAdapterHost.Capabilities capabilities=new NativeAdapterHost.Capabilities();
    volatile Thread renderThread;
    volatile boolean prepared=true,started=true,resumeRequested=true;
    boolean serializationFailure,audioFailure,secondaryFailure;
    final AtomicInteger rejected=new AtomicInteger();
    File saveRamFile;
    Listener listener=new Listener(){
        public void onSessionStopRejected(String message,Throwable failure){rejected.incrementAndGet();}
        public void onRestoreAvailabilityChanged(boolean available){}
    };
    void detachSecondaryBeforeBlank(){
        if(secondaryFailure)throw new IllegalStateException("secondary release failed");
    }
    void releaseSecondaryDisplay(){detachSecondaryBeforeBlank();}
    void releaseAudio(){if(audioFailure)throw new IllegalStateException("audio release failed");}
    // ACTUAL_FIELDS
    // ACTUAL_METHODS
    NativeAdapterEngineSession(){
        host.beforeStop=()->{
            check(renderThread==null || !renderThread.isAlive(),"native stop overlapped render owner");
            check(!Thread.currentThread().isInterrupted(),"join interrupt leaked into native stop");
        };
    }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void await(BooleanSupplier condition,String message) throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(4);
        while(!condition.getAsBoolean() && System.nanoTime()<deadline)Thread.sleep(2);
        check(condition.getAsBoolean(),message);
    }
    static void waitUninterruptibly(CountDownLatch latch){
        boolean interrupted=false;
        for(;;)try {latch.await();break;}catch(InterruptedException e){interrupted=true;}
        if(interrupted)Thread.currentThread().interrupt();
    }
    static Thread blockedOwner(CountDownLatch allowed){
        Thread thread=new Thread(()->waitUninterruptibly(allowed),"fake-native-render");
        thread.setDaemon(true);thread.start();return thread;
    }
    static void noStopReleaseAndDuplicates() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        h.blockClose=true;AtomicInteger done=new AtomicInteger();
        s.release();s.releaseWhenComplete(done::incrementAndGet);
        check(h.closeEntered.await(2,TimeUnit.SECONDS),"close was not submitted");
        s.releaseWhenComplete(done::incrementAndGet);
        check(done.get()==0 && s.host==h,"queued close falsely completed or lost host");
        h.closeAllowed.countDown();await(()->done.get()==2,"late close did not complete duplicates");
        s.releaseWhenComplete(done::incrementAndGet);
        check(done.get()==3 && s.host==null && h.stops.get()==1 && h.closes.get()==1,
                "release was not one-shot after actual close");
    }
    static void lateAndInterruptedOwner() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        CountDownLatch ownerAllowed=new CountDownLatch(1);Thread owner=blockedOwner(ownerAllowed);
        s.renderThread=owner;AtomicInteger done=new AtomicInteger();
        s.releaseWhenComplete(done::incrementAndGet);
        await(()->!s.prepared,"lifecycle did not begin join");
        Thread.sleep(2100); // Explicitly cross the obsolete two-second join bound.
        check(done.get()==0 && s.renderThread==owner && h.stops.get()==0,
                "join timeout released a live native owner");
        s.lifecycleThread.get().interrupt();Thread.sleep(25);
        check(done.get()==0 && s.renderThread==owner && h.stops.get()==0,
                "interrupted join released a live native owner");
        ownerAllowed.countDown();await(()->done.get()==1,"actual owner return did not complete");
        check(s.renderThread==null && s.host==null && h.closes.get()==1,"retirement not complete");
    }
    static void duplicateStopAndRelease() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        h.blockClose=true;AtomicInteger stopped=new AtomicInteger(),released=new AtomicInteger();
        s.stop(StopReason.EXIT_TO_LUCENT,stopped::incrementAndGet);
        check(h.closeEntered.await(2,TimeUnit.SECONDS),"stop never reached native close");
        s.stop(StopReason.ACTIVITY_DESTROYED,stopped::incrementAndGet);
        s.releaseWhenComplete(released::incrementAndGet);
        s.stop(StopReason.ACTIVITY_DESTROYED,stopped::incrementAndGet);
        check(stopped.get()==0 && released.get()==0,"duplicate stop/release completed early");
        h.closeAllowed.countDown();await(()->stopped.get()==3 && released.get()==1,"waiters lost");
        check(h.stops.get()==1 && h.closes.get()==1 && s.host==null,"stop-release closed twice");
    }
    static void closeErrorsKeepOwner(boolean stopFailure,boolean stopFirst) throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        h.stopFailure=stopFailure;h.closeFailure=!stopFailure;AtomicInteger done=new AtomicInteger();
        if(stopFirst)s.stop(StopReason.ACTIVITY_DESTROYED,done::incrementAndGet);
        else s.releaseWhenComplete(done::incrementAndGet);
        await(()->s.lifecycleThread.get()!=null,"lifecycle not started");
        if(stopFirst)s.lifecycle.submit(()->{}).get(2,TimeUnit.SECONDS);
        else check(s.lifecycle.awaitTermination(2,TimeUnit.SECONDS),"release worker did not finish");
        if(stopFirst)s.stop(StopReason.ACTIVITY_DESTROYED,done::incrementAndGet);
        else s.releaseWhenComplete(done::incrementAndGet);
        check(done.get()==0 && s.host==h,"native failure lost owner or acknowledged completion");
        check(h.stops.get()==1 && h.closes.get()==(stopFailure?0:1),"unsafe implicit close retry");
    }
    static void saveAndCleanupErrorsStillRequireNativeReturn() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        s.capabilities.hasQuickResume=true;s.serializationFailure=true;
        s.audioFailure=true;s.secondaryFailure=true;h.blockClose=true;
        AtomicInteger done=new AtomicInteger();
        s.listener=new Listener(){
            public void onSessionStopRejected(String m,Throwable f){s.rejected.incrementAndGet();throw new RuntimeException();}
            public void onRestoreAvailabilityChanged(boolean available){throw new RuntimeException();}
        };
        s.stop(StopReason.ACTIVITY_DESTROYED,done::incrementAndGet);
        check(h.closeEntered.await(2,TimeUnit.SECONDS),"save/callback error prevented native retirement");
        check(done.get()==0 && s.host==h && s.rejected.get()==1,"save error faked completion");
        h.closeAllowed.countDown();await(()->done.get()==1,"late cleanup did not complete");
    }
    static void releaseAfterFailedStopCanAcknowledgeActualRetry() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        h.closeFailure=true;AtomicInteger done=new AtomicInteger();
        s.stop(StopReason.ACTIVITY_DESTROYED,done::incrementAndGet);
        s.lifecycle.submit(()->{}).get(2,TimeUnit.SECONDS);
        check(done.get()==0 && s.host==h,"failed stop did not retain owner");
        h.closeFailure=false;s.releaseWhenComplete(done::incrementAndGet);
        await(()->done.get()==2,"actual release did not drain failed stop observer");
        check(h.closes.get()==2 && s.host==null,"explicit release did not close retained owner");
    }
    static void durableSaveFailureIsNotReportedAsSuccess() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        s.capabilities.hasPersistentSave=true;h.flushFailure=true;AtomicInteger done=new AtomicInteger();
        s.stop(StopReason.EXIT_TO_LUCENT,done::incrementAndGet);
        await(()->done.get()==1,"flush failure changed final-stop retirement policy");
        check(s.rejected.get()==1 && h.flushes.get()==1 && h.closes.get()==1,"flush failure was not reported");
        check(Log.info.stream().noneMatch(text->text.contains("save flushed and session stopped")),
                "failed durable flush reported a successful save");
    }
    static void failedStartDoesNotSaveOrWarn() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        s.started=false;s.prepared=false;
        s.capabilities.hasQuickResume=true;s.capabilities.hasPersistentSave=true;
        h.flushFailure=true;h.state=null;AtomicInteger done=new AtomicInteger();
        s.stop(StopReason.EXIT_TO_LUCENT,done::incrementAndGet);
        await(()->done.get()==1,"failed launch did not retire");
        check(s.rejected.get()==0 && h.flushes.get()==0 && h.serializes.get()==0,
                "unstarted guest attempted a save or reported save loss");
        check(DurableBlobStore.writes.get()==0 && h.stops.get()==1 && h.closes.get()==1,
                "unstarted guest changed checkpoint or skipped native cleanup");
        check(Log.info.stream().noneMatch(text->text.contains("save flushed and session stopped")),
                "unstarted guest falsely claimed a saved game");
        check(Log.info.stream().anyMatch(text->text.contains("marker=unstarted-no-save")),
                "missing explicit no-save outcome");
    }
    static void stopWhileStarting(boolean quickResume, boolean startSucceeds) throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        s.started=false;s.capabilities.hasQuickResume=quickResume;s.capabilities.hasPersistentSave=true;
        CountDownLatch begin=new CountDownLatch(1);AtomicInteger done=new AtomicInteger();
        s.renderThread=new Thread(()->{
            waitUninterruptibly(begin);
            s.started=startSucceeds;
            if(!startSucceeds){s.prepared=false;s.abandonRenderTasks();return;}
            while(s.prepared){
                RenderTask task=s.renderTasks.poll();if(task!=null)task.run();
                else Thread.yield();
            }
        });
        s.renderThread.start();s.stop(StopReason.EXIT_TO_LUCENT,done::incrementAndGet);
        await(()->quickResume ? !s.renderTasks.isEmpty() : !s.prepared,"stop not waiting on start");
        check(h.flushes.get()==0 && h.serializes.get()==0 && done.get()==0,"save/close overtook start");
        begin.countDown();await(()->done.get()==1,"pending start was not retired");
        check(h.flushes.get()==(startSucceeds?1:0),"flush decision used stale pre-start state");
        check(h.serializes.get()==(startSucceeds&&quickResume?1:0),"snapshot decision used stale start state");
        check(DurableBlobStore.writes.get()==(startSucceeds&&quickResume?1:0),"wrong checkpoint write count");
        check(s.rejected.get()==0 && h.closes.get()==1,"pending start introduced save error or leaked host");
    }
    static void emptyStartedSnapshotStillFails() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        s.capabilities.hasQuickResume=true;h.state=null;AtomicInteger done=new AtomicInteger();
        s.renderThread=new Thread(()->{
            while(s.prepared){RenderTask task=s.renderTasks.poll();if(task!=null)task.run();else Thread.yield();}
        });
        s.renderThread.start();s.stop(StopReason.EXIT_TO_LUCENT,done::incrementAndGet);
        await(()->done.get()==1,"invalid snapshot did not retire");
        check(s.rejected.get()==1 && h.serializes.get()==1 && DurableBlobStore.writes.get()==0,
                "empty snapshot of started guest silently accepted");
    }
    static void startupErrorMessageIsPreserved() {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();s.started=false;
        String detail="Switch graphics could not start: Vulkan initialization failed";
        check(detail.equals(s.sessionFailureMessage(new IllegalStateException(detail))),"startup cause hidden");
        check(s.sessionFailureMessage(null).equals("EmuFusion could not start eden."),"null cause lacks fallback");
        check(s.sessionFailureMessage(new RuntimeException(" ")).equals("EmuFusion could not start eden."),"empty cause lacks fallback");
        s.started=true;
        check(s.sessionFailureMessage(new RuntimeException(detail)).equals("The native adapter stopped."),"runtime failure classified as startup");
    }
    static void retainedAps3ePolicyIsNotNativeClose() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        s.entry.id="aps3e";s.capabilities.hasQuickResume=true;s.serializationFailure=true;
        AtomicInteger done=new AtomicInteger();
        s.stop(StopReason.EXIT_TO_LUCENT,done::incrementAndGet);
        await(()->done.get()==1,"retained policy failed to retire Java owner");
        s.releaseWhenComplete(done::incrementAndGet);await(()->done.get()==2,"retained release incomplete");
        check(h.stops.get()==0 && h.closes.get()==0 && s.rejected.get()==0 && s.host==null,
                "aPS3e deliberate process-retirement policy changed");
        check(NativeAdapterStopPolicy.requiresCleanFrontendRestart("aps3e"),"retained host lacks restart policy");
        check(Log.info.stream().anyMatch(text->text.contains("nativeHost=retained-for-process-exit")),
                "retained release was not distinguished from native close");
    }
    static void latePreparationIsObserved() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        s.host=null;CountDownLatch prepareEntered=new CountDownLatch(1),prepareAllowed=new CountDownLatch(1);
        CountDownLatch ownerAllowed=new CountDownLatch(1);AtomicInteger done=new AtomicInteger();
        s.lifecycle.execute(()->{prepareEntered.countDown();waitUninterruptibly(prepareAllowed);
            s.host=h;s.prepared=true;s.renderThread=blockedOwner(ownerAllowed);});
        check(prepareEntered.await(2,TimeUnit.SECONDS),"prepare not entered");
        s.releaseWhenComplete(done::incrementAndGet);check(done.get()==0,"release skipped pending prepare");
        check(s.audioFocus.abandons.get()==1,"first release kept focus behind pending prepare");
        prepareAllowed.countDown();await(()->s.renderThread!=null && !s.prepared,"late owner not joined");
        check(done.get()==0 && h.stops.get()==0,"late prepare owner bypassed retirement");
        ownerAllowed.countDown();await(()->done.get()==1,"late prepared host not retired");
        check(s.audioFocus.abandons.get()==2,"release did not abandon focus acquired by late prepare");
    }
    static void callbackAndSchedulingErrors() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        h.blockClose=true;AtomicInteger done=new AtomicInteger();
        s.releaseWhenComplete(()->{throw new RuntimeException("callback");});
        s.releaseWhenComplete(done::incrementAndGet);h.closeAllowed.countDown();
        await(()->done.get()==1,"throwing callback lost another waiter");
        NativeAdapterEngineSession rejected=new NativeAdapterEngineSession();rejected.lifecycle.shutdown();
        rejected.releaseWhenComplete(done::incrementAndGet);rejected.releaseWhenComplete(done::incrementAndGet);
        check(done.get()==1 && rejected.host!=null,"rejected executor faked completion");
    }
    static void lifecycleFlagsNeverDispatchAgainstRetiringOwner() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();
        CountDownLatch allowed=new CountDownLatch(1);s.renderThread=blockedOwner(allowed);
        AtomicInteger calls=new AtomicInteger();
        s.stopping.set(true);s.runOnRenderThread(calls::incrementAndGet);
        s.stopping.set(false);s.released.set(true);s.runOnRenderThread(calls::incrementAndGet);
        s.released.set(false);s.prepared=false;s.runOnRenderThread(calls::incrementAndGet);
        check(calls.get()==0 && s.renderTasks.isEmpty(),"retiring owner dispatched caller-thread native action");
        allowed.countDown();s.renderThread.join();
    }
    static void prepareFailureJoinsOwnerAndReportsCleanupFailure() throws Exception {
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();NativeAdapterHost h=s.host;
        h.closeFailure=true;s.secondaryFailure=true;s.audioFocus.fail=true;
        CountDownLatch ownerAllowed=new CountDownLatch(1);s.renderThread=blockedOwner(ownerAllowed);
        AtomicInteger errors=new AtomicInteger();AtomicReference<Throwable> notified=new AtomicReference<>();
        Throwable original=new IllegalStateException("ready callback failed");
        Listener callback=new Listener(){
            public void onSessionStopRejected(String m,Throwable f){}
            public void onRestoreAvailabilityChanged(boolean available){}
            public void onSessionError(String m,Throwable f){notified.set(f);errors.incrementAndGet();}
        };
        s.lifecycle.execute(()->s.failPreparation(callback,original));
        await(()->!s.prepared,"failed preparation did not begin owner join");
        check(h.stops.get()==0 && errors.get()==0,"failed preparation closed against live owner");
        ownerAllowed.countDown();await(()->errors.get()==1,"cleanup failure swallowed session error");
        check(s.renderThread==null && s.host==h && h.closes.get()==1,
                "failed preparation lost unclosed native host");
        check(notified.get()==original && original.getSuppressed().length==3,
                "cleanup failures replaced or concealed original preparation failure");
        check(Log.errors.stream().anyMatch(text->text.contains("failed-preparation teardown is incomplete")),
                "failed preparation native close was not reported");
    }
    public static void main(String[] args) throws Exception {
        switch(args[0]){
            case "release":noStopReleaseAndDuplicates();break;
            case "late":lateAndInterruptedOwner();break;
            case "stop-release":duplicateStopAndRelease();break;
            case "release-stop-error":closeErrorsKeepOwner(true,false);break;
            case "release-close-error":closeErrorsKeepOwner(false,false);break;
            case "stop-stop-error":closeErrorsKeepOwner(true,true);break;
            case "stop-close-error":closeErrorsKeepOwner(false,true);break;
            case "save-error":saveAndCleanupErrorsStillRequireNativeReturn();break;
            case "retry":releaseAfterFailedStopCanAcknowledgeActualRetry();break;
            case "flush":durableSaveFailureIsNotReportedAsSuccess();break;
            case "failed-start":failedStartDoesNotSaveOrWarn();break;
            case "pending-persistent-success":stopWhileStarting(false,true);break;
            case "pending-persistent-failure":stopWhileStarting(false,false);break;
            case "pending-snapshot-success":stopWhileStarting(true,true);break;
            case "pending-snapshot-failure":stopWhileStarting(true,false);break;
            case "empty-snapshot":emptyStartedSnapshotStillFails();break;
            case "startup-message":startupErrorMessageIsPreserved();break;
            case "aps3e":retainedAps3ePolicyIsNotNativeClose();break;
            case "prepare":latePreparationIsObserved();break;
            case "callback":callbackAndSchedulingErrors();break;
            case "dispatch":lifecycleFlagsNeverDispatchAgainstRetiringOwner();break;
            case "prepare-error":prepareFailureJoinsOwnerAndReportsCleanupFailure();break;
            default:throw new AssertionError(args[0]);
        }
    }
}
'''


class NativeAdapterRetirementExecutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SESSION.read_text()
        start = source.index("    private final AtomicBoolean stopping =")
        end = source.index("    private final AtomicBoolean audioFailureReported", start)
        fields = source[start:end]
        signatures = (
            "public void stop(", "private void stopOnLifecycle(", "private void completeStop(",
            "public void release()", "public void releaseWhenComplete(",
            "private void releaseOnLifecycle(", "private void retireSessionOwner(",
            "private static void completeRetirementCallback(", "private boolean runFlushSave(",
            "private void runRetirementTask(",
            "private byte[] serializeQuickResumeOnRenderThread(",
            "private String sessionFailureMessage(", "private void abandonRenderTasks(",
            "private void retireHost(", "private void closeHost(", "private void joinRenderThread(",
            "private void runOnRenderThread(", "private static void runQuietly(",
            "private static final class RenderTask")
        actual = "\n".join(member(source, signature) for signature in signatures)
        prepare = member(source, "public void prepare(")
        catch_body = member(prepare, "catch (Throwable failure)")
        actual += ("\nprivate void failPreparation(Listener callback, Throwable failure) " +
                   catch_body[catch_body.index("{"):])
        cls.temp = tempfile.TemporaryDirectory(prefix="native-adapter-retirement-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        target = cls.directory / "NativeAdapterEngineSession.java"
        target.write_text(HARNESS.replace("// ACTUAL_FIELDS", fields).replace("// ACTUAL_METHODS", actual))
        result = subprocess.run([str(JAVA / "javac"), "-d", str(cls.directory), str(POLICY),
                                 str(SESSION.parent / "DiscImagePreflight.java"), str(target)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("Actual native-adapter retirement compile failed:\n" + result.stderr)

    def scenario(self, name):
        result = subprocess.run([str(JAVA / "java"), "-cp", str(self.directory),
                                 "NativeAdapterEngineSession", name],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_no_stop_release_and_duplicate_waiters(self): self.scenario("release")
    def test_join_past_old_bound_and_interruption_wait_for_actual_owner(self): self.scenario("late")
    def test_duplicate_stop_stop_then_release_and_stop_after_release(self): self.scenario("stop-release")
    def test_release_stop_failure_keeps_host_and_no_ack(self): self.scenario("release-stop-error")
    def test_release_close_failure_keeps_host_and_no_ack(self): self.scenario("release-close-error")
    def test_stop_native_stop_failure_keeps_host_and_no_ack(self): self.scenario("stop-stop-error")
    def test_stop_native_close_failure_keeps_host_and_no_ack(self): self.scenario("stop-close-error")
    def test_save_audio_secondary_and_listener_failure_wait_for_close(self): self.scenario("save-error")
    def test_explicit_release_after_failed_stop_acknowledges_only_actual_close(self): self.scenario("retry")
    def test_failed_durable_flush_is_reported_without_success_claim(self): self.scenario("flush")
    def test_failed_start_preserves_checkpoint_without_false_save_warning(self): self.scenario("failed-start")
    def test_stop_during_successful_start_flushes_after_owner_returns(self): self.scenario("pending-persistent-success")
    def test_stop_during_failed_start_does_not_flush(self): self.scenario("pending-persistent-failure")
    def test_stop_during_successful_start_serializes_on_owner(self): self.scenario("pending-snapshot-success")
    def test_stop_during_failed_start_preserves_previous_snapshot(self): self.scenario("pending-snapshot-failure")
    def test_started_guest_empty_snapshot_is_still_a_save_error(self): self.scenario("empty-snapshot")
    def test_startup_message_preserves_native_cause_and_runtime_fallback(self): self.scenario("startup-message")
    def test_aps3e_deliberate_process_retirement_policy_is_preserved(self): self.scenario("aps3e")
    def test_release_observes_host_and_worker_published_by_pending_prepare(self): self.scenario("prepare")
    def test_throwing_callback_and_rejected_executor_do_not_fake_ack(self): self.scenario("callback")
    def test_stopping_released_and_unprepared_live_owner_drop_new_native_dispatch(self): self.scenario("dispatch")
    def test_prepare_error_joins_live_owner_retains_failed_close_and_notifies_original_error(self):
        self.scenario("prepare-error")

    def test_prepare_keeps_created_host_reachable_before_fallible_initialization(self):
        source = SESSION.read_text()
        prepare = member(source, "public void prepare(")
        self.assertLess(prepare.index("host = created;"), prepare.index("created.describe()"))
        self.assertIn("failure.addSuppressed(closeFailure)", prepare)


if __name__ == "__main__":
    unittest.main()
