"""Ordering rules that keep a Switch session's teardown from wedging or faulting.

Exiting a Switch game back to the library used to either hang forever with the
guest half torn down, or segfault inside Eden's guest-kernel finalisation
(KThread::Finalize -> KProcess::DeleteThreadLocalRegion ->
KLightLock::UnlockSlowPath -> KThread::EndWait, on CPUCore_3). Three ordering
rules fixed that, and all three are invisible at runtime until they are already
broken, so they are pinned here as source invariants.

1. ONE THREAD OWNS THE WHOLE SESSION. Eden's own Android frontend runs
   InitializeEmulation, RunEmulation and ShutdownEmulation as a single function
   body on a single thread (jni/native.cpp's static RunEmulation, with a
   SCOPE_EXIT for the shutdown). Every host thread that reaches into Eden's
   kernel is given a dummy KThread in KernelCore's thread_local storage, and
   that object is registered with the kernel by its constructor but only
   unregistered by a refcount drop -- so a host thread that exits leaves the
   kernel holding a pointer to a destroyed KThread. Joining the emulation
   thread and only then calling ShutdownEmulation from another thread destroys
   the identity that brought the guest kernel up and asks a stranger to tear it
   down.

2. SERVICES CLOSE BEFORE EMULATION SUSPENDS. Eden's HLE services are not host
   threads: they are guest KThreads pinned to guest core 3 by
   KernelCore::RunOnGuestCoreProcess. KernelCore::SuspendEmulation parks every
   thread of every process, and KernelCore::CloseServices then destroys the
   ServerManagers, whose destructor does an unbounded wait for the thread that
   was just parked. Suspending first is a deadlock by construction.

3. PER-PROCESS INITIALISERS RUN ONCE. Upstream calls initializeGpuDriver and
   initializeSystem(false) once, from YuzuApplication.onCreate, and passes
   reload = true everywhere after. InitializeSystem(false) re-runs
   InputSubsystem::Initialize, whose RegisterEngine replaces every input engine
   while HIDCore still holds devices built by the engines being dropped.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "engines" / "patches" / "eden-lucent-adapter.cpp"
EDEN_CORE = ROOT / "engines" / "build" / "switch-src" / "eden" / "src" / "core" / "core.cpp"


def _strip_comments(source: str) -> str:
    """Drop // and /* */ so a rule is never satisfied by prose about the rule."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def _body(source: str, signature: str) -> str:
    """The brace-balanced body of the function whose signature line matches."""
    start = source.index(signature)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("unterminated body for " + signature)


class AdapterOwnsOneSessionThread(unittest.TestCase):
    """Rule 1: bring-up, the run loop and teardown share one thread."""

    def setUp(self):
        self.source = _strip_comments(ADAPTER.read_text())

    def test_start_runs_initialize_run_and_shutdown_on_the_engine_thread(self):
        start = _body(self.source, "static bool adapter_start(")
        thread = start[start.index("std::thread"):]
        for call in ("InitializeEmulation", "RunEmulation", "ShutdownEmulation"):
            self.assertIn(
                call, thread,
                call + " must run on the engine thread, as upstream's "
                "RunEmulation() does, not on whichever thread Lucent calls from")
        self.assertLess(
            thread.index("InitializeEmulation"), thread.index("RunEmulation"),
            "the title has to be loaded before the loop runs")
        self.assertLess(
            thread.index("RunEmulation"), thread.index("ShutdownEmulation"),
            "teardown unwinds after the loop, like upstream's SCOPE_EXIT")

    def test_stop_only_signals_and_joins(self):
        stop = _body(self.source, "static void adapter_stop(")
        self.assertIn("HaltEmulation", stop)
        self.assertIn("join()", stop)
        started = stop[stop.index("engine->started.load()"):stop.index("else if")]
        self.assertNotIn(
            "ShutdownEmulation", started,
            "stop() must not tear the guest kernel down itself: the engine "
            "thread does that, and joining it is what proves it finished")
        self.assertLess(
            stop.index("HaltEmulation"), stop.index("join()"),
            "halt before join, or the join never returns")

    def test_stop_leaves_the_paused_state_before_halting(self):
        stop = _body(self.source, "static void adapter_stop(")
        self.assertIn(
            "UnPauseEmulation", stop,
            "Lucent pauses twice on the way out; ShutdownMainProcess has to "
            "terminate those guest threads and wait for each one")
        self.assertLess(
            stop.index("UnPauseEmulation"), stop.index("HaltEmulation"),
            "unpause first, so teardown is handed a running guest")

    def test_never_started_session_still_releases_what_load_built(self):
        stop = _body(self.source, "static void adapter_stop(")
        self.assertIn("else if (engine->loaded.load())", stop)
        self.assertIn("ShutdownEmulation", stop.split("else if")[1])


class ServicesCloseBeforeEmulationSuspends(unittest.TestCase):
    """Rule 2: the vendored ShutdownMainProcess ordering."""

    def test_close_services_precedes_suspend_emulation(self):
        if not EDEN_CORE.is_file():
            self.skipTest("vendored Eden tree is not present in this checkout")
        body = _body(_strip_comments(EDEN_CORE.read_text()),
                     "void ShutdownMainProcess()")
        close = body.index("kernel.CloseServices()")
        suspend = body.index("kernel.SuspendEmulation(true)")
        self.assertLess(
            close, suspend,
            "CloseServices waits for guest service threads on core 3; "
            "SuspendEmulation parks them. Suspending first deadlocks the exit.")
        self.assertLess(
            suspend, body.index("kernel.ShutdownCores()"),
            "cores still shut down after the guest is parked")


class PerProcessInitialisersRunOnce(unittest.TestCase):
    """Rule 3: once-per-process work is not repeated per title."""

    def setUp(self):
        self.load = _body(_strip_comments(ADAPTER.read_text()),
                          "static bool adapter_load(")

    def test_gpu_driver_is_resolved_once_per_process(self):
        self.assertIn("first_session", self.load)
        guard = self.load.index("if (first_session)")
        self.assertLess(
            guard, self.load.index("InitializeGpuDriver"),
            "re-opening the Vulkan driver replaces the library the previous "
            "render window was built against")

    def test_initialize_system_reloads_after_the_first_title(self):
        self.assertIn(
            "InitializeSystem(!first_session)", self.load,
            "InitializeSystem(false) re-runs InputSubsystem::Initialize, which "
            "replaces every input engine under a live HIDCore")
        self.assertNotIn("InitializeSystem(false)", self.load)


if __name__ == "__main__":
    unittest.main()
