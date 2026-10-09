"""Read-only QA admission policy for a fresh `dumpsys battery` snapshot.

These are conservative test-start thresholds, not hardware safety ratings:
at least 20% charge, battery temperature below 43 C, present/healthy battery,
and real (not overridden) telemetry. This does not monitor an ongoing test.
"""
import re
import sys


def check_battery(snapshot):
    if "Current Battery Service state:" not in snapshot:
        return False, "missing Battery Service state"
    if re.search(r"updates\s+stopped", snapshot, re.IGNORECASE):
        return False, "battery telemetry is overridden; resolve it before QA"

    def field(name):
        values = re.findall(r"^\s*" + re.escape(name) + r":\s*(\S+)\s*$",
                            snapshot, re.MULTILINE)
        if len(values) != 1:
            raise ValueError("missing or ambiguous " + name)
        return values[0]

    try:
        if field("present") != "true":
            return False, "battery is not reported present"
        health = int(field("health"))
        status = int(field("status"))
        level = int(field("level"))
        scale = int(field("scale"))
        temperature = int(field("temperature"))
    except ValueError as error:
        return False, "invalid battery telemetry: " + str(error)
    if health != 2 or status not in (2, 3, 4, 5):
        return False, "battery health/status is not qualified for QA"
    if scale <= 0 or not 0 <= level <= scale or not 0 < temperature < 1000:
        return False, "battery telemetry is out of range"
    summary = f"{level * 100 / scale:.1f}% charge, {temperature / 10:.1f} C"
    if level * 100 < 20 * scale or temperature >= 430:
        return False, summary + "; QA requires at least 20% and below 43 C"
    return True, summary


if __name__ == "__main__":
    allowed, reason = check_battery(sys.stdin.read())
    print("Thor battery preflight: " + ("ready: " if allowed else "REFUSED: ") + reason)
    sys.exit(0 if allowed else 3)
