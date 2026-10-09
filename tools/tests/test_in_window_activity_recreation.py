"""Focused activity-recreation contracts; no emulator or device is required."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
PATCHER = ROOT / "unified-android/tools/patch_main_activity_right_stick.py"


def java_block(source, signature):
    """Extract the actual declaration/body, preserving its source text."""
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                    lambda match: " " * len(match.group()), source,
                    flags=re.DOTALL)
    depth = 0
    for index in range(opening, len(source)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("Unclosed Java declaration: " + signature)


def smali_method(source, signature):
    return source.split(signature, 1)[1].split(".end method", 1)[0]


class ActivityRecreationWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = HOST.read_text(encoding="utf-8")
        fixture = """.class public Lorg/pegasus_frontend/android/MainActivity;
.super Lorg/qtproject/qt5/android/bindings/QtActivity;
.method protected onStart()V
    .locals 1
    invoke-super {p0}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onStart()V
    sput v0, Lorg/pegasus_frontend/android/MainActivity;->m_icon_density:I

    return-void
.end method
.method public static launchAmCommand([Ljava/lang/String;)Ljava/lang/String;
    .locals 2
    const/4 v0, 0x0
    return-object v0
.end method
"""
        with tempfile.TemporaryDirectory(prefix="lucent-recreation-smali-") as temp:
            target = Path(temp) / "MainActivity.smali"
            target.write_text(fixture, encoding="utf-8")
            subprocess.run([sys.executable, str(PATCHER), str(target)],
                           check=True, capture_output=True, text=True)
            cls.generated = target.read_text(encoding="utf-8")

    def test_create_hook_preserves_qt_and_original_bundle(self):
        create = smali_method(self.generated,
                              ".method protected onCreateHook(Landroid/os/Bundle;)V")
        qt = ("invoke-super {p0, p1}, Lorg/qtproject/qt5/android/bindings/"
              "QtActivity;->onCreateHook(Landroid/os/Bundle;)V")
        host = ("invoke-static {p0, p1}, Lcom/thorium/preview/game/"
                "InWindowGameHost;->onCreate(Landroid/app/Activity;Landroid/os/Bundle;)V")
        self.assertEqual(1, create.count(qt))
        self.assertEqual(1, create.count(host))
        # Stage metadata before Qt initialization; do not launch from this hook.
        self.assertLess(create.index(host), create.index(qt))
        self.assertNotRegex(create, r"(?:const|move|new-instance)[^\n]*\bp1\b")

    def test_save_hook_preserves_qt_and_same_bundle(self):
        save = smali_method(self.generated,
                            ".method protected onSaveInstanceState(Landroid/os/Bundle;)V")
        qt = ("invoke-super {p0, p1}, Lorg/qtproject/qt5/android/bindings/"
              "QtActivity;->onSaveInstanceState(Landroid/os/Bundle;)V")
        host = ("invoke-static {p0, p1}, Lcom/thorium/preview/game/"
                "InWindowGameHost;->onSaveInstanceState(Landroid/app/Activity;Landroid/os/Bundle;)V")
        self.assertEqual(1, save.count(qt))
        self.assertEqual(1, save.count(host))
        self.assertLess(save.index(qt), save.index(host))
        self.assertNotRegex(save, r"(?:const|move|new-instance)[^\n]*\bp1\b")

    def test_start_routes_through_recreation_gate_once(self):
        start = smali_method(self.generated, ".method protected onStart()V")
        gate = ("InWindowGameHost;->onStart(Landroid/app/Activity;)V")
        self.assertEqual(1, start.count(gate))
        self.assertLess(start.index("QtActivity;->onStart()V"), start.index(gate))
        self.assertNotIn("InWindowGameHost;->handleIntent", start)
        self.assertIn("InWindowGameHost;->onResume(Landroid/app/Activity;)V",
                      self.generated)

    def test_recreation_state_is_not_global_cold_boot_autolaunch(self):
        create = java_block(self.host, "public static synchronized void onCreate(")
        save = java_block(self.host, "public static synchronized void onSaveInstanceState(")
        self.assertIn("Bundle", create)
        self.assertIn("Bundle", save)
        self.assertNotIn("getSharedPreferences", create + save)
        self.assertNotIn("serialize(", save)
        self.assertNotIn("saveQuickResume(", save)
        self.assertNotIn('"Started"', create + save)
        self.assertNotIn('"FullScreen"', create + save)
        self.assertNotIn(".clear()", create + save)

    def test_consumption_pause_and_terminal_exit_are_wired(self):
        restore = java_block(self.host, "private static void restorePendingRecreation(")
        self.assertLess(restore.index("state.pending = null;"),
                        restore.index("handleIntent(activity, pending);"))
        handle = java_block(self.host, "public static synchronized boolean handleIntent(")
        self.assertLess(handle.index("clearPendingRecreation(activity);"),
                        handle.index("requestFrom(activity, source)"))
        pause = java_block(self.host, "public static synchronized void onPause(")
        self.assertLess(pause.index("state.resumed = false"),
                        pause.index("if (active == null"))
        for signature in ("private void returnToLibraryUi(",
                          "private void showFatalError(String message, boolean runtimeFailure)"):
            self.assertIn("clearPendingRecreation(activity);",
                          java_block(self.host, signature))

    def test_retirement_gate_opens_only_after_successful_off_ui_release(self):
        normal = java_block(self.host, "private synchronized void finishRetiringSession(")
        destroyed = java_block(self.host, "private void releaseDestroyedSession(")
        for method, opening, dispatch in (
                (normal, "RETIRING_SESSIONS.remove(ending);", "mainHandler.post(() -> {"),
                (destroyed, "destroyedSessionsRetiring--;",
                 "mainHandler.post(InWindowGameHost::restorePendingRecreations)")):
            self.assertLess(method.index("releaseSessionWhenComplete(ending, () ->"),
                            method.index(opening))
            self.assertLess(method.index(opening),
                            method.index(dispatch))
            self.assertNotIn("finally", method)
        # Native adapters already use a clean-process restart after acknowledged
        # release. Ordinary engines must still restore pending recreations in
        # the posted callback, not before the native retirement barrier.
        self.assertIn("if (requiresCleanFrontendRestart()) beginCleanFrontendRestart();", normal)
        self.assertIn("else restorePendingRecreations();", normal)
        self.assertLess(normal.index("mainHandler.post(() -> {"),
                        normal.index("else restorePendingRecreations();"))
        release = java_block(self.host, "private void releaseSessionWhenComplete(")
        self.assertIn("RETIREMENT_RELEASES.execute(() ->", release)
        self.assertIn("releaseWhenComplete(once)", release)
        self.assertIn("acknowledged.compareAndSet(false, true)", release)


JAVA_SHELL = r'''
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
public class InWindowGameHost {
    static final String ACTION_LAUNCH="com.thorium.preview.LAUNCH_INTERNAL_GAME", TAG="test";
    static InWindowGameHost active;
    static boolean cleanFrontendRestartPending, importFrontendRestartPending;
    static Intent pendingCleanFrontendLaunch;
    static final Set<Object> RETIRING_SESSIONS=new HashSet<>();
    Activity activity;
    GameLaunchRequest request;
    AtomicBoolean exitStarted=new AtomicBoolean();
    boolean libraryReturned, fatalErrorVisible, resumed, prepared, menuVisible, surfaceAvailable;
    View gameSurface;
    Session session;
    static int launches, validationAttempts;
    static String launched;
    InWindowGameHost(Activity a, GameLaunchRequest r, ViewGroup ignored) { activity=a; request=r; }
    void attach() { launches++; launched=request.gameId; }
    boolean sameRequest(GameLaunchRequest r) { return request.gameId.equals(r.gameId); }
    void replaceWith(GameLaunchRequest r) { request=r; attach(); }
    void enterImmersiveMode() {}
    void attachSurfaceListener() {}
    // View-scoped idle policy has its own executed fixture; this suite tests recreation.
    void updateGameplayScreenOn() {}
    void destroyNow() {}
    static GameLaunchRequest requestFrom(Activity a, Intent i) {
        validationAttempts++;
        return i.getStringExtra("game_id")==null ? null : new GameLaunchRequest(i);
    }
    static class Session { void resume() {} }
    static class Context { static final String POWER_SERVICE="power"; }
    static class Looper { static Looper getMainLooper(){return new Looper();} }
    static class Handler {
        Handler(Looper ignored){}
        void post(Runnable task){throw new AssertionError("unexpected Qt terminal request");}
    }
    static class Activity extends Context {
        Intent intent; PowerManager power=new PowerManager();
        boolean finishing,destroyed,throwPower;
        Activity(Intent i) { intent=i; }
        Intent getIntent() { return intent; }
        boolean isFinishing() { return finishing; }
        boolean isDestroyed() { return destroyed; }
        Object getSystemService(String key) {
            if(throwPower) throw new IllegalStateException("power"); return power;
        }
        Window getWindow() { return new Window(); }
    }
    static class Window { View getDecorView() { return new ViewGroup(); } }
    static class View { static final int VISIBLE=0; void setVisibility(int ignored) {} }
    static class ViewGroup extends View {}
    static class PowerManager { boolean interactive=true; boolean isInteractive(){return interactive;} }
    static class Bundle {
        Map<String,Object> data=new HashMap<>();
        boolean containsKey(String k){return data.containsKey(k);}
        Bundle getBundle(String k){return (Bundle)data.get(k);}
        void putBundle(String k,Bundle v){data.put(k,v);}
        String getString(String k,String d){return (String)data.getOrDefault(k,d);}
        void putString(String k,String v){data.put(k,v);}
        @SuppressWarnings("unchecked") <T>T getParcelable(String k){return (T)data.get(k);}
        void putParcelable(String k,Object v){data.put(k,v);}
    }
    static class Intent {
        String action; Map<String,Object> extras=new TreeMap<>();
        Intent(String a){action=a;} Intent(Intent i){action=i.action;extras.putAll(i.extras);}
        String getAction(){return action;}
        Intent putExtra(String k,String v){extras.put(k,v);return this;}
        Intent putExtra(String k,boolean v){extras.put(k,v);return this;}
        Intent putExtra(String k,int v){extras.put(k,v);return this;}
        String getStringExtra(String k){return (String)extras.get(k);}
        boolean getBooleanExtra(String k,boolean d){return (Boolean)extras.getOrDefault(k,d);}
        int getIntExtra(String k,int d){return (Integer)extras.getOrDefault(k,d);}
        String toUri(int ignored){return action+extras.toString();}
    }
    static class Uri { String path; Uri(String p){path=p;} String getQueryParameter(String k){return path;} }
    static class GameLaunchRequest {
        String engineId,systemId,gameId,gameTitle,qualificationSession="";
        Uri contentUri; SessionReturnState returnState;
        GameLaunchRequest(Intent i) {
            gameId=i.getStringExtra("game_id"); engineId=i.getStringExtra("engine_id");
            systemId=i.getStringExtra("system_id"); gameTitle=i.getStringExtra("title");
            contentUri=new Uri(i.getStringExtra("path"));
            returnState=SessionReturnState.from(i);
            if(i.getStringExtra("qualification_session")!=null)
                qualificationSession=i.getStringExtra("qualification_session");
        }
    }
    static class Log {
        static void i(String a,String b){} static void e(String a,String b){}
        static void e(String a,String b,Throwable t){}
        static void w(String a,String b){} static void w(String a,String b,Throwable t){}
    }
    // ACTUAL_MEMBERS
    static Intent game(String id) {
        return new Intent(ACTION_LAUNCH).putExtra("game_id",id).putExtra("engine_id","dolphin")
            .putExtra("system_id","gamecube").putExtra("title",id).putExtra("path","/games/"+id);
    }
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static Bundle savedGame(String id) {
        Activity a=new Activity(new Intent("MAIN")); onCreate(a,null); handleIntent(a,game(id));
        Bundle out=new Bundle(); out.putString("Started","qt-started");
        out.putString("FullScreen","qt-fullscreen"); onSaveInstanceState(a,out);
        check(out.getString("Started","").equals("qt-started"),"Qt Started clobbered");
        check(out.getString("FullScreen","").equals("qt-fullscreen"),"Qt FullScreen clobbered");
        active=null; RECREATIONS.clear(); launches=0; validationAttempts=0; launched=null; return out;
    }
    static Activity recreated(Bundle saved) {
        Activity a=new Activity(new Intent("MAIN")); onCreate(a,saved); return a;
    }
    static void deferredResave() {
        Activity a=recreated(savedGame("A")); a.power.interactive=false;
        onStart(a); onResume(a); check(launches==0,"screen-off recreation launched");
        onPause(a); Bundle again=new Bundle(); onSaveInstanceState(a,again);
        check(again.getBundle(RECREATION_STATE).getParcelable("request")!=null,"pending lost on resave");
        onDestroy(a); Activity b=recreated(again); onStart(b);
        restorePendingRecreations(); check(launches==0,"not-resumed recreation launched");
        onResume(b); onResume(b); onStart(b);
        check(launches==1 && "A".equals(launched),"restore was missing/duplicated/wrong game");
        check(RECREATIONS.get(b).pending==null,"request not consumed");
    }
    static void explicitWins() {
        Bundle old=savedGame("A"); Activity a=new Activity(game("B")); onCreate(a,old);
        onStart(a); check(launches==0,"recreated launch was not deferred"); onResume(a);
        check("B".equals(launched),"new initial intent lost");
        active=null; launches=0; Activity b=recreated(old); handleIntent(b,game("C")); onResume(b);
        check(launches==1 && "C".equals(launched),"pending game overrode fresh intent");
    }
    static void inactiveAndExit() {
        Activity a=new Activity(game("A")); onCreate(a,null); onStart(a);
        active.exitStarted.set(true); Bundle out=new Bundle(); onSaveInstanceState(a,out);
        check(out.getBundle(RECREATION_STATE).getParcelable("request")==null,"exiting game saved");
        active=null; launches=0; Activity b=new Activity(game("A").putExtra("android-task-change",true));
        onCreate(b,out); onStart(b); onResume(b);
        check(launches==0,"inactive record replayed original task intent");
        Activity c=recreated(savedGame("A")); clearPendingRecreation(c);
        Bundle closed=new Bundle(); onSaveInstanceState(c,closed); Activity d=recreated(closed); onResume(d);
        check(launches==0,"cleared Exit request restored");
        Activity e=new Activity(new Intent("MAIN")); onCreate(e,null); handleIntent(e,game("fatal"));
        active.fatalErrorVisible=true; Bundle fatal=new Bundle(); onSaveInstanceState(e,fatal);
        check(fatal.getBundle(RECREATION_STATE).getParcelable("request")==null,"fatal game saved");
    }
    static void badAndUnavailable() {
        Bundle malformed=new Bundle(); malformed.data.put(RECREATION_STATE,"not a bundle");
        Activity a=recreated(malformed); onStart(a); onResume(a); check(launches==0,"malformed state launched");
        Bundle saved=savedGame("A"); saved.getBundle(RECREATION_STATE).putParcelable("request",new Intent(ACTION_LAUNCH));
        Activity b=recreated(saved); onResume(b); onResume(b);
        check(launches==0 && validationAttempts==1 && RECREATIONS.get(b).pending==null,"invalid request retried");
        Activity c=recreated(savedGame("A")); c.throwPower=true; onResume(c);
        check(launches==0 && RECREATIONS.get(c).pending!=null,"power failure consumed request");
        c.throwPower=false; c.finishing=true; onResume(c); check(launches==0,"finishing activity launched");
        c.finishing=false; c.destroyed=true; onResume(c); check(launches==0,"destroyed activity launched");
    }
    static void oldOwnerAndRetirement() {
        Bundle saved=savedGame("A"); Activity old=new Activity(new Intent("MAIN"));
        onCreate(old,null); handleIntent(old,game("A")); active.session=new Session(); launches=0;
        Activity next=recreated(saved); onResume(next); check(launches==0,"overlapped old owner");
        handleIntent(next,game("B")); check(launches==0,"explicit launch overlapped old owner");
        onDestroy(old); onResume(next); check(launches==0,"overlapped retiring native session");
        destroyedSessionsRetiring=0; RETIRING_SESSIONS.add(new Object()); restorePendingRecreations();
        check(launches==0,"overlapped ordinary retiring session");
        RETIRING_SESSIONS.clear(); restorePendingRecreations();
        check(launches==1 && "B".equals(launched),"queued successor not restored");
    }
    static void roundTrip() {
        Activity a=new Activity(new Intent("MAIN")); onCreate(a,null);
        Intent original=game("QA").putExtra("qualification_only",true)
            .putExtra("qualification_session","qa-01234567890123456789012345678901")
            .putExtra("lucent.return.view","cover").putExtra("lucent.return.system","gamecube")
            .putExtra("lucent.return.section","favorites").putExtra("lucent.return.sort","title")
            .putExtra("lucent.return.game","QA").putExtra("lucent.return.system_index",3)
            .putExtra("lucent.return.game_index",17).putExtra("lucent.return.token","navigation-token");
        handleIntent(a,original); Bundle out=new Bundle(); onSaveInstanceState(a,out);
        Intent copy=out.getBundle(RECREATION_STATE).getParcelable("request");
        check(copy.extras.equals(original.extras),"path/qualification/return-state roundtrip differs");
        original.putExtra("path","/changed");
        check(copy.getStringExtra("path").equals("/games/QA"),"saved request aliases original Intent");
    }
    static void importGate() {
        destroyedSessionsRetiring=1;
        check(!tryBeginImportFrontendRestart(),"import overlapped destroyed native owner");
        check(!importFrontendRestartPending,"failed import gate latched restart");
        destroyedSessionsRetiring=0; RETIRING_SESSIONS.add(new Object());
        check(!tryBeginImportFrontendRestart(),"import overlapped normal retirement");
        RETIRING_SESSIONS.clear();
        check(tryBeginImportFrontendRestart(),"quiesced import gate remained closed");
        check(!tryBeginImportFrontendRestart(),"duplicate import reservation succeeded");
    }
    public static void main(String[] args) {
        switch(args[0]) {
        case "deferred":deferredResave();break;
        case "explicit":explicitWins();break;
        case "inactive":inactiveAndExit();break;
        case "bad":badAndUnavailable();break;
        case "retirement":oldOwnerAndRetirement();break;
        case "roundtrip":roundTrip();break;
        case "import":importGate();break;
        default:throw new AssertionError(args[0]);
        }
    }
}
'''


class ActivityRecreationExecutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = HOST.read_text(encoding="utf-8")
        start = source.index("private static final String RECREATION_STATE")
        end = source.index("    /**\n     * Sessions that are committing", start)
        members = source[start:end]
        for signature in ("public static synchronized boolean handleIntent(",
                          "public static synchronized void onResume(",
                          "public static synchronized void onDestroy(",
                          "public static synchronized boolean tryBeginImportFrontendRestart(",
                          "private static String clean("):
            members += "\n" + java_block(source, signature)
        return_source = (HOST.parent / "SessionReturnState.java").read_text(encoding="utf-8")
        members += "\n" + java_block(return_source, "public final class SessionReturnState").replace(
            "public final class SessionReturnState", "static final class SessionReturnState", 1)
        # Run the real pause callback's recovery prefix, before the unrelated
        # engine/surface work. The source-wiring check below pins that boundary.
        pause = java_block(source, "public static synchronized void onPause(")
        members += "\n" + pause.split("if (active == null", 1)[0] + "}\n"
        cls.temp = tempfile.TemporaryDirectory(prefix="lucent-recreation-java-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        target = directory / "InWindowGameHost.java"
        target.write_text(JAVA_SHELL.replace("// ACTUAL_MEMBERS", members), encoding="utf-8")
        os_stub = directory / "android/system/Os.java"
        os_stub.parent.mkdir(parents=True)
        os_stub.write_text('''package android.system;
public class Os {
    public static void setenv(String key, String value, boolean overwrite) {
        throw new AssertionError("unexpected Qt terminal environment mutation");
    }
}''', encoding="utf-8")
        process_stub = directory / "android/os/Process.java"
        process_stub.parent.mkdir(parents=True)
        process_stub.write_text('''package android.os;
public class Process {
    public static int myPid() { return 4242; }
    public static void killProcess(int pid) {
        throw new AssertionError("unexpected terminal process termination");
    }
}''', encoding="utf-8")
        cls.java = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")
        result = subprocess.run([str(cls.java / "javac"), "-d", str(directory), str(target),
                                 str(os_stub), str(process_stub)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError("Actual recreation methods failed to compile:\n" + result.stderr)
        cls.directory = directory

    def scenario(self, name):
        result = subprocess.run([str(self.java / "java"), "-cp", str(self.directory),
                                 "InWindowGameHost", name], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_sleep_recreation_resave_then_resume_exactly_once(self):
        self.scenario("deferred")

    def test_explicit_new_game_wins_over_pending_saved_game(self):
        self.scenario("explicit")

    def test_exit_inactive_and_fatal_markers_do_not_resume(self):
        self.scenario("inactive")

    def test_bad_state_and_unavailable_activity_fail_closed(self):
        self.scenario("bad")

    def test_old_activity_and_retirement_block_new_native_owner(self):
        self.scenario("retirement")

    def test_qualification_path_and_real_return_state_roundtrip(self):
        self.scenario("roundtrip")

    def test_import_restart_waits_for_destroyed_and_normal_retirement(self):
        self.scenario("import")


if __name__ == "__main__":
    unittest.main()
