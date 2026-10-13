"""Lower-panel previews show the whole video instead of a cropped middle.

The Thor's bottom screen is 1240x1080. PreviewActivity scaled 16:9 previews to
fill it, which kept only 65% of each frame's width (owner, 2026-10-13: the
bottom screen was "cutting off half the preview videos").
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")
FIT = ROOT / "android-companion/src/com/thorium/preview/PreviewVideoFit.java"
ACTIVITY = (ROOT / "android-companion/src/com/thorium/preview/PreviewActivity.java").read_text()


class LowerPanelPreviewFitTest(unittest.TestCase):
    def test_activity_contains_instead_of_cropping(self):
        self.assertNotIn("applyCrop(", ACTIVITY)
        self.assertIn("float[] scale = PreviewVideoFit.contain(width, height, videoWidth, videoHeight);",
                      ACTIVITY)
        self.assertIn("matrix.setScale(scale[0], scale[1], width / 2f, height / 2f);", ACTIVITY)
        self.assertEqual(ACTIVITY.count("applyFit(player.getVideoWidth(), player.getVideoHeight());"), 1)
        self.assertEqual(ACTIVITY.count("applyFit(mediaPlayer.getVideoWidth(), mediaPlayer.getVideoHeight());"), 1)

    def test_contain_scales(self):
        probe = r'''
public class FitProbe {
  static void near(float a, float b, String why) { if (Math.abs(a - b) > 1e-3f) throw new AssertionError(why + " " + a + " vs " + b); }
  public static void main(String[] args) {
    float[] wide = com.thorium.preview.PreviewVideoFit.contain(1240, 1080, 1920, 1080);
    near(wide[0], 1f, "16:9 keeps the full panel width");
    near(wide[1], (1240f / 1080f) / (16f / 9f), "and is letterboxed to its own height");
    float[] fourThree = com.thorium.preview.PreviewVideoFit.contain(1240, 1080, 640, 480);
    near(fourThree[0], 1f, "4:3 is still wider than the panel");
    near(fourThree[1], (1240f / 1080f) / (4f / 3f), "4:3 letterbox");
    float[] tall = com.thorium.preview.PreviewVideoFit.contain(1240, 1080, 1080, 1920);
    near(tall[1], 1f, "a portrait video keeps the full height");
    near(tall[0], (1080f / 1920f) / (1240f / 1080f), "and is pillarboxed");
    float[] same = com.thorium.preview.PreviewVideoFit.contain(1920, 1080, 1280, 720);
    near(same[0], 1f, "same shape: no bars"); near(same[1], 1f, "same shape: no bars");
    float[] bad = com.thorium.preview.PreviewVideoFit.contain(0, 1080, 1920, 1080);
    near(bad[0], 1f, "invalid sizes leave the view alone"); near(bad[1], 1f, "invalid");
    System.out.println("FIT_OK");
  }
}
'''
        with tempfile.TemporaryDirectory(prefix="preview-fit-") as tmp:
            Path(tmp, "FitProbe.java").write_text(probe)
            built = subprocess.run([str(JAVA / "javac"), "-d", tmp, str(FIT), str(Path(tmp, "FitProbe.java"))],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(JAVA / "java"), "-cp", tmp, "FitProbe"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("FIT_OK", run.stdout)


if __name__ == "__main__":
    unittest.main()
