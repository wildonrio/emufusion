"""Actual host/bridge methods: process renewal must follow native acknowledgement."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_host_acknowledged_retirement import method, member

ROOT = Path(__file__).resolve().parents[2]
JDK = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')
PATHS = {
    'NativeAdapterStopPolicy.java': 'unified-android/src/com/thorium/lucent/emulators/',
    'InWindowGameHost.java': 'unified-android/src/com/thorium/preview/game/',
    'FrontendRestartActivity.java': 'android-companion/src/com/thorium/preview/',
}


def source(name):
    override = os.environ.get('EMUFUSION_RESTART_SOURCE_DIR')
    return (Path(override) / name if override else ROOT / PATHS[name] / name).read_text()


def execute(java, name, extra=None):
    with tempfile.TemporaryDirectory(prefix='emufusion-session-restart-') as folder:
        root = Path(folder)
        paths = []
        for filename, body in {name + '.java': java, **(extra or {})}.items():
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
            paths.append(str(path))
        for command in ([str(JDK / 'javac'), '-d', folder] + paths,
                        [str(JDK / 'java'), '-cp', folder, name]):
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)


class NativeSessionRestartTest(unittest.TestCase):
    def test_actual_policy_keeps_switch_native_cleanup_and_waits_for_ack(self):
        policy = source('NativeAdapterStopPolicy.java')
        execute('''
import com.thorium.lucent.emulators.NativeAdapterStopPolicy;
public class PolicyTest {
 static void check(boolean v,String why){if(!v)throw new AssertionError(why);}
 public static void main(String[] args){
  check(NativeAdapterStopPolicy.requiresCleanFrontendRestart("eden"),"Switch reuse must cross process boundary");
  check(NativeAdapterStopPolicy.destroyNativeHostOnStop("eden"),"Switch must still flush and destroy native owner");
  check(!NativeAdapterStopPolicy.allowsForcedFrontendRestart("eden"),"Switch cleanup may not be killed by a timer");
  check(NativeAdapterStopPolicy.requiresCleanFrontendRestart("aps3e"),"PS3 restart retained");
  check(NativeAdapterStopPolicy.allowsForcedFrontendRestart("aps3e"),"PS3 bounded retirement retained");
  check(!NativeAdapterStopPolicy.destroyNativeHostOnStop("aps3e"),"PS3 retained native owner policy changed");
  for(String id:new String[]{"cemu","mupen64plus-next","dolphin",null,"unknown"}){
   check(!NativeAdapterStopPolicy.requiresCleanFrontendRestart(id),"unrelated restart enabled");
   check(!NativeAdapterStopPolicy.allowsForcedFrontendRestart(id),"unrelated forced restart enabled");
  }
 }
}''', 'PolicyTest', {'com/thorium/lucent/emulators/NativeAdapterStopPolicy.java': policy})

    def test_actual_exit_completion_waits_for_release_not_just_stop(self):
        body = method(source('InWindowGameHost.java'), 'finishRetiringSession')
        execute('''
import java.util.*;
public class InWindowGameHost {
 static final String TAG="test";
 interface EngineSession {interface Completion {void complete();}}
 static Set<EngineSession> RETIRING_SESSIONS=new HashSet<>();
 static int restores,dispatches;
 int restarts,detaches;
 boolean restartRequired=true;
 EngineSession retiringSession;
 EngineSession.Completion releaseAck;
 static class Request {String engineId="eden",systemId="switch";}
 final Request request=new Request();
 static class Handler {ArrayDeque<Runnable> tasks=new ArrayDeque<>();
  void post(Runnable r){tasks.add(r);} void drain(){while(!tasks.isEmpty())tasks.remove().run();}}
 final Handler mainHandler=new Handler();
 void releaseSessionWhenComplete(EngineSession s,EngineSession.Completion c){releaseAck=c;}
 static void restorePendingRecreations(){restores++;}
 static void dispatchQtTerminalShutdownIfReady(){dispatches++;}
 void detachViews(){detaches++;}
 boolean requiresCleanFrontendRestart(){return restartRequired;}
 void beginCleanFrontendRestart(){restarts++;}
 static class Log {static void i(String t,String m){} static void w(String t,String m,Throwable f){}}
 METHODS
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 public static void main(String[] args){
  InWindowGameHost h=new InWindowGameHost(); EngineSession e=new EngineSession(){};
  h.retiringSession=e; RETIRING_SESSIONS.add(e);
  h.finishRetiringSession(e,null); h.mainHandler.drain();
  check(h.restarts==0,"process restarted before native release acknowledgement");
  check(RETIRING_SESSIONS.contains(e),"pending native owner forgotten");
  check(h.detaches==1 && h.releaseAck!=null,"UI return/release not scheduled");
  h.releaseAck.complete(); check(h.restarts==0,"restart ran on release worker");
  h.mainHandler.drain(); check(h.restarts==1,"acknowledged Switch session never renewed process");
  check(!RETIRING_SESSIONS.contains(e),"completed owner remained registered");
  h.finishRetiringSession(e,null); h.mainHandler.drain(); check(h.restarts==1,"duplicate stop restarted twice");
  InWindowGameHost ordinary=new InWindowGameHost();ordinary.restartRequired=false;
  ordinary.retiringSession=e;ordinary.finishRetiringSession(e,new Exception("save rejected"));
  ordinary.releaseAck.complete();ordinary.mainHandler.drain();
  check(ordinary.restarts==0,"ordinary core restarted frontend");
 }
}'''.replace('METHODS', body), 'InWindowGameHost')

    def test_actual_bridge_carries_next_game_without_mutating_it(self):
        body = member(source('FrontendRestartActivity.java'),
                      '    private static Intent freshFrontendIntent(')
        execute('''
import java.util.*;
public class BridgeTest {
 static class ComponentName {String pkg,name;ComponentName(String p,String n){pkg=p;name=n;}}
 static class Intent {
  static final String ACTION_MAIN="main",CATEGORY_LAUNCHER="launcher";
  static final int FLAG_ACTIVITY_NEW_TASK=1,FLAG_ACTIVITY_CLEAR_TASK=2,FLAG_ACTIVITY_NO_ANIMATION=4;
  String action;int flags;ComponentName component;Map<String,String> extras=new HashMap<>();
  Set<String> categories=new HashSet<>();
  Intent(String a){action=a;} Intent(Intent i){action=i.action;flags=i.flags;component=i.component;
   extras.putAll(i.extras);categories.addAll(i.categories);}
  Intent addCategory(String c){categories.add(c);return this;}
  Intent setComponent(ComponentName c){component=c;return this;}
  Intent setFlags(int f){flags=f;return this;}
 }
 METHODS
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 public static void main(String[] args){
  Intent menu=freshFrontendIntent("com.thorium.preview",null);
  check(menu.action.equals(Intent.ACTION_MAIN)&&menu.categories.contains(Intent.CATEGORY_LAUNCHER),"normal exit must return library");
  Intent next=new Intent("com.thorium.preview.LAUNCH_INTERNAL_GAME");next.flags=32;
  next.extras.put("path","/Games/Metroid.nsp");next.extras.put("engine_id","eden");
  next.extras.put("qualification_session","existing-namespace");
  Intent launch=freshFrontendIntent("com.thorium.preview",next);
  check(launch!=next && next.flags==32 && next.component==null,"caller intent mutated");
  check(launch.action.equals(next.action)&&launch.extras.equals(next.extras),"pending game identity lost");
  check(launch.flags==7 && launch.component.pkg.equals("com.thorium.preview") &&
        launch.component.name.equals("org.pegasus_frontend.android.MainActivity"),"fresh task route incorrect");
 }
}'''.replace('METHODS', body), 'BridgeTest')

    def test_timer_and_game_switch_call_sites_obey_policy(self):
        host = source('InWindowGameHost.java')
        ret = method(host, 'returnToLibraryUi')
        self.assertIn('NativeAdapterStopPolicy.allowsForcedFrontendRestart(request.engineId)', ret)
        switch = method(host, 'replaceWith')
        self.assertIn('beginCleanFrontendRestart(launch)', switch)
        self.assertIn('releaseSessionWhenComplete(ending, released)', switch)
        launch = method(host, 'handleIntent')
        self.assertIn('pendingCleanFrontendLaunch = recreationIntent(request)', launch)
        bridge = source('FrontendRestartActivity.java')
        self.assertIn('freshFrontendIntent(getPackageName(), next)', bridge)
        self.assertIn('EXTRA_NEXT_LAUNCH, new Intent(nextLaunch)', bridge)


if __name__ == '__main__':
    unittest.main()
