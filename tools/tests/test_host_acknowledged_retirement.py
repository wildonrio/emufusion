"""Execute the host's release acknowledgement boundary with fake native owners."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
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
    raise AssertionError("Unclosed member: " + signature)


def method(source, name):
    match = re.search(r"(?:public|private)\s+(?:static\s+)?(?:synchronized\s+)?"
                      r"(?:void|boolean)\s+" + re.escape(name) + r"\(", source)
    if match is None:
        raise AssertionError("Missing actual host method " + name)
    return member(source, match.group())


SHELL = r'''
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import android.app.Activity;
public class InWindowGameHost {
    static final String TAG="test";
    static InWindowGameHost active;
    static final Set<EngineSession> RETIRING_SESSIONS=new HashSet<>();
    static int destroyedSessionsRetiring;
    static boolean cleanFrontendRestartPending,importFrontendRestartPending;
    static boolean qtTerminalShutdownRequested;
    static boolean qtTerminalExecutionStarted;
    static Runnable pendingQtTerminalShutdown;
    static Activity qtTerminalShutdownOwner;
    static int completions,terminals,restores;
    Activity activity=new org.pegasus_frontend.android.MainActivity();
    EngineSession session,switchingSession;
    EngineSession.Completion switchingCompletion;
    AtomicBoolean switchingStopCompleted;
    static class Queue {
        final ArrayDeque<Runnable> work=new ArrayDeque<>();
        void execute(Runnable task){work.add(task);}
        void drain(){while(!work.isEmpty())work.remove().run();}
    }
    static final Queue RETIREMENT_RELEASES=new Queue();
    static class Looper {static Looper getMainLooper(){return new Looper();}}
    static class Handler {
        static final Queue MAIN=new Queue();
        Handler(Looper looper){}
        boolean post(Runnable task){MAIN.execute(task);return true;}
    }
    final Handler mainHandler=new Handler(Looper.getMainLooper());
    static void restorePendingRecreations(){restores++;}
    static class Log {
        static void i(String tag,String message){}
        static void w(String tag,String message,Throwable failure){}
        static void e(String tag,String message,Throwable failure){}
    }
    interface EngineSession {
        interface Completion {void complete();}
        void release();
    }
    static class Generic implements EngineSession {
        int releases;
        boolean fail;
        public void release(){releases++;if(fail)throw new IllegalStateException("release failed");}
    }
    static class NetplayGeneric extends Generic
            implements com.thorium.lucent.netplay.NetplayCapableSession {}
    static class NativeAdapterGeneric extends Generic
            implements com.thorium.lucent.netplay.NativeAdapterCapableSession {}
    static class AsyncOwner implements EngineSession {
        int releases,requests;
        boolean fail,immediate;
        Completion acknowledgement;
        public void release(){releases++;throw new AssertionError("async owner used fire-and-forget release");}
        void releaseWhenComplete(Completion completion){
            requests++;acknowledgement=completion;
            if(fail)throw new IllegalStateException("native close failed");
            if(immediate)completion.complete();
        }
        void acknowledge(){check(acknowledgement!=null,"release not submitted");acknowledgement.complete();}
    }
    // Distinct sibling types ensure each actual instanceof dispatch branch is
    // exercised; inheriting the GLES fake would hide missing software/native cases.
    static class PpssppGlesEngineSession extends AsyncOwner {}
    static class LibretroEngineSession extends AsyncOwner {}
    static class NativeAdapterEngineSession extends AsyncOwner {}
    static AsyncOwner asyncOwner(String kind){
        if(kind.equals("software"))return new LibretroEngineSession();
        if(kind.equals("native"))return new NativeAdapterEngineSession();
        return new PpssppGlesEngineSession();
    }
    // ACTUAL_METHODS
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void normalOwner(InWindowGameHost host,EngineSession engine){
        RETIRING_SESSIONS.add(engine);
        host.releaseSessionWhenComplete(engine,()->{
            completions++; RETIRING_SESSIONS.remove(engine);
            dispatchQtTerminalShutdownIfReady();
        });
    }
    static void requestTerminal(){
        check(requestQtTerminalShutdown(new org.pegasus_frontend.android.MainActivity(),()->terminals++),
              "Main terminal request rejected");
    }
    static void generic(){
        Generic engine=new Generic();
        normalOwner(new InWindowGameHost(),engine);
        check(engine.releases==0 && completions==0,"release ran on caller");
        check(!tryBeginImportFrontendRestart(),"import bypassed pending release");
        RETIREMENT_RELEASES.drain();
        check(engine.releases==1 && completions==1 && RETIRING_SESSIONS.isEmpty(),
              "generic return did not acknowledge release");
        check(tryBeginImportFrontendRestart(),"successful generic release retained gate");
    }
    static void delayed(String kind){
        AsyncOwner engine=asyncOwner(kind);
        normalOwner(new InWindowGameHost(),engine);
        check(engine.requests==0,"GLES release ran on caller");
        RETIREMENT_RELEASES.drain();
        check(engine.requests==1 && engine.releases==0 && completions==0,
              "GLES method return mistaken for completion");
        check(!tryBeginImportFrontendRestart(),"import bypassed unacknowledged native teardown");
        requestTerminal(); Handler.MAIN.drain();
        check(terminals==0,"Qt shutdown bypassed unacknowledged native teardown");
        engine.acknowledge();
        check(completions==1 && terminals==0,"acknowledgement not one-shot/asynchronously dispatched");
        Handler.MAIN.drain();check(terminals==1,"Qt did not drain after acknowledgement");
        engine.acknowledge();Handler.MAIN.drain();
        check(completions==1 && terminals==1,"duplicate acknowledgement repeated retirement");
    }
    static void failed(String kind){
        EngineSession engine;
        if(!kind.equals("generic")){AsyncOwner value=asyncOwner(kind);value.fail=true;engine=value;}
        else {Generic value=new Generic();value.fail=true;engine=value;}
        normalOwner(new InWindowGameHost(),engine);
        RETIREMENT_RELEASES.drain();
        check(completions==0 && RETIRING_SESSIONS.contains(engine),"failed release opened gate");
        check(!tryBeginImportFrontendRestart(),"import bypassed failed release");
        requestTerminal();Handler.MAIN.drain();
        check(terminals==0,"Qt bypassed failed release");
    }
    static void immediateGles(){
        PpssppGlesEngineSession engine=new PpssppGlesEngineSession();engine.immediate=true;
        normalOwner(new InWindowGameHost(),engine);RETIREMENT_RELEASES.drain();
        check(completions==1 && engine.requests==1 && engine.releases==0,"inline native ack lost");
        engine.acknowledge();check(completions==1,"inline then duplicate ack repeated completion");
    }
    static void allOwners(){
        InWindowGameHost host=new InWindowGameHost();
        PpssppGlesEngineSession normal=new PpssppGlesEngineSession();
        PpssppGlesEngineSession destroyed=new PpssppGlesEngineSession();
        normalOwner(host,normal);
        destroyedSessionsRetiring=1;
        host.releaseDestroyedSession(destroyed);
        RETIREMENT_RELEASES.drain();
        check(destroyedSessionsRetiring==1,"actual destroyed path decremented before native ack");
        check(!tryBeginImportFrontendRestart(),"multiple-owner import gate lost");
        requestTerminal();normal.acknowledge();Handler.MAIN.drain();
        check(terminals==0 && destroyedSessionsRetiring==1,"one owner released all gates");
        destroyed.acknowledge();
        check(destroyedSessionsRetiring==0 && terminals==0,"actual destroyed ack not deferred to main");
        Handler.MAIN.drain();check(terminals==1 && restores==1,"last owner did not drain recovery/Qt");
        destroyed.acknowledge();Handler.MAIN.drain();
        check(destroyedSessionsRetiring==0 && restores==1 && terminals==1,"destroy counter decremented twice");
    }
    static void rejectedSwitch(String reason){
        InWindowGameHost host=new InWindowGameHost();active=host;
        Generic engine=reason.equals("netplay") ? new NetplayGeneric()
                : reason.equals("native_adapter") ? new NativeAdapterGeneric() : new Generic();
        host.switchingSession=engine;
        host.switchingStopCompleted=new AtomicBoolean(false);
        EngineSession.Completion original=()->completions++;
        host.switchingCompletion=original;
        RETIRING_SESSIONS.add(engine);
        boolean allowed=reason.equals("live") || reason.equals("netplay") || reason.equals("native_adapter");
        switch(reason){
            case "different_owner":active=new InWindowGameHost();break;
            case "destroyed":host.activity.destroyed=true;break;
            case "finishing":host.activity.finishing=true;break;
            case "terminal":requestTerminal();break;
            case "completed":host.switchingStopCompleted.set(true);break;
            case "missing_claim":host.switchingStopCompleted=null;break;
        }
        check(host.restoreRejectedSwitchSession()==allowed,"incorrect rejected-switch restoration: "+reason);
        if(allowed){
            check(host.session==engine && host.switchingSession==null && host.switchingCompletion==null,
                  "live switch rejection did not restore original session ownership");
            check(host.switchingStopCompleted.get() && !RETIRING_SESSIONS.contains(engine),
                  "switch rejection did not claim completion/remove only retirement ownership");
            check(!host.restoreRejectedSwitchSession(),"rejected switch restored twice");
            Object published=com.thorium.lucent.netplay.ActiveEngineSessionRegistry.active;
            check(published==(reason.equals("live") ? null : engine),"netplay registry publication changed");
            requestTerminal();Handler.MAIN.drain();
            check(terminals==0 && active==host,"restored active owner no longer gates Qt shutdown");
        }else{
            check(host.session==null && host.switchingSession==engine && host.switchingCompletion==original,
                  "unavailable owner was resurrected or its retirement callback discarded");
            check(RETIRING_SESSIONS.contains(engine),"rejected restoration dropped retirement gate");
            check(com.thorium.lucent.netplay.ActiveEngineSessionRegistry.active==null,
                  "unavailable owner published a netplay session");
        }
        check(!tryBeginImportFrontendRestart(),"switch rejection incorrectly opened import gate");
        check(engine.releases==0 && completions==0 && RETIREMENT_RELEASES.work.isEmpty(),
              "restoration was mistaken for native release acknowledgement");
    }
    public static void main(String[] args){
        if(args[0].startsWith("reject_")){rejectedSwitch(args[0].substring(7));return;}
        switch(args[0]){
            case "generic":generic();break;
            case "delayed":delayed("gles");break;
            case "delayed_software":delayed("software");break;
            case "delayed_native":delayed("native");break;
            case "failed_generic":failed("generic");break;
            case "failed_gles":failed("gles");break;
            case "failed_software":failed("software");break;
            case "failed_native":failed("native");break;
            case "immediate_gles":immediateGles();break;
            case "all_owners":allOwners();break;
            default:throw new AssertionError(args[0]);
        }
    }
}
'''


class AcknowledgedRetirementJvmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (JAVA / "javac").exists():
            raise unittest.SkipTest("Local JDK 17 unavailable")
        source = HOST.read_text()
        names = ("releaseSessionWhenComplete", "releaseDestroyedSession", "restoreRejectedSwitchSession",
                 "requestQtTerminalShutdown", "isMainQtActivity",
                 "dispatchQtTerminalShutdownIfReady", "tryBeginImportFrontendRestart")
        actual = "\n".join(method(source, name) for name in names)
        cls.temp = tempfile.TemporaryDirectory(prefix="host-acknowledged-retirement-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        (directory / "InWindowGameHost.java").write_text(SHELL.replace("// ACTUAL_METHODS", actual))
        activity = directory / "android/app/Activity.java"
        activity.parent.mkdir(parents=True)
        activity.write_text("package android.app; public class Activity {"
                            "public boolean finishing,destroyed;"
                            "public boolean isFinishing(){return finishing;}"
                            "public boolean isDestroyed(){return destroyed;}}")
        main = directory / "org/pegasus_frontend/android/MainActivity.java"
        main.parent.mkdir(parents=True)
        main.write_text("package org.pegasus_frontend.android; "
                        "public class MainActivity extends android.app.Activity {}")
        os_stub = directory / "android/system/Os.java"
        os_stub.parent.mkdir(parents=True)
        os_stub.write_text('''package android.system;
public class Os {
    public static void setenv(String key, String value, boolean overwrite) {
        if (!"QT_ANDROID_NO_EXIT_CALL".equals(key) || !"1".equals(value) || !overwrite)
            throw new AssertionError("unexpected environment mutation");
    }
}''')
        netplay = directory / "com/thorium/lucent/netplay"
        netplay.mkdir(parents=True)
        for name in ("NetplayCapableSession", "NativeAdapterCapableSession"):
            (netplay / (name + ".java")).write_text(
                "package com.thorium.lucent.netplay; public interface " + name + " {}")
        (netplay / "ActiveEngineSessionRegistry.java").write_text(
            "package com.thorium.lucent.netplay; public class ActiveEngineSessionRegistry {"
            "public static Object active; public static void set(Object session){active=session;}}")
        compile_result = subprocess.run(
            [str(JAVA / "javac"), "-d", str(directory),
             *map(str, directory.rglob("*.java"))], text=True, capture_output=True, timeout=30)
        if compile_result.returncode:
            raise AssertionError(compile_result.stdout + compile_result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(JAVA / "java"), "-cp", self.temp.name,
                                 "InWindowGameHost", name],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generic_release_is_queued_and_return_acknowledges(self):
        self.run_case("generic")

    def test_delayed_gles_ack_blocks_import_and_qt_then_completes_once(self):
        self.run_case("delayed")

    def test_delayed_software_ack_blocks_import_and_qt_then_completes_once(self):
        self.run_case("delayed_software")

    def test_delayed_native_adapter_ack_blocks_import_and_qt_then_completes_once(self):
        self.run_case("delayed_native")

    def test_generic_failure_keeps_owner_gate(self):
        self.run_case("failed_generic")

    def test_gles_failure_without_ack_keeps_owner_gate(self):
        self.run_case("failed_gles")

    def test_software_failure_without_ack_keeps_owner_gate(self):
        self.run_case("failed_software")

    def test_native_adapter_failure_without_ack_keeps_owner_gate(self):
        self.run_case("failed_native")

    def test_immediate_gles_ack_and_duplicate_are_safe(self):
        self.run_case("immediate_gles")

    def test_actual_destroyed_path_waits_for_ack_and_all_owners(self):
        self.run_case("all_owners")

    def test_rejected_switch_restores_live_owner_but_keeps_active_gate(self):
        self.run_case("reject_live")

    def test_rejected_switch_restores_capable_registry_only_for_live_owner(self):
        for kind in ("netplay", "native_adapter"):
            with self.subTest(kind=kind):
                self.run_case("reject_" + kind)

    def test_rejected_switch_never_resurrects_unavailable_owner(self):
        for reason in ("different_owner", "destroyed", "finishing", "terminal", "completed", "missing_claim"):
            with self.subTest(reason=reason):
                self.run_case("reject_" + reason)


class AcknowledgedRetirementWiringTests(unittest.TestCase):
    def test_all_host_retirement_paths_use_acknowledged_release(self):
        source = HOST.read_text()
        for name in ("replaceWith", "finishRetiringSession", "releaseDestroyedSession"):
            with self.subTest(path=name):
                body = method(source, name)
                self.assertIn("releaseSessionWhenComplete(ending,", body)
                self.assertNotIn("ending.release();", body)
                self.assertNotIn("RETIREMENT_RELEASES.execute", body)

    def test_normal_and_destroyed_gate_changes_are_inside_completion(self):
        source = HOST.read_text()
        for name, transition in (("finishRetiringSession", "RETIRING_SESSIONS.remove(ending)"),
                                 ("releaseDestroyedSession", "destroyedSessionsRetiring--")):
            with self.subTest(path=name):
                body = method(source, name)
                callback = member(body, "releaseSessionWhenComplete(ending, () ->")
                self.assertIn(transition, callback)
                self.assertIn("dispatchQtTerminalShutdownIfReady()", callback)

    def test_launch_gate_does_not_require_active_owner_to_be_null(self):
        body = method(HOST.read_text(), "handleIntent")
        self.assertNotIn("previous == null && !RETIRING_SESSIONS.isEmpty()", body)
        self.assertLess(body.index("!RETIRING_SESSIONS.isEmpty()"),
                        body.index("previous.replaceWith(request)"))

    def test_switch_gate_and_successor_are_in_acknowledged_callback(self):
        body = method(HOST.read_text(), "replaceWith")
        released = member(body, "Runnable released = () ->")
        self.assertIn("RETIRING_SESSIONS.remove(ending)", released)
        self.assertIn("activity.runOnUiThread", released)
        self.assertIn("handleIntent(activity, launch)", released)
        self.assertIn("dispatchQtTerminalShutdownIfReady()", released)
        self.assertIn("releaseSessionWhenComplete(ending, released)", body)
        self.assertEqual(body.count("handleIntent(activity, launch)"), 1)
        self.assertLess(released.index("qtTerminalShutdownRequested"),
                        released.index("handleIntent(activity, launch)"))

    def test_destroyed_switch_and_rejected_stop_continue_retirement_not_resume(self):
        source = HOST.read_text()
        destroy = method(source, "destroyNow")
        self.assertIn("if (ending == null && switchingCompletion != null) switchingCompletion.complete();", destroy)
        rejection = member(source, "if (switchingSession != null && !restoreRejectedSwitchSession())")
        self.assertIn("switchingCompletion.complete();", rejection)
        self.assertRegex(rejection, r"switchingCompletion\.complete\(\);\s*return;")
        self.assertNotIn("session.resume()", rejection)


if __name__ == "__main__":
    unittest.main()
