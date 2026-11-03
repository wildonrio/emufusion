"""Thor lower-panel framebuffer check: parse SurfaceFlinger dumps (host only, no device)."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "thor_lower_display_repair", ROOT / "tools/thor_lower_display_repair.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
JAVA = Path(os.environ.get(
    "JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")

UPPER = "4630946441858561667"
LOWER = "4630946482288158084"


def dump(lower_surface, lower_target, lower_mode_id=1):
    """Trimmed `dumpsys SurfaceFlinger` with the sections the check reads."""
    return f"""Displays (2 entries)
Display {UPPER} (internal, primary, "")
   powerMode=On
   activeModeId=0
   displayModes=
      {{id=0, hwcId=0, resolution=1080x1920, refreshRate=60.00 Hz, dpi=318.98x320.84, group=0}}
      {{id=1, hwcId=1, resolution=1080x1920, refreshRate=120.00 Hz, dpi=318.98x320.84, group=0}}

Display {LOWER} (internal, "")
   powerMode=On
   activeModeId={lower_mode_id}
   displayModes=
      {{id=0, hwcId=0, resolution=1080x1240, refreshRate=120.00 Hz, dpi=318.98x321.39, group=0}}
      {{id=1, hwcId=1, resolution=1080x1240, refreshRate=60.00 Hz, dpi=318.98x321.39, group=0}}

Display {UPPER} (physical, "")
   Composition Display State:
   layerFilter={{layerStack=0 toInternalDisplay=true }}
   Composition RenderSurface State:
   size=[1080 1920] ANativeWindow=0xb4 (format 1) flips=373717
   FramebufferSurface
       >[01:0xb4] state=ACQUIRED 0xb4 frame=176 [1080x1920:1088,  1]
Display {LOWER} (physical, "")
   Composition Display State:
   layerFilter={{layerStack=4 toInternalDisplay=true }}
   framebufferSpace=ProjectionSpace{{bounds=Rect(0, 0, {lower_surface.replace('x', ', ')}), content=Rect(0, 0, 1080, 1240), orientation=ROTATION_90}}
   Composition RenderSurface State:
   size=[{lower_surface.replace('x', ' ')}] ANativeWindow=0xb4 (format 1) flips=285527
   FramebufferSurface
        default-size=[{lower_surface}] default-format=1         transform-hint=00 frame-counter=1738
       >[02:0xb4] state=ACQUIRED 0xb4 frame=1738 [{lower_target}:1088,  1]
        [01:0xb4] state=FREE     0xb4 frame=1736 [{lower_target}:1088,  1]
   1 Layers
  - Output Layer 0xb4(com.thorium.preview/com.thorium.preview.PreviewActivity#3969)
Tracing state: disabled
"""


class LowerDisplayCheckTest(unittest.TestCase):
    def test_squeezed_state_reports_upper_panel_framebuffer(self):
        # 2026-10-18 and 2026-11-02: lower framebuffer recreated with the upper mode.
        display_id, info = MODULE.lower_display(dump("1080x1920", "1080x1920"))
        self.assertEqual(display_id, LOWER)
        self.assertEqual(info["mode"], "1080x1240")
        self.assertEqual(info["layerStack"], 4)
        found = MODULE.problems(info)
        self.assertEqual(len(found), 2)
        self.assertIn("framebuffer 1080x1920 != panel mode 1080x1240", found[0])

    def test_resized_framebuffer_still_needs_a_client_frame(self):
        # After setDisplaySize alone the HWC keeps scaling the old client target.
        _, info = MODULE.lower_display(dump("1080x1240", "1080x1920"))
        self.assertEqual(MODULE.problems(info),
                         ["HWC client target 1080x1920 != panel mode 1080x1240"])

    def test_healthy_lower_display(self):
        for mode_id in (0, 1):
            _, info = MODULE.lower_display(dump("1080x1240", "1080x1240", mode_id))
            self.assertEqual(MODULE.problems(info), [])

    def test_upper_display_is_never_selected(self):
        displays = MODULE.parse_displays(dump("1080x1920", "1080x1920"))
        self.assertTrue(displays[UPPER]["primary"])
        self.assertEqual(MODULE.problems(displays[UPPER]), [])

    def test_missing_lower_display(self):
        only_upper = dump("1080x1240", "1080x1240").split(f"Display {LOWER} (internal")[0]
        self.assertEqual(MODULE.lower_display(only_upper), (None, None))
        self.assertTrue(MODULE.problems(None))

    def test_recorded_dumps_when_present(self):
        evidence = ROOT / "docs/qa/thor-barbie-2026-10-18"
        cases = {"physical-display/surfaceflinger-before.txt": False,
                 "os-display/launcher-surfaceflinger.txt": False,
                 "os-recovery/boot-surfaceflinger.txt": True,
                 "os-recovery/launcher-surfaceflinger.txt": True}
        if not evidence.is_dir():
            self.skipTest("local QA evidence not present")
        for name, healthy in cases.items():
            _, info = MODULE.lower_display((evidence / name).read_text(errors="replace"))
            self.assertEqual(not MODULE.problems(info), healthy, name)

    def test_asleep_display_is_refused_not_repaired(self):
        # Asleep, SurfaceFlinger reports layerStack 4294967295 for both displays;
        # the helper's int parse of it crashed with "Killed" (November 3).
        asleep = dump("1080x1920", "1080x1920").replace("layerStack=4 ", "layerStack=4294967295 ")
        calls = []

        class Device:
            def __init__(self, *args): pass
            def surfaceflinger(self): return asleep
            def run(self, *args, **kwargs): calls.append(args); return ""

        original = MODULE.Device
        MODULE.Device = Device
        try:
            self.assertEqual(MODULE.main(["--repair"]), 1)
        finally:
            MODULE.Device = original
        self.assertEqual(calls, [])

    def test_repair_moves_the_size_off_and_back(self):
        # SurfaceFlinger resizes only on a changed size: one row short, then the panel's.
        tool = (ROOT / "tools/thor_lower_display_repair.py").read_text()
        repair = tool[tool.index("def repair("):tool.index("def describe(")]
        short = repair.index("{int(height) - 1}")
        exact = repair.index('f"{helper} size {display_id} {width} {height}"')
        self.assertLess(short, exact)
        self.assertEqual(repair.count("client-frame"), 2)
        self.assertLess(exact, repair.rindex("client-frame"))

    def test_helper_is_shell_only_and_restores_its_layer(self):
        source = MODULE.JAVA_SOURCE.read_text()
        self.assertIn('"setDisplaySize"', source)
        self.assertIn("done.reparent(layer, null)", source)
        self.assertIn("finally", source)
        self.assertNotIn("setDisplayPowerMode", source)
        tool = (ROOT / "tools/thor_lower_display_repair.py").read_text()
        self.assertIn('f"rm -f {DEVICE_DEX}"', tool)
        self.assertNotIn("reboot", tool.split('"""', 2)[2])
        self.assertNotIn('"install"', tool)
        self.assertNotIn("pm install", tool)

    @unittest.skipUnless((JAVA / "javac").exists(), "JDK not installed")
    def test_helper_compiles_against_the_public_sdk(self):
        sdk = Path(os.environ.get("ANDROID_HOME", Path.home() / "Library/Android/sdk"))
        jars = sorted((sdk / "platforms").glob("android-*/android.jar"))
        if not jars:
            self.skipTest("Android SDK platform not installed")
        out = Path(tempfile.mkdtemp())
        try:
            result = subprocess.run(
                [str(JAVA / "javac"), "-source", "8", "-target", "8", "-nowarn",
                 "-cp", str(jars[-1]), "-d", str(out), str(MODULE.JAVA_SOURCE)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
