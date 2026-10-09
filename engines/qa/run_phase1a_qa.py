#!/usr/bin/env python3
"""Run Phase 1A core operability checks on an Android ARM64 emulator.

The script deliberately refuses physical devices. It builds the tiny probe,
stages redistributable fixtures, executes each available core, and writes
machine-readable evidence under engines/build/qa-results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "engines" / "build"
CORE_DIR = BUILD / "arm64-v8a"
FIXTURE_DIR = BUILD / "qa-fixtures"
FIRMWARE_DIR = BUILD / "firmware"
FIRMWARE_MANIFEST = ROOT / "engines" / "firmware" / "manifest.json"
QA_BUILD = BUILD / "qa"
DEFAULT_RESULTS = BUILD / "qa-results"
REMOTE = "/data/local/tmp/lucent-phase1a-qa"


class TestCase:
    def __init__(self, system: str, display_name: str, core: str | None,
                 fixture: str | None, blocked_reason: str | None = None,
                 state_cycles: int = 100,
                 firmware: tuple[str, ...] = (),
                 require_input_effect: bool = False):
        self.system = system
        self.display_name = display_name
        self.core = core
        self.fixture = fixture
        self.blocked_reason = blocked_reason
        self.state_cycles = state_cycles
        self.firmware = firmware
        self.require_input_effect = require_input_effect


CASES = (
    TestCase("nes", "NES", "mesen", "lucent-callback-test.nes"),
    TestCase("snes", "SNES", "mesen-s", "lucent-callback-test.sfc"),
    TestCase("gb", "Game Boy", "sameboy", "dmg-acid2.gb"),
    TestCase("gbc", "Game Boy Color", "sameboy", "cgb-acid2.gbc"),
    TestCase("gba", "Game Boy Advance", "mgba", "mgba-2d-wrap-test.gba"),
    TestCase("sg1000", "SG-1000", "gearsystem", "lucent-callback-test.sg"),
    TestCase("mastersystem", "Master System", "gearsystem", "lucent-callback-test.sms"),
    TestCase("gamegear", "Game Gear", "gearsystem", "lucent-callback-test.gg"),
    TestCase(
        "colecovision", "ColecoVision", "gearcoleco",
        "lucent-firmware-gate-test.col",
        "The candidate minimal BIOS has adjacent GPL source, but its pinned upstream build instructions do not reproduce the packaged ROM; no firmware identity is accepted for qualification.",
    ),
    TestCase(
        "intellivision", "Intellivision", "freeintv", "4-tris.rom",
        "No clearly licensed, source-auditable replacement exists for the required exec.bin and grom.bin firmware; proprietary originals and binary-only substitutes are excluded from QA.",
    ),
    TestCase("psx", "PlayStation", "swanstation", "lucent-callback-test.psexe"),
    TestCase("nds", "Nintendo DS", "melonds-ds", "melonds-homebrew-periph-slot2.nds", state_cycles=100),
    TestCase("zxspectrum", "ZX Spectrum", "fuse", "lucent-visible-test.sna"),
    TestCase("arcade", "Arcade", "mame", "pong.cmd", state_cycles=100),
    TestCase("neogeo", "Neo Geo", "mame", "ngdevkit-open.cmd", state_cycles=100),
    TestCase("dos", "DOS", "dosbox-pure", "lucent-dos-callback-test.zip",
             state_cycles=100),
    TestCase("windows", "Windows / PC", "dosbox-pure",
             "emufusion-internal-pc-callback-test.zip", state_cycles=100),
    TestCase("pcengine", "PC Engine", "beetle-pce-fast", "lucent-pce-qa.pce",
             require_input_effect=True),
    TestCase(
        "pcenginecd", "PC Engine CD", "beetle-pce-fast", None,
        "Needs the owner's own system card (syscard3.pce) and a CD image; neither can be redistributed, so this bundled matrix cannot run it. The PcEngineCdFirmware importer is covered by its own tests.",
    ),
    TestCase("ngp", "Neo Geo Pocket Color", "beetle-neopop", "stargunner.ngc",
             require_input_effect=True),
    TestCase("wonderswancolor", "WonderSwan Color", "beetle-cygne", "bug-witch.wsc",
             require_input_effect=True),
    TestCase(
        "amstradcpc", "Amstrad CPC", "caprice32", None,
        "Caprice32 is GPL-2.0-only and is excluded from the GPLv3 Lucent aggregate until license compatibility is resolved.",
    ),
    TestCase(
        "atari2600", "Atari 2600", "stella-2023", None,
        "Stella 2023 is GPL-2.0-only and is excluded from the GPLv3 Lucent aggregate until license compatibility is resolved.",
    ),
    TestCase(
        "atari5200", "Atari 5200", "atari800", None,
        "Atari800 is GPL-2.0-only and is excluded from the GPLv3 Lucent aggregate until license compatibility is resolved.",
    ),
    TestCase(
        "atari7800", "Atari 7800", "prosystem", None,
        "The pinned ProSystem core is reproducible, but no redistributable visible-output Atari 7800 fixture has been qualified.",
    ),
    TestCase(
        "atari800", "Atari 8-bit", "atari800", None,
        "Atari800 is GPL-2.0-only and is excluded from the GPLv3 Lucent aggregate until license compatibility is resolved.",
    ),
    TestCase(
        "atarist", "Atari ST", "hatari", None,
        "Hatari is GPL-2.0-only and requires user firmware; it remains excluded until license and firmware qualification are complete.",
    ),
    TestCase(
        "c64", "Commodore 64", "vice-x64sc", None,
        "VICE is GPL-2.0-only and its ROM-data policy is unresolved, so it is excluded from the GPLv3 Lucent aggregate.",
    ),
    TestCase(
        "megadrive", "Mega Drive / Genesis", "blastem", None,
        "The pinned GPL-compatible BlastEm build awaits a redistributable fixture and physical menu-driven qualification.",
    ),
    TestCase(
        "msx", "MSX", "bluemsx", None,
        "blueMSX has a mixed source/data license closure and required machine databases that are not qualified for redistribution.",
    ),
    TestCase(
        "n64", "Nintendo 64", "mupen64plus-next", None,
        "The pinned Mupen64Plus-Next GLES3 build awaits a redistributable fixture and physical menu-driven qualification.",
    ),
    TestCase(
        "odyssey2", "Odyssey2 / Videopac", "o2em", None,
        "O2EM's Artistic-1.0 compatibility and required firmware/data closure are unresolved.",
    ),
    TestCase(
        "sega32x", "Sega 32X", "picodrive", None,
        "PicoDrive has a mixed, unresolved source-license closure and is excluded from the Lucent aggregate.",
    ),
    TestCase(
        "segacd", "Sega CD", "picodrive", None,
        "PicoDrive has a mixed, unresolved source-license closure; Sega CD also requires user firmware.",
    ),
    TestCase(
        "virtualboy", "Virtual Boy", "beetle-vb", None,
        "The Beetle Virtual Boy build includes a SoftFloat-2b license combination that has not been cleared for Lucent distribution.",
    ),
    TestCase(
        "neogeocd", "Neo Geo CD", None, None,
        "Pinned MAME requires a user-supplied Neo Geo CD/CDZ BIOS set (main BIOS plus 000-lo.lo) and a valid user-provided disc image; none is redistributable in QA.",
    ),
)


def run(command: list[str], *, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=check, capture_output=True, text=text)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_sdk() -> Path:
    candidates = [
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        str(ROOT.parent / "cemu" / "Cemu-0.5" / "android-sdk"),
        str(Path.home() / "Library" / "Android" / "sdk"),
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "platform-tools" / "adb").is_file():
            return Path(candidate)
    raise SystemExit("Android SDK not found; set ANDROID_SDK_ROOT")


def find_ndk(sdk: Path) -> Path:
    requested = os.environ.get("ANDROID_NDK_ROOT")
    if requested and Path(requested).is_dir():
        return Path(requested)
    pinned = sdk / "ndk" / "27.0.12077973"
    if pinned.is_dir():
        return pinned
    raise SystemExit("Android NDK 27.0.12077973 not found; set ANDROID_NDK_ROOT")


def select_emulator(adb: Path, requested: str | None) -> str:
    listing = run([str(adb), "devices"]).stdout.splitlines()[1:]
    online = [line.split()[0] for line in listing if line.strip().endswith("\tdevice")]
    serial = requested or os.environ.get("LUCENT_QA_SERIAL")
    if serial:
        if serial not in online:
            raise SystemExit(f"requested Android emulator is not online: {serial}")
    else:
        emulators = [item for item in online if item.startswith("emulator-")]
        if len(emulators) != 1:
            raise SystemExit("set --serial or LUCENT_QA_SERIAL when exactly one emulator is not online")
        serial = emulators[0]
    if not serial.startswith("emulator-"):
        raise SystemExit(f"refusing non-emulator Android target: {serial}")
    qemu = run([str(adb), "-s", serial, "shell", "getprop", "ro.kernel.qemu"]).stdout.strip()
    if qemu != "1":
        raise SystemExit(f"refusing target without ro.kernel.qemu=1: {serial}")
    abi = run([str(adb), "-s", serial, "shell", "getprop", "ro.product.cpu.abi"]).stdout.strip()
    if abi != "arm64-v8a":
        raise SystemExit(f"QA requires an arm64-v8a emulator, got {abi}")
    return serial


def compile_probe(ndk: Path) -> tuple[Path, Path]:
    host = "darwin-x86_64" if sys.platform == "darwin" else "linux-x86_64"
    toolchain = ndk / "toolchains" / "llvm" / "prebuilt" / host
    clang = toolchain / "bin" / "aarch64-linux-android23-clang"
    runtime = toolchain / "sysroot" / "usr" / "lib" / "aarch64-linux-android" / "libc++_shared.so"
    if not clang.is_file() or not runtime.is_file():
        raise SystemExit(f"incomplete NDK toolchain under {toolchain}")
    QA_BUILD.mkdir(parents=True, exist_ok=True)
    probe = QA_BUILD / "libretro_probe"
    run([
        str(clang), "-std=c11", "-O2", "-fPIE", "-pie",
        "-I", str(ROOT / "unified-android" / "native" / "include"),
        str(ROOT / "engines" / "qa" / "libretro_probe.c"), "-ldl", "-lm",
        "-o", str(probe),
    ])
    return probe, runtime


def adb_run(adb: Path, serial: str, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return run([str(adb), "-s", serial, *arguments], check=check, text=False)


def decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").replace("\r\n", "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", help="Android emulator serial (physical devices are refused)")
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--build-runnable", action="store_true", help="rebuild every available core first")
    parser.add_argument("--system", action="append",
                        choices=[case.system for case in CASES],
                        help="run only this system after validating the complete matrix")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.frames < 8:
        parser.error("--frames must be at least 8")

    sdk = find_sdk()
    ndk = find_ndk(sdk)
    adb = sdk / "platform-tools" / "adb"
    serial = select_emulator(adb, args.serial)

    selected_cases = tuple(
        case for case in CASES if not args.system or case.system in set(args.system)
    )
    if args.build_runnable:
        run([sys.executable, str(ROOT / "engines" / "qa" / "build_neogeo_open_fixture.py")])
        run([sys.executable, str(ROOT / "engines" / "qa" / "build_open_newcore_fixtures.py")])
        for core in sorted({
            case.core for case in selected_cases
            if case.core and not case.blocked_reason
        }):
            run([str(ROOT / "engines" / "build_core.sh"), core])
    run([sys.executable, str(ROOT / "engines" / "qa" / "generate_fixtures.py")])
    fixture_manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text())
    fixtures = {entry["file"]: entry for entry in fixture_manifest["fixtures"]}
    firmware_manifest = json.loads(FIRMWARE_MANIFEST.read_text())
    firmware = {
        f'{entry["engineId"]}/{entry["file"]}': entry
        for entry in firmware_manifest["firmware"]
    }
    for firmware_id in sorted({item for case in selected_cases for item in case.firmware}):
        metadata = firmware.get(firmware_id)
        if metadata is None:
            raise SystemExit(f"firmware is not present in the audited manifest: {firmware_id}")
        engine_id = firmware_id.split("/", 1)[0]
        path = FIRMWARE_DIR / firmware_id
        if not path.is_file():
            run([str(ROOT / "engines" / "firmware" / "fetch_open_firmware.sh"), engine_id])
        if sha256(path) != metadata["sha256"]:
            raise SystemExit(f"staged firmware checksum mismatch: {path}")
    probe, cpp_runtime = compile_probe(ndk)

    adb_run(adb, serial, "shell", "rm", "-rf", REMOTE)
    adb_run(adb, serial, "shell", "mkdir", "-p", f"{REMOTE}/cores", f"{REMOTE}/fixtures", f"{REMOTE}/system", f"{REMOTE}/save")
    adb_run(adb, serial, "push", str(probe), f"{REMOTE}/probe")
    adb_run(adb, serial, "push", str(cpp_runtime), f"{REMOTE}/libc++_shared.so")
    adb_run(adb, serial, "shell", "chmod", "755", f"{REMOTE}/probe")

    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    pushed_cores: set[str] = set()
    pushed_fixtures: set[str] = set()
    pushed_firmware: set[str] = set()
    for case in selected_cases:
        record: dict[str, object] = {"system": case.system, "displayName": case.display_name}
        if case.blocked_reason:
            record.update(
                status="BLOCKED",
                reason=case.blocked_reason,
                core=case.core,
                fixture=fixtures.get(str(case.fixture)),
                firmware=[],
                probe=None,
            )
            records.append(record)
            print(f"BLOCKED {case.display_name}")
            continue
        if case.core is None:
            record.update(status="BLOCKED", reason=case.blocked_reason, probe=None)
            records.append(record)
            continue

        core_path = CORE_DIR / f"{case.core}_libretro.so"
        fixture_path = FIXTURE_DIR / str(case.fixture)
        fixture_metadata = fixtures.get(str(case.fixture), {})
        support_paths = [
            FIXTURE_DIR / str(entry["file"])
            for entry in fixture_metadata.get("supportFiles", [])
        ]
        required_paths = [core_path, fixture_path, *support_paths]
        if not fixture_metadata:
            record.update(
                status="BLOCKED",
                reason=f"fixture is absent from the audited manifest: {case.fixture}",
                probe=None,
            )
            records.append(record)
            continue
        missing_paths = [path for path in required_paths if not path.is_file()]
        if missing_paths:
            missing = missing_paths[0]
            record.update(status="BLOCKED", reason=f"required QA artifact is missing: {missing.relative_to(ROOT)}", probe=None)
            records.append(record)
            continue
        if sha256(fixture_path) != fixture_metadata["sha256"]:
            raise SystemExit(f"fixture checksum mismatch: {fixture_path}")
        for metadata, support_path in zip(
            fixture_metadata.get("supportFiles", []), support_paths
        ):
            if sha256(support_path) != metadata["sha256"]:
                raise SystemExit(f"fixture support checksum mismatch: {support_path}")
        if case.core not in pushed_cores:
            adb_run(adb, serial, "push", str(core_path), f"{REMOTE}/cores/{core_path.name}")
            pushed_cores.add(case.core)
        if case.fixture not in pushed_fixtures:
            adb_run(adb, serial, "push", str(fixture_path), f"{REMOTE}/fixtures/{fixture_path.name}")
            pushed_fixtures.add(str(case.fixture))
        for support_path in support_paths:
            support_name = support_path.name
            if support_name not in pushed_fixtures:
                adb_run(adb, serial, "push", str(support_path),
                        f"{REMOTE}/fixtures/{support_name}")
                pushed_fixtures.add(support_name)
        case_firmware: list[dict[str, object]] = []
        for firmware_id in case.firmware:
            metadata = firmware[firmware_id]
            firmware_path = FIRMWARE_DIR / firmware_id
            remote_name = metadata["file"]
            if firmware_id not in pushed_firmware:
                adb_run(adb, serial, "push", str(firmware_path),
                        f"{REMOTE}/system/{remote_name}")
                pushed_firmware.add(firmware_id)
            case_firmware.append(metadata)

        input_gate = "export LUCENT_PROBE_REQUIRE_INPUT_EFFECT=1 && " \
            if case.require_input_effect else ""
        command = (
            f"cd {REMOTE} && export LD_LIBRARY_PATH={REMOTE} && {input_gate}"
            f"./probe cores/{core_path.name} fixtures/{fixture_path.name} system save "
            f"{args.frames} {case.state_cycles}"
        )
        completed = adb_run(adb, serial, "shell", command, check=False)
        stdout = decode(completed.stdout)
        stderr = decode(completed.stderr)
        log_path = args.output / f"{case.system}.log"
        log_path.write_text(stderr + stdout, encoding="utf-8")
        payload = None
        for line in reversed(stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "result" in candidate:
                payload = candidate
                break
        if payload is None:
            status, reason = "FAIL", f"probe produced no JSON result (exit {completed.returncode})"
        elif completed.returncode == 0 and payload.get("result") == "PASS":
            status, reason = "PASS", None
        else:
            status, reason = "FAIL", f"callback/state probe failed (exit {completed.returncode})"
        record.update(
            status=status,
            reason=reason,
            core=case.core,
            coreSha256=sha256(core_path),
            fixture=fixture_metadata,
            firmware=case_firmware,
            probe=payload,
            probeExitCode=completed.returncode,
            log=str(log_path.relative_to(ROOT)),
        )
        records.append(record)
        print(f"{status:7} {case.display_name}")

    counts = {status: sum(item["status"] == status for item in records) for status in ("PASS", "FAIL", "BLOCKED")}
    report = {
        "schemaVersion": 1,
        "target": {"serial": serial, "abi": "arm64-v8a", "emulatorOnly": True},
        "frames": args.frames,
        "probeSha256": sha256(probe),
        "counts": counts,
        "systems": records,
    }
    report_path = args.output / "results.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence: {report_path}")
    print(f"summary: {counts}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
