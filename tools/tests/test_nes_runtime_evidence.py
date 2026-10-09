import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "unified-android" / "tools" / "verify_nes_runtime_evidence.py"
SPEC = importlib.util.spec_from_file_location("nes_runtime_evidence", VERIFIER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NesRuntimeEvidenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def frame(self, name, interior=(24, 76, 190), border=(240, 240, 240),
              sprite_x=700, marker_y=None):
        path = self.root / name
        image = Image.new("RGB", (1920, 1080), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((240, 0, 1679, 1079), fill=interior)
        draw.rectangle((240, 0, 1679, 35), fill=border)
        draw.rectangle((240, 1044, 1679, 1079), fill=border)
        draw.rectangle((240, 0, 284, 1079), fill=border)
        draw.rectangle((1635, 0, 1679, 1079), fill=border)
        draw.rectangle((sprite_x, 500, sprite_x + 40, 540), fill=(255, 255, 0))
        if marker_y is not None:
            x0 = 240 + round(24 * 5.625)
            y0 = round((marker_y + 1) * 4.5)
            marker = (190, 20, 190)
            draw.rectangle((x0 + 17, y0, x0 + 27, y0 + 35), fill=marker)
            draw.rectangle((x0, y0 + 13, x0 + 44, y0 + 22), fill=marker)
        image.save(path)
        return path

    def test_geometry_requires_full_height_centered_four_three(self):
        valid = self.frame("valid.png")
        report = MODULE.analyze_geometry(valid)
        self.assertTrue(report["fullHeight"])
        self.assertEqual(report["activeLeft"], 240)
        self.assertEqual(report["activeWidth"], 1440)
        letterboxed = Image.open(valid).convert("RGB")
        ImageDraw.Draw(letterboxed).rectangle((0, 0, 1919, 30), fill="black")
        bad = self.root / "letterboxed.png"
        letterboxed.save(bad)
        with self.assertRaisesRegex(ValueError, "vertical edges"):
            MODULE.analyze_geometry(bad)

    def test_launch_video_requires_pre_input_menu_and_guest_within_500ms(self):
        menu = self.root / "menu.bin"
        guest = self.root / "guest.bin"
        other = self.root / "other.bin"
        for path in (menu, guest, other):
            path.write_bytes(path.name.encode())
        origin = 5_000_000_000
        frames = [
            MODULE.TimedImage(0, origin - 30_000_000, menu),
            MODULE.TimedImage(1, origin + 20_000_000, other),
            MODULE.TimedImage(2, origin + 480_000_000, guest),
            MODULE.TimedImage(3, origin + 520_000_000, guest),
        ]
        # The 460ms middle gap correctly fails the continuity gate.
        with self.assertRaisesRegex(ValueError, "too sparse"):
            MODULE.evaluate_launch_video(
                frames, origin, lambda path: path == menu, lambda path: path == guest
            )
        frames = [MODULE.TimedImage(index, origin - 30_000_000 + index * 50_000_000,
                                    guest if index >= 7 else menu if index == 0 else other)
                  for index in range(12)]
        report = MODULE.evaluate_launch_video(
            frames, origin, lambda path: path == menu, lambda path: path == guest
        )
        self.assertEqual(report["visibleLatencyUpperBoundMs"], 320)
        self.assertTrue(report["preInputMenuFrame"])

    def test_controls_require_eight_unique_material_colours(self):
        neutral = self.frame("neutral.png")
        colours = tuple(MODULE.CONTROL_DISTINCT_TEST_RGB[name]
                        for name in MODULE.CONTROL_NAMES)
        paths = {name: self.frame(
            f"{name}.png", interior=colour,
            marker_y=MODULE.CONTROL_MARKER_SOURCE_Y[name])
            for name, colour in zip(MODULE.CONTROL_NAMES, colours)}
        self.assertTrue(MODULE.analyze_controls(neutral, paths)["allUnique"])
        paths["B"] = paths["A"]
        with self.assertRaisesRegex(ValueError, "A/B"):
            MODULE.analyze_controls(neutral, paths)
        paths = {name: self.frame(f"mapped-{name}.png", interior=colour,
                                 marker_y=MODULE.CONTROL_MARKER_SOURCE_Y[name])
                 for name, colour in zip(MODULE.CONTROL_NAMES, colours)}
        paths["A"], paths["B"] = paths["B"], paths["A"]
        with self.assertRaisesRegex(ValueError, "physical A did not render.*observed=B"):
            MODULE.analyze_controls(neutral, paths)

    def test_control_identity_is_marker_y_not_palette_mean(self):
        neutral = self.frame("marker-neutral.png")
        arbitrary = {
            name: (70 + index * 20, 70 + index * 20, 70 + index * 20)
            for index, name in enumerate(MODULE.CONTROL_NAMES)
        }
        correct = {name: self.frame(
            f"arbitrary-{name}.png", interior=arbitrary[name],
            marker_y=MODULE.CONTROL_MARKER_SOURCE_Y[name]
        ) for name in MODULE.CONTROL_NAMES}
        self.assertTrue(MODULE.analyze_controls(neutral, correct)["allUnique"])
        permuted = dict(correct)
        permuted["A"], permuted["B"] = permuted["B"], permuted["A"]
        with self.assertRaisesRegex(
                ValueError, "physical A did not render.*observed=B"):
            MODULE.analyze_controls(neutral, permuted)

    def test_motion_is_real_but_not_a_crossfade(self):
        first = self.frame("motion-1.png", sprite_x=700)
        second = self.frame("motion-2.png", sprite_x=760)
        report = MODULE.analyze_motion(first, second, 250)
        self.assertGreater(report["changedPixels"], 100)
        with self.assertRaisesRegex(ValueError, "less than 200"):
            MODULE.analyze_motion(first, second, 100)
        dissolve = self.frame("motion-dissolve.png", interior=(220, 180, 10))
        with self.assertRaisesRegex(ValueError, "authored horizontal scroll"):
            MODULE.analyze_motion(first, dissolve, 250)

    def test_resume_requires_exact_frozen_pixels_and_restore_marker(self):
        before = self.frame("before.png", sprite_x=803)
        after = self.frame("after.png", sprite_x=803)
        chronology = (
            "Quick Resume committed engine=mesen system=nes\n"
            "Quick Resume restored engine=mesen system=nes\n"
            "Quick Resume committed engine=mesen system=nes\n"
            "Quick Resume restored engine=mesen system=nes\n"
            "Quick Resume committed engine=mesen system=nes\n"
        )
        report = MODULE.analyze_resume(before, after, chronology)
        self.assertTrue(report["exactFrozenStateRestored"])
        changed = self.frame("changed.png", sprite_x=820)
        with self.assertRaisesRegex(ValueError, "exact frozen"):
            MODULE.analyze_resume(before, changed, chronology)

    def test_device_clock_input_rejects_summary_text_without_raw_edges(self):
        path = self.root / "not-raw-input.txt"
        path.write_text("launch passed at 5 seconds\n", encoding="utf-8")
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            MODULE.analyze_device_clock_input(
                path, action="launch-a", key_code=304,
                expected_node="/dev/input/event9",
            )

    def test_tier_schedule_requires_ordered_physical_chords(self):
        schedule = self.root / "schedule.json"
        tiers = [60, 50, 40, 30, 40, 50, 60]
        combos = {60: "Select+Up", 50: "Select+Right",
                  40: "Select+Down", 30: "Select+Left"}
        schedule.write_text(json.dumps({
            "schemaVersion": 1, "tiers": tiers,
            "directSelections": [
                {"tier": tier, "combo": combos[tier],
                 "hostStartNs": 1_000 + index * 1_000,
                 "hostEndNs": 1_500 + index * 1_000,
                 "deviceStartMonotonicNs": 1_000_000_000 + index * 1_000_000_000,
                 "deviceEndMonotonicNs": 1_250_000_000 + index * 1_000_000_000,
                 "physicalEventNode": "/dev/input/event9"}
                for index, tier in enumerate(tiers)
            ],
            "proofResets": [
                {"tier": tier, "pid": 1234, "generator": 7,
                 "disabledLineIndex": 100 + index * 2,
                 "enabledLineIndex": 101 + index * 2,
                 "baselineWindowEndNs":
                     2_000_000_000 + index * 30_000_000_000}
                for index, tier in enumerate(tiers)
            ],
            "source": "physical Odin Controller Select+direction",
            "noClockOverride": True,
        }), encoding="utf-8")
        ordered_lines = []
        expected_axes = {60: (17, -1), 50: (16, 1),
                         40: (17, 1), 30: (16, -1)}
        for index, tier in enumerate(tiers):
            axis, value = expected_axes[tier]
            encoded = value & 0xFFFFFFFF
            start = 1.0 + index
            ordered_lines.extend((
                f"[ {start:.6f}] 0003 {axis:04x} {encoded:08x}",
                f"[ {start + 0.1:.6f}] 0001 013a 00000001",
                f"[ {start + 0.2:.6f}] 0001 013a 00000000",
                f"[ {start + 0.25:.6f}] 0003 {axis:04x} 00000000",
            ))
        accepted = MODULE.analyze_tier_input_schedule(
            schedule, "\n".join(ordered_lines), "/dev/input/event9"
        )
        self.assertEqual(accepted["directSelections"], 7)
        self.assertEqual(accepted["selections"][0]["combo"], "Select+Up")

        stale_r23 = json.loads(schedule.read_text(encoding="utf-8"))
        stale_r23.pop("proofResets")
        schedule.write_text(json.dumps(stale_r23), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected schema"):
            MODULE.analyze_tier_input_schedule(
                schedule, "\n".join(ordered_lines), "/dev/input/event9"
            )
        stale_r23["proofResets"] = accepted["proofResets"]
        schedule.write_text(json.dumps(stale_r23), encoding="utf-8")

        missing_initial = json.loads(schedule.read_text(encoding="utf-8"))
        missing_initial["directSelections"] = missing_initial["directSelections"][1:]
        schedule.write_text(json.dumps(missing_initial), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "seven direct selections"):
            MODULE.analyze_tier_input_schedule(
                schedule, "\n".join(ordered_lines), "/dev/input/event9"
            )
        schedule.write_text(json.dumps({
            **missing_initial,
            "directSelections": [
                {"tier": tier, "combo": combos[tier],
                 "hostStartNs": 1_000 + index * 1_000,
                 "hostEndNs": 1_500 + index * 1_000,
                 "deviceStartMonotonicNs":
                     1_000_000_000 + index * 1_000_000_000,
                 "deviceEndMonotonicNs":
                     1_250_000_000 + index * 1_000_000_000,
                 "physicalEventNode": "/dev/input/event9"}
                for index, tier in enumerate(tiers)
            ],
        }), encoding="utf-8")
        # Balanced aggregate counts in the wrong order are not qualification.
        unrelated = (
            "0003 0011 ffffffff\n0001 013a 00000001\n"
            "0001 013a 00000000\n0003 0011 00000000\n"
        ) * 7
        with self.assertRaisesRegex(
                ValueError, "ordered direct tier chord|monotonic bounds"):
            MODULE.analyze_tier_input_schedule(
                schedule, unrelated, "/dev/input/event9"
            )

    def test_seven_reset_campaign_binds_each_zero_health_baseline(self):
        tiers = [60, 50, 40, 30, 40, 50, 60]
        resets = [{"tier": tier, "pid": 1234, "generator": 7,
                   "disabledLineIndex": index * 3,
                   "enabledLineIndex": index * 3 + 1,
                   "baselineWindowEndNs": (index + 1) * 1_000_000_000}
                  for index, tier in enumerate(tiers)]
        events = []
        for reset in resets:
            for enabled, key in ((False, "disabledLineIndex"),
                                 (True, "enabledLineIndex")):
                events.append({"lineIndex": reset[key], "pid": 1234,
                               "generator": 7, "enabled": enabled,
                               "proofContract": MODULE.frame_gen.PROOF_CONTRACT,
                               "proofSchemaVersion":
                                   MODULE.frame_gen.PROOF_SCHEMA_VERSION})

        class Health:
            def __init__(self, index):
                self.values = {key: "0" for key in
                               MODULE.frame_gen.HEALTH.groupindex}
                self.values.update({"generator": "7", "role": "primary",
                                    "display_id": "0",
                                    "proof_contract":
                                        MODULE.frame_gen.PROOF_CONTRACT,
                                    "window_end_ns":
                                        str((index + 1) * 1_000_000_000)})

            def groupdict(self):
                return dict(self.values)

        health_by_line = {index * 3 + 2: Health(index)
                          for index in range(7)}
        lines = [f"line-{index}" for index in range(21)]
        search = mock.Mock(side_effect=lambda line: health_by_line.get(
            int(line.split("-")[1])
        ))
        fake_health = mock.Mock(search=search)
        schedule = {"proofResets": resets}
        with mock.patch.object(MODULE.frame_gen,
                               "framegen_proof_state_events",
                               return_value=events), mock.patch.object(
                                   MODULE.frame_gen, "HEALTH", fake_health), \
                mock.patch.object(MODULE.frame_gen, "framegen_line_pid",
                                  return_value=1234):
            proof = MODULE.analyze_tier_proof_reset_log(
                schedule, "\n".join(lines), 1234
            )
        self.assertEqual(proof["resets"], 7)
        self.assertTrue(proof["allBaselinesZero"])

        bad_events = list(events)
        bad_events.insert(2, dict(events[1], lineIndex=2))
        with mock.patch.object(MODULE.frame_gen,
                               "framegen_proof_state_events",
                               return_value=bad_events), mock.patch.object(
                                   MODULE.frame_gen, "HEALTH", fake_health), \
                mock.patch.object(MODULE.frame_gen, "framegen_line_pid",
                                  return_value=1234):
            with self.assertRaisesRegex(ValueError, "missing/extra markers"):
                MODULE.analyze_tier_proof_reset_log(
                    schedule, "\n".join(lines), 1234
                )

        mixed = {"proofResets": [dict(reset) for reset in resets]}
        mixed["proofResets"][3]["pid"] = 9999
        with self.assertRaisesRegex(ValueError, "mix PID/generator"):
            MODULE.analyze_tier_proof_reset_log(
                mixed, "\n".join(lines), 1234
            )

        health_by_line[2].values["proof"] = "1"
        with mock.patch.object(MODULE.frame_gen,
                               "framegen_proof_state_events",
                               return_value=events), mock.patch.object(
                                   MODULE.frame_gen, "HEALTH", fake_health), \
                mock.patch.object(MODULE.frame_gen, "framegen_line_pid",
                                  return_value=1234):
            with self.assertRaisesRegex(ValueError, "baseline counters are nonzero"):
                MODULE.analyze_tier_proof_reset_log(
                    schedule, "\n".join(lines), 1234
                )

    def test_video_only_geometry_and_motion_accept_exact_half_scale(self):
        full_a = self.frame("video-full-a.png", sprite_x=700)
        full_b = self.frame("video-full-b.png", sprite_x=760)
        half_a = self.root / "video-half-a.png"
        half_b = self.root / "video-half-b.png"
        Image.open(full_a).resize((960, 540), Image.Resampling.NEAREST).save(half_a)
        Image.open(full_b).resize((960, 540), Image.Resampling.NEAREST).save(half_b)
        self.assertTrue(MODULE.analyze_geometry(
            half_a, allow_video_scale=True
        )["fullHeight"])
        self.assertTrue(MODULE.analyze_motion(
            half_a, half_b, 250, allow_video_scale=True
        )["continuousMotion"])
        with self.assertRaisesRegex(ValueError, "requires 1920x1080"):
            MODULE.analyze_geometry(half_a)

    def test_video_binding_rejects_non_mp4_and_timestamp_splice(self):
        frame = self.frame("bound-video-frame.png")
        non_mp4 = self.root / "not-video.mp4"
        non_mp4.write_text("not a video", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not an MP4"):
            MODULE.verify_video_frame_binding(
                non_mp4, [MODULE.TimedImage(0, 1, frame)], 1, launch=True
            )
        container = self.root / "fake-container.mp4"
        container.write_bytes(b"\x00\x00\x00\x18ftyp" + b"\x00" * 80)
        with mock.patch.object(
                MODULE.return_video, "parse_winscope_frame_timestamps",
                return_value=[1_000_000_000, 1_050_000_000]):
            with self.assertRaisesRegex(ValueError, "index/timestamps"):
                MODULE.verify_video_frame_binding(
                    container, [MODULE.TimedImage(0, 123, frame)],
                    1_000_000_000, launch=True,
                )

    def test_panel_summary_cannot_replace_pixel_ocr(self):
        panel = self.frame("unrelated-panel.png", interior=(70, 70, 80))
        completed = mock.Mock(returncode=0, stdout="Completely unrelated panel")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(ValueError, "pixels lack"):
                MODULE.analyze_cheat_panel(
                    panel,
                    "Cheats panel shown engine=mesen system=nes count=1 lowerDisplay=true",
                )

    def test_r26_tight_panel_row_ocr_accepts_selected_off(self):
        panel = self.root / "r26-panel.png"
        image = Image.new("RGB", (1240, 1080), (2, 4, 8))
        ImageDraw.Draw(image).rectangle((45, 240, 729, 329),
                                        fill=(146, 120, 247))
        image.save(panel)
        completed = (
            mock.Mock(returncode=0, stdout="Lucent Callback Test CHEATS"),
            mock.Mock(returncode=0,
                      stdout="Qualification red border * OFF"),
        )
        with mock.patch.object(MODULE.subprocess, "run", side_effect=completed):
            result = MODULE.analyze_cheat_panel(
                panel,
                "Cheats panel shown engine=mesen system=nes count=1 lowerDisplay=true",
            )
        self.assertEqual(result["rowLogicalBox"], [70, 240, 1130, 330])
        self.assertEqual(result["initialState"], "OFF")
        self.assertTrue(result["selected"])

    def test_tight_panel_row_rejects_blank_wrong_on_unselected_and_offset(self):
        marker = "Cheats panel shown engine=mesen system=nes count=1 lowerDisplay=true"
        for case, row_text, selected_box in (
                ("blank", "Qualification red border OFF", None),
                ("wrong", "Different cheat OFF", (45, 240, 729, 329)),
                ("on", "Qualification red border ON", (45, 240, 729, 329)),
                ("unselected", "Qualification red border OFF", (45, 60, 400, 120)),
                ("offset", "Qualification red border OFF", (45, 350, 729, 439))):
            with self.subTest(case=case):
                panel = self.root / f"panel-{case}.png"
                image = Image.new(
                    "RGB", (1240, 1080),
                    (0, 0, 0) if case == "blank" else (2, 4, 8),
                )
                if selected_box is not None:
                    ImageDraw.Draw(image).rectangle(
                        selected_box, fill=(146, 120, 247)
                    )
                image.save(panel)
                completed = (
                    mock.Mock(returncode=0,
                              stdout="Lucent Callback Test CHEATS"),
                    mock.Mock(returncode=0, stdout=row_text),
                )
                with mock.patch.object(MODULE.subprocess, "run",
                                       side_effect=completed), \
                        self.assertRaises(ValueError):
                    MODULE.analyze_cheat_panel(panel, marker)

    def test_cheat_rejects_wrong_catalog_row_marker(self):
        before = self.frame("wrong-cheat-before.png", border=(240, 240, 240))
        enabled = self.frame("wrong-cheat-enabled.png", border=(200, 20, 30))
        disabled = self.frame("wrong-cheat-disabled.png", border=(240, 240, 240))
        log = (
            "Cheat apply returned engine=mesen system=nes id=wrong "
            "enabled=true callbackReturned=true acknowledged=false "
            "effectProofRequired=true marker=cheat-apply-returned\n"
            "Cheat apply returned engine=mesen system=nes id=wrong "
            "enabled=false callbackReturned=true acknowledged=false "
            "effectProofRequired=true marker=cheat-apply-returned\n"
        )
        with self.assertRaisesRegex(ValueError, "exact live enable marker"):
            MODULE.analyze_cheat(before, enabled, disabled, log)

    def test_audio_requires_clean_full_speed_consumed_pcm(self):
        valid = (
            "Runtime telemetry engine=mesen system=nes frames=120 elapsedMs=1990 "
            "measuredFps=60.302 targetFps=60.099 audioFrames=88200 "
            "audioStarted=true audioHead=93500 audioProducedFrames=88200 "
            "audioWrittenFrames=88200 audioDroppedFrames=0 "
            "audioFocusDroppedFrames=0 audioQueuedFrames=800 "
            "audioPartialWrites=0 audioZeroWrites=0 audioWriteErrors=0 "
            "audioNativeDrainBoundHits=0 audioUnderruns=0"
            "\nPCM signal telemetry engine=mesen system=nes "
            "audioSignalBoundary=pre-AudioTrack audioSignalAudibilityProven=false "
            "audioSignalSampleRateHz=48000 audioSignalWindowFrames=8192 "
            "audioSignalWindowSamples=16384 audioSignalWindowFrequencyResolutionHz=5.860090 "
            "audioSignalWindowOverflow=false audioSignalWindowLeftMin=-12000 "
            "audioSignalWindowLeftMax=12000 audioSignalWindowLeftPeak=12000 "
            "audioSignalWindowLeftRms=8000.0 audioSignalWindowLeftToneHz=440.4 "
            "audioSignalWindowLeftCrossings=75 audioSignalWindowRightMin=-12000 "
            "audioSignalWindowRightMax=12000 audioSignalWindowRightPeak=12000 "
            "audioSignalWindowRightRms=8000.0 audioSignalWindowRightToneHz=440.4 "
            "audioSignalWindowRightCrossings=75 marker=audio-pcm-signal"
        )
        self.assertEqual(MODULE.analyze_audio(valid)["audioFrames"], 88200)
        with self.assertRaisesRegex(ValueError, "source/sink pipeline"):
            MODULE.analyze_audio(valid.replace("audioUnderruns=0", "audioUnderruns=1"))

    def test_cheat_requires_pixels_and_exact_returned_marker(self):
        before = self.frame("cheat-before.png", border=(240, 240, 240))
        after = self.frame("cheat-after.png", border=(200, 20, 30))
        disabled = self.frame("cheat-disabled.png", border=(240, 240, 240))
        log = (
            "Cheat apply returned engine=mesen system=nes attempt=1 id=qualification-red-border "
            "enabled=true active=1 callbackReturned=true persisted=true "
            "acknowledged=false effectProofRequired=true marker=cheat-apply-returned\n"
            "Cheat apply returned engine=mesen system=nes attempt=2 id=qualification-red-border "
            "enabled=false active=0 callbackReturned=true persisted=true "
            "acknowledged=false effectProofRequired=true marker=cheat-apply-returned"
        )
        self.assertTrue(
            MODULE.analyze_cheat(before, after, disabled, log)["materialEffect"]
        )
        with self.assertRaisesRegex(ValueError, "material border effect"):
            MODULE.analyze_cheat(before, before, disabled, log)

    def test_kernel_trace_rejects_repeat_and_stuck_edges(self):
        lines = []
        for code, pairs in ((304, 4), (305, 2), (310, 1), (314, 10), (315, 3)):
            for _ in range(pairs):
                lines.extend((f"0001 {code:04x} 00000001",
                              f"0001 {code:04x} 00000000"))
        for axis in (16, 17):
            lines.extend((f"0003 {axis:04x} ffffffff",
                          f"0003 {axis:04x} 00000000",
                          f"0003 {axis:04x} 00000001",
                          f"0003 {axis:04x} 00000000"))
        valid = "\n".join(lines)
        self.assertTrue(MODULE.analyze_kernel_input_trace(valid)[
            "noRepeatsOrStuckState"])
        with self.assertRaisesRegex(ValueError, "repeats/missing/stuck A"):
            MODULE.analyze_kernel_input_trace(
                valid.replace("0001 0130 00000000", "0001 0130 00000002", 1)
            )

    def test_r28_symbolic_kernel_trace_maps_gamepad_a_and_timed_hat_edges(self):
        stamp = 213670.0
        lines = []
        symbolic_names = {
            304: "BTN_GAMEPAD", 305: "BTN_EAST", 310: "BTN_TL",
            314: "BTN_SELECT", 315: "BTN_START",
        }
        for code, pairs in ((304, 4), (305, 2), (310, 1), (314, 10), (315, 3)):
            for _ in range(pairs):
                lines.append(f"[ {stamp:.6f}] EV_KEY {symbolic_names[code]} DOWN")
                stamp += 0.01
                lines.append(f"[ {stamp:.6f}] EV_KEY {symbolic_names[code]} UP")
                stamp += 0.01
        for axis in ("X", "Y"):
            for value in ("ffffffff", "00000000", "00000001", "00000000"):
                lines.append(f"[ {stamp:.6f}] EV_ABS ABS_HAT0{axis} {value}")
                stamp += 0.01
        trace = "\n".join(lines)
        result = MODULE.analyze_kernel_input_trace(trace)
        self.assertEqual(result["keys"]["A"], {"down": 4, "up": 4})
        timed = MODULE._kernel_timed_events(trace)
        self.assertEqual(timed[0][:3], (1, 304, 1))
        self.assertIn((3, 16, -1), [event[:3] for event in timed])
        self.assertIn((3, 17, 1), [event[:3] for event in timed])
        self.assertTrue(all(right[3] > left[3]
                            for left, right in zip(timed, timed[1:])))

    def test_symbolic_kernel_trace_rejects_spoof_malformed_and_wrong_a_name(self):
        valid = (
            "[  213670.153128] EV_KEY BTN_GAMEPAD DOWN\n"
            "[  213670.224713] EV_KEY BTN_GAMEPAD UP\n"
            "[  213670.300000] EV_ABS ABS_HAT0X ffffffff\n"
            "[  213670.400000] EV_ABS ABS_HAT0X 00000000\n"
        )
        self.assertEqual(MODULE._kernel_timed_events(valid)[0][:3], (1, 304, 1))
        for replacement in ("BTN_NORTH", "BTN_GAMEPAD DOWN SPOOF"):
            with self.subTest(replacement=replacement):
                tampered = valid.replace("BTN_GAMEPAD DOWN", replacement, 1)
                self.assertNotIn((1, 304, 1), MODULE._kernel_events(tampered))
        malformed_time = valid.replace("[  213670.153128]", "[ uptime? ]", 1)
        self.assertNotIn((1, 304, 1),
                         [event[:3] for event in
                          MODULE._kernel_timed_events(malformed_time)])
        self.assertNotIn((1, 304, 1), MODULE._kernel_events(
            valid.replace("BTN_GAMEPAD", "BTN_EAST", 1)
        ))

    def test_tier_schedule_accepts_exact_symbolic_r28_chord_order(self):
        schedule = self.root / "symbolic-schedule.json"
        tiers = [60, 50, 40, 30, 40, 50, 60]
        expected = {
            60: ("Y", "ffffffff", "Select+Up"),
            50: ("X", "00000001", "Select+Right"),
            40: ("Y", "00000001", "Select+Down"),
            30: ("X", "ffffffff", "Select+Left"),
        }
        selections = []
        lines = []
        for index, tier in enumerate(tiers):
            axis, value, combo = expected[tier]
            start_ns = (1 + index) * 1_000_000_000
            end_ns = start_ns + 250_000_000
            selections.append({
                "tier": tier, "combo": combo,
                "hostStartNs": 1_000 + index * 1_000,
                "hostEndNs": 1_500 + index * 1_000,
                "deviceStartMonotonicNs": start_ns,
                "deviceEndMonotonicNs": end_ns,
                "physicalEventNode": "/dev/input/event9",
            })
            lines.extend((
                f"[ {1 + index:.9f}] EV_ABS ABS_HAT0{axis} {value}",
                f"[ {1.1 + index:.9f}] EV_KEY BTN_SELECT DOWN",
                f"[ {1.2 + index:.9f}] EV_KEY BTN_SELECT UP",
                f"[ {1.25 + index:.9f}] EV_ABS ABS_HAT0{axis} 00000000",
            ))
        resets = [
            {"tier": tier, "pid": 1234, "generator": 7,
             "disabledLineIndex": 100 + index * 2,
             "enabledLineIndex": 101 + index * 2,
             "baselineWindowEndNs": 20_000_000_000 + index * 30_000_000_000}
            for index, tier in enumerate(tiers)
        ]
        schedule.write_text(json.dumps({
            "schemaVersion": 1, "tiers": tiers,
            "directSelections": selections, "proofResets": resets,
            "source": "physical Odin Controller Select+direction",
            "noClockOverride": True,
        }), encoding="utf-8")
        accepted = MODULE.analyze_tier_input_schedule(
            schedule, "\n".join(lines), "/dev/input/event9"
        )
        self.assertEqual(accepted["directSelections"], 7)
        swapped = list(lines)
        swapped[1], swapped[2] = swapped[2], swapped[1]
        with self.assertRaisesRegex(
                ValueError, "ordered direct tier chord|monotonic bounds"):
            MODULE.analyze_tier_input_schedule(
                schedule, "\n".join(swapped), "/dev/input/event9"
            )

    def test_manifest_rehashes_artifacts_and_rejects_inflated_gates(self):
        roles = {
            "launch-video", "launch-input-trace", "geometry", "motion-before",
            "motion-after", "control-neutral", "resume-before", "resume-after",
            "cheat-before", "cheat-after", "logcat", "stop-video",
            *(f"control-{name.lower()}" for name in MODULE.CONTROL_NAMES),
        }
        artifacts = []
        for role in sorted(roles):
            path = self.root / f"{role}.bin"
            path.write_bytes((role + "\n").encode())
            artifacts.append({"role": role, "path": path.name,
                              "sha256": MODULE.sha256_file(path),
                              "bytes": path.stat().st_size})
        digest = "1" * 64
        manifest = {
            "schemaVersion": 1, "profile": MODULE.PROFILE,
            "identity": {"engine": "mesen", "system": "nes",
                         "apkSha256": digest, "installedApkSha256": digest,
                         "romSha256": "2" * 64, "coreArtifactSha256": "3" * 64},
            "artifacts": artifacts,
            "gates": {
                "launch": {"visibleLatencyUpperBoundMs": 499, "maxFrameGapMs": 99,
                           "preInputMenuFrame": True, "firstGuestGeometryMatched": True},
                "stop": {"visibleReturnLatencyUpperBoundMs": 500, "maxFrameGapMs": 100,
                         "continuousGameplayBeforeStop": True},
            },
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        # The former summary-only contract must now fail closed: these opaque
        # .bin roles cannot prove pixels, audio spectrum, transitions, or raw
        # frame-generation qualification.
        report = MODULE.verify_manifest(path)
        self.assertFalse(report["passed"])
        self.assertTrue(any("missing required artifacts" in error
                            for error in report["errors"]))
        manifest["gates"]["launch"]["visibleLatencyUpperBoundMs"] = 501
        path.write_text(json.dumps(manifest), encoding="utf-8")
        report = MODULE.verify_manifest(path)
        self.assertFalse(report["passed"])
        manifest["gates"]["launch"]["visibleLatencyUpperBoundMs"] = 499
        (self.root / artifacts[0]["path"]).write_bytes(b"tampered")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertFalse(MODULE.verify_manifest(path)["passed"])

    def test_complete_raw_campaign_recomputes_every_semantic_gate(self):
        files: dict[str, Path] = {}

        def bind(role: str, path: Path):
            files[role] = path

        for role, payload in (("qualification-rom", b"rom"),
                              ("core-artifact", b"core")):
            target = self.root / role
            target.write_bytes(payload)
            bind(role, target)
        candidate_apk = self.root / "candidate-apk"
        rom_sha = MODULE.sha256_file(files["qualification-rom"])
        with zipfile.ZipFile(candidate_apk, "w") as archive:
            archive.writestr("assets/cheats/cheat-database.json", json.dumps({
                "games": [{"system": "nes", "title": "Lucent Callback Test",
                           "cheats": [{"id": "qualification-red-border",
                                       "code": "6000:3F",
                                       "description": f"fixture {rom_sha}"}]}]
            }))
            archive.writestr("lib/arm64-v8a/liblucent_core_mesen.so", b"core")
        bind("candidate-apk", candidate_apk)
        menu = self.root / "menu.png"
        Image.new("RGB", (1920, 1080), (4, 4, 4)).save(menu)
        bind("launch-menu-reference", menu)
        bind("stop-menu-reference", menu)
        bind("geometry", self.frame("geometry.png"))
        bind("motion-before", self.frame("motion-before.png", sprite_x=700))
        bind("motion-after", self.frame("motion-after.png", sprite_x=760))
        bind("control-neutral", self.frame("neutral.png"))
        colours = tuple(MODULE.CONTROL_DISTINCT_TEST_RGB[name]
                        for name in MODULE.CONTROL_NAMES)
        for name, colour in zip(MODULE.CONTROL_NAMES, colours):
            bind(f"control-{name.lower()}",
                 self.frame(f"control-{name.lower()}.png", interior=colour,
                            marker_y=MODULE.CONTROL_MARKER_SOURCE_Y[name]))
        bind("resume-before", self.frame("resume-before.png", sprite_x=803))
        bind("resume-after", self.frame("resume-after.png", sprite_x=803))
        bind("cheat-before", self.frame("cheat-before.png", border=(240, 240, 240)))
        bind("cheat-enabled", self.frame("cheat-enabled.png", border=(200, 20, 30)))
        bind("cheat-disabled", self.frame("cheat-disabled.png", border=(240, 240, 240)))
        bind("cheat-initial", self.frame("cheat-initial.png", border=(240, 240, 240)))
        bind("cheat-panel", self.frame("cheat-panel.png", interior=(70, 70, 80)))

        log_text = (
            "Quick Resume committed engine=mesen system=nes\n"
            "Quick Resume restored engine=mesen system=nes\n"
            "Cheats panel shown engine=mesen system=nes count=1 lowerDisplay=true\n"
            "Quick Resume committed engine=mesen system=nes\n"
            "Quick Resume restored engine=mesen system=nes\n"
            "Runtime telemetry engine=mesen system=nes frames=120 elapsedMs=1990 "
            "measuredFps=60.302 targetFps=60.099 audioFrames=88200 "
            "audioStarted=true audioHead=93500 audioProducedFrames=88200 "
            "audioWrittenFrames=88200 audioDroppedFrames=0 "
            "audioFocusDroppedFrames=0 audioQueuedFrames=800 "
            "audioPartialWrites=0 audioZeroWrites=0 audioWriteErrors=0 "
            "audioNativeDrainBoundHits=0 audioUnderruns=0\n"
            "PCM signal telemetry engine=mesen system=nes "
            "audioSignalBoundary=pre-AudioTrack audioSignalAudibilityProven=false "
            "audioSignalSampleRateHz=48000 audioSignalWindowFrames=8192 "
            "audioSignalWindowSamples=16384 audioSignalWindowFrequencyResolutionHz=5.860090 "
            "audioSignalWindowOverflow=false audioSignalWindowLeftMin=-12000 "
            "audioSignalWindowLeftMax=12000 audioSignalWindowLeftPeak=12000 "
            "audioSignalWindowLeftRms=8000.0 audioSignalWindowLeftToneHz=440.4 "
            "audioSignalWindowLeftCrossings=75 audioSignalWindowRightMin=-12000 "
            "audioSignalWindowRightMax=12000 audioSignalWindowRightPeak=12000 "
            "audioSignalWindowRightRms=8000.0 audioSignalWindowRightToneHz=440.4 "
            "audioSignalWindowRightCrossings=75 marker=audio-pcm-signal\n"
            "Cheat apply returned engine=mesen system=nes attempt=1 id=qualification-red-border "
            "enabled=true active=1 callbackReturned=true persisted=true "
            "acknowledged=false effectProofRequired=true marker=cheat-apply-returned\n"
            "Cheat apply returned engine=mesen system=nes attempt=2 id=qualification-red-border "
            "enabled=false active=0 callbackReturned=true persisted=true "
            "acknowledged=false effectProofRequired=true marker=cheat-apply-returned\n"
        )
        log_text = "\n".join(
            f"08-11 12:00:00.000  1234  1234 I EmuFusion: {line}"
            for line in log_text.splitlines()
        ) + "\n"
        logcat = self.root / "logcat.txt"
        logcat.write_text(log_text, encoding="utf-8")
        bind("logcat", logcat)
        framegen_log = self.root / "framegen-log.txt"
        framegen_log.write_text(log_text, encoding="utf-8")
        bind("framegen-log", framegen_log)
        for role in ("launch-video", "stop-video"):
            target = self.root / f"{role}.txt"
            target.write_text(role + "\n", encoding="utf-8")
            bind(role, target)
        launch_input = self.root / "launch-input-trace.json"
        launch_input.write_text(json.dumps({
            "schemaVersion": 1, "eventNode": "/dev/input/event9",
            "action": "launch-a", "keyCode": 304,
            "uptimeBeforeSeconds": 5.0, "uptimeAfterSeconds": 5.06,
            "rawKernelTrace": (
                "[ 5.001] 0001 0130 00000001\n"
                "[ 5.056] 0001 0130 00000000\n"
            ),
        }), encoding="utf-8")
        bind("launch-input-trace", launch_input)
        stop_input = self.root / "stop-input-trace.json"
        stop_input.write_text(json.dumps({
            "schemaVersion": 1, "eventNode": "/dev/input/event9",
            "action": "held-stop", "keyCode": 314,
            "uptimeBeforeSeconds": 9.0, "uptimeAfterSeconds": 10.15,
            "rawKernelTrace": (
                "[ 9.001] 0001 013a 00000001\n"
                "[ 10.151] 0001 013a 00000000\n"
            ),
        }), encoding="utf-8")
        bind("stop-input-trace", stop_input)
        description = self.root / "controller-description.txt"
        description.write_text(
            'N: Name="Odin Controller"\nI: Bus=0019 Vendor=2020 Product=0111 Version=0100\n'
            'H: Handlers=sysrq kbd event9\n/dev/input/event9\n', encoding="utf-8")
        bind("controller-description", description)
        settings = self.root / "controller-settings.json"
        settings.write_text(json.dumps({"flip_button_layout": "0",
                                        "no_create_gamepad_button_layout": "0",
                                        "style": "Odin Style"}), encoding="utf-8")
        bind("controller-settings", settings)
        input_trace = self.root / "controller-input-trace.txt"
        trace_lines = []
        for code, pairs in ((304, 5), (305, 2), (310, 1), (314, 10), (315, 3)):
            for _ in range(pairs):
                trace_lines.extend((f"0001 {code:04x} 00000001",
                                    f"0001 {code:04x} 00000000"))
        for axis in (16, 17):
            trace_lines.extend((f"0003 {axis:04x} ffffffff",
                                f"0003 {axis:04x} 00000000",
                                f"0003 {axis:04x} 00000001",
                                f"0003 {axis:04x} 00000000"))
        for chord_index, (axis, value) in enumerate(
                ((17, -1), (16, 1), (17, 1), (16, -1),
                 (17, 1), (16, 1), (17, -1))):
            encoded = value & 0xFFFFFFFF
            start = 10.0 + chord_index * 30.0
            trace_lines.extend((
                f"[ {start:.6f}] 0003 {axis:04x} {encoded:08x}",
                f"[ {start + 0.1:.6f}] 0001 013a 00000001",
                f"[ {start + 0.2:.6f}] 0001 013a 00000000",
                f"[ {start + 0.3:.6f}] 0003 {axis:04x} 00000000",
            ))
        input_trace.write_text("\n".join(trace_lines) + "\n", encoding="utf-8")
        bind("controller-input-trace", input_trace)
        schedule = self.root / "framegen-tier-input-schedule.json"
        tiers = [60, 50, 40, 30, 40, 50, 60]
        combos = {60: "Select+Up", 50: "Select+Right",
                  40: "Select+Down", 30: "Select+Left"}
        schedule.write_text(json.dumps({
            "schemaVersion": 1, "tiers": tiers,
            "directSelections": [
                {"tier": tier, "combo": combos[tier],
                 "hostStartNs": 10_000 + index * 1_000,
                 "hostEndNs": 10_500 + index * 1_000,
                 "deviceStartMonotonicNs": 10_000_000_000 + index * 30_000_000_000,
                 "deviceEndMonotonicNs": 10_300_000_000 + index * 30_000_000_000,
                 "physicalEventNode": "/dev/input/event9"}
                for index, tier in enumerate(tiers)
            ],
            "proofResets": [
                {"tier": tier, "pid": 1234, "generator": 7,
                 "disabledLineIndex": 100 + index * 2,
                 "enabledLineIndex": 101 + index * 2,
                 "baselineWindowEndNs":
                     10_500_000_000 + index * 30_000_000_000}
                for index, tier in enumerate(tiers)
            ],
            "source": "physical Odin Controller Select+direction",
            "noClockOverride": True,
        }), encoding="utf-8")
        bind("framegen-tier-input-schedule", schedule)
        keylayout = self.root / "controller-keylayout.kl"
        keylayout.write_text("key 304 BUTTON_A\n", encoding="utf-8")
        bind("controller-keylayout", keylayout)

        launch_origin = 5_000_000_000
        launch_frames = []
        for index in range(12):
            role = f"launch-frame-{index:06d}"
            path = self.root / f"{role}.png"
            if index >= 7:
                source = self.frame(f"launch-source-{index}.png", sprite_x=700 + index)
                path.write_bytes(source.read_bytes())
            else:
                path.write_bytes(menu.read_bytes())
            bind(role, path)
            launch_frames.append({"role": role, "index": index,
                                  "elapsedNs": launch_origin - 30_000_000 +
                                  index * 50_000_000})
        stop_origin = 10_000_000_000
        stop_specs = ((stop_origin - 300_000_000, 700),
                      (stop_origin - 50_000_000, 760),
                      (stop_origin + 50_000_000, None))
        stop_frames = []
        for index, (timestamp, sprite) in enumerate(stop_specs):
            role = f"stop-frame-{index:06d}"
            path = self.root / f"{role}.png"
            if sprite is None:
                path.write_bytes(menu.read_bytes())
            else:
                source = self.frame(f"stop-source-{index}.png", sprite_x=sprite)
                path.write_bytes(source.read_bytes())
            bind(role, path)
            stop_frames.append({"role": role, "index": index,
                                "elapsedNs": timestamp})
        stop_first = self.root / "stop-menu-first.png"
        stop_first.write_bytes(menu.read_bytes())
        bind("stop-menu-first", stop_first)
        stop_interactive = self.root / "stop-menu-interactive.png"
        interactive_image = Image.open(menu).convert("RGB")
        ImageDraw.Draw(interactive_image).rectangle((400, 300, 1500, 800),
                                                    fill=(180, 180, 180))
        interactive_image.save(stop_interactive)
        bind("stop-menu-interactive", stop_interactive)
        stop_selection = self.root / "stop-menu-selection.png"
        stop_selection.write_bytes(menu.read_bytes())
        bind("stop-menu-selection", stop_selection)

        segments = [*(f"steady-{tier}" for tier in MODULE.STEADY_TIERS),
                    *(f"transition-{left}-{right}"
                      for left, right in MODULE.TRANSITIONS)]
        for name in segments:
            if name.startswith("steady-"):
                tier = int(name.split("-")[1])
                first_occurrence = {60: 0, 50: 1, 40: 2, 30: 3}[tier]
                reset_index = first_occurrence
                segment = {"segmentId": name, "kind": "steady",
                           "expectedLockedFps": tier,
                           "startWindowEndNs":
                               10_500_000_000 +
                               first_occurrence * 30_000_000_000}
            else:
                _, left, right = name.split("-")
                transition_index = MODULE.TRANSITIONS.index((int(left), int(right)))
                reset_index = transition_index + 1
                device_start = (10_000_000_000 +
                                (transition_index + 1) * 30_000_000_000)
                segment = {"segmentId": name, "kind": "transition",
                           "expectedFromFps": int(left),
                           "expectedToFps": int(right),
                           "startWindowEndNs": device_start - 1,
                           "proofBaselineWindowEndNs": device_start + 500_000_000}
            segment["proofReset"] = {
                "pid": 1234, "generator": 7,
                "disabledLineIndex": 100 + reset_index * 2,
                "enabledLineIndex": 101 + reset_index * 2,
                "baselineWindowEndNs":
                    10_500_000_000 + reset_index * 30_000_000_000,
            }
            qualification = self.root / f"{name}-qualification.json"
            qualification.write_text(json.dumps({
                "identity": {"systemId": "nes", "coreId": "mesen",
                             "pid": 1234, "packageName": "com.thorium.preview",
                             "romSha256": MODULE.sha256_file(files["qualification-rom"]),
                             "coreSha256": MODULE.sha256_file(files["core-artifact"]),
                             "apkSha256": MODULE.sha256_file(files["candidate-apk"])},
                "segments": [segment],
            }), encoding="utf-8")
            latency = self.root / f"{name}-latency.txt"
            latency.write_text("latency\n", encoding="utf-8")
            report = self.root / f"{name}-report.json"
            report.write_text(json.dumps({
                "passed": True, "failures": [],
                "calibrationOnly": True,
                "contentQualificationEligible": False,
                "contentQualityPassed": True,
            }), encoding="utf-8")
            bind(f"framegen-{name}-qualification", qualification)
            bind(f"framegen-{name}-latency", latency)
            bind(f"framegen-{name}-report", report)

        artifacts = [{"role": role, "path": path.name,
                      "sha256": MODULE.sha256_file(path),
                      "bytes": path.stat().st_size}
                     for role, path in sorted(files.items())]
        apk_hash = MODULE.sha256_file(files["candidate-apk"])
        manifest = {
            "schemaVersion": 1, "profile": MODULE.PROFILE,
            "identity": {"engine": "mesen", "system": "nes",
                         "gameTitle": "Lucent Callback Test",
                         "pid": 1234,
                         "apkSha256": apk_hash, "installedApkSha256": apk_hash,
                         "romSha256": MODULE.sha256_file(files["qualification-rom"]),
                         "coreArtifactSha256": MODULE.sha256_file(files["core-artifact"])},
            "artifacts": artifacts,
            "measurements": {
                "motion": {"spanMs": 250},
                "cheat": {"initialEnabled": False,
                          "panelOcr": "Qualification red border"},
                "launch": {"inputLowerBoundElapsedNs": launch_origin,
                           "frames": launch_frames},
                "stop": {"thresholdElapsedNs": stop_origin,
                         "frames": stop_frames,
                         "selectionOcr": "Lucent Callback Test",
                         "immediateInputChangedPixels": sum(
                             max(pixel) >= 10 for pixel in ImageChops.difference(
                                 Image.open(stop_first).convert("RGB").resize((320, 180)),
                                 Image.open(stop_interactive).convert("RGB").resize((320, 180)),
                             ).getdata())},
                "controller": {"flip_button_layout": "0",
                               "no_create_gamepad_button_layout": "0",
                               "style": "Odin Style",
                               "eventNode": "/dev/input/event9", "name": "Odin Controller",
                               "vid": 0x2020, "pid": 0x0111,
                               "keylayoutPath": "/system/usr/keylayout/Vendor_2020_Product_0111.kl",
                               "keylayoutSha256": MODULE.sha256_file(keylayout)},
                "logcatCapture": {"pid": 1234, "arguments":
                                  ["logcat", "--pid", "1234", "-v", "threadtime"]},
                "frameGeneration": {"calibrationOnly": True,
                                    "contentQualificationEligible": False,
                                    "contentQualityPassed": True,
                                    "segmentCount": len(segments)},
            },
        }
        path = self.root / "complete-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(MODULE.frame_gen, "verify",
                               return_value={"passed": True, "failures": []}), mock.patch.object(
                                   MODULE, "verify_video_frame_binding",
                                   return_value=[]), mock.patch.object(
                                   MODULE, "analyze_cheat_panel",
                                   return_value={"exactRowOcr": True}), mock.patch.object(
                                   MODULE, "analyze_tier_proof_reset_log",
                                   return_value={"resets": 7}), mock.patch.object(
                                   MODULE, "EXPECTED_THOR_KEYLAYOUT_SHA256",
                                   MODULE.sha256_file(keylayout)):
            report = MODULE.verify_manifest(path)
        self.assertTrue(report["passed"], report["errors"])
        original_log = logcat.read_text(encoding="utf-8")
        logcat.write_text(original_log.replace(" 1234  1234 ", " 9999  1234 ", 1),
                          encoding="utf-8")
        log_artifact = next(item for item in manifest["artifacts"]
                            if item["role"] == "logcat")
        log_artifact["sha256"] = MODULE.sha256_file(logcat)
        log_artifact["bytes"] = logcat.stat().st_size
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(MODULE.frame_gen, "verify",
                               return_value={"passed": True}), mock.patch.object(
                                   MODULE, "analyze_tier_proof_reset_log",
                                   return_value={"resets": 7}), mock.patch.object(
                                   MODULE, "EXPECTED_THOR_KEYLAYOUT_SHA256",
                                   MODULE.sha256_file(keylayout)):
            foreign = MODULE.verify_manifest(path)
        self.assertFalse(foreign["passed"])
        self.assertTrue(any("foreign-PID" in error for error in foreign["errors"]))
        logcat.write_text(original_log, encoding="utf-8")
        log_artifact["sha256"] = MODULE.sha256_file(logcat)
        log_artifact["bytes"] = logcat.stat().st_size
        manifest["measurements"]["controller"]["keylayoutSha256"] = "f" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(MODULE.frame_gen, "verify",
                               return_value={"passed": True}), mock.patch.object(
                                   MODULE, "analyze_tier_proof_reset_log",
                                   return_value={"resets": 7}), mock.patch.object(
                                   MODULE, "EXPECTED_THOR_KEYLAYOUT_SHA256",
                                   MODULE.sha256_file(keylayout)):
            report = MODULE.verify_manifest(path)
        self.assertFalse(report["passed"])
        self.assertIn("NES controller identity/settings/keylayout binding is incomplete",
                      report["errors"])

    def test_pathological_calibration_report_preserves_raw_failed_verdict(self):
        calculated = {
            "passed": False,
            "failures": [
                "most synthetic output is indistinguishable from fixed-pixel crossfade",
                "motion field and non-crossfade synthetic output are not correlated",
            ],
        }
        saved = {**calculated, "calibrationOnly": True,
                 "contentQualificationEligible": False,
                 "contentQualityPassed": False}
        MODULE.validate_calibration_report(calculated, saved, "steady-60")
        self.assertFalse(saved["passed"])

    def test_calibration_offline_rejects_cadence_reset_and_unknown_failure(self):
        for failure in (
                "generator did not present at its 120 FPS target",
                "qualification proof reset baseline counters are nonzero",
                "unexpected new verifier failure"):
            calculated = {"passed": False, "failures": [failure]}
            saved = {**calculated, "calibrationOnly": True,
                     "contentQualificationEligible": False,
                     "contentQualityPassed": False}
            with self.subTest(failure=failure), self.assertRaisesRegex(
                    ValueError, "non-content calibration failures"):
                MODULE.validate_calibration_report(
                    calculated, saved, "steady-60"
                )

    def test_real_game_closure_rejects_missing_and_failed_child(self):
        children = []
        for index, title in enumerate(MODULE.REAL_GAME_TITLES):
            path = self.root / f"real-{index}.json"
            path.write_text("{}", encoding="utf-8")
            children.append({"title": title, "manifest": path.name,
                             "sha256": MODULE.sha256_file(path)})
        closure = self.root / "closure.json"
        closure.write_text(json.dumps({
            "schemaVersion": 1, "profile": MODULE.REAL_GAME_CLOSURE_PROFILE,
            "games": children[:-1],
        }), encoding="utf-8")
        missing = MODULE.verify_real_game_closure(closure)
        self.assertFalse(missing["passed"])
        self.assertTrue(any("missing or duplicating" in error
                            for error in missing["errors"]))

        closure.write_text(json.dumps({
            "schemaVersion": 1, "profile": MODULE.REAL_GAME_CLOSURE_PROFILE,
            "games": children,
        }), encoding="utf-8")
        with mock.patch.object(
                MODULE, "verify_real_title_manifest",
                side_effect=lambda _path, title: {
                    "passed": title != MODULE.REAL_GAME_TITLES[1],
                    "errors": ["failed"] if title == MODULE.REAL_GAME_TITLES[1] else [],
                }):
            failed = MODULE.verify_real_game_closure(closure)
        self.assertFalse(failed["passed"])
        self.assertTrue(any("1943" in error for error in failed["errors"]))

    def test_real_title_recomputes_full_framegen_report_and_identity(self):
        title = MODULE.REAL_GAME_TITLES[0]
        hashes = {"apkSha256": "a" * 64, "romSha256": "b" * 64,
                  "coreSha256": "c" * 64}
        log = self.root / "real-log.txt"
        latency = self.root / "real-latency.txt"
        qualification = self.root / "real-qualification.json"
        report = self.root / "real-report.json"
        readiness = self.root / "real-readiness.json"
        controller = self.root / "real-controller.txt"
        log.write_text("log", encoding="utf-8")
        latency.write_text("latency", encoding="utf-8")
        qualification.write_text(json.dumps({
            "identity": {"systemId": "nes", "coreId": "mesen", "pid": 1234,
                         **hashes},
            "segments": [{"segmentId": "real-steady"}],
        }), encoding="utf-8")
        calculated = {"passed": True, "failures": [], "proofSchemaVersion": 21}
        report.write_text(json.dumps(calculated), encoding="utf-8")
        readiness.write_text("{}", encoding="utf-8")
        controller.write_text("controller", encoding="utf-8")
        artifacts = []
        for role, path in (("framegen-log", log), ("framegen-latency", latency),
                           ("framegen-qualification", qualification),
                           ("framegen-report", report),
                           ("gameplay-readiness-report", readiness),
                           ("controller-input-trace", controller),
                           ("logcat", log)):
            artifacts.append({"role": role, "path": path.name,
                              "sha256": MODULE.sha256_file(path),
                              "bytes": path.stat().st_size})
        manifest = self.root / "real-title.json"
        manifest.write_text(json.dumps({
            "schemaVersion": 1, "profile": MODULE.REAL_GAME_PROFILE,
            "identity": {"title": title, "pid": 1234, **hashes},
            "artifacts": artifacts,
        }), encoding="utf-8")
        with mock.patch.object(MODULE.frame_gen, "verify",
                               return_value=calculated), \
                mock.patch.object(MODULE, "verify_real_readiness",
                                  return_value={"passed": True}):
            result = MODULE.verify_real_title_manifest(manifest, title)
        self.assertTrue(result["passed"], result["errors"])

        report.write_text(json.dumps({**calculated, "passed": False}),
                          encoding="utf-8")
        report_artifact = next(item for item in artifacts
                               if item["role"] == "framegen-report")
        report_artifact["sha256"] = MODULE.sha256_file(report)
        report_artifact["bytes"] = report.stat().st_size
        manifest.write_text(json.dumps({
            "schemaVersion": 1, "profile": MODULE.REAL_GAME_PROFILE,
            "identity": {"title": title, "pid": 1234, **hashes},
            "artifacts": artifacts,
        }), encoding="utf-8")
        with mock.patch.object(MODULE.frame_gen, "verify",
                               return_value=calculated), \
                mock.patch.object(MODULE, "verify_real_readiness",
                                  return_value={"passed": True}):
            failed = MODULE.verify_real_title_manifest(manifest, title)
        self.assertFalse(failed["passed"])

    def test_real_readiness_recomputes_timing_health_and_raw_activation(self):
        title = "10-Yard Fight"
        baseline = {"window_end_ns": 100, "window_promoted": 60,
                    "pid": 1234, "generator": 9}
        windows = [{"window_end_ns": 200 + index * 100,
                    "window_promoted": 60, "pid": 1234, "generator": 9}
                   for index in range(3)]
        roles = {}

        def artifact(role, name, content=b"pixel"):
            path = self.root / name
            path.write_bytes(content)
            roles[role] = path
            return path

        menu = artifact("gameplay-readiness-attempt-01-00", "menu.png")
        Image.new("RGB", (1920, 1080), "black").save(menu)
        gameplay = []
        timestamps = [3_000_000_000 + index * 3_000_000_001
                      for index in range(8)]
        for index in range(8):
            path = artifact(
                f"gameplay-readiness-attempt-02-{index:02d}",
                f"game-{index}.png",
            )
            image = Image.new("RGB", (1920, 1080), "black")
            ImageDraw.Draw(image).rectangle(
                (240, 0, 1679, 1079), fill=(40 + index * 20, 80, 120)
            )
            image.save(path)
            gameplay.append(path)
        attempts = [
            {"sequence": 1, "frames": [str(menu)],
             "states": ["10-yard-1-player"],
             "samples": [{"path": str(menu), "hostMonotonicNs": 1_000_000_000,
                          "state": "10-yard-1-player"}],
             "elapsedNs": 0, "healthBaseline": baseline, "healthWindows": []},
            {"sequence": 2, "frames": [str(path) for path in gameplay],
             "states": [None] * 8,
             "samples": [{"path": str(path), "hostMonotonicNs": stamp,
                          "state": None}
                         for path, stamp in zip(gameplay, timestamps)],
             "elapsedNs": timestamps[-1] - timestamps[0],
             "healthBaseline": baseline, "healthWindows": windows},
        ]
        action_raw = (b"[ 1.000] EV_KEY BTN_START DOWN\n"
                      b"[ 1.080] EV_KEY BTN_START UP\n")
        action_trace = artifact("gameplay-readiness-action-00",
                                "activation-00.txt", action_raw)
        actions = [{
            "label": "real-nes-activate-01-confirm",
            "controllerCode": 315, "hostMonotonicNs": 1_100_000_000,
            "recognizedFrameHostMonotonicNs": 1_000_000_000,
            "sourceState": "10-yard-1-player", "attemptSequence": 1,
            "kernelEvent": {"type": 1, "code": 315, "value": 1},
            "actionTracePath": str(action_trace),
        }]
        readiness = artifact("gameplay-readiness-report", "readiness.json")
        fractions = [MODULE._real_frame_change_fraction(left, right)
                     for left, right in zip(gameplay, gameplay[1:])]
        saved_gameplay = {
            "title": title, "frameCount": 8, "changedPairs": 7,
            "requiredChangedPairs": 5,
            "changeFractions": [round(value, 8) for value in fractions],
            "titleMenuAbsent": True, "sustainedMaterialMotion": True,
            "frames": [{"path": str(path), "ocr": ""} for path in gameplay],
        }
        readiness.write_text(json.dumps({
            "schemaVersion": 2, "title": title, "saveStatePreserved": True,
            "attempts": attempts, "actions": actions,
            "gameplay": saved_gameplay,
        }), encoding="utf-8")
        artifact("controller-input-trace", "controller.txt", action_raw)
        artifact("logcat", "logcat.txt", b"health")
        identity = {"title": title, "pid": 1234}
        with mock.patch.object(MODULE, "_real_health_records",
                               return_value=[baseline, *windows]), \
                mock.patch.object(
                    MODULE, "_real_menu_state_from_pixels",
                    side_effect=lambda path, _title: (
                        "10-yard-1-player" if path == menu else None)):
            result = MODULE.verify_real_readiness(roles, identity, title)
        self.assertTrue(result["passed"])
        self.assertGreater(result["elapsedNs"], 19_000_000_000)
        self.assertEqual(result["activationCount"], 1)

        original = json.loads(readiness.read_text(encoding="utf-8"))
        adversaries = (
            ("elapsed", lambda value: value["attempts"][1].update(
                elapsedNs=19_000_000_000)),
            ("late-action", lambda value: value["actions"][0].update(
                hostMonotonicNs=3_100_000_001)),
            ("forged-state", lambda value: value["actions"][0].update(
                sourceState="10-yard-2-player")),
            ("pixel-state", lambda value: (
                value["attempts"][0].update(states=["10-yard-2-player"]),
                value["attempts"][0]["samples"][0].update(
                    state="10-yard-2-player"))),
        )
        for name, mutate in adversaries:
            value = json.loads(json.dumps(original))
            mutate(value)
            readiness.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(name=name), \
                    mock.patch.object(MODULE, "_real_health_records",
                                      return_value=[baseline, *windows]), \
                    mock.patch.object(
                        MODULE, "_real_menu_state_from_pixels",
                        side_effect=lambda path, _title: (
                            "10-yard-1-player" if path == menu else None)), \
                    self.assertRaises(ValueError):
                MODULE.verify_real_readiness(roles, identity, title)
        readiness.write_text(json.dumps(original), encoding="utf-8")
        cross = [dict(item) for item in windows]
        cross[1]["pid"] = 999
        bad_report = json.loads(json.dumps(original))
        bad_report["attempts"][1]["healthWindows"] = cross
        readiness.write_text(json.dumps(bad_report), encoding="utf-8")
        with mock.patch.object(MODULE, "_real_health_records",
                               return_value=[baseline, *cross]), \
                mock.patch.object(
                    MODULE, "_real_menu_state_from_pixels",
                    side_effect=lambda path, _title: (
                        "10-yard-1-player" if path == menu else None)), \
                self.assertRaisesRegex(ValueError, "crossed identity"):
            MODULE.verify_real_readiness(roles, identity, title)
        readiness.write_text(json.dumps(original), encoding="utf-8")
        stale = dict(baseline)
        stale["generator"] = 10
        with mock.patch.object(MODULE, "_real_health_records",
                               return_value=[stale, *windows]), \
                mock.patch.object(
                    MODULE, "_real_menu_state_from_pixels",
                    side_effect=lambda path, _title: (
                        "10-yard-1-player" if path == menu else None)), \
                self.assertRaisesRegex(ValueError, "stale/forged"):
            MODULE.verify_real_readiness(roles, identity, title)
        roles["controller-input-trace"].write_text(
            "[ 1.000] EV_KEY BTN_GAMEPAD DOWN\n"
            "[ 1.080] EV_KEY BTN_GAMEPAD UP\n", encoding="utf-8"
        )
        with mock.patch.object(MODULE, "_real_health_records",
                               return_value=[baseline, *windows]), \
                mock.patch.object(
                    MODULE, "_real_menu_state_from_pixels",
                    side_effect=lambda path, _title: (
                        "10-yard-1-player" if path == menu else None)), \
                self.assertRaisesRegex(ValueError, "absent from continuous raw trace"):
            MODULE.verify_real_readiness(roles, identity, title)

        # Hash-bound timestamps/HEALTH cannot substitute for real motion.
        roles["controller-input-trace"].write_bytes(action_raw)
        for path in gameplay:
            image = Image.new("RGB", (1920, 1080), "black")
            ImageDraw.Draw(image).rectangle(
                (240, 0, 1679, 1079), fill=(80, 90, 100)
            )
            image.save(path)
        with mock.patch.object(MODULE, "_real_health_records",
                               return_value=[baseline, *windows]), \
                mock.patch.object(
                    MODULE, "_real_menu_state_from_pixels",
                    side_effect=lambda path, _title: (
                        "10-yard-1-player" if path == menu else None)), \
                self.assertRaisesRegex(ValueError, "static"):
            MODULE.verify_real_readiness(roles, identity, title)

        # Motion does not excuse a top bar or a shifted/nonblack pillar.
        for index, path in enumerate(gameplay):
            image = Image.new("RGB", (1920, 1080), "black")
            ImageDraw.Draw(image).rectangle(
                (240, 8, 1679, 1079), fill=(40 + index * 20, 80, 120)
            )
            image.save(path)
        with mock.patch.object(MODULE, "_real_health_records",
                               return_value=[baseline, *windows]), \
                mock.patch.object(
                    MODULE, "_real_menu_state_from_pixels",
                    side_effect=lambda path, _title: (
                        "10-yard-1-player" if path == menu else None)), \
                self.assertRaisesRegex(ValueError, "top/bottom bar"):
            MODULE.verify_real_readiness(roles, identity, title)
        for index, path in enumerate(gameplay):
            image = Image.new("RGB", (1920, 1080), "black")
            ImageDraw.Draw(image).rectangle(
                (220, 0, 1679, 1079), fill=(40 + index * 20, 80, 120)
            )
            image.save(path)
        with mock.patch.object(MODULE, "_real_health_records",
                               return_value=[baseline, *windows]), \
                mock.patch.object(
                    MODULE, "_real_menu_state_from_pixels",
                    side_effect=lambda path, _title: (
                        "10-yard-1-player" if path == menu else None)), \
                self.assertRaisesRegex(ValueError, "nonblack outer pillars"):
            MODULE.verify_real_readiness(roles, identity, title)


if __name__ == "__main__":
    unittest.main()
