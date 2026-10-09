"""Summarize runtime admission evidence; never certify cadence or image quality."""
import argparse
import json
import re
from pathlib import Path


def summarize(lines):
    counters = {}
    activated_real = activated_generated = dropped_real = dropped_generated = 0
    proof_enabled = False
    for line in lines:
        if "Qualification proof generator=" in line and " enabled=true " in line:
            proof_enabled = True
        if "Native endpoint provenance generator=" in line:
            for name, value in re.findall(r"\badmission(\w+)=(\d+)", line):
                counters[name] = int(value)
        if "Private output activated presentId=" in line:
            if " generated=1 " in line:
                activated_generated += 1
            elif " generated=0 " in line:
                activated_real += 1
        if "External presentation not ready; slot dropped" in line:
            if " generated=1 " in line:
                dropped_generated += 1
            elif " generated=0 " in line:
                dropped_real += 1
    return {
        "qualificationSwitchObservedEnabled": proof_enabled,
        "loggedRealActivations": activated_real,
        "loggedGeneratedActivations": activated_generated,
        "loggedRealNotReadyDrops": dropped_real,
        "loggedGeneratedNotReadyDrops": dropped_generated,
        "lastAdmissionCounters": counters,
        "generatedActivationObserved": activated_generated > 0,
        "cadenceQualified": False,
        "imageQualityQualified": False,
        "limitations": "Activation logging is bounded; absence is not proof of no generation. "
        "Counters are attempts, not FPS. Use one process/generator run. "
        "Activation is not physical delivery or pixel-quality evidence.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    with args.log.open(errors="replace") as stream:
        print(json.dumps(summarize(stream), indent=2))
