#!/usr/bin/env python3
"""Capture isolated launch evidence on a disposable Android emulator only.

This is a boot survey, NOT gameplay/performance acceptance. A successful `am
start`, live PID or frame counter must never be relabeled a gameplay pass.
No app data, ROMs or saves are removed. Each case force-stops only the test app.
Inspect the captured screenshots and logs before interpreting each outcome.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

PACKAGE = "com.thorium.preview"
ACTIVITY = PACKAGE + "/org.pegasus_frontend.android.MainActivity"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dwell", type=int, default=25)
    args = parser.parse_args()
    if not re.fullmatch(r"emulator-\d+", args.serial):
        parser.error("Only a disposable emulator-* serial is permitted")
    if not 5 <= args.dwell <= 60:
        parser.error("dwell must be between 5 and 60 seconds")
    base = [str(args.adb), "-s", args.serial]

    def adb(*command, check=True):
        return subprocess.run(base + list(command), capture_output=True,
                              check=check, timeout=45)

    if adb("shell", "getprop", "ro.kernel.qemu").stdout.strip() != b"1":
        raise RuntimeError("Target did not identify itself as an emulator")
    args.output.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.cases.read_text())
    results = []
    for index, case in enumerate(cases):
        system, engine, path = case["system"], case["engine"], case["path"]
        if not re.fullmatch(r"[a-z0-9-]+", system):
            raise ValueError("Unsafe case identifier")
        folder = args.output / f"{index + 1:02d}-{system}"
        folder.mkdir()
        adb("shell", "test -f " + shlex.quote(path))
        adb("shell", "am", "force-stop", PACKAGE)
        log_file = (folder / "runtime.log").open("wb")
        logger = subprocess.Popen(base + ["logcat", "-v", "threadtime", "-T", "1"],
                                  stdout=log_file, stderr=subprocess.DEVNULL)
        try:
            command = ["am", "start", "-W", "-n", ACTIVITY,
                       "-a", PACKAGE + ".LAUNCH_INTERNAL_GAME",
                       "--activity-single-top", "--activity-clear-top",
                       "--es", "path", path, "--es", "system_id", system,
                       "--es", "engine_id", engine, "--es", "title", case["title"]]
            if system not in ("wiiu",):
                command += ["--ez", "qualification_only", "true", "--es",
                            "qualification_session", "qa-48cc806d21554c70b70d96ec7d6feb90"]
            started = time.monotonic()
            launch = adb("shell", shlex.join(command), check=False)
            (folder / "launch.txt").write_bytes(launch.stdout + launch.stderr)
            for stamp in (5, args.dwell):
                time.sleep(max(0, started + stamp - time.monotonic()))
                screen = adb("exec-out", "screencap", "-p", check=False)
                if screen.returncode == 0:
                    (folder / f"screen-{stamp}s.png").write_bytes(screen.stdout)
            pid = adb("shell", "pidof", PACKAGE, check=False).stdout.decode().strip()
            result = {**case, "launch_returncode": launch.returncode,
                      "final_pid": pid, "status": "captured_requires_review",
                      "gameplay_pass": False, "evidence": str(folder)}
            results.append(result)
            (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(json.dumps({"case": index + 1, "total": len(cases), **result}), flush=True)
        finally:
            logger.terminate()
            logger.wait(timeout=10)
            log_file.close()
            adb("shell", "am", "force-stop", PACKAGE, check=False)


if __name__ == "__main__":
    main()
