"""Stick, D-pad and touch motion reaches the core as it arrives, not at a later refresh.

Stock Android batches joystick and touch MotionEvent moves until a later vsync
input callback: on the stock phone emulator a stick change reached the game
15.5 ms after it happened, 1.5 ms unbatched (2026-10-24). The window takes its unbuffered source from
the focused view's chain and recomputes it on focus changes, so the request
must follow focus while a game is attached and be withdrawn afterwards. This
compiles the production class unchanged against minimal Android stand-ins.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT

GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
SOURCE = GAME / 'UnbufferedJoystickInput.java'
HOST = GAME / 'InWindowGameHost.java'
ACTIVITY = GAME / 'EmuFusionGameActivity.java'
ANDROID_JAR = Path.home() / 'Library/Android/sdk/platforms/android-35/android.jar'

STUBS = {
    'android/os/Build.java': '''package android.os;
public class Build { public static class VERSION { public static int SDK_INT = 33; } }''',
    'android/util/Log.java': '''package android.util;
public final class Log { public static int i(String tag, String message) { return 0; } }''',
    'android/view/InputDevice.java': '''package android.view;
public final class InputDevice {
  public static final int SOURCE_CLASS_NONE = 0, SOURCE_CLASS_POINTER = 2, SOURCE_CLASS_JOYSTICK = 16;
}''',
    'android/view/MotionEvent.java': '''package android.view;
public class MotionEvent {
  public static final int ACTION_MOVE = 2;
  public boolean isFromSource(int source) { return true; }
  public int getActionMasked() { return ACTION_MOVE; }
  public long getEventTime() { return System.nanoTime() / 1000000L; }
  public int getHistorySize() { return 0; }
}''',
    'android/view/ViewTreeObserver.java': '''package android.view;
import java.util.ArrayList;
public final class ViewTreeObserver {
  public interface OnGlobalFocusChangeListener { void onGlobalFocusChanged(View o, View n); }
  public final ArrayList<OnGlobalFocusChangeListener> listeners = new ArrayList<>();
  public void addOnGlobalFocusChangeListener(OnGlobalFocusChangeListener l) { listeners.add(l); }
  public void removeOnGlobalFocusChangeListener(OnGlobalFocusChangeListener l) { listeners.remove(l); }
  public boolean isAlive() { return true; }
  public void focus(View o, View n) {
    for (OnGlobalFocusChangeListener l : new ArrayList<>(listeners)) l.onGlobalFocusChanged(o, n);
  }
}''',
    'android/view/View.java': '''package android.view;
public class View {
  public int unbuffered;
  public View focused;
  public final ViewTreeObserver observer;
  public View(ViewTreeObserver observer) { this.observer = observer; }
  public void requestUnbufferedDispatch(int source) { unbuffered = source; }
  public View findFocus() { return focused; }
  public ViewTreeObserver getViewTreeObserver() { return observer; }
}''',
}

PROBE = r'''
package com.thorium.preview.game;

import android.os.Build;
import android.view.InputDevice;
import android.view.View;
import android.view.ViewTreeObserver;

public class UnbufferedJoystickInputProbe {
  static void check(boolean condition, String message) {
    if (!condition) throw new AssertionError(message);
  }
  public static void main(String[] args) {
    int joystick = InputDevice.SOURCE_CLASS_JOYSTICK | InputDevice.SOURCE_CLASS_POINTER;
    ViewTreeObserver observer = new ViewTreeObserver();
    View decor = new View(observer), qt = new View(observer), menu = new View(observer);
    decor.focused = qt;

    UnbufferedJoystickInput input = UnbufferedJoystickInput.install(decor);
    check(qt.unbuffered == joystick, "The focused view carries the request into the window");
    check(observer.listeners.size() == 1, "Focus is followed while the game is attached");

    observer.focus(qt, menu);
    check(menu.unbuffered == joystick, "A newly focused view (pause menu) is asked too");
    observer.focus(menu, null);
    check(decor.unbuffered == joystick, "With focus cleared the window root holds the request");

    input.release();
    check(qt.unbuffered == 0 && menu.unbuffered == 0 && decor.unbuffered == 0,
          "The library gets Android's batching back on every view that was asked");
    check(observer.listeners.isEmpty(), "Focus is no longer followed after the game");
    input.release();

    Build.VERSION.SDK_INT = 29;
    View old = new View(new ViewTreeObserver());
    UnbufferedJoystickInput.install(old).release();
    check(old.unbuffered == 0 && old.observer.listeners.isEmpty(),
          "Before Android 11 the per-source request does not exist and nothing is asked");
    System.out.println("PASS");
  }
}
'''


class UnbufferedJoystickInputTest(unittest.TestCase):
    def test_request_follows_focus_and_is_withdrawn(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-stick-input-') as temp:
            folder = Path(temp)
            sources = []
            for name, text in STUBS.items():
                path = folder / 'src' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                sources.append(str(path))
            package = folder / 'src/com/thorium/preview/game'
            package.mkdir(parents=True)
            (package / SOURCE.name).write_text(SOURCE.read_text())
            (package / 'UnbufferedJoystickInputProbe.java').write_text(PROBE)
            sources += [str(package / SOURCE.name), str(package / 'UnbufferedJoystickInputProbe.java')]
            classes = folder / 'classes'
            subprocess.run([str(JAVA / 'javac'), '-d', str(classes)] + sources,
                           check=True, capture_output=True, text=True)
            result = subprocess.run([str(JAVA / 'java'), '-cp', str(classes),
                                     'com.thorium.preview.game.UnbufferedJoystickInputProbe'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS', result.stdout)

    @unittest.skipUnless(ANDROID_JAR.is_file(), 'Android SDK platform 35 not installed')
    def test_compiles_against_the_android_sdk(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-stick-sdk-') as temp:
            subprocess.run([str(JAVA / 'javac'), '-cp', str(ANDROID_JAR), '-d', temp, str(SOURCE)],
                           check=True, capture_output=True, text=True)

    def test_every_game_window_installs_it(self):
        host = HOST.read_text()
        attach = host[host.index('private void attach() {'):][:1600]
        self.assertIn('stickInput = UnbufferedJoystickInput.install(content);', attach)
        detach = host[host.index('private void detachViews() {'):][:400]
        self.assertIn('stickInput.release();', detach)
        motion = host[host.index('private boolean handleMotionEvent('):][:300]
        self.assertIn('stickInput.record(event);', motion)
        touch = host[host.index('root.setOnTouchListener((view, event) -> {'):][:200]
        self.assertIn('stickInput.record(event);', touch)
        activity = ACTIVITY.read_text()
        self.assertIn('UnbufferedJoystickInput.install(getWindow().getDecorView())', activity)
        source = SOURCE.read_text()
        self.assertIn('Build.VERSION.SDK_INT >= 30', source)
        self.assertIn('InputDevice.SOURCE_CLASS_JOYSTICK | InputDevice.SOURCE_CLASS_POINTER', source)
        self.assertIn('/data/local/tmp/emufusion-buffered-input', source)


if __name__ == '__main__':
    unittest.main()
