#!/usr/bin/env python3
"""Exercise Phase 1A cores inside EmuFusion's one display-0 emulation window.

The harness builds/installs an explicit qualification APK, defaults to Android
emulators and requires an explicit hardware-safe opt-in for a verified AYN Thor,
launches only redistributable fixtures directly into EmuFusion MainActivity, and
records identity, visible-frame, pause/resume/return, crash, and Quick Resume
evidence. On a Thor, a same-process, excluded-from-recents PreviewActivity is
allowed on display 4 only while its single-screen-game surface is verified black.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "unified-android"
FIXTURES = ROOT / "engines" / "build" / "qa-fixtures"
DEFAULT_RESULTS = PROJECT / "build" / "phase1a-activity-qa"
PACKAGE = "com.thorium.preview"
LEGACY_PACKAGE = "org.pegasus_frontend.android"
MAIN_ACTIVITY = f"{PACKAGE}/org.pegasus_frontend.android.MainActivity"
GAME_ACTIVITY = "org.pegasus_frontend.android.MainActivity"
ACTION_LAUNCH = "com.thorium.preview.LAUNCH_INTERNAL_GAME"
REMOTE = "/storage/emulated/0/Download/lucent-phase1a-activity-qa"
# Some deliberately minimal conformance ROMs render only a pair of sprites;
# the open MAME Pong fixture renders only two paddles, a net, and a ball. Core-
# originated nonblack telemetry is required independently before this check,
# so the screenshot floor only rejects an empty surface rather than demanding
# a content-heavy scene.
SCREENSHOT_VISIBLE_PIXEL_FLOOR = 100
SCREENSHOT_COLOR_FLOOR = 1
SECONDARY_BLANK_MAX_VISIBLE_FRACTION = 0.001


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Case:
    system: str
    title: str
    engine: str
    fixture: str
    # A physical-library qualification can point at an existing user-owned
    # game without copying or renaming it. ``fixture`` remains the sanitized
    # report identifier and is never required to expose the source filename.
    content_path: str | None = None


@dataclass(frozen=True)
class BlockedCase:
    system: str
    engine: str
    gate: str
    reason: str


CASES = (
    Case("nes", "Lucent NES QA", "mesen", "lucent-callback-test.nes"),
    Case("snes", "Lucent SNES QA", "mesen-s", "lucent-callback-test.sfc"),
    Case("gb", "SameBoy DMG Acid2", "sameboy", "dmg-acid2.gb"),
    Case("gbc", "SameBoy CGB Acid2", "sameboy", "cgb-acid2.gbc"),
    Case("gba", "mGBA 2D Wrap", "mgba", "mgba-2d-wrap-test.gba"),
    Case("sg1000", "Lucent SG-1000 QA", "gearsystem", "lucent-callback-test.sg"),
    Case("mastersystem", "Lucent Master System QA", "gearsystem", "lucent-callback-test.sms"),
    Case("gamegear", "Lucent Game Gear QA", "gearsystem", "lucent-callback-test.gg"),
    Case("psx", "Lucent PlayStation QA", "swanstation", "lucent-callback-test.psexe"),
    Case("nds", "melonDS Homebrew QA", "melonds-ds", "melonds-homebrew-periph-slot2.nds"),
    Case("zxspectrum", "Lucent ZX Spectrum QA", "fuse", "lucent-visible-test.sna"),
    Case("arcade", "MAME Romless Pong", "mame", "pong.cmd"),
    Case("neogeo", "MAME Open Neo Geo QA", "mame", "ngdevkit-open.cmd"),
    Case("dos", "Lucent DOS QA", "dosbox-pure", "lucent-dos-callback-test.zip"),
    Case("windows", "EmuFusion Internal PC QA", "dosbox-pure",
         "emufusion-internal-pc-callback-test.zip"),
    Case("pcengine", "Lucent PC Engine QA", "beetle-pce-fast", "lucent-pce-qa.pce"),
    Case("ngp", "Stargunner Neo Geo Pocket Color", "beetle-neopop", "stargunner.ngc"),
    Case("wonderswancolor", "Bug Witch WonderSwan Color", "beetle-cygne", "bug-witch.wsc"),
)

# These registry systems are deliberately present in the Activity QA report,
# but must not be launched.  A missing legal fixture, unresolved firmware
# identity, or incompatible license is evidence, not an invitation to route
# to an external app or silently call the platform supported.
BLOCKED_CASES = (
    BlockedCase("amstradcpc", "caprice32", "license", "Core remains license-blocked."),
    BlockedCase("atari2600", "stella-2023", "license", "Core remains license-blocked."),
    BlockedCase("atari5200", "atari800", "license", "Core remains license-blocked."),
    BlockedCase("atari7800", "prosystem", "legal-fixture", "No redistributable visible-output fixture is qualified."),
    BlockedCase("atari800", "atari800", "license", "Core remains license-blocked."),
    BlockedCase("atarist", "hatari", "license", "Core remains license-blocked."),
    BlockedCase("c64", "vice-x64sc", "license", "Core remains license-blocked."),
    BlockedCase("colecovision", "gearcoleco", "firmware", "No reproducible accepted BIOS identity exists."),
    BlockedCase("intellivision", "freeintv", "firmware", "Required firmware has no accepted redistributable identities."),
    BlockedCase("megadrive", "blastem", "physical-qa", "Pinned BlastEm build still requires a redistributable fixture and physical menu-path qualification."),
    BlockedCase("msx", "bluemsx", "license", "Core remains license-blocked."),
    BlockedCase("n64", "mupen64plus-next", "physical-qa", "Pinned GLES3 build still requires a redistributable fixture and physical menu-path qualification."),
    BlockedCase("neogeocd", "mame", "firmware-content", "User BIOS and legal disc content are required."),
    BlockedCase("odyssey2", "o2em", "license", "Core remains license-blocked."),
    BlockedCase("pcenginecd", "beetle-pce-fast", "fixture-inputs",
                "Internal route imports a user-owned System Card 3; this redistributable-fixture runner has neither that BIOS nor a qualified CD fixture. Owned-game runtime evidence is tracked separately."),
    BlockedCase("sega32x", "picodrive", "license", "Core remains license-blocked."),
    BlockedCase("segacd", "picodrive", "license", "Core remains license-blocked."),
    BlockedCase("virtualboy", "beetle-vb", "license", "Core remains license-blocked."),
)


def validate_runner_coverage() -> None:
    """Fail closed if the core probe's runnable matrix changes under us."""
    path = ROOT / "engines" / "qa" / "run_phase1a_qa.py"
    spec = importlib.util.spec_from_file_location("lucent_phase1a_probe_matrix", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load probe matrix: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    expected = {
        (case.system, case.core, case.fixture)
        for case in module.CASES
        if case.core is not None and case.blocked_reason is None
    }
    actual = {(case.system, case.engine, case.fixture) for case in CASES}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(
            f"activity QA is out of sync with runnable probe matrix; missing={missing}, extra={extra}"
        )
    registry = json.loads((ROOT / "engines" / "registry.json").read_text(
        encoding="utf-8"))
    registry_systems = {
        system for engine in registry["engines"] for system in engine["systems"]
    }
    disposition_systems = {case.system for case in CASES} | {
        case.system for case in BLOCKED_CASES
    }
    if disposition_systems != registry_systems:
        raise RuntimeError(
            "Activity QA dispositions do not exactly cover the Phase 1 registry; "
            f"missing={sorted(registry_systems - disposition_systems)}, "
            f"extra={sorted(disposition_systems - registry_systems)}"
        )
    if {case.system for case in CASES} & {case.system for case in BLOCKED_CASES}:
        raise RuntimeError("a Phase 1 system cannot be both runnable and blocked")


def run(command: list[str], *, check: bool = True, binary: bool = False,
        env: dict[str, str] | None = None,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    # Emulator cores occasionally emit raw non-UTF-8 bytes into logcat; a
    # strict decode then kills the whole harness mid-run (physically hit on
    # 2026-08-15: 0xc0 at offset ~649k of a logcat dump). Replacement keeps
    # every parseable line intact.
    return subprocess.run(
        command, cwd=ROOT, check=check, capture_output=True,
        text=not binary, errors=None if binary else "replace",
        env=env, timeout=timeout,
    )


def find_sdk() -> Path:
    candidates = (
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        str(ROOT.parent / "cemu" / "Cemu-0.5" / "android-sdk"),
        str(Path.home() / "Library" / "Android" / "sdk"),
    )
    for candidate in candidates:
        if candidate and (Path(candidate) / "platform-tools" / "adb").is_file():
            return Path(candidate)
    raise SystemExit("Android SDK not found; set ANDROID_SDK_ROOT")


def adb(adb_path: Path, serial: str, *args: str, check: bool = True,
        binary: bool = False,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    return run([str(adb_path), "-s", serial, *args], check=check, binary=binary,
               timeout=timeout)


def select_target(adb_path: Path, requested: str | None,
                  allow_physical_thor: bool) -> tuple[str, bool]:
    rows = run([str(adb_path), "devices"]).stdout.splitlines()[1:]
    online = [row.split()[0] for row in rows if row.strip().endswith("\tdevice")]
    serial = requested or os.environ.get("LUCENT_QA_SERIAL")
    if serial is None:
        candidates = [item for item in online if item.startswith("emulator-")]
        if len(candidates) != 1:
            raise SystemExit("pass --serial when exactly one emulator is not online")
        serial = candidates[0]
    if serial not in online:
        raise SystemExit(f"refusing offline Android target: {serial}")
    qemu = adb(adb_path, serial, "shell", "getprop", "ro.kernel.qemu").stdout.strip()
    abi = adb(adb_path, serial, "shell", "getprop", "ro.product.cpu.abi").stdout.strip()
    is_emulator = serial.startswith("emulator-") and qemu == "1"
    if abi != "arm64-v8a":
        raise SystemExit(f"qualification requires arm64-v8a, got abi={abi}")
    if is_emulator:
        return serial, True
    if not allow_physical_thor:
        raise SystemExit(f"refusing physical target without --allow-physical-thor: {serial}")
    manufacturer = adb(adb_path, serial, "shell", "getprop",
                       "ro.product.manufacturer").stdout.strip().lower()
    model = adb(adb_path, serial, "shell", "getprop",
                "ro.product.model").stdout.strip().lower()
    if "ayn" not in manufacturer or "thor" not in model:
        raise SystemExit(
            f"physical qualification opt-in is Thor-only, got {manufacturer=} {model=}"
        )
    return serial, False


def wait_until(predicate, description: str, timeout: float = 25.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except Exception as failure:
            last = failure
            time.sleep(0.25)
            continue
        # ElementTree leaf nodes intentionally have false truthiness. UI nodes
        # are still successful wait results, so only None/False mean pending.
        if last is not None and last is not False:
            return last
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {description}; last={last!r}")


def activity_dump(adb_path: Path, serial: str) -> str:
    return adb(adb_path, serial, "shell", "dumpsys", "activity", "activities").stdout


def canonical_window_section(value: str) -> str:
    marker = "WINDOW MANAGER WINDOWS (dumpsys window windows)"
    start = value.find(marker)
    if start < 0:
        return value
    section = value[start:]
    following = re.search(r"(?m)^WINDOW MANAGER (?!WINDOWS \()[^\n]*$",
                          section[len(marker):])
    if following is not None:
        section = section[:len(marker) + following.start()]
    return section


def window_dump(adb_path: Path, serial: str) -> str:
    # The aggregate form repeats Window records in multiple service sections
    # on the Thor firmware. Restrict output to the canonical windows section
    # so the one-window identity gate measures live windows, not duplicate
    # textual representations of each window.
    return canonical_window_section(adb(
        adb_path, serial, "shell", "dumpsys", "window", "windows"
    ).stdout)


def window_focus_dump(adb_path: Path, serial: str) -> str:
    # Focus is reported by the aggregate WindowManager dump, not the scoped
    # windows section on this firmware.
    return adb(adb_path, serial, "shell", "dumpsys", "window").stdout


def recents_dump(adb_path: Path, serial: str) -> str:
    return adb(adb_path, serial, "shell", "dumpsys", "activity", "recents").stdout


def package_activity_records(value: str) -> list[str]:
    return re.findall(
        r"\* Hist\s+#\d+: ActivityRecord\{[^\n]*\su\d+\s+"
        r"(com\.thorium\.preview/[^\s}]+)", value
    )


def package_window_records(value: str) -> list[str]:
    return re.findall(
        r"Window #\d+ Window\{[^\n]*\su\d+\s+(com\.thorium\.preview/[^\s}]+)\}:",
        value,
    )


def display_activity_block(value: str, display_id: int) -> str:
    match = re.search(
        rf"^Display #{display_id} \(activities from top to bottom\):\n"
        rf"(.*?)(?=^Display #\d+ \(activities from top to bottom\):|\Z)",
        value,
        re.M | re.S,
    )
    return match.group(1) if match else ""


def package_window_displays(value: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    pattern = re.compile(
        r"Window #\d+ Window\{[^\n]*\su\d+\s+"
        r"(com\.thorium\.preview/[^\s}]+)\}:.*?"
        r"^\s+mDisplayId=(\d+)\b",
        re.M | re.S,
    )
    for component, display in pattern.findall(value):
        found.setdefault(component, []).append(int(display))
    return found


def package_recents_tasks(value: str) -> set[str]:
    # Android's full "Recent tasks" section retains excluded helper tasks even
    # though they can never appear in the user's recents UI.  The identity gate
    # is concerned with user-visible app identities, so read only the explicit
    # "Visible recent tasks" projection when the platform provides it.  This
    # permits EmuFusion's private display-4 PreviewActivity while still rejecting
    # any second visible EmuFusion task.
    visible_marker = "  Visible recent tasks (most recent first):"
    if visible_marker in value:
        value = value.split(visible_marker, 1)[1]
    return set(re.findall(
        r"(?:realActivity|mActivityComponent)=\{?"
        r"(com\.thorium\.preview/[^\s}]+)", value
    ))


def strict_gameplay_identity(adb_path: Path, serial: str) -> dict[str, object] | bool:
    activity_state = activity_dump(adb_path, serial)
    window_state = window_dump(adb_path, serial)
    activity_components = package_activity_records(activity_state)
    window_components = package_window_records(window_state)
    allowed_activities = {
        MAIN_ACTIVITY,
        "com.thorium.preview/.PreviewActivity",
    }
    allowed_windows = {
        MAIN_ACTIVITY,
        "com.thorium.preview/com.thorium.preview.PreviewActivity",
    }
    window_displays = package_window_displays(window_state)
    recent_state = recents_dump(adb_path, serial)
    recent_components = package_recents_tasks(recent_state)
    # The unified component intentionally retains Pegasus's JNI-compatible
    # MainActivity class name after EmuFusion's package slash.  Match the legacy
    # package only as an Android component/package prefix; a raw substring
    # check falsely classifies
    # com.thorium.preview/org.pegasus_frontend.android.MainActivity as the old
    # standalone package.
    legacy_in_recents = f"{LEGACY_PACKAGE}/" in recent_state
    legacy_enabled = LEGACY_PACKAGE in adb(
        adb_path, serial, "shell", "pm", "list", "packages", "-e", LEGACY_PACKAGE,
        check=False,
    ).stdout
    legacy_disabled = LEGACY_PACKAGE in adb(
        adb_path, serial, "shell", "pm", "list", "packages", "-d", LEGACY_PACKAGE,
        check=False,
    ).stdout
    pids = adb(adb_path, serial, "shell", "pidof", PACKAGE,
               check=False).stdout.split()
    focused = bool(re.search(
        r"mCurrentFocus=Window\{[^\n]*\scom\.thorium\.preview/"
        r"org\.pegasus_frontend\.android\.MainActivity\}",
        window_focus_dump(adb_path, serial),
    ))
    resumed = game_is_resumed(adb_path, serial)
    preview_activity = "com.thorium.preview/.PreviewActivity"
    preview_window = "com.thorium.preview/com.thorium.preview.PreviewActivity"
    preview_present = preview_activity in activity_components
    preview_window_present = preview_window in window_components
    if (activity_components.count(MAIN_ACTIVITY) != 1 or
            not set(activity_components).issubset(allowed_activities) or
            window_components.count(MAIN_ACTIVITY) != 1 or
            not set(window_components).issubset(allowed_windows) or
            window_displays.get(MAIN_ACTIVITY) != [0] or
            preview_present != preview_window_present or
            window_displays.get(preview_window, []) !=
            ([4] if preview_present else []) or
            recent_components != {MAIN_ACTIVITY} or
            legacy_in_recents or legacy_enabled or
            len(pids) != 1 or not focused or not resumed):
        return False
    identity = main_activity_identity(adb_path, serial)
    identity.update({
        "packageActivities": activity_components,
        "packageWindows": window_components,
        "packagePids": pids,
        "packageRecentTasks": sorted(recent_components),
        "legacyFrontendPackage": "disabled" if legacy_disabled else "absent",
        "legacyFrontendInRecents": False,
        "mainActivityDisplay": 0,
        "previewActivityDisplay": (
            4 if preview_present
            else None
        ),
        "focusedMainActivity": focused,
        "resumedMainActivity": resumed,
    })
    return identity


def thor_preview_recreated(adb_path: Path, serial: str) -> bool:
    return ("com.thorium.preview/.PreviewActivity" in
            package_activity_records(activity_dump(adb_path, serial)) and
            "com.thorium.preview/com.thorium.preview.PreviewActivity" in
            package_window_records(window_dump(adb_path, serial)))


def game_is_resumed(adb_path: Path, serial: str) -> bool:
    dump = activity_dump(adb_path, serial)
    return bool(re.search(
        r"(?:mResumedActivity|topResumedActivity|ResumedActivity).*?"
        r"com\.thorium\.preview/org\.pegasus_frontend\.android\.MainActivity",
        dump,
    ))


def frontend_is_resumed(adb_path: Path, serial: str) -> bool:
    dump = activity_dump(adb_path, serial)
    return bool(re.search(
        r"(?:mResumedActivity|topResumedActivity|ResumedActivity).*?"
        r"com\.thorium\.preview/org\.pegasus_frontend\.android\.MainActivity",
        dump,
    ))


def main_activity_identity(adb_path: Path, serial: str) -> dict[str, str]:
    matches = set(re.findall(
        r"ActivityRecord\{([0-9a-f]+)[^\n]*\s"
        r"com\.thorium\.preview/org\.pegasus_frontend\.android\.MainActivity"
        # AOSP prints the task id inside the ActivityRecord braces (`... t42}`),
        # while some vendor releases print it immediately after the braces.
        # Accept both layouts without relaxing the exact component identity.
        r"(?:\s+t(\d+)\}|\}\s+t(\d+))", activity_dump(adb_path, serial),
    ))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one live Lucent MainActivity record, observed {sorted(matches)}"
        )
    token, task_inside, task_after = next(iter(matches))
    task = task_inside or task_after
    return {"activityToken": token, "taskId": task,
            "component": GAME_ACTIVITY}


def ensure_library(adb_path: Path, serial: str) -> dict[str, str]:
    completed = adb(adb_path, serial, "shell", "am", "start", "--display", "0",
        "-W", "-n", MAIN_ACTIVITY, "-a", "android.intent.action.MAIN",
        "-c", "android.intent.category.LAUNCHER", "-f", "0x10008000",
        check=False)
    if completed.returncode != 0 or "Error:" in completed.stdout:
        raise RuntimeError("Lucent library launch failed: " + completed.stdout)
    wait_until(lambda: frontend_is_resumed(adb_path, serial),
               "Lucent library MainActivity", timeout=30.0)
    return main_activity_identity(adb_path, serial)


def ui_root(adb_path: Path, serial: str) -> ET.Element:
    remote = "/sdcard/lucent-qa-window.xml"
    try:
        adb(adb_path, serial, "shell", "uiautomator", "dump", remote,
            check=False, timeout=3.0)
        payload = adb(adb_path, serial, "exec-out", "cat", remote, binary=True,
                      timeout=2.0).stdout
        return ET.fromstring(payload.decode("utf-8", errors="replace"))
    except (subprocess.TimeoutExpired, ET.ParseError):
        # UIAutomator is supplemental evidence only. It can stall on a
        # continuously rendering TextureView, so Activity-authored event logs
        # remain the deterministic interaction oracle.
        return ET.Element("hierarchy")


def find_text(adb_path: Path, serial: str, text: str) -> ET.Element | None:
    for node in ui_root(adb_path, serial).iter("node"):
        if node.attrib.get("text") == text:
            return node
    return None


def tap_node(adb_path: Path, serial: str, node: ET.Element) -> None:
    values = [int(value) for value in re.findall(r"\d+", node.attrib.get("bounds", ""))]
    if len(values) != 4:
        raise RuntimeError(f"node has invalid bounds: {node.attrib}")
    adb(adb_path, serial, "shell", "input", "tap",
        str((values[0] + values[2]) // 2), str((values[1] + values[3]) // 2))


def screenshot_is_visible(visible_pixels: int, sampled_colors: int) -> bool:
    return (visible_pixels >= SCREENSHOT_VISIBLE_PIXEL_FLOOR and
            sampled_colors >= SCREENSHOT_COLOR_FLOOR)


def evidence_key(case: Case) -> str:
    label = re.sub(r"[^a-z0-9]+", "-", case.fixture.lower()).strip("-")
    return f"{case.system}-{label or 'case'}"


def screenshot_metrics(adb_path: Path, serial: str, output: Path) -> dict[str, object]:
    payload = adb(adb_path, serial, "exec-out", "screencap", "-p", binary=True).stdout
    output.write_bytes(payload)
    image = Image.open(io.BytesIO(payload)).convert("RGB")
    width, height = image.size
    # Touch controls live near the edges. The central crop must contain a real
    # presented core frame, not merely EmuFusion chrome over an empty surface.
    crop = image.crop((width // 5, height // 10, width * 4 // 5, height * 9 // 10))
    pixels = list(crop.getdata())
    visible = sum(max(pixel) >= 18 for pixel in pixels)
    sampled = pixels[::max(1, len(pixels) // 20_000)]
    distinct = len(set(sampled))
    visible_fraction = visible / max(1, len(pixels))
    return {
        "width": width,
        "height": height,
        "centralVisiblePixels": visible,
        "centralVisibleFraction": round(visible_fraction, 6),
        "centralSampledColorCount": distinct,
        "visible": screenshot_is_visible(visible, distinct),
    }


def secondary_blank_metrics(adb_path: Path, serial: str,
                            output: Path) -> dict[str, object]:
    # `screencap -d` expects SurfaceFlinger's 64-bit physical display token,
    # not Android DisplayManager's logical display id.  Thor's lower panel is
    # logical display 4, whose token is exposed as local:<digits> in the active
    # viewport.  Resolve it on every run instead of hard-coding a per-boot id.
    display_state = adb(
        adb_path, serial, "shell", "dumpsys", "display", check=False
    ).stdout
    token_match = re.search(
        r"DisplayViewport\{[^\n]*displayId=4,\s+"
        r"uniqueId='local:(\d+)'",
        display_state,
    )
    if token_match is None:
        return {"present": False, "blank": False}
    physical_display = token_match.group(1)
    completed = adb(adb_path, serial, "exec-out", "screencap", "-d",
                    physical_display, "-p",
                    check=False, binary=True)
    if completed.returncode != 0 or not completed.stdout.startswith(b"\x89PNG"):
        return {"present": False, "blank": False}
    output.write_bytes(completed.stdout)
    image = Image.open(io.BytesIO(completed.stdout)).convert("RGB")
    width, height = image.size
    crop = image.crop((width // 20, height // 20, width * 19 // 20, height * 19 // 20))
    pixels = list(crop.getdata())
    visible = sum(max(pixel) >= 18 for pixel in pixels)
    fraction = visible / max(1, len(pixels))
    return {
        "present": True,
        "width": width,
        "height": height,
        "visiblePixels": visible,
        "visibleFraction": round(fraction, 6),
        "blank": fraction <= SECONDARY_BLANK_MAX_VISIBLE_FRACTION,
    }


def logs(adb_path: Path, serial: str) -> str:
    return adb(adb_path, serial, "logcat", "-d", "-v", "brief").stdout


def log_when_present(adb_path: Path, serial: str, marker: str) -> str | None:
    value = logs(adb_path, serial)
    return value if marker in value else None


def core_frame_evidence(log: str, case: Case) -> dict[str, int] | None:
    pattern = re.compile(
        rf"Core frame presented engine={re.escape(case.engine)} "
        rf"system={re.escape(case.system)} sequence=(\d+) size=(\d+)x(\d+) nonblack=(\d+)"
    )
    matches = list(pattern.finditer(log))
    if not matches:
        return None
    match = matches[-1]
    sequence, width, height, nonblack = (int(value) for value in match.groups())
    if width < 1 or height < 1 or nonblack < 1:
        return None
    return {"sequence": sequence, "width": width, "height": height,
            "nonblackPixels": nonblack}


def runtime_telemetry(log: str, case: Case) -> dict[str, object] | None:
    pattern = re.compile(
        rf"Runtime telemetry engine={re.escape(case.engine)} "
        rf"system={re.escape(case.system)} frames=(\d+) elapsedMs=(\d+) "
        rf"measuredFps=([0-9.]+) targetFps=([0-9.]+) "
        rf"audioFrames=(\d+) audioStarted=(true|false)"
    )
    matches = list(pattern.finditer(log))
    if not matches:
        return None
    # Rolling qualification emits multiple windows. Always judge the newest
    # completed window rather than permanently pinning the first warmup sample.
    match = matches[-1]
    frames, elapsed_ms, measured_fps, target_fps, audio_frames, audio_started = (
        match.groups()
    )
    measured = float(measured_fps)
    target = float(target_fps)
    return {
        "frames": int(frames),
        "elapsedMs": int(elapsed_ms),
        "measuredFps": measured,
        "targetFps": target,
        "pacingWithinTolerance": target * 0.97 <= measured <= target * 1.03,
        "audioFrames": int(audio_frames),
        "audioStarted": audio_started == "true",
    }


def wait_for_qualified_runtime(adb_path: Path, serial: str, case: Case,
                               timeout: float = 30.0) -> dict[str, object]:
    marker = f"Runtime telemetry engine={case.engine} system={case.system}"
    baseline = logs(adb_path, serial).count(marker)
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        value = logs(adb_path, serial)
        count = value.count(marker)
        if count > baseline:
            baseline = count
            last = runtime_telemetry(value, case)
            if (last is not None and last["pacingWithinTolerance"] and
                    last["audioStarted"] and last["audioFrames"] > 0):
                return last
        time.sleep(0.25)
    raise RuntimeError(f"no qualified rolling audio/pacing window; last={last}")


def thor_controller_events(adb_path: Path, serial: str) -> list[str]:
    devices = adb(adb_path, serial, "shell", "cat", "/proc/bus/input/devices").stdout
    found: list[tuple[bool, str]] = []
    for block in re.split(r"\n\s*\n", devices):
        if not re.search(r'N:\s+Name="(?:AYN Thor|Odin Controller)', block, re.I):
            continue
        match = re.search(r"H:\s+Handlers=.*\b(event\d+)\b", block)
        if match:
            # Prefer the node Android itself classifies as a keyboard/gamepad,
            # while retaining every matching Thor/Odin node for firmware
            # revisions that split face and system buttons across devices.
            found.append(("kbd" in block, "/dev/input/" + match.group(1)))
    events = [node for _, node in sorted(found, key=lambda row: not row[0])]
    if not events:
        raise RuntimeError("AYN Thor controller input node was not found")
    return events


def send_linux_key(adb_path: Path, serial: str, event_node: str,
                   code: int, hold_seconds: float = 0.08) -> None:
    for value in ("1",):
        adb(adb_path, serial, "shell", "sendevent", event_node, "1", str(code), value)
        adb(adb_path, serial, "shell", "sendevent", event_node, "0", "0", "0")
    time.sleep(hold_seconds)
    adb(adb_path, serial, "shell", "sendevent", event_node, "1", str(code), "0")
    adb(adb_path, serial, "shell", "sendevent", event_node, "0", "0", "0")


def exercise_runtime_input(adb_path: Path, serial: str, case: Case,
                           event_nodes: list[str]) -> dict[str, object]:
    marker = f"Input consumed engine={case.engine} system={case.system}"
    baseline = logs(adb_path, serial).count(marker)
    # Thor firmware revisions have shipped different key-layout assignments.
    # Exercise the four standard Linux face-button scan codes on every matching
    # physical controller node and stop at the first event the production input
    # router consumes. This is still kernel-device input, not adb's virtual
    # keyboard injection.
    for event_node in event_nodes:
        for key_code in range(304, 308):
            send_linux_key(adb_path, serial, event_node, key_code)
            value = logs(adb_path, serial)
            if value.count(marker) <= baseline:
                time.sleep(0.15)
                value = logs(adb_path, serial)
            if value.count(marker) > baseline:
                match = re.search(
                    re.escape(marker) + r" control=([A-Z0-9_]+)", value
                )
                return {
                    "consumed": True,
                    "control": match.group(1) if match else "UNKNOWN",
                    "linuxKeyCode": key_code,
                    "eventNode": event_node,
                }
    raise RuntimeError("Thor physical face-button events were not consumed")


def app_crash_markers(log: str) -> list[str]:
    """Return only crash evidence attributable to EmuFusion's process.

    A physical device's global log can contain tombstones from system services
    while EmuFusion is under test. Treating an unrelated ``mediaserver`` crash as
    an app failure hides the real result without improving safety. Java crash
    records name the app in their exception block; native records either name
    it on the signal line or bind the signalled PID to the subsequent tombstone.
    """
    found: list[str] = []
    for match in re.finditer(r"FATAL EXCEPTION", log):
        block = log[match.start():match.start() + 4_096]
        if re.search(rf"\bProcess:\s*{re.escape(PACKAGE)}(?:\s|,|$)", block):
            found.append("FATAL EXCEPTION")
            break

    for match in re.finditer(r"Fatal signal[^\n]*", log):
        signal_line = match.group(0)
        if PACKAGE in signal_line or "m.thorium.preview" in signal_line:
            found.append("Fatal signal")
            break
        pid_match = re.search(r"\bpid\s+(\d+)\s*\(", signal_line)
        if pid_match is None:
            continue
        pid = re.escape(pid_match.group(1))
        tombstone = log[match.start():match.start() + 24_000]
        if (re.search(rf"\bpid:\s*{pid}\b[^\n]*>>>\s*{re.escape(PACKAGE)}\s*<<<", tombstone)
                or re.search(rf"\bCmdline:\s*{re.escape(PACKAGE)}(?:\s|$)", tombstone)):
            found.append("Fatal signal")
            break

    for marker in (f"ANR in {PACKAGE}", "E/LucentEngine", "Unable to prepare"):
        if marker in log:
            found.append(marker)
    return found


def assert_no_crash(log: str) -> None:
    found = app_crash_markers(log)
    if found:
        raise RuntimeError("crash/error markers in logcat: " + ", ".join(found))


def launch(adb_path: Path, serial: str, case: Case) -> dict[str, object]:
    adb(adb_path, serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
    adb(adb_path, serial, "shell", "wm", "dismiss-keyguard", check=False)
    time.sleep(0.5)
    remote_path = case.content_path or f"{REMOTE}/{case.fixture}"
    completed = adb(
        adb_path, serial, "shell", "am", "start", "--display", "0", "-W",
        "-n", MAIN_ACTIVITY,
        "-a", ACTION_LAUNCH,
        "--activity-single-top", "--activity-clear-top",
        "--es", "path", shlex.quote(remote_path),
        "--es", "engine_id", case.engine,
        "--es", "system_id", case.system,
        "--es", "game_id", "phase1a-" + case.system,
        # Keep shell-facing QA extras token-safe; the fixture's human title is
        # retained in this report rather than relying on adb shell quoting.
        "--es", "title", "phase1a-" + case.system,
        check=False,
    )
    if completed.returncode != 0 or "Error:" in completed.stdout:
        raise RuntimeError("in-window qualification launch failed: " + completed.stdout)
    wait_until(lambda: game_is_resumed(adb_path, serial), "Lucent MainActivity")
    accepted = f"In-window route accepted engine={case.engine} system={case.system}"
    wait_until(lambda: accepted in logs(adb_path, serial),
               "in-window engine route", timeout=20.0)
    identity = wait_until(
        lambda: strict_gameplay_identity(adb_path, serial),
        "one Lucent Activity/task/window/process after lower-preview closure",
        timeout=20.0,
    )
    wait_until(lambda: find_text(adb_path, serial, "Unable to start game") is None,
               "absence of fatal dialog", timeout=2.0)
    return identity


def wait_for_new_log(adb_path: Path, serial: str, marker: str, baseline: int,
                     description: str) -> str:
    def present():
        value = logs(adb_path, serial)
        return value if value.count(marker) > baseline else False

    return wait_until(
        present,
        description,
        timeout=10.0,
    )


def pause_resume_exit(adb_path: Path, serial: str, case: Case) -> None:
    shown = f"Pause menu shown engine={case.engine} system={case.system}"
    hidden = f"Pause menu hidden engine={case.engine} system={case.system}"
    exited = f"Exit to Lucent invoked engine={case.engine} system={case.system}"
    baseline = logs(adb_path, serial)
    adb(adb_path, serial, "shell", "input", "keyevent", "4")
    wait_for_new_log(adb_path, serial, shown, baseline.count(shown), "pause menu log")
    # The pause panel focuses Resume by construction. ENTER validates the real
    # controller/focus path; UIAutomator text is only best-effort evidence.
    find_text(adb_path, serial, "Resume")
    adb(adb_path, serial, "shell", "input", "keyevent", "66")
    wait_for_new_log(adb_path, serial, hidden, baseline.count(hidden), "resume log")
    if not game_is_resumed(adb_path, serial):
        raise RuntimeError("game activity did not remain resumed after Resume")
    current = logs(adb_path, serial)
    adb(adb_path, serial, "shell", "input", "keyevent", "4")
    wait_for_new_log(adb_path, serial, shown, current.count(shown), "second pause menu log")
    find_text(adb_path, serial, "Exit to Lucent")
    # Restore is disabled until checkpoint history exists, so deterministic
    # pause navigation skips it: Resume -> Controls -> Exit.
    for _ in range(2):
        adb(adb_path, serial, "shell", "input", "keyevent", "20")
    adb(adb_path, serial, "shell", "input", "keyevent", "66")
    wait_for_new_log(adb_path, serial, exited, current.count(exited), "exit invocation log")
    returned = (f"Returned to Lucent immediately in same window engine={case.engine} "
                f"system={case.system}")
    wait_until(lambda: returned in logs(adb_path, serial),
               "same-window return", timeout=40.0)
    wait_until(lambda: frontend_is_resumed(adb_path, serial),
               "stable Lucent frontend return", timeout=40.0)


def stop_hold_exit(adb_path: Path, serial: str, case: Case,
                   event_nodes: list[str]) -> dict[str, object]:
    returned = (f"Returned to Lucent immediately in same window engine={case.engine} "
                f"system={case.system}")
    baseline = logs(adb_path, serial).count(returned)
    # BTN_SELECT is the normal Thor mapping. KEY_STOPCD and KEY_STOP cover AYN
    # firmware revisions that expose the dedicated square button as media Stop.
    for event_node in event_nodes:
        for key_code in (314, 166, 128):
            send_linux_key(adb_path, serial, event_node, key_code,
                           hold_seconds=1.15)
            try:
                returned_log = wait_for_new_log(
                    adb_path, serial, returned, baseline,
                    "one-second Stop/Select hold immediate return")
            except RuntimeError:
                continue
            latencies = re.findall(
                re.escape(returned) + r" latencyMs=(\d+)", returned_log
            )
            if not latencies:
                raise RuntimeError("same-window return omitted UI latency telemetry")
            latency_ms = int(latencies[-1])
            if latency_ms >= 500:
                raise RuntimeError(
                    f"held-Stop UI return took {latency_ms}ms; expected <500ms"
                )
            wait_until(lambda: frontend_is_resumed(adb_path, serial),
                       "stable Lucent frontend return", timeout=40.0)
            return {"eventNode": event_node, "linuxKeyCode": key_code,
                    "acceptedToLibraryMs": latency_ms}
    raise RuntimeError("Thor one-second Stop/Select hold was not consumed")


def verify_case(adb_path: Path, serial: str, case: Case, output: Path,
                require_preview_lifecycle: bool,
                require_runtime_telemetry: bool = False,
                require_stop_hold: bool = False) -> dict[str, object]:
    library_identity = ensure_library(adb_path, serial)
    adb(adb_path, serial, "logcat", "-c")
    gameplay_identity = launch(adb_path, serial, case)
    key = evidence_key(case)
    activity_evidence = output / f"{key}-gameplay-activities.txt"
    window_evidence = output / f"{key}-gameplay-windows.txt"
    pid_evidence = output / f"{key}-gameplay-pids.txt"
    recents_evidence = output / f"{key}-gameplay-recents.txt"
    activity_evidence.write_text(activity_dump(adb_path, serial), encoding="utf-8")
    window_evidence.write_text(window_dump(adb_path, serial), encoding="utf-8")
    pid_evidence.write_text(" ".join(gameplay_identity["packagePids"]) + "\n",
                            encoding="utf-8")
    recents_evidence.write_text(recents_dump(adb_path, serial), encoding="utf-8")
    if ({key: gameplay_identity[key] for key in library_identity} != library_identity):
        raise RuntimeError(
            f"gameplay replaced Lucent's Activity/task: "
            f"{library_identity} -> {gameplay_identity}"
        )
    frame_log = wait_until(
        lambda: (value := logs(adb_path, serial)) and core_frame_evidence(value, case),
        "nonblack core-originated frame", timeout=30.0,
    )
    wait_until(
        lambda: (metrics := screenshot_metrics(adb_path, serial,
                    output / f"{key}-frame.png"))["visible"] and metrics,
        "visible nonempty core frame", timeout=30.0,
    )
    frame = screenshot_metrics(adb_path, serial, output / f"{key}-frame.png")
    secondary_blank: dict[str, object] | None = None
    if require_preview_lifecycle:
        secondary_blank = wait_until(
            lambda: (metrics := secondary_blank_metrics(
                adb_path, serial, output / f"{key}-lower-blank.png"
            ))["blank"] and metrics,
            "black-only Thor lower display during single-screen gameplay",
            timeout=15.0,
        )
    route_log = logs(adb_path, serial)
    if f"In-window route accepted engine={case.engine} system={case.system}" not in route_log:
        raise RuntimeError("Lucent in-window route was not observed")
    assert_no_crash(route_log)

    runtime: dict[str, object] | None = None
    physical_input: dict[str, object] | None = None
    stop_hold: dict[str, object] | None = None
    event_nodes: list[str] = []
    if require_runtime_telemetry or require_stop_hold:
        event_nodes = thor_controller_events(adb_path, serial)
    if require_runtime_telemetry:
        physical_input = exercise_runtime_input(adb_path, serial, case, event_nodes)
        runtime = wait_for_qualified_runtime(adb_path, serial, case)

    if require_stop_hold:
        preferred = ([str(physical_input["eventNode"])] + event_nodes
                     if physical_input else event_nodes)
        stop_hold = stop_hold_exit(adb_path, serial, case,
                                   list(dict.fromkeys(preferred)))
    else:
        pause_resume_exit(adb_path, serial, case)
    if require_preview_lifecycle:
        wait_until(lambda: thor_preview_recreated(adb_path, serial),
                   "Thor lower-screen preview recreation after return", timeout=20.0)
    returned_identity = main_activity_identity(adb_path, serial)
    if returned_identity != library_identity:
        raise RuntimeError(
            f"return replaced Lucent's Activity/task: "
            f"{library_identity} -> {returned_identity}"
        )
    committed_marker = f"Quick Resume committed engine={case.engine} system={case.system}"
    committed_log = wait_until(
        lambda: log_when_present(adb_path, serial, committed_marker),
        "committed Quick Resume", timeout=40.0,
    )
    assert_no_crash(committed_log)

    # Relaunch proves the same production state identity is readable and the
    # core accepts the atomically committed state, not merely that a file exists.
    adb(adb_path, serial, "shell", "am", "force-stop", PACKAGE)
    gameplay_identity_after_process_death = launch(adb_path, serial, case)
    restored_marker = f"Quick Resume restored engine={case.engine} system={case.system}"
    restored_log = wait_until(
        lambda: log_when_present(adb_path, serial, restored_marker),
        "restored Quick Resume", timeout=30.0,
    )
    assert_no_crash(restored_log)
    if require_stop_hold:
        preferred = ([str(stop_hold["eventNode"])] + event_nodes
                     if stop_hold else event_nodes)
        stop_hold_exit(adb_path, serial, case, list(dict.fromkeys(preferred)))
    else:
        pause_resume_exit(adb_path, serial, case)
    # Explicit exit must clear the retained game launch Intent. A normal app
    # restart after process death must remain in the library, not relaunch the
    # game that the user already closed.
    exit_log_count = logs(adb_path, serial).count(
        f"In-window route accepted engine={case.engine} system={case.system}"
    )
    adb(adb_path, serial, "shell", "am", "force-stop", PACKAGE)
    ensure_library(adb_path, serial)
    time.sleep(1.0)
    if logs(adb_path, serial).count(
            f"In-window route accepted engine={case.engine} system={case.system}") != exit_log_count:
        raise RuntimeError("explicit exit retained ACTION_LAUNCH and relaunched the game")
    return {
        "status": "PASS",
        "system": case.system,
        "engine": case.engine,
        "fixture": case.fixture,
        "frame": frame,
        "coreFrame": frame_log,
        "runtimeTelemetry": runtime,
        "physicalInput": physical_input,
        "stopHoldInput": stop_hold,
        "internalRoute": True,
        "oneActivityWindowProcess": True,
        "inProcessActivity": GAME_ACTIVITY,
        "libraryIdentity": library_identity,
        "gameplayIdentity": gameplay_identity,
        "gameplayIdentityAfterProcessDeath": gameplay_identity_after_process_death,
        "identityEvidence": {
            "activities": str(activity_evidence),
            "windows": str(window_evidence),
            "pids": str(pid_evidence),
            "recents": str(recents_evidence),
        },
        "returnedIdentity": returned_identity,
        "pauseResume": not require_stop_hold,
        "stopHoldReturn": require_stop_hold,
        "returnedToLucent": True,
        "quickResumeCommitted": True,
        "quickResumeRestored": True,
        "explicitExitClearedLaunchIntent": True,
        "thorPreviewExcludedFromDisplayZeroDuringGameplay": require_preview_lifecycle,
        "thorLowerDisplayBlankDuringGameplay": secondary_blank,
        "thorPreviewRecreatedAfterReturn": require_preview_lifecycle,
        "crashMarkers": [],
    }


def build_apk() -> Path:
    environment = os.environ.copy()
    environment["LUCENT_INCLUDE_EXPERIMENTAL_CORES"] = "1"
    environment["LUCENT_AUTOSELECT_EXPERIMENTAL_CORES"] = "0"
    completed = run([str(PROJECT / "build.sh")], env=environment)
    path = Path(completed.stdout.strip().splitlines()[-1])
    if not path.is_file():
        raise RuntimeError(f"qualification build did not produce APK: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--apk", type=Path, help="reuse an existing qualification APK")
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--system", action="append", choices=[case.system for case in CASES],
                        help="run only this system after validating the complete matrix")
    parser.add_argument("--allow-physical-thor", action="store_true",
                        help="permit the verified AYN Thor without clearing its app data")
    args = parser.parse_args()

    sdk = find_sdk()
    adb_path = sdk / "platform-tools" / "adb"
    serial, emulator_only = select_target(
        adb_path, args.serial, args.allow_physical_thor
    )
    validate_runner_coverage()
    selected_cases = tuple(
        case for case in CASES if not args.system or case.system in set(args.system)
    )
    if any(case.system in {"pcengine", "ngp", "wonderswancolor"}
           for case in selected_cases):
        run([sys.executable, str(ROOT / "engines" / "qa" / "build_open_newcore_fixtures.py")])
    run([sys.executable, str(ROOT / "engines" / "qa" / "generate_fixtures.py")])
    apk = args.apk.resolve() if args.apk else build_apk()
    args.output.mkdir(parents=True, exist_ok=True)

    adb(adb_path, serial, "install", "--no-incremental", "-r", "-d", str(apk))
    if emulator_only:
        adb(adb_path, serial, "shell", "pm", "clear", PACKAGE)
    # Pegasus's recovery activity may otherwise put Android's notification
    # permission dialog above the second launch after the first Exit to Lucent.
    # Pregranting this declared runtime permission keeps QA focused on EmuFusion's
    # own activity lifecycle rather than system onboarding chrome.
    for permission in (
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_AUDIO",
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
    ):
        adb(adb_path, serial, "shell", "pm", "grant", PACKAGE, permission, check=False)
    adb(adb_path, serial, "shell", "appops", "set", "--uid", PACKAGE,
        "MANAGE_EXTERNAL_STORAGE", "allow", check=False)
    adb(adb_path, serial, "shell", "mkdir", "-p", REMOTE)
    fixture_manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    manifest_by_file = {row["file"]: row for row in fixture_manifest["fixtures"]}
    pushed: set[str] = set()
    for case in selected_cases:
        fixture = FIXTURES / case.fixture
        if not fixture.is_file():
            raise SystemExit(f"missing legal fixture: {fixture}")
        staged_fixture = fixture
        if case.system == "neogeo":
            # The probe's legal command points at its /data/local/tmp staging
            # root. Rewrite only that absolute directory in the transient QA
            # copy so the exact same open cartridge assets are visible to the
            # sandboxed Activity through shared storage.
            staged_fixture = args.output / case.fixture
            staged_fixture.write_text(
                fixture.read_text(encoding="utf-8").replace(
                    "/data/local/tmp/lucent-phase1a-qa/fixtures", REMOTE
                ),
                encoding="utf-8",
            )
        adb(adb_path, serial, "push", str(staged_fixture), f"{REMOTE}/{case.fixture}")
        pushed.add(case.fixture)
        for support in manifest_by_file.get(case.fixture, {}).get("supportFiles", []):
            name = support["file"]
            if name in pushed:
                continue
            support_path = FIXTURES / name
            if not support_path.is_file():
                raise SystemExit(f"missing legal support fixture: {support_path}")
            adb(adb_path, serial, "push", str(support_path), f"{REMOTE}/{name}")
            pushed.add(name)

    records = []
    for case in selected_cases:
        try:
            record = verify_case(adb_path, serial, case, args.output,
                                 require_preview_lifecycle=not emulator_only)
        except Exception as failure:
            (args.output / f"{case.system}-failure-activities.txt").write_text(
                activity_dump(adb_path, serial), encoding="utf-8")
            (args.output / f"{case.system}-failure-windows.txt").write_text(
                window_dump(adb_path, serial), encoding="utf-8")
            (args.output / f"{case.system}-failure-logcat.txt").write_text(
                logs(adb_path, serial), encoding="utf-8")
            record = {
                "status": "FAIL", "system": case.system, "engine": case.engine,
                "fixture": case.fixture, "reason": str(failure),
            }
        records.append(record)
        print(f"{record['status']:4} {case.system} ({case.engine})")
        if record["status"] == "FAIL":
            break

    report = {
        "schemaVersion": 1,
        "target": {"serial": serial, "abi": "arm64-v8a",
                   "emulatorOnly": emulator_only},
        "apk": str(apk),
        "apkSha256": sha256_file(apk),
        "qualificationOnly": True,
        "textureViewPreserved": True,
        "systems": records,
        "blockedSystems": [
            {"status": "BLOCKED", "system": case.system,
             "engine": case.engine, "gate": case.gate, "reason": case.reason}
            for case in BLOCKED_CASES
        ],
        "counts": {
            "PASS": sum(record["status"] == "PASS" for record in records),
            "FAIL": sum(record["status"] == "FAIL" for record in records),
            "BLOCKED": len(BLOCKED_CASES),
        },
    }
    (args.output / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 1 if report["counts"]["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
