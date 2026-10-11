"""Games render at the screen's resolution, not the console's (owner, 2026-10-10).

3.2.17 reset every hardware core to console-native resolution, so a 1440p
phone showed a bilinear-upscaled 528-line Wii picture. RenderResolutionPolicy
picks, per core, the smallest advertised size at least as tall as the panel.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT, method

POLICY = ROOT / 'unified-android/src/com/thorium/preview/game/RenderResolutionPolicy.java'
WIDESCREEN = ROOT / 'unified-android/src/com/thorium/preview/game/WidescreenHackPolicy.java'
HOST = ROOT / 'unified-android/native/lucent_libretro_host.c'


class RenderResolutionPolicyTest(unittest.TestCase):
    def test_sizes_follow_the_screen(self):
        source = POLICY.read_text()
        body = '\n'.join(method(source, name) for name in (
            'static Map<String, String> forScreen(', 'private static int scale(',
            'private static String atLeast('))
        constants = '\n'.join(line for line in source.splitlines()
                              if line.strip().startswith(('static final int', 'private static final String[]'))
                              or line.strip().startswith('"640x480"') or line.strip().startswith('"1280x720"'))
        harness = r'''
import java.util.*;
public final class ResolutionProbe {
  static final int MAX_TARGET_LINES = 1440;
  static final int MAX_PS2_SCALE = 3;
  private static final String[] FOUR_BY_THREE = {
      "640x480", "960x720", "1280x960", "1440x1080", "1920x1440", "2560x1920"};
  private static final String[] SIXTEEN_BY_NINE = {"1280x720", "1920x1080", "2560x1440", "3840x2160"};
  static void eq(String want, String got, String why) {
    if (!want.equals(got)) throw new AssertionError(why + ": " + got + " != " + want);
  }
  public static void main(String[] a) {
    int[] screens = {720, 1080, 1440, 2160};
    String[][] expect = {
      // dolphin, ppsspp, flycast, mupen 4:3, mupen 16:9, azahar, armsx2
      {"2", "1440x816",  "960x720",   "960x720",   "1280x720",  "3", "2x"},
      {"3", "1920x1088", "1440x1080", "1440x1080", "1920x1080", "5", "3x"},
      {"3", "2880x1632", "1920x1440", "1920x1440", "2560x1440", "6", "3x"},
      {"3", "2880x1632", "1920x1440", "1920x1440", "2560x1440", "6", "3x"}};
    for (int i = 0; i < screens.length; i++) {
      int s = screens[i];
      eq(expect[i][0], forScreen("dolphin", s).get("dolphin_efb_scale"), s + " dolphin");
      eq(expect[i][1], forScreen("ppsspp", s).get("ppsspp_internal_resolution"), s + " ppsspp");
      eq(expect[i][2], forScreen("flycast", s).get("reicast_internal_resolution"), s + " flycast");
      eq(expect[i][3], forScreen("mupen64plus-next", s).get("mupen64plus-43screensize"), s + " n64");
      eq(expect[i][4], forScreen("mupen64plus-next", s).get("mupen64plus-169screensize"), s + " n64 wide");
      eq(expect[i][5], forScreen("azahar", s).get("citra_resolution_factor"), s + " 3ds");
      eq(expect[i][6], forScreen("armsx2", s).get("armsx2_upscale"), s + " ps2");
    }
    if (!forScreen("mesen", 1080).isEmpty()) throw new AssertionError("software cores untouched");
    if (!forScreen("dolphin", 0).isEmpty()) throw new AssertionError("unknown screen keeps defaults");
    System.out.println("resolution PASS");
  }
''' + body + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-resolution-') as temp:
            unit = Path(temp) / 'ResolutionProbe.java'
            unit.write_text(harness)
            subprocess.run([str(JAVA / 'javac'), str(unit)], check=True, capture_output=True, text=True)
            run = subprocess.run([str(JAVA / 'java'), '-cp', temp, 'ResolutionProbe'],
                                 capture_output=True, text=True)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)

    def test_launch_writes_the_sizes_and_the_host_validates_tokens(self):
        launch = WIDESCREEN.read_text()
        self.assertIn('overrides.putAll(RenderResolutionPolicy.coreOptionOverrides(context, engine));',
                      launch)
        # The host only accepts a value the core itself advertises.
        self.assertIn('core-option override ignored', HOST.read_text())


if __name__ == '__main__':
    unittest.main()
