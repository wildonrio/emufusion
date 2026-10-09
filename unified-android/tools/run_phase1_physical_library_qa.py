#!/usr/bin/env python3
"""Qualify Phase 1 with real user content on one physical AYN Thor build.

The runner is deliberately non-destructive: it never copies, renames, deletes,
or prints user game paths. It validates file signatures, picks up to three
distinct titles per available Phase 1 system, and records only opaque case IDs
in the public result. The three open late-core fixtures are added so those
engines remain covered when a user's library has no matching content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import run_phase1a_activity_qa as qa


GAME_ROOT = "/storage/emulated/0/Games"
SYSTEMS = {
    "nes": ("mesen", {".nes"}),
    "snes": ("mesen-s", {".sfc", ".smc"}),
    "gb": ("sameboy", {".gb"}),
    "gbc": ("sameboy", {".gbc"}),
    "gba": ("mgba", {".gba"}),
    "gamegear": ("gearsystem", {".gg"}),
    "megadrive": ("blastem", {".md", ".gen", ".bin", ".smd"}),
    "n64": ("mupen64plus-next", {".z64", ".v64", ".n64"}),
    "psx": ("swanstation", {".chd"}),
    "nds": ("melonds-ds", {".nds"}),
}
ALL_PHASE1_SYSTEMS = tuple(dict.fromkeys(
    [case.system for case in qa.CASES] + list(SYSTEMS)
))
BAD_NAME_MARKERS = re.compile(
    r"(?:\b(?:beta|proto(?:type)?|sample|demo|trainer|bios|bad\s*dump|hack)\b|"
    r"\[[bht!]\]|\(hack\))", re.I
)

GB_LOGO = bytes.fromhex(
    "ce ed 66 66 cc 0d 00 0b 03 73 00 83 00 0c 00 0d "
    "00 08 11 1f 88 89 00 0e dc cc 6e e6 dd dd d9 99 "
    "bb bb 67 63 6e 0e ec cc dd dc 99 9f bb b9 33 3e"
)
GBA_LOGO = bytes.fromhex(
    "24 ff ae 51 69 9a a2 21 3d 84 82 0a 84 e4 09 ad "
    "11 24 8b 98 c0 81 7f 21 a3 52 be 19 93 09 ce 20 "
    "10 46 4a 4a f8 27 31 ec 58 c7 e8 33 82 e3 ce bf "
    "85 f4 df 94 ce 4b 09 c1 94 56 8a c0 13 72 a7 fc "
    "9f 84 4d 73 a3 ca 9a 61 58 97 a3 27 fc 03 98 76 "
    "23 1d c7 61 03 04 ae 56 bf 38 84 00 40 a7 0e fd "
    "ff 52 fe 03 6f 95 30 f1 97 fb c0 85 60 d6 80 25 "
    "a9 63 be 03 01 4e 38 e2 f9 a2 34 ff bb 3e 03 44 "
    "78 00 90 cb 88 11 3a 94 65 c0 7c 63 87 f0 3c af "
    "d6 25 e4 8b 38 0a ac 72 21 d4 f8 07"
)


def shell_output(adb_path: Path, serial: str, command: str,
                 *, binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        [str(adb_path), "-s", serial, "exec-out", "sh", "-c", command],
        check=True, capture_output=True, text=not binary,
    )
    return completed.stdout


def list_candidates(adb_path: Path, serial: str) -> list[str]:
    payload = shell_output(
        adb_path, serial,
        "find " + shlex.quote(GAME_ROOT) + " -type f -print0 2>/dev/null",
        binary=True,
    )
    return sorted(
        (part.decode("utf-8", errors="surrogateescape")
         for part in payload.split(b"\0") if part),
        key=lambda value: value.casefold(),
    )


def read_range(adb_path: Path, serial: str, path: str,
               offset: int, count: int) -> bytes:
    command = (f"dd if={shlex.quote(path)} bs=1 skip={offset} count={count} "
               "2>/dev/null")
    return shell_output(adb_path, serial, command, binary=True)


def file_size(adb_path: Path, serial: str, path: str) -> int:
    value = shell_output(
        adb_path, serial, "stat -c %s " + shlex.quote(path) + " 2>/dev/null"
    )
    return int(value.strip())


def valid_snes_header(adb_path: Path, serial: str, path: str) -> bool:
    size = file_size(adb_path, serial, path)
    copier = 512 if size % 0x8000 == 512 else 0
    for base in (0x7FC0, 0xFFC0, 0x40FFC0):
        offset = copier + base
        if size < offset + 32:
            continue
        header = read_range(adb_path, serial, path, offset, 32)
        if len(header) != 32:
            continue
        title = header[:21]
        if sum(32 <= byte < 127 or byte == 0 for byte in title) < 17:
            continue
        complement = int.from_bytes(header[28:30], "little")
        checksum = int.from_bytes(header[30:32], "little")
        if (complement ^ checksum) == 0xFFFF:
            return True
    return False


def valid_content(adb_path: Path, serial: str, system: str, path: str) -> bool:
    try:
        if system == "nes":
            return read_range(adb_path, serial, path, 0, 4) == b"NES\x1a"
        if system in {"gb", "gbc"}:
            return read_range(adb_path, serial, path, 0x104, 48) == GB_LOGO
        if system == "gba":
            return read_range(adb_path, serial, path, 4, 156) == GBA_LOGO
        if system == "gamegear":
            return any(read_range(adb_path, serial, path, offset, 8) == b"TMR SEGA"
                       for offset in (0x1FF0, 0x3FF0, 0x7FF0))
        if system == "megadrive":
            # Raw Genesis/Mega Drive dumps carry the SEGA hardware string in
            # the standard cartridge header. Interleaved SMD content is not
            # selected automatically: it must first be normalized by EmuFusion's
            # importer so this evidence path never trusts an extension alone.
            return (Path(path).suffix.casefold() != ".smd" and
                    read_range(adb_path, serial, path, 0x100, 4) == b"SEGA")
        if system == "n64":
            return read_range(adb_path, serial, path, 0, 4) in {
                bytes.fromhex("80 37 12 40"),  # native big-endian (.z64)
                bytes.fromhex("37 80 40 12"),  # byte-swapped (.v64)
                bytes.fromhex("40 12 37 80"),  # little-endian (.n64)
            }
        if system == "snes":
            return valid_snes_header(adb_path, serial, path)
        if system == "psx":
            return read_range(adb_path, serial, path, 0, 8) == b"MComprHD"
        if system == "nds":
            header = read_range(adb_path, serial, path, 0, 0x200)
            size = file_size(adb_path, serial, path)
            if len(header) != 0x200 or size < 0x4000:
                return False
            arm9_offset = int.from_bytes(header[0x20:0x24], "little")
            arm9_size = int.from_bytes(header[0x2C:0x30], "little")
            arm7_offset = int.from_bytes(header[0x30:0x34], "little")
            arm7_size = int.from_bytes(header[0x3C:0x40], "little")
            return (arm9_offset >= 0x200 and arm7_offset >= 0x200 and
                    0 < arm9_size <= size - arm9_offset and
                    0 < arm7_size <= size - arm7_offset)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False
    return False


def normalized_title_key(path: str) -> str:
    stem = Path(path).stem
    stem = re.sub(r"\s*[\[(].*?[\])]", "", stem)
    stem = re.sub(r"[^a-z0-9]+", " ", stem.casefold()).strip()
    return stem


def path_matches_system(system: str, path: str) -> bool:
    """Resolve extension collisions without trusting a filename as content ID."""
    if system != "psx":
        return True
    folders = [part.casefold() for part in Path(path).parts[:-1]]
    joined = " ".join(folders)
    return bool(re.search(
        r"(?:^|[^a-z0-9])(?:ps1|psx|playstation(?:\s*1)?)(?:[^a-z0-9]|$)",
        joined,
    )) and not re.search(r"playstation\s*[2345]|\bps[2345]\b", joined)


def select_user_cases(adb_path: Path, serial: str,
                      paths: list[str]) -> tuple[list[qa.Case], dict[str, str]]:
    selected: list[qa.Case] = []
    private_map: dict[str, str] = {}
    for system, (engine, extensions) in SYSTEMS.items():
        seen: set[str] = set()
        index = 0
        for path in paths:
            if Path(path).suffix.casefold() not in extensions:
                continue
            if not path_matches_system(system, path):
                continue
            if BAD_NAME_MARKERS.search(Path(path).name):
                continue
            key = normalized_title_key(path)
            if not key or key in seen or not valid_content(adb_path, serial, system, path):
                continue
            seen.add(key)
            index += 1
            opaque = hashlib.sha256(path.encode("utf-8", errors="surrogateescape")).hexdigest()[:12]
            case_id = f"user-title-{index:02d}-{opaque}"
            selected.append(qa.Case(system, case_id, engine, case_id, path))
            private_map[f"{system}/{case_id}"] = path
            if index == 3:
                break
    return selected, private_map


def stage_legal_fixtures(adb_path: Path, serial: str,
                         user_cases: list[qa.Case], output: Path) -> list[qa.Case]:
    qa.run([sys.executable, str(qa.ROOT / "engines" / "qa" /
                                "build_open_newcore_fixtures.py")])
    qa.run([sys.executable, str(qa.ROOT / "engines" / "qa" /
                                "generate_fixtures.py")])
    qa.adb(adb_path, serial, "shell", "mkdir", "-p", qa.REMOTE)
    user_systems = {case.system for case in user_cases}
    # A legal fixture fills every system absent from the user's library. The
    # three late Phase 1 cores are always fixture-qualified because the pinned
    # open content is also the artifact used by their native reproducibility
    # gate, making the physical and native evidence directly comparable.
    always_fixture = {"pcengine", "ngp", "wonderswancolor"}
    cases = [case for case in qa.CASES
             if case.system not in user_systems or case.system in always_fixture]
    fixture_manifest = json.loads(
        (qa.FIXTURES / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_by_file = {row["file"]: row for row in fixture_manifest["fixtures"]}
    pushed: set[str] = set()
    for case in cases:
        fixture = qa.FIXTURES / case.fixture
        staged = fixture
        if case.system == "neogeo":
            staged = output / case.fixture
            staged.write_text(
                fixture.read_text(encoding="utf-8").replace(
                    "/data/local/tmp/lucent-phase1a-qa/fixtures", qa.REMOTE
                ),
                encoding="utf-8",
            )
        qa.adb(adb_path, serial, "push", str(staged), f"{qa.REMOTE}/{case.fixture}")
        pushed.add(case.fixture)
        for support in manifest_by_file.get(case.fixture, {}).get("supportFiles", []):
            name = support["file"]
            if name in pushed:
                continue
            qa.adb(adb_path, serial, "push", str(qa.FIXTURES / name),
                   f"{qa.REMOTE}/{name}")
            pushed.add(name)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--system", action="append", choices=ALL_PHASE1_SYSTEMS,
        help=("run only the selected system; repeat for a targeted regression "
              "subset. Omit for the complete Phase 1 matrix."),
    )
    args = parser.parse_args()

    sdk = qa.find_sdk()
    adb_path = sdk / "platform-tools" / "adb"
    serial, emulator_only = qa.select_target(adb_path, args.serial, True)
    if emulator_only:
        raise SystemExit("physical-library QA requires a verified AYN Thor")
    apk = args.apk.resolve()
    if not apk.is_file():
        raise SystemExit(f"APK not found: {apk}")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    os.chmod(args.output, stat.S_IRWXU)

    # One install and one hash own the complete matrix. Never clear app or user data.
    qa.adb(adb_path, serial, "install", "--no-incremental", "-r", "-d", str(apk))
    for permission in (
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_AUDIO",
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
    ):
        qa.adb(adb_path, serial, "shell", "pm", "grant", qa.PACKAGE,
               permission, check=False)
    qa.adb(adb_path, serial, "shell", "appops", "set", "--uid", qa.PACKAGE,
           "MANAGE_EXTERNAL_STORAGE", "allow", check=False)

    user_cases, private_map = select_user_cases(
        adb_path, serial, list_candidates(adb_path, serial)
    )
    requested_systems = set(args.system or ())
    if requested_systems:
        user_cases = [case for case in user_cases
                      if case.system in requested_systems]
        private_map = {
            key: value for key, value in private_map.items()
            if key.split("/", 1)[0] in requested_systems
        }
    private_path = args.output / "selected-content-private.json"
    private_path.write_text(json.dumps(private_map, indent=2) + "\n", encoding="utf-8")
    os.chmod(private_path, stat.S_IRUSR | stat.S_IWUSR)
    cases = user_cases + stage_legal_fixtures(
        adb_path, serial, user_cases, args.output
    )
    if requested_systems:
        cases = [case for case in cases if case.system in requested_systems]

    records: list[dict[str, object]] = []
    for case in cases:
        try:
            record = qa.verify_case(
                adb_path, serial, case, args.output,
                require_preview_lifecycle=True,
                require_runtime_telemetry=True,
                require_stop_hold=True,
            )
        except Exception as failure:
            key = qa.evidence_key(case)
            (args.output / f"{key}-failure-activities.txt").write_text(
                qa.activity_dump(adb_path, serial), encoding="utf-8")
            (args.output / f"{key}-failure-windows.txt").write_text(
                qa.window_dump(adb_path, serial), encoding="utf-8")
            (args.output / f"{key}-failure-logcat.txt").write_text(
                qa.logs(adb_path, serial), encoding="utf-8")
            record = {
                "status": "FAIL", "system": case.system,
                "engine": case.engine, "fixture": case.fixture,
                "reason": str(failure),
            }
        records.append(record)
        print(f"{record['status']:4} {case.system} {case.fixture}", flush=True)
        (args.output / "results.partial.json").write_text(
            json.dumps({
                "apkSha256": qa.sha256_file(apk),
                "completed": len(records),
                "total": len(cases),
                "systems": records,
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    report = {
        "schemaVersion": 1,
        "target": {"serial": serial, "abi": "arm64-v8a", "model": "AYN Thor"},
        "apk": str(apk),
        "apkSha256": qa.sha256_file(apk),
        "oneApkForCompleteMatrix": not requested_systems,
        "selectedSystems": sorted(requested_systems),
        "userContentModified": False,
        "systems": records,
        "counts": {
            "PASS": sum(row["status"] == "PASS" for row in records),
            "FAIL": sum(row["status"] == "FAIL" for row in records),
        },
    }
    (args.output / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / "results.partial.json").unlink(missing_ok=True)
    return 1 if report["counts"]["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
