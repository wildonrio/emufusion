import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "unified-android/tools/run_strict_off_cadence_probe.py"
SPEC = importlib.util.spec_from_file_location("strict_off_probe", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StrictOffCadenceProbeTest(unittest.TestCase):
    @staticmethod
    def cadence_case(slots, panel_hz=120):
        log = "\n".join([
            "Requested native gameplay panel mode display=0 modeId=2 refreshHz=120",
            "In-window route accepted engine=mesen-s system=snes",
            "Frame generation Off; engine owns the display Surface directly "
            "surfaceIdentity=true rendererCreated=0 liveRenderers=0",
            "Display-synchronized core clock engine=mesen-s system=snes "
            "declaredHz=60.098 synchronizedHz=60 panelHz=120 uniform=true",
        ] + [
            "Health engine=mesen-s fps=60 frames={n} audioUnderruns=0 "
            "audioReceived=1 audioWritten=1 audioDropped=0 audioRate=48000 "
            "audioStarted=true audioHead={n}".format(n=n)
            for n in (300, 600, 900, 1200)
        ])
        blocks = []
        period = round(1e9 / panel_hz)
        for window in range(4):
            stamp = 1_000_000_000 + window * 10_000_000_000
            rows = [str(period), f"{stamp} {stamp} {stamp}"]
            for i in range(110):
                stamp += slots[i % len(slots)] * period
                rows.append(f"{stamp} {stamp} {stamp}")
            blocks.append("\n".join(rows))
        return log, "\n---capture---\n".join(blocks)

    def test_uniform_two_scan_holds_pass_explicit_sixty_target(self):
        log, latency = self.cadence_case([2])
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=60)
        self.assertTrue(result["pass"], result["errors"])
        self.assertEqual(2, result["expectedHoldSlots"])

    def test_later_live_renderer_cannot_hide_behind_initial_bypass(self):
        log, latency = self.cadence_case([2])
        log += ("\nFrame generation Off; engine owns the display Surface directly "
                "surfaceIdentity=true rendererCreated=1 liveRenderers=1")
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=60)
        self.assertFalse(result["pass"], result)

    def test_nonzero_live_count_prefix_cannot_match_zero(self):
        log, latency = self.cadence_case([2])
        log = log.replace("liveRenderers=0", "liveRenderers=01")
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=60)
        self.assertFalse(result["pass"], result)

    def test_alternating_one_three_scans_is_judder_despite_sixty_average(self):
        log, latency = self.cadence_case([1, 3])
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=60)
        self.assertFalse(result["pass"])
        self.assertIn("uneven or incorrect physical frame holds", result["errors"])

    def test_uniform_wrong_rate_fails(self):
        log, latency = self.cadence_case([4])
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=60)
        self.assertFalse(result["pass"])

    def test_eighty_target_cannot_be_uniform_on_one_twenty(self):
        log, latency = self.cadence_case([1, 2])
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=80)
        self.assertIn("presentation target does not divide physical refresh", result["errors"])

    def test_rounded_sixty_period_accepts_one_scan_target(self):
        log, latency = self.cadence_case([1], panel_hz=60)
        log = log.replace("refreshHz=120", "refreshHz=60").replace("panelHz=120", "panelHz=60")
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=60)
        self.assertTrue(result["pass"], result["errors"])

    def test_refresh_header_not_requested_mode_is_authoritative(self):
        log, latency = self.cadence_case([2], panel_hz=60)
        result = MODULE.analyze(log, latency, "mesen-s", "snes", expected_present_hz=60)
        self.assertFalse(result["pass"])
        self.assertIn("observed refresh period differs from requested panel mode", result["errors"])

    def test_guest_clock_cannot_substitute_for_presentation_target(self):
        log, latency = self.cadence_case([2])
        result = MODULE.analyze(log, latency, "mesen-s", "snes")
        self.assertFalse(result["pass"])
        self.assertIn("missing independently established presentation target", result["errors"])

    def test_actual_timestamps_deduplicate_rolling_latency_captures(self):
        self.assertEqual(
            MODULE.actual_timestamps("1 2 3\n1 2 3\n3 4 5\n0 9223372036854775807 0"),
            [2, 4],
        )

    def test_latency_windows_do_not_create_cross_capture_holds(self):
        text = "1 2 3\n3 4 5\n---capture---\n101 102 103\n103 104 105"
        self.assertEqual(MODULE.actual_timestamp_windows(text), [[2, 4], [102, 104]])

    def test_fifty_hz_is_not_an_allowed_tier(self):
        self.assertNotEqual(MODULE.nearest_allowed(50.0), 50.0)

    def test_missing_source_clock_can_never_be_certified(self):
        result = MODULE.analyze("", "", "cemu", "wiiu", minimum_presents=1)
        self.assertIn("missing measured engine source clock", result["errors"])

    def test_native_engine_owned_fps_satisfies_source_measurement(self):
        log = "\n".join(
            f"engine speed engine=eden system=switch averageGameFps={fps}"
            for fps in (59.9, 60.0, 60.1, 60.0)
        )
        result = MODULE.analyze(log, "", "eden", "switch", minimum_presents=1)
        self.assertNotIn("missing measured engine source clock", result["errors"])
        self.assertEqual(60.0, result["observedEngineHz"])

    def test_scan_lattice_accepts_intentional_duplicate_slots(self):
        base = 16_666_667
        block = "\n".join(
            f"{index} {1_000_000_000 + sum((base, base * 2)[value % 2] for value in range(index))} {index}"
            for index in range(110)
        )
        latency = "\n---capture---\n".join([block] * 4)
        # The full analyzer has additional log contracts; this fixture asserts
        # that the timestamp parser retains both one- and two-scan intervals.
        intervals = [second - first for first, second in zip(
            MODULE.actual_timestamp_windows(latency)[0],
            MODULE.actual_timestamp_windows(latency)[0][1:])]
        self.assertIn(base, intervals)
        self.assertIn(base * 2, intervals)

    def test_rolling_health_fps_excludes_cold_start_dilution(self):
        log = "\n".join([
            "Health engine=azahar fps=58.54 frames=300 audioUnderruns=0 "
            "audioReceived=1 audioWritten=1 audioDropped=0 audioRate=48000 "
            "audioStarted=true audioHead=1",
            "Health engine=azahar fps=59.28 frames=600 audioUnderruns=0 "
            "audioReceived=1 audioWritten=1 audioDropped=0 audioRate=48000 "
            "audioStarted=true audioHead=2",
            "Health engine=azahar fps=59.21 frames=900 audioUnderruns=0 "
            "audioReceived=1 audioWritten=1 audioDropped=0 audioRate=48000 "
            "audioStarted=true audioHead=3",
            "Health engine=azahar fps=59.41 frames=1200 audioUnderruns=0 "
            "audioReceived=1 audioWritten=1 audioDropped=0 audioRate=48000 "
            "audioStarted=true audioHead=4",
        ])
        rates = MODULE.rolling_health_fps(list(MODULE.HEALTH.finditer(log)))
        self.assertEqual(len(rates), 3)
        self.assertTrue(all(58.9 < rate < 60.2 for rate in rates), rates)

    def test_audio_counter_only_fails_when_it_increases_in_sample(self):
        log = "\n".join(
            "Health engine=armsx2 fps=60 frames={frames} audioUnderruns=14 "
            "audioReceived=1 audioWritten=1 audioDropped=0 audioRate=48000 "
            "audioStarted=true audioHead={frames}".format(frames=frames)
            for frames in (300, 600, 900, 1200)
        )
        rows = list(MODULE.HEALTH.finditer(log))
        self.assertEqual(MODULE.health_counter_increases(rows, 4), [])


if __name__ == "__main__":
    unittest.main()
