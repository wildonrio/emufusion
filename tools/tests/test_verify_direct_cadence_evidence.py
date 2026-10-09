import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "unified-android" / "tools" / "verify_direct_cadence_evidence.py"
SPEC = importlib.util.spec_from_file_location("verify_direct_cadence_evidence", SCRIPT)
verify_direct = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = verify_direct
SPEC.loader.exec_module(verify_direct)


def clock_line():
    return (
        "Display-synchronized core clock engine=mgba system=gba "
        "declaredHz=59.727500 synchronizedHz=60.000000 panelHz=60 "
        "uniform=true\n"
    )


def runtime_line(window=0, *, busy=0, failures=0, pool=0, direct=60.0):
    return (
        "Runtime telemetry engine=mgba system=gba frames=300 elapsedMs=5000 "
        "measuredFps=60.000 targetFps=60.000 audioFrames=163840 "
        "audioStarted=true audioHead=1000 audioProducedFrames=163840 "
        "audioWrittenFrames=163840 audioDroppedFrames=0 "
        "audioFocusDroppedFrames=0 audioQueuedFrames=0 audioPartialWrites=0 "
        "audioZeroWrites=0 audioWriteErrors=0 audioNativeDrainBoundHits=0 "
        "audioUnderruns=0 directMailboxOffers=300 "
        f"directMailboxBusyDrops={busy} directPresentAttempts=300 "
        f"directPresentSuccesses={300 - failures} directPresentFailures={failures} "
        f"directPresentFps={direct:.3f} videoBufferAllocations=3 "
        f"videoPoolExhaustions={pool}\n"
    )


def latency(intervals=700, *, bad_index=None):
    timestamp = 1_000_000_000
    rows = []
    for index in range(intervals + 1):
        rows.append(f"{timestamp - 1} {timestamp} {timestamp + 1}")
        timestamp += 33_333_334 if index == bad_index else 16_666_667
    return "\n".join(rows)


class VerifyDirectCadenceEvidenceTest(unittest.TestCase):
    def good_log(self):
        return clock_line() + "".join(runtime_line(index) for index in range(12))

    def test_accepts_sustained_exact_gba_correction(self):
        result = verify_direct.verify(self.good_log(), latency(), "mgba", "gba")
        self.assertAlmostEqual(result.synchronized_hz, 60.0)
        self.assertAlmostEqual(result.correction_percent, 0.45624, places=4)
        self.assertEqual(result.surface_interval_min_ns, 16_666_667)
        self.assertEqual(result.surface_interval_max_ns, 16_666_667)

    def test_rejects_one_periodic_surface_hitch_despite_a_perfect_average_log(self):
        with self.assertRaisesRegex(ValueError, "long/short hold"):
            verify_direct.verify(
                self.good_log(), latency(bad_index=650), "mgba", "gba"
            )

    def test_ignores_pending_surfaceflinger_int64_sentinel(self):
        rows = latency().splitlines()
        rows.insert(350, f"0 {(1 << 63) - 1} 0")
        result = verify_direct.verify(
            self.good_log(), "\n".join(rows), "mgba", "gba"
        )
        self.assertEqual(result.surface_interval_min_ns, 16_666_667)
        self.assertEqual(result.surface_interval_max_ns, 16_666_667)

    def test_rejects_video_pool_or_direct_presentation_loss(self):
        bad_pool = clock_line() + "".join(
            runtime_line(index, pool=1 if index == 11 else 0)
            for index in range(12)
        )
        with self.assertRaisesRegex(ValueError, "video pool"):
            verify_direct.verify(bad_pool, latency(), "mgba", "gba")
        bad_present = clock_line() + "".join(
            runtime_line(index, failures=1 if index == 11 else 0)
            for index in range(12)
        )
        with self.assertRaisesRegex(ValueError, "direct video frame"):
            verify_direct.verify(bad_present, latency(), "mgba", "gba")

    def test_rejects_nonuniform_or_overcorrected_source(self):
        nonuniform = clock_line().replace("uniform=true", "uniform=false")
        with self.assertRaisesRegex(ValueError, "not uniform"):
            verify_direct.verify(
                nonuniform + "".join(runtime_line() for _ in range(12)),
                latency(), "mgba", "gba",
            )


if __name__ == "__main__":
    unittest.main()
