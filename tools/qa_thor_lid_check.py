"""Read a Thor dumpsys-input snapshot from stdin; permit QA only with an open lid.

This is a QA preflight, not an emulator setting or a substitute for the OLED
deadline guard. Recheck immediately before each wake. Linux SW_LID is bit0:
https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes.h
"""
import re
import sys


def lid_state(snapshot):
    # InputReader's current Device blocks, not EventHub capability/inventory text.
    blocks = re.findall(
        r"^  Device \d+: hall_switch\r?\n(.*?)(?=^  Device \d+:|^  Configuration:|\Z)",
        snapshot, re.MULTILINE | re.DOTALL)
    if len(blocks) != 1:
        return "unknown"
    values = re.findall(r"^\s+SwitchValues: (?:0x)?([0-9a-fA-F]+)\s*$", blocks[0], re.MULTILINE)
    if len(values) != 1:
        return "unknown"
    return "closed" if int(values[0], 16) & 1 else "open"


if __name__ == "__main__":
    state = lid_state(sys.stdin.read())
    print("Thor lid preflight: " + state)
    if state != "open":
        print("Do not wake or start gameplay. Open the Thor, or resolve its lid-sensor state first.",
              file=sys.stderr)
    sys.exit(0 if state == "open" else 3)
