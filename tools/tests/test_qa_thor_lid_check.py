from pathlib import Path
import subprocess
import sys
import unittest

from tools.qa_thor_lid_check import lid_state

ROOT = Path(__file__).resolve().parents[2]


def snapshot(value):
    return ("EventHub state:\n    5: hall_switch\n      Classes: SWITCH\n"
            "  Device 9: unrelated_switch\n    SwitchValues: 0\n"
            "  Device 5: hall_switch\n    Switch Input Mapper:\n"
            f"      SwitchValues: {value}\n  Configuration:\n")


class ThorLidCheckTest(unittest.TestCase):
    def test_open_and_closed_and_other_bits(self):
        for value, expected in (("0", "open"), ("1", "closed"),
                                ("00000000", "open"), ("0x1", "closed"),
                                ("10", "open"), ("11", "closed")):
            with self.subTest(value=value):
                self.assertEqual(expected, lid_state(snapshot(value)))

    def test_unknown_or_conflicting_state_never_opens(self):
        for dump in ("", "permission denied", snapshot("bad-value"),
                     snapshot("1") + snapshot("0"),
                     snapshot("1").replace("hall_switch", "unidentified")):
            with self.subTest(dump=dump):
                self.assertEqual("unknown", lid_state(dump))

    def test_cli_refuses_closed_and_unknown_without_device_commands(self):
        for dump, code in ((snapshot("0"), 0), (snapshot("1"), 3), ("", 3)):
            result = subprocess.run([sys.executable, str(ROOT / "tools/qa_thor_lid_check.py")],
                                    input=dump, text=True, capture_output=True, timeout=5)
            self.assertEqual(code, result.returncode, result.stderr)

    def test_guard_preflight_precedes_all_device_mutations(self):
        source = (ROOT / "tools/qa_oled_timeout.sh").read_text()
        check = source.index('qa_thor_lid_check.py')
        for mutation in ('shell mktemp', '"$adb_bin" -s 427c87b2 push',
                         'shell "nohup', 'shell settings put'):
            self.assertLess(check, source.index(mutation))


if __name__ == "__main__":
    unittest.main()
