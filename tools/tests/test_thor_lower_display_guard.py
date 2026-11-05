"""Thor lower-display guard: parser parity with the Python check, daemon limits, start logic (no device)."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import thor_lower_display_guard as GUARD  # noqa: E402
import thor_lower_display_repair as REPAIR  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "test_thor_lower_display_repair", ROOT / "tools/tests/test_thor_lower_display_repair.py")
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)
JAVA_DIR = ROOT / "tools/thor_lower_display"
JAVA = Path(os.environ.get(
    "JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


@unittest.skipUnless((JAVA / "javac").exists(), "no JDK")
class ParserParityTest(unittest.TestCase):
    """The daemon's Java reading must agree with thor_lower_display_repair.py."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="lower-state-")
        subprocess.run([str(JAVA / "javac"), "-d", cls.work, str(JAVA_DIR / "LowerDisplayState.java")],
                       check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def java(self, dump):
        result = subprocess.run([str(JAVA / "java"), "-cp", self.work, "LowerDisplayState"],
                                input=dump, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def assert_parity(self, dump):
        display_id, info = REPAIR.lower_display(dump)
        fields = self.java(dump).split("|")
        self.assertEqual(fields[0], display_id)
        self.assertEqual(fields[1], info["mode"])
        self.assertEqual(fields[2], str(info["renderSurface"]).replace("None", "null"))
        self.assertEqual(fields[3], str(info["clientTarget"]).replace("None", "null"))
        self.assertEqual(fields[4], str(info["layerStack"]).replace("None", "null"))
        self.assertEqual(fields[6], "; ".join(REPAIR.problems(info)))

    def test_squeezed(self):
        self.assert_parity(FIXTURES.dump("1080x1920", "1080x1920"))

    def test_resized_with_a_stale_client_target(self):
        self.assert_parity(FIXTURES.dump("1080x1240", "1080x1920"))

    def test_healthy(self):
        self.assert_parity(FIXTURES.dump("1080x1240", "1080x1240", 0))
        self.assertTrue(self.java(FIXTURES.dump("1080x1240", "1080x1240")).endswith("|false|"))

    def test_asleep_is_reported_as_asleep(self):
        asleep = FIXTURES.dump("1080x1920", "1080x1920").replace("layerStack=4 ", "layerStack=4294967295 ")
        self.assertEqual(self.java(asleep).split("|")[5], "true")

    def test_separate_dumpsys_sections_joined(self):
        # The daemon reads --displays and --comp-displays and joins them.
        dump = FIXTURES.dump("1080x1920", "1080x1920")
        physical = dump.index(f"Display {FIXTURES.UPPER} (physical")
        joined = dump[:physical] + "\n" + dump[physical:]
        self.assert_parity(joined)

    def test_no_lower_display(self):
        only_upper = FIXTURES.dump("1080x1240", "1080x1240").split(f"Display {FIXTURES.LOWER} (internal")[0]
        self.assertEqual(self.java(only_upper), "none")

    def test_recorded_dumps_when_present(self):
        evidence = ROOT / "docs/qa/thor-lower-display-2026-11-05"
        if not evidence.is_dir():
            self.skipTest("local QA evidence not present")
        for path in evidence.glob("**/*surfaceflinger*.txt"):
            self.assert_parity(path.read_text(errors="replace"))


class DaemonLimitsTest(unittest.TestCase):
    def test_guard_never_touches_panel_power_or_brightness(self):
        source = (JAVA_DIR / "LowerDisplayGuard.java").read_text()
        for forbidden in ("setDisplayPowerMode", "setDisplayBrightness", "PowerManager", "screen_brightness"):
            self.assertNotIn(forbidden, source)

    def test_guard_waits_on_events_and_does_not_poll(self):
        source = (JAVA_DIR / "LowerDisplayGuard.java").read_text()
        self.assertNotIn("Thread.sleep", source)
        self.assertNotIn("scheduleAtFixedRate", source)
        check = source[source.index("private static void check("):source.index("/** One row short")]
        # The only re-arm inside a check is the bounded retry after a failed repair.
        self.assertEqual(check.count("postDelayed"), 1)
        self.assertIn("retries++ < MAX_RETRIES", check)

    def test_refresh_changes_do_not_cause_dumps(self):
        source = (JAVA_DIR / "LowerDisplayGuard.java").read_text()
        changed = source[source.index("public void onDisplayChanged"):source.index("Class<?> global")]
        self.assertIn("previous != state", changed)

    def test_repair_order_matches_the_host_tool(self):
        source = (JAVA_DIR / "LowerDisplayGuard.java").read_text()
        repair = source[source.index("private static void repair("):source.index("/** What the firmware did")]
        self.assertLess(repair.index("height - 1"), repair.index("setSize(id, width, height)"))
        self.assertEqual(repair.count("clientFrame"), 2)

    def test_supervisor_stops_only_on_duplicate(self):
        self.assertIn('[ "$?" = 3 ] && exit 0', GUARD.SUPERVISOR)
        self.assertIn(f"--nice-name={GUARD.NAME}", GUARD.SUPERVISOR)
        self.assertIn("EXIT_ALREADY_RUNNING = 3", (JAVA_DIR / "LowerDisplayGuard.java").read_text())


class FakeDevice:
    def __init__(self, running=False, processes=""):
        self.running = running
        self.processes = processes
        self.calls = []

    def run(self, *args, check=True):
        self.calls.append(args)
        command = args[-1]
        if "getprop sys.boot_completed" in command:
            return "1\n"
        if "pidof" in command:
            return "1234\n" if self.running else ""
        if "setsid" in command:
            self.running = True
            return ""
        if command.startswith("ps "):
            return self.processes
        return ""

    def launches(self):
        return [call for call in self.calls if "setsid" in call[-1]]


class StartLogicTest(unittest.TestCase):
    def setUp(self):
        self.install = GUARD.install_files
        self.sleep = GUARD.time.sleep
        GUARD.time.sleep = lambda seconds: None

    def tearDown(self):
        GUARD.install_files = self.install
        GUARD.time.sleep = self.sleep

    def test_running_and_current_is_left_alone(self):
        GUARD.install_files = lambda device: False
        device = FakeDevice(running=True)
        self.assertEqual(GUARD.start(device), 0)
        self.assertEqual(device.launches(), [])

    def test_stopped_guard_is_launched_detached(self):
        GUARD.install_files = lambda device: False
        device = FakeDevice()
        self.assertEqual(GUARD.start(device), 0)
        launch = device.launches()[0][-1]
        self.assertIn("setsid", launch)
        self.assertIn("</dev/null", launch)

    def test_missing_toolchain_uses_the_device_copy(self):
        def fail(device):
            raise OSError("no javac")
        GUARD.install_files = fail
        device = FakeDevice()
        self.assertEqual(GUARD.start(device), 0)
        self.assertEqual(len(device.launches()), 1)

    def test_stop_kills_exact_pids_only(self):
        # pkill -f would match its own adb shell and stop before reaching the guard.
        processes = f"""  PID NAME ARGS
  10 sh sh {GUARD.DEVICE_SCRIPT}
  11 {GUARD.NAME} {GUARD.NAME}
  12 sh sh -c ps -A -o PID,NAME,ARGS
  13 ps ps -A -o PID,NAME,ARGS
"""
        device = FakeDevice(processes=processes)
        GUARD.stop(device)
        kills = [call[-1] for call in device.calls if call[-1].startswith("kill")]
        self.assertEqual(kills, ["kill 10 11"])
        tool = (ROOT / "tools/thor_lower_display_guard.py").read_text()
        self.assertNotIn('"pkill', tool)

    def test_watcher_starts_on_each_arrival_only(self):
        class Tracker:
            stdout = iter(["0000\n", "0018427c87b2\toffline\n", "0017427c87b2\tdevice\n",
                           "0017427c87b2\tdevice\n", "0000\n", "0017427c87b2\tdevice\n"])

            def wait(self):
                pass

        class Done(Exception):
            pass

        def stop_after_stream(seconds):
            raise Done()

        device = FakeDevice()
        device.base = ["adb", "-s", "427c87b2"]
        arrivals = []
        popen, ensure = GUARD.subprocess.Popen, GUARD.ensure_running
        GUARD.subprocess.Popen = lambda *args, **kwargs: Tracker()
        GUARD.ensure_running = arrivals.append
        GUARD.time.sleep = stop_after_stream
        try:
            with self.assertRaises(Done):
                GUARD.watch(device)
        finally:
            GUARD.subprocess.Popen, GUARD.ensure_running = popen, ensure
        self.assertEqual(len(arrivals), 2)

    def test_launchd_job_does_not_depend_on_the_checked_out_branch(self):
        text = GUARD.plist_text()
        self.assertIn(str(GUARD.LAUNCH_HOME), text)
        self.assertNotIn("Code/emufusion", text.split("<dict>")[1])


if __name__ == "__main__":
    unittest.main()
