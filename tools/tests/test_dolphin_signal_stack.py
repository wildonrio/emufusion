"""Execute the pinned/patched POSIX lifecycle with a pre-existing Android stack.

The syscall/allocator boundary is recorded; no real process handlers are changed.
Both the pre-fix ownership violation and the corrected lifetime are exercised.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "engines/build/sources/dolphin-0ff12a5a2835762e0665afe6a161a648b433f996/Source/Core/Core/MemTools.cpp"
PATCH = ROOT / "engines/patches/dolphin-libretro-own-signal-stack.patch"


def harness(source):
    posix = source.split("#elif defined(_POSIX_VERSION)", 1)[1]
    functions = posix.split("void InstallExceptionHandler()", 1)[1]
    functions = "void InstallExceptionHandler()" + functions.split(
        "bool IsExceptionHandlerSupported()", 1)[0]
    ownership = ""
    if "static thread_local void* owned_signal_stack" in posix:
        ownership = posix[posix.index("static thread_local void* owned_signal_stack"):
                          posix.index("static struct sigaction old_sa_segv")]
    return r'''
#include <cassert>
#include <cstddef>
#include <cstdio>
#undef __APPLE__
#define SIGSTKSZ 16384
#define SS_DISABLE 2
#define SA_SIGINFO 4
#define SIGSEGV 11
struct stack_t { void* ss_sp; size_t ss_size; int ss_flags; };
struct sigaction { void (*sa_sigaction)(int, void*, void*); int sa_flags, sa_mask; };
static char android_stack[1024], dolphin_stack[16384];
static stack_t current_stack{android_stack, sizeof(android_stack), 0};
static int allocated, freed, actions, stack_calls, alerts;
static bool fail_allocate, fail_stack;
static bool foreign_free;
static void* allocate(size_t size) {
    assert(size == sizeof(dolphin_stack));
    if (fail_allocate) return nullptr;
    ++allocated; return dolphin_stack;
}
static void release(void* ptr) {
    if (ptr != dolphin_stack) {
        std::fputs("must not free Android's pre-existing stack\n", stderr);
        foreign_free = true;
        return;
    }
    assert(current_stack.ss_sp != ptr || (current_stack.ss_flags & SS_DISABLE));
    ++freed;
}
#define malloc allocate
#define free release
static int sigaltstack(const stack_t* next, stack_t* previous) {
    ++stack_calls;
    if (fail_stack) return -1;
    if (previous) *previous = current_stack;
    if (next) current_stack = *next;
    return 0;
}
static int sigaction(int signal, const struct sigaction*, struct sigaction* previous) {
    assert(signal == SIGSEGV); ++actions;
    if (previous) *previous = {};
    return 0;
}
static void sigemptyset(int* mask) { *mask = 0; }
static void sigsegv_handler(int, void*, void*) {}
template <typename... Args> static void PanicAlertFmt(const char*, Args...) { ++alerts; }
namespace Common { static const char* LastStrerrorString() { return "injected"; } }
static struct sigaction old_sa_segv;
''' + ownership + functions + r'''
int main() {
    // The r15 crash: unloading after load, before any emulated frame/handler.
    UninstallExceptionHandler();
    if (foreign_free) return 42;
    assert(stack_calls == 0 && actions == 0 && freed == 0);
    assert(current_stack.ss_sp == android_stack);
    InstallExceptionHandler();
    assert(allocated == 1 && current_stack.ss_sp == dolphin_stack && actions == 1);
    InstallExceptionHandler(); // idempotent ownership
    assert(allocated == 1 && actions == 1);
    UninstallExceptionHandler();
    assert(freed == 1 && actions == 2 && current_stack.ss_sp == android_stack);
    assert(current_stack.ss_size == sizeof(android_stack) && current_stack.ss_flags == 0);
    UninstallExceptionHandler();
    assert(freed == 1 && actions == 2);
    // Normal next session, including a caller with no alternate stack.
    current_stack = {nullptr, 0, SS_DISABLE};
    InstallExceptionHandler();
    UninstallExceptionHandler();
    assert(allocated == 2 && freed == 2 && current_stack.ss_flags == SS_DISABLE);
    fail_allocate = true;
    InstallExceptionHandler();
    UninstallExceptionHandler();
    assert(allocated == 2 && freed == 2 && alerts == 1);
    fail_allocate = false;
    fail_stack = true;
    InstallExceptionHandler();
    UninstallExceptionHandler();
    assert(allocated == 3 && freed == 3 && alerts == 2);
    fail_stack = false;
    InstallExceptionHandler();
    fail_stack = true;
    UninstallExceptionHandler(); // failed restoration must not free a live stack
    assert(allocated == 4 && freed == 3 && alerts == 3);
    fail_stack = false;
    UninstallExceptionHandler();
    assert(freed == 4 && current_stack.ss_flags == SS_DISABLE);
}
'''


class DolphinSignalStackTest(unittest.TestCase):
    def test_patch_is_pinned_and_applied_by_build_recipe(self):
        patch_sha = hashlib.sha256(PATCH.read_bytes()).hexdigest()
        lock = json.loads((ROOT / "engines/dolphin-source-lock.json").read_text())
        entry = next(row for row in lock["patches"] if row["path"] ==
                     str(PATCH.relative_to(ROOT)))
        self.assertEqual(entry["sha256"], patch_sha)
        recipe = (ROOT / "engines/build_core.sh").read_text()
        self.assertIn(str(PATCH.relative_to(ROOT)), recipe)
        self.assertIn(patch_sha, recipe)

    def test_before_fails_after_passes(self):
        self.assertTrue(SOURCE.is_file(), "pinned Dolphin source is required")
        with tempfile.TemporaryDirectory(prefix="dolphin-signal-stack-") as directory:
            directory = Path(directory)
            staged = directory / "Source/Core/Core/MemTools.cpp"
            staged.parent.mkdir(parents=True)
            shutil.copy2(SOURCE, staged)
            before = SOURCE.read_text()
            subprocess.run(["patch", "-p1", "--batch", "-i", str(PATCH)],
                           cwd=directory, check=True, capture_output=True)
            for label, source, expected_success in (
                    ("before", before, False), ("after", staged.read_text(), True)):
                test = directory / (label + ".cpp")
                test.write_text(harness(source))
                binary = directory / label
                subprocess.run(["clang++", "-std=c++17", "-Wall", "-Wextra",
                                "-fsanitize=address,undefined", str(test), "-o", str(binary)],
                               check=True, capture_output=True)
                result = subprocess.run([str(binary)], capture_output=True, timeout=10)
                if expected_success:
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b"must not free Android", result.stderr)


if __name__ == "__main__":
    unittest.main()
