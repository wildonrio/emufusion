"""The hidden Pegasus splash must not keep Qt redrawing the library.

Its progress-bar stripe looped forever with no running guard while the splash
was only hidden (visible: focus), and a running animation makes Qt Quick render
every vsync: the library's surface redrew at the panel rate, also behind
in-window games (2026-10-24). The frontend compiles its QML in
(qtquickcompiler), so the fix is a source patch in the frontend recipe and a
rebuilt library pinned in the kit lock, not an edit of retained QML text.
"""
import hashlib
import json
import unittest

from tools.tests.test_first_install_startup import ROOT

TOOLS = ROOT / 'unified-android/tools'
PATCH = TOOLS / 'pegasus-splash-idle.patch'
LOCK = ROOT / 'unified-android/source-frontend-artifact-lock.json'


class PegasusSplashIdleTest(unittest.TestCase):
    def test_recipe_and_lock_carry_the_splash_patch(self):
        patch = PATCH.read_text()
        self.assertIn('+                running: root.visible', patch)
        self.assertIn(' SequentialAnimation on animatedWidth {', patch)
        self.assertIn(PATCH.name, (TOOLS / 'build_pegasus_source_android.sh').read_text())
        lock = json.loads(LOCK.read_text())
        self.assertEqual(lock['patches'][PATCH.name], hashlib.sha256(PATCH.read_bytes()).hexdigest())
        self.assertIn('pegasus-splash-idle.patch', lock['postBuildSplashIdle'])
        self.assertNotEqual(lock['payloads']['lib/arm64-v8a/libpegasus-fe_arm64-v8a.so'],
                            'cd17524aca9f2405cdcc2fbc9848ad0ecdb30ddfd6a7957a4601f430a41a80b8')


if __name__ == '__main__':
    unittest.main()
