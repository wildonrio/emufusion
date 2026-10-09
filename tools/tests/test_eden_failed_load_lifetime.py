"""Execute Eden's real Load error branches against a checked lifetime model.

The runtime tombstone ends in Process::Finalize after ShutdownMainProcess has
unmapped DeviceMemory. This harness checks local ownership/cleanup order, not
GPU compatibility or the complete guest kernel. Runtime QA remains required.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "engines/build/switch-src/eden/src/core/core.cpp"


def branch(source, condition):
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    start = source.index(condition, source.index("SystemResultStatus Load("))
    begin = source.index("{", start)
    depth = 1
    end = begin + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def harness(source):
    blocks = [branch(source, condition) for condition in (
        "if (load_result != Loader::ResultStatus::Success)",
        "if (!app_loader)",
        "if (init_result != SystemResultStatus::Success)",
    )]
    methods = []
    for i, block in enumerate(blocks):
        methods.append("""
        SystemResultStatus Run%d(bool owns_process) {
            auto process = owns_process ? std::make_unique<Process>(*this) : nullptr;
            const auto load_result = Loader::ResultStatus::Failure;
            const auto init_result = SystemResultStatus::ErrorVideoCore;
            const auto app_loader = nullptr;
            const auto filepath = "fixture.rom";
            %s
            return SystemResultStatus::Success;
        }
        """ % (i, block))
    return """
        #include <cassert>
        #include <cstdlib>
        #include <memory>
        using u32 = unsigned;
        #define LOG_CRITICAL(...) ((void)0)
        enum class SystemResultStatus { Success=0, ErrorVideoCore=5,
            ErrorGetLoader=6, ErrorLoader=100 };
        namespace Loader { enum class ResultStatus { Success=0, Failure=1 }; }
        struct Harness {
            bool kernel_alive = true;
            int owners = 0, finalized = 0, shutdowns = 0;
            struct Process {
                Harness& h;
                explicit Process(Harness& h_) : h(h_) { ++h.owners; }
                ~Process() {
                    assert(h.kernel_alive && "process finalized after kernel memory freed");
                    --h.owners;
                    ++h.finalized;
                }
            };
            void ShutdownMainProcess() {
                assert(owners == 0 && "local process still owns guest kernel memory");
                assert(kernel_alive);
                kernel_alive = false;
                ++shutdowns;
            }
            %s
        };
        int main(int argc, char** argv) {
            assert(argc == 3);
            const int which = std::atoi(argv[1]);
            const bool owns = std::atoi(argv[2]);
            Harness h;
            const auto result = which == 0 ? h.Run0(owns) :
                which == 1 ? h.Run1(owns) : h.Run2(owns);
            assert(result == (which == 0 ? SystemResultStatus(101) :
                which == 1 ? SystemResultStatus::ErrorGetLoader :
                SystemResultStatus::ErrorVideoCore));
            assert(h.shutdowns == 1 && !h.kernel_alive);
            assert(h.owners == 0 && h.finalized == (owns ? 1 : 0));
        }
    """ % "\n".join(methods)


@unittest.skipUnless(CORE.is_file(), "local Eden sources unavailable")
class FailedLoadLifetime(unittest.TestCase):
    def test_all_error_branches_release_local_owner_before_shutdown(self):
        if not CORE.is_file():
            self.skipTest("local Eden sources unavailable")
        with tempfile.TemporaryDirectory(prefix="eden-failed-load-") as directory:
            root = Path(directory)
            source, executable = root / "test.cpp", root / "test"
            source.write_text(harness(CORE.read_text()))
            built = subprocess.run([os.environ.get("CXX", "clang++"), "-std=c++17",
                                    "-fsanitize=address,undefined", str(source), "-o", str(executable)],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            for which in range(3):
                for owns in (False, True):
                    with self.subTest(branch=which, local_process=owns):
                        result = subprocess.run([str(executable), str(which), str(int(owns))],
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_success_hands_ownership_to_applet_manager_before_return(self):
        source = CORE.read_text()
        load = source[source.index("SystemResultStatus Load("):
                      source.index("void ShutdownMainProcess()")]
        self.assertIn("CreateAndInsertByFrontendAppletParameters(std::move(process), params)", load)
        success = load[load.index("// Waiting for GPU before initializing CPU"):]
        self.assertNotIn("process.reset()", success)

    def test_canonical_patch_round_trips_without_changing_other_edits(self):
        patch = ROOT / "engines/patches/eden-process-load-unwind.patch"
        original = CORE.read_bytes()
        with tempfile.TemporaryDirectory(prefix="eden-load-patch-") as directory:
            target = Path(directory) / "src/core/core.cpp"
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            for direction in (["--reverse"], []):
                result = subprocess.run(
                    ["git", "-C", directory, "apply", *direction, str(patch)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(original, target.read_bytes())


if __name__ == "__main__":
    unittest.main()
