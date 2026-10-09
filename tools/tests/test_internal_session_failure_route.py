"""Execute the real internal host error callback, including retirement ordering.

This is a host Java regression, not Android/UI or real-engine acceptance.
An internal launch must not be redirected after failure, including when an
External preference is selected while that internal session is still loading.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT

HOST = ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java'


class InternalSessionFailureRouteTest(unittest.TestCase):
    def test_internal_failures_stay_internal_after_route_preference_changes(self):
        source = HOST.read_text()
        callback = source[source.index('    @Override public void onSessionError('):
                          source.index('    @Override public void onSessionStopRejected(')]
        callback = callback.replace('@Override ', '')
        harness = r'''
import java.util.*;
class Activity { void runOnUiThread(Runnable r) { r.run(); } }
class Uri { String getQueryParameter(String k) { return "/owned/test.nsp"; } }
class Request { String engineId, systemId; Uri contentUri = new Uri(); }
class Handler { void postDelayed(Runnable r,long ms) { r.run(); } }
class Log { static void e(String a,String b,Throwable c) {} static void w(String a,String b) {}
            static void i(String a,String b) {} }
class NativeAdapterSystemDirectory {
  static boolean isPrerequisiteFailure(String e,Throwable c) {
    return "eden".equals(e) && c != null && "missing firmware".equals(c.getMessage());
  }
}
class NativeAdapterPrerequisites { static void record(Activity a,String s,boolean b) {} }
class ExternalGameFallback {
  static boolean explicitExternal; static int launched;
  static boolean canLaunchSwitch(Activity a) { return explicitExternal; }
  static boolean launchSwitch(Activity a,String p) { launched++; return true; }
}
public class InternalFailureProbe {
  static final String TAG = "test";
  Activity activity = new Activity(); Request request = new Request(); Handler mainHandler = new Handler();
  boolean libraryReturned; Object retiringSession = new Object();
  int fatal, retired, runtime, exits; String message; Throwable failure;
  static String clean(String s) { return s == null ? "" : s.trim(); }
  void finishRetiringSession(Object session,Throwable cause) {
    if(session != retiringSession) throw new AssertionError("wrong retiring owner");
    retired++; failure = cause;
  }
  void showFatalError(String s) { fatal++; message = s; }
  void onSurfaceRuntimeError(String s,Throwable t) { runtime++; message = s; failure = t; }
  void exitToLibrary(String s) { exits++; }
  CALLBACK
  static void check(boolean value,String why) { if(!value) throw new AssertionError(why); }
  public static void main(String[] args) {
    int cases = 0;
    for(String system : new String[]{"switch","wiiu","ps3","gc","wii","ps2","psp",
        "psx","dreamcast","n3ds","nds","n64","nes","snes","gb","gbc","gba","megadrive","gamegear"}) {
      for(boolean preference : new boolean[]{false,true}) {
        for(Throwable cause : new Throwable[]{null, new IllegalStateException("missing firmware"),
            new IllegalStateException("renderer initialization failed")}) {
          InternalFailureProbe host = new InternalFailureProbe();
          host.request.systemId = system; host.request.engineId = system.equals("switch") ? "eden" : system;
          ExternalGameFallback.explicitExternal = preference; ExternalGameFallback.launched = 0;
          host.onSessionError("Readable setup or renderer error",cause);
          check(host.fatal == 1 && host.message.equals("Readable setup or renderer error"),
                system + " failure did not remain visible inside EmuFusion; external=" + preference);
          check(ExternalGameFallback.launched == 0 && host.exits == 0 && host.retired == 0,
                system + " silently launched or retired during load failure");
          cases++;
        }
      }
    }
    for(Throwable cause : new Throwable[]{null,new IllegalStateException("late failure")}) {
      InternalFailureProbe host = new InternalFailureProbe(); host.libraryReturned = true;
      host.onSessionError("late failure",cause);
      check(host.retired == 1 && host.fatal == 0 && host.runtime == 0,"late error reopens UI");
      check(cause == null ? host.failure instanceof IllegalStateException : host.failure == cause,
            "retirement lost original failure");
    }
    InternalFailureProbe host = new InternalFailureProbe();
    Throwable failure = new com.thorium.lucent.video.RuntimePresentationFailure.Failure("display stopped");
    host.onSessionError("outer message",failure);
    check(host.runtime == 1 && host.fatal == 0 && host.retired == 0 && host.failure == failure,
          "runtime presentation error lost dedicated recovery path");
    System.out.println("PASS internal failures=" + cases + ", retirement=2, presentation=1");
  }
}
'''.replace('CALLBACK', callback)
        with tempfile.TemporaryDirectory(prefix='internal-error-route-') as directory:
            directory = Path(directory)
            main = directory / 'InternalFailureProbe.java'
            main.write_text(harness)
            failure = directory / 'com/thorium/lucent/video/RuntimePresentationFailure.java'
            failure.parent.mkdir(parents=True)
            failure.write_text('package com.thorium.lucent.video; public class RuntimePresentationFailure {'
                               'public static class Failure extends RuntimeException {'
                               'public Failure(String message){super(message);}}}')
            compile_result = subprocess.run([str(JAVA/'javac'), '-d', str(directory), str(main), str(failure)],
                                            capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(JAVA/'java'), '-cp', str(directory), 'InternalFailureProbe'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS internal failures=114, retirement=2, presentation=1', result.stdout)


if __name__ == '__main__':
    unittest.main()
