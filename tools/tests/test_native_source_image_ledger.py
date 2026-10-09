"""Compile and execute actual sealed-transfer/retention methods, including allocation accounting."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


class NativeSourceImageLedgerTest(unittest.TestCase):
    def test_actual_retention_identity_and_zero_hot_allocations(self):
        with tempfile.TemporaryDirectory(prefix="source-image-retention-") as temporary:
            base = ROOT / "unified-android"
            files = [base / "src/com/thorium/lucent/video/NativeSourceImage.java",
                     base / "src/com/thorium/lucent/video/NativeSourceImageLedger.java",
                     base / "test/com/thorium/lucent/video/NativeSourceImageLedgerTest.java"]
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", temporary,
                                       *map(str, files)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / "java"), "-cp", temporary,
                                  "com.thorium.lucent.video.NativeSourceImageLedgerTest"],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn("retention foundation only; no source authority", ran.stdout)


if __name__ == "__main__":
    unittest.main()
