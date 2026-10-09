"""UI-thread input and pause must not wait for a running software core frame.

Reproduces the October 8 Sonic 2 ANR: BlastEm stopped returning from retro_run
while LibretroHost.runFrame held the host monitor, and the next touch blocked
the UI thread inside synchronized LibretroHost.setJoypadButton for 5 s.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
PREVIEW = ROOT / 'unified-android/src/com/thorium/preview'
HOST = PREVIEW / 'LibretroHost.java'
PENDING = PREVIEW / 'PendingHostInput.java'
SESSION = PREVIEW / 'game/LibretroEngineSession.java'


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def compile_and_run(files, main):
    with tempfile.TemporaryDirectory(prefix='lucent-host-input-') as temporary:
        sources = []
        for name, text in files.items():
            path = Path(temporary) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            sources.append(str(path))
        out = Path(temporary) / 'out'
        compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out),
                                   *sources], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        return subprocess.run([str(JAVA / 'java'), '-cp', str(out), main],
                              capture_output=True, text=True, timeout=60)


PENDING_PROBE = r'''
package com.thorium.preview;
import java.util.ArrayList;
import java.util.List;
public class PendingProbe {
  static final List<String> calls = new ArrayList<>();
  static final PendingHostInput.Sink SINK = new PendingHostInput.Sink() {
    public void joypadButton(int p, int b, boolean v) { calls.add("joy " + p + " " + b + " " + v); }
    public void analogAxis(int p, int i, int id, int v) { calls.add("axis " + p + " " + i + " " + id + " " + v); }
    public void pointer(int p, int x, int y, boolean v) { calls.add("ptr " + p + " " + x + " " + y + " " + v); }
    public void paused(boolean v) { calls.add("paused " + v); }
  };
  static void check(boolean ok, String what) { if (!ok) throw new AssertionError(what + " calls=" + calls); }
  static void rejects(Runnable r, String what) {
    try { r.run(); } catch (IllegalStateException expected) { return; }
    throw new AssertionError("accepted " + what);
  }
  public static void main(String[] args) {
    PendingHostInput in = new PendingHostInput();
    in.applyTo(SINK);
    check(calls.isEmpty(), "clean state applies nothing");
    in.setJoypadButton(0, 3, true);
    in.setJoypadButton(0, 3, false);
    in.applyTo(SINK);
    check(calls.isEmpty(), "press+release before a frame nets to the native final mask");
    in.setJoypadButton(0, 3, true);
    in.setJoypadButton(1, 8, true);
    in.setPaused(true);
    in.applyTo(SINK);
    check(calls.equals(java.util.Arrays.asList("paused true", "joy 0 3 true", "joy 1 8 true")),
          "pause first, then each changed button");
    calls.clear();
    in.applyTo(SINK);
    check(calls.isEmpty(), "unchanged state is not reapplied");
    in.setAnalogAxis(0, 0, 1, -32768);
    in.setAnalogAxis(0, 2, 15, 1234);
    in.setPointer(0, -5, 7, true);
    in.setJoypadButton(0, 3, false);
    in.setPaused(false);
    in.applyTo(SINK);
    check(calls.equals(java.util.Arrays.asList("paused false", "joy 0 3 false",
          "axis 0 0 1 -32768", "axis 0 2 15 1234", "ptr 0 -5 7 true")), "latest values in order");
    calls.clear();
    in.setAnalogAxis(0, 0, 1, -32768);
    in.setPointer(0, -5, 7, true);
    in.applyTo(SINK);
    check(calls.isEmpty(), "rewriting the same values is a no-op");
    rejects(() -> in.setJoypadButton(8, 0, true), "port 8");
    rejects(() -> in.setJoypadButton(0, 16, true), "button 16");
    rejects(() -> in.setJoypadButton(-1, 0, true), "port -1");
    rejects(() -> in.setAnalogAxis(0, 0, 2, 0), "stick id 2");
    rejects(() -> in.setAnalogAxis(0, 3, 0, 0), "analog index 3");
    rejects(() -> in.setAnalogAxis(0, 0, 0, 40000), "axis value out of range");
    rejects(() -> in.setPointer(8, 0, 0, false), "pointer port 8");
    in.applyTo(SINK);
    check(calls.isEmpty(), "rejected calls change nothing");
    System.out.println("pending host input probe passed");
  }
}
'''


def host_probe(host_source, setter_body):
    fields = host_source[host_source.index('    private volatile long handle;'):
                         host_source.index('    private final int[] videoInfoScratch')]
    fields = fields.replace('private volatile long handle;', 'private volatile long handle = 1L;')
    extracted = '\n'.join(method(host_source, sig) for sig in (
        'public synchronized void runFrame()',
        'public void pause()',
        'public void resume()',
        'public boolean awaitFrameBoundary(',
        'public void setAnalogAxis(',
        'public void setAnalogAxisRaw(',
        'public void setPointer(',
        'private void checkOpen()'))
    return r'''
package com.thorium.preview;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
public class HostProbe {
  static final List<String> calls = Collections.synchronizedList(new ArrayList<String>());
  static volatile CountDownLatch entered, release;
  static void nativeRunFrame(long h) {
    calls.add("run");
    CountDownLatch gate = release;
    if (gate != null) {
      entered.countDown();
      try { gate.await(); } catch (InterruptedException e) { throw new RuntimeException(e); }
    }
  }
  static void nativeSetPaused(long h, boolean v) { calls.add("paused " + v); }
  static void nativeSetJoypadButton(long h, int p, int b, boolean v) { calls.add("joy " + p + " " + b + " " + v); }
  static void nativeSetAnalogAxis(long h, int p, int i, int id, int v) { calls.add("axis " + p + " " + i + " " + id + " " + v); }
  static void nativeSetPointer(long h, int p, int x, int y, boolean v) { calls.add("ptr " + p + " " + x + " " + y + " " + v); }
''' + fields + extracted + '\n' + setter_body + r'''
  static void check(boolean ok, String what) { if (!ok) throw new AssertionError(what + " calls=" + calls); }
  public static void main(String[] args) throws Exception {
    final HostProbe host = new HostProbe();
    entered = new CountDownLatch(1);
    release = new CountDownLatch(1);
    Thread frame = new Thread(new Runnable() { public void run() { host.runFrame(); } });
    frame.start();
    check(entered.await(5, TimeUnit.SECONDS), "frame entered the core");
    final long[] elapsed = new long[1];
    Thread ui = new Thread(new Runnable() { public void run() {
      long start = System.nanoTime();
      host.setJoypadButton(0, 3, true);
      host.pause();
      host.setPointer(0, (short) 10, (short) 20, true);
      host.setAnalogAxis(0, 0, 0, 1f);
      elapsed[0] = System.nanoTime() - start;
    }});
    ui.start();
    ui.join(1500);
    if (ui.isAlive()) {
      System.out.println("UI thread blocked behind the running frame");
      release.countDown();
      frame.join(5000);
      System.exit(3);
    }
    check(TimeUnit.NANOSECONDS.toMillis(elapsed[0]) < 250, "UI calls returned promptly");
    check(!host.awaitFrameBoundary(50), "frame boundary reports the frame still running");
    check(calls.equals(java.util.Arrays.asList("run")), "nothing reached native during the frame");
    release.countDown();
    release = null;
    frame.join(5000);
    check(host.awaitFrameBoundary(1000), "frame boundary observed after the frame returned");
    host.runFrame();
    check(calls.equals(java.util.Arrays.asList("run", "paused true", "joy 0 3 true",
          "axis 0 0 0 32767", "ptr 0 10 20 true", "run")),
          "queued pause and input applied before the next frame");
    calls.clear();
    host.resume();
    host.setJoypadButton(0, 3, false);
    host.runFrame();
    check(calls.equals(java.util.Arrays.asList("paused false", "joy 0 3 false", "run")),
          "resume and release applied before the next frame");
    System.out.println("host ui input probe passed");
  }
}
'''


class LibretroHostUiInputTest(unittest.TestCase):
    def test_pending_input_keeps_latest_state_and_validates_on_caller(self):
        ran = compile_and_run({
            'com/thorium/preview/PendingHostInput.java': PENDING.read_text(),
            'com/thorium/preview/PendingProbe.java': PENDING_PROBE,
        }, 'com.thorium.preview.PendingProbe')
        self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
        self.assertIn('pending host input probe passed', ran.stdout)

    def test_actual_host_methods_do_not_block_ui_on_running_frame(self):
        source = HOST.read_text()
        setter = method(source, 'public void setJoypadButton(')
        ran = compile_and_run({
            'com/thorium/preview/PendingHostInput.java': PENDING.read_text(),
            'com/thorium/preview/HostProbe.java': host_probe(source, setter),
        }, 'com.thorium.preview.HostProbe')
        self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
        self.assertIn('host ui input probe passed', ran.stdout)

    def test_control_previous_synchronized_setter_blocks_ui(self):
        # Expected-failure control: the former setter, which took the host
        # monitor and wrote native state directly, blocks behind runFrame.
        source = HOST.read_text()
        previous = '''  public synchronized void setJoypadButton(int port, int retroJoypadId, boolean pressed) {
    checkOpen();
    nativeSetJoypadButton(handle, port, retroJoypadId, pressed);
  }'''
        ran = compile_and_run({
            'com/thorium/preview/PendingHostInput.java': PENDING.read_text(),
            'com/thorium/preview/HostProbe.java': host_probe(source, previous),
        }, 'com.thorium.preview.HostProbe')
        self.assertEqual(3, ran.returncode, ran.stdout + ran.stderr)
        self.assertIn('UI thread blocked behind the running frame', ran.stdout)

    def test_exit_quiesce_waits_bounded_for_the_frame_boundary(self):
        session = SESSION.read_text()
        quiesce = method(session, '@Override public void quiesceForExit()')
        self.assertIn('pause(PauseReason.LUCENT_MENU);', quiesce)
        self.assertIn('active.awaitFrameBoundary(250L)', quiesce)
        self.assertLess(quiesce.index('awaitFrameBoundary'), quiesce.index('presentationLock.tryLock'))

    def test_ui_reachable_host_calls_are_not_monitor_bound(self):
        source = HOST.read_text()
        for signature in ('public void pause()', 'public void resume()',
                          'public void setJoypadButton(', 'public void setAnalogAxis(',
                          'public void setAnalogAxisRaw(', 'public void setPointer('):
            body = method(source, signature)
            self.assertNotIn('native', body.replace('pendingInput', ''), signature)
        run = method(source, 'public synchronized void runFrame()')
        self.assertLess(run.index('pendingInput.applyTo(nativeInput)'), run.index('nativeRunFrame(handle)'))


if __name__ == '__main__':
    unittest.main()
