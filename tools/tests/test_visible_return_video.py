import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "unified-android" / "tools"
SPEC = importlib.util.spec_from_file_location(
    "visible_return_video", TOOLS / "visible_return_video.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def winscope_payload(timestamps):
    return (
        b"mp4-prefix" + MODULE.WINSC0PE_V2_MAGIC +
        struct.pack("<IqI", 2, 123456, len(timestamps)) +
        struct.pack(f"<{len(timestamps)}Q", *timestamps) + b"mp4-suffix"
    )


class VisibleReturnVideoTest(unittest.TestCase):
    def test_winscope_v2_timestamps_are_device_elapsed_time(self):
        values = [10_000_000_000, 10_016_666_667, 10_033_333_334]
        self.assertEqual(
            MODULE.parse_winscope_frame_timestamps(winscope_payload(values)),
            values,
        )

    def test_winscope_parser_fails_closed_on_missing_duplicate_or_bad_order(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            MODULE.parse_winscope_frame_timestamps(b"ordinary mp4")
        valid = winscope_payload([10, 20])
        with self.assertRaisesRegex(ValueError, "found 2"):
            MODULE.parse_winscope_frame_timestamps(valid + valid)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            MODULE.parse_winscope_frame_timestamps(
                winscope_payload([10, 10, 20])
            )
        with self.assertRaisesRegex(ValueError, "truncated"):
            MODULE.parse_winscope_frame_timestamps(
                winscope_payload([10, 20, 30])[:-12]
            )

    def test_uptime_parser_rejects_non_device_clock_text(self):
        self.assertEqual(MODULE.parse_uptime_seconds("123.45 88.00\n"), 123.45)
        for invalid in ("", "123.4", "nan 4", "0 9"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.parse_uptime_seconds(invalid)

    def test_visible_latency_is_ceiling_from_pre_down_lower_bound(self):
        threshold = 101_000_000_000
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = [
                MODULE.TimedFrame(1, threshold - 10_000_000, root / "game.png"),
                MODULE.TimedFrame(2, threshold + 10_000_000, root / "transition.png"),
                MODULE.TimedFrame(3, threshold + 21_000_001, root / "menu.png"),
            ]
            result = MODULE.evaluate_visible_return(
                frames, threshold, lambda path: path.name == "menu.png"
            )
        self.assertEqual(result["visibleReturnLatencyUpperBoundMs"], 22)
        self.assertEqual(
            result["method"],
            "screenrecord-winscope-v2-device-clock-upper-bound",
        )

    def test_visible_return_rejects_sparse_or_unbounded_recording(self):
        threshold = 10_000_000_000
        root = Path("unused")
        sparse = [
            MODULE.TimedFrame(1, threshold - 200_000_000, root / "a.png"),
            MODULE.TimedFrame(2, threshold + 10_000_000, root / "menu.png"),
        ]
        with self.assertRaisesRegex(ValueError, "too sparse"):
            MODULE.evaluate_visible_return(
                sparse, threshold, lambda path: path.name == "menu.png"
            )
        incomplete = [
            MODULE.TimedFrame(1, threshold - 10_000_000, root / "a.png"),
            MODULE.TimedFrame(2, threshold + 10_000_000, root / "b.png"),
        ]
        with self.assertRaisesRegex(ValueError, "ended before"):
            MODULE.evaluate_visible_return(incomplete, threshold, lambda _path: False)

    def test_frame_window_includes_entire_five_hundred_ms_budget(self):
        threshold = 5_000_000_000
        values = [threshold - 400_000_000 + index * 50_000_000
                  for index in range(23)]
        first, last = MODULE.frame_window(values, threshold)
        self.assertLessEqual(values[first], threshold)
        self.assertGreaterEqual(values[last], threshold + 500_000_000)


if __name__ == "__main__":
    unittest.main()
