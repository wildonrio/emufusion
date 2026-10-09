import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
TIMING = ROOT / "engines/build/switch-src/eden/src/core/core_timing.cpp"
TIMING_TEST = ROOT / "engines/build/switch-src/eden/src/tests/core/core_timing.cpp"
LOCK = ROOT / "engines/eden-source-lock.json"
SOAK = ROOT / "tools/verify_eden_switch_soak.py"
sys.path.insert(0, str(ROOT / "tools"))
import verify_eden_switch_soak as soak


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace:index + 1]
    raise AssertionError(f"unterminated function {signature}")


class EdenCoreTimingRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TIMING.read_text(encoding="utf-8")
        cls.tests = TIMING_TEST.read_text(encoding="utf-8")
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cls.soak = SOAK.read_text(encoding="utf-8")

    def test_event_does_not_persist_a_self_handle(self):
        event = re.search(r"struct CoreTiming::Event \{(.*?)\n\};", self.source, re.S)
        self.assertIsNotNone(event)
        self.assertNotIn("handle", event.group(1))
        unschedule = function_body(self.source, "void CoreTiming::UnscheduleEvent")
        self.assertIn("heap_t::s_handle_from_iterator(itr)", unschedule)
        self.assertNotIn("itr->handle", unschedule)

    def test_advance_owns_no_queue_node_across_the_callback_unlock(self):
        advance = function_body(self.source, "std::optional<s64> CoreTiming::Advance")
        self.assertNotIn("const Event& evt", advance)
        copy = advance.index("const Event evt = event_queue.top();")
        pop = advance.index("event_queue.pop();")
        unlock = advance.index("basic_lock.unlock();")
        callback = advance.index("event_type->callback(")
        self.assertLess(copy, pop)
        self.assertLess(pop, unlock)
        self.assertLess(unlock, callback)
        self.assertNotIn("event_queue.update", advance)

    def test_loop_rearm_remains_cancellation_guarded(self):
        advance = function_body(self.source, "std::optional<s64> CoreTiming::Advance")
        guard = "evt_sequence_num == event_type->sequence_number"
        self.assertIn(guard, advance)
        self.assertLess(advance.index(guard), advance.rindex("event_queue.emplace"))

    def test_expired_due_event_is_popped_before_weak_lock(self):
        advance = function_body(self.source, "std::optional<s64> CoreTiming::Advance")
        self.assertLess(advance.index("event_queue.pop();"),
                        advance.index("evt.type.lock()"))

    def test_deterministic_native_regressions_are_present(self):
        self.assertIn("CoreTiming[LoopingEventConcurrentUnschedule]", self.tests)
        self.assertIn("UnscheduleEventType::NoWait", self.tests)
        self.assertIn("gate.wait_for", self.tests)
        self.assertIn("CoreTiming[UnscheduleRemovesEveryQueuedInstance]", self.tests)
        self.assertIn("CoreTiming[ExpiredEventIsConsumed]", self.tests)

    def test_source_lock_pins_the_exact_timing_source(self):
        rows = [row for row in self.lock["patches"]
                if row.get("path") == "src/core/core_timing.cpp"]
        self.assertEqual(1, len(rows))
        self.assertEqual(hashlib.sha256(TIMING.read_bytes()).hexdigest(), rows[0]["sha256"])

    def test_soak_is_observation_only_and_has_all_hard_gates(self):
        for forbidden in ("shell input", "sendevent", "monkey", "am start", "force-stop"):
            self.assertNotIn(forbidden, self.soak)
        for required in ("one_pid", "averageGameFps", "assert_foreground", "screencap",
                         "gameplayProofSsim", "previousFramePsnr", "CRASH_RE"):
            self.assertIn(required, self.soak)
        self.assertIn("formal runs must be at least 600 seconds", self.soak)
        self.assertIn("exactly three result.json files are required", self.soak)
        self.assertIn('"referenceSha256"', self.soak)
        self.assertIn('"approvedBy"', self.soak)

    def test_soak_crash_matcher_covers_engine_native_and_contention_failures(self):
        for line in (
                "Fatal signal 11 (SIGSEGV)",
                "CoreTiming::Advance fibonacci_heap::consolidate",
                "ActivityManager: Killing 1234:com.thorium.preview",
                "PackageManager: installPackageLI started"):
            self.assertIsNotNone(soak.CRASH_RE.search(line), line)

    def test_three_run_aggregator_rejects_a_short_or_failed_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = []
            for index in range(3):
                record = {
                    "status": "PASS", "formal": True,
                    "durationObservedSeconds": 600.1,
                    "gameId": "known-game", "adapterSha256": "a" * 64,
                    "runId": f"run-{index}", "startedEpochSeconds": index * 700,
                }
                path = root / f"result-{index}.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                results.append(path)
            output = root / "series.json"
            arguments = SimpleNamespace(results=results, output=output)
            self.assertEqual(0, soak.verify_series(arguments))
            self.assertEqual("PASS", json.loads(output.read_text())["status"])

            short = json.loads(results[1].read_text())
            short["durationObservedSeconds"] = 599.9
            results[1].write_text(json.dumps(short), encoding="utf-8")
            with self.assertRaises(soak.GateFailure):
                soak.verify_series(arguments)


if __name__ == "__main__":
    unittest.main()
