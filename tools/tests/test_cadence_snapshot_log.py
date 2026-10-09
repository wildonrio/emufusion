"""Exercise the production Java emitter against the independent Python decoder."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
SPEC = importlib.util.spec_from_file_location('timing_snapshot_verifier',
    ROOT / 'unified-android/tools/verify_rife_frame_generation_timing.py')
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class CadenceSnapshotLogTest(unittest.TestCase):
    def test_real_java_emitter_is_bounded_and_roundtrips_unicode(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/CadenceSnapshotLog.java').read_text()
        with tempfile.TemporaryDirectory(prefix='cadence-snapshot-') as folder:
            out = Path(folder)
            files = {
                'CadenceSnapshotLog.java': source,
                'Log.java': 'package android.util; public class Log { public static int i(String t,String s){System.out.println(s);return 0;} }',
                'Process.java': 'package android.os; public class Process { public static int myPid(){return 42;} }',
                'Harness.java': '''package com.thorium.preview.game;
public class Harness { public static void main(String[] args) {
    StringBuilder s = new StringBuilder("App swap cadence ");
    for(int i=0;i<8000;i++) s.append(i%3==0 ? "😀" : "界");
    CadenceSnapshotLog.write("test", 4, s.toString());
    CadenceSnapshotLog.write("test", 4, s.toString());
} }''',
            }
            for name, text in files.items():
                (out / name).write_text(text)
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8',
                '-encoding', 'UTF-8', '-d', folder,
                *[str(out / name) for name in files]], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(JAVA / 'java'), '-cp', folder,
                'com.thorium.preview.game.Harness'], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(all(len(line.encode()) < 3000 for line in run.stdout.splitlines()))
            expected = 'App swap cadence ' + ''.join('😀' if i % 3 == 0 else '界' for i in range(8000))
            self.assertEqual(VERIFIER.snapshot_lines(run.stdout), [expected, expected])


if __name__ == '__main__':
    unittest.main()
