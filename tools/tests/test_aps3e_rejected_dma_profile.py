"""Do not re-enable the ICO workaround falsified by its device gameplay trial."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"


class RejectedDmaProfileTest(unittest.TestCase):
    def test_failed_profile_is_not_in_the_launch_path(self):
        source = (GAME / "NativeAdapterEngineSession.java").read_text()
        self.assertNotIn("Aps3eCompatibilityProfile", source)
        self.assertNotIn("APS3E_CUSTOM_CONFIG_YAML_PATH", source)
        self.assertFalse((GAME / "Aps3eCompatibilityProfile.java").exists())

    def test_preexisting_save_identity_and_environment_preparation_remain(self):
        source = (GAME / "NativeAdapterEngineSession.java").read_text()
        self.assertIn('? contentSha256Short(game) : gameIdentity;', source)
        content_hash = source.split("private static String contentSha256Short", 1)[1]
        self.assertIn('getInstance("SHA-256")', content_hash)
        self.assertIn("return result.substring(0, 32);", content_hash)
        self.assertLess(source.index("NativeAdapterSystemDirectory.prepareForOpen"),
                        source.index("new NativeAdapterHost("))


if __name__ == "__main__":
    unittest.main()
