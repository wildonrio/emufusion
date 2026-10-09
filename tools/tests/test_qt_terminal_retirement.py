"""Execute the Qt terminal-shutdown coordinator without Android or native cores."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


def member(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                    lambda match: " " * len(match.group()), source, flags=re.DOTALL)
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
    match = re.search(r"(?:public|private)\s+(?:static\s+)?(?:synchronized\s+)?"
                      r"(?:void|boolean)\s+" + re.escape(name) + r"\(", source)
    if match is None:
        raise AssertionError("Missing actual host method " + name)
    return member(source, match.group())


SHELL = r'''
import java.util.*;
import android.app.Activity;
public class InWindowGameHost {
    static final String TAG="test";
    static InWindowGameHost active;
    static final Set<Object> RETIRING_SESSIONS=new HashSet<>();
    static final Map<Activity,Object> RECREATIONS=new HashMap<>();
    static int destroyedSessionsRetiring;
    static boolean cleanFrontendRestartPending,importFrontendRestartPending;
    static final Activity MAIN=new org.pegasus_frontend.android.MainActivity();
    static Thread QT_THREAD;
    static Thread completedThread(){
        Thread thread=new Thread(()->{});
        thread.start();
        try { thread.join(); } catch(InterruptedException failure) { throw new AssertionError(failure); }
        return thread;
    }
    Activity activity;
    Object session;
    int destroyCalls;
    void destroyNow(){destroyCalls++;}
    static class Looper {
        static final Looper MAIN=new Looper();
        static Looper getMainLooper(){return MAIN;}
    }
    static class Handler {
        static final ArrayDeque<Runnable> QUEUE=new ArrayDeque<>();
        static int posts;
        Handler(Looper looper){check(looper==Looper.MAIN,"not main looper");}
        boolean post(Runnable r){posts++;QUEUE.add(r);return true;}
        static void drain(){
            int limit=20;
            while(!QUEUE.isEmpty()){
                check(--limit>0,"unbounded repost loop");
                QUEUE.remove().run();
            }
        }
    }
    static class Log {
        static void i(String a,String b){}
        static void w(String a,String b){}
        static void e(String a,String b,Throwable t){}
    }
    // ACTUAL_COORDINATOR
    static boolean finishQtTerminalProcess(Activity owner){
        return finishQtTerminalProcess(owner,QT_THREAD);
    }
    static int callbacks,secondCallbacks;
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void terminal(){
        check(!Thread.holdsLock(InWindowGameHost.class),"terminal ran under host monitor");
        check(active==null && RETIRING_SESSIONS.isEmpty() && destroyedSessionsRetiring==0,
              "terminal ran with live engine owner");
        check("1".equals(android.system.Os.value),"Qt native exit not disabled before terminal");
        callbacks++;
    }
    static void idleOnce(){
        check(!isQtTerminalShutdownPending(),"fresh process already terminal");
        check(requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal),"Main request rejected");
        check(isQtTerminalShutdownPending(),"request did not immediately reserve shutdown");
        check(callbacks==0,"terminal ran inline");
        check(Handler.posts==1,"idle request not posted exactly once");
        check(requestQtTerminalShutdown(MAIN,()->secondCallbacks++),"duplicate Main not consumed");
        dispatchQtTerminalShutdownIfReady();
        Handler.drain();
        check(callbacks==1 && secondCallbacks==0,"first callback did not win");
        requestQtTerminalShutdown(MAIN,()->secondCallbacks++);
        dispatchQtTerminalShutdownIfReady(); Handler.drain();
        check(callbacks==1 && secondCallbacks==0,"terminal retried after dispatch");
        check(isQtTerminalShutdownPending(),"terminal reservation reopened");
    }
    static void allOwners(){
        Object one=new Object(),two=new Object();
        active=new InWindowGameHost(); RETIRING_SESSIONS.add(one); RETIRING_SESSIONS.add(two);
        destroyedSessionsRetiring=2;
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal); Handler.drain();
        check(callbacks==0,"live active session ignored");
        active=null; dispatchQtTerminalShutdownIfReady(); Handler.drain();
        check(callbacks==0,"normal/destroyed retirement ignored");
        RETIRING_SESSIONS.remove(one); destroyedSessionsRetiring--;
        dispatchQtTerminalShutdownIfReady(); Handler.drain();
        check(callbacks==0,"only one owner was required");
        RETIRING_SESSIONS.remove(two); dispatchQtTerminalShutdownIfReady(); Handler.drain();
        check(callbacks==0,"last destroyed owner ignored");
        destroyedSessionsRetiring--; dispatchQtTerminalShutdownIfReady();
        check(callbacks==0,"last-owner transition ran terminal inline");
        Handler.drain(); check(callbacks==1,"fully quiesced terminal missing");
    }
    static void failedRelease(){
        Object failed=new Object(); RETIRING_SESSIONS.add(failed);
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal);
        for(int i=0;i<4;i++){dispatchQtTerminalShutdownIfReady();Handler.drain();}
        check(callbacks==0,"failed/pending normal release lost gate");
        RETIRING_SESSIONS.clear(); destroyedSessionsRetiring=1;
        for(int i=0;i<4;i++){dispatchQtTerminalShutdownIfReady();Handler.drain();}
        check(callbacks==0,"failed/pending destroyed release lost gate");
        check(isQtTerminalShutdownPending(),"failed release reopened new work");
    }
    static void underOuterLock(){
        synchronized(InWindowGameHost.class){
            requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal);
            check(callbacks==0,"terminal ran inside request lock");
        }
        Handler.drain(); check(callbacks==1,"posted terminal missing");
    }
    static void reentrant(){
        requestQtTerminalShutdown(MAIN,()->{
            terminal(); requestQtTerminalShutdown(MAIN,()->secondCallbacks++);
            dispatchQtTerminalShutdownIfReady();
        });
        Handler.drain(); check(callbacks==1 && secondCallbacks==0,"reentrant terminal duplicated");
    }
    static void importBlocked(){
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal);
        check(!tryBeginImportFrontendRestart(),"import entered while terminal callback queued");
        check(!importFrontendRestartPending,"rejected import modified reservation");
        Handler.drain();
        check(!tryBeginImportFrontendRestart(),"import entered after terminal dispatch");
    }
    static void missingCallback(){
        boolean rejected=false;
        try{requestQtTerminalShutdown(MAIN,null);}catch(IllegalArgumentException expected){rejected=true;}
        check(rejected && !isQtTerminalShutdownPending(),"invalid callback poisoned process gate");
        check(Handler.posts==0,"invalid callback posted");
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal); Handler.drain();
        check(callbacks==1,"valid callback rejected after invalid request");
    }
    static void throwingCallback(){
        requestQtTerminalShutdown(MAIN,()->{terminal();throw new IllegalStateException("terminal failure");});
        boolean thrown=false;
        try{Handler.drain();}catch(IllegalStateException expected){thrown=true;}
        check(thrown && callbacks==1,"fake terminal exception missing");
        requestQtTerminalShutdown(MAIN,()->secondCallbacks++);
        dispatchQtTerminalShutdownIfReady(); Handler.drain();
        check(callbacks==1 && secondCallbacks==0,"throwing terminal was retried");
        check(isQtTerminalShutdownPending(),"throwing terminal reopened work");
    }
    static void destroyOwner(boolean nativeSession){
        Activity owner=new org.pegasus_frontend.android.MainActivity();
        InWindowGameHost host=new InWindowGameHost();
        host.activity=owner; if(nativeSession)host.session=new Object();
        active=host; RECREATIONS.put(owner,new Object());
        requestQtTerminalShutdown(owner,InWindowGameHost::terminal);
        onDestroy(new Activity()); check(active==host,"unrelated Activity destroyed owner");
        onDestroy(owner);
        check(active==null && host.destroyCalls==1 && !RECREATIONS.containsKey(owner),
              "actual Activity destruction did not retire owner");
        check(callbacks==0,"onDestroy ran terminal inline"); Handler.drain();
        if(nativeSession){
            check(callbacks==0 && destroyedSessionsRetiring==1,"native retirement not counted");
            destroyedSessionsRetiring--; dispatchQtTerminalShutdownIfReady(); Handler.drain();
        }
        check(callbacks==1,"destroyed final owner failed to dispatch terminal");
        onDestroy(owner); Handler.drain(); check(host.destroyCalls==1 && callbacks==1,"duplicate destroy");
    }
    static void ownerIdentity(){
        Activity replacement=new org.pegasus_frontend.android.MainActivity();
        Activity unrelated=new Activity();
        Activity subclass=new org.pegasus_frontend.android.MainActivity(){};
        check(!requestQtTerminalShutdown(null,null),"null owner accepted");
        check(!requestQtTerminalShutdown(unrelated,()->secondCallbacks++),"non-Main accepted");
        check(!requestQtTerminalShutdown(subclass,()->secondCallbacks++),"subclass accepted by exact-name gate");
        check(!isQtTerminalShutdownPending() && Handler.posts==0,"rejected owner reserved shutdown");
        check(!shouldSkipQtDelegate(MAIN) && !shouldSkipQtDelegate(replacement),"premature bootstrap gate");
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal);
        check(!shouldSkipQtDelegate(MAIN),"original owner delegate blocked");
        check(shouldSkipQtDelegate(replacement),"replacement delegate not blocked");
        check(!shouldSkipQtDelegate(null) && !shouldSkipQtDelegate(unrelated) &&
              !shouldSkipQtDelegate(subclass),"non-Main delegate blocked");
        check(requestQtTerminalShutdown(replacement,()->secondCallbacks++),"replacement request not consumed");
        check(qtTerminalShutdownOwner==MAIN,"duplicate replaced original owner");
        Handler.drain();
        check(callbacks==1 && secondCallbacks==0,"duplicate replaced original terminal");
        check(shouldSkipQtDelegate(replacement) && !shouldSkipQtDelegate(MAIN),"owner gate changed after dispatch");
    }
    static void processExitOnlyAfterPostedTerminal(){
        check(!finishQtTerminalProcess(MAIN),"unmanaged Main consumed legacy endpoint");
        requestQtTerminalShutdown(MAIN,()->{
            terminal();
            check(android.os.Process.kills==0,"process killed before original Qt cleanup returned");
            // The generated delegate invokes this endpoint after its Qt cleanup/join.
            check(finishQtTerminalProcess(MAIN),"managed endpoint did not consume legacy exit");
        });
        check(finishQtTerminalProcess(MAIN),"early managed endpoint fell through to System.exit");
        check(android.os.Process.kills==0 && android.system.Os.calls==0,
              "process termination or environment mutation preceded posted terminal");
        check(!finishQtTerminalProcess(new Activity()),"non-Main legacy exit intercepted");
        check(!finishQtTerminalProcess(new org.pegasus_frontend.android.MainActivity()),
              "wrong Main owner authorized process termination");
        Handler.drain();
        check(callbacks==1 && android.os.Process.kills==1 &&
              android.os.Process.lastPid==android.os.Process.myPid(),"late endpoint did not kill own process");
        check(finishQtTerminalProcess(MAIN) && android.os.Process.kills==1,
              "terminal endpoint issued duplicate process termination");
        check(isQtTerminalShutdownPending(),"process endpoint reopened lifecycle");
    }
    static void failedEnvironmentCannotEnterQtOrKill(){
        android.system.Os.fail=true;
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal);
        Handler.drain();
        check(android.system.Os.calls==1 && callbacks==0 && android.os.Process.kills==0,
              "failed environment setting entered unsafe Qt exit");
        check(finishQtTerminalProcess(MAIN) && android.os.Process.kills==0,
              "failed environment setting allowed legacy exit or process kill");
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal);
        dispatchQtTerminalShutdownIfReady(); Handler.drain();
        check(android.system.Os.calls==1 && callbacks==0 && isQtTerminalShutdownPending(),
              "failed environment callback retried or reopened work");
    }
    static void newWorkBetweenPostAndExecutionStaysFailClosed(){
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal);
        RETIRING_SESSIONS.add(new Object());
        Handler.drain();
        check(callbacks==0 && android.system.Os.calls==0 && android.os.Process.kills==0,
              "queued terminal ignored newly pending retirement");
        check(finishQtTerminalProcess(MAIN) && android.os.Process.kills==0,
              "pending work fell through to unsafe legacy exit");
    }
    static void finalEndpointRechecksAllGates(){
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal); Handler.drain();
        active=new InWindowGameHost();
        check(finishQtTerminalProcess(MAIN) && android.os.Process.kills==0,"active owner ignored");
        active=null; destroyedSessionsRetiring=1;
        check(finishQtTerminalProcess(MAIN) && android.os.Process.kills==0,"destroyed owner ignored");
        destroyedSessionsRetiring=0; RETIRING_SESSIONS.add(new Object());
        check(finishQtTerminalProcess(MAIN) && android.os.Process.kills==0,"normal retirement ignored");
        RETIRING_SESSIONS.clear();
        check(finishQtTerminalProcess(MAIN) && android.os.Process.kills==1,"drained final endpoint rejected");
    }
    static void missingOrLiveQtThreadCannotKill() throws Exception {
        requestQtTerminalShutdown(MAIN,InWindowGameHost::terminal); Handler.drain();
        check(finishQtTerminalProcess(MAIN,null) && android.os.Process.kills==0,
              "missing Qt thread allowed process kill or unsafe legacy exit");
        java.util.concurrent.CountDownLatch release=new java.util.concurrent.CountDownLatch(1);
        Thread running=new Thread(()->{
            try { release.await(); } catch(InterruptedException failure) { throw new AssertionError(failure); }
        });
        running.start();
        try {
            check(running.isAlive(),"test Qt thread was not alive");
            check(finishQtTerminalProcess(MAIN,running) && android.os.Process.kills==0,
                  "interrupted Qt join allowed process kill or unsafe legacy exit");
            check(isQtTerminalShutdownPending(),"incomplete Qt thread reopened lifecycle");
        } finally {
            release.countDown(); running.join();
        }
        check(finishQtTerminalProcess(MAIN,running) && android.os.Process.kills==1,
              "completed Qt thread could not reach acknowledged endpoint");
    }
    public static void main(String[] args) throws Exception {
        QT_THREAD=completedThread();
        switch(args[0]){
        case "idle":idleOnce();break;
        case "owners":allOwners();break;
        case "failed":failedRelease();break;
        case "lock":underOuterLock();break;
        case "reentrant":reentrant();break;
        case "import":importBlocked();break;
        case "null":missingCallback();break;
        case "throwing":throwingCallback();break;
        case "empty-owner":destroyOwner(false);break;
        case "native-owner":destroyOwner(true);break;
        case "identity":ownerIdentity();break;
        case "late-kill":processExitOnlyAfterPostedTerminal();break;
        case "env-failure":failedEnvironmentCannotEnterQtOrKill();break;
        case "late-work":newWorkBetweenPostAndExecutionStaysFailClosed();break;
        case "final-gates":finalEndpointRechecksAllGates();break;
        case "qt-thread":missingOrLiveQtThreadCannotKill();break;
        default:throw new AssertionError(args[0]);
        }
    }
}
'''


class QtTerminalExecutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = HOST.read_text(encoding="utf-8")
        declarations = []
        for name in ("pendingQtTerminalShutdown", "qtTerminalShutdownRequested", "qtTerminalShutdownOwner",
                     "qtTerminalExecutionStarted", "qtTerminalProcessExitStarted"):
            match = re.search(r"private static\s+(?:final\s+)?(?:Runnable|boolean|Activity)\s+" +
                              name + r"\s*(?:=[^;]*)?;", source)
            if match is None:
                raise AssertionError("Missing coordinator field " + name)
            declarations.append(match.group())
        for name in ("requestQtTerminalShutdown", "isQtTerminalShutdownPending",
                     "dispatchQtTerminalShutdownIfReady", "tryBeginImportFrontendRestart",
                     "onDestroy", "shouldSkipQtDelegate", "isMainQtActivity",
                     "finishQtTerminalProcess"):
            declarations.append(method(source, name))
        cls.temp = tempfile.TemporaryDirectory(prefix="lucent-qt-terminal-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        target = cls.directory / "InWindowGameHost.java"
        target.write_text(SHELL.replace("// ACTUAL_COORDINATOR", "\n".join(declarations)),
                          encoding="utf-8")
        activity = cls.directory / "android/app/Activity.java"
        activity.parent.mkdir(parents=True)
        activity.write_text("package android.app; public class Activity {}", encoding="utf-8")
        main = cls.directory / "org/pegasus_frontend/android/MainActivity.java"
        main.parent.mkdir(parents=True)
        main.write_text("package org.pegasus_frontend.android; "
                        "public class MainActivity extends android.app.Activity {}", encoding="utf-8")
        os_stub = cls.directory / "android/system/Os.java"
        os_stub.parent.mkdir(parents=True)
        os_stub.write_text('''package android.system;
public class Os {
    public static boolean fail;
    public static int calls;
    public static String value;
    public static void setenv(String key, String next, boolean overwrite) throws Exception {
        calls++;
        if (!"QT_ANDROID_NO_EXIT_CALL".equals(key) || !"1".equals(next) || !overwrite)
            throw new AssertionError("unexpected environment mutation");
        if (fail) throw new Exception("setenv rejected");
        value=next;
    }
}''', encoding="utf-8")
        process = cls.directory / "android/os/Process.java"
        process.parent.mkdir(parents=True)
        process.write_text('''package android.os;
public class Process {
    public static int kills, lastPid;
    public static int myPid(){return 4242;}
    public static void killProcess(int pid){kills++;lastPid=pid;}
}''', encoding="utf-8")
        result = subprocess.run([str(JAVA / "javac"), "-d", str(cls.directory),
                                 str(activity), str(main), str(os_stub), str(process), str(target)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError("Actual coordinator compile failed:\n" + result.stderr)

    def scenario(self, name):
        result = subprocess.run([str(JAVA / "java"), "-cp", str(self.directory),
                                 "InWindowGameHost", name], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_idle_shutdown_is_posted_once_and_first_callback_wins(self):
        self.scenario("idle")

    def test_all_active_normal_and_destroyed_owners_must_retire(self):
        self.scenario("owners")

    def test_failed_or_pending_releases_keep_terminal_deferred(self):
        self.scenario("failed")

    def test_terminal_never_runs_inline_or_under_host_monitor(self):
        self.scenario("lock")

    def test_terminal_callback_cannot_reenter_a_second_shutdown(self):
        self.scenario("reentrant")

    def test_import_restart_is_blocked_before_and_after_posted_callback(self):
        self.scenario("import")

    def test_null_callback_is_rejected_without_reserving_shutdown(self):
        self.scenario("null")

    def test_terminal_failure_does_not_reopen_or_repeat_shutdown(self):
        self.scenario("throwing")

    def test_destroying_host_without_native_session_drains_terminal(self):
        self.scenario("empty-owner")

    def test_destroying_host_with_native_session_waits_for_release(self):
        self.scenario("native-owner")

    def test_exact_main_identity_original_owner_and_replacement_bootstrap_gate(self):
        self.scenario("identity")

    def test_process_exit_is_owned_posted_and_only_after_terminal_callback(self):
        self.scenario("late-kill")

    def test_failed_setenv_neither_enters_qt_nor_allows_legacy_exit(self):
        self.scenario("env-failure")

    def test_new_retirement_after_posting_prevents_qt_and_process_exit(self):
        self.scenario("late-work")

    def test_final_process_endpoint_rechecks_every_native_owner_gate(self):
        self.scenario("final-gates")

    def test_missing_or_live_qt_backing_thread_retains_process_without_legacy_exit(self):
        self.scenario("qt-thread")


class QtTerminalWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HOST.read_text(encoding="utf-8")

    def test_new_launch_recovery_and_switch_are_blocked_before_attachment(self):
        launch = method(self.source, "handleIntent")
        self.assertLess(launch.index("if (qtTerminalShutdownRequested)"),
                        launch.index("requestFrom(activity, source)"))
        recovery = method(self.source, "restorePendingRecreation")
        gate = recovery.split("try {", 1)[0]
        self.assertIn("qtTerminalShutdownRequested", gate)
        self.assertIn("return;", gate)
        switch = method(self.source, "replaceWith")
        self.assertLess(switch.index("if (qtTerminalShutdownRequested"),
                        switch.index("handleIntent(activity, launch);"))

    def test_each_release_path_dispatches_only_after_successful_owner_removal(self):
        for name, removal in (("finishRetiringSession", "RETIRING_SESSIONS.remove(ending);"),
                              ("releaseDestroyedSession", "destroyedSessionsRetiring--;"),
                              ("replaceWith", "RETIRING_SESSIONS.remove(ending);")):
            body = method(self.source, name)
            self.assertIn("releaseSessionWhenComplete(ending,", body, name)
            callback = "Runnable released = () ->" if name == "replaceWith" else "releaseSessionWhenComplete(ending, () ->"
            self.assertLess(body.index(callback), body.index(removal), name)
            self.assertLess(body.index(removal),
                            body.index("dispatchQtTerminalShutdownIfReady();"), name)
        helper = method(self.source, "releaseSessionWhenComplete")
        self.assertIn("catch (RuntimeException", helper)
        self.assertIn("releaseWhenComplete(once)", helper)
        self.assertIn("acknowledged.compareAndSet(false, true)", helper)

    def test_bootstrap_pending_flag_is_process_lifetime_sticky(self):
        query = method(self.source, "isQtTerminalShutdownPending")
        self.assertIn("synchronized boolean isQtTerminalShutdownPending", query)
        self.assertIn("return qtTerminalShutdownRequested;", query)
        # New Qt bootstrap must continue to see the gate after its callback was
        # posted or returned; native termination is not a reusable lifecycle.
        self.assertNotIn("qtTerminalShutdownRequested = false", self.source)


if __name__ == "__main__":
    unittest.main()
