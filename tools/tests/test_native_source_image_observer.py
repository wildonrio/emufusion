"""Execute the actual pure Java observer against deterministic synthetic ABI fixtures.

This checks metadata retention/one-shot observation, not runtime timing or image quality.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


class NativeSourceImageObserverTest(unittest.TestCase):
    def test_exact_observation_lifetimes_statuses_and_zero_allocations(self):
        base = ROOT / "unified-android"
        names = ("NativeSourceImage", "NativeSourceImageLedger", "NativeSourceImageProvider",
                 "NativeSourceImageObserver")
        sources = [base / f"src/com/thorium/lucent/video/{name}.java" for name in names]
        sources.append(base / "test/com/thorium/lucent/video/NativeSourceImageObserverTest.java")
        with tempfile.TemporaryDirectory(prefix="source-image-observer-") as temporary:
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", temporary,
                                       *map(str, sources)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / "java"), "-cp", temporary,
                                  "com.thorium.lucent.video.NativeSourceImageObserverTest"],
                                 capture_output=True, text=True, timeout=45)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn("no source authority; zero hot allocations", ran.stdout)


if __name__ == "__main__":
    unittest.main()
