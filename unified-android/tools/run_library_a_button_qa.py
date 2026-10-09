#!/usr/bin/env python3
"""Prove that a real Thor A press launches library metadata in one EmuFusion task."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import time
from pathlib import Path
from typing import Optional

import run_phase1a_activity_qa as qa
from PIL import Image, ImageChops


ROUTE = re.compile(
    r"In-window route accepted engine=([^ ]+) system=([^\s]+)"
)


def press_a(adb_path: Path, serial: str, event_node: str) -> None:
    qa.send_linux_key(adb_path, serial, event_node, 304, hold_seconds=0.08)


def wait_for_route(adb_path: Path, serial: str, baseline: int,
                   expected_system: str, expected_engine: str) -> dict[str, object]:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        log = qa.logs(adb_path, serial)
        matches = list(ROUTE.finditer(log))
        if len(matches) > baseline:
            engine, system = matches[-1].groups()
            if (system, engine) != (expected_system, expected_engine):
                raise RuntimeError(
                    f"A launched {system}/{engine}, expected "
                    f"{expected_system}/{expected_engine}"
                )
            identity = qa.strict_gameplay_identity(adb_path, serial)
            if not identity:
                raise RuntimeError("A launch violated the one-window identity gate")
            return {"system": system, "engine": engine, "identity": identity}
        time.sleep(0.25)
    raise RuntimeError(f"physical A did not launch {expected_system}")


def launch_selected(adb_path: Path, serial: str, event_node: str,
                    system: str, engine: str,
                    *, open_system: bool = False,
                    evidence_dir: Optional[Path] = None) -> dict[str, object]:
    print(f"physical A route: opening {system}", flush=True)
    baseline = len(ROUTE.findall(qa.logs(adb_path, serial)))
    if open_system:
        press_a(adb_path, serial, event_node)  # Open the selected system.
        time.sleep(2.0)
    before_frame = None
    before_metrics = None
    if evidence_dir is not None:
        before_frame = evidence_dir / f"{system}-library-before-launch.png"
        before_metrics = qa.screenshot_metrics(
            adb_path, serial, before_frame
        )
    press_a(adb_path, serial, event_node)  # Open the selected real library game.
    record = wait_for_route(adb_path, serial, baseline, system, engine)
    print(f"PASS physical A route: {system}/{engine}", flush=True)
    record["controller"] = {"eventNode": event_node, "linuxKeyCode": 304}
    case = qa.Case(system, "library", engine, "selected")
    committed = f"Quick Resume committed engine={engine} system={system}"
    commit_baseline = qa.logs(adb_path, serial).count(committed)
    stop_result = qa.stop_hold_exit(adb_path, serial, case, [event_node])
    record["heldStop"] = stop_result

    if evidence_dir is not None and before_frame is not None:
        returned_frame = evidence_dir / f"{system}-library-immediate-return.png"
        returned_metrics = qa.screenshot_metrics(
            adb_path, serial, returned_frame
        )
        visual = library_frame_similarity(before_frame, returned_frame)
        if not returned_metrics["visible"] or not visual["sameLibraryComposition"]:
            raise RuntimeError(
                "held-Stop exposed a splash/progress frame instead of the prior library: "
                + repr({"metrics": returned_metrics, "similarity": visual})
            )
        record["immediateReturnPixels"] = {
            "before": str(before_frame),
            "after": str(returned_frame),
            "beforeMetrics": before_metrics,
            "afterMetrics": returned_metrics,
            **visual,
        }

    # Prove the restored Qt surface consumes navigation immediately rather
    # than presenting a hidden progress/interstitial layer. RIGHT then LEFT
    # returns the persisted selection to its original position.
    identity_before = qa.main_activity_identity(adb_path, serial)
    route_count = len(ROUTE.findall(qa.logs(adb_path, serial)))
    qa.adb(adb_path, serial, "shell", "input", "keyevent", "22")
    qa.adb(adb_path, serial, "shell", "input", "keyevent", "21")
    identity_after = qa.main_activity_identity(adb_path, serial)
    if identity_after != identity_before or not qa.frontend_is_resumed(adb_path, serial):
        raise RuntimeError("library did not accept immediate post-Stop navigation")
    if len(ROUTE.findall(qa.logs(adb_path, serial))) != route_count:
        raise RuntimeError("post-Stop navigation unexpectedly relaunched gameplay")
    record["immediateLibraryInput"] = {
        "rightThenLeftAccepted": True,
        "identityBefore": identity_before,
        "identityAfter": identity_after,
    }

    commit_log = qa.wait_for_new_log(
        adb_path, serial, committed, commit_baseline,
        "background Quick Resume commit after interactive library return",
    )
    qa.assert_no_crash(commit_log)
    record["backgroundSaveCommitted"] = True
    return record


def library_frame_similarity(before_path: Path, after_path: Path) -> dict[str, object]:
    """Reject the black EmuFusion/Pegasus reload splash using actual display pixels.

    Wallpaper/video content can advance while gameplay runs, so this is not a
    byte comparison. The downsampled mean absolute difference still separates
    the same library composition from the near-black centered progress splash.
    """
    before = Image.open(before_path).convert("RGB").resize((192, 108))
    after = Image.open(after_path).convert("RGB").resize((192, 108))
    difference = ImageChops.difference(before, after)
    samples = list(difference.getdata())
    mean_absolute = sum(sum(pixel) / 3.0 for pixel in samples) / max(1, len(samples))
    return {
        "meanAbsoluteDifference": round(mean_absolute, 4),
        "sameLibraryComposition": mean_absolute < 65.0,
    }


def move_cover_right(adb_path: Path, serial: str, steps: int) -> None:
    # Stop returns to the system's game view. B returns to the persisted cover
    # card, then DPAD_RIGHT moves across the deterministic system order.
    # The same Qt library surface is restored synchronously; post-return menu
    # input must not require a progress-screen settling delay.
    qa.adb(adb_path, serial, "shell", "input", "keyevent", "4")
    time.sleep(1.0)
    for _ in range(steps):
        qa.adb(adb_path, serial, "shell", "input", "keyevent", "22")
        time.sleep(0.25)


def metadata_evidence(adb_path: Path, serial: str) -> dict[str, list[str]]:
    roots = (
        "/storage/emulated/0/pegasus-frontend",
        "/storage/emulated/0/Android/data/org.pegasus_frontend.android/files/pegasus-frontend",
        "/storage/emulated/0/Android/data/com.thorium.preview/files/pegasus-frontend",
    )
    directories = [path for root in roots
                   for path in (root, root + "/metadata", root + "/metafiles",
                                root + "/metadata-systems")]
    command = (
        "find " + " ".join(directories) +
        " -maxdepth 1 -type f \\( -iname '*nes*.pegasus.txt' "
        "-o -iname '*gb*.pegasus.txt' -o -iname '*gamegear*.pegasus.txt' \\) "
        "-print 2>/dev/null"
    )
    paths = sorted(set(qa.adb(
        adb_path, serial, "shell", "sh", "-c", command, check=False
    ).stdout.splitlines()))
    expected = {"nes": "mesen", "gb": "sameboy", "gamegear": "gearsystem"}
    evidence: dict[str, list[str]] = {system: [] for system in expected}
    for path in paths:
        # Some legacy libraries contain multi-megabyte metadata files and even
        # invalid bytes in game titles. Transfer only collection header fields.
        header_command = (
            "awk '/^game:/{exit} /^(collection|shortname|launch):/{print}' " +
            shlex.quote(path)
        )
        text = qa.adb(adb_path, serial, "shell", "sh", "-c", header_command,
                      check=False).stdout
        blocks = re.split(r"(?=^collection:)", text, flags=re.M)
        for block in blocks:
            short = re.search(r"(?m)^shortname:\s*([^\s]+)", block)
            if short is None or short.group(1).lower() not in expected:
                continue
            system = short.group(1).lower()
            launches = re.findall(r"(?m)^launch:\s*(.+)$", block)
            if len(launches) != 1:
                raise RuntimeError(
                    f"{path} {system} has {len(launches)} collection launch routes"
                )
            command_text = launches[0]
            required = (
                "com.thorium.preview/org.pegasus_frontend.android.MainActivity",
                f"--es system {system}",
                f"--es engine_id {expected[system]}",
            )
            if not all(value in command_text for value in required):
                raise RuntimeError(f"{path} does not use Lucent's in-window route")
            evidence[system].append(path)
    missing = [system for system, paths_for_system in evidence.items()
               if not paths_for_system]
    if missing:
        raise RuntimeError("missing normalized launch metadata: " + ", ".join(missing))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-metadata-audit", action="store_true")
    parser.add_argument("--nes-only", action="store_true")
    args = parser.parse_args()

    sdk = qa.find_sdk()
    adb_path = sdk / "platform-tools" / "adb"
    serial, emulator_only = qa.select_target(adb_path, args.serial, True)
    if emulator_only:
        raise SystemExit("library A-button QA requires a verified AYN Thor")
    apk = args.apk.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, stat.S_IRWXU)

    qa.adb(adb_path, serial, "install", "--no-incremental", "-r", "-d", str(apk))
    qa.adb(adb_path, serial, "shell", "am", "force-stop", qa.PACKAGE)
    qa.adb(adb_path, serial, "logcat", "-c")
    qa.ensure_library(adb_path, serial)
    time.sleep(5.0)
    metadata: dict[str, list[str]] = {}
    if not args.skip_metadata_audit:
        print("auditing normalized launch metadata", flush=True)
        metadata = metadata_evidence(adb_path, serial)
        print("PASS normalized launch metadata", flush=True)
    event_node = qa.thor_controller_events(adb_path, serial)[0]

    report = {
        "apk": str(apk),
        "apkSha256": qa.sha256_file(apk),
        "metadata": metadata,
        "physicalAButtonLaunches": [],
        "counts": {"PASS": 0, "FAIL": 0},
    }

    def persist() -> None:
        (output / "results.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        (output / "current-activities.txt").write_text(
            qa.activity_dump(adb_path, serial), encoding="utf-8")
        (output / "current-windows.txt").write_text(
            qa.window_dump(adb_path, serial), encoding="utf-8")

    persist()

    records = report["physicalAButtonLaunches"]
    try:
        records.append(launch_selected(
            adb_path, serial, event_node, "nes", "mesen", open_system=True,
            evidence_dir=output))
        report["counts"]["PASS"] = len(records)
        persist()
        if not args.nes_only:
            move_cover_right(adb_path, serial, 2)  # NES -> Genesis -> Game Boy.
            records.append(launch_selected(
                adb_path, serial, event_node, "gb", "sameboy", open_system=True,
                evidence_dir=output))
            report["counts"]["PASS"] = len(records)
            persist()
            move_cover_right(adb_path, serial, 1)  # Game Boy -> Game Gear.
            records.append(launch_selected(
                adb_path, serial, event_node, "gamegear", "gearsystem",
                open_system=True, evidence_dir=output))
            report["counts"]["PASS"] = len(records)
            persist()
    except Exception as error:
        report["counts"]["PASS"] = len(records)
        report["counts"]["FAIL"] = 1
        report["failure"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        persist()
        raise

    report["counts"]["PASS"] = len(records)
    (output / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "final-activities.txt").write_text(
        qa.activity_dump(adb_path, serial), encoding="utf-8")
    (output / "final-windows.txt").write_text(
        qa.window_dump(adb_path, serial), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
