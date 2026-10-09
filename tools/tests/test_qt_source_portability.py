"""Execute Qt source patches and Android qmake links, not string-only gates."""
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "unified-android"
WORK = PROJECT / "build/qt-5.15.10-16k"
SOURCE = WORK / "source/qtbase-everywhere-src-5.15.10"
QMAKE = WORK / "build-base/bin/qmake"
SDK = Path(os.environ.get("ANDROID_SDK_ROOT", "/Users/tyleryoung/Library/Android/sdk"))
LLVM = SDK / "ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin"
LOCK = json.loads((PROJECT / "qt-source-lock.json").read_text())


class QtSourcePortabilityTest(unittest.TestCase):
    def compile_and_run(self, source, extra=()):
        with tempfile.TemporaryDirectory(prefix="emufusion-qt-behavior-") as directory:
            binary = Path(directory) / "probe"
            result = subprocess.run(["/usr/bin/clang++", "-std=c++11", "-x", "c++", "-", "-o", str(binary), *extra],
                                    input=source, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_gamepad_helper_discards_late_events_and_preserves_dispatch(self):
        path = WORK / "source/qtgamepad-everywhere-src-5.15.10/src/plugins/gamepads/android/src/qandroidgamepadbackend.cpp"
        if not path.exists():
            self.skipTest("Patched Qt Gamepad source required")
        source = path.read_text()
        start = source.index("    class FunctionEvent")
        body = source[start:source.index("    const char keyEventClass", start)]
        self.compile_and_run(r'''
#include <functional>
struct QEvent { enum Type { User }; QEvent(Type) {} virtual ~QEvent() {} };
struct QObject {};
struct QThread { static int currentThread() { return 1; } };
static QEvent *posted = nullptr;
static int postCount = 0, nullAccess = 0;
struct App { int threadId = 1; int thread() { return threadId; }
    void postEvent(QObject *, QEvent *e) { ++postCount; posted = e; } };
// Instrument null access without invoking undefined behavior or crashing Mac UI.
struct AppPointer { App *value = nullptr; App fallback;
    explicit operator bool() const { return value != nullptr; }
    App *operator->() { if (!value) ++nullAccess; return value ? value : &fallback; }
} qApp;
''' + body + r'''
int main() {
    QObject receiver; int calls = 0;
    FunctionEvent::runOnQtThread(&receiver, [&] { ++calls; });
    if (calls || postCount || nullAccess) return 1;
    App application; qApp.value = &application;
    FunctionEvent::runOnQtThread(&receiver, [&] { ++calls; });
    if (calls != 1 || postCount) return 2;
    application.threadId = 2;
    FunctionEvent::runOnQtThread(&receiver, [&] { ++calls; });
    if (calls != 1 || postCount != 1 || !posted) return 3;
    static_cast<FunctionEvent *>(posted)->call(); delete posted;
    return calls == 2 ? 0 : 4;
}
''')

    def test_actual_frontend_android_launch_keeps_scene_and_bookkeeping(self):
        path = WORK / "source/pegasus-frontend-6b322063a036db60cba5810fda82a3ce38f1e62f/src/backend/Backend.cpp"
        if not path.exists():
            self.skipTest("Patched Pegasus source required")
        source = path.read_text()
        start = source.index("void Backend::onProcessLaunched()")
        body = source[start:source.index("void Backend::onProcessFinished()", start)]
        # Use the real declaration: the previous fake public afterRun missed a
        # compile error because that method is deliberately private upstream.
        header = path.with_name("ProcessLauncher.h").read_text()
        header = re.sub(r"^#(?:include|pragma).*\n", "", header, flags=re.MULTILINE)
        fixture = r'''
#define Q_OBJECT
#define signals public
#define slots
struct QObject {};
struct QString {};
struct QStringList {};
struct QProcess { enum ProcessError {}; enum ExitStatus {}; };
''' + header + r'''
int launcherCount = 0;
ProcessLauncher::ProcessLauncher(QObject *) : m_process(nullptr) {}
void ProcessLauncher::afterRun() { ++launcherCount; }
ProcessLauncher launcher;
struct Api { int count = 0; void onGameProcessFinished() { ++count; } } api;
struct Frontend { int count = 0; void teardown() { ++count; } } frontend;
struct Gamepad { int count = 0; void stop() { ++count; } } gamepad;
struct Private { Gamepad &gamepad() { return ::gamepad; } } priv;
struct Backend { Api *m_api_public = &api; ProcessLauncher *m_launcher = &launcher;
    Frontend *m_frontend = &frontend; Private *m_api_private = &priv;
    void onProcessLaunched(); };
''' + body + r'''
int main() { Backend backend; backend.onProcessLaunched();
#ifdef Q_OS_ANDROID
    return api.count == 1 && launcherCount == 1 && !frontend.count && !gamepad.count ? 0 : 1;
#else
    return !api.count && !launcherCount && frontend.count == 1 && gamepad.count == 1 ? 0 : 2;
#endif
}
'''
        self.compile_and_run(fixture, ["-DQ_OS_ANDROID"])
        self.compile_and_run(fixture)

    def test_frontend_patch_applies_and_reverses_pinned_source(self):
        archive = WORK / "downloads/pegasus-6b322063.tar.gz"
        if not archive.exists():
            self.skipTest("Pinned Pegasus source archive required")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), LOCK["pegasus"]["sha256"])
        files = ["src/backend/Backend.cpp", "src/backend/ProcessLauncher.h",
                 "src/backend/platform/AndroidHelpers.h", "src/link_to_backend.pri"]
        with tempfile.TemporaryDirectory(prefix="emufusion-frontend-patch-") as directory:
            folder = Path(directory)
            prefix = "pegasus-frontend-" + LOCK["pegasus"]["commit"] + "/"
            with tarfile.open(archive) as tar:
                originals = {name: tar.extractfile(prefix + name).read() for name in files}
            for name, data in originals.items():
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            command = ["patch", "-f", "-p1", "-d", str(folder)]
            patches = ["pegasus-in-window-source.patch", "pegasus-ndk27-headers.patch", "pegasus-apng-link.patch"]
            for name in patches:
                subprocess.run(command, input=(PROJECT / "tools" / name).read_bytes(), check=True, capture_output=True)
            for name in files:
                self.assertEqual((folder / name).read_bytes(),
                                 (WORK / "source" / prefix / name).read_bytes())
            for name in reversed(patches):
                subprocess.run(command + ["-R"], input=(PROJECT / "tools" / name).read_bytes(), check=True, capture_output=True)
            for name, data in originals.items():
                self.assertEqual((folder / name).read_bytes(), data)

    def test_source_patches_apply_and_reverse_exactly(self):
        archive = WORK / "downloads/qtbase-everywhere-opensource-src-5.15.10.tar.xz"
        if not archive.exists():
            self.skipTest("Pinned Qt source archive not downloaded")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), LOCK["qt_modules"]["qtbase"])
        files = ["mkspecs/android-clang/qmake.conf", "mkspecs/features/android/default_pre.prf",
                 "src/corelib/global/qlogging.cpp"]
        with tempfile.TemporaryDirectory(prefix="emufusion-qt-patch-test-") as directory:
            folder = Path(directory)
            with tarfile.open(archive) as tar:
                originals = {name: tar.extractfile("qtbase-everywhere-src-5.15.10/" + name).read() for name in files}
            for name, data in originals.items():
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for name in ("qtbase-android-16k.patch", "qtbase-ndk27-api.patch"):
                payload = (PROJECT / "tools" / name).read_bytes()
                command = ["patch", "-f", "-p1", "-d", str(folder)]
                # Without -f BSD patch can auto-guess the opposite direction.
                before = subprocess.run(command + ["--dry-run", "-R"], input=payload, capture_output=True)
                self.assertNotEqual(before.returncode, 0, name)
                subprocess.run(command, input=payload, check=True, capture_output=True)
                subprocess.run(command + ["--dry-run", "-R"], input=payload, check=True, capture_output=True)
                subprocess.run(command + ["-R"], input=payload, check=True, capture_output=True)
            for name, data in originals.items():
                self.assertEqual((folder / name).read_bytes(), data, name)

    def test_android_backtrace_guard_matches_available_apis(self):
        if not SOURCE.exists() or not (LLVM / "clang++").exists():
            self.skipTest("Qt source and NDK required")
        text = (SOURCE / "src/corelib/global/qlogging.cpp").read_text()
        start = text.index("#if QT_CONFIG(regularexpression)")
        end = text.index("\n#if QT_CONFIG(slog2)", start)
        guard = text[start:end]
        for api, expected in ((23, False), (32, False), (33, True)):
            with self.subTest(api=api):
                source = "#define QT_CONFIG(x) 1\n#define Q_OS_ANDROID 1\n" + guard
                source += "\n#include <execinfo.h>\n#ifdef QLOGGING_HAVE_BACKTRACE\nvoid *fn = (void*)&backtrace;\n#endif\n"
                source += ("#ifndef" if expected else "#ifdef") + " QLOGGING_HAVE_BACKTRACE\n#error wrong API availability\n#endif\n"
                result = subprocess.run([str(LLVM / "clang++"), "-target", f"aarch64-linux-android{api}",
                                         "-x", "c++", "-fsyntax-only", "-"], input=source, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_qmake_android_shared_and_plugin_links(self):
        if not QMAKE.exists() or not (LLVM / "clang++").exists():
            self.skipTest("Configured isolated Qt qmake and NDK required")
        spec = importlib.util.spec_from_file_location("qt_elf_check", PROJECT / "tools/verify_elf_alignment.py")
        elf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(elf)
        env = dict(os.environ, ANDROID_NDK_ROOT=str(SDK / "ndk/27.0.12077973"),
                   ANDROID_NDK_HOST="darwin-x86_64", ANDROID_SDK_ROOT=str(SDK))
        for kind in ("shared", "shared plugin"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix="emufusion-qt-link-test-") as directory:
                folder = Path(directory)
                (folder / "probe.cpp").write_text('extern "C" int emufusion_probe() { return 16; }\n')
                (folder / "probe.pro").write_text("TEMPLATE = lib\nCONFIG -= qt\nCONFIG += " + kind +
                                                "\nTARGET = page_probe\nSOURCES = probe.cpp\nANDROID_ABIS = arm64-v8a\n")
                for command in ([str(QMAKE), "-spec", "android-clang", "probe.pro"], ["make", "-j2"]):
                    result = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                libraries = list(folder.glob("libpage_probe*.so*"))
                self.assertTrue(libraries)
                for library in libraries:
                    self.assertGreaterEqual(min(elf.load_alignments(library.read_bytes())), 16384)


if __name__ == "__main__":
    unittest.main()
