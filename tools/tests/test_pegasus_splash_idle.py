"""The hidden Pegasus splash must not keep Qt redrawing the library.

Its progress animation looped forever with no running guard, and any running
animation makes Qt Quick render every vsync: the library's surface redrew at
~120 Hz behind in-window games (2026-10-24). The patch is an exact,
equal-length edit of the embedded QML, recorded in the frontend lock.
"""
import importlib.util
import json
import unittest

from tools.tests.test_first_install_startup import ROOT

TOOL = ROOT / 'unified-android/tools/patch_pegasus_splash_idle.py'
LOCK = ROOT / 'unified-android/source-frontend-artifact-lock.json'


def load():
    spec = importlib.util.spec_from_file_location('patch_pegasus_splash_idle', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PegasusSplashIdleTest(unittest.TestCase):
    def test_equal_length_guard_on_the_one_block(self):
        tool = load()
        blob = b'\x00prefix' + tool.OLD + b'\n\n            Image {\x00'
        patched = tool.patch(blob)
        self.assertEqual(len(patched), len(blob))
        # Neither a visibility guard nor a finite loop stopped it on the Thor.
        self.assertIn(b'running: false', patched)
        self.assertNotIn(b'Animation.Infinite', patched)
        self.assertNotIn(tool.OLD, patched)
        self.assertEqual(tool.patch(patched), patched, 'patching twice changes nothing')
        for earlier in tool.EARLIER:
            upgraded = tool.patch(b'\x00prefix' + earlier + b'\x00')
            self.assertIn(tool.NEW, upgraded, 'earlier staged forms are upgraded in place')
        with self.assertRaises(SystemExit):
            tool.patch(b'no splash here')
        with self.assertRaises(SystemExit):
            tool.patch(tool.OLD + tool.OLD)

    def test_the_lock_pins_the_patched_frontend(self):
        lock = json.loads(LOCK.read_text())
        note = lock['postBuildSplashIdle']
        self.assertIn('patch_pegasus_splash_idle.py', note)
        self.assertIn('cd17524aca9f2405cdcc2fbc9848ad0ecdb30ddfd6a7957a4601f430a41a80b8', note)
        self.assertNotEqual(lock['payloads']['lib/arm64-v8a/libpegasus-fe_arm64-v8a.so'],
                            'cd17524aca9f2405cdcc2fbc9848ad0ecdb30ddfd6a7957a4601f430a41a80b8')

    def test_stale_compiled_qml_is_dropped_before_qt_starts(self):
        # Qt trusts cached compilations of embedded QML by resource timestamp,
        # which an in-place patch does not change: the Thor ran September 13
        # compilations through every update until this reset.
        app = (ROOT / 'unified-android/src/com/thorium/preview/EmuFusionApplication.java').read_text()
        create = app[app.index('public void onCreate() {'):]
        self.assertLess(create.index('QmlCacheReset.discardIfUpdated(this);'),
                        create.index('migrateLegacyNames();'))
        self.assertLess(create.index('QmlCacheReset.discardIfUpdated(this);'),
                        create.index('startEmuFusionService();'))
        reset = (ROOT / 'unified-android/src/com/thorium/preview/QmlCacheReset.java').read_text()
        self.assertIn('.lastUpdateTime', reset)
        self.assertIn('new File(context.getCacheDir(), "qmlcache")', reset)


if __name__ == '__main__':
    unittest.main()
