"""Switch uses the system Vulkan driver by default, as standalone Eden does."""
from pathlib import Path
import unittest
from tools.tests.test_framegen_startup_fallback import method

ROOT = Path(__file__).resolve().parents[2]
PROVISIONER = ROOT / "unified-android/src/com/thorium/preview/game/GpuDriverProvisioner.java"


class SwitchSystemGpuDriverTest(unittest.TestCase):
    def test_default_mode_is_system(self):
        source = PROVISIONER.read_text()
        mode = method(source, "    static String mode(Context context)")
        # Owner, 2026-10-26: shader corruption in Metroid Dread / 3D World on
        # the automatic Turnip pick; stock Eden keeps the system driver.
        self.assertIn('prefs(context).getString("mode", MODE_SYSTEM)', mode)
        self.assertNotIn('getString("mode", MODE_AUTO)', source)
        self.assertIn('"emufusion_switch_gpu_driver"', source)

    def test_system_mode_downloads_nothing_and_retires_old_package(self):
        provision = method(PROVISIONER.read_text(),
                           "    static void provision(Context context)")
        self.assertIn("removeOtherPackages(root, system ? null : chosen);", provision)
        self.assertLess(provision.index("if (system) {"), provision.index("install(root, chosen);"))

    def test_launch_hands_eden_a_driver_only_in_auto_mode(self):
        launch = method(PROVISIONER.read_text(),
                        "    static String prepareLaunch(Context context, String engineId)")
        self.assertIn("MODE_AUTO.equals(mode(context))", launch)
        self.assertIn("android.system.Os.unsetenv(ENV_DIR);", launch)


if __name__ == "__main__":
    unittest.main()
