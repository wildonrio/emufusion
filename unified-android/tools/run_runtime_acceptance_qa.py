#!/usr/bin/env python3
"""Black-box EmuFusion acceptance on the exact signed AYN Thor artifact.

Unlike the engine qualification runners, this gate never starts a game intent.
It drives the same Odin Controller event node a person uses: right-stick view
selection, D-pad menu movement, physical A, and the one-second physical Stop
hold.  Every game must remain in EmuFusion's original MainActivity/task/window/PID.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import http.client
import io
import json
import math
import os
import re
import shlex
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageChops, ImageStat

import run_phase1a_activity_qa as qa
import verify_frame_generation_evidence as frame_gen
import verify_rife_frame_generation_timing as rife_timing
import verify_n64_hw_runtime_evidence as n64_hw
import verify_nes_runtime_evidence as nes_qa
import verify_menu_route_closure as route_closure
import verify_volume_evidence as volume_proof
import visible_return_video as return_video


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "com.thorium.preview"
NES_QUALIFICATION_FILE = "lucent-callback-test.nes"
NES_QUALIFICATION_SHA256 = "42019e9ca4a3a11815a9e13b7c60734a73fb7ae3cb06a140915daa4605ee8508"
NES_REAL_QUALIFICATION_TITLES = (
    "10-Yard Fight", "1943: The Battle of Midway", "8 Eyes",
)
NES_CALIBRATION_CONTENT_FAILURES = frozenset({
    "motion field is effectively zero",
    "motion field has no confident vectors",
    "synthesized frames repeat a real endpoint too often",
    "sampled output content does not change often enough",
    "too few genuinely changing pixels were sampled",
    "synthetic pixels do not materially depart from both endpoints",
    "most synthetic output is indistinguishable from fixed-pixel crossfade",
    "too few synthesized samples contain measurable selected motion",
    "motion field and non-crossfade synthetic output are not correlated",
    "too few changing pixels have a confident selected motion vector",
    "motion-compensated pixels do not spatially follow their selected vectors",
})
NES_IMPORT_REGISTRY = "/sdcard/pegasus-frontend/thorium-imports.json"
MAIN_ACTIVITY = "com.thorium.preview/org.pegasus_frontend.android.MainActivity"
# Reviewed Settings-only External-route Accessibility authorization handling;
# Cover/List/System/gameplay menus remain unchanged.
# Exact current product theme.  The prior digest predated the reviewed
# full-height/settings/screensaver work and made the physical QA runner reject
# the very APK it had just built, before any game launch.  Keep this as a byte
# identity gate rather than weakening it to a structural/theme-name check.
# Re-pinned for the WIDESCREEN HACK Settings slot (23); the theme.qml byte
# identity otherwise stays the reviewed product source.
FROZEN_THEME_QML = "8680a9999c0a374dc44c296a215b6243cd29965d55fc67321a72ff9bcccc02e2"
FROZEN_THEME_CFG = "89163b758b21e36d7be4bb4ab22502936a84957e5580003bfd1d3a3c8b8cf2b5"
ROUTE = re.compile(r"In-window route accepted engine=([^ ]+) system=([^\s]+)")
RETURN = re.compile(
    r"Returned to Lucent immediately in same window engine=([^ ]+) "
    r"system=([^ ]+) latencyMs=(\d+)"
)
ACTIVITY_START = re.compile(
    r"ActivityTaskManager.*START\s+u\d+.*com\.thorium\.preview",
    re.I,
)
# Any Activity START of any package, with its intent block captured, so the
# in-process assertion can classify each new Activity rather than only counting
# EmuFusion starts. `intent` is the `{...}` payload (act=/cmp=/flg=...) and `tail`
# is the remainder of the line (uid, launch flags, and sometimes a display).
ACTIVITY_START_INTENT = re.compile(
    r"ActivityTaskManager:\s*START\s+u\d+\s*\{(?P<intent>[^}]*)\}(?P<tail>[^\n]*)",
    re.I,
)
# EmuFusion's OWN dual-screen gameplay window on the physical lower display.
SECONDARY_GAMEPLAY_ACTION = "com.thorium.preview.SECONDARY_GAMEPLAY"
# The secondary gameplay window resuming on a NON-primary (>=1) display. This
# corroborates that the whitelisted PreviewActivity landed on the lower panel
# and never on display 0.
SECONDARY_GAMEPLAY_RESUME = re.compile(
    r"performResumeActivity com\.thorium\.preview displayId ([1-9]\d*)"
)
SECONDARY_GAMEPLAY_REUSED = re.compile(
    r"request served by the resumed lower-display activity.*?"
    r"showGameplaySurface .*?displayId=([1-9]\d*).*?"
    r"Frame generator attached .*?role=secondary displayId=\1",
    re.S,
)
PROHIBITED_TEXT = re.compile(
    r"PREPARING|SAVING\s+AND\s+RETURNING|POWERED\s+BY\s+PEGASUS|"
    r"\bLUCENT\b|\bPEGASUS\b",
    re.I,
)
ACTIVE_NES_CAPTURES: list[dict[str, object]] = []
ACTIVE_NES_STAGE_CONTEXT: Optional[dict[str, object]] = None
SWITCH_NVDEC_OPEN = "OnOpen: NVDEC video stream started"
SWITCH_NVDEC_CLOSE = "OnClose: NVDEC video stream ended"
SWITCH_SETTINGS_TEXT = re.compile(
    r"\bACCESSIBILITY\b|(?:\bGAME\b.*\bAUDIO\b.*\bBACK\b)", re.I | re.S,
)
SWITCH_TITLE_PROMPT_TEXT = re.compile(
    # OCR renders a circled button glyph as @/(c)/(r) noise: Metroid Dread's
    # "Press (A)" read as "Press @" with no bare A token (run switch25).
    r"\bPRESS\b.{0,36}(?:\bA\b|\bBUTTON\b|\bANY\b|\bCONTINUE\b|[@©®])",
    re.I | re.S,
)
SWITCH_PLAY_MENU_TEXT = re.compile(
    r"\bPILGRIMAGE\b|\bNEW\s+GAME\b|\bCONTINUE\b|\bLOAD\s+GAME\b|"
    r"\bSTART\s+GAME\b",
    re.I,
)
SWITCH_SAVE_MENU_TEXT = re.compile(
    # "SAMUS FILES" / "NO DATA" is Metroid Dread's save-select vocabulary
    # (run switch26).
    r"\bSAVE\s+(?:FILE|SLOT)\b|\bEMPTY(?:\s+(?:FILE|SLOT))?\b|"
    r"\bSLOT(?:\s+\d+)?\b|\bNO\s+DATA\b|\bSAMUS\s+FILES\b",
    re.I,
)
SWITCH_CHOICE_MENU_TEXT = re.compile(
    r"\bDIFFICULTY\b|\bPENITENCE\b|\bTRUE\s+TORMENT\b|"
    r"\bSTANDARD\s+MODE\b",
    re.I,
)
SWITCH_CONFIRM_MENU_TEXT = re.compile(r"\bYES\b.*\bNO\b|\bNO\b.*\bYES\b",
                                      re.I | re.S)
SWITCH_MENU_GUARD_TEXT = re.compile(
    r"\bACCESSIBILITY\b|\bOPTIONS?\b|\bAUDIO\b|\bBACK\b|"
    r"\bPILGRIMAGE\b|\bNEW\s+GAME\b|\bCONTINUE\b|\bLOAD\s+GAME\b|"
    r"\bSAVE\s+(?:FILE|SLOT)\b|\bEMPTY\s+(?:FILE|SLOT)\b|"
    r"\bDIFFICULTY\b|\bPENITENCE\b|\bTRUE\s+TORMENT\b|"
    r"\bYES\b.*\bNO\b|\bNO\b.*\bYES\b",
    re.I,
)


@dataclass(frozen=True)
class SystemCase:
    folder: str
    aliases: tuple[str, ...]
    engines: tuple[str, ...]
    phase: int
    dual_screen: bool = False
    flicker_burst: bool = False
    lower_touch: bool = False
    required_titles: tuple[str, ...] = ()
    required_source_tiers: tuple[int, ...] = ()


@dataclass
class InputTrace:
    action: str
    monotonic_ms: int


def parse_quick_key_edges(getevent_output: str, key_code: int) -> dict[str, object]:
    """Parse the kernel timestamps for one injected quick key pair.

    ``getevent -lt`` differs slightly across Android releases: translated
    builds print ``EV_KEY KEY_VOLUMEDOWN DOWN`` while minimal builds print raw
    hexadecimal triples.  Accept both, but only for the requested key code.
    Any repeat, duplicate edge, missing edge, or reversed chronology fails.
    """
    translated_names = {
        PhysicalController.VOLUME_DOWN: "KEY_VOLUMEDOWN",
        PhysicalController.VOLUME_UP: "KEY_VOLUMEUP",
    }
    translated_name = translated_names.get(key_code, "")
    raw_code = f"{key_code:04x}"
    edges: list[tuple[str, float]] = []
    for line in getevent_output.splitlines():
        timestamp_match = re.search(r"\[\s*(\d+(?:\.\d+)?)\]", line)
        if timestamp_match is None:
            continue
        timestamp = float(timestamp_match.group(1))
        translated = re.search(
            r"\bEV_KEY\s+(KEY_[A-Z0-9_]+)\s+(DOWN|UP|REPEAT)\b", line,
            re.I,
        )
        if translated is not None:
            if translated.group(1).upper() != translated_name:
                continue
            edges.append((translated.group(2).lower(), timestamp))
            continue
        raw = re.search(
            r"(?:^|\s)0001\s+([0-9a-f]{4})\s+([0-9a-f]{8})(?:\s|$)",
            line, re.I,
        )
        if raw is None or raw.group(1).lower() != raw_code:
            continue
        value = int(raw.group(2), 16)
        edges.append(("down" if value == 1 else "up" if value == 0
                      else "repeat", timestamp))
    down = [timestamp for edge, timestamp in edges if edge == "down"]
    up = [timestamp for edge, timestamp in edges if edge == "up"]
    repeats = [timestamp for edge, timestamp in edges if edge == "repeat"]
    if len(down) != 1 or len(up) != 1 or repeats or up[0] <= down[0]:
        raise RuntimeError(
            "quick-tap kernel trace needs exactly one DOWN then one UP and no "
            f"repeats; edges={edges}"
        )
    return {
        "downKernelSeconds": down[0],
        "upKernelSeconds": up[0],
        "holdMs": round((up[0] - down[0]) * 1000.0, 3),
        "downEventCount": 1,
        "upEventCount": 1,
        "repeatCount": 0,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def one_app_verifier_command(verifier: Path, aapt: Path, apk: Path) -> list[str]:
    """Build the identity-verifier command for the exact product edition.

    EmuFusion+ deliberately has a distinct application label and a fail-closed
    native-payload contract.  Treating it as the base edition rejects a valid
    Plus APK before runtime QA reaches a game.
    """
    command = [sys.executable, str(verifier), "--aapt", str(aapt)]
    if "emufusion-plus-lsfg-internal" in apk.name:
        command.append("--internal-lsfg-plus")
    command.append(str(apk))
    return command


def packaged_engine_sha256(apk: Path, engine: str) -> str:
    """Hash the exact executable payload for either engine architecture."""
    # Retain the build's canonical hyphen->underscore spelling
    # (mesen-s -> mesen_s); normalize() intentionally removes separators and
    # therefore cannot name APK members. Phase 3 engines are native adapters,
    # not libretro cores, so asking for liblucent_core_eden/cemu made physical
    # QA fail before those games were launched even though both adapters were
    # present and independently verified.
    stem = re.sub(r"[^a-z0-9]+", "_", engine.lower()).strip("_")
    prefix = ("liblucent_native_adapter_" if engine.lower() in
              {"eden", "cemu", "aps3e"} else "liblucent_core_")
    member = "lib/arm64-v8a/" + prefix + stem + ".so"
    with zipfile.ZipFile(apk) as archive:
        try:
            payload = archive.read(member)
        except KeyError as error:
            # Route records report separator-free canonical ids (melondsds)
            # while packaged members keep underscores (melonds_ds). Match by
            # separator-free identity — still exactly one member — before
            # failing (physically hit on the first DS run, 2026-08-15).
            want = re.sub(r"[^a-z0-9]", "", engine.lower())
            candidates = [
                name for name in archive.namelist()
                if name.startswith("lib/arm64-v8a/" + prefix) and
                name.endswith(".so") and
                re.sub(r"[^a-z0-9]", "",
                       name.rsplit("/", 1)[1][len(prefix):-3]) == want
            ]
            if len(candidates) == 1:
                member = candidates[0]
                payload = archive.read(member)
                return hashlib.sha256(payload).hexdigest()
            raise RuntimeError(
                f"exact packaged engine is absent for frame-generation identity: {member}"
            ) from error
    return hashlib.sha256(payload).hexdigest()


def normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def load_matrix(path: Path) -> list[SystemCase]:
    root = json.loads(path.read_text(encoding="utf-8"))
    if root.get("schemaVersion") != 1:
        raise RuntimeError("unsupported runtime acceptance matrix")
    result = []
    for row in root.get("systems", []):
        required_titles = tuple(str(value) for value in
                                row.get("requiredTitles", []))
        required_source_tiers = tuple(int(value) for value in
                                      row.get("requiredSourceTiers", []))
        if (required_source_tiers and
                len(required_source_tiers) != len(required_titles)):
            raise RuntimeError(
                "requiredSourceTiers must parallel requiredTitles for " +
                str(row.get("folder", "unknown"))
            )
        if any(tier not in {20, 30, 40, 50, 60}
               for tier in required_source_tiers):
            raise RuntimeError(
                "requiredSourceTiers contains an unsupported source tier for " +
                str(row.get("folder", "unknown"))
            )
        result.append(SystemCase(
            folder=normalize(row["folder"]),
            aliases=tuple(normalize(value) for value in row.get("aliases", [])),
            engines=tuple(normalize(value) for value in row.get("engines", [])),
            phase=int(row["phase"]),
            dual_screen=bool(row.get("dualScreen", False)),
            flicker_burst=bool(row.get("flickerBurst", False)),
            lower_touch=bool(row.get("lowerTouch", False)),
            required_titles=required_titles,
            required_source_tiers=required_source_tiers,
        ))
    return result


def _intent_field(intent: str, key: str) -> str:
    match = re.search(rf"(?:^|\s){re.escape(key)}=(\S+)", intent)
    return match.group(1) if match else ""


def is_secondary_gameplay_start(match: "re.Match[str]") -> bool:
    """True only for EmuFusion's OWN PreviewActivity opened with the
    SECONDARY_GAMEPLAY action, and never one pinned to the primary display.
    This is the single second Activity that dual-screen gameplay is allowed to
    open on the physical lower panel; everything else is a one-app violation."""
    intent = match.group("intent")
    tail = match.group("tail") or ""
    if _intent_field(intent, "act") != SECONDARY_GAMEPLAY_ACTION:
        return False
    component = _intent_field(intent, "cmp")
    package, _, clazz = component.partition("/")
    if package != "com.thorium.preview" or "PreviewActivity" not in clazz:
        return False
    # The secondary gameplay window must never land on display 0.
    if re.search(r"displayId=?0\b", intent + " " + tail):
        return False
    return True


def classify_new_activity_starts(
        routed_log: str, baseline_log: str,
        case: SystemCase) -> tuple[int, list[str]]:
    """Split the Activity starts that appeared after the physical-A launch into
    (permitted EmuFusion secondary-gameplay starts, violating starts).

    Only dual-screen systems may open exactly one EmuFusion PreviewActivity with the
    SECONDARY_GAMEPLAY action on a non-primary display. Any other new Activity,
    any Activity on display 0, any MainActivity relaunch, and any non-Lucent
    package is a violation for every system."""
    baseline = len(ACTIVITY_START_INTENT.findall(baseline_log))
    matches = list(ACTIVITY_START_INTENT.finditer(routed_log))
    secondary = 0
    violations: list[str] = []
    for match in matches[baseline:]:
        if case.dual_screen and is_secondary_gameplay_start(match):
            secondary += 1
        else:
            violations.append(match.group(0))
    return secondary, violations


def embedded_theme(apk: Path) -> tuple[bytes, bytes, list[str]]:
    with zipfile.ZipFile(apk) as archive:
        payload = archive.read("assets/pegasus-lucent-theme.zip")
    with zipfile.ZipFile(io.BytesIO(payload)) as theme:
        qml_names = [name for name in theme.namelist()
                     if name == "theme.qml" or name.endswith("/theme.qml")]
        cfg_names = [name for name in theme.namelist()
                     if name == "theme.cfg" or name.endswith("/theme.cfg")]
        if len(qml_names) != 1 or len(cfg_names) != 1:
            raise RuntimeError("bundled theme has ambiguous qml/cfg roots")
        qml = theme.read(qml_names[0])
        cfg = theme.read(cfg_names[0])
    text = qml.decode("utf-8")
    catalog = text.split("id: systemCatalog", 1)[1].split(
        "// Predecode official platform logotypes", 1)[0]
    order = [normalize(value) for value in re.findall(
        r'ListElement\s*\{[^{}]*?folder:\s*"([^"]+)"[^{}]*\}',
        catalog, re.S,
    )]
    if not order or order[0] != "all":
        raise RuntimeError("cannot derive system order from exact bundled theme")
    return qml, cfg, order


def catalog_display_names(apk: Path) -> dict[str, str]:
    """Map each catalog folder to the normalized on-screen system name.

    The List view renders the highlighted system as a large header (e.g.
    "GAME BOY ADVANCE"), which is the catalog ``name`` field, not the ``folder``
    id ("gba"). This map is what lets the List view smoke resolve an OCR'd
    header back to a canonical folder without assuming the Cover view order.
    """
    qml, _cfg, _order = embedded_theme(apk)
    text = qml.decode("utf-8")
    catalog = text.split("id: systemCatalog", 1)[1].split(
        "// Predecode official platform logotypes", 1)[0]
    names: dict[str, str] = {}
    for element in re.findall(r"ListElement\s*\{[^{}]*\}", catalog, re.S):
        name_match = re.search(r'name:\s*"([^"]*)"', element)
        folder_match = re.search(r'folder:\s*"([^"]+)"', element)
        if name_match and folder_match:
            names[normalize(folder_match.group(1))] = normalize(name_match.group(1))
    return names


def verify_frozen_menu(apk: Path) -> list[str]:
    qml, cfg, order = embedded_theme(apk)
    errors = []
    if hashlib.sha256(qml).hexdigest() != FROZEN_THEME_QML:
        errors.append("exact APK does not contain the frozen menu theme.qml")
    if hashlib.sha256(cfg).hexdigest() != FROZEN_THEME_CFG:
        errors.append("exact APK does not contain the frozen menu theme.cfg")
    if len(order) < 2:
        errors.append("exact APK has no usable system catalog")
    return errors


def latest_tool(root: Path, name: str) -> Path:
    candidates = sorted(root.glob(f"*/{name}"))
    if not candidates:
        raise RuntimeError(f"Android SDK tool is missing: {name}")
    return candidates[-1]


def exact_install(adb: Path, serial: str, apk: Path, expected_sha: str,
                  output: Path, perform_install: bool = True) -> dict[str, object]:
    actual = sha256_file(apk)
    if actual != expected_sha.lower():
        raise RuntimeError(f"candidate SHA mismatch: expected {expected_sha}, got {actual}")

    def installed_identity(label: str) -> tuple[str, dict[str, object]]:
        package_path = qa.adb(adb, serial, "shell", "pm", "path", PACKAGE).stdout.strip()
        (output / f"package-{label}-path.txt").write_text(package_path + "\n")
        bases = [line.split(":", 1)[1] for line in package_path.splitlines()
                 if line.startswith("package:") and line.endswith("/base.apk")]
        if len(bases) != 1:
            raise RuntimeError(
                f"installed EmuFusion base.apk path was not found or is ambiguous ({label}); "
                "stop for recovery assessment, do not reinstall a missing package")
        report = qa.adb(adb, serial, "shell", "dumpsys", "package", PACKAGE).stdout
        (output / f"package-{label}-identity.txt").write_text(report)
        # Android 16 names this package-level field appId; older builds use
        # userId. Still require exactly one identity, never accept ambiguity.
        uids = re.findall(r"^\s*(?:userId|appId)=(\d+)\s*$", report, re.M)
        first_installs = re.findall(r"^\s*firstInstallTime=([^\r\n]+)", report, re.M)
        # Reused UID alone cannot prove a preserving update. Missing or
        # ambiguous identity evidence cannot authorize a QA replacement.
        if len(uids) != 1 or len(first_installs) != 1 or not first_installs[0].strip():
            raise RuntimeError(f"cannot establish installed package identity ({label}); no recovery retry")
        return bases[0], {"uid": int(uids[0]), "firstInstallTime": first_installs[0].strip()}

    _, identity_before = installed_identity("before")
    if perform_install:
        # Preserve the owner's app data and accept only a normal
        # same/newer-version replacement. The release gate explicitly forbids
        # downgrade or uninstall. Explicitly disable incremental delivery:
        # Thor lost package registration after a reported-success incremental
        # update. The installed-byte check below remains required with streaming.
        qa.adb(adb, serial, "install", "--no-incremental", "-r", str(apk))
    base, identity_after = installed_identity("after")
    if identity_before != identity_after:
        raise RuntimeError(
            f"package identity changed across QA replacement: {identity_before} -> {identity_after}; "
            "stop for settings/save recovery assessment, do not launch gameplay")
    installed = output / "installed-base.apk"
    with installed.open("wb") as handle:
        completed = subprocess.run(
            [str(adb), "-s", serial, "exec-out", "cat", base],
            stdout=handle, stderr=subprocess.PIPE,
        )
    if completed.returncode != 0:
        raise RuntimeError("cannot read installed Lucent base.apk")
    installed_sha = sha256_file(installed)
    if installed_sha != actual:
        raise RuntimeError(
            f"installed APK differs from candidate: {installed_sha} != {actual}"
        )
    # Reading the APK may take several seconds. Recheck after that transfer so
    # removal/replacement during verification cannot be reported as success.
    final_base, final_identity = installed_identity("verified")
    if final_base != base or final_identity != identity_before:
        raise RuntimeError("installed package changed during APK verification; stop for recovery assessment")
    return {"candidateSha256": actual, "installedSha256": installed_sha,
            "installedBaseApk": base,
            "replacementInstallPerformed": perform_install,
            "packageIdentityBefore": identity_before,
            "packageIdentityAfter": final_identity,
            # Identity stability is an installation check, NOT a save-content
            # comparison. Never elevate it to a claim of private-data retention.
            "privateDataRetentionVerified": False}


def assert_installed_hash(adb: Path, serial: str, expected_sha: str) -> dict[str, object]:
    """Fail closed if another installer/updater replaces the QA artifact."""
    package_path = qa.adb(adb, serial, "shell", "pm", "path", PACKAGE).stdout.strip()
    base = next((line.split(":", 1)[1] for line in package_path.splitlines()
                 if line.startswith("package:") and line.endswith("base.apk")), "")
    if not base:
        raise RuntimeError("installed Lucent base.apk path was not found by hash guard")
    completed = qa.adb(adb, serial, "shell", "sha256sum", base)
    actual = completed.stdout.strip().split()[0].lower()
    expected = expected_sha.lower()
    if actual != expected:
        raise RuntimeError(
            f"installed APK hash changed during QA: {actual} != {expected}"
        )
    return {"monotonicMs": int(time.monotonic() * 1000), "sha256": actual}


def library_index(adb: Path, serial: str) -> dict:
    forwarded = qa.adb(adb, serial, "forward", "tcp:0", "tcp:43821").stdout.strip()
    try:
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{forwarded}/library/index", timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            # Some AYN firmware revisions reject the companion Service start
            # even after MainActivity is visibly resumed. The signed Pegasus
            # metadata remains the source of truth and is independently read
            # by the frontend, so QA can reconstruct the same Alpha index
            # without weakening any launch/core/hash gate.
            return metadata_library_index(adb, serial)
    finally:
        qa.adb(adb, serial, "forward", "--remove", f"tcp:{forwarded}", check=False)


def import_service_request(adb: Path, serial: str, path: str,
                           *, method: str = "GET") -> dict[str, object]:
    forwarded = qa.adb(adb, serial, "forward", "tcp:0", "tcp:43821").stdout.strip()
    try:
        import urllib.request
        request = urllib.request.Request(
            f"http://127.0.0.1:{forwarded}{path}", method=method
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    finally:
        qa.adb(adb, serial, "forward", "--remove", f"tcp:{forwarded}", check=False)


def exact_remote_nes_fixture_paths(adb: Path, serial: str) -> set[str]:
    listing = qa.adb(
        adb, serial, "shell", "find /sdcard/Download /sdcard/Games/nes "
        "-type f -name '*.nes' 2>/dev/null", check=False,
    ).stdout.splitlines()
    return {remote_canonical_path(adb, serial, path.strip())
            for path in listing if path.strip() and
            remote_sha256(adb, serial, path.strip()) == NES_QUALIFICATION_SHA256}


def remote_path_exists(adb: Path, serial: str, path: str) -> bool:
    return qa.adb(
        adb, serial, "shell", "test -e " + shlex.quote(path), check=False
    ).returncode == 0


def remote_canonical_path(adb: Path, serial: str, path: str) -> str:
    quoted = shlex.quote(path)
    for command in ("readlink -f -- " + quoted, "realpath -- " + quoted):
        completed = qa.adb(adb, serial, "shell", command, check=False)
        values = [value.strip() for value in completed.stdout.splitlines()
                  if value.strip()]
        if completed.returncode == 0 and len(values) == 1 and values[0].startswith("/"):
            return canonical_shared_path(values[0])
    raise RuntimeError("could not canonicalize remote path: " + path)


def canonical_shared_path(path: str) -> str:
    if path == "/sdcard":
        return "/storage/emulated/0"
    if path.startswith("/sdcard/"):
        return "/storage/emulated/0/" + path[len("/sdcard/"):]
    return path


def read_import_registry(adb: Path, serial: str) -> dict[str, dict[str, object]]:
    completed = qa.adb(
        adb, serial, "exec-out", "cat", NES_IMPORT_REGISTRY, check=False
    )
    if completed.returncode != 0:
        if remote_path_exists(adb, serial, NES_IMPORT_REGISTRY):
            raise RuntimeError("EmuFusion import registry exists but is unreadable")
        return {}
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("EmuFusion import registry is malformed") from error
    if not isinstance(payload, list):
        raise RuntimeError("EmuFusion import registry is not an array")
    rows: dict[str, dict[str, object]] = {}
    for value in payload:
        if not isinstance(value, dict):
            raise RuntimeError("EmuFusion import registry contains a non-object row")
        identity = value.get("sourceIdentity")
        if not isinstance(identity, str) or not identity or identity in rows:
            raise RuntimeError("EmuFusion import registry has an invalid source identity")
        rows[identity] = value
    return rows


def validate_nes_registry_row(adb: Path, serial: str,
                              identity: str, row: dict[str, object],
                              indexed_path: str) -> None:
    if row.get("sourceIdentity") != identity:
        raise RuntimeError("NES fixture registry source identity changed")
    if normalize(str(row.get("system", ""))) != "nes" or \
            normalize(str(row.get("title", ""))) != normalize("Lucent Callback Test"):
        raise RuntimeError("NES fixture registry row has the wrong system or title")
    registry_path = str(row.get("file", ""))
    canonical_registry_path = remote_canonical_path(adb, serial, registry_path)
    canonical_indexed_path = remote_canonical_path(adb, serial, indexed_path)
    if (canonical_registry_path != canonical_indexed_path or
            remote_sha256(adb, serial, canonical_registry_path) !=
            NES_QUALIFICATION_SHA256):
        raise RuntimeError("NES fixture registry row does not bind the exact indexed ROM")


def delete_owned_nes_registry_row(adb: Path, serial: str,
                                  identity: str) -> dict[str, object]:
    import urllib.parse
    response = import_service_request(
        adb, serial, "/game/delete?id=" + urllib.parse.quote(identity, safe="")
    )
    if response.get("ok") is not True:
        raise RuntimeError("supported NES fixture registry delete did not return ok=true")
    return response


def resolve_live_nes_qualification(adb: Path, serial: str,
                                   index: dict) -> dict[str, str]:
    systems = index.get("systems") or {}
    nes = next((value for key, value in systems.items()
                if normalize(str(key)) == "nes"), None)
    alpha = nes.get("alpha") if isinstance(nes, dict) else None
    if not isinstance(alpha, list):
        raise RuntimeError("live index has no NES Alpha list")
    matching_titles = [title_from_key(str(key)) for key in alpha
                       if normalize(title_from_key(str(key))) ==
                       normalize("Lucent Callback Test")]
    if len(matching_titles) != 1:
        raise RuntimeError(
            "live index does not contain exactly one Lucent Callback Test"
        )
    case = SystemCase("nes", ("nintendoentertainmentsystem", "famicom"),
                      ("mesen",), 1)
    files = metadata_title_files(adb, serial, case).get(
        normalize("Lucent Callback Test"), set()
    )
    matches = [(remote_canonical_path(adb, serial, path),
                remote_sha256(adb, serial, path)) for path in sorted(files)]
    matches = sorted({(path, digest) for path, digest in matches
                      if digest == NES_QUALIFICATION_SHA256})
    if len(matches) != 1:
        raise RuntimeError(
            "live Lucent Callback Test does not resolve to one exact-hash ROM"
        )
    return {"title": "Lucent Callback Test", "path": matches[0][0],
            "sha256": matches[0][1]}


def main_process_pid(adb: Path, serial: str) -> int:
    completed = qa.adb(
        adb, serial, "shell", "pidof com.thorium.preview", check=False
    )
    values = re.findall(r"\b\d+\b", completed.stdout or "")
    if completed.returncode != 0 or len(values) != 1:
        raise RuntimeError("expected exactly one EmuFusion main process")
    return int(values[0])


def process_is_alive(adb: Path, serial: str, pid: int) -> bool:
    return qa.adb(
        adb, serial, "shell", f"test -d /proc/{pid}", check=False
    ).returncode == 0


def named_process_pids(adb: Path, serial: str, process_name: str) -> list[int]:
    completed = qa.adb(
        adb, serial, "shell", "pidof " + shlex.quote(process_name), check=False
    )
    if completed.returncode != 0:
        return []
    values = [int(value) for value in re.findall(r"\b\d+\b", completed.stdout or "")]
    if len(values) != len(set(values)):
        raise RuntimeError("process lookup returned duplicate PIDs: " + process_name)
    return values


def timestamped_logs(adb: Path, serial: str) -> str:
    """Return logcat with device timestamps for bounded reload diagnostics."""
    return qa.adb(
        adb, serial, "logcat", "-d", "-v", "threadtime"
    ).stdout


THREADTIME_LOG = re.compile(
    r"^(?P<month>\d{2})-(?P<day>\d{2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\."
    r"(?P<millisecond>\d{3})\s+(?P<pid>\d+)\s+(?P<tid>\d+)\s+"
    r"(?P<priority>[VDIWEF])\s+(?P<tag>[^:]+):\s?(?P<message>.*)$"
)
ABANDONED_SURFACE = re.compile(
    r"\[(?P<surface>.*?)\]"
    r"\(id:(?P<id>[^,]+),api:(?P<api>\d+),p:(?P<producer>\d+),"
    r"c:(?P<consumer>\d+)\)\s+(?P<operation>\w+):\s+"
    r"BufferQueue has been abandoned",
    re.I,
)


def deferred_remote_media_abandonment(line: str, new_pid: int) -> bool:
    """Defer only an exact remote API-3 preview queue to grouped validation."""
    match = ABANDONED_SURFACE.search(line)
    if match is None:
        return False
    surface = re.fullmatch(
        rf"SurfaceTexture-\d+-{new_pid}-\d+", match.group("surface")
    )
    return bool(
        surface and int(match.group("api")) == 3 and
        int(match.group("consumer")) == new_pid and
        int(match.group("producer")) != new_pid and
        match.group("operation").lower() in
        {"queuebuffer", "dequeuebuffer", "cancelbuffer", "connect"}
    )


def parse_threadtime_log(text: str) -> list[dict[str, object]]:
    records = []
    for line in text.splitlines():
        match = THREADTIME_LOG.match(line)
        if match is None:
            continue
        parts = {key: int(match.group(key)) for key in (
            "month", "day", "hour", "minute", "second", "millisecond", "pid"
        )}
        # A reload is sub-minute. This monotonically orders records even across
        # midnight without trusting the host clock or the current year.
        timestamp_ms = (((parts["month"] * 32 + parts["day"]) * 24 +
                         parts["hour"]) * 60 + parts["minute"]) * 60_000
        timestamp_ms += parts["second"] * 1000 + parts["millisecond"]
        records.append({
            "timestampMs": timestamp_ms,
            "pid": parts["pid"],
            "tag": match.group("tag").strip(),
            "message": match.group("message"),
            "line": line,
        })
    return records


def classify_reload_surface_teardown(threadtime_delta: str,
                                     new_pid: int) -> dict[str, object]:
    """Distinguish bounded codec teardown from an abandoned app renderer."""
    records = parse_threadtime_log(threadtime_delta)
    hard_markers = (
        "android egl swap failed", "egl_bad_surface", "0x300d",
        "renderer stopped", "engine session error",
        "dequeuebuffer failed", "queuebuffer failed",
    )
    def references_new_surface(message: str) -> bool:
        return bool(
            re.search(rf"SurfaceTexture-\d+-{new_pid}-\d+", message) or
            re.search(rf"\b(?:p|c):{new_pid}\b", message)
        )

    failures = [record["line"] for record in records
                if any(marker in str(record["message"]).lower()
                       for marker in hard_markers) and
                (int(record["pid"]) == new_pid or
                 references_new_surface(str(record["message"])))]
    groups: dict[tuple[object, ...], list[tuple[dict[str, object], re.Match[str]]]] = {}
    for record in records:
        match = ABANDONED_SURFACE.search(str(record["message"]))
        if match is None:
            continue
        if (not re.search(rf"SurfaceTexture-\d+-{new_pid}-\d+",
                          match.group("surface")) and
                int(match.group("producer")) != new_pid and
                int(match.group("consumer")) != new_pid):
            # The old process and unrelated media clients can tear down in the
            # same diagnostic capture. Only replacement-owned surfaces prove
            # or disprove the health of the fresh frontend.
            continue
        key = (match.group("surface"), match.group("id"), int(match.group("api")),
               int(match.group("producer")), int(match.group("consumer")))
        groups.setdefault(key, []).append((record, match))

    allowed_groups = []
    all_records: list[dict[str, object]] = []
    for key, items in groups.items():
        surface, surface_id, api, producer, consumer = key
        group_records = [record for record, _match in items]
        all_records.extend(group_records)
        operations = [match.group("operation").lower() for _record, match in items]
        span_ms = int(group_records[-1]["timestampMs"]) - int(
            group_records[0]["timestampMs"]
        )
        surface_pid_match = re.fullmatch(
            r"SurfaceTexture-\d+-(\d+)-\d+", str(surface)
        )
        surface_pid = int(surface_pid_match.group(1)) if surface_pid_match else -1
        queue_count = operations.count("queuebuffer")
        dequeue_count = operations.count("dequeuebuffer")
        if (api != 3 or surface_pid != new_pid or consumer != new_pid or
                producer == new_pid or
                any(op not in {"queuebuffer", "dequeuebuffer",
                              "cancelbuffer", "connect"}
                    for op in operations) or
                queue_count > 1 or
                dequeue_count > 1 or
                (queue_count and dequeue_count) or
                (queue_count == 1 and operations[0] != "queuebuffer") or
                "cancelbuffer" not in operations or
                operations.count("connect") > 1 or
                ("connect" in operations and operations[-1] != "connect") or
                span_ms < 0 or span_ms > 250):
            failures.append(str(group_records[0]["line"]))
            continue
        start_ms = int(group_records[0]["timestampMs"])
        end_ms = int(group_records[-1]["timestampMs"])
        nearby_records = [record for record in records
                          if start_ms - 500 <= int(record["timestampMs"]) <=
                          end_ms + 500]
        nearby = [(str(record["tag"]) + " " +
                   str(record["message"])).lower()
                  for record in nearby_records]
        families = set()
        if any("preparing video path=" in message or "prepared video path=" in message
               for message in nearby):
            families.add("ThorPreview")
        if any("nuplayer" in message and
               ("stop" in message or "reset" in message) for message in nearby):
            families.add("NuPlayer")
        if any("mediaplayer" in message and
               ("reset" in message or "release" in message or "drm" in message)
               for message in nearby):
            families.add("MediaPlayer")
        if any(("mediacodec" in message or "ccodec" in message or "qc2" in message) and
               ("stop" in message or "release" in message or "flush" in message)
               for message in nearby):
            families.add("MediaCodec")
        if any("surfaceutils" in message and
               ("disconnect" in message or "shutdown" in message)
               for message in nearby):
            families.add("SurfaceUtils")
        if len(families) < 2 or not families.intersection(
                {"NuPlayer", "MediaPlayer", "MediaCodec", "SurfaceUtils"}):
            failures.append("media teardown context missing: " + str(group_records[0]["line"]))
            continue
        queue_context = None
        dequeue_context = None
        if queue_count == 1:
            queue_record = group_records[0]
            try:
                queue_index = nearby_records.index(queue_record)
            except ValueError:
                failures.append(
                    "media queue teardown chronology missing: " +
                    str(group_records[0]["line"])
                )
                continue

            def first_after(start: int, predicate) -> int:
                for candidate in range(start + 1, len(nearby_records)):
                    combined = (str(nearby_records[candidate]["tag"]) + " " +
                                str(nearby_records[candidate]["message"])).lower()
                    if predicate(combined):
                        return candidate
                return -1

            nuplayer = first_after(
                queue_index,
                lambda value: "nuplayer" in value and
                ("stop(" in value or "reset(" in value),
            )
            codec_error = first_after(
                nuplayer,
                lambda value: ("ccodec" in value or "mediacodec" in value) and
                ("-19" in value or ("obsolete" in value and "surface" in value)),
            ) if nuplayer >= 0 else -1
            media_player = first_after(
                codec_error,
                lambda value: "mediaplayer" in value and
                ("reset" in value or "release" in value or "drm" in value),
            ) if codec_error >= 0 else -1
            surface_disconnect = first_after(
                media_player,
                lambda value: "surfaceutils" in value and "disconnect" in value,
            ) if media_player >= 0 else -1
            terminal = first_after(
                surface_disconnect,
                lambda value: ("resetcomplete" in value or
                               (("ccodec" in value or "mediacodec" in value) and
                                ("release" in value or "dealloc" in value))),
            ) if surface_disconnect >= 0 else -1
            if min(nuplayer, codec_error, media_player,
                   surface_disconnect, terminal) < 0:
                failures.append(
                    "media queue teardown chronology missing: " +
                    str(group_records[0]["line"])
                )
                continue
            queue_context = {
                "queueIndex": queue_index, "nuPlayerIndex": nuplayer,
                "codecErrorIndex": codec_error,
                "mediaPlayerIndex": media_player,
                "surfaceDisconnectIndex": surface_disconnect,
                "terminalIndex": terminal,
            }
        if dequeue_count == 1:
            dequeue_group_index = operations.index("dequeuebuffer")
            if (dequeue_group_index == 0 or
                    "cancelbuffer" not in operations[:dequeue_group_index] or
                    "cancelbuffer" not in operations[dequeue_group_index + 1:] or
                    "connect" not in operations or len(items) > 20 or span_ms > 32):
                failures.append(
                    "media dequeue teardown shape invalid: " +
                    str(group_records[0]["line"])
                )
                continue
            dequeue_record = group_records[dequeue_group_index]
            dequeue_nearby_index = nearby_records.index(dequeue_record)

            def find_before(end: int, predicate) -> int:
                for candidate in range(end - 1, -1, -1):
                    combined = (str(nearby_records[candidate]["tag"]) + " " +
                                str(nearby_records[candidate]["message"])).lower()
                    if predicate(combined):
                        return candidate
                return -1

            def find_after(start: int, predicate) -> int:
                for candidate in range(start + 1, len(nearby_records)):
                    combined = (str(nearby_records[candidate]["tag"]) + " " +
                                str(nearby_records[candidate]["message"])).lower()
                    if predicate(combined):
                        return candidate
                return -1

            nuplayer_stop = find_before(
                dequeue_nearby_index,
                lambda value: "nuplayer" in value and
                ("stop(" in value or "reset(" in value),
            )
            player_reset = find_before(
                dequeue_nearby_index,
                lambda value: "mediaplayer" in value and
                ("resetdrmstate" in value or "cleandrmobj" in value),
            )
            codec_dequeue = find_after(
                dequeue_nearby_index,
                lambda value: ("c2bq" in value or "ccodec" in value or
                               "qc2" in value) and
                ("dequeue" in value or "allocation" in value) and
                ("-19" in value or "fail" in value or "error" in value),
            )
            codec_flush = find_after(
                codec_dequeue,
                lambda value: ("codec" in value or "qc2" in value) and
                ("flushing" in value or "flush failure" in value or
                 "unknown_error" in value),
            ) if codec_dequeue >= 0 else -1
            surface_disconnect = find_after(
                codec_flush,
                lambda value: "surfaceutils" in value and
                "disconnect" in value,
            ) if codec_flush >= 0 else -1
            nuplayer_shutdown = find_after(
                surface_disconnect,
                lambda value: "nuplayer" in value and
                ("shutting down" in value or "shutdown" in value),
            ) if surface_disconnect >= 0 else -1
            release = find_after(
                nuplayer_shutdown,
                lambda value: "release" in value and "ok" in value,
            ) if nuplayer_shutdown >= 0 else -1
            null_producer = find_after(
                release,
                lambda value: "null producer" in value,
            ) if release >= 0 else -1
            shutdown_connect = find_after(
                null_producer,
                lambda value: "surfaceutils" in value and
                "onshutdown" in value and "connect" in value,
            ) if null_producer >= 0 else -1
            terminal_group_record = group_records[-1]
            try:
                terminal_group = nearby_records.index(terminal_group_record)
            except ValueError:
                terminal_group = -1
            reset_complete = find_after(
                terminal_group,
                lambda value: "notifyresetcomplete" in value,
            ) if terminal_group >= 0 else -1
            native_disconnect = find_after(
                reset_complete,
                lambda value: "disconnectnativewindow" in value,
            ) if reset_complete >= 0 else -1
            deallocated = find_after(
                native_disconnect,
                lambda value: ("codec" in value or "driver" in value) and
                ("dealloc" in value or "closed" in value),
            ) if native_disconnect >= 0 else -1
            required = (nuplayer_stop, player_reset, codec_dequeue, codec_flush,
                        surface_disconnect, nuplayer_shutdown, release,
                        null_producer, shutdown_connect, terminal_group,
                        reset_complete, native_disconnect, deallocated)
            if min(required) < 0 or not (
                    nuplayer_stop < dequeue_nearby_index and
                    player_reset < dequeue_nearby_index < codec_dequeue <
                    codec_flush < surface_disconnect < nuplayer_shutdown <
                    release < null_producer < shutdown_connect < terminal_group <
                    reset_complete < native_disconnect < deallocated):
                failures.append(
                    "media dequeue teardown chronology missing: " +
                    str(group_records[0]["line"])
                )
                continue
            dequeue_context = {
                "dequeueGroupIndex": dequeue_group_index,
                "nuPlayerStopIndex": nuplayer_stop,
                "mediaPlayerResetIndex": player_reset,
                "codecDequeueErrorIndex": codec_dequeue,
                "codecFlushErrorIndex": codec_flush,
                "surfaceDisconnectIndex": surface_disconnect,
                "nuPlayerShutdownIndex": nuplayer_shutdown,
                "releaseIndex": release, "nullProducerIndex": null_producer,
                "shutdownConnectIndex": shutdown_connect,
                "terminalGroupIndex": terminal_group,
                "resetCompleteIndex": reset_complete,
                "nativeDisconnectIndex": native_disconnect,
                "deallocatedIndex": deallocated,
            }
        allowed_groups.append({
            "surface": surface, "id": surface_id, "api": api,
            "producerPid": producer, "consumerPid": consumer,
            "events": len(items), "spanMs": span_ms,
            "operations": operations, "contextFamilies": sorted(families),
            "queueTeardownChronology": queue_context,
            "dequeueTeardownChronology": dequeue_context,
        })

    all_records.sort(key=lambda record: int(record["timestampMs"]))
    total = len(all_records)
    aggregate_span = (int(all_records[-1]["timestampMs"]) -
                      int(all_records[0]["timestampMs"])) if all_records else 0
    if total > 32 or aggregate_span > 250:
        failures.append(
            f"recurrent abandoned BufferQueue groups events={total} spanMs={aggregate_span}"
        )
    if len(allowed_groups) > 1:
        failures.append(
            f"recurrent abandoned BufferQueue groups count={len(allowed_groups)}"
        )
    fingerprint = hashlib.sha256("\n".join(
        str(record["line"]) for record in all_records
    ).encode("utf-8")).hexdigest()
    return {
        "failures": failures,
        "allowedGroups": allowed_groups,
        "totalAbandonments": total,
        "aggregateSpanMs": aggregate_span,
        "lastAbandonTimestampMs": (
            int(all_records[-1]["timestampMs"]) if all_records else None
        ),
        "fingerprint": fingerprint,
    }


def activity_record(text: str, component: str) -> tuple[str, str]:
    records = list(re.finditer(
        rf"(?m)^\s+\* Hist\s+#\d+: ActivityRecord\{{([^\s]+)[^\n]*"
        rf"{re.escape(component)}[^\n]*$", text
    ))
    if len(records) != 1:
        return "", ""
    match = records[0]
    following = re.search(r"(?m)^\s+\* Hist\s+#\d+: ActivityRecord\{", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return match.group(1), text[match.start():end]


def window_record(text: str, component: str) -> str:
    records = list(re.finditer(
        rf"(?m)^\s*Window #\d+ Window\{{[^\n]*{re.escape(component)}[^\n]*$",
        text,
    ))
    if len(records) != 1:
        return ""
    match = records[0]
    following = re.search(r"(?m)^\s*Window #\d+ Window\{", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def frontend_reload_snapshot(activities: str, windows: str) -> dict[str, object]:
    main_component = "com.thorium.preview/org.pegasus_frontend.android.MainActivity"
    preview_component = "com.thorium.preview/com.thorium.preview.PreviewActivity"
    main_token, main_activity = activity_record(activities, "MainActivity")
    preview_token, preview_activity = activity_record(activities, "PreviewActivity")
    main_window = window_record(windows, main_component)
    preview_window = window_record(windows, preview_component)

    def drawn_resumed(record: str) -> bool:
        return bool(record and "state=RESUMED" in record and
                    "reportedDrawn=true" in record and
                    "firstWindowDrawn=true" in record and
                    "nowVisible=true" in record)

    def drawn_window(record: str, display_id: int) -> bool:
        return bool(record and f"mDisplayId={display_id}" in record and
                    "mHasSurface=true" in record and
                    "isReadyForDisplay()=true" in record and
                    "Surface: shown=true" in record and
                    "mDrawState=HAS_DRAWN" in record and
                    "isOnScreen=true" in record and "isVisible=true" in record)

    main_focused = bool(
        re.search(r"topResumedActivity=.*MainActivity", activities) and
        re.search(r"ResumedActivity:.*MainActivity", activities) and
        re.search(r"mCurrentFocus=Window\{[^\n]*MainActivity", activities + windows) and
        "mTopFocusedDisplayId=0" in windows
    )
    return {
        "mainToken": main_token,
        "previewToken": preview_token,
        "mainDrawnResumed": drawn_resumed(main_activity),
        "mainFocused": main_focused,
        "mainWindowReady": drawn_window(main_window, 0),
        "previewDrawnResumed": drawn_resumed(preview_activity),
        "previewWindowReady": drawn_window(preview_window, 4),
    }


def reload_log_failures(delta: str, old_pid: int, new_pid: int) -> list[str]:
    failures = []
    for line in delta.splitlines():
        lowered = line.lower()
        compact = re.sub(r"\s+", "", lowered)
        if ("abort background activity starts" in lowered or
                "allowbackgroundactivitystart:false" in compact or
                "allowbackgroundactivitystart=false" in compact or
                "frontend restart bridge launch attempt failed" in lowered or
                "frontend restart stopped:" in lowered):
            failures.append(line)
            continue
        if (("anr in com.thorium.preview" in lowered) or
                ("com.thorium.preview" in lowered and
                 ("not responding" in lowered or
                  "input dispatching timed out" in lowered))):
            failures.append(line)
            continue
        if any(marker in lowered for marker in (
                "android egl swap failed", "egl_bad_surface", "0x300d",
                "renderer stopped", "engine session error",
                "dequeuebuffer failed", "queuebuffer failed")):
            logger = re.search(r"\(\s*(\d+)\s*\)", line)
            logger_pid = int(logger.group(1)) if logger else None
            new_surface = bool(
                re.search(rf"SurfaceTexture-\d+-{new_pid}-\d+", line) or
                re.search(rf"\b(?:p|c):{new_pid}\b", line)
            )
            if logger_pid == new_pid or new_surface:
                failures.append(line)
            continue
        if ("bufferqueue" in lowered and "abandon" in lowered and
                ("api:1" in compact or "dequeuebuffer:" in compact or
                 "queuebuffer:" in compact)):
            if not deferred_remote_media_abandonment(line, new_pid):
                failures.append(line)
    return failures


def bridge_reload_chronology(delta: str, old_pid: int,
                             new_pid: int) -> dict[str, object]:
    prefix = r"(?m)^[^\n]*?\(\s*(\d+)\s*\):\s*"
    ready = list(re.finditer(
        prefix + r"Frontend restart bridge ready oldPid=(\d+) bridgePid=(\d+) "
        r"resumed=true focused=true firstFrameDrawn=true\s*$", delta
    ))
    exited = list(re.finditer(
        prefix + r"Frontend restart observed old process exit oldPid=(\d+)\s*$",
        delta,
    ))
    launched = list(re.finditer(
        prefix + r"Frontend restart bridge launching fresh Qt process attempt=(\d+)\s*$",
        delta,
    ))
    if len(ready) != 1 or len(exited) != 1 or len(launched) != 1:
        raise RuntimeError("frontend restart bridge chronology is incomplete or ambiguous")
    ready_line, exit_line, launch_line = ready[0], exited[0], launched[0]
    ready_logger_pid = int(ready_line.group(1))
    ready_old_pid = int(ready_line.group(2))
    bridge_pid = int(ready_line.group(3))
    exit_logger_pid = int(exit_line.group(1))
    exit_old_pid = int(exit_line.group(2))
    launch_logger_pid = int(launch_line.group(1))
    launch_attempt = int(launch_line.group(2))
    if not ready_line.start() < exit_line.start() < launch_line.start():
        raise RuntimeError("frontend restart bridge markers are out of order")
    if (ready_old_pid != old_pid or exit_old_pid != old_pid or
            ready_logger_pid != bridge_pid or exit_logger_pid != bridge_pid or
            launch_logger_pid != bridge_pid or launch_attempt != 1):
        raise RuntimeError("frontend restart bridge marker PID/attempt mismatch")
    if len({old_pid, bridge_pid, new_pid}) != 3:
        raise RuntimeError("frontend restart old/bridge/new PIDs are not distinct")
    return {"bridgePid": bridge_pid, "readyLogPid": ready_logger_pid,
            "oldExitLogPid": exit_logger_pid,
            "launchLogPid": launch_logger_pid, "launchAttempt": launch_attempt,
            "readyOffset": ready_line.start(), "oldExitOffset": exit_line.start(),
            "launchOffset": launch_line.start()}


def frontend_reload_is_ready(proof: dict[str, object]) -> bool:
    return bool(
        proof.get("oldPidDead") and proof.get("differentNewPid") and
        proof.get("mainDrawnResumed") and proof.get("mainFocused") and
        proof.get("mainWindowReady") and proof.get("previewDrawnResumed") and
        proof.get("previewWindowReady") and proof.get("previewRecreated") and
        proof.get("serviceReady") and proof.get("bridgeProcessAcceptable") and
        proof.get("bridgeActivityGone") and proof.get("mediaTeardownQuiet") and
        not proof.get("postReloadLogFailures")
    )


def bridge_process_state(adb: Path, serial: str, bridge_pid: int,
                         activities: str, windows: str) -> dict[str, object]:
    alive = process_is_alive(adb, serial, bridge_pid)
    named = named_process_pids(adb, serial, "com.thorium.preview:frontend_restart")
    activity_gone = (
        "FrontendRestartActivity" not in activities and
        "FrontendRestartActivity" not in windows
    )
    services = qa.adb(
        adb, serial, "shell", "dumpsys", "activity", "services",
        "com.thorium.preview", check=False,
    ).stdout
    service_gone = not bool(re.search(
        rf"(?i)(?:pid\s*[=:]\s*{bridge_pid}\b|"
        rf"{re.escape('com.thorium.preview:frontend_restart')})", services
    ))
    if not alive:
        return {
            "bridgeProcessAlive": False, "bridgeNamedPids": named,
            "bridgeActivityGone": activity_gone,
            "bridgeServiceGone": service_gone, "bridgeForegroundGone": True,
            "bridgeCachedEmpty": False, "bridgeOomScoreAdj": None,
            "bridgeProcessAcceptable": activity_gone and service_gone and not named,
        }

    processes = qa.adb(
        adb, serial, "shell", "dumpsys", "activity", "processes", check=False
    ).stdout
    oom_result = qa.adb(
        adb, serial, "shell", "cat", f"/proc/{bridge_pid}/oom_score_adj",
        check=False,
    )
    oom_match = re.fullmatch(r"\s*(-?\d+)\s*", oom_result.stdout or "")
    oom_score = int(oom_match.group(1)) if (
        oom_result.returncode == 0 and oom_match is not None
    ) else None
    process_match = re.search(
        rf"(?ms)^\s*(?:\*APP\*\s+UID\s+\d+\s+)?\*?\s*"
        rf"ProcessRecord\{{[^\n]*\b{bridge_pid}:"
        rf"com\.thorium\.preview:frontend_restart/[^\n]*\}}.*?"
        rf"(?=^\s*(?:\*APP\*\s+UID\s+\d+\s+)?\*?\s*ProcessRecord\{{|\Z)",
        processes,
    )
    process_record = process_match.group(0) if process_match else ""
    lowered_record = process_record.lower().replace("_", "-")
    cached_empty = bool(
        process_record and oom_score is not None and oom_score >= 900 and
        ("cached-empty" in lowered_record or "cached empty" in lowered_record or
         re.search(r"\bcem\b", lowered_record) or
         ("cached=true" in lowered_record and "empty=true" in lowered_record) or
         re.search(r"(?:cur|set)procstate\s*=\s*(?:19|cached-empty)",
                   lowered_record))
    )
    foreground_gone = not bool(re.search(
        r"(?i)(?:hasForegroundServices|foregroundServices|foregroundService)\s*=\s*true",
        process_record,
    ))
    acceptable = bool(
        activity_gone and named == [bridge_pid] and service_gone and
        foreground_gone and cached_empty
    )
    return {
        "bridgeProcessAlive": True, "bridgeNamedPids": named,
        "bridgeActivityGone": activity_gone,
        "bridgeServiceGone": service_gone,
        "bridgeForegroundGone": foreground_gone,
        "bridgeCachedEmpty": cached_empty, "bridgeOomScoreAdj": oom_score,
        "bridgeProcessRecord": process_record,
        "bridgeProcessAcceptable": acceptable,
    }


def wait_frontend_reload(adb: Path, serial: str, old_pid: int,
                         old_preview_token: str, baseline_log: str,
                         baseline_threadtime_log: str,
                         timeout: float = 35.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    stable = 0
    last: dict[str, object] = {}
    teardown_fingerprint: Optional[str] = None
    teardown_quiet_since: Optional[float] = None
    while time.monotonic() < deadline:
        try:
            old_dead = not process_is_alive(adb, serial, old_pid)
            new_pid = main_process_pid(adb, serial)
            activities = qa.adb(
                adb, serial, "shell", "dumpsys", "activity", "activities"
            ).stdout
            windows = qa.adb(
                adb, serial, "shell", "dumpsys", "window", "windows"
            ).stdout
            snapshot = frontend_reload_snapshot(activities, windows)
            service_error = ""
            service_payload_valid = False
            try:
                index_payload = import_service_request(adb, serial, "/library/index")
                if isinstance(index_payload, dict):
                    index = index_payload
                    service_payload_valid = True
                else:
                    index = {}
                    service_error = (
                        "malformed library index payload type=" +
                        type(index_payload).__name__
                    )
            except (urllib.error.URLError, http.client.RemoteDisconnected,
                    ConnectionError, TimeoutError, OSError) as failure:
                index = {}
                service_error = (
                    "transient library index transport failure: " +
                    type(failure).__name__ + ": " + str(failure)
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as failure:
                index = {}
                service_error = (
                    "malformed library index response: " +
                    type(failure).__name__ + ": " + str(failure)
                )
            service_ready = bool(
                service_payload_valid and isinstance(index.get("systems"), dict)
            )
            if service_payload_valid and not service_ready:
                service_error = "malformed library index: systems is not an object"
            preview_recreated = bool(
                snapshot["previewToken"] and
                snapshot["previewToken"] != old_preview_token
            )
            delta = _log_delta(baseline_log, qa.logs(adb, serial))
            failures = reload_log_failures(delta, old_pid, new_pid)
            chronology = bridge_reload_chronology(delta, old_pid, new_pid)
            bridge_pid = int(chronology["bridgePid"])
            bridge_state = bridge_process_state(
                adb, serial, bridge_pid, activities, windows
            )
            timed_delta = _log_delta(
                baseline_threadtime_log, timestamped_logs(adb, serial)
            )
            teardown = classify_reload_surface_teardown(timed_delta, new_pid)
            if teardown["failures"]:
                failures.extend(str(value) for value in teardown["failures"])
            fingerprint = str(teardown["fingerprint"])
            now = time.monotonic()
            if teardown["totalAbandonments"]:
                if fingerprint != teardown_fingerprint:
                    teardown_fingerprint = fingerprint
                    teardown_quiet_since = now
                media_teardown_quiet = bool(
                    teardown_quiet_since is not None and
                    now - teardown_quiet_since >= 1.0
                )
            else:
                media_teardown_quiet = True
            last = {"oldPid": old_pid, "oldPidDead": old_dead,
                    "newPid": new_pid, "differentNewPid": new_pid != old_pid,
                    "oldPreviewToken": old_preview_token,
                    "previewRecreated": preview_recreated,
                    "serviceReady": service_ready,
                    "servicePayloadValid": service_payload_valid,
                    "serviceError": service_error,
                    "liveSystemCount": len(index.get("systems") or {}),
                    **chronology, **bridge_state,
                    "mediaTeardown": teardown,
                    "mediaTeardownQuiet": media_teardown_quiet,
                    **snapshot, "postReloadLogFailures": failures}
            ready = frontend_reload_is_ready(last)
            stable = stable + 1 if ready else 0
            if failures:
                raise RuntimeError(
                    "post-reload ANR/renderer/BufferQueue failure: " + failures[0]
                )
            if stable >= 2:
                last["stablePolls"] = stable
                return last
        except RuntimeError as failure:
            if "post-reload ANR/renderer/BufferQueue failure" in str(failure):
                raise
            last = {"pending": str(failure), **last}
        time.sleep(0.25)
    raise RuntimeError("EmuFusion frontend reload did not become healthy: " + str(last))


IMPORT_TERMINAL_STATES = {"idle", "complete", "error"}
IMPORT_ACTIVE_STATES = {
    "permission",
    "scanning",
    "discovering",
    "identified",
    "transferring",
    "artwork",
    "video",
    # 2026-09-06: ImportManager.runScan emits "cheats" while GameCheatDownloader
    # fetches per-game cheat catalogs between the video and scores passes.
    "cheats",
    "scores",
    "writing",
    "artless",
}
IMPORT_STATES = IMPORT_TERMINAL_STATES | IMPORT_ACTIVE_STATES
IMPORT_TRANSPORT_ERRORS = (
    http.client.RemoteDisconnected, ConnectionError, TimeoutError, OSError,
)


def validated_import_status(payload: object, source: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"malformed successful {source} payload type={type(payload).__name__}"
        )
    state = payload.get("state")
    if not isinstance(state, str) or state not in IMPORT_STATES:
        raise RuntimeError(
            f"malformed successful {source} state={state!r}"
        )
    running = payload.get("running")
    if not isinstance(running, bool):
        raise RuntimeError(f"malformed successful {source} running flag")
    if state in IMPORT_ACTIVE_STATES and not running:
        raise RuntimeError(f"malformed successful {source}: active state is not running")
    if state in IMPORT_TERMINAL_STATES and running:
        raise RuntimeError(f"malformed successful {source}: terminal state is running")
    return dict(payload)


def import_status_changed(baseline: dict[str, object],
                          observed: dict[str, object]) -> bool:
    if observed.get("state") != baseline.get("state"):
        return True
    before = baseline.get("updatedAt")
    after = observed.get("updatedAt")
    return isinstance(after, int) and (not isinstance(before, int) or after > before)


def wait_import_complete(adb: Path, serial: str, timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}

    # Bind the pre-trigger generation. If a POST disconnects after reaching the
    # service, an old terminal status must not be mistaken for this scan.
    while time.monotonic() < deadline:
        try:
            baseline = validated_import_status(
                import_service_request(adb, serial, "/import/status"),
                "import status",
            )
            break
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, *IMPORT_TRANSPORT_ERRORS) as failure:
            last = {"baselineTransport": type(failure).__name__}
            time.sleep(0.25)
    else:
        raise RuntimeError(
            "NES fixture import status endpoint never became reachable: " + str(last)
        )

    waiting_for_prior_scan = baseline.get("state") in IMPORT_ACTIVE_STATES
    scan_started = False
    trigger_attempts = 0

    def trigger_scan() -> None:
        nonlocal scan_started, trigger_attempts, last
        if trigger_attempts >= 3:
            return
        trigger_attempts += 1
        try:
            response = validated_import_status(
                import_service_request(
                    adb, serial, "/import/scan", method="POST"
                ),
                "import scan",
            )
        except urllib.error.HTTPError:
            # HTTP application failures are responses, not transient transport.
            raise
        except (urllib.error.URLError, *IMPORT_TRANSPORT_ERRORS) as failure:
            # Delivery is unknown. Poll status before considering another POST;
            # ImportManager.startScan is idempotent via running/fingerprint
            # guards, but the harness still avoids ambiguous duplicate triggers.
            last = {"scanDeliveryUnknown": True,
                    "transport": type(failure).__name__,
                    "triggerAttempts": trigger_attempts}
            return
        last = response
        state = response["state"]
        if state == "error":
            raise RuntimeError(
                "NES fixture import failed: " + str(response.get("message", ""))
            )
        if state in IMPORT_ACTIVE_STATES or (
                state == "complete" and import_status_changed(baseline, response)):
            scan_started = True

    if not waiting_for_prior_scan:
        trigger_scan()
    while time.monotonic() < deadline:
        try:
            observed = validated_import_status(
                import_service_request(adb, serial, "/import/status"),
                "import status",
            )
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, *IMPORT_TRANSPORT_ERRORS) as failure:
            last = {"statusTransport": type(failure).__name__,
                    "triggerAttempts": trigger_attempts,
                    "scanStarted": scan_started}
            time.sleep(0.25)
            continue
        last = observed
        state = observed["state"]
        if state in IMPORT_ACTIVE_STATES:
            if not waiting_for_prior_scan:
                scan_started = True
        elif state == "error" and waiting_for_prior_scan:
            # The failure belongs to the generation that predated fixture
            # staging. Bind that terminal result, then start our independent
            # generation; only an error from the new generation is fatal.
            baseline = observed
            waiting_for_prior_scan = False
            trigger_scan()
        elif state == "error":
            raise RuntimeError(
                "NES fixture import failed: " + str(observed.get("message", ""))
            )
        elif state == "complete" and waiting_for_prior_scan:
            # A scan that predated fixture staging is not qualification
            # evidence. Bind its terminal generation, then issue our scan.
            baseline = observed
            waiting_for_prior_scan = False
            trigger_scan()
        elif state == "complete" and (
                scan_started or import_status_changed(baseline, observed)):
            old_pid = main_process_pid(adb, serial)
            old_activities = qa.adb(
                adb, serial, "shell", "dumpsys", "activity", "activities"
            ).stdout
            old_preview_token, _record = activity_record(
                old_activities, "PreviewActivity"
            )
            if not old_preview_token:
                raise RuntimeError("lower PreviewActivity was absent before import reload")
            baseline_log = qa.logs(adb, serial)
            baseline_threadtime_log = timestamped_logs(adb, serial)
            reload = import_service_request(
                adb, serial, "/import/reload", method="POST"
            )
            if reload.get("ok") is True:
                last["reloadLifecycle"] = wait_frontend_reload(
                    adb, serial, old_pid, old_preview_token, baseline_log,
                    baseline_threadtime_log,
                )
            else:
                last["reloadLifecycle"] = {"reloadRequested": False,
                                           "oldPid": old_pid}
            return last
        elif state == "idle" and waiting_for_prior_scan:
            raise RuntimeError(
                "prior NES fixture import became idle without a terminal result"
            )
        elif state == "idle" or (
                state == "complete" and not scan_started):
            # Synchronous startScan sets `scanning` before responding. Therefore
            # idle, or the unchanged pre-trigger terminal generation,
            # proves the unknown POST did not begin this scan. Only now may the
            # bounded idempotent trigger be reissued.
            trigger_scan()
        time.sleep(0.25)
    raise RuntimeError(
        "NES fixture import/scan did not complete: " +
        str({"last": last, "triggerAttempts": trigger_attempts,
             "scanStarted": scan_started})
    )


def stage_nes_qualification_fixture(adb: Path, serial: str,
                                    fixture: Path) -> dict[str, object]:
    fixture = fixture.resolve()
    if not fixture.is_file() or sha256_file(fixture) != NES_QUALIFICATION_SHA256:
        raise RuntimeError("host NES qualification fixture is absent or has the wrong SHA")
    remote = "/sdcard/Download/Lucent Callback Test.nes"
    canonical_source = canonical_shared_path(remote)
    source_identity = canonical_source + ":" + str(fixture.stat().st_size)
    registry_before = read_import_registry(adb, serial)
    before = exact_remote_nes_fixture_paths(adb, serial)
    if before:
        try:
            indexed = resolve_live_nes_qualification(
                adb, serial, library_index(adb, serial)
            )
            preexisting_indexed_path = remote_canonical_path(
                adb, serial, indexed["path"]
            )
            matching_rows = [
                (identity, row) for identity, row in registry_before.items()
                if normalize(str(row.get("system", ""))) == "nes"
                and normalize(str(row.get("title", ""))) ==
                    normalize("Lucent Callback Test")
                if remote_canonical_path(adb, serial,
                                         str(row.get("file", ""))) ==
                   preexisting_indexed_path
            ]
            if len(matching_rows) != 1:
                raise RuntimeError("preexisting NES fixture has no unique registry row")
            preexisting_identity, preexisting_row = matching_rows[0]
            validate_nes_registry_row(
                adb, serial, preexisting_identity, preexisting_row,
                preexisting_indexed_path,
            )
            return {"createdByRun": False, "preexistingPaths": sorted(before),
                    "createdPaths": [], "hostSha256": NES_QUALIFICATION_SHA256,
                    "sourceIdentity": preexisting_identity,
                    "indexedTitle": indexed["title"],
                    "indexedPath": preexisting_indexed_path,
                    "indexedSha256": indexed["sha256"]}
        except RuntimeError:
            # A nested, unindexed owner copy is not discoverable by
            # ImportManager. Preserve it and continue with the root staging
            # target; ownership subtraction below ensures it is never deleted.
            pass
    if source_identity in registry_before:
        raise RuntimeError(
            "refusing NES qualification staging because its source identity "
            "is already registered"
        )
    if remote_path_exists(adb, serial, remote):
        raise RuntimeError(
            "refusing to overwrite existing /sdcard/Download/Lucent Callback Test.nes"
        )
    pushed = subprocess.run(
        [str(adb), "-s", serial, "push", str(fixture), remote],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30,
    )
    if pushed.returncode != 0 or remote_sha256(adb, serial, remote) != NES_QUALIFICATION_SHA256:
        qa.adb(adb, serial, "shell", "rm -f " + shlex.quote(remote), check=False)
        raise RuntimeError("could not stage the exact NES qualification fixture")
    staged_source = remote_canonical_path(adb, serial, remote)
    if staged_source != canonical_source:
        qa.adb(adb, serial, "shell", "rm -f " + shlex.quote(staged_source),
               check=False)
        raise RuntimeError("staged NES qualification source resolved unexpectedly")
    try:
        import_result = wait_import_complete(adb, serial) or {}
        after = exact_remote_nes_fixture_paths(adb, serial)
        created = after - before
        if not created:
            raise RuntimeError("NES importer did not publish the staged fixture")
        if staged_source in after:
            raise RuntimeError("NES importer did not consume its immediate Downloads source")
        indexed = resolve_live_nes_qualification(
            adb, serial, library_index(adb, serial)
        )
        indexed_path = remote_canonical_path(adb, serial, indexed["path"])
        if (indexed_path not in created or
                indexed["sha256"] != NES_QUALIFICATION_SHA256):
            raise RuntimeError(
                "live indexed NES fixture is not the importer-created destination"
            )
        registry_after = read_import_registry(adb, serial)
        created_registry = set(registry_after) - set(registry_before)
        if source_identity not in created_registry:
            raise RuntimeError("NES importer did not create the expected source identity")
        validate_nes_registry_row(
            adb, serial, source_identity, registry_after[source_identity],
            indexed_path,
        )
        return {"createdByRun": True, "preexistingPaths": sorted(before),
                "createdPaths": sorted(created),
                "hostSha256": NES_QUALIFICATION_SHA256,
                "sourceIdentity": source_identity,
                "reloadLifecycle": import_result.get("reloadLifecycle"),
                "indexedTitle": indexed["title"],
                "indexedPath": indexed_path,
                "indexedSha256": indexed["sha256"]}
    except Exception as failure:
        # Stage can fail after the importer has copied the ROM. Resolve every
        # exact-hash path that did not exist before this run and roll back only
        # that owned delta before propagating the original failure.
        cleanup_errors = []
        try:
            current = exact_remote_nes_fixture_paths(adb, serial)
            owned = current - before
            registry_current = read_import_registry(adb, serial)
            registry_owned = (source_identity not in registry_before and
                              source_identity in registry_current)
            if registry_owned:
                row = registry_current[source_identity]
                registry_path = str(row.get("file", ""))
                validate_nes_registry_row(
                    adb, serial, source_identity, row, registry_path
                )
                delete_owned_nes_registry_row(adb, serial, source_identity)
            for path in sorted(owned):
                if not remote_path_exists(adb, serial, path):
                    continue
                if remote_sha256(adb, serial, path) != NES_QUALIFICATION_SHA256:
                    raise RuntimeError("staged NES fixture changed during rollback")
                qa.adb(adb, serial, "shell", "rm -f " + shlex.quote(path))
            wait_import_complete(adb, serial)
            if owned & exact_remote_nes_fixture_paths(adb, serial):
                raise RuntimeError("staged NES fixture remained after rollback")
            leaked_owned = [path for path in sorted(owned)
                            if remote_path_exists(adb, serial, path)]
            if leaked_owned:
                raise RuntimeError(
                    "staged NES fixture paths still exist after rollback: " +
                    str(leaked_owned)
                )
            if source_identity in read_import_registry(adb, serial):
                raise RuntimeError("staged NES fixture registry row remained after rollback")
        except Exception as cleanup_error:
            cleanup_errors.append(str(cleanup_error))
        if cleanup_errors and hasattr(failure, "add_note"):
            failure.add_note("NES stage rollback failed: " + "; ".join(cleanup_errors))
        raise


def cleanup_nes_qualification_fixture(adb: Path, serial: str,
                                      stage: dict[str, object]) -> dict[str, object]:
    if not stage.get("createdByRun"):
        return {"performed": False, "preexistingPreserved": True,
                "removedPaths": [], "absenceVerified": False}
    identity = str(stage.get("sourceIdentity", ""))
    registry = read_import_registry(adb, serial)
    if not identity or identity not in registry:
        raise RuntimeError("owned NES fixture registry row is missing before cleanup")
    indexed_path = str(stage.get("indexedPath", ""))
    validate_nes_registry_row(adb, serial, identity, registry[identity], indexed_path)
    delete_owned_nes_registry_row(adb, serial, identity)
    removed = []
    for path in stage.get("createdPaths", []):
        path = str(path)
        if remote_path_exists(adb, serial, path):
            if remote_sha256(adb, serial, path) != NES_QUALIFICATION_SHA256:
                raise RuntimeError("owned NES fixture changed before cleanup; refusing deletion")
            qa.adb(adb, serial, "shell", "rm -f " + shlex.quote(path))
        removed.append(path)
    import_result = wait_import_complete(adb, serial) or {}
    if identity in read_import_registry(adb, serial):
        raise RuntimeError("owned NES fixture registry row remained after cleanup")
    remaining = exact_remote_nes_fixture_paths(adb, serial)
    leaked = sorted(set(removed) & remaining)
    if leaked:
        raise RuntimeError("owned NES fixture paths remained after cleanup: " + str(leaked))
    existing = [path for path in removed if remote_path_exists(adb, serial, path)]
    if existing:
        raise RuntimeError("owned NES fixture paths still exist after cleanup: " + str(existing))
    refreshed_index = library_index(adb, serial)
    refreshed_systems = refreshed_index.get("systems") or {}
    fixture_title = normalize("Lucent Callback Test")
    if any(
        normalize(title_from_key(str(key))) == fixture_title
        for system in refreshed_systems.values()
        if isinstance(system, dict)
        for key in (system.get("alpha") or [])
    ):
        raise RuntimeError("owned NES fixture row remained in the live index after rescan")
    return {"performed": True, "preexistingPreserved": True,
            "removedPaths": removed, "absenceVerified": True,
            "liveIndexAbsenceVerified": True,
            "reloadLifecycle": import_result.get("reloadLifecycle")}


def metadata_library_index(adb: Path, serial: str) -> dict:
    roots = (
        "/storage/emulated/0/Android/data/com.thorium.preview/files/"
        "pegasus-frontend/metafiles",
        "/storage/emulated/0/Android/data/com.thorium.preview/files/"
        "pegasus-frontend/metadata",
        "/storage/emulated/0/pegasus-frontend/metafiles",
        "/storage/emulated/0/pegasus-frontend",
    )
    systems: dict[str, set[str]] = {}
    for root in roots:
        listing = qa.adb(adb, serial, "shell", "find", root, "-maxdepth", "1",
                         "-type", "f", "-name", "*.metadata.pegasus.txt",
                         check=False).stdout.splitlines()
        for raw in listing:
            path = raw.strip()
            if not path:
                continue
            text = qa.adb(adb, serial, "exec-out", "cat", path,
                          check=False).stdout
            shortnames = [normalize(value) for value in
                          re.findall(r"^shortname:\s*(.+)$", text, re.M)]
            titles = [value.strip() for value in
                      re.findall(r"^game:\s*(.+)$", text, re.M)
                      if value.strip()]
            for shortname in shortnames:
                systems.setdefault(shortname, set()).update(titles)
        if systems:
            break
    if not systems:
        raise RuntimeError("neither companion index nor signed metadata is available")
    return {"systems": {
        system: {"alpha": [f"{index:06d}|{title}" for index, title in
                            enumerate(sorted(titles, key=lambda value: value.casefold()))]}
        for system, titles in systems.items()
    }, "source": "signed-metadata-fallback"}


def visible_system_order(apk: Path, index: dict) -> list[str]:
    _qml, _cfg, catalog = embedded_theme(apk)
    active = {normalize(value) for value in (index.get("systems") or {}).keys()}
    return ["all"] + [folder for folder in catalog
                      if folder != "all" and folder in active]


class PhysicalController:
    EV_SYN = 0
    EV_KEY = 1
    EV_ABS = 3
    SYN_REPORT = 0
    A = 304
    B = 305
    START = 315
    Y = 308
    L1 = 310
    R1 = 311
    L2 = 312
    STOP = 314
    VOLUME_DOWN = 114
    VOLUME_UP = 115
    UP = 544
    DOWN = 545
    LEFT = 546
    RIGHT = 547
    AXIS_CODES = {"ABS_X": 0, "ABS_Y": 1, "ABS_Z": 2,
                  "ABS_RX": 3, "ABS_RY": 4, "ABS_RZ": 5}
    HAT_X = 16
    HAT_Y = 17

    def __init__(self, adb: Path, serial: str, node: str):
        self.adb = adb
        self.serial = serial
        self.node = node
        self.trace: list[InputTrace] = []
        description = qa.adb(adb, serial, "shell", "getevent", "-lp", node).stdout
        self.axes = self.parse_axes(description)
        horizontal = "ABS_Z" if "ABS_Z" in self.axes else "ABS_RX"
        vertical = "ABS_RZ" if "ABS_RZ" in self.axes else "ABS_RY"
        if horizontal not in self.axes or vertical not in self.axes:
            raise RuntimeError("Thor right-stick axes were not found on controller node")
        self.horizontal = horizontal
        self.vertical = vertical
        self.left_horizontal = "ABS_X"
        self.left_vertical = "ABS_Y"
        if self.left_horizontal not in self.axes or self.left_vertical not in self.axes:
            raise RuntimeError("Thor left-stick axes were not found on controller node")

    @staticmethod
    def parse_axes(value: str) -> dict[str, tuple[int, int, int]]:
        result = {}
        pattern = re.compile(
            r"\b(ABS_(?:X|Y|Z|RZ|RX|RY))\b\s*:.*?min\s+(-?\d+),\s*max\s+(-?\d+)",
            re.I,
        )
        for name, minimum, maximum in pattern.findall(value):
            low, high = int(minimum), int(maximum)
            result[name.upper()] = (low, high, round((low + high) / 2))
        return result

    def event(self, event_type: int, code: int, value: int) -> None:
        qa.adb(self.adb, self.serial, "shell", "sendevent", self.node,
               str(event_type), str(code), str(value))

    def sync(self) -> None:
        self.event(self.EV_SYN, self.SYN_REPORT, 0)

    def neutralize(self, label: str) -> None:
        """Atomically release every controller state the QA process can own.

        ``sendevent`` changes the kernel device's persistent absolute state.
        If a prior run is interrupted between the asserted and centred halves
        of a motion, the next frontend session receives an indefinitely held
        stick even though no new QA input is being sent. Physical N64 r11
        demonstrated exactly that failure: the Alpha cursor walked from row
        282 to row 233 while the host only OCRed an immutable screenshot.
        Clear all stick/hat axes and QA-used buttons in one remote transaction,
        so no partially neutralized state is exposed between ADB round trips.
        """
        lines = []
        for name, (_low, _high, center) in sorted(
                self.axes.items(), key=lambda item: self.AXIS_CODES[item[0]]):
            lines.append(
                f"sendevent {shlex.quote(self.node)} {self.EV_ABS} "
                f"{self.AXIS_CODES[name]} {center}"
            )
        lines.extend((
            f"sendevent {shlex.quote(self.node)} {self.EV_ABS} {self.HAT_X} 0",
            f"sendevent {shlex.quote(self.node)} {self.EV_ABS} {self.HAT_Y} 0",
        ))
        for code in (self.A, self.B, self.Y, self.L1, self.R1, self.L2,
                     self.STOP, self.START):
            lines.append(
                f"sendevent {shlex.quote(self.node)} {self.EV_KEY} {code} 0"
            )
        lines.append(
            f"sendevent {shlex.quote(self.node)} {self.EV_SYN} "
            f"{self.SYN_REPORT} 0"
        )
        completed = subprocess.run(
            [str(self.adb), "-s", self.serial, "shell", "sh"],
            input="\n".join(lines) + "\n", text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5.0,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "physical controller neutralization failed: " +
                completed.stdout.strip()
            )
        self.trace.append(InputTrace(
            label + ":all-axes-and-buttons",
            time.monotonic_ns() // 1_000_000,
        ))
        # Let Qt consume the single neutral report before any intentional edge.
        time.sleep(0.25)

    def key_down(self, code: int, label: str) -> int:
        now = time.monotonic_ns() // 1_000_000
        self.trace.append(InputTrace(label + ":down", now))
        self.event(self.EV_KEY, code, 1)
        self.sync()
        return now

    def key_up(self, code: int, label: str) -> int:
        now = time.monotonic_ns() // 1_000_000
        self.trace.append(InputTrace(label + ":up", now))
        self.event(self.EV_KEY, code, 0)
        self.sync()
        return now

    def key(self, code: int, label: str, hold: float = 0.07) -> None:
        if code in {self.UP, self.DOWN, self.LEFT, self.RIGHT}:
            axis = self.HAT_Y if code in {self.UP, self.DOWN} else self.HAT_X
            value = -1 if code in {self.UP, self.LEFT} else 1
            self.trace.append(InputTrace(label + ":hat", time.monotonic_ns() // 1_000_000))
            self.event(self.EV_ABS, axis, value)
            self.sync()
            # A real human hat press remains asserted for roughly a tenth of a
            # second. Ultra-short synthetic pulses can reach evdev but be
            # missed by Qt between render/input polls, especially immediately
            # after an emulator returns to the library.
            time.sleep(max(hold, 0.12))
            self.event(self.EV_ABS, axis, 0)
            self.sync()
            # The Thor/Qt gamepad stack coalesces repeated hat taps while the
            # system-card transition is still settling. A human-paced release
            # interval is required; faster synthetic taps visibly skip input.
            time.sleep(0.65)
            return
        self.key_down(code, label)
        time.sleep(hold)
        self.key_up(code, label)
        time.sleep(0.10)

    def exact_quick_key_pair(self, code: int, label: str,
                             hold_ms: int = 40,
                             device_sleep_ms: Optional[float] = None) -> dict[str, object]:
        """Inject one device-timed pair and return its kernel edge proof.

        Separate ``adb shell sendevent`` calls made the previous nominal
        40-ms test hold the key for 131-169 ms of host/ADB latency.  One remote
        shell owns both edges here, while a concurrent ``getevent -lt`` reads
        the input subsystem's own timestamps.  The report therefore measures
        the event duration on Android rather than trusting a requested sleep or
        a host-side stopwatch.
        """
        if code not in {self.VOLUME_DOWN, self.VOLUME_UP}:
            raise ValueError("exact quick-pair capture is reserved for volume keys")
        if hold_ms <= 0:
            raise ValueError("hold_ms must be positive")
        monitor = subprocess.Popen(
            [str(self.adb), "-s", self.serial, "shell", "getevent", "-lt",
             "-c", "12", self.node],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            # Let getevent open the node before either edge is emitted.
            time.sleep(0.10)
            started = time.monotonic_ns() // 1_000_000
            self.trace.append(InputTrace(label + ":device-script-start", started))
            sleep_ms = hold_ms if device_sleep_ms is None else device_sleep_ms
            seconds = max(1.0, float(sleep_ms)) / 1000.0
            script = (
                f"sendevent {shlex.quote(self.node)} {self.EV_KEY} {code} 1\n"
                f"sendevent {shlex.quote(self.node)} {self.EV_SYN} {self.SYN_REPORT} 0\n"
                f"sleep {seconds:.3f}\n"
                f"sendevent {shlex.quote(self.node)} {self.EV_KEY} {code} 0\n"
                f"sendevent {shlex.quote(self.node)} {self.EV_SYN} {self.SYN_REPORT} 0\n"
            )
            completed = subprocess.run(
                [str(self.adb), "-s", self.serial, "shell", "sh"],
                input=script, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=5.0,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "device-side quick-tap injection failed: " + completed.stdout.strip()
                )
            self.trace.append(InputTrace(
                label + ":device-script-end", time.monotonic_ns() // 1_000_000
            ))
            # Allow getevent's final line to cross the ADB transport before the
            # host closes the monitor process.
            time.sleep(0.10)
        finally:
            monitor.terminate()
            try:
                observed, _ = monitor.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                monitor.kill()
                observed, _ = monitor.communicate(timeout=2.0)
        evidence = parse_quick_key_edges(observed, code)
        evidence["requestedHoldMs"] = hold_ms
        evidence["kernelTrace"] = observed
        return evidence

    def hat(self, direction: str, label: str, hold: float = 0.12) -> None:
        """Press the physical d-pad the way the Thor actually reports it.

        The Thor's d-pad is HAT axes (ABS_HAT0X/Y), not BTN_DPAD_* keys, so
        an EV_KEY 544-547 injection never reaches a running native-adapter
        game (physically confirmed against Cemu's Miiverse dialog,
        2026-08-16). One direction is held and released around a human hold.
        """
        code = 16 if direction in {"left", "right"} else 17
        value = -1 if direction in {"left", "up"} else 1
        self.trace.append(InputTrace(f"{label}:hat-{direction}",
                                     time.monotonic_ns() // 1_000_000))
        self.event(self.EV_ABS, code, value)
        self.sync()
        time.sleep(hold)
        self.event(self.EV_ABS, code, 0)
        self.sync()
        time.sleep(0.05)

    def chord(self, codes: tuple[int, ...], label: str,
              hold: float = 0.08) -> None:
        """Press multiple physical controller keys in one human chord."""
        for code in codes:
            self.key_down(code, label)
        time.sleep(hold)
        for code in reversed(codes):
            self.key_up(code, label)
        time.sleep(0.10)

    def stick(self, direction: str, hold: float = 0.16) -> None:
        axis_name = self.vertical if direction in {"up", "down"} else self.horizontal
        low, high, center = self.axes[axis_name]
        value = low if direction in {"up", "left"} else high
        code = self.AXIS_CODES[axis_name]
        self.trace.append(InputTrace("right-stick-" + direction,
                                     time.monotonic_ns() // 1_000_000))
        self.event(self.EV_ABS, code, value)
        self.sync()
        time.sleep(hold)
        self.event(self.EV_ABS, code, center)
        self.sync()
        time.sleep(0.16)

    def aim_right(self, horizontal: float, vertical: float,
                  label: str, settle: float = 0.80) -> None:
        """Place Thor's right stick at one bounded absolute IR position."""
        if not -1.0 <= horizontal <= 1.0 or not -1.0 <= vertical <= 1.0:
            raise ValueError("right-stick aim must remain in [-1, 1]")
        for name, fraction in ((self.horizontal, horizontal),
                               (self.vertical, vertical)):
            low, high, center = self.axes[name]
            value = round(center + fraction * (high - low) / 2.0)
            self.event(self.EV_ABS, self.AXIS_CODES[name], value)
        self.sync()
        self.trace.append(InputTrace(
            f"{label}:right-stick-{horizontal:+.3f}-{vertical:+.3f}",
            time.monotonic_ns() // 1_000_000,
        ))
        time.sleep(settle)

    def motion_pair(self, left_direction: str, right_direction: str,
                    hold: float = 0.45,
                    chord_codes: tuple[int, ...] = (),
                    chord_label: str = "",
                    right_scale: float = 1.0) -> None:
        """Drive both sticks and optionally click while IR remains aimed."""
        if not 0.0 < right_scale <= 1.0:
            raise ValueError("right-stick scale must be in (0, 1]")

        def axis_value(name: str, direction: str,
                       scale: float = 1.0) -> tuple[int, int]:
            low, high, center = self.axes[name]
            if direction in {"left", "up"}:
                value = round(center + (low - center) * scale)
            elif direction in {"right", "down"}:
                value = round(center + (high - center) * scale)
            else:
                value = center
            return self.AXIS_CODES[name], value

        left_name = (self.left_vertical if left_direction in {"up", "down"}
                     else self.left_horizontal)
        right_name = (self.vertical if right_direction in {"up", "down"}
                      else self.horizontal)
        for name, direction, scale in ((left_name, left_direction, 1.0),
                                       (right_name, right_direction,
                                        right_scale)):
            code, value = axis_value(name, direction, scale)
            self.event(self.EV_ABS, code, value)
        self.sync()
        self.trace.append(InputTrace(
            f"analog-motion-left-{left_direction}-right-{right_direction}",
            time.monotonic_ns() // 1_000_000,
        ))
        if chord_codes:
            # Wii IR is absolute. Press A while the right stick still holds the
            # cursor at the requested screen position; centring first and then
            # clicking only ever selects the middle of a title prompt.
            self.chord(chord_codes, chord_label or "physical-aimed-chord",
                       hold=0.08)
            time.sleep(max(0.0, hold - 0.18))
        else:
            time.sleep(hold)
        for name in (self.left_horizontal, self.left_vertical,
                     self.horizontal, self.vertical):
            code, value = axis_value(name, "center")
            self.event(self.EV_ABS, code, value)
        self.sync()
        time.sleep(0.05)

    def motion_left(self, direction: str, hold: float = 0.45,
                    scale: float = 1.0) -> None:
        """Drive only the gameplay stick, without clicking through menus.

        Switch qualification used to pair both sticks with an A press on every
        sample.  On a title screen that is navigation, not harmless motion: the
        03cd44 run walked from Blasphemous II's title menu into Options and then
        Accessibility.  A left-stick-only sweep can move a controllable player
        but cannot accept a highlighted menu row.
        """
        axis_name = (self.left_vertical if direction in {"up", "down"}
                     else self.left_horizontal)
        if not 0.0 < scale <= 1.0:
            raise ValueError("left-stick scale must be in (0, 1]")
        low, high, center = self.axes[axis_name]
        extreme = low if direction in {"up", "left"} else high
        value = round(center + (extreme - center) * scale)
        code = self.AXIS_CODES[axis_name]
        self.trace.append(InputTrace(
            f"analog-motion-left-only-{direction}",
            time.monotonic_ns() // 1_000_000,
        ))
        self.event(self.EV_ABS, code, value)
        self.sync()
        time.sleep(hold)
        self.event(self.EV_ABS, code, center)
        self.sync()
        time.sleep(0.05)

    def set_left_stick_vector(self, horizontal: float, vertical: float,
                              label: str, hold: float = 0.45) -> None:
        """Hold one non-neutral gameplay-stick vector without recentering.

        Strict unique-image qualification must not manufacture a discontinuity
        at every harness sample. This primitive lets a caller move directly
        from one vector to the next; the owning motion routine must call
        :meth:`center_left_stick` in ``finally``.
        """
        if not -1.0 <= horizontal <= 1.0 or not -1.0 <= vertical <= 1.0:
            raise ValueError("left-stick vector must remain in [-1, 1]")
        if horizontal == 0.0 and vertical == 0.0:
            raise ValueError("left-stick motion vector must be non-neutral")
        for name, fraction in ((self.left_horizontal, horizontal),
                               (self.left_vertical, vertical)):
            low, high, center = self.axes[name]
            value = round(center + fraction * (high - low) / 2.0)
            self.event(self.EV_ABS, self.AXIS_CODES[name], value)
        self.sync()
        self.trace.append(InputTrace(
            f"{label}:left-stick-{horizontal:+.3f}-{vertical:+.3f}",
            time.monotonic_ns() // 1_000_000,
        ))
        time.sleep(hold)

    def center_left_stick(self, label: str) -> None:
        """Release both gameplay-stick axes in one coherent input report."""
        for name in (self.left_horizontal, self.left_vertical):
            _low, _high, center = self.axes[name]
            self.event(self.EV_ABS, self.AXIS_CODES[name], center)
        self.sync()
        self.trace.append(InputTrace(
            label + ":left-stick-centered", time.monotonic_ns() // 1_000_000,
        ))
        time.sleep(0.05)

    def set_right_stick_vector(self, horizontal: float, vertical: float,
                               label: str, hold: float = 0.0) -> None:
        """Assert one right-stick vector until explicitly replaced/released.

        N64 C-buttons are the core's analog-index-1 axes. Holding C-UP through
        this path is more faithful than guessing a face-button alias and lets
        a simultaneous left-stick vector control Ocarina's first-person view.
        """
        if not -1.0 <= horizontal <= 1.0 or not -1.0 <= vertical <= 1.0:
            raise ValueError("right-stick vector must remain in [-1, 1]")
        if horizontal == 0.0 and vertical == 0.0:
            raise ValueError("right-stick vector must be non-neutral")
        for name, fraction in ((self.horizontal, horizontal),
                               (self.vertical, vertical)):
            low, high, center = self.axes[name]
            value = round(center + fraction * (high - low) / 2.0)
            self.event(self.EV_ABS, self.AXIS_CODES[name], value)
        self.sync()
        self.trace.append(InputTrace(
            f"{label}:right-stick-{horizontal:+.3f}-{vertical:+.3f}",
            time.monotonic_ns() // 1_000_000,
        ))
        if hold > 0.0:
            time.sleep(hold)

    def center_right_stick(self, label: str) -> None:
        """Release both C-button/right-stick axes in one coherent report."""
        for name in (self.horizontal, self.vertical):
            _low, _high, center = self.axes[name]
            self.event(self.EV_ABS, self.AXIS_CODES[name], center)
        self.sync()
        self.trace.append(InputTrace(
            label + ":right-stick-centered", time.monotonic_ns() // 1_000_000,
        ))
        time.sleep(0.05)


def image_metrics(image: Image.Image, output: Path) -> dict[str, object]:
    image = image.convert("RGB")
    sampled = list(image.resize((240, 135)).getdata())
    visible = sum(max(pixel) >= 18 for pixel in sampled)
    return {
        "path": str(output), "width": image.width, "height": image.height,
        "visibleFraction": round(visible / max(1, len(sampled)), 5),
        "distinctColors": len(set(sampled)),
        "visible": visible >= len(sampled) * 0.08 and len(set(sampled)) >= 48,
    }


def screenshot(adb: Path, serial: str, output: Path,
               display_token: Optional[str] = None) -> dict[str, object]:
    arguments = ["exec-out", "screencap"]
    if display_token is not None:
        arguments += ["-d", display_token]
    arguments += ["-p"]
    payload = qa.adb(adb, serial, *arguments, binary=True).stdout
    if not payload.startswith(b"\x89PNG"):
        raise RuntimeError("Android screenshot is not a PNG")
    output.write_bytes(payload)
    image = Image.open(io.BytesIO(payload)).convert("RGB")
    return image_metrics(image, output)


def begin_visible_return_recording(adb: Path, serial: str,
                                   prefix: str) -> tuple[subprocess.Popen, str]:
    """Start continuous composed-pixel capture before physical Stop.

    The file stays on the device until MediaMuxer has finalized its Winscope
    timestamp tracks.  A fixed five-second limit avoids relying on whether a
    host SIGINT is forwarded through a particular adb version.
    """
    safe_prefix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", prefix)[:80]
    remote = (
        f"/data/local/tmp/emufusion-return-{safe_prefix}-"
        f"{time.monotonic_ns()}.mp4"
    )
    process = subprocess.Popen(
        [str(adb), "-s", serial, "shell", "screenrecord",
         "--size", "960x540", "--bit-rate", "8M", "--time-limit", "5",
         remote],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    # Encoder setup is intentionally outside the measured interval.  The MP4
    # must later contain a pre-threshold frame, so this sleep cannot manufacture
    # a pass when setup is actually slower.
    time.sleep(0.80)
    if process.poll() is not None:
        detail = process.communicate(timeout=1.0)[0]
        raise RuntimeError("screenrecord could not start: " + detail.strip())
    return process, remote


def inject_held_stop_device_clocked(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str) -> dict[str, object]:
    """Emit one held Stop and bracket DOWN using Android elapsed time.

    ``/proc/uptime`` and Winscope v2 timestamps both use elapsed-realtime.  The
    first uptime read precedes DOWN in the same device shell, making
    ``pre + 1s`` a conservative lower bound for the actual hold threshold.
    """
    monitor = subprocess.Popen(
        [str(adb), "-s", serial, "shell", "getevent", "-t", "-c", "4",
         controller.node],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(0.10)
    host_down_lower_ms = time.monotonic_ns() // 1_000_000
    controller.trace.append(InputTrace("physical-stop:device-script-start",
                                       host_down_lower_ms))
    script = (
        "cat /proc/uptime\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_KEY} "
        f"{controller.STOP} 1\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} "
        f"{controller.SYN_REPORT} 0\n"
        "sleep 1.150\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_KEY} "
        f"{controller.STOP} 0\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} "
        f"{controller.SYN_REPORT} 0\n"
        "cat /proc/uptime\n"
    )
    completed = subprocess.run(
        [str(adb), "-s", serial, "shell", "sh"], input=script, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5.0,
    )
    controller.trace.append(InputTrace(
        "physical-stop:device-script-end",
        time.monotonic_ns() // 1_000_000,
    ))
    if completed.returncode != 0:
        monitor.terminate()
        raise RuntimeError(
            "device-clocked held Stop injection failed: " +
            completed.stdout.strip()
        )
    time.sleep(0.10)
    monitor.terminate()
    try:
        kernel_trace, _ = monitor.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        monitor.kill()
        kernel_trace, _ = monitor.communicate(timeout=2.0)
    edge = parse_quick_key_edges(kernel_trace, controller.STOP)
    if not 1_100 <= float(edge["holdMs"]) <= 1_300:
        raise RuntimeError(
            "held Stop kernel duration was outside 1100-1300 ms: " +
            str(edge["holdMs"])
        )
    uptime_lines = [line for line in completed.stdout.splitlines()
                    if re.fullmatch(r"\s*\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s*",
                                    line)]
    if len(uptime_lines) != 2:
        raise RuntimeError(
            "held Stop needs exactly two /proc/uptime samples; output=" +
            completed.stdout.strip()
        )
    before = return_video.parse_uptime_seconds(uptime_lines[0])
    after = return_video.parse_uptime_seconds(uptime_lines[1])
    if not 1.10 <= after - before <= 1.40:
        raise RuntimeError(
            f"device uptime bracket was not a single held Stop: {after - before:.3f}s"
        )
    trace_path = output / f"{prefix}-return-stop-input.json"
    trace_path.write_text(json.dumps({
        "schemaVersion": 1, "eventNode": controller.node,
        "action": "held-stop", "keyCode": controller.STOP,
        "uptimeBeforeSeconds": before, "uptimeAfterSeconds": after,
        "rawKernelTrace": kernel_trace,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "hostDownLowerBoundMs": host_down_lower_ms,
        "downLowerBoundElapsedNs": int(before * 1_000_000_000),
        "thresholdLowerBoundElapsedNs": int(before * 1_000_000_000) +
            1_000_000_000,
        "postReleaseElapsedNs": int(after * 1_000_000_000),
        "kernelEdges": edge,
        "tracePath": str(trace_path),
    }


def inject_nes_launch_device_clocked(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str) -> dict[str, object]:
    """Press physical A once and bind its kernel edge to Android uptime."""
    monitor = subprocess.Popen(
        [str(adb), "-s", serial, "shell", "getevent", "-t", "-c", "4",
         controller.node], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(0.10)
    script = (
        "cat /proc/uptime\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_KEY} {controller.A} 1\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} {controller.SYN_REPORT} 0\n"
        "sleep 0.055\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_KEY} {controller.A} 0\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} {controller.SYN_REPORT} 0\n"
        "cat /proc/uptime\n"
    )
    completed = subprocess.run(
        [str(adb), "-s", serial, "shell", "sh"], input=script, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5.0,
    )
    time.sleep(0.10)
    monitor.terminate()
    try:
        kernel_trace, _ = monitor.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        monitor.kill()
        kernel_trace, _ = monitor.communicate(timeout=2.0)
    if completed.returncode != 0:
        raise RuntimeError("device-clocked NES launch input failed")
    edge = parse_quick_key_edges(kernel_trace, controller.A)
    if not 40 <= float(edge["holdMs"]) <= 100:
        raise RuntimeError(f"NES launch A hold is not one physical tap: {edge['holdMs']} ms")
    uptime = [line for line in completed.stdout.splitlines()
              if re.fullmatch(r"\s*\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s*", line)]
    if len(uptime) != 2:
        raise RuntimeError("NES launch input lacks two device uptime samples")
    before = return_video.parse_uptime_seconds(uptime[0])
    after = return_video.parse_uptime_seconds(uptime[1])
    if not 0.04 <= after - before <= 0.20:
        raise RuntimeError("NES launch input uptime bracket is not one short tap")
    trace_path = output / f"{prefix}-nes-launch-input.json"
    trace_path.write_text(json.dumps({
        "schemaVersion": 1, "eventNode": controller.node,
        "action": "launch-a", "keyCode": controller.A,
        "uptimeBeforeSeconds": before, "uptimeAfterSeconds": after,
        "rawKernelTrace": kernel_trace,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    controller.trace.append(InputTrace("physical-a-launch:device-clocked",
                                       time.monotonic_ns() // 1_000_000))
    return {"inputLowerBoundElapsedNs": int(before * 1_000_000_000),
            "postReleaseElapsedNs": int(after * 1_000_000_000),
            "kernelEdges": edge, "tracePath": str(trace_path)}


def begin_nes_kernel_capture(adb: Path, serial: str,
                             controller: PhysicalController, output: Path,
                             prefix: str) -> dict[str, object]:
    path = output / f"{prefix}-nes-controller-kernel-trace.txt"
    handle = path.open("wb")
    process = subprocess.Popen(
        [str(adb), "-s", serial, "shell", "getevent", "-lt", controller.node],
        stdout=handle, stderr=subprocess.STDOUT,
    )
    time.sleep(0.12)
    capture = {"kind": "kernel", "path": path, "handle": handle,
               "process": process, "finalized": False}
    ACTIVE_NES_CAPTURES.append(capture)
    return capture


def finish_nes_kernel_capture(capture: dict[str, object]) -> Path:
    if capture.get("finalized"):
        return Path(capture["path"])
    process = capture["process"]
    handle = capture["handle"]
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()
    capture["finalized"] = True
    if capture in ACTIVE_NES_CAPTURES:
        ACTIVE_NES_CAPTURES.remove(capture)
    path = Path(capture["path"])
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("NES continuous kernel input trace is empty")
    return path


def begin_nes_logcat_capture(adb: Path, serial: str, output: Path,
                             prefix: str, pid: int) -> dict[str, object]:
    if pid <= 0:
        raise RuntimeError("NES logcat capture requires one exact package PID")
    path = output / f"{prefix}-nes-session-logcat.txt"
    handle = path.open("wb")
    process = subprocess.Popen(
        [str(adb), "-s", serial, "logcat", "--pid", str(pid),
         "-v", "threadtime"],
        stdout=handle, stderr=subprocess.STDOUT,
    )
    time.sleep(0.12)
    capture = {"kind": "logcat", "path": path, "handle": handle, "pid": pid,
               "process": process, "finalized": False}
    ACTIVE_NES_CAPTURES.append(capture)
    return capture


def snapshot_nes_logcat_capture(capture: dict[str, object], path: Path) -> Path:
    handle = capture["handle"]
    handle.flush()
    os.fsync(handle.fileno())
    path.write_bytes(Path(capture["path"]).read_bytes())
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("NES continuous logcat snapshot is empty")
    return path


def finish_nes_logcat_capture(capture: dict[str, object]) -> Path:
    if capture.get("finalized"):
        return Path(capture["path"])
    process = capture["process"]
    handle = capture["handle"]
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()
    capture["finalized"] = True
    if capture in ACTIVE_NES_CAPTURES:
        ACTIVE_NES_CAPTURES.remove(capture)
    path = Path(capture["path"])
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("NES continuous logcat capture is empty")
    return path


def finish_abandoned_nes_captures() -> list[str]:
    failures = []
    for capture in list(ACTIVE_NES_CAPTURES):
        try:
            if capture.get("kind") == "kernel":
                finish_nes_kernel_capture(capture)
            else:
                finish_nes_logcat_capture(capture)
        except Exception as error:
            failures.append(str(error))
    return failures


def _nes_video_guest_frame(path: Path) -> bool:
    image = Image.open(path).convert("RGB")
    if image.size != (960, 540):
        return False
    left = image.crop((0, 40, 112, 500))
    right = image.crop((848, 40, 960, 500))
    active = image.crop((128, 0, 832, 540))
    luma = lambda pixel: 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]
    pillar_luma = max(sum(luma(pixel) for pixel in pillar.getdata()) /
                      max(1, pillar.width * pillar.height)
                      for pillar in (left, right))
    active_visible = (sum(max(pixel) >= 24 for pixel in active.getdata()) /
                      max(1, active.width * active.height))
    # Real games may begin on a mostly-black legal/logo frame. The exact
    # destination rectangle is independently bound from runtime geometry logs;
    # video only needs non-menu guest pixels inside the expected pillars.
    return pillar_luma <= 12.0 and active_visible >= 0.03


def analyze_real_nes_panel_geometry(gameplay_screenshot: Path) -> dict[str, object]:
    """Prove a real title occupies the runtime-owned centered 4:3 rectangle.

    Unlike the calibration ROM, commercial games may author black pixels at
    either horizontal edge. Their screenshot proof therefore never infers an
    active rectangle from brightness. The runtime record owns x=240..1679;
    pixels independently prove black outer pillars and material image content
    at both physical panel edges inside that rectangle.
    """
    image = Image.open(gameplay_screenshot).convert("RGB")
    if image.size != (1920, 1080):
        raise ValueError("real NES screenshot is not the exact 1920x1080 panel")

    def luma(pixel: tuple[int, int, int]) -> float:
        return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]

    # Ignore the upper-left frame-rate badge while sampling essentially the
    # full physical pillars. A shifted/scaled guest still spills into these
    # central strips and fails the bright-pixel bound.
    pillar_boxes = ((0, 160, 240, 920), (1680, 160, 1920, 920))
    pillar_records = []
    for box in pillar_boxes:
        pixels = list(image.crop(box).getdata())
        values = [luma(pixel) for pixel in pixels]
        pillar_records.append({
            "meanLuma": sum(values) / len(values),
            "materialFraction": sum(value > 12.0 for value in values) /
            len(values),
        })
    if any(record["meanLuma"] > 2.0 or
           record["materialFraction"] > 0.002
           for record in pillar_records):
        raise ValueError("real NES screenshot has nonblack outer pillars")

    active = image.crop((240, 0, 1680, 1080))

    def material_fraction(crop: Image.Image) -> float:
        pixels = list(crop.getdata())
        return sum(luma(pixel) > 12.0 for pixel in pixels) / len(pixels)

    top_fraction = material_fraction(image.crop((240, 0, 1680, 8)))
    bottom_fraction = material_fraction(image.crop((240, 1072, 1680, 1080)))
    active_fraction = material_fraction(active)
    if top_fraction < 0.01 or bottom_fraction < 0.01:
        raise ValueError(
            "real NES screenshot has a top/bottom bar or clipped content"
        )
    if active_fraction < 0.03:
        raise ValueError("real NES screenshot has no material guest content")
    return {
        "panelWidth": 1920, "panelHeight": 1080,
        "expectedActiveLeft": 240, "expectedActiveTop": 0,
        "expectedActiveWidth": 1440, "expectedActiveHeight": 1080,
        "leftPillarMeanLuma": round(pillar_records[0]["meanLuma"], 6),
        "rightPillarMeanLuma": round(pillar_records[1]["meanLuma"], 6),
        "leftPillarMaterialFraction": round(
            pillar_records[0]["materialFraction"], 8
        ),
        "rightPillarMaterialFraction": round(
            pillar_records[1]["materialFraction"], 8
        ),
        "topEdgeMaterialFraction": round(top_fraction, 8),
        "bottomEdgeMaterialFraction": round(bottom_fraction, 8),
        "activeMaterialFraction": round(active_fraction, 8),
        "fullHeight": True, "aspectPreserved": True,
        "method": "runtime-owned-rectangle-plus-panel-pixels",
    }


def _ten_yard_selected_player(path: Path) -> int:
    image = Image.open(path).convert("RGB")
    if image.size != (1920, 1080):
        raise RuntimeError("10-Yard player cursor needs an exact panel screenshot")

    def red_cursor_pixels(top: int, bottom: int) -> int:
        count = 0
        for red, green, blue in image.crop((620, top, 800, bottom)).getdata():
            if (red >= 120 and red >= green * 1.4 and
                    red >= blue * 1.4):
                count += 1
        return count

    counts = {1: red_cursor_pixels(620, 710),
              2: red_cursor_pixels(710, 800)}
    selected = max(counts, key=counts.get)
    other = 1 if selected == 2 else 2
    if counts[selected] < 50 or counts[selected] - counts[other] < 25:
        raise RuntimeError(
            f"10-Yard player cursor is absent/ambiguous: {counts}"
        )
    return selected


def real_nes_gameplay_state(title: str, text: str,
                            path: Optional[Path] = None) -> Optional[str]:
    """Return a recognized commercial-title menu state, never a fuzzy title."""
    key = normalize(title)
    normalized_text = " ".join(text.upper().split())
    if PROHIBITED_TEXT.search(normalized_text):
        return "foreign-interstitial"
    if key == normalize("10-Yard Fight"):
        has_one = re.search(r"\b1\s+PLAYER\b", normalized_text) is not None
        has_two = re.search(r"\b2\s+PLAYERS?\b", normalized_text) is not None
        if has_one and has_two:
            if path is None:
                raise RuntimeError(
                    "10-Yard player menu needs cursor-bound screenshot pixels"
                )
            return f"10-yard-{_ten_yard_selected_player(path)}-player"
        if has_two:
            return "10-yard-2-player"
        if has_one:
            return "10-yard-1-player"
        if re.search(r"\b(?:SKILL|BEGINNER|INTERMEDIATE|EXPERT)\b",
                     normalized_text):
            return "10-yard-skill"
        if "10-YARD" in normalized_text and "FIGHT" in normalized_text:
            return "10-yard-title"
    elif key == normalize("1943: The Battle of Midway"):
        if ("PASSWORD" in normalized_text or "PRESS START" in normalized_text or
                ("1943" in normalized_text and "START" in normalized_text)):
            return "1943-start-menu"
    elif key == normalize("8 Eyes"):
        has_one = re.search(r"\b1\s+PLAYER\b", normalized_text) is not None
        has_two = re.search(r"\b2\s+PLAYERS?\b", normalized_text) is not None
        if has_one and has_two:
            return "8-eyes-player-select"
        if has_two:
            return "8-eyes-2-player"
        if has_one:
            return "8-eyes-1-player"
        has_continue = "CONTINUE" in normalized_text
        has_initiate = "INITIATE" in normalized_text
        if has_continue and has_initiate:
            return "8-eyes-initiate-continue"
        if has_continue:
            return "8-eyes-continue"
        if has_initiate:
            return "8-eyes-initiate"
        if any(label in normalized_text for label in
               ("LEVEL SELECT", "RUTH", "SPAIN", "EGYPT", "INDIA",
                "ITALY", "GERMANY")):
            return "8-eyes-level-select"
        if "8 EYES" in normalized_text or "PRESS START" in normalized_text:
            return "8-eyes-title"
    else:
        raise RuntimeError(f"unsupported real NES readiness title: {title}")
    return None


def real_nes_frame_change_fraction(left: Path, right: Path) -> float:
    before = Image.open(left).convert("RGB").crop((240, 0, 1680, 1080)).resize(
        (320, 240), Image.Resampling.BILINEAR
    )
    after = Image.open(right).convert("RGB").crop((240, 0, 1680, 1080)).resize(
        (320, 240), Image.Resampling.BILINEAR
    )
    pixels = list(ImageChops.difference(before, after).getdata())
    return sum(max(pixel) >= 12 for pixel in pixels) / len(pixels)


def analyze_real_nes_gameplay_frames(
        frames: list[Path], title: str, *,
        minimum_changed_pairs: Optional[int] = None) -> dict[str, object]:
    if len(frames) < 3:
        raise RuntimeError("real NES gameplay proof needs at least three frames")
    states = []
    texts = []
    for path in frames:
        # Every readiness/proof sample independently retains the physical
        # full-height destination proof, without invoking fixture markers.
        analyze_real_nes_panel_geometry(path)
        text = " ".join(ocr(path).upper().split())
        texts.append(text)
        states.append(real_nes_gameplay_state(title, text, path))
    visible_states = [(index, state) for index, state in enumerate(states)
                      if state is not None]
    if visible_states:
        raise RuntimeError(
            "real NES gameplay regressed to a title/menu/interstitial: " +
            repr(visible_states)
        )
    fractions = [real_nes_frame_change_fraction(left, right)
                 for left, right in zip(frames, frames[1:])]
    required = (len(fractions) if minimum_changed_pairs is None else
                minimum_changed_pairs)
    changed = sum(value >= 0.005 for value in fractions)
    if required < 1 or required > len(fractions) or changed < required:
        raise RuntimeError(
            "real NES gameplay did not sustain material frame changes: "
            f"changedPairs={changed}/{len(fractions)} fractions={fractions}"
        )
    return {
        "title": title, "frameCount": len(frames),
        "changedPairs": changed, "requiredChangedPairs": required,
        "changeFractions": [round(value, 8) for value in fractions],
        "titleMenuAbsent": True, "sustainedMaterialMotion": True,
        "frames": [{"path": str(path), "ocr": text}
                   for path, text in zip(frames, texts)],
    }


def require_real_nes_proof_health(
        records: list[dict[str, object]],
        baseline: dict[str, object]) -> dict[str, object]:
    baseline_end = int(baseline["window_end_ns"])
    pid = int(baseline["pid"])
    generator = int(baseline["generator"])
    later = [record for record in records
             if int(record["window_end_ns"]) > baseline_end]
    if len(later) < 3:
        raise RuntimeError("real NES proof has fewer than three complete HEALTH windows")
    if any(int(record["pid"]) != pid or
           int(record["generator"]) != generator for record in later):
        raise RuntimeError("real NES proof HEALTH crossed PID/generator identity")
    zero = [int(record["window_end_ns"]) for record in later
            if int(record.get("window_promoted", 0)) <= 0]
    if zero:
        raise RuntimeError(
            f"real NES proof contains zero-promotion HEALTH windows: {zero}"
        )
    return {"pid": pid, "generator": generator,
            "baselineWindowEndNs": baseline_end,
            "windowCount": len(later), "zeroPromotionWindows": 0,
            "windows": later}


def _capture_real_nes_gameplay_probe(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str, title: str,
        sequence: int) -> tuple[list[Path], list[Optional[str]], int,
                               list[dict[str, object]]]:
    frames = []
    states = []
    samples: list[dict[str, object]] = []
    sustained_started_ns: Optional[int] = None
    directions = (controller.RIGHT, controller.LEFT,
                  controller.RIGHT, controller.LEFT,
                  controller.UP, controller.DOWN,
                  controller.RIGHT)
    for index in range(8):
        path = output / (
            f"{prefix}-real-nes-readiness-{sequence:02d}-{index:02d}.png"
        )
        screenshot(adb, serial, path)
        frames.append(path)
        text = " ".join(ocr(path).upper().split())
        state = real_nes_gameplay_state(title, text, path)
        captured_ns = time.monotonic_ns()
        states.append(state)
        samples.append({"path": str(path), "hostMonotonicNs": captured_ns,
                        "state": state})
        # A recognized menu is actionable evidence, not part of a gameplay
        # motion probe. Return before sleeping or injecting a direction so the
        # caller can move the cursor/confirm while this exact state is still
        # present. This closes the r32 loop where an attract sequence began
        # during the old unconditional 19-second capture.
        if state is not None:
            elapsed_ns = (0 if sustained_started_ns is None else
                          int(samples[-1]["hostMonotonicNs"]) -
                          int(samples[0]["hostMonotonicNs"]))
            return frames, states, elapsed_ns, samples
        if sustained_started_ns is None:
            # The sustained-readiness clock starts only after an independently
            # captured sample proves that gameplay is menu-free.
            sustained_started_ns = time.monotonic_ns()
        if index < len(directions):
            controller.key(
                directions[index],
                f"real-nes-readiness-{sequence:02d}-direction-{index + 1}",
                hold=0.08,
            )
            # Seven intervals span >19 seconds with the PhysicalController's
            # human-paced hat release. This exceeds r31's ~8-second attract
            # burst and covers at least three five-second HEALTH windows.
            time.sleep(2.0)
    if sustained_started_ns is None:  # Defensive: every nonempty probe sets it.
        raise RuntimeError("real NES readiness never entered a sustained probe")
    elapsed_ns = int(samples[-1]["hostMonotonicNs"]) - int(
        samples[0]["hostMonotonicNs"])
    return frames, states, elapsed_ns, samples


def _drive_real_nes_menu_state(
        controller: PhysicalController, title: str, state: str,
        transition: int, recognized_host_ns: Optional[int],
        output: Optional[Path] = None,
        prefix: str = "") -> list[dict[str, object]]:
    label = f"real-nes-activate-{transition:02d}"
    actions: list[tuple[int, str]]
    if state == "foreign-interstitial":
        raise RuntimeError("real NES readiness encountered a foreign interstitial")
    if normalize(title) == normalize("10-Yard Fight"):
        if state == "10-yard-2-player":
            actions = [(controller.STOP, label + "-select-one-player")]
        elif state in {"10-yard-1-player", "10-yard-skill"}:
            actions = [(controller.START, label + "-confirm")]
        else:
            actions = [(controller.START, label + "-advance-title")]
    elif normalize(title) == normalize("1943: The Battle of Midway"):
        actions = [(controller.START, label + "-start")]
    elif normalize(title) == normalize("8 Eyes"):
        if state in {"8-eyes-2-player", "8-eyes-player-select"}:
            # Player options are horizontal. LEFT deterministically selects
            # one-player regardless of the prior cursor, then Start advances.
            actions = [(controller.LEFT, label + "-select-one-player"),
                       (controller.START, label + "-confirm-one-player")]
        elif state in {"8-eyes-continue", "8-eyes-initiate",
                       "8-eyes-initiate-continue"}:
            # Preserve an owner's existing Continue selection; either branch
            # is valid only if the subsequent sustained-gameplay gate passes.
            actions = [(controller.START, label + "-confirm-save-choice")]
        elif state == "8-eyes-level-select":
            actions = [(controller.A, label + "-choose-level"),
                       (controller.START, label + "-enter-level")]
        else:
            actions = [(controller.START, label + "-advance")]
    else:
        raise RuntimeError(f"unsupported real NES readiness title: {title}")
    result = []
    for action_index, (code, action_label) in enumerate(actions):
        capture = None
        capture_path = None
        if output is not None:
            capture_path = output / (
                f"{prefix}-real-nes-activation-{transition:02d}-"
                f"{action_index + 1:02d}.getevent.txt"
            )
            capture = subprocess.Popen(
                [str(controller.adb), "-s", controller.serial, "shell",
                 "getevent", "-lt", "-c", "4", controller.node],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            # Let the exact-node monitor attach before the physical edge.
            time.sleep(0.12)
        host_ns = time.monotonic_ns()
        if code in {controller.UP, controller.DOWN, controller.LEFT,
                    controller.RIGHT}:
            axis = controller.HAT_Y if code in {controller.UP, controller.DOWN} \
                else controller.HAT_X
            value = -1 if code in {controller.UP, controller.LEFT} else 1
            event = {"type": controller.EV_ABS, "code": axis, "value": value}
        else:
            event = {"type": controller.EV_KEY, "code": code, "value": 1}
        result.append({"label": action_label, "controllerCode": code,
                       "hostMonotonicNs": host_ns,
                       "recognizedFrameHostMonotonicNs": recognized_host_ns,
                       "sourceState": state, "attemptSequence": transition,
                       "kernelEvent": event,
                       "actionTracePath": (None if capture_path is None else
                                           str(capture_path))})
        try:
            controller.key(code, action_label, hold=0.08)
            if capture is not None:
                raw, _ = capture.communicate(timeout=5.0)
                capture_path.write_text(raw, encoding="utf-8")
                timed = nes_qa._kernel_timed_events(raw)
                expected = [(event["type"], event["code"], event["value"]),
                            (event["type"], event["code"], 0)]
                if [item[:3] for item in timed] != expected:
                    raise RuntimeError(
                        "real NES activation lacks its exact device input edges"
                    )
        finally:
            if capture is not None and capture.poll() is None:
                capture.terminate()
                try:
                    capture.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    capture.kill()
                    capture.wait(timeout=2.0)
        time.sleep(0.7)
    return result


def prepare_real_nes_gameplay(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str, title: str,
        continuous_log: Optional[dict[str, object]]) -> dict[str, object]:
    """Reach and prove sustained gameplay without deleting owner save state."""
    if title not in NES_REAL_QUALIFICATION_TITLES:
        raise RuntimeError(f"unreviewed real NES readiness title: {title}")
    if continuous_log is None:
        raise RuntimeError("real NES readiness lacks continuous PID-bound logcat")
    attempts = []
    actions: list[dict[str, object]] = []
    for sequence in range(1, 7):
        baseline_log = _live_nes_log_text(continuous_log)
        baseline_records = _framegen_health_records(
            baseline_log, "primary", 0
        )
        baseline = max(baseline_records,
                       key=lambda record: int(record["window_end_ns"]),
                       default=None)
        baseline_window = (-1 if baseline is None else
                           int(baseline["window_end_ns"]))
        frames, states, elapsed_ns, samples = _capture_real_nes_gameplay_probe(
            adb, serial, controller, output, prefix, title, sequence
        )
        later_health = [record for record in _framegen_health_records(
            _live_nes_log_text(continuous_log), "primary", 0
        ) if int(record["window_end_ns"]) > baseline_window]
        health = later_health
        if baseline is not None:
            identity = (int(baseline["pid"]), int(baseline["generator"]))
            if any((int(record["pid"]), int(record["generator"])) != identity
                   for record in later_health):
                raise RuntimeError(
                    "real NES readiness HEALTH crossed PID/generator identity"
                )
        attempts.append({"sequence": sequence,
                         "frames": [str(path) for path in frames],
                         "states": states, "samples": samples,
                         "elapsedNs": elapsed_ns,
                         "healthBaseline": baseline,
                         "healthWindows": health})
        if not any(state is not None for state in states):
            try:
                result = analyze_real_nes_gameplay_frames(
                    frames, title, minimum_changed_pairs=5
                )
                if elapsed_ns <= 19_000_000_000:
                    raise RuntimeError(
                        "real NES readiness did not exceed 19 seconds"
                    )
                if baseline is None or len(health) < 3 or any(
                        int(record.get("window_promoted", 0)) <= 0
                        for record in health[-3:]):
                    raise RuntimeError(
                        "real NES readiness has missing/zero-promotion HEALTH "
                        f"windows: {health[-3:]}"
                    )
                report = {"schemaVersion": 2, "title": title,
                          "actions": actions, "attempts": attempts,
                          "gameplay": result, "saveStatePreserved": True}
                path = output / f"{prefix}-real-nes-readiness.json"
                path.write_text(json.dumps(report, indent=2, sort_keys=True) +
                                "\n", encoding="utf-8")
                report["reportPath"] = str(path)
                return report
            except RuntimeError as failure:
                if not any(message in str(failure) for message in (
                        "did not sustain material frame changes",
                        "did not exceed 19 seconds",
                        "missing/zero-promotion HEALTH windows")):
                    raise
                state = "static-gameplay"
        else:
            state = next(state for state in reversed(states)
                         if state is not None)
        # A static, menu-free recovery is also causally tied to the last
        # observed sample. Persist that timestamp just like a recognized menu
        # so offline verification never has to synthesize it.
        recognized_host_ns = int(samples[-1]["hostMonotonicNs"])
        actions.extend(_drive_real_nes_menu_state(
            controller, title, state, sequence, recognized_host_ns,
            output, prefix
        ))
    raise RuntimeError(
        f"real NES title never reached sustained gameplay: {title}; "
        f"attempts={attempts}"
    )


def require_nes_runtime_geometry(
        log_text: str, gameplay_screenshot: Path, *,
        calibration_fixture: bool = True) -> dict[str, object]:
    matches = re.findall(
        r"Core frame presented engine=mesen system=nes .*?"
        r"surface=(\d+)x(\d+) .*?aspect=([0-9.]+) "
        r"destination=(\d+),(\d+) (\d+)x(\d+)",
        log_text,
    )
    if len(matches) != 1:
        raise RuntimeError("NES launch lacks one exact runtime geometry record")
    surface_w, surface_h, aspect, left, top, width, height = matches[0]
    surface_width, surface_height, destination_left, destination_top, \
        destination_width, destination_height = map(
            int, (surface_w, surface_h, left, top, width, height)
        )
    aspect_value = float(aspect)
    if abs(aspect_value - 4 / 3) > 0.002:
        raise RuntimeError(f"NES runtime geometry is not full-height 4:3: {matches[0]}")
    if (destination_top != 0 or destination_height != surface_height or
            destination_height != 1080 or destination_width != 1440 or
            abs(destination_width / destination_height - 4 / 3) > 0.002):
        raise RuntimeError(f"NES runtime geometry is not full-height 4:3: {matches[0]}")
    if (surface_width, destination_left) == (1440, 0):
        coordinate_space = "local-aspect-surface"
    elif (surface_width, destination_left) == (1920, 240):
        coordinate_space = "global-panel-surface"
    else:
        raise RuntimeError(
            "NES runtime geometry is neither the exact local aspect surface nor "
            f"the centered global panel surface: {matches[0]}"
        )
    try:
        global_geometry = (
            nes_qa.analyze_geometry(gameplay_screenshot)
            if calibration_fixture else
            analyze_real_nes_panel_geometry(gameplay_screenshot)
        )
    except ValueError as failure:
        kind = "calibration" if calibration_fixture else "real-title"
        raise RuntimeError(
            f"NES {kind} global screenshot does not prove centered full-height 4:3"
        ) from failure
    return {
        "runtimeSurface": f"{surface_width}x{surface_height}",
        "runtimeDestination": (
            f"{destination_left},{destination_top} "
            f"{destination_width}x{destination_height}"
        ),
        "runtimeCoordinateSpace": coordinate_space,
        "aspect": aspect_value, "fullHeight": True,
        "calibrationFixture": calibration_fixture,
        "globalScreenshot": global_geometry,
        "globalScreenshotPath": str(gameplay_screenshot),
    }


def finish_nes_launch_recording(
        adb: Path, serial: str, process: subprocess.Popen, remote: str,
        output: Path, prefix: str, input_lower_bound_ns: int,
        menu_reference: Path, expected_title: Optional[str]) -> dict[str, object]:
    try:
        recorder_output, _ = process.communicate(timeout=7.0)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.communicate(timeout=2.0)
        raise RuntimeError("NES launch screenrecord did not finalize") from error
    if process.returncode != 0:
        raise RuntimeError("NES launch screenrecord failed: " + recorder_output.strip())
    local_video = output / f"{prefix}-nes-launch-visible.mp4"
    pulled = subprocess.run(
        [str(adb), "-s", serial, "pull", remote, str(local_video)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15.0,
    )
    qa.adb(adb, serial, "shell", "rm", "-f", remote)
    if pulled.returncode != 0 or not local_video.is_file():
        raise RuntimeError("could not pull NES launch video")
    timestamps = return_video.parse_winscope_frame_timestamps(local_video.read_bytes())
    first, last = return_video.frame_window(
        timestamps, input_lower_bound_ns, before_ms=300, after_ms=650
    )
    ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
    if not ffmpeg.is_file():
        raise RuntimeError("ffmpeg is required for NES launch evidence")
    pattern = output / f"{prefix}-nes-launch-video-%06d.png"
    decoded = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i", str(local_video),
         "-map", "0:v:0", "-vf", f"select=between(n\\,{first}\\,{last})",
         "-fps_mode", "passthrough", "-start_number", "0", str(pattern)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60.0,
    )
    if decoded.returncode != 0:
        raise RuntimeError("could not decode NES launch video: " + decoded.stdout.strip())
    paths = sorted(output.glob(f"{prefix}-nes-launch-video-*.png"))
    if len(paths) != last - first + 1:
        raise RuntimeError("NES launch decoded frames do not match Winscope timestamps")
    frames = [nes_qa.TimedImage(index, timestamps[index], path)
              for index, path in zip(range(first, last + 1), paths)]

    def is_menu(path: Path) -> bool:
        return bool(classify_nes_library_frame(
            menu_reference, path, expected_title
        )["matched"])

    def is_guest(path: Path) -> bool:
        text = " ".join(ocr(path).upper().split())
        return not PROHIBITED_TEXT.search(text) and not any(
            label in text for label in ("SYSTEM VIEW", "LIST VIEW", "COVER VIEW")
        ) and _nes_video_guest_frame(path)

    pre_input_classification = require_nes_preinput_library_frame(
        frames, input_lower_bound_ns, menu_reference, expected_title
    )
    report = nes_qa.evaluate_launch_video(
        frames, input_lower_bound_ns, is_menu, is_guest
    )
    report["preInputMenuClassification"] = pre_input_classification
    report["videoPath"] = str(local_video)
    report["firstGuestGeometryMatched"] = True
    report["frames"] = [{"index": frame.index,
                         "elapsedNs": frame.elapsed_ns,
                         "path": str(frame.path)} for frame in frames]
    return report


def classify_nes_library_frame(menu_reference: Path, frame: Path,
                               expected_title: Optional[str]) -> dict[str, object]:
    """Identify a selected library frame without relying on tiny footer OCR."""
    difference = mean_absolute_difference(menu_reference, frame)
    text = " ".join(ocr(frame).upper().split())
    title_matched = expected_title is None or selected_title_matches(
        expected_title, text
    )
    rating_labels = [label for label in ("CRITICS", "USERS", "RELEASE")
                     if label in text]
    view_labels = [label for label in ("SYSTEM VIEW", "LIST VIEW", "COVER VIEW")
                   if label in text]
    # At screenrecord's 960x540 resolution Tesseract can omit the small footer,
    # as r12 did, while preserving the selected title and all three list-column
    # headings. A tight whole-frame reference bound prevents a title splash or
    # game frame from being mistaken for the library.
    structure_matched = bool(view_labels or len(rating_labels) >= 2)
    matched = difference < 65.0 and title_matched and structure_matched
    return {
        "matched": matched,
        "referenceMeanAbsoluteDifference": round(difference, 6),
        "referenceThresholdExclusive": 65.0,
        "expectedTitle": expected_title,
        "titleMatched": title_matched,
        "ratingLabels": rating_labels,
        "viewLabels": view_labels,
        "structureMatched": structure_matched,
        "ocr": text,
    }


def classify_generic_library_frame(menu_reference: Path,
                                   frame: Path) -> dict[str, object]:
    """Identify the library without depending on its tiny footer labels.

    Non-NES return video is encoded at 960x540.  At that resolution Tesseract
    commonly drops ``SYSTEM VIEW``/``LIST VIEW``/``COVER VIEW`` even though the
    much larger CRITICS/USERS/RELEASE columns and the reference-matched library
    composition are intact.  Reuse the structural half of the exact NES
    classifier, but deliberately omit a title match because generic systems do
    not have the NES title oracle at this call site.
    """
    return classify_nes_library_frame(menu_reference, frame, None)


def require_nes_preinput_library_frame(
        frames: list[nes_qa.TimedImage], input_lower_bound_ns: int,
        menu_reference: Path,
        expected_title: Optional[str]) -> dict[str, object]:
    pre_input = [frame for frame in frames
                 if frame.elapsed_ns <= input_lower_bound_ns]
    if not pre_input:
        raise RuntimeError(
            "NES launch recording has no timestamped pre-input frame"
        )
    classification = classify_nes_library_frame(
        menu_reference, pre_input[-1].path, expected_title
    )
    if not classification["matched"]:
        raise RuntimeError(
            "NES timestamped pre-input frame failed the library-menu classifier: " +
            json.dumps(classification, sort_keys=True)
        )
    return classification


def classify_nes_return_frames(
        frames: list[Path], menu_reference: Path,
        expected_title: Optional[str]) -> tuple[list[dict[str, object]], set[Path]]:
    """Require guest* followed by the exact selected NES library menu+.

    The selected calibration title legitimately contains ``Lucent``, so the
    generic prohibited-text scan cannot identify it. Acceptance instead binds
    that text to the known library reference, exact selected title, and menu
    structure. Once the library appears, gameplay may never reappear.
    """
    if not frames:
        raise RuntimeError("NES return captured no frames")
    if not expected_title:
        raise RuntimeError("NES return requires the exact selected title")
    evidence: list[dict[str, object]] = []
    menu_paths: set[Path] = set()
    menu_seen = False
    guest_seen = False
    for path in frames:
        selected = classify_nes_library_frame(
            menu_reference, path, expected_title
        )
        text = str(selected["ocr"])
        reference_bound = (
            float(selected["referenceMeanAbsoluteDifference"]) <
            float(selected["referenceThresholdExclusive"])
        )
        any_library = reference_bound and bool(selected["structureMatched"])
        if selected["matched"]:
            if not guest_seen:
                raise RuntimeError(
                    "NES return reached the selected library menu without "
                    "preceding guest pixels"
                )
            menu_seen = True
            menu_paths.add(path)
            state = "selected-menu"
        elif any_library:
            raise RuntimeError(
                f"NES return showed the wrong selected menu in {path.name}: {text}"
            )
        elif bool(selected["titleMatched"]):
            raise RuntimeError(
                f"NES return showed a title splash without library structure in "
                f"{path.name}: {text}"
            )
        elif PROHIBITED_TEXT.search(text):
            raise RuntimeError(
                f"visible NES return interstitial in {path.name}: {text}"
            )
        elif _nes_video_guest_frame(path):
            if menu_seen:
                raise RuntimeError(
                    f"NES guest pixels reappeared after the library menu in "
                    f"{path.name}"
                )
            state = "guest"
            guest_seen = True
        else:
            raise RuntimeError(
                f"NES return showed a foreign/unclassified frame in {path.name}: "
                f"{text}"
            )
        evidence.append({
            "path": str(path), "ocr": text, "state": state,
            "referenceMeanAbsoluteDifference": selected[
                "referenceMeanAbsoluteDifference"
            ],
            "titleMatched": selected["titleMatched"],
            "structureMatched": selected["structureMatched"],
        })
    if not menu_seen:
        raise RuntimeError("NES return never reached the exact selected library menu")
    return evidence, menu_paths


def begin_nes_launch_capture(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str) -> tuple[subprocess.Popen, str,
                                             dict[str, object]]:
    """Start/warm the recorder completely before emitting the physical A edge."""
    recorder, remote = begin_visible_return_recording(
        adb, serial, prefix + "-nes-launch"
    )
    try:
        clock = inject_nes_launch_device_clocked(
            adb, serial, controller, output, prefix
        )
    except Exception:
        if recorder.poll() is None:
            recorder.kill()
            recorder.communicate(timeout=2.0)
        qa.adb(adb, serial, "shell", "rm", "-f", remote, check=False)
        raise
    return recorder, remote, clock


def finish_visible_return_recording(
        adb: Path, serial: str, process: subprocess.Popen, remote: str,
        output: Path, prefix: str, threshold_ns: int,
        menu_reference: Path,
        expected_title: Optional[str] = None) -> tuple[dict[str, object], Path,
                                                       list[dict[str, object]],
                                                       list[dict[str, object]]]:
    """Finalize, decode, and grade continuous visible-return evidence."""
    try:
        recorder_output, _ = process.communicate(timeout=7.0)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.communicate(timeout=2.0)
        raise RuntimeError("screenrecord did not finalize its MP4") from error
    if process.returncode != 0:
        raise RuntimeError(
            f"screenrecord failed ({process.returncode}): {recorder_output.strip()}"
        )
    (output / f"{prefix}-return-screenrecord.txt").write_text(
        recorder_output, encoding="utf-8"
    )
    local_video = output / f"{prefix}-return-visible.mp4"
    pulled = subprocess.run(
        [str(adb), "-s", serial, "pull", remote, str(local_video)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        timeout=15.0,
    )
    qa.adb(adb, serial, "shell", "rm", "-f", remote)
    if pulled.returncode != 0 or not local_video.is_file():
        raise RuntimeError("could not pull visible-return video: " + pulled.stdout.strip())
    timestamps = return_video.parse_winscope_frame_timestamps(local_video.read_bytes())
    first, last = return_video.frame_window(timestamps, threshold_ns)
    ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
    if not ffmpeg.is_file():
        raise RuntimeError("ffmpeg is required to decode visible-return evidence")
    frame_pattern = output / f"{prefix}-return-video-%06d.png"
    selection = f"select=between(n\\,{first}\\,{last})"
    decoded = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i",
         str(local_video), "-map", "0:v:0", "-vf", selection,
         "-fps_mode", "passthrough", "-start_number", "0",
         str(frame_pattern)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        timeout=60.0,
    )
    if decoded.returncode != 0:
        raise RuntimeError("could not decode visible-return video: " + decoded.stdout.strip())
    paths = sorted(output.glob(f"{prefix}-return-video-*.png"))
    expected = last - first + 1
    if len(paths) != expected:
        raise RuntimeError(
            "decoded video frames do not match Winscope timestamps: "
            f"decoded={len(paths)} expected={expected}"
        )
    timed = [return_video.TimedFrame(index, timestamps[index], path)
             for index, path in zip(range(first, last + 1), paths)]
    similarities: list[dict[str, object]] = []
    menu_paths: set[Path] = set()
    if expected_title is not None:
        interstitial, menu_paths = classify_nes_return_frames(
            paths, menu_reference, expected_title
        )
        by_path = {Path(str(item["path"])): item for item in interstitial}
        if not any(
                frame.elapsed_ns <= threshold_ns and
                by_path[frame.path]["state"] == "guest"
                for frame in timed):
            raise RuntimeError(
                "NES return recording lacks guest pixels before the Stop threshold"
            )
        if any(
                frame.elapsed_ns < threshold_ns and
                by_path[frame.path]["state"] == "selected-menu"
                for frame in timed):
            raise RuntimeError(
                "NES library menu appeared before the Stop threshold"
            )
        for frame in timed:
            classification = by_path[frame.path]
            similarities.append({
                "path": str(frame.path), "frameIndex": frame.index,
                "elapsedNs": frame.elapsed_ns,
                "meanAbsoluteDifference": classification[
                    "referenceMeanAbsoluteDifference"
                ],
                "libraryViewVisible": classification["state"] == "selected-menu",
                "state": classification["state"],
                "titleMatched": classification["titleMatched"],
                "structureMatched": classification["structureMatched"],
            })
    else:
        # Other systems have no exact selected-title oracle here.  Require the
        # reference-matched library composition plus its large list headings;
        # tiny footer OCR is not reliable in the 960x540 return recording.
        # Prohibited splash/interstitial frames were rejected immediately
        # above and a gameplay frame lacks the list-column structure.
        interstitial = assert_no_interstitial(paths)
        for frame in timed:
            classification = classify_generic_library_frame(
                menu_reference, frame.path
            )
            if classification["matched"]:
                menu_paths.add(frame.path)
            similarities.append({
                "path": str(frame.path), "frameIndex": frame.index,
                "elapsedNs": frame.elapsed_ns,
                "meanAbsoluteDifference": classification[
                    "referenceMeanAbsoluteDifference"
                ],
                "libraryViewVisible": classification["matched"],
                "structureMatched": classification["structureMatched"],
            })
    report = return_video.evaluate_visible_return(
        timed, threshold_ns, lambda path: path in menu_paths,
    )
    report["videoPath"] = str(local_video)
    first_path = next(frame.path for frame in timed
                      if frame.index == report["firstMenuFrameIndex"])
    return report, first_path, similarities, interstitial


def _thor_usb_chooser_window(window_dump: str) -> Optional[str]:
    """Return Thor's exact visible vendor USB chooser window, if present.

    AYN can raise this system-alert window after USB reconnect even when the
    launcher is already interactive.  It fully covers the library and makes
    menu OCR time out.  Bind dismissal to the measured vendor component,
    dimensions, frame, and visibility so this can never become a blind tap on
    EmuFusion or an unrelated Android dialog.
    """
    blocks = re.findall(
        r"(?:^|\n)([ \t]*Window #[0-9]+ Window.*?)(?=\n[ \t]*Window #[0-9]+ Window|\Z)",
        window_dump,
        re.S,
    )
    for block in blocks:
        if "com.odin.settings" not in block:
            continue
        visible = "isOnScreen=true" in block and "isVisible=true" in block
        if not visible:
            continue
        # Thor also keeps a harmless visible 1x1 NOT_TOUCHABLE
        # MAGNIFICATION_OVERLAY owned by com.odin.settings. It is not the USB
        # chooser and must neither be tapped nor make startup fail. Only a
        # window that advertises the chooser's alert app-op or measured size is
        # eligible for the strict geometry check below.
        chooser_candidate = (
            "appop=SYSTEM_ALERT_WINDOW" in block or
            "Requested w=1248 h=545" in block
        )
        if not chooser_candidate:
            continue
        required = (
            "appop=SYSTEM_ALERT_WINDOW",
            "Requested w=1248 h=545",
            "frame=[336,267][1584,812]",
        )
        if not all(value in block for value in required):
            raise RuntimeError(
                "visible Thor USB chooser did not match the safe Cancel geometry"
            )
        return block
    return None


def dismiss_thor_usb_chooser_if_present(adb: Path, serial: str,
                                        output: Path) -> bool:
    """Dismiss only the proven vendor USB chooser's Cancel control."""
    windows = qa.adb(
        adb, serial, "shell", "dumpsys", "window", "windows"
    ).stdout
    chooser = _thor_usb_chooser_window(windows)
    if chooser is None:
        return False
    (output / "startup-usb-chooser-window.txt").write_text(
        chooser, encoding="utf-8"
    )
    # The exact frame above has a single bottom-right Cancel control. This
    # preserves the owner's selected USB function and merely closes the prompt.
    qa.adb(adb, serial, "shell", "input", "tap", "1450", "755")
    return True


def wait_visible_menu(adb: Path, serial: str, output: Path,
                      timeout: float = 60.0) -> Path:
    """Wait until the actual interactive library replaces the startup splash.

    The library HTTP index can be ready several seconds before QML has replaced
    the splash. Controller events during that interval are correctly ignored by
    EmuFusion, so acceptance must not mistake them for failed physical controls.
    """
    deadline = time.monotonic() + timeout
    latest_text = ""
    attempt = 0
    while time.monotonic() < deadline:
        if dismiss_thor_usb_chooser_if_present(adb, serial, output):
            time.sleep(0.5)
            continue
        path = output / f"startup-menu-ready-{attempt:02d}.png"
        screenshot(adb, serial, path)
        latest_text = " ".join(ocr(path).upper().split())
        splash = "POWERED BY PEGASUS" in latest_text
        interactive = (
            any(label in latest_text for label in
                ("COVER VIEW", "LIST VIEW", "SYSTEM VIEW"))
            and any(label in latest_text for label in
                    ("SYSTEM", "TITLES", "CONTINUE", "RECENTLY"))
        )
        # The home rows are large, high-contrast labels the OCR reads even
        # when the small footer over busy artwork comes back as noise
        # (2026-09-04: "CONTINUE PLAYING" and "MOST PLAYED" were legible while
        # "COVER VIEW" read as "BSS CO B", failing a healthy startup).
        if not interactive:
            interactive = ("CONTINUE PLAYING" in latest_text or
                           "MOST PLAYED" in latest_text)
        if interactive and not splash:
            return path
        attempt += 1
        time.sleep(0.45)
    raise RuntimeError(
        "Lucent did not expose an interactive menu after startup; "
        f"last OCR={latest_text}"
    )


def changed_pixels(left: Path, right: Path, threshold: int = 18) -> int:
    before = Image.open(left).convert("RGB").resize((320, 180))
    after = Image.open(right).convert("RGB").resize((320, 180))
    difference = ImageChops.difference(before, after)
    return sum(max(pixel) >= threshold for pixel in difference.getdata())


def mean_absolute_difference(left: Path, right: Path) -> float:
    before = Image.open(left).convert("RGB").resize((192, 108))
    after = Image.open(right).convert("RGB").resize((192, 108))
    pixels = list(ImageChops.difference(before, after).getdata())
    return sum(sum(pixel) / 3.0 for pixel in pixels) / max(1, len(pixels))


def ocr(path: Path) -> str:
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        return ""
    # Dark low-contrast game UI (Metroid Dread's SAMUS FILES) classified in
    # only ~1 of 10 frames under a single raw psm-6 pass, so the stable
    # recognized-twice gates could never latch (run switch27). A grayscale
    # autocontrast pass plus a sparse-text mode makes recognition of the
    # SAME vocabulary reliable; no classifier text is weakened by this.
    variants = [(str(path), None)]
    try:
        image = Image.open(path).convert("L")
        from PIL import ImageOps
        boosted = ImageOps.autocontrast(image, cutoff=1)
        # This derived OCR aid is scratch, not evidence. Send it in memory so
        # thousands of probes cannot accumulate duplicate PNGs on disk.
        with io.BytesIO() as buffer:
            boosted.save(buffer, format="PNG")
            variants.append(("stdin", buffer.getvalue()))
    except Exception:
        pass
    parts = []
    for variant, payload in variants:
        for psm in ("6", "11"):
            completed = subprocess.run(
                [str(tesseract), variant, "stdout", "--psm", psm],
                input=payload, check=False, capture_output=True,
            )
            parts.append(completed.stdout.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def ocr_region(path: Path, box: tuple[int, int, int, int], psm: int = 6) -> str:
    """OCR a logical 1920x1080 region without leaking a user's ROM path."""
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        return ""
    image = Image.open(path).convert("RGB")
    sx, sy = image.width / 1920.0, image.height / 1080.0
    scaled = (round(box[0] * sx), round(box[1] * sy),
              round(box[2] * sx), round(box[3] * sy))
    with io.BytesIO() as buffer:
        image.crop(scaled).save(buffer, format="PNG")
        completed = subprocess.run(
            [str(tesseract), "stdin", "stdout", "--psm", str(psm)],
            input=buffer.getvalue(), check=False, capture_output=True,
        )
    return completed.stdout.decode("utf-8", errors="replace")


def wii_galaxy_title_prompt(path: Path) -> tuple[bool, str]:
    """Recognize the Galaxy A+B prompt without trusting the stylized logo."""
    # The prompt's vertical position depends on the letterboxed gameplay
    # frame: on 2026-09-02 (run wii-b50b) Galaxy 2's "Press A and B." sat at
    # y~735-770 and the historical 760-920 strip read only the copyright
    # line for 64 probes.  Scan the historical strip and a raised one; the
    # first strip that proves the prompt wins.
    texts = []
    for box in ((500, 760, 1450, 920), (500, 690, 1450, 800),
                (500, 700, 1450, 920)):
        text = " ".join(ocr_region(path, box, 11).upper().split())
        texts.append(text)
        # The stylized prompt font OCRs unreliably ("TA BRESS © AND )." was
        # physically captured on the Thor, 2026-08-15): accept common P/B
        # and partial-word confusions of PRESS as long as AND is present.
        press = any(token in text
                    for token in ("PRESS", "BRESS", "RESS", "ESS "))
        conjunction = any(token in text
                          for token in ("AND", "OND", "ANO", "4ND"))
        if press and conjunction:
            return True, text
    return False, " | ".join(texts)


def nes_system_label_ocr(path: Path) -> str:
    """Read the red NES platform label independently of a busy wallpaper."""
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        return ""
    image = Image.open(path).convert("RGB")
    sx, sy = image.width / 1920.0, image.height / 1080.0
    box = (35, 120, 800, 180)
    crop = image.crop((round(box[0] * sx), round(box[1] * sy),
                       round(box[2] * sx), round(box[3] * sy)))
    mask = Image.new("L", crop.size)
    mask.putdata([
        0 if red >= 140 and red >= green * 1.35 and red >= blue * 1.20
        else 255
        for red, green, blue in crop.getdata()
    ])
    mask = mask.resize((mask.width * 2, mask.height * 2))
    with io.BytesIO() as buffer:
        mask.save(buffer, format="PNG")
        completed = subprocess.run(
            [str(tesseract), "stdin", "stdout", "--psm", "7"],
            input=buffer.getvalue(), check=False, capture_output=True,
        )
    return completed.stdout.decode("utf-8", errors="replace")


def psp_system_label_ocr(path: Path) -> str:
    """Read the blue PSP platform label independently of busy artwork.

    Castlevania's high-contrast wallpaper makes ordinary grayscale OCR turn
    the clearly visible ``PLAYSTATION PORTABLE`` label into glyph noise.  The
    label itself uses the frozen PSP-blue accent, so isolate only strongly
    blue pixels in the same bounded platform-label strip.  This proves the
    platform without trusting the selected game's title or any ROM path.
    """
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        return ""
    image = Image.open(path).convert("RGB")
    sx, sy = image.width / 1920.0, image.height / 1080.0
    box = (35, 120, 800, 180)
    crop = image.crop((round(box[0] * sx), round(box[1] * sy),
                       round(box[2] * sx), round(box[3] * sy)))
    mask = Image.new("L", crop.size)
    mask.putdata([
        0 if blue >= 130 and blue >= red * 1.25 and blue >= green * 1.15
        else 255
        for red, green, blue in crop.getdata()
    ])
    mask = mask.resize((mask.width * 3, mask.height * 3))
    with io.BytesIO() as buffer:
        mask.save(buffer, format="PNG")
        completed = subprocess.run(
            [str(tesseract), "stdin", "stdout", "--psm", "7"],
            input=buffer.getvalue(), check=False, capture_output=True,
        )
    return completed.stdout.decode("utf-8", errors="replace")


def accent_system_label_ocr(path: Path) -> str:
    """Read the platform label in whatever accent colour the theme chose.

    The wallpaper-accent mode colours the platform label per game (Donkey
    Kong Country Returns 3D: purple over a jungle wallpaper, run n3ds-b32,
    2026-09-01), so the frozen red/blue masks above cannot apply.  The label
    is the most saturated colour family in the bounded label strip: take the
    modal saturated hue there, keep only pixels within a narrow hue distance
    of it, and OCR that mask.  Busy artwork rarely shares one saturated hue
    across the whole strip, and a wrong guess only yields glyph noise that
    resolves to no folder.
    """
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        return ""
    image = Image.open(path).convert("RGB")
    sx, sy = image.width / 1920.0, image.height / 1080.0
    box = (35, 120, 800, 180)
    crop = image.crop((round(box[0] * sx), round(box[1] * sy),
                       round(box[2] * sx), round(box[3] * sy)))
    hsv = crop.convert("HSV")
    pixels = list(hsv.getdata())
    histogram = [0] * 36
    for hue, saturation, value in pixels:
        if saturation >= 120 and value >= 110:
            histogram[(hue * 36) // 256] += 1
    modal_bin = max(range(36), key=lambda index: histogram[index])
    if histogram[modal_bin] < 200:
        return ""
    modal_hue = (modal_bin * 256) // 36 + 256 // 72
    mask = Image.new("L", crop.size)
    mask.putdata([
        0 if saturation >= 100 and value >= 100 and
        min(abs(hue - modal_hue), 256 - abs(hue - modal_hue)) <= 14
        else 255
        for hue, saturation, value in pixels
    ])
    mask = mask.resize((mask.width * 3, mask.height * 3))
    with io.BytesIO() as buffer:
        mask.save(buffer, format="PNG")
        completed = subprocess.run(
            [str(tesseract), "stdin", "stdout", "--psm", "7"],
            input=buffer.getvalue(), check=False, capture_output=True,
        )
    return completed.stdout.decode("utf-8", errors="replace")


def expected_system_label_ocr(path: Path, expected_folder: str) -> str:
    """Return only a bounded, platform-specific label proof when available."""
    if expected_folder == "nes":
        return nes_system_label_ocr(path)
    if expected_folder == "psp":
        return psp_system_label_ocr(path)
    return accent_system_label_ocr(path)


def switch_nvdec_lifecycle(log: str) -> dict[str, object]:
    """Summarize Eden's title-video lifecycle without guessing from time.

    Runtime acceptance clears logcat immediately before each physical launch,
    so a close without a corresponding open is malformed evidence.  Once any
    stream opens, *all* observed streams must close before title navigation or
    proof can proceed.
    """
    opened = log.count(SWITCH_NVDEC_OPEN)
    closed = log.count(SWITCH_NVDEC_CLOSE)
    return {
        "opened": opened,
        "closed": closed,
        "valid": closed <= opened,
        "complete": opened > 0 and closed == opened,
        "active": max(0, opened - closed),
    }


def classify_switch_screen(text: str) -> str:
    """Classify only OCR states for which a safe physical action is known.

    Unknown screens deliberately remain unknown.  The harness must never turn
    an unrecognized logo, cinematic, loading screen, or menu into permission
    for another blind A press.
    """
    value = " ".join(text.upper().split())
    if SWITCH_SETTINGS_TEXT.search(value):
        return "settings"
    if SWITCH_TITLE_PROMPT_TEXT.search(value):
        return "title-prompt"
    if SWITCH_SAVE_MENU_TEXT.search(value):
        return "save-menu"
    if SWITCH_CHOICE_MENU_TEXT.search(value):
        return "choice-menu"
    if SWITCH_CONFIRM_MENU_TEXT.search(value):
        return "confirm-menu"
    if SWITCH_PLAY_MENU_TEXT.search(value):
        return "play-menu"
    # Stylized play-entry fonts can defeat OCR entirely (Blasphemous'
    # gothic "Pilgrimage" read as glyph noise on the Thor, 2026-08-16)
    # while the plain-font OPTIONS and CREDITS rows read cleanly. Their
    # co-occurrence identifies a main menu whose default selection is the
    # play entry; an Options or Credits SUBSCREEN never shows both.
    if re.search(r"\bOPTIONS\b", value) and re.search(r"\bCREDITS\b", value):
        return "play-menu"
    return "unknown"


def switch_screen_has_menu(text: str) -> bool:
    return SWITCH_MENU_GUARD_TEXT.search(" ".join(text.upper().split())) is not None


def write_switch_navigation_trace(path: Path,
                                  trace: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({
        "schemaVersion": 1,
        "policy": "nvdec-closed-recognized-ui-no-blind-accept",
        "events": trace,
    }, indent=2) + "\n", encoding="utf-8")


def capture_switch_navigation_state(
        adb: Path, serial: str, output: Path, prefix: str,
        trace: list[dict[str, object]]) -> tuple[Path, str, str]:
    path = output / f"{prefix}-switch-navigation-{len(trace) + 1:02d}.png"
    metrics = screenshot(adb, serial, path)
    text = ocr(path)
    kind = classify_switch_screen(text)
    lifecycle = switch_nvdec_lifecycle(qa.logs(adb, serial))
    trace.append({
        "event": "screen",
        "monotonicMs": time.monotonic_ns() // 1_000_000,
        "path": str(path),
        "ocr": " ".join(text.split()),
        "kind": kind,
        "visible": metrics["visible"],
        "nvdec": lifecycle,
    })
    return path, text, kind


def wait_switch_title_ready(
        adb: Path, serial: str, output: Path, prefix: str,
        trace: list[dict[str, object]], timeout: float = 150.0,
        nvdec_discovery_seconds: float = 30.0) -> tuple[Path, str, str]:
    """Wait for a recognized title UI after title-video decoding has ended.

    75 s intermittently expired inside the publisher-logo loop on slow Eden
    boots (runs switch6/22, 2026-08-16); the recognized-twice conditions are
    unchanged — only the wall-clock allowance grew.

    The exact 03cd44 evidence has two NVDEC opens followed by two closes.  Its
    old bright-pixel readiness gate returned on the earlier Game Kitchen logo.
    This gate waits long enough to discover that lifecycle, then requires all
    streams to close and the same actionable OCR state to be seen twice.  A
    Switch title with no NVDEC use can qualify only after the discovery window;
    it still needs the same stable recognized UI.
    """
    started = time.monotonic()
    deadline = started + timeout
    stable_kind = ""
    stable_count = 0
    latest: tuple[Path, str, str] | None = None
    while time.monotonic() < deadline:
        log = qa.logs(adb, serial)
        lifecycle = switch_nvdec_lifecycle(log)
        if not lifecycle["valid"]:
            raise RuntimeError(f"Switch NVDEC lifecycle is malformed: {lifecycle}")
        latest = capture_switch_navigation_state(
            adb, serial, output, prefix, trace
        )
        _path, _text, kind = latest
        recognized = kind != "unknown"
        elapsed = time.monotonic() - started
        # A LOOPING title-background video (Metroid Dread) legitimately keeps
        # NVDEC streams open on the title screen forever, so all-closed can
        # never be required unconditionally (run switch24: opened=4 active=2
        # at a fully interactive title). After the discovery window, a
        # recognized actionable OCR state seen twice is the guard that the
        # old bright-pixel gate lacked — a mid-video logo never classifies.
        decoder_ready = bool(lifecycle["complete"]) or (
            elapsed >= nvdec_discovery_seconds
        )
        if recognized and decoder_ready:
            stable_count = stable_count + 1 if stable_kind == kind else 1
            stable_kind = kind
            if stable_count >= 2:
                return latest
        else:
            stable_kind = ""
            stable_count = 0
        time.sleep(0.55)
    lifecycle = switch_nvdec_lifecycle(qa.logs(adb, serial))
    raise RuntimeError(
        "Switch title never reached a stable recognized UI after NVDEC close; "
        f"nvdec={lifecycle} last={latest[2] if latest else 'none'}"
    )


def prove_switch_gameplay_motion(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str, trace: list[dict[str, object]],
        timeout: float = 300.0) -> dict[str, object]:
    """Require visible, non-menu motion after an explicit Play selection.

    35 s was too tight for titles whose slot selection opens a long static
    load screen (Blasphemous holds a poetry quote card for tens of seconds
    before gameplay — physically hit on the Thor, 2026-08-16), and 120 s
    was too tight for a NEW-GAME intro cinematic whose slow narrated pans
    sit just under the strong-transition bar for minutes before the first
    controllable scene (physically hit after the save-slot hold-A fix,
    run switch4: deltas 1637-1841 against the 3000 floor). The gate's
    conditions are unchanged; only the wall-clock allowance grew.

    This is a readiness gate, not the frame-generation proof itself.  The
    subsequent v7 verifier still has to prove source-correlated novel pixels
    and actual SurfaceFlinger cadence.  Here we ensure qualification is not
    armed over a title/settings page and wait through any second NVDEC movie
    opened by the selected save slot.
    """
    deadline = time.monotonic() + timeout
    frames: list[Path] = []
    deltas: list[int] = []
    menu_guard_hits = 0
    directions = ("left", "right", "left", "right", "left", "right")
    while time.monotonic() < deadline:
        lifecycle = switch_nvdec_lifecycle(qa.logs(adb, serial))
        if not lifecycle["valid"]:
            raise RuntimeError(f"Switch NVDEC lifecycle is malformed: {lifecycle}")
        if int(lifecycle["active"]) > 0:
            # A silent park on active NVDEC sampled NOTHING for the whole
            # window while Metroid Dread's post-file story movie played
            # (run switch29, changedPixels=[]). Movies must not satisfy the
            # motion acceptance, so they still do not produce samples — but
            # menu-safe B presses attempt the skip so a long movie cannot
            # consume the entire allowance, and the wall clock keeps
            # draining toward the movie's natural end otherwise.
            controller.key(controller.B,
                           "physical-switch-b-skip-movie", hold=0.05)
            time.sleep(1.0)
            continue
        path, text, kind = capture_switch_navigation_state(
            adb, serial, output, prefix, trace
        )
        if kind != "unknown" or switch_screen_has_menu(text):
            # A transient TUTORIAL overlay ("Bile Flasks … [B] Back") also
            # matches the menu vocabulary; it is dismissed by the same
            # menu-safe B this gate already presses (run switch18). Only a
            # PERSISTENT menu — five consecutive guard hits despite B — is
            # the armed-over-a-menu failure this guard exists for.
            menu_guard_hits += 1
            if kind != "unknown" or menu_guard_hits >= 5:
                raise RuntimeError(
                    "Switch gameplay readiness remained in a menu; "
                    f"kind={kind} OCR={' '.join(text.split())!r}"
                )
            controller.key(controller.B,
                           "physical-switch-b-dismiss-tutorial", hold=0.05)
            time.sleep(0.80)
            continue
        menu_guard_hits = 0
        if frames:
            deltas.append(changed_pixels(frames[-1], path, threshold=12))
        frames.append(path)
        # CONSECUTIVE strong samples separate continuous gameplay motion
        # from a narration card flip: Blasphemous II's new-game intro
        # produced isolated 57 k-pixel card transitions between long
        # near-static holds, which satisfied the old any-three-strong count
        # and armed proof over the narration (runs switch5-11, 2026-08-16).
        strong = [value for value in deltas if value >= 3_000]
        tail = deltas[-3:]
        # Two acceptance shapes, both impossible for narration cards (isolated
        # ~57k flips between near-zero holds) and static menus (<50):
        # three consecutive STRONG samples (large-sprite traversal), or twelve
        # consecutive MODERATE samples — Blasphemous II's post-tutorial scene
        # animates ~880 changing pixels every sample without pause (run
        # switch19); the dense content gates stay the strict arbiter of what
        # that scene is actually worth.
        # 300 keeps a 6x margin over static menus/cards (<50 between flips)
        # while admitting the dimmest observed continuous animation (run
        # switch21 held 405-442 for 24 straight samples under a 500 floor).
        moderate_tail = deltas[-12:]
        if (len(tail) == 3 and all(value >= 3_000 for value in tail)) or (
                len(moderate_tail) == 12 and
                all(value >= 300 for value in moderate_tail)):
            result = {
                "passed": True,
                "frames": [str(item) for item in frames],
                "changedPixels": deltas,
                "strongTransitions": len(strong),
                "input": "left-stick-and-south-b",
            }
            trace.append({"event": "gameplay-motion-ready", **result})
            return result
        # A 0.32 s nudge produced only idle-animation deltas (~100-200
        # pixels) in the bounded altar room (run switch12); a full walking
        # step pans the camera and moves the whole sprite, which is what
        # the three-consecutive-strong requirement above measures.
        controller.motion_left(
            directions[(len(frames) - 1) % len(directions)], hold=1.2
        )
        # Raw south resolves to Switch B (menu-safe: only ever BACK). Press
        # it ONLY after a weak sample: an unconditional per-sample press
        # advanced a narration card between every capture and manufactured
        # the exact three-consecutive-strong pattern this gate requires
        # (run switch13). Card-driven progress now alternates strong/weak
        # and can never satisfy the gate; only self-sustained walking can.
        if not deltas or deltas[-1] < 3_000:
            for press in range(2):
                controller.key(
                    controller.B,
                    "physical-switch-b-advance-readiness", hold=0.05)
                time.sleep(0.30)
            # Blasphemous II parks the Penitent One kneeling at the opening
            # altar behind a HOLD-L interaction prompt that neither stick
            # motion nor B can break (run switch17). A held L is parry in
            # gameplay and a tab switch in menus — both harmless.
            controller.key(controller.L1,
                           "physical-switch-l-hold-interact", hold=1.2)
        time.sleep(0.18)
    raise RuntimeError(
        "Switch did not show sustained non-menu motion after the explicit "
        f"Play selection; changedPixels={deltas}"
    )


def wait_switch_recognized_after_action(
        adb: Path, serial: str, output: Path, prefix: str,
        trace: list[dict[str, object]], timeout: float = 30.0
) -> tuple[Path, str, str]:
    """Wait through a bounded, input-free transition between known menus.

    Eden can legitimately show publisher/copyright frames for several seconds
    after accepting the title prompt.  Those frames are not authority to press
    another button.  Require the next recognized state to be observed twice,
    without injecting any input, or fail closed when the transition times out.
    """
    deadline = time.monotonic() + timeout
    stable_kind = ""
    stable_count = 0
    latest: tuple[Path, str, str] | None = None
    while time.monotonic() < deadline:
        lifecycle = switch_nvdec_lifecycle(qa.logs(adb, serial))
        if not lifecycle["valid"]:
            raise RuntimeError(f"Switch NVDEC lifecycle is malformed: {lifecycle}")
        latest = capture_switch_navigation_state(
            adb, serial, output, prefix, trace
        )
        kind = latest[2]
        if kind != "unknown":
            stable_count = stable_count + 1 if stable_kind == kind else 1
            stable_kind = kind
            if stable_count >= 2:
                trace.append({
                    "event": "recognized-after-action",
                    "kind": kind,
                    "inputSentWhileWaiting": False,
                })
                return latest
        else:
            stable_kind = ""
            stable_count = 0
        time.sleep(0.45)
    raise RuntimeError(
        "Switch remained on an unknown transition screen after a recognized "
        "action; no blind input was sent; "
        f"last={latest[2] if latest else 'none'}"
    )


def navigate_switch_to_gameplay(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str) -> dict[str, object]:
    """Reach Switch gameplay by recognized states, never generic A spam."""
    trace_path = output / f"{prefix}-switch-navigation.json"
    trace: list[dict[str, object]] = []
    play_selections = 0

    def record_action(action: str, kind: str) -> None:
        trace.append({
            "event": "input",
            "action": action,
            "fromKind": kind,
            "monotonicMs": time.monotonic_ns() // 1_000_000,
        })
        write_switch_navigation_trace(trace_path, trace)

    try:
        _path, _text, kind = wait_switch_title_ready(
            adb, serial, output, prefix, trace
        )
        for step in range(10):
            if kind == "settings":
                record_action("B", kind)
                controller.key(
                    controller.B, f"physical-switch-back-settings-{step + 1}",
                    hold=0.055,
                )
            elif kind == "title-prompt":
                record_action("A", kind)
                controller.key(
                    controller.A, f"physical-switch-accept-title-{step + 1}",
                    hold=0.055,
                )
            elif kind == "confirm-menu":
                for column in range(4):
                    record_action("HAT-LEFT", kind)
                    controller.hat(
                        "left",
                        f"physical-switch-confirm-first-{step + 1}-{column + 1}",
                    )
                record_action("A", kind)
                controller.key(
                    controller.A, f"physical-switch-confirm-play-{step + 1}",
                    hold=0.055,
                )
                play_selections += 1
            elif kind in {"play-menu", "save-menu", "choice-menu"}:
                # Saturating Up is deterministic even when a prior run left a
                # different row selected; A is sent only after OCR proves this
                # is a playable/save/difficulty menu rather than Options.
                # The d-pad must be the physical HAT axis: EV_KEY dpad codes
                # never reach a native-adapter game on the Thor (run switch3
                # pressed UP x6 with zero effect, 2026-08-16).
                for row in range(6):
                    record_action("HAT-UP", kind)
                    controller.hat(
                        "up",
                        f"physical-switch-first-choice-{step + 1}-{row + 1}",
                    )
                record_action("A", kind)
                # Blasphemous confirms a save slot with HOLD-to-confirm (a
                # fill ring); the 55 ms tap left run switch3 parked on the
                # recognized slot screen through the whole state budget. A
                # long hold still registers exactly once on tap-confirm
                # menus.
                controller.key(
                    controller.A, f"physical-switch-select-play-{step + 1}",
                    hold=1.6 if kind == "save-menu" else 0.055,
                )
                play_selections += 1
            else:
                if play_selections == 0:
                    raise RuntimeError(
                        "Switch navigation reached an unknown screen before an "
                        "OCR-proven Play selection; refusing blind input"
                    )
                motion = prove_switch_gameplay_motion(
                    adb, serial, controller, output, prefix, trace
                )
                write_switch_navigation_trace(trace_path, trace)
                return {
                    "passed": True,
                    "playSelections": play_selections,
                    "trace": str(trace_path),
                    "motion": motion,
                }

            # Give an accepted control time to change state, but keep all
            # subsequent actions conditional on the newly captured OCR.
            time.sleep(0.80)
            _path, _text, kind = capture_switch_navigation_state(
                adb, serial, output, prefix, trace
            )
            if kind == "unknown" and play_selections == 0:
                _path, _text, kind = wait_switch_recognized_after_action(
                    adb, serial, output, prefix, trace
                )
            if kind == "unknown" and play_selections:
                motion = prove_switch_gameplay_motion(
                    adb, serial, controller, output, prefix, trace
                )
                write_switch_navigation_trace(trace_path, trace)
                return {
                    "passed": True,
                    "playSelections": play_selections,
                    "trace": str(trace_path),
                    "motion": motion,
                }
        raise RuntimeError("Switch navigation exceeded ten recognized states")
    finally:
        write_switch_navigation_trace(trace_path, trace)


def selected_title_matches(expected: str, observed: str) -> bool:
    expected_normalized = normalize(expected)
    observed_normalized = normalize(observed)
    if expected_normalized and expected_normalized in observed_normalized:
        return True
    # The frozen header can crop the first/last glyph of a long title. Match
    # alphabetic words by a four-character prefix, but preserve a trailing
    # numeric sequel discriminator (Galaxy 2 must never pass as Galaxy).
    words = [normalize(word) for word in re.findall(r"[A-Za-z0-9]+", expected)
             if len(normalize(word)) >= 3 or normalize(word).isdigit()]
    if not words:
        return False
    # A short trailing number is normally a sequel discriminator (Galaxy 2,
    # Tekken 5) and must remain exact. Four-digit numbers also occur as years
    # in long canonical titles; the fixed-width header may crop only that year
    # after already proving the distinctive words, as on Capcom vs. SNK 2:
    # Mark of the Millennium 2001. Do not turn that harmless edge crop into a
    # foreign-title claim.
    observed_tokens = {
        normalize(token) for token in re.findall(r"[A-Za-z0-9]+", observed)
    }
    if any(word.isdigit() and len(word) <= 2 and word not in observed_tokens
           for word in words):
        return False
    alphabetic = [word for word in words if not word.isdigit()]

    def word_present(word: str) -> bool:
        prefix = word[:min(4, len(word))]
        if prefix in observed_normalized:
            return True
        # One-substitution tolerance on the prefix: OCR of a header over an
        # animated preview confuses single glyphs (physically hit: WORLD
        # read as HORLD, run 2026-08-17-wiiu4). Insertions/deletions stay
        # unmatched so this cannot make short words promiscuous.
        if len(prefix) < 4:
            return False
        for token in observed_tokens:
            if len(token) < 4:
                continue
            candidate = token[:4]
            differences = sum(1 for a, b in zip(prefix, candidate) if a != b)
            if differences <= 1:
                return True
        return False

    matched = sum(word_present(word) for word in alphabetic)
    if len(alphabetic) == 1:
        # Titles whose only substantial word survives filtering ("F-Zero X"
        # keeps just "zero"; the single-glyph F and X are OCR chaff over an
        # animated preview — run n64-6 returned to the correct game and
        # still failed here). One distinctive word present is the whole
        # obtainable signal for such titles.
        return matched == 1
    return bool(alphabetic) and matched >= max(2, (len(alphabetic) * 2 + 2) // 3)


def selected_header_ocr(path: Path) -> str:
    """Read the selected-title header without letting wallpaper defeat OCR."""
    boxes = (
        (45, 120, 1810, 315),  # long/two-line title
        (45, 130, 900, 260),   # normal title, less wallpaper
        (45, 165, 650, 245),   # short/numeric title only
    )
    # Multiple psm modes for the same reliability reason as ocr(): a busy
    # frame (animated preview under the header) reads differently per mode,
    # and one clean read among them is enough for the fuzzy title match.
    values = [" ".join(ocr_region(path, box, psm).split())
              for box in boxes for psm in (6, 7, 11)]
    return " | ".join(value for value in values if value)


def resolve_list_folder(observed: str,
                        display_names: dict[str, str]) -> Optional[str]:
    """Resolve an OCR'd List view header to a catalog folder.

    Returns the folder whose normalized display name is the *longest* one
    contained in the observed header text, so shorter families never shadow a
    longer one (e.g. "GAME BOY" -> gb must not swallow "GAME BOY ADVANCE" ->
    gba). Returns None when nothing resolves, which the caller treats as an
    unreadable frame rather than a match.
    """
    normalized = normalize(observed)
    if not normalized:
        return None
    best: Optional[str] = None
    best_len = 0
    for folder, name in display_names.items():
        if name and name in normalized and len(name) > best_len:
            best = folder
            best_len = len(name)
    return best


def list_view_highlighted_folder(path: Path,
                                 display_names: dict[str, str]) -> Optional[str]:
    """OCR the List view header and map it back to a canonical catalog folder."""
    return resolve_list_folder(selected_header_ocr(path), display_names)


class AlphaNavigationDrift(RuntimeError):
    """The physical game-list cursor no longer matches its proven origin."""


def game_list_identity(path: Path,
                       display_names: dict[str, str],
                       require_counter: bool = True) -> dict[str, object]:
    """Recompute the open System View identity from stable on-screen regions.

    The system label and ``current / total`` counter are deliberately read
    separately from the title/wallpaper.  In r16, hundreds of individually
    paced Down presses crossed the idle/screensaver boundary: the next press
    woke into a persisted All Systems/SNES list and the old numeric cursor was
    blindly reused.  These fields make that state change observable before any
    further relative navigation is trusted.
    """
    system_text = " ".join(
        " ".join(ocr_region(path, (35, 125, 1000, 180), psm).split())
        for psm in (6, 7, 11)
    )
    # Busy r19 artwork defeated the narrow red platform-label crop while the
    # wider selected-title header still independently read the exact platform.
    # Combine both stable OCR routes; All Systems remains an explicit reject.
    wider_header = selected_header_ocr(path)
    system_evidence = system_text + " | " + wider_header
    normalized_system = normalize(system_evidence)
    aggregate = "allsystems" in normalized_system
    folder = "all" if aggregate else resolve_list_folder(
        system_evidence, display_names
    )
    counter_text = ""
    current: Optional[int] = None
    total: Optional[int] = None
    if require_counter:
        counter_text = " ".join(
            " ".join(ocr_region(path, (45, 270, 350, 315), psm).split())
            for psm in (6, 7, 11)
        )
        counters = {
            (int(observed_current), int(observed_total))
            for observed_current, observed_total in re.findall(
                r"\b(\d+)\s*/\s*(\d+)\b", counter_text
            )
        }
        if len(counters) != 1:
            raise AlphaNavigationDrift(
                "cannot prove one System View current/total counter: " +
                repr(counter_text)
            )
        current, total = next(iter(counters))
        if current < 1 or total < 1 or current > total:
            raise AlphaNavigationDrift(
                f"invalid System View current/total counter: {current}/{total}"
            )
    return {
        "folder": folder,
        "aggregate": aggregate,
        "current": current,
        "total": total,
        "systemOcr": system_evidence,
        "counterOcr": counter_text,
    }


def assert_game_list_checkpoint(path: Path, expected_folder: str,
                                expected_current: int,
                                expected_total: Optional[int],
                                display_names: dict[str, str],
                                expected_title: Optional[str] = None,
                                require_counter: bool = True,
                                require_list_layout: bool = True,
                                require_system_identity: bool = True) -> int:
    identity = game_list_identity(
        path, display_names, require_counter=require_counter
    )
    accent_system_ocr = ""
    system_matches = identity["folder"] == expected_folder
    if not identity["aggregate"] and not system_matches:
        accent_system_ocr = expected_system_label_ocr(path, expected_folder)
        system_matches = (resolve_list_folder(
            accent_system_ocr, display_names
        ) == expected_folder)
    if require_system_identity and (identity["aggregate"] or not system_matches):
        raise AlphaNavigationDrift(
            f"System View drifted from {expected_folder!r}: "
            f"folder={identity['folder']!r} OCR={identity['systemOcr']!r} "
            f"accentOCR={accent_system_ocr!r}"
        )
    if require_list_layout and current_game_view(path) != "list":
        raise AlphaNavigationDrift("System View left the proven List layout")
    if expected_title is not None:
        observed_title = selected_header_ocr(path)
        if not selected_title_matches(expected_title, observed_title):
            raise AlphaNavigationDrift(
                "System View cursor did not select the immutable Alpha title: "
                f"expected={expected_title!r} OCR={observed_title!r}"
            )
    if require_counter:
        if identity["current"] != expected_current:
            raise AlphaNavigationDrift(
                "System View cursor did not follow the exact physical page plan: "
                f"expected={expected_current} observed={identity['current']}"
            )
        observed_total = int(identity["total"])
        if expected_total is not None and observed_total != expected_total:
            raise AlphaNavigationDrift(
                "System View Alpha count changed during physical traversal: "
                f"expected={expected_total} observed={observed_total}"
            )
        return observed_total
    if expected_total is None:
        raise ValueError("later Alpha checkpoints require the row-zero total")
    return expected_total


def resolve_alpha_header_position(observed: str, keys: list[str]) -> int:
    """Resolve one selected-title header to exactly one immutable Alpha row."""
    matches = [index for index, key in enumerate(keys)
               if selected_title_matches(title_from_key(key), observed)]
    if len(matches) > 1:
        # The fuzzy word-prefix matcher can admit two titles that share their
        # distinctive words (run nds-b32, 2026-09-01: the header OCR proved
        # "Castlevania: Dawn of Sorrow" verbatim, yet a sibling Castlevania row
        # also matched by prefix).  An exact normalized-title containment is
        # stronger evidence than any prefix match: when exactly one candidate
        # is contained verbatim, it wins.
        observed_normalized = normalize(observed)
        exact = [index for index in matches
                 if normalize(title_from_key(keys[index])) and
                 normalize(title_from_key(keys[index])) in observed_normalized]
        if len(exact) == 1:
            matches = exact
        elif len(exact) > 1:
            # A very short title is contained by accident: "Ys" sits inside
            # the header's own "SYSTEM" (run e2-nes, 2026-09-04, where the
            # verbatim "10-Yard Fight" lost to it). Among verbatim
            # containments the strictly longest title is the most specific
            # evidence; equal-length duplicates stay ambiguous so a genuine
            # duplicate row still requires the counter.
            lengths = {index: len(normalize(title_from_key(keys[index])))
                       for index in exact}
            longest = max(lengths.values())
            best = [index for index in exact if lengths[index] == longest]
            others = [index for index in exact if index not in best]
            # Only a candidate too short to be trusted on its own (fewer
            # than four characters) yields; "Beta" against "Beta Special"
            # stays ambiguous.
            if len(best) == 1 and longest >= 6 and \
                    all(lengths[index] < 4 for index in others):
                matches = best
    if len(matches) != 1:
        raise AlphaNavigationDrift(
            "selected System View title does not resolve uniquely in the "
            f"immutable Alpha index: matches={matches[:8]} OCR={observed!r}"
        )
    return matches[0]


def assert_cover_system(path: Path, expected_folder: str,
                        display_names: dict[str, str]) -> None:
    observed = " ".join(
        " ".join(ocr_region(path, (35, 135, 1120, 255), psm).split())
        for psm in (6, 7, 11)
    )
    if ("allsystems" in normalize(observed) or
            resolve_list_folder(observed, display_names) != expected_folder):
        raise AlphaNavigationDrift(
            f"deterministic Cover origin did not prove {expected_folder!r}: "
            f"OCR={observed!r}"
        )


def sort_tab_scores(path: Path) -> list[float]:
    """Score the four exact frozen sort buttons by their non-text interiors."""
    image = Image.open(path).convert("RGB")
    sx, sy = image.width / 1920.0, image.height / 1080.0
    scores = []
    for index in range(4):
        left = 48 + index * 150
        # Sample above and below the label. The selected button has an opaque
        # accent fill; unselected buttons remain the same nearly-black glass.
        regions = ((left + 8, 355, left + 134, 365),
                   (left + 8, 383, left + 134, 391))
        pixels = []
        for x1, y1, x2, y2 in regions:
            crop = image.crop((round(x1 * sx), round(y1 * sy),
                               round(x2 * sx), round(y2 * sy)))
            pixels.extend(crop.getdata())
        count = max(1, len(pixels))
        mean = tuple(sum(pixel[channel] for pixel in pixels) / count
                     for channel in range(3))
        luminance = 0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]
        chroma = max(mean) - min(mean)
        scores.append(luminance + chroma * 0.65)
    return scores


def active_sort_index(path: Path) -> int:
    scores = sort_tab_scores(path)
    ranked = sorted(range(4), key=lambda index: scores[index], reverse=True)
    if scores[ranked[0]] - scores[ranked[1]] < 8.0:
        raise RuntimeError(f"cannot identify active sort button: {scores}")
    return ranked[0]


def current_game_view(path: Path) -> Optional[str]:
    """Read the frozen System View layout label without wallpaper noise.

    The old wide footer crop included almost half of the animated wallpaper.
    On the Thor that made Tesseract miss a perfectly visible ``Y VIEW: LIST``
    label, after which QA toggled the already-correct List layout into Covers.
    Keep this crop tightly bounded around the stable Y instruction and combine
    two segmentation modes.  Unknown remains fail-closed.
    """
    box = (950, 995, 1400, 1070)
    observed = " ".join(
        " ".join(ocr_region(path, box, psm).split()).upper()
        for psm in (7, 11)
    )
    if re.search(r"VIEW\s*:\s*LIST", observed):
        return "list"
    if re.search(r"VIEW\s*:\s*COVERS", observed):
        return "covers"
    # Nintendo's busy artwork can make the low-contrast footer unreadable.
    # The vertical List layout still has a stable selected-row contract: one
    # wide, comparatively uniform accent rectangle followed by a darker row.
    # Require both low variance and strong separation from the next row; a
    # merely flat wallpaper therefore cannot be mistaken for List.
    image = Image.open(path).convert("RGB")
    sx, sy = image.width / 1920.0, image.height / 1080.0
    def scaled(box: tuple[int, int, int, int]):
        return tuple(round(value * (sx if index % 2 == 0 else sy))
                     for index, value in enumerate(box))
    selected = ImageStat.Stat(image.crop(scaled((690, 320, 1870, 395))))
    following = ImageStat.Stat(image.crop(scaled((690, 410, 1870, 480))))
    selected_variance = sum(selected.stddev) / 3.0
    row_separation = sum(abs(a - b)
                         for a, b in zip(selected.mean, following.mean))
    if selected_variance < 38.0 and row_separation > 80.0:
        return "list"
    return None


def force_alpha_list(adb: Path, serial: str, controller: PhysicalController,
                     output: Path, prefix: str, expected_folder: str,
                     display_names: dict[str, str],
                     keys: list[str]) -> tuple[Path, int]:
    """Force Alpha/List and return its physically proven remembered row.

    Pegasus persists the last selected row independently for each sort.  Merely
    cycling back to A-Z therefore does *not* establish row one (physical N64
    r4 restored row 282).  Bind the visible counter and selected title to the
    immutable live Alpha index and let the caller navigate from that exact
    position instead of inventing an origin.
    """
    frame = output / f"{prefix}-sort-probe-00.png"
    screenshot(adb, serial, frame)
    active = active_sort_index(frame)
    # Always cycle at least once so the active Alpha identity is independently
    # re-established rather than inherited from an earlier screenshot.
    # A Thor screencap can briefly return the previously latched UI frame after
    # the QML sort mode has changed.  Issuing another R1 from that stale image
    # skips the state we meant to prove (physical r10 visibly skipped Alpha this
    # way).  Drive one transition at a time and wait until its exact successor
    # is visible before another physical input is allowed.
    for transition in range(5):
        previous = active
        expected = (previous + 1) % 4
        controller.key(controller.R1, "physical-r1-next-sort", hold=0.04)
        frame = output / f"{prefix}-sort-probe-{transition + 1:02d}.png"
        deadline = time.monotonic() + 4.0
        while True:
            time.sleep(0.12)
            screenshot(adb, serial, frame)
            observed = active_sort_index(frame)
            if observed == expected:
                active = observed
                break
            if observed != previous:
                raise RuntimeError(
                    "physical R1 sort transition jumped "
                    f"from {previous} to {observed}, expected {expected}"
                )
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "physical R1 sort transition did not settle "
                    f"from {previous} to {expected}"
                )
        if active == 2:
            break
    else:
        raise RuntimeError("physical R1 could not select Alpha sort")

    # The footer names the current game layout.  The Cover layout is a
    # horizontal carousel where Up/Down are not row navigation, so accepting
    # ``VIEW: COVERS`` here makes an index-based QA move land on an unrelated
    # title.  Force the vertical List layout before using Up/Down.
    view = current_game_view(frame)
    if view != "list":
        controller.key(controller.Y, "physical-y-toggle-game-view", hold=0.05)
        frame = output / f"{prefix}-list-view.png"
        screenshot(adb, serial, frame)
        view = current_game_view(frame)
    if view != "list":
        raise RuntimeError(f"physical Y could not prove List game view: {view}")
    # Let the artwork-led title header converge, then prove Alpha + List and
    # the exact persisted position before relative navigation starts.
    time.sleep(0.50)
    frame = output / f"{prefix}-alpha-origin-settled.png"
    screenshot(adb, serial, frame)
    if active_sort_index(frame) != 2 or current_game_view(frame) != "list":
        raise RuntimeError("Alpha/List origin changed before navigation")
    identity = game_list_identity(frame, display_names, require_counter=False)
    system_matches = identity["folder"] == expected_folder
    accent_system_ocr = ""
    if not identity["aggregate"] and not system_matches:
        accent_system_ocr = expected_system_label_ocr(frame, expected_folder)
        system_matches = (resolve_list_folder(
            accent_system_ocr, display_names
        ) == expected_folder)
    if identity["aggregate"] or not system_matches:
        raise AlphaNavigationDrift(
            "Alpha/List position belongs to the wrong system: "
            f"expected={expected_folder!r} observed={identity['folder']!r} "
            f"accentOCR={accent_system_ocr!r}"
        )
    observed_title = selected_header_ocr(frame)
    # The library can contain two distinct ROM rows with the same display
    # title (physical N64 r6: WCW Nitro at rows 284 and 286).  The exact visible
    # counter is therefore the authoritative position; title OCR proves that
    # this counter points at the corresponding immutable row without requiring
    # display-name uniqueness.  Some artwork makes that translucent counter
    # unreadable (physical r12), while the large selected title remains exact.
    # In that case accept only a title that resolves to exactly one live Alpha
    # row; duplicate names still require the counter and therefore fail closed.
    if identity["current"] is not None and identity["total"] is not None:
        if identity["total"] != len(keys):
            raise AlphaNavigationDrift(
                "Alpha/List total differs from the immutable live index: "
                f"observed={identity['total']} expected={len(keys)}"
            )
        observed_position = int(identity["current"]) - 1
    else:
        observed_position = resolve_alpha_header_position(observed_title, keys)
    expected_title = title_from_key(keys[observed_position])
    if not selected_title_matches(expected_title, observed_title):
        raise AlphaNavigationDrift(
            "Alpha/List counter does not name its immutable title: "
            f"counter={identity['current']} expected={expected_title!r} "
            f"OCR={observed_title!r}"
        )
    return frame, observed_position


def alpha_keys(index: dict, case: SystemCase) -> list[str]:
    systems = index.get("systems") or {}
    for candidate in (case.folder,) + case.aliases:
        modes = systems.get(candidate)
        if isinstance(modes, dict) and isinstance(modes.get("alpha"), list):
            return [str(value) for value in modes["alpha"]]
    return []


def title_position(keys: list[str], title: str) -> int:
    target = normalize(title)
    exact = [index for index, key in enumerate(keys)
             if normalize(key.split("|", 1)[-1]) == target]
    if len(exact) != 1:
        raise RuntimeError(
            f"required title has {len(exact)} exact Alpha-index matches: {title}"
        )
    return exact[0]


def title_from_key(key: str) -> str:
    return key.split("|", 1)[-1].strip()


def metadata_title_files(adb: Path, serial: str,
                         case: SystemCase) -> dict[str, set[str]]:
    """Union all exact-system metadata roots and retain every ROM path/title.

    ImportManager writes its generated row to ``metafiles`` while the owner's
    established library can remain in the sibling ``metadata`` directory. r17
    stopped after seeing the generated fixture file, thereby hiding every real
    NES ROM. Root precedence is valid for the *same canonical title/path*, but
    it must never discard distinct owner titles. Canonical path aliases are
    deduplicated and a single ROM claimed by different titles fails closed.
    """
    roots = (
        "/storage/emulated/0/Android/data/com.thorium.preview/files/"
        "pegasus-frontend/metafiles",
        "/storage/emulated/0/Android/data/com.thorium.preview/files/"
        "pegasus-frontend/metadata",
        "/storage/emulated/0/pegasus-frontend/metafiles",
        "/storage/emulated/0/pegasus-frontend",
    )
    tokens = {normalize(case.folder), *(normalize(value) for value in case.aliases)}
    paths: list[str] = []
    seen_metadata_paths: set[str] = set()
    for root in roots:
        listing = qa.adb(
            adb, serial, "shell", "find", root, "-maxdepth", "1",
            "-type", "f", "-name", "*.pegasus.txt", check=False,
        ).stdout.splitlines()
        for raw in listing:
            name = Path(raw.strip()).name.lower()
            if any(re.search(rf"-{re.escape(token)}\.metadata\.pegasus\.txt$", name)
                   for token in tokens):
                metadata_path = canonical_shared_path(raw.strip())
                if metadata_path not in seen_metadata_paths:
                    seen_metadata_paths.add(metadata_path)
                    paths.append(raw.strip())
    values: dict[str, set[str]] = {}
    path_titles: dict[str, str] = {}
    for path in paths:
        text = qa.adb(adb, serial, "exec-out", "cat", path).stdout
        current = ""
        for line in text.splitlines():
            if line.startswith("game:"):
                current = normalize(line.split(":", 1)[1])
            elif current and line.startswith("file:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    canonical_value = canonical_shared_path(value)
                    previous_title = path_titles.get(canonical_value)
                    if previous_title is not None and previous_title != current:
                        raise RuntimeError(
                            "metadata title conflict for one canonical ROM path: "
                            f"{canonical_value!r} belongs to both "
                            f"{previous_title!r} and {current!r}"
                        )
                    path_titles[canonical_value] = current
                    values.setdefault(current, set()).add(canonical_value)
    return values


def remote_sha256(adb: Path, serial: str, path: str) -> str:
    result = qa.adb(
        adb, serial, "shell", "sha256sum " + shlex.quote(path), check=False
    )
    match = re.match(r"^([0-9a-fA-F]{64})\s", result.stdout or "")
    if result.returncode != 0 or match is None:
        raise RuntimeError(f"could not hash indexed ROM: {Path(path).name}")
    return match.group(1).lower()


def indexed_nes_qualification(adb: Path, serial: str, case: SystemCase,
                              keys: list[str]) -> dict[str, str]:
    """Resolve the exact legal fixture through the live Alpha index.

    The filename alone is not trusted: the selected title, its live metadata
    path and the bytes on the device must all identify this generated ROM.
    """
    if case.folder != "nes":
        raise ValueError("NES qualification lookup is NES-only")
    title_files = metadata_title_files(adb, serial, case)
    matches: list[tuple[str, str]] = []
    indexed_titles = {normalize(title_from_key(key)): title_from_key(key) for key in keys}
    fixture_title = normalize("Lucent Callback Test")
    for normalized_title, paths in title_files.items():
        if normalized_title != fixture_title:
            continue
        title = indexed_titles.get(normalized_title)
        if title is None:
            continue
        for path in sorted(paths):
            # ImportManager intentionally preserves the exact display title in
            # its destination filename (`Lucent Callback Test.nes`). Bind the
            # indexed title and bytes, never the host generator's hyphenated
            # source basename.
            if remote_sha256(adb, serial, path) == NES_QUALIFICATION_SHA256:
                matches.append((title, path))
    if len(matches) != 1:
        raise RuntimeError(
            "NES qualification requires exactly one indexed legal fixture; "
            f"found={[(title, Path(path).name) for title, path in matches]}"
        )
    title, path = matches[0]
    digest = remote_sha256(adb, serial, path)
    if digest != NES_QUALIFICATION_SHA256:
        raise RuntimeError(
            "indexed NES qualification ROM hash differs from the generated fixture: " + digest
        )
    return {"title": title, "path": path, "sha256": digest,
            "file": Path(path).name, "profile": nes_qa.PROFILE}


def indexed_title_rom_identity(adb: Path, serial: str, case: SystemCase,
                               title: str) -> dict[str, str]:
    paths = sorted(metadata_title_files(adb, serial, case).get(normalize(title), set()))
    if len(paths) != 1:
        raise RuntimeError(
            f"frame-generation identity needs one exact ROM for {title!r}; found {len(paths)}"
        )
    return {"path": paths[0], "sha256": remote_sha256(adb, serial, paths[0])}


def title_has_live_rom(adb: Path, serial: str,
                       title_files: dict[str, set[str]], title: str) -> bool:
    for path in sorted(title_files.get(normalize(title), set())):
        remote = "test -f " + shlex.quote(path)
        if qa.adb(adb, serial, "shell", remote, check=False).returncode == 0:
            return True
    return False


def acceptance_titles(case: SystemCase, keys: list[str], count: int) -> list[str]:
    if len(keys) < count:
        raise RuntimeError(
            f"{case.folder} has only {len(keys)} indexed titles; {count} are required"
        )
    selected = list(case.required_titles)
    target = max(count, len(case.required_titles))
    if len(selected) >= target:
        return selected
    # Exact named regressions come first. Fill the remaining independent
    # samples from the signed live Alpha index, never from a handcrafted path.
    existing = {normalize(value) for value in selected}
    for key in keys:
        title = title_from_key(key)
        if normalize(title) in existing:
            continue
        selected.append(title)
        existing.add(normalize(title))
        if len(selected) >= target:
            break
    return selected


def require_frame_generation_source_tier(
        game: dict[str, object], expected_tier: int,
        system: str, title: str) -> None:
    """Bind a named rate-family title to the detector tier it must prove."""
    framegen = game.get("frameGeneration") or {}
    qualification_report = framegen.get("qualification") or {}
    segment = qualification_report.get("segment") or {}
    actual_tier = int(segment.get("expectedLockedFps", -1))
    if actual_tier != expected_tier:
        raise RuntimeError(
            f"{system} title {title!r} must prove source tier "
            f"{expected_tier}, observed {actual_tier}"
        )
    game["requiredSourceTier"] = expected_tier


def playable_alpha_keys(adb: Path, serial: str, case: SystemCase,
                        keys: list[str], count: int,
                        extra_required_titles: tuple[str, ...] = ()) -> list[str]:
    """Filter stale indexed rows whose referenced ROM no longer exists."""
    title_files = metadata_title_files(adb, serial, case)
    required_names = (*case.required_titles, *extra_required_titles)
    required = {normalize(title) for title in required_names}
    for title in required_names:
        if not title_has_live_rom(adb, serial, title_files, title):
            raise RuntimeError(f"required title ROM is absent: {title}")
    playable = []
    playable_titles = set()
    for key in keys:
        title = title_from_key(key)
        normalized_title = normalize(title)
        if normalized_title in playable_titles:
            continue
        if not title_has_live_rom(adb, serial, title_files, title):
            continue
        playable.append(key)
        playable_titles.add(normalized_title)
        if (len(playable_titles) >= max(count, len(required)) and
                required.issubset(playable_titles)):
            break
    return playable


def move_to_title(adb: Path, serial: str, controller: PhysicalController,
                  current: int, target: int, title: str,
                  output: Path, prefix: str, expected_folder: str,
                  display_names: dict[str, str], keys: list[str]) -> int:
    """Move through a proven per-system Alpha list using its exact 8-row page.

    Single-row traversal took r16 more than seven minutes and crossed Lucent's
    idle/screensaver boundary.  The frozen theme maps physical Left/Right to an
    exact eight-row page in List layout, so use that bounded path. Row zero
    proves the total against the immutable live-key list; later checkpoints
    prove system/layout and the exact expected title (their translucent
    current/total text is not a reliable OCR oracle). The remaining at most
    seven rows still use physical Up/Down.
    """
    if current < 0 or target < 0:
        raise ValueError("Alpha positions must be non-negative")
    checkpoint_number = 0

    def checkpoint(position: int, total: Optional[int],
                   require_counter: bool) -> int:
        nonlocal checkpoint_number
        if position >= len(keys):
            raise AlphaNavigationDrift(
                f"Alpha position {position + 1} exceeds immutable live keys"
            )
        frame = output / f"{prefix}-navigation-{checkpoint_number:02d}.png"
        checkpoint_number += 1
        screenshot(adb, serial, frame)
        expected_title = title_from_key(keys[position])
        try:
            return assert_game_list_checkpoint(
                frame, expected_folder, position + 1, total, display_names,
                expected_title=expected_title,
                require_counter=require_counter,
                # force_alpha_list and the row-zero checkpoint prove List once.
                # Busy r19 wallpaper made repeated footer OCR unreadable; no Y
                # input occurs during traversal, so system + exact immutable
                # title remains the stronger later page-semantics oracle.
                require_list_layout=require_counter,
                require_system_identity=False,
            )
        except AlphaNavigationDrift as original_failure:
            if require_counter:
                raise
            # A human-paced hat pulse can exceptionally land a small number of
            # rows away even though the surrounding eight-row page checkpoints
            # are exact (r19 recovery landed Dezaemon at 195 instead of Destiny
            # of an Emperor at 193). Correction is allowed only after the same
            # system is independently re-proven and the observed title resolves
            # to exactly one immutable live row within two positions.
            context = game_list_identity(
                frame, display_names, require_counter=False
            )
            context_system_matches = context["folder"] == expected_folder
            if (not context["aggregate"] and not context_system_matches and
                    expected_folder == "nes"):
                context_system_matches = (resolve_list_folder(
                    nes_system_label_ocr(frame), display_names
                ) == expected_folder)
            if context["aggregate"] or not context_system_matches:
                raise original_failure
            observed_header = selected_header_ocr(frame)
            observed_position = resolve_alpha_header_position(
                observed_header, keys
            )
            correction = position - observed_position
            if correction == 0 or abs(correction) > 2:
                raise AlphaNavigationDrift(
                    "physical Alpha page deviation is not safely correctable: "
                    f"expected={position + 1} observed={observed_position + 1}"
                ) from original_failure
            correction_code = controller.DOWN if correction > 0 else controller.UP
            correction_label = ("dpad-down-alpha-correction" if correction > 0
                                else "dpad-up-alpha-correction")
            for _ in range(abs(correction)):
                controller.key(correction_code, correction_label, hold=0.025)
            corrected = output / (
                f"{prefix}-navigation-{checkpoint_number - 1:02d}-corrected.png"
            )
            screenshot(adb, serial, corrected)
            return assert_game_list_checkpoint(
                corrected, expected_folder, position + 1, total, display_names,
                expected_title=expected_title, require_counter=False,
                require_list_layout=False, require_system_identity=False,
            )

    # The current translucent header is artwork-led. Tesseract cannot
    # consistently read its small platform label or `1 / N` counter on the
    # real Thor even though the selected title and List row remain crisp. The
    # Cover step immediately proved the system, no system-changing input occurs
    # here, and every checkpoint is joined to the immutable live Alpha title.
    # That is stronger than treating unreadable translucent footer text as a
    # mandatory oracle, and it remains fail-closed on any cursor drift.
    observed_total = checkpoint(current, len(keys), False)
    if target >= observed_total:
        raise AlphaNavigationDrift(
            f"required Alpha position {target + 1} exceeds visible total "
            f"{observed_total}"
        )

    direction = 1 if target > current else -1
    page_code = controller.RIGHT if direction > 0 else controller.LEFT
    page_label = ("dpad-right-exact-page" if direction > 0 else
                  "dpad-left-exact-page")
    page_steps = 0
    while abs(target - current) >= 8:
        controller.key(page_code, page_label, hold=0.045)
        current += direction * 8
        page_steps += 1
        if page_steps % 8 == 0 or abs(target - current) < 8:
            checkpoint(current, observed_total, False)

    row_code = controller.DOWN if direction > 0 else controller.UP
    row_label = ("dpad-down-exact-title" if direction > 0 else
                 "dpad-up-exact-title")
    for _ in range(abs(target - current)):
        controller.key(row_code, row_label, hold=0.025)
        current += direction

    selected = output / f"{prefix}-selected-title.png"
    screenshot(adb, serial, selected)
    assert_game_list_checkpoint(
        selected, expected_folder, target + 1, observed_total, display_names,
        expected_title=title, require_counter=False,
        require_list_layout=False, require_system_identity=False,
    )
    observed = selected_header_ocr(selected)
    if not selected_title_matches(title, observed):
        raise AlphaNavigationDrift(
            f"physical selection did not prove required title {title!r}; "
            f"OCR={observed!r}"
        )
    return target


def select_title_alpha(adb: Path, serial: str,
                       controller: PhysicalController, case: SystemCase,
                       visible_order: list[str], display_names: dict[str, str],
                       keys: list[str], current: int, title: str,
                       output: Path, prefix: str) -> int:
    """Select a title, with one fail-closed deterministic-origin recovery."""
    target = title_position(keys, title)
    try:
        return move_to_title(
            adb, serial, controller, current, target, title, output, prefix,
            case.folder, display_names, keys,
        )
    except AlphaNavigationDrift as first_failure:
        # Never continue relative navigation after a foreign system/count is
        # observed. Rebuild Cover -> system -> Alpha and prove the newly
        # restored remembered row before trying once more.
        recovery_prefix = prefix + "-recovery"
        # Refreshing the live index performs several ADB metadata/path reads.
        # Do that slow work BEFORE re-establishing the interactive position;
        # doing it afterward left the frontend idle for ~17.5 s and its
        # screensaver moved to an unrelated random title (physical r3).
        refreshed_keys = alpha_keys(library_index(adb, serial), case)
        if refreshed_keys != keys:
            raise AlphaNavigationDrift(
                "live Alpha index changed during navigation recovery; refusing "
                "to reuse stale positions"
            ) from first_failure
        go_to_cover_system(controller, visible_order, case.folder)
        cover = output / f"{recovery_prefix}-cover.png"
        screenshot(adb, serial, cover)
        assert_cover_system(cover, case.folder, display_names)
        controller.key(controller.A, "physical-a-reopen-system", hold=0.055)
        time.sleep(0.35)
        _, recovered_position = force_alpha_list(
            adb, serial, controller, output, recovery_prefix,
            case.folder, display_names, keys,
        )
        try:
            return move_to_title(
                adb, serial, controller, recovered_position, target, title, output,
                recovery_prefix, case.folder, display_names, keys,
            )
        except AlphaNavigationDrift as second_failure:
            raise AlphaNavigationDrift(
                "physical Alpha navigation drifted again after one exact "
                "deterministic-origin recovery"
            ) from second_failure


def assert_no_interstitial(frames: list[Path]) -> list[dict[str, str]]:
    evidence = []
    for path in frames:
        text = " ".join(ocr(path).split())
        evidence.append({"path": str(path), "ocr": text})
        if PROHIBITED_TEXT.search(text):
            raise RuntimeError(f"visible launch/return interstitial in {path.name}: {text}")
    return evidence


def _nes_immediate_guest_frame(path: Path) -> bool:
    """Recognize the aspect-preserved NES guest in a full-panel screenshot."""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    if width <= 0 or height <= 0 or abs(width / height - 16 / 9) > 0.01:
        return False
    # The NES destination is centered 4:3 and full height. Sample comfortably
    # inside its black pillars and active area so scaler edge pixels cannot
    # decide the classification.
    pillar_width = max(1, round(width / 9))
    inset = max(pillar_width + 1, round(width / 7.5))
    vertical_inset = max(1, round(height * 0.075))
    left = image.crop((0, vertical_inset, pillar_width, height - vertical_inset))
    right = image.crop(
        (width - pillar_width, vertical_inset, width, height - vertical_inset)
    )
    active = image.crop((inset, 0, width - inset, height))
    luma = lambda pixel: 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]
    pillar_luma = max(
        sum(luma(pixel) for pixel in pillar.getdata()) /
        max(1, pillar.width * pillar.height)
        for pillar in (left, right)
    )
    visible = sum(max(pixel) >= 24 for pixel in active.getdata()) / max(
        1, active.width * active.height
    )
    return pillar_luma <= 12.0 and visible >= 0.03


def classify_nes_immediate_launch_frames(
        frames: list[Path], menu_reference: Path,
        expected_title: Optional[str]) -> list[dict[str, object]]:
    """Require selected-menu* followed by guest+, with no other visible state."""
    if not frames:
        raise RuntimeError("NES immediate launch captured no frames")
    if not expected_title:
        raise RuntimeError("NES immediate launch requires the exact selected title")
    evidence: list[dict[str, object]] = []
    guest_seen = False
    for path in frames:
        selected = classify_nes_library_frame(
            menu_reference, path, expected_title
        )
        text = str(selected["ocr"])
        any_library = (
            float(selected["referenceMeanAbsoluteDifference"]) <
            float(selected["referenceThresholdExclusive"]) and
            bool(selected["structureMatched"])
        )
        if selected["matched"]:
            if guest_seen:
                raise RuntimeError(
                    f"NES library menu reappeared after guest pixels in {path.name}"
                )
            state = "selected-menu"
        elif any_library:
            raise RuntimeError(
                f"NES immediate launch showed the wrong selected menu in {path.name}: "
                f"{text}"
            )
        elif PROHIBITED_TEXT.search(text):
            raise RuntimeError(
                f"visible NES launch interstitial in {path.name}: {text}"
            )
        elif _nes_immediate_guest_frame(path):
            guest_seen = True
            state = "guest"
        else:
            raise RuntimeError(
                f"NES immediate launch showed a foreign/unclassified frame in "
                f"{path.name}: {text}"
            )
        evidence.append({"path": str(path), "ocr": text, "state": state})
    if not guest_seen:
        raise RuntimeError("NES immediate launch never reached guest pixels")
    return evidence


def secondary_token(adb: Path, serial: str) -> str:
    state = qa.adb(adb, serial, "shell", "dumpsys", "display").stdout
    match = re.search(
        r"DisplayViewport\{[^\n]*displayId=4,\s+uniqueId='local:(\d+)'", state
    )
    if match is None:
        raise RuntimeError("Thor lower physical display token was not found")
    return match.group(1)


def wait_new_route(adb: Path, serial: str, baseline: int,
                   case: Optional[SystemCase]) -> tuple[str, str]:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        matches = ROUTE.findall(qa.logs(adb, serial))
        if len(matches) > baseline:
            engine, system = matches[-1]
            normalized_engine, normalized_system = normalize(engine), normalize(system)
            if case is not None:
                if normalized_system not in set(case.aliases) | {case.folder}:
                    raise RuntimeError(
                        f"menu launched {system}/{engine}; expected {case.folder}"
                    )
                if normalized_engine not in case.engines:
                    raise RuntimeError(
                        f"menu launched unexpected engine {engine} for {case.folder}"
                    )
            return engine, system
        time.sleep(0.10)
    raise RuntimeError("physical A did not reach an in-window route")


def has_presented_frame_telemetry(log: str, engine: str, system: str) -> bool:
    """Return true only for an engine-owned indication that the guest advanced.

    Libretro sessions publish their own presented-frame/telemetry markers.  A
    native adapter instead reports its first measured guest frame through
    ``NativeAdapterEngineSession``.  Treating only the libretro vocabulary as
    readiness left Eden on a correctly rendered, intentionally static title
    prompt until the 60-second timeout; the physical gameplay-input phase was
    therefore never reached.

    Keep the engine and system in every accepted marker so stale telemetry from
    a prior title or a different route cannot satisfy the gate.
    """
    exact = any(marker in log for marker in (
        f"Core frame presented engine={engine} system={system}",
        f"Runtime telemetry engine={engine} system={system}",
        f"Health engine={engine} system={system}",
        f"First guest frame engine={engine} system={system}",
    ))
    if exact:
        return True
    # Phase-2 engine health predates the system field. Bind it to the latest
    # exact in-window route and accept only a later health record, so stale
    # telemetry from a previous title or engine cannot qualify this launch.
    route = f"In-window route accepted engine={engine} system={system}"
    route_index = log.rfind(route)
    if route_index < 0:
        return False
    if f"Health engine={engine} " in log[route_index:]:
        return True
    # Cemu and aPS3e ship no measured-fps hook (only the Eden adapter exports
    # lucent_eden_average_game_fps), so "First guest frame" can never log for
    # them.  Their audio prime counter advances only on samples drained from
    # the adapter — guest-produced DSP output, not host-inserted silence — so
    # a started playback bound to this exact route is engine-owned proof the
    # guest advanced.  The visible-screenshot and changed-pixel requirements
    # in the caller still hold independently.
    if f"Adapter audio playback started engine={engine} " in log[route_index:]:
        return True
    # aPS3e ICO presented a 40/80 badge with no adapter-audio line
    # (run ps3-2). Frame-generator HEALTH after this exact route is
    # engine-owned proof a guest frame reached the compositor.
    tail = log[route_index:]
    return (
        "Presentation health base generator=1 role=primary" in tail or
        "Presentation health generator=1 role=primary" in tail
    )


def wait_presented_frame(adb: Path, serial: str, engine: str, system: str,
                         menu: Path, output: Path,
                         timeout: float = 60.0,
                         assist: Optional[Callable[[], None]] = None,
                         ) -> dict[str, object]:
    # Cemu and aPS3e disc boots legitimately spend minutes on solid black
    # (shader/pipeline compilation) and solid white (intro flash) frames that
    # the engine is genuinely presenting — the run that motivated the longer
    # window ended on a full-screen white Wind Waker HD flash with 27 distinct
    # colours while the badge reported 48/47.  The assist presses a real
    # mapped confirm at human pace so an A-gated title prompt cannot deadlock
    # the gate; it cannot manufacture a rendered frame, and every acceptance
    # below still requires engine telemetry plus a visibly changed screen.
    deadline = time.monotonic() + timeout
    next_assist = time.monotonic() + 20.0
    latest = None
    while time.monotonic() < deadline:
        log = qa.logs(adb, serial)
        latest = screenshot(adb, serial, output)
        if (latest["visible"] and changed_pixels(menu, output) >= 5_000 and
                has_presented_frame_telemetry(log, engine, system)):
            return latest
        if assist is not None and time.monotonic() >= next_assist:
            assist()
            next_assist = time.monotonic() + 20.0
        time.sleep(0.20)
    raise RuntimeError(f"no proven visible frame for {system}/{engine}; last={latest}")


SECONDARY_GENERATOR_ATTACHED = re.compile(
    r"Frame generator attached generator=(\d+) role=secondary"
)


def require_dual_screen_lower_presentation(
        read_log: Callable[[], str],
        timeout: float = 10.0) -> dict[str, object]:
    """Require the lower-display generator to have completed one real swap.

    ``wait_presented_frame`` proves only the primary display. Run nds-b57
    (2026-09-01) presented the top screen normally while the secondary
    DisplayFrameGenerator logged ``Presentation stalled generator=2
    presents=0`` for the rest of the launch, so every later lower-panel gate
    measured a stale surface and misreported the stall as game state. The
    generator re-asserts its output cadence exactly once after its first
    successful eglSwapBuffers (``reason=first-successful-swap``); require that
    line for the attached secondary generator within ``timeout`` seconds of
    the primary proof and quote the last stall diagnostic when it never comes.
    The secondary generator is normally ``generator=2`` but a process that
    re-attaches after a previous title has logged ``generator=4``, so the id
    is read from the attach line inside this launch's bounded logcat.
    """
    deadline = time.monotonic() + timeout
    while True:
        log = read_log()
        attached = SECONDARY_GENERATOR_ATTACHED.findall(log)
        generator = int(attached[-1]) if attached else 2
        marker = (
            f"Requested game display cadence generator={generator} "
            "reason=first-successful-swap"
        )
        if marker in log:
            return {"generator": generator, "marker": marker,
                    "secondaryAttached": bool(attached)}
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    stall_prefix = f"Presentation stalled generator={generator}"
    stalls = [line.strip() for line in log.splitlines() if stall_prefix in line]
    last_stall = (stalls[-1] if stalls
                  else f"no '{stall_prefix}' line was logged")
    raise RuntimeError(
        "dual-screen lower generator presented nothing (presents=0) after "
        f"the top screen presented; expected '{marker}' within "
        f"{timeout:.0f} s; last stall: {last_stall}"
    )


def n64_gameplay_evidence(adb: Path, serial: str,
                          controller: PhysicalController, output: Path,
                          prefix: str, reference: Path) -> dict[str, object]:
    """Prove Mupen is visibly advancing and producing audio after input."""
    frames = []
    first = reference
    maximum_delta = 0
    # The frame-generation phase's motion worker has already stopped by
    # this point, and an attract-looping title (F-Zero X, runs n64-5/7)
    # can be back on its static PUSH START card when the first sample
    # lands. Its self-running demo auto-starts ~10 s after the title IF
    # LEFT ALONE — pressing START/A between attempts reset that timer
    # forever (run n64-7 sampled the title through all three stirred
    # attempts). Wait untouched between bounded attempts instead; the
    # demo's full-screen racing then trivially clears the pixel bar.
    for attempt in range(5):
        frames = []
        maximum_delta = 0
        for index in range(8):
            path = output / (
                f"{prefix}-n64-motion-a{attempt + 1}-{index + 1:02d}.png")
            metrics = screenshot(adb, serial, path)
            delta = changed_pixels(first, path, threshold=10)
            maximum_delta = max(maximum_delta, delta)
            frames.append({"frame": metrics, "changedPixels": delta})
            time.sleep(0.14)
        if maximum_delta >= 8_000:
            break
        time.sleep(12.0)
    if maximum_delta < 8_000:
        raise RuntimeError("N64 presented no changing visible gameplay frames")

    controller.key(n64_console_a_key(controller),
                   "physical-n64-a-gameplay-input", hold=0.055)
    post_input = output / f"{prefix}-n64-post-input.png"
    post_metrics = screenshot(adb, serial, post_input)
    post_delta = changed_pixels(first, post_input, threshold=10)

    deadline = time.monotonic() + 20.0
    telemetry = None
    health_pattern = re.compile(
        r"Health engine=mupen64plus-next fps=([0-9.]+) frames=(\d+) "
        r"audioUnderruns=(-?\d+) audioReceived=(\d+) audioWritten=(\d+) "
        r"audioRate=(\d+)"
    )
    while time.monotonic() < deadline:
        matches = health_pattern.findall(qa.logs(adb, serial))
        if matches:
            fps, frame_count, underruns, received, written, rate = matches[-1]
            telemetry = {
                "fps": float(fps), "frames": int(frame_count),
                "audioUnderruns": int(underruns),
                "audioReceived": int(received), "audioWritten": int(written),
                "audioRate": int(rate),
            }
        if (telemetry and float(telemetry["fps"]) >= 55.0 and
                int(telemetry["frames"]) > 0 and
                int(telemetry["audioReceived"]) > 0 and
                int(telemetry["audioWritten"]) > 0 and
                int(telemetry["audioRate"]) > 0):
            break
        time.sleep(0.20)
    else:
        raise RuntimeError(f"N64 produced no sustained video/audio telemetry: {telemetry}")
    return {"motionFrames": frames, "maximumChangedPixels": maximum_delta,
            "physicalInputSent": True, "postInputFrame": post_metrics,
            "postInputChangedPixels": post_delta, "telemetry": telemetry}


def n64_console_a_key(controller: PhysicalController) -> int:
    """Return the Thor button position that the N64 core reads as A.

    The Thor is labelled Nintendo-style: its printed B button is physically
    SOUTH while its printed A button is EAST. EmuFusion intentionally maps
    N64 A to SOUTH and N64 B to EAST, matching the original N64 pad. The
    harness's historical ``controller.A`` name describes the Thor label, not
    the canonical position, and therefore sent N64 B at file selectors and
    mission menus. Keep this title-navigation choice bound to the runtime
    controller contract instead of relying on the printed label.
    """
    return controller.B


def n64_start_entry_presses(path: Path) -> int:
    """Authorize one N64 START press only from a proven START-owned state.

    N64 cold boots such as TWINE expose an explicit PRESS START title card,
    while Quick Resume can already be in controllable gameplay.  The old
    unconditional two-press sequence paused a resumed Ocarina session and
    collected its MAP sheet as if it were gameplay.  Ocarina's pause sheet is
    also START-owned, so recognize its simultaneous MAP/RETURN/SAVE labels and
    close it once.  Every other state advances with console A only.
    """
    text = " ".join(ocr(path).upper().split())
    explicit_prompt = re.search(r"\b(?:PRESS|PUSH)\s+START\b", text) is not None
    ocarina_pause = all(token in text for token in ("MAP", "RETURN", "SAVE"))
    return 1 if explicit_prompt or ocarina_pause else 0


def capture_n64_start_entry_presses(adb: Path, serial: str, output: Path,
                                    prefix: str, sample_count: int = 8,
                                    sample_interval: float = 0.25) -> int:
    """Observe a bounded title-animation cycle before authorizing START.

    TWINE fades its PRESS START lettering completely out for part of the
    animation.  A single arbitrarily-timed screenshot therefore produced a
    false negative on the physical Thor and left the entire 30->60 proof run
    parked on the title card.  Sample a short bounded cycle and retain the
    existing fail-closed OCR predicate: START is still sent only after one
    frame visibly proves a START-owned state.
    """
    if sample_count < 1:
        raise ValueError("N64 entry sample_count must be positive")
    for index in range(sample_count):
        suffix = "" if index == 0 else f"-{index + 1:02d}"
        path = output / f"{prefix}-n64-entry-state{suffix}.png"
        screenshot(adb, serial, path)
        if n64_start_entry_presses(path):
            return 1
        if index + 1 < sample_count:
            time.sleep(sample_interval)
    return 0


def n64_ocarina_gameplay_hud(path: Path) -> bool:
    """Recognize Ocarina's controllable top-screen HUD, not an animated card.

    Pixel motion alone admitted the physical child-Link close-up before proof:
    hair/fairy animation changed enough pixels while no gameplay input could
    move the scene.  Controllable Ocarina gameplay independently exposes red
    hearts at upper-left and saturated action/C-button glyphs at upper-right.
    Requiring both in their physical HUD boxes is insensitive to the world
    palette and rejects title, file-select, dialogue close-ups, pause sheets,
    black loads and FMV.  Do not broaden these boxes: the r5 Deku Tree
    dialogue contained enough red/blue text in the old full-width top-strip
    scan to arm proof while Link was still asleep.
    """
    with Image.open(path) as source:
        image = source.convert("RGB").resize((480, 270))
    red_hearts = 0
    # The 4:3 game viewport is pillarboxed inside the 16:9 Thor screenshot.
    # At the normalized 480x270 analysis size, Ocarina's hearts occupy this
    # upper-left viewport box; dialogue text begins farther right/below it.
    for y in range(18, 38):
        for x in range(82, 126):
            red, green, blue = image.getpixel((x, y))
            if red >= 125 and red >= green * 1.45 and red >= blue * 1.45:
                red_hearts += 1
    action_colours = 0
    # A/B/C action glyphs are confined to the upper-right of the 4:3
    # viewport.  Excluding the outer pillarbox also prevents EmuFusion's own
    # status overlay from contributing to this readiness predicate.
    for y in range(14, 76):
        for x in range(236, 414):
            red, green, blue = image.getpixel((x, y))
            green_button = (green >= 90 and green >= red * 1.25 and
                            green >= blue * 1.20)
            blue_button = (blue >= 100 and blue >= red * 1.25 and
                           blue >= green * 1.08)
            orange_button = (red >= 120 and green >= 55 and blue <= 75 and
                             red >= green * 1.20)
            if green_button or blue_button or orange_button:
                action_colours += 1
    return red_hearts >= 24 and action_colours >= 90


def n64_ocarina_name_entry(path: Path) -> bool:
    """Recognize Ocarina's owned new-file name editor.

    Blindly pressing console A on this screen types the highlighted character
    forever.  The editor exposes three independent labels that do not occur in
    gameplay or the title attract loop; only that exact state authorizes the
    bounded START-to-END, A-to-confirm sequence below.
    """
    text = " ".join(ocr(path).upper().split())
    words = re.findall(r"[A-Z]+", text)

    def resembles(expected: str, threshold: float) -> bool:
        return any(
            difflib.SequenceMatcher(None, word, expected).ratio() >= threshold
            for word in words
        )

    # The Thor's bilinear-scaled N64 text is deliberately recognized as
    # three independent owned labels.  Exact OCR remains preferred, while
    # the bounded fuzzy path covers the physically captured readings
    # NAME->NASE/NURE, DECIDE->DECCA/OECCE and CANCEL->CARCE.  Requiring the
    # question mark plus all three labels prevents a title, file menu or
    # gameplay frame from authorizing START.
    has_name = (re.search(r"\bNAME\s*\?", text) is not None or
                "?" in text and resembles("NAME", 0.50))
    has_end = re.search(r"\bEND\b", text) is not None
    has_decide = (re.search(r"A\s*[-–]\s*DECIDE", text) is not None or
                  resembles("DECIDE", 0.54))
    has_cancel = (re.search(r"B\s*[-–]\s*CANCEL", text) is not None or
                  resembles("CANCEL", 0.66))
    return has_name and has_decide and (has_end or has_cancel)


def n64_ocarina_file_menu_action(path: Path) -> Optional[str]:
    """Return the one safe action owned by an Ocarina file-menu state.

    A blind console-A loop can land on Erase, enter its confirmation sheet,
    choose Quit, and repeat forever.  It also risks destructive input if the
    highlight ever moves.  Bind file loading to the visible file selector and
    use N64 B to leave Copy/Erase/Options sheets without changing a save.
    """
    text = " ".join(ocr(path).upper().split())
    if re.search(r"PLEASE\s+SELECT\s+A\s+FILE", text):
        return "select"
    if (re.search(r"ERASE\s+WHICH\s+FILE", text) or
            re.search(r"COPY\s+WHICH\s+FILE", text) or
            re.search(r"\bOPTIONS\b", text) and
            re.search(r"(?:SOUND|TARGETING|Z\s*TARGETING)", text)):
        return "cancel"
    if (re.search(r"OPEN\s+THIS\s+FILE", text) or
            re.search(r"START\s+WITH\s+THIS\s+FILE", text)):
        return "confirm"
    return None


def wait_n64_ocarina_gameplay_hud(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str, timeout: float = 420.0,
        poll_seconds: float = 1.5) -> dict[str, object]:
    """Advance only owned Ocarina entry states until gameplay HUD is visible.

    A fresh file's name editor, file confirmation, opening movie and dialogue
    physically remained pre-HUD beyond the former 120-second bound on the
    Thor (deadline run r4).  With RIFE active, r73 was still advancing owned
    opening dialogue at the former 300-second deadline.  This remains a
    navigation-only hard deadline; frame-generation collection starts only
    after the HUD predicate passes.
    """
    deadline = time.monotonic() + timeout
    attempt = 0
    recover_file_selection = False
    while time.monotonic() < deadline:
        attempt += 1
        path = output / f"{prefix}-n64-ocarina-hud-{attempt:02d}.png"
        metrics = screenshot(adb, serial, path)
        if n64_ocarina_gameplay_hud(path):
            return {"screenshot": str(path), "samples": attempt,
                    "gameplayHudVisible": True, "frame": metrics}
        file_action = n64_ocarina_file_menu_action(path)
        # START is permitted only on an explicit title/pause state. Every
        # other bounded progression uses N64 A; neither branch can silently
        # accept an unrelated menu choice through a raw Thor-label mismatch.
        if n64_ocarina_name_entry(path):
            # A blank Ocarina file name cannot be confirmed.  The editor
            # initially owns the highlighted A character, so type exactly one
            # character before START moves the cursor to END.  The final
            # console A owns the visible "A-Decide" action.  Sending all three
            # as one bounded transaction prevents the following poll from
            # typing another character while retaining fail-closed ownership.
            controller.key(n64_console_a_key(controller),
                           "physical-n64-a-ocarina-name-character", hold=0.055)
            time.sleep(0.15)
            controller.key(controller.START,
                           "physical-start-n64-ocarina-name-end", hold=0.055)
            time.sleep(0.15)
            controller.key(n64_console_a_key(controller),
                           "physical-n64-a-ocarina-name-confirm", hold=0.055)
        elif file_action == "cancel":
            # Thor's printed A/east position is canonical N64 B.  Cancel is
            # deliberately separate from n64_console_a_key (south/N64 A).
            controller.key(controller.A,
                           "physical-n64-b-ocarina-safe-cancel", hold=0.055)
            recover_file_selection = True
        elif file_action in {"select", "confirm"}:
            if file_action == "select" and recover_file_selection:
                # Move one row toward the file slots after cancelling an
                # unsafe Copy/Erase/Options selection.  Re-check the visible
                # state on the next poll; repeated cancel/up cycles converge
                # without ever confirming a destructive menu.
                controller.hat("up", "physical-up-ocarina-safe-file-recovery")
                recover_file_selection = False
            controller.key(n64_console_a_key(controller),
                           "physical-n64-a-ocarina-file-confirm", hold=0.055)
        elif n64_start_entry_presses(path):
            controller.key(controller.START,
                           "physical-start-n64-ocarina-owned", hold=0.055)
        else:
            controller.key(n64_console_a_key(controller),
                           "physical-n64-a-ocarina-progress", hold=0.055)
        time.sleep(poll_seconds)
    raise RuntimeError(
        "Ocarina never exposed its controllable top-screen gameplay HUD"
    )


def n64_fzero_single_player_race_hud(path: Path) -> bool:
    """Recognize F-Zero X's full-screen GP-race view, never split-screen.

    F-Zero's attract loop contains both a useful one-player race and a
    four-way battle demo.  The latter produces perfect 60/120 cadence but its
    four tiny viewports collapse the 16x9 motion proof and are not a defensible
    image-quality scene.  A genuine one-player race has all three independent
    properties below: no dark full-height/full-width viewport divider, the
    large saturated rank/time glyphs, and the green ENERGY meter.  Rank digits
    become olive in Mute City's dark tunnel (physical r34), so hue-specific
    yellow matching is invalid.  Menu cards can satisfy at most one property.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        # Split seams are not guaranteed to land on the mathematical centre:
        # r36's physical four-way separator was y=532 on a 1080-line capture.
        # Scan a narrow centre band and reject any mostly-dark row/column.
        horizontal_seam = max(
            sum(max(image.getpixel((x, y))) < 35
                for x in range(int(width * 0.15), int(width * 0.85))) /
            max(1, int(width * 0.70))
            for y in range(int(height * 0.46), int(height * 0.54))
        )
        vertical_seam = max(
            sum(max(image.getpixel((x, y))) < 35
                for y in range(int(height * 0.05), int(height * 0.95))) /
            max(1, int(height * 0.90))
            for x in range(int(width * 0.46), int(width * 0.54))
        )

        # The centred 4:3 N64 composition places the large rank/time glyphs
        # across its upper middle and the green ENERGY bar at upper right.
        # r246 proved that sampling the physical screen's lower band only
        # caught incidental track/vehicle colours: it reduced long, genuine
        # one-player races to isolated false detections. Keep these two HUD
        # populations in their real, independent top regions. Menus may have
        # a saturated heading or green accent, but do not have both fixed HUD
        # populations; two/four-player races remain rejected by the seam gate.
        glyph = 0
        for y in range(int(height * 0.06), int(height * 0.27)):
            for x in range(int(width * 0.25), int(width * 0.62)):
                red, value_green, blue = image.getpixel((x, y))
                if (max(red, value_green, blue) > 100 and
                        max(red, value_green, blue) -
                        min(red, value_green, blue) > 25):
                    glyph += 1
        green = 0
        for y in range(int(height * 0.06), int(height * 0.22)):
            for x in range(int(width * 0.60), int(width * 0.86)):
                red, value_green, blue = image.getpixel((x, y))
                if (value_green > 110 and value_green > red * 1.25 and
                        value_green > blue * 1.25):
                    green += 1
        coloured_floor = max(500, int(width * height * 0.0015))
        # A one-player track can itself be a mostly-dark vertical ribbon
        # through screen centre (physical F-Zero Mute City, r42j).  The actual
        # two-player attract is divided horizontally (r42k), and the four-way
        # view contains that same horizontal divider plus a vertical one.
        # Therefore horizontal is the fail-closed viewport signature; vertical
        # alone is scene content.  Keep the vertical measurement above as a
        # documented diagnostic of the exact false-positive shape.
        split_screen = horizontal_seam >= 0.50
        return (
            not split_screen and
            glyph >= coloured_floor and green >= coloured_floor
        )


def n64_fzero_owned_action(text: str) -> Optional[str]:
    """Return an input only for a visibly identified F-Zero menu state."""
    normalized = " ".join(text.upper().split())
    if re.search(r"\b(?:PRESS|PUSH)\s+START\b", normalized):
        return "start"
    if "SELECT MODE" in normalized:
        return "select-gp"
    if "SELECT COURSE" in normalized:
        return "accept"
    # A GP course card ("<n>: NAME" plus its layout subtitle such as FIGURE
    # EIGHT) demands one confirm. Quick Resume can boot qualification directly
    # onto this card frozen mid-transition (run r26 resumed r25's final frame
    # and timed out staring at it), so the card must be an owned state like
    # every other menu. The cup header never survives OCR of this font
    # ("F-ZERO JACK CUP" reads as "F-ZERO TACK", run r27), so ownership is
    # the numbered course line plus a known course token.
    if (re.search(r"\b\d\s*[:.]\s*[A-Z]", normalized) and
            ("MUTE CITY" in normalized or "FIGURE" in normalized)):
        return "accept"
    if ("BLUE FALCON" in normalized and "ACCELERATION" in normalized and
            "BOOST" in normalized and "GRIP" in normalized):
        return "accept"
    return None


def rearm_n64_fzero_accelerator_on_owned_accept(
        controller: PhysicalController, action: Optional[str]) -> bool:
    """Create a fresh N64-A edge only on an OCR-owned accept screen.

    Qualification owns one continuous throttle hold while the race is live.
    If the craft retires, that still-held button cannot advance F-Zero's next
    course or machine card: the game needs a new key-down edge.  Release, tap,
    and restore the hold only after the visible-state classifier proves an
    ``accept`` card.  Never inject an edge on an unknown scene, title prompt,
    or mode selector; their navigation remains owned by the bounded entry
    state machine above.
    """
    if action != "accept":
        return False
    accelerator = n64_console_a_key(controller)
    controller.key_up(
        accelerator, "physical-n64-a-fzero-owned-rearm-release")
    controller.key(
        accelerator, "physical-n64-a-fzero-owned-rearm-accept", hold=0.08)
    controller.key_down(
        accelerator, "physical-n64-a-fzero-owned-rearm-throttle")
    return True


def prepare_n64_fzero_attract_race(
        adb: Path, serial: str, controller: PhysicalController, output: Path,
        prefix: str, timeout: float = 240.0,
        warmup_cycles: int = 1) -> dict[str, object]:
    """Cold-reset into F-Zero's moving full-screen single-player attract race.

    Open-loop steering is not a repeatable qualification scene: r32 and r33
    both left the craft motionless against a wall while cadence itself was
    healthy.  The host's reviewed Select+Start reset returns even a Quick
    Resume launch to the title without deleting save data.  From that point
    qualification supplies *no game input*; F-Zero's own AI attract race owns
    the camera motion.  The four-way attract is still rejected by the HUD
    predicate, and one visibly moving pair is required before proof can arm.
    The built-in proof path treats the first full-screen attract as a warm-up:
    on a cold reset it begins while the controller is still acquiring source
    tiers and can end before 30 asynchronous proof samples exist (r35).
    Qualification-only RIFE instead uses this first moving race to start its
    backend warm-up, then independently waits for a fresh one-player attract
    after its eleven-second timing epoch is ready. ``warmup_cycles`` therefore
    remains one by default and is zero only for that two-stage RIFE path.

    F-Zero's stylized title text did not survive OCR reliably in r37, so do not
    use text as a cycle boundary. Eight consecutive non-race captures separate
    warm-up cycles. A one-frame fade/HUD dropout cannot complete the warm-up,
    while the observed title/black/split interval is substantially longer.
    Keep this wait hard-bounded to four minutes: r246 proved a bad classifier
    could otherwise keep the OLED illuminated for ten minutes even though
    valid races were already present. Device cleanup remains owned by the
    outer runner's unconditional trap.
    """
    if warmup_cycles < 0:
        raise ValueError("F-Zero warmup cycle count cannot be negative")
    controller.chord(
        (controller.STOP, controller.START),
        "physical-n64-fzero-host-reset-for-attract", hold=2.20,
    )
    time.sleep(2.0)
    deadline = time.monotonic() + timeout
    stable = 0
    samples = 0
    last_path: Optional[Path] = None
    previous_hud_path: Optional[Path] = None
    last_motion = 0.0
    warmup_race_seen = False
    warmup_race_cycles = 0
    non_race_gap_samples = 0
    while time.monotonic() < deadline:
        samples += 1
        path = output / f"{prefix}-n64-fzero-attract-{samples:03d}.png"
        screenshot(adb, serial, path)
        last_path = path
        if n64_fzero_single_player_race_hud(path):
            warmup_race_seen = True
            non_race_gap_samples = 0
            stable += 1
            if previous_hud_path is not None:
                last_motion = mean_absolute_difference(previous_hud_path, path)
            previous_hud_path = path
            if (warmup_race_cycles >= warmup_cycles and stable >= 2 and
                    last_motion >= 2.0):
                return {"samples": samples, "screenshot": str(path),
                        "stableHudSamples": stable,
                        "movingPairMeanAbsDiff": round(last_motion, 5),
                        "warmupRaceCycles": warmup_race_cycles,
                        "sceneProvenance": "single-player-attract-race",
                        "gameplayInputs": [],
                        "hostActions": ["select-start-core-reset"]}
        else:
            stable = 0
            previous_hud_path = None
            last_motion = 0.0
            if warmup_race_seen:
                non_race_gap_samples += 1
                if non_race_gap_samples >= 8:
                    warmup_race_cycles += 1
                    warmup_race_seen = False
                    non_race_gap_samples = 0
        time.sleep(0.50)
    raise RuntimeError(
        "F-Zero X never exposed a stable moving full-screen single-player "
        "attract race without gameplay input; "
        f"samples={samples}, last={last_path}"
    )


FZERO_RIFE_SCENE_RETRY_SECONDS = 180.0


def wait_n64_fzero_moving_attract_race(
        adb: Path, serial: str, output: Path, prefix: str,
        timeout: float = FZERO_RIFE_SCENE_RETRY_SECONDS) -> dict[str, object]:
    """Wait input-free for the next moving full-screen one-player attract.

    F-Zero changes camera layouts within its attract loop. Physical r247
    proved that the second one-player view can become a two-player horizontal
    split while RIFE is accumulating its first eleven-second timing epoch.
    Once that epoch is already ready, wait for two consecutive one-player HUD
    captures with real pixel motion and hand the very next operation back to
    the compositor collector. This function never resets the core or sends a
    controller event, and is separately bounded from the cold-start wait.
    r248 reached the title transition after 90 seconds and r250 still had not
    reached the next race at 120 seconds. The measured cold loop needs roughly
    140 seconds on the host screenshot/classification path, so the dedicated
    retry remains bounded at 180 seconds and under the capture-wide hard cap.
    """
    deadline = time.monotonic() + timeout
    samples = 0
    stable = 0
    previous_hud_path: Optional[Path] = None
    last_path: Optional[Path] = None
    last_motion = 0.0
    while time.monotonic() < deadline:
        samples += 1
        path = output / f"{prefix}-n64-fzero-ready-{samples:03d}.png"
        screenshot(adb, serial, path)
        last_path = path
        if n64_fzero_single_player_race_hud(path):
            stable += 1
            if previous_hud_path is not None:
                last_motion = mean_absolute_difference(
                    previous_hud_path, path)
            previous_hud_path = path
            if stable >= 2 and last_motion >= 2.0:
                return {
                    "samples": samples,
                    "screenshot": str(path),
                    "stableHudSamples": stable,
                    "movingPairMeanAbsDiff": round(last_motion, 5),
                    "sceneProvenance": "single-player-attract-race",
                    "gameplayInputs": [],
                }
        else:
            stable = 0
            previous_hud_path = None
            last_motion = 0.0
        time.sleep(0.50)
    raise RuntimeError(
        "F-Zero X did not return to a stable moving full-screen one-player "
        f"attract race after timing warm-up; samples={samples}, last={last_path}"
    )


def n64_twine_owned_action(text: str) -> Optional[str]:
    """Classify only TWINE screens that visibly own a navigation input."""
    normalized = " ".join(text.upper().split())
    if re.search(r"\b(?:PRESS|PUSH)\s+START\b", normalized):
        return "start"
    # TWINE's angular font repeatedly OCRs "Load/Save Menu" as "oad Save
    # len" on the Thor.  EMPTY + PAGES + SAVE are three independent labels
    # unique to the notebook and remain readable across the four OCR modes.
    if ("EMPTY" in normalized and "PAGES" in normalized and
            "SAVE" in normalized):
        return "save"
    # MAIN MENU itself similarly aliases to MAIN VIEN/WEM.  The paired menu
    # rows START GAME and MULTIPLAYER are stable and cannot occur in gameplay.
    if "START GAME" in normalized and "MULTIPLAYER" in normalized:
        return "accept"
    if ("MISSION SELECTION" in normalized or
            "MISSION BRIEFING" in normalized or
            "SELECT DIFFICULTY" in normalized or
            ("SECRET AGENT" in normalized and "00 AGENT" in normalized) or
            "COURIER" in normalized):
        return "accept"
    return None


def n64_twine_gameplay_hud(path: Path) -> bool:
    """Recognize TWINE's first-person health HUD, never a menu transition."""
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        # The N64 viewport is letterboxed on Thor.  TWINE's first-person
        # health cross and bar occupy this stable lower-left region; title
        # and notebook screens can contain red artwork, but do not satisfy
        # the paired red+green predicate here.  Physical Thor captures are
        # darker than the synthetic fixture, so use channel dominance rather
        # than requiring near-primary RGB values.
        crop = image.crop((int(width * 0.04), int(height * 0.58),
                           int(width * 0.30), int(height * 0.94)))
        red = 0
        green = 0
        for r, g, b in crop.getdata():
            if r >= 75 and r >= g * 2.2 and r >= b * 2.2:
                red += 1
            if g >= 65 and g >= r * 1.45 and g >= b * 1.45:
                green += 1
        return red >= 300 and green >= 500


def n64_twine_title_start_visual(path: Path) -> bool:
    """Recognize the visibly owned PRESS START state in Thor captures.

    Mupen currently rotates TWINE's N64 picture ninety degrees inside the
    landscape top-display surface. Tesseract consequently misses the prompt,
    but the prompt itself remains a stable black vertical glyph cluster over
    the otherwise bright white title art. The crop deliberately excludes the
    black game logo and Bond silhouette. It must contain both a mostly bright
    field and enough near-black prompt pixels, so the prompt's blinking blank
    phase, boot cards, gameplay and the cyan/gold front menu all fail.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        crop = image.crop((int(width * 0.24), int(height * 0.22),
                           int(width * 0.34), int(height * 0.50)))
        total = max(1, crop.width * crop.height)
        dark = bright = 0
        for r, g, b in crop.getdata():
            if max(r, g, b) <= 70:
                dark += 1
            if min(r, g, b) >= 145:
                bright += 1
        return dark / total >= 0.015 and bright / total >= 0.85


def n64_twine_title_art_visual(path: Path) -> bool:
    """Recognize TWINE title art even while PRESS START is blinked off."""
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        crop = image.crop((int(width * 0.24), int(height * 0.22),
                           int(width * 0.34), int(height * 0.50)))
        total = max(1, crop.width * crop.height)
        bright = 0
        for r, g, b in crop.getdata():
            if min(r, g, b) >= 145:
                bright += 1
        return bright / total >= 0.85


def n64_twine_front_menu_visual(path: Path) -> bool:
    """Recognize TWINE's front/difficulty selection family without OCR.

    TWINE is rendered ninety degrees inside Thor's landscape screencap and its
    low-resolution angular font produces no usable Tesseract words. The menu
    family has a much stronger invariant: a large gold Bond silhouette and
    rule, a cyan wire/text panel and a yellow selected row, with no green HUD.
    Fractions keep the predicate resolution-independent. Pressing console A on
    each owned member is safe: Start Game enters setup and the highlighted
    Agent difficulty advances toward its mission. Physical r156's difficulty
    panel has cyan fraction 0.0184; the title's nearest false candidate is
    0.0170, while profile selection is handled by its independent blue-grid
    predicate and gameplay has the green health bar.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
        total = max(1, image.width * image.height)
        orange = cyan = yellow = green = 0
        for r, g, b in image.getdata():
            if r >= 100 and g >= 35 and g <= r * 0.75 and b <= g * 0.75:
                orange += 1
            if g >= 75 and b >= 75 and r <= min(g, b) * 0.75:
                cyan += 1
            if r >= 100 and g >= 80 and b <= min(r, g) * 0.55:
                yellow += 1
            if g >= 60 and g >= r * 1.4 and g >= b * 1.4:
                green += 1
        return (orange / total >= 0.030 and cyan / total >= 0.018 and
                yellow / total >= 0.055 and green / total < 0.001)


def n64_twine_mission_selection_visual(path: Path) -> bool:
    """Recognize TWINE's visibly owned mission-selection notebook.

    The clean r157 path reaches a large cyan rectangular notebook after the
    highlighted Agent difficulty is accepted.  Its cyan frame spans all four
    sides of the stable top-display viewport and encloses separate white,
    neutral-gray and yellow selection populations.  Requiring those four
    edge populations distinguishes it from the blue profile grid; the low
    orange population distinguishes it from the front/difficulty family, and
    the green exclusion prevents scene artwork from owning a menu input.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size

        def cyan_fraction(box: tuple[int, int, int, int]) -> float:
            crop = image.crop(box)
            total = max(1, crop.width * crop.height)
            cyan = 0
            for r, g, b in crop.getdata():
                if g >= 75 and b >= 75 and r <= min(g, b) * 0.75:
                    cyan += 1
            return cyan / total

        left_cyan = cyan_fraction((int(width * 0.15), int(height * 0.16),
                                   int(width * 0.24), int(height * 0.82)))
        right_cyan = cyan_fraction((int(width * 0.78), int(height * 0.16),
                                    int(width * 0.84), int(height * 0.82)))
        top_cyan = cyan_fraction((int(width * 0.15), int(height * 0.16),
                                  int(width * 0.84), int(height * 0.24)))
        bottom_cyan = cyan_fraction((int(width * 0.15), int(height * 0.71),
                                     int(width * 0.84), int(height * 0.82)))

        total = max(1, width * height)
        white = gray = yellow = orange = green = 0
        for r, g, b in image.getdata():
            low = min(r, g, b)
            high = max(r, g, b)
            if low >= 145:
                white += 1
            if low >= 80 and high - low <= 20:
                gray += 1
            if r >= 100 and g >= 80 and b <= min(r, g) * 0.55:
                yellow += 1
            if r >= 100 and g >= 35 and g <= r * 0.75 and b <= g * 0.75:
                orange += 1
            if g >= 60 and g >= r * 1.4 and g >= b * 1.4:
                green += 1
        return (left_cyan >= 0.10 and right_cyan >= 0.15 and
                top_cyan >= 0.12 and bottom_cyan >= 0.13 and
                white / total >= 0.030 and gray / total >= 0.040 and
                yellow / total >= 0.015 and orange / total < 0.020 and
                green / total < 0.002)


def n64_twine_mission_briefing_visual(path: Path) -> bool:
    """Recognize TWINE's owned briefing with its START THE MISSION action.

    The physical r158 screen follows mission selection and exposes a bright
    cyan Start The Mission row beside blue briefing text, a small red action
    marker and restrained white/yellow accents.  Its population is sharply
    separated from the white title, gold front menu, blue profile grid, cyan
    mission notebook and first-person HUD.  The physical screen explicitly
    says ``Press START To Continue``, so console Start is the owned action.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
        total = max(1, image.width * image.height)
        cyan = blue = white = yellow = orange = green = red = 0
        for r, g, b in image.getdata():
            if g >= 75 and b >= 75 and r <= min(g, b) * 0.75:
                cyan += 1
            if b >= 55 and b >= r * 1.5 and b >= g * 1.25:
                blue += 1
            if min(r, g, b) >= 145:
                white += 1
            if r >= 100 and g >= 80 and b <= min(r, g) * 0.55:
                yellow += 1
            if r >= 100 and g >= 35 and g <= r * 0.75 and b <= g * 0.75:
                orange += 1
            if g >= 60 and g >= r * 1.4 and g >= b * 1.4:
                green += 1
            if r >= 75 and r >= g * 2.2 and r >= b * 2.2:
                red += 1
        return (0.024 <= cyan / total <= 0.035 and
                0.020 <= blue / total <= 0.050 and
                0.012 <= white / total <= 0.030 and
                0.003 <= yellow / total <= 0.012 and
                orange / total < 0.002 and green / total < 0.001 and
                0.001 <= red / total <= 0.004)


def n64_twine_blue_selection_visual(path: Path) -> bool:
    """Recognize TWINE's owned profile/mission selection grid.

    After Start Game the clean physical r155 path presents a cyan-outlined
    grid of blue profile cards with one white/yellow selected card. The N64
    image is still rotated and OCR returns nothing useful, but this four-colour
    population is stable and absent from the white title, front menu and live
    first-person HUD. Console A is the screen's visible select action.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
        total = max(1, image.width * image.height)
        cyan = blue = white = yellow = green = 0
        for r, g, b in image.getdata():
            if g >= 70 and b >= 80 and r <= min(g, b) * 0.75:
                cyan += 1
            if b >= 55 and b >= r * 1.5 and b >= g * 1.25:
                blue += 1
            if min(r, g, b) >= 145:
                white += 1
            if r >= 100 and g >= 80 and b <= min(r, g) * 0.55:
                yellow += 1
            if g >= 60 and g >= r * 1.4 and g >= b * 1.4:
                green += 1
        return (cyan / total >= 0.012 and blue / total >= 0.10 and
                white / total >= 0.015 and yellow / total >= 0.015 and
                green / total < 0.002)


def prepare_n64_twine_gameplay(adb: Path, serial: str,
                               controller: PhysicalController, output: Path,
                               prefix: str, timeout: float = 180.0
                               ) -> dict[str, object]:
    """Drive TWINE's fresh/resumed profile menus with visible ownership.

    The game may arrive at a fading PRESS START card, Main Menu, an empty
    Load/Save notebook, the Rumble Pak warning, or Mission Selection depending
    on retained state.  A blind repeating cycle physically bounced between
    these screens.  Reclassify after every action and stop only after TWINE's
    first-person health HUD persists; the generic live-motion gate remains
    responsible for proving actual movement before instrumentation is armed.
    """
    deadline = time.monotonic() + timeout
    actions: list[str] = []
    owned_entry_action_seen = False
    gameplay_hud_samples = 0
    last_text = ""
    last_path: Optional[Path] = None
    sample = 0
    while time.monotonic() < deadline:
        sample += 1
        path = output / f"{prefix}-n64-twine-entry-{sample:02d}.png"
        screenshot(adb, serial, path)
        last_path = path
        action = None
        title_start = n64_twine_title_start_visual(path)
        if title_start:
            action = "start"
        # OCR is several seconds slower than the visual predicates on Thor.
        # During the title's prompt-off phase, poll the known title art again
        # quickly instead of missing the next visibly owned prompt and falling
        # into the long unowned attract loop.
        if action is None and n64_twine_title_art_visual(path):
            last_text = ""
            gameplay_hud_samples = 0
            time.sleep(0.10)
            continue
        if action is None and n64_twine_mission_selection_visual(path):
            action = "accept"
        if action is None and n64_twine_mission_briefing_visual(path):
            action = "start"
        if action is None and n64_twine_front_menu_visual(path):
            action = "accept"
        if action is None and n64_twine_blue_selection_visual(path):
            action = "accept"
        gameplay_hud = n64_twine_gameplay_hud(path)
        if action is None and not gameplay_hud:
            last_text = " ".join(ocr(path).split())
            action = n64_twine_owned_action(last_text)
        if gameplay_hud and owned_entry_action_seen:
            gameplay_hud_samples += 1
            if gameplay_hud_samples >= 2:
                return {
                    "actions": actions,
                    "lastText": last_text,
                    "screenshot": str(path),
                    "sceneProvenance": "owned-menu-to-mission",
                }
            time.sleep(0.5)
            continue
        # TWINE's title idle loop contains a first-person attract demo with the
        # exact same health HUD as a controllable mission. Physical r148/r149
        # accepted that demo, then deterministically fell back to Main Menu
        # after roughly 20 seconds. A HUD is therefore evidence of appearance,
        # not ownership, until this run has visibly classified and advanced at
        # least one title/profile/mission screen. Let an unowned demo finish;
        # never inject gameplay input into it or call it qualification content.
        # Physical r151 proved that A does not exit this demo: it resets or
        # extends the attract state and can leave the same first-person frame
        # up for the entire bounded wait.  Any input before an owned menu is
        # therefore both ineffective and provenance-destroying.
        if gameplay_hud:
            gameplay_hud_samples = 0
            time.sleep(0.5)
            continue
        gameplay_hud_samples = 0
        if action == "start":
            controller.key(controller.START, "physical-start-n64-twine-owned",
                           hold=0.08)
        elif action == "save":
            controller.hat("down", "physical-down-n64-twine-save", hold=0.16)
            controller.key(n64_console_a_key(controller),
                           "physical-a-n64-twine-save", hold=0.08)
        elif action == "accept":
            controller.key(n64_console_a_key(controller),
                           "physical-a-n64-twine-owned", hold=0.08)
        if action is not None:
            actions.append(action)
            owned_entry_action_seen = True
            time.sleep(1.5)
            continue
        time.sleep(0.5)
    raise RuntimeError(
        "TWINE never left its owned title/profile menus for a structured "
        f"game scene; actions={actions}, last OCR={last_text!r}, "
        f"last={last_path}"
    )


def _capture_nes_control(adb: Path, serial: str,
                         controller: PhysicalController, code: int,
                         name: str, output: Path, prefix: str) -> Path:
    path = output / f"{prefix}-nes-control-{name.lower()}.png"
    label = f"nes-qualification-{name.lower()}"
    if code in {controller.UP, controller.DOWN, controller.LEFT, controller.RIGHT}:
        axis = controller.HAT_Y if code in {controller.UP, controller.DOWN} \
            else controller.HAT_X
        value = -1 if code in {controller.UP, controller.LEFT} else 1
        controller.trace.append(InputTrace(label + ":hat-down",
                                            time.monotonic_ns() // 1_000_000))
        controller.event(controller.EV_ABS, axis, value)
        controller.sync()
        time.sleep(0.18)
        screenshot(adb, serial, path)
        controller.event(controller.EV_ABS, axis, 0)
        controller.sync()
        controller.trace.append(InputTrace(label + ":hat-up",
                                            time.monotonic_ns() // 1_000_000))
    elif code in {controller.STOP, controller.START}:
        # Host semantics intentionally deliver short Select/Start taps on
        # release. The fixture retains their unique response for 30 NMIs.
        controller.key(code, label, hold=0.08)
        time.sleep(0.10)
        screenshot(adb, serial, path)
    else:
        controller.key_down(code, label)
        time.sleep(0.18)
        screenshot(adb, serial, path)
        controller.key_up(code, label)
    time.sleep(0.12)
    return path


def _capture_nes_motion_pair(adb: Path, serial: str, output: Path,
                             prefix: str, label: str) -> tuple[Path, Path]:
    before = output / f"{prefix}-nes-motion-{label}-before.png"
    after = output / f"{prefix}-nes-motion-{label}-after.png"
    screenshot(adb, serial, before)
    time.sleep(0.25)
    screenshot(adb, serial, after)
    return before, after


def normalize_nes_fixture_motion(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str, phase: str) -> dict[str, object]:
    """Return the fixture to moving state through its physical Start oracle."""
    initial_before, initial_after = _capture_nes_motion_pair(
        adb, serial, output, prefix, phase + "-initial"
    )
    try:
        motion = nes_qa.analyze_motion(initial_before, initial_after, 250)
        return {
            "initialState": "moving", "action": "none",
            "actionTraceLabel": "", "motion": motion,
            "initialBefore": str(initial_before),
            "initialAfter": str(initial_after),
            "motionBefore": str(initial_before),
            "motionAfter": str(initial_after),
        }
    except ValueError as failure:
        static = re.search(r"did not visibly advance: changedPixels=(\d+)", str(failure))
        if static is None or int(static.group(1)) >= 100:
            raise
        changed = int(static.group(1))

    trace_label = f"nes-qualification-{phase}-restore-moving"
    controller.key(controller.START, trace_label, hold=0.08)
    # Start is consumed on release and the fixture advances on NMI. Do not let
    # the pre-toggle frame leak into the independently captured proof pair.
    time.sleep(0.20)
    motion_before, motion_after = _capture_nes_motion_pair(
        adb, serial, output, prefix, phase + "-normalized"
    )
    try:
        motion = nes_qa.analyze_motion(motion_before, motion_after, 250)
    except ValueError as failure:
        raise RuntimeError(
            "physical Start did not restore NES fixture motion"
        ) from failure
    return {
        "initialState": "static", "initialChangedPixels": changed,
        "action": "physical-start", "actionTraceLabel": trace_label,
        "motion": motion,
        "initialBefore": str(initial_before),
        "initialAfter": str(initial_after),
        "motionBefore": str(motion_before),
        "motionAfter": str(motion_after),
    }


def nes_fixture_evidence(adb: Path, serial: str,
                         controller: PhysicalController, output: Path,
                         prefix: str, presented_path: Path) -> dict[str, object]:
    """Exercise the fixture oracles before the long frame-generation campaign."""
    geometry = nes_qa.analyze_geometry(presented_path)
    motion_normalization = normalize_nes_fixture_motion(
        adb, serial, controller, output, prefix, "startup"
    )
    motion_before = Path(str(motion_normalization["motionBefore"]))
    motion_after = Path(str(motion_normalization["motionAfter"]))
    motion = dict(motion_normalization["motion"])

    time.sleep(0.65)  # expire any prior 30-NMI control response
    neutral = output / f"{prefix}-nes-control-neutral.png"
    screenshot(adb, serial, neutral)
    physical = {
        "A": controller.A, "B": controller.B, "Select": controller.STOP,
        "Start": controller.START, "Up": controller.UP, "Down": controller.DOWN,
        "Left": controller.LEFT, "Right": controller.RIGHT,
    }
    paths = {}
    controls = None
    control_cleanup = None
    try:
        paths = {name: _capture_nes_control(
            adb, serial, controller, physical[name], name, output, prefix
        ) for name in nes_qa.CONTROL_NAMES}
        controls = nes_qa.analyze_controls(neutral, paths)
    finally:
        # Start is itself one of the control oracles. Whether a later capture or
        # analyzer fails, observe the actual visible state and physically
        # restore motion before session teardown can persist a frozen snapshot.
        control_cleanup = normalize_nes_fixture_motion(
            adb, serial, controller, output, prefix, "post-controls"
        )
    if control_cleanup["action"] != "physical-start":
        raise RuntimeError("NES Start control did not leave the fixture frozen")

    # The control pass toggled Select once (50 Hz). Motion is now normalized;
    # cycle 50->40->30->60 without another blind Start toggle.
    time.sleep(0.65)  # expire the final Right direct-mode latch
    for index in range(3):
        controller.key(controller.STOP,
                       f"nes-qualification-restore-60-{index + 1}", hold=0.08)
    time.sleep(0.65)

    deadline = time.monotonic() + 12.0
    last_error = ""
    while time.monotonic() < deadline:
        try:
            audio = nes_qa.analyze_audio(qa.logs(adb, serial))
            break
        except ValueError as error:
            last_error = str(error)
            time.sleep(0.25)
    else:
        raise RuntimeError("NES audio qualification failed: " + last_error)
    return {
        "profile": nes_qa.PROFILE,
        "geometry": geometry, "motion": motion, "controls": controls,
        "motionNormalization": motion_normalization,
        "postControlMotionNormalization": control_cleanup,
        "audio": audio,
        "paths": {
            "geometry": str(presented_path), "motionBefore": str(motion_before),
            "motionAfter": str(motion_after), "controlNeutral": str(neutral),
            "motionNormalizationInitialBefore":
                motion_normalization["initialBefore"],
            "motionNormalizationInitialAfter":
                motion_normalization["initialAfter"],
            "controls": {name: str(path) for name, path in paths.items()},
        },
    }


def _wait_log_count(adb: Path, serial: str, marker: str, baseline: int,
                    timeout: float = 8.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        log = qa.logs(adb, serial)
        if log.count(marker) > baseline:
            return log
        time.sleep(0.10)
    raise RuntimeError(f"timed out waiting for exact runtime marker: {marker}")


def nes_cheat_evidence(adb: Path, serial: str,
                       controller: PhysicalController, output: Path,
                       prefix: str) -> dict[str, object]:
    before = output / f"{prefix}-nes-cheat-before.png"
    enabled = output / f"{prefix}-nes-cheat-enabled.png"
    disabled = output / f"{prefix}-nes-cheat-disabled.png"
    baseline_log = qa.logs(adb, serial)
    shown_marker = "Cheats panel shown engine=mesen system=nes count=1 lowerDisplay=true"
    panel = output / f"{prefix}-nes-cheat-panel.png"
    initial = output / f"{prefix}-nes-cheat-initial-state.png"
    enabled_marker = ("id=qualification-red-border enabled=true active=1 "
                      "callbackReturned=true persisted=true acknowledged=false "
                      "effectProofRequired=true marker=cheat-apply-returned")
    disabled_marker = ("id=qualification-red-border enabled=false active=0 "
                       "callbackReturned=true persisted=true acknowledged=false "
                       "effectProofRequired=true marker=cheat-apply-returned")
    panel_open = False
    known_enabled = False
    initial_enabled = False
    panel_text = ""
    panel_proof = None
    final_log = baseline_log

    def red_border(path: Path) -> bool:
        mean = ImageStat.Stat(Image.open(path).convert("RGB").crop(
            (320, 0, 1600, 24))).mean[:3]
        return mean[0] > mean[1] + 60 and mean[0] > mean[2] + 60

    try:
        controller.chord((controller.STOP, controller.L1),
                         "nes-open-cheats-panel", hold=0.10)
        _wait_log_count(adb, serial, shown_marker, baseline_log.count(shown_marker))
        panel_open = True
        screenshot(adb, serial, panel, secondary_token(adb, serial))
        try:
            panel_proof = nes_qa.analyze_cheat_panel(
                panel, qa.logs(adb, serial)
            )
        except ValueError as failure:
            raise RuntimeError(
                "physical Cheats panel did not expose the selected "
                "Qualification red border OFF row"
            ) from failure
        panel_text = str(panel_proof["rowOcr"])
        screenshot(adb, serial, initial)
        known_enabled = red_border(initial)
        initial_enabled = known_enabled
        if known_enabled:
            count = qa.logs(adb, serial).count(disabled_marker)
            controller.key(controller.A, "nes-normalize-persisted-cheat-off", hold=0.08)
            _wait_log_count(adb, serial, disabled_marker, count)
            known_enabled = False
            time.sleep(0.20)
        screenshot(adb, serial, before)
        count = qa.logs(adb, serial).count(enabled_marker)
        controller.key(controller.A, "nes-enable-qualification-cheat", hold=0.08)
        enabled_log = _wait_log_count(adb, serial, enabled_marker, count)
        known_enabled = True
        time.sleep(0.20)
        screenshot(adb, serial, enabled)
        controller.key(controller.A, "nes-disable-qualification-cheat", hold=0.08)
        final_log = _wait_log_count(
            adb, serial, disabled_marker, enabled_log.count(disabled_marker)
        )
        known_enabled = False
        time.sleep(0.20)
        screenshot(adb, serial, disabled)
    finally:
        active_failure = sys.exc_info()[1]
        cleanup_failures: list[str] = []
        if panel_open:
            try:
                observed_state = output / f"{prefix}-nes-cheat-finally-observed.png"
                screenshot(adb, serial, observed_state)
                # Never rely on the optimistic state transition around a
                # callback marker: an apply may have changed pixels even when
                # the marker wait itself timed out.
                known_enabled = red_border(observed_state)
            except Exception as error:
                cleanup_failures.append(
                    f"could not observe current cheat effect before cleanup: {error}"
                )
        if panel_open and known_enabled:
            try:
                count = qa.logs(adb, serial).count(disabled_marker)
                controller.key(controller.A, "nes-finally-disable-cheat", hold=0.08)
                final_log = _wait_log_count(
                    adb, serial, disabled_marker, count, timeout=3.0
                )
                time.sleep(0.20)
                cleanup_state = output / f"{prefix}-nes-cheat-cleanup-disabled.png"
                screenshot(adb, serial, cleanup_state)
                if red_border(cleanup_state):
                    raise RuntimeError(
                        "NES cheat cleanup marker arrived but red effect remained"
                    )
                known_enabled = False
            except Exception as error:
                cleanup_failures.append(f"could not disable persisted cheat: {error}")
        if panel_open:
            try:
                controller.key(
                    controller.B, "nes-finally-close-cheats-panel", hold=0.08
                )
            except Exception as error:
                cleanup_failures.append(f"could not close Cheats panel: {error}")
        if cleanup_failures:
            message = "NES cheat cleanup failed: " + "; ".join(cleanup_failures)
            if active_failure is not None:
                active_failure.add_note(message)
            else:
                raise RuntimeError(message)
    result = nes_qa.analyze_cheat(before, enabled, disabled, final_log)
    return {"result": result, "panelOcr": panel_text,
            "panelProof": panel_proof,
            "initialEnabled": initial_enabled,
            "exactCatalogId": "qualification-red-border",
            "exactCode": "6000:3F",
            "paths": {"before": str(before), "enabled": str(enabled),
                      "disabled": str(disabled), "initial": str(initial),
                      "panel": str(panel)}}


def relaunch_nes_fixture(adb: Path, serial: str,
                         controller: PhysicalController, case: SystemCase,
                         menu: Path, library_identity: dict[str, object],
                         output: Path, prefix: str) -> dict[str, object]:
    baseline_log = qa.logs(adb, serial)
    route_baseline = len(ROUTE.findall(baseline_log))
    restore_marker = "Quick Resume restored engine=mesen system=nes"
    restore_baseline = baseline_log.count(restore_marker)
    controller.key(controller.A, "physical-a-relaunch-nes-fixture", hold=0.055)
    engine, system = wait_new_route(adb, serial, route_baseline, case)
    if (engine, system) != ("mesen", "nes"):
        raise RuntimeError(f"NES semantic relaunch routed to {engine}/{system}")
    if not same_identity(library_identity, identity(adb, serial)):
        raise RuntimeError("NES semantic relaunch changed Activity/task/PID")
    presented_path = output / f"{prefix}-presented.png"
    presented = wait_presented_frame(
        adb, serial, engine, system, menu, presented_path
    )
    restored_log = _wait_log_count(
        adb, serial, restore_marker, restore_baseline, timeout=8.0
    )
    return {"engine": engine, "system": system, "presented": presented,
            "presentedPath": str(presented_path), "log": restored_log}


def nes_resume_evidence(adb: Path, serial: str,
                        controller: PhysicalController, case: SystemCase,
                        menu: Path, library_identity: dict[str, object],
                        output: Path, prefix: str,
                        expected_title: str) -> dict[str, object]:
    # First Stop is intentionally taken while the broad fixture field is
    # moving. Its video proves continuous gameplay all the way to the <=500ms
    # return. The second Stop saves an explicitly frozen semantic state.
    moving_return = stop_and_return(
        adb, serial, controller, case, "mesen", "nes", menu,
        library_identity, output, prefix + "-moving-stop", expected_title,
    )
    relaunch_nes_fixture(
        adb, serial, controller, case, menu, library_identity,
        output, prefix + "-resume-stage-1",
    )
    controller.key(controller.START, "nes-freeze-semantic-state", hold=0.08)
    time.sleep(0.65)
    before = output / f"{prefix}-nes-resume-before.png"
    screenshot(adb, serial, before)
    semantic_return = stop_and_return(
        adb, serial, controller, case, "mesen", "nes", menu,
        library_identity, output, prefix + "-semantic-save", expected_title,
    )
    relaunched = relaunch_nes_fixture(
        adb, serial, controller, case, menu, library_identity,
        output, prefix + "-resume-stage-2",
    )
    after = output / f"{prefix}-nes-resume-after.png"
    screenshot(adb, serial, after)
    result = nes_qa.analyze_resume(before, after, str(relaunched["log"]))
    final_return = stop_and_return(
        adb, serial, controller, case, "mesen", "nes", menu,
        library_identity, output, prefix + "-semantic-exit", expected_title,
    )
    return {"result": result, "movingReturn": moving_return,
            "semanticSaveReturn": semantic_return, "finalReturn": final_return,
            "paths": {"before": str(before), "after": str(after)}}


def nes_real_title_resume_evidence(
        adb: Path, serial: str, controller: PhysicalController,
        case: SystemCase, menu: Path, library_identity: dict[str, object],
        output: Path, prefix: str, expected_title: str) -> dict[str, object]:
    """Prove Stop and exact Quick Resume for a sampled, non-fixture NES title.

    The first Stop remains a normal running-game latency trial.  After that
    return the same title is relaunched and Start must produce a genuinely
    stable in-game pause state; two exact semantic signatures reject games for
    which Start does not pause.  That stable guest state is then saved,
    relaunched, and compared exactly before the final return to the library.
    """
    moving_return = stop_and_return(
        adb, serial, controller, case, "mesen", "nes", menu,
        library_identity, output, prefix + "-moving-stop", expected_title,
    )
    relaunch_nes_fixture(
        adb, serial, controller, case, menu, library_identity,
        output, prefix + "-resume-stage-1",
    )
    controller.key(controller.START, "nes-real-title-enter-pause", hold=0.08)
    time.sleep(0.65)
    stability_a = output / f"{prefix}-nes-real-pause-a.png"
    stability_b = output / f"{prefix}-nes-real-pause-b.png"
    screenshot(adb, serial, stability_a)
    time.sleep(0.65)
    screenshot(adb, serial, stability_b)
    if (nes_qa.semantic_state_signature(stability_a) !=
            nes_qa.semantic_state_signature(stability_b)):
        raise RuntimeError(
            "sampled real NES title did not reach an exact stable Start pause"
        )
    semantic_return = stop_and_return(
        adb, serial, controller, case, "mesen", "nes", menu,
        library_identity, output, prefix + "-semantic-save", expected_title,
    )
    relaunched = relaunch_nes_fixture(
        adb, serial, controller, case, menu, library_identity,
        output, prefix + "-resume-stage-2",
    )
    restored = output / f"{prefix}-nes-real-resume-after.png"
    screenshot(adb, serial, restored)
    result = nes_qa.analyze_resume(stability_b, restored, str(relaunched["log"]))
    final_return = stop_and_return(
        adb, serial, controller, case, "mesen", "nes", menu,
        library_identity, output, prefix + "-semantic-exit", expected_title,
    )
    return {"result": result, "movingReturn": moving_return,
            "semanticSaveReturn": semantic_return, "finalReturn": final_return,
            "sampledRealTitle": True,
            "paths": {"before": str(stability_b), "after": str(restored),
                      "stabilityProbe": str(stability_a)}}


def nes_controller_identity(adb: Path, serial: str,
                            controller: PhysicalController, output: Path,
                            prefix: str) -> dict[str, object]:
    devices = qa.adb(adb, serial, "shell", "cat",
                     "/proc/bus/input/devices").stdout
    handler = Path(controller.node).name
    blocks = [block for block in re.split(r"\n\s*\n", devices)
              if re.search(rf"\b{re.escape(handler)}\b", block)]
    if len(blocks) != 1:
        raise RuntimeError("NES controller identity cannot bind one input-device block")
    block = blocks[0]
    name_match = re.search(r'N:\s+Name="([^"]+)"', block)
    id_match = re.search(r"Vendor=([0-9a-f]+) Product=([0-9a-f]+)", block, re.I)
    if name_match is None or id_match is None:
        raise RuntimeError("NES controller block omits name/VID/PID")
    description = output / f"{prefix}-nes-controller-description.txt"
    getevent = qa.adb(adb, serial, "shell", "getevent", "-lp",
                      controller.node).stdout
    description.write_text(block + "\n\n" + getevent, encoding="utf-8")
    flip = qa.adb(adb, serial, "shell", "settings", "get", "system",
                  "flip_button_layout").stdout.strip()
    no_create = qa.adb(adb, serial, "shell", "settings", "get", "system",
                       "no_create_gamepad_button_layout").stdout.strip()
    vid, pid = int(id_match.group(1), 16), int(id_match.group(2), 16)
    keylayout_name = f"Vendor_{vid:04x}_Product_{pid:04x}.kl"
    candidates = (f"/system/usr/keylayout/{keylayout_name}",
                  f"/vendor/usr/keylayout/{keylayout_name}")
    readable = []
    for candidate in candidates:
        probe = qa.adb(adb, serial, "shell", "test", "-r", candidate,
                       check=False)
        if probe.returncode == 0:
            readable.append(candidate)
    if not readable:
        raise RuntimeError(
            "NES controller vendor keylayout has no readable candidate"
        )
    if len(readable) != 1:
        raise RuntimeError("NES controller vendor keylayout is ambiguous")
    keylayout_path = readable[0]
    keylayout_result = qa.adb(
        adb, serial, "exec-out", "cat", keylayout_path, check=False
    )
    if keylayout_result.returncode != 0:
        raise RuntimeError(
            "NES controller vendor keylayout became unreadable after its probe"
        )
    keylayout_text = keylayout_result.stdout
    substantive = [line.strip() for line in keylayout_text.splitlines()
                   if line.strip() and not line.lstrip().startswith("#")]
    directive = re.compile(r"^(?:key|axis|led|sensor)\s+", re.I)
    key_definition = re.compile(
        r"^key\s+(?:usage\s+)?(?:0x[0-9a-f]+|\d+)\s+"
        r"[A-Z0-9_]+(?:\s+[A-Z0-9_]+)*$", re.I,
    )
    if (not keylayout_text.strip() or "\x00" in keylayout_text or
            not substantive or any(not directive.match(line)
                                   for line in substantive) or
            not any(key_definition.fullmatch(line) for line in substantive)):
        raise RuntimeError(
            "NES controller vendor keylayout content is empty or malformed"
        )
    keylayout = output / f"{prefix}-nes-controller-keylayout.kl"
    keylayout.write_text(keylayout_text, encoding="utf-8")
    settings_path = output / f"{prefix}-nes-controller-settings.json"
    settings = {"flip_button_layout": flip,
                "no_create_gamepad_button_layout": no_create,
                "style": "Odin Style" if (flip, no_create, pid) == ("0", "0", 0x0111)
                else "unqualified"}
    settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    return {**settings, "eventNode": controller.node,
            "name": name_match.group(1), "vid": vid, "pid": pid,
            "keylayoutPath": keylayout_path,
            "keylayoutSha256": sha256_file(keylayout),
            "paths": {"description": str(description),
                      "keylayout": str(keylayout), "settings": str(settings_path)}}


def write_nes_qualification_manifest(
        adb: Path, serial: str, controller: PhysicalController, apk: Path,
        output: Path, prefix: str, rom_identity: dict[str, str],
        core_sha256: str, expected_apk_sha256: str, menu: Path,
        launch_video: dict[str, object], launch_clock: dict[str, object],
        fixture: dict[str, object], framegen: dict[str, object],
        cheat: dict[str, object], resume: dict[str, object],
        log_path: Path, kernel_trace_path: Optional[Path], pid: int) -> dict[str, object]:
    candidate = output / f"{prefix}-nes-candidate.apk"
    candidate.write_bytes(apk.read_bytes())
    rom = output / f"{prefix}-nes-qualification-rom.nes"
    pulled = subprocess.run(
        [str(adb), "-s", serial, "pull", str(rom_identity["path"]), str(rom)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20,
    )
    if pulled.returncode != 0 or not rom.is_file():
        raise RuntimeError("could not pull exact NES qualification ROM")
    core = output / f"{prefix}-nes-core-mesen.so"
    with zipfile.ZipFile(apk) as archive:
        core.write_bytes(archive.read("lib/arm64-v8a/liblucent_core_mesen.so"))
    if (sha256_file(rom) != rom_identity["sha256"] or
            sha256_file(core) != core_sha256 or
            sha256_file(candidate) != expected_apk_sha256):
        raise RuntimeError("NES raw identity artifacts differ from launch identity")
    controller_identity = nes_controller_identity(
        adb, serial, controller, output, prefix
    )
    artifacts: dict[str, Path] = {}

    def bind(role: str, value: object) -> None:
        path = Path(str(value))
        if not path.is_file() or path.parent.resolve() != output.resolve():
            raise RuntimeError(f"NES artifact {role} is absent/outside evidence root: {path}")
        if role in artifacts:
            raise RuntimeError(f"duplicate NES artifact role: {role}")
        artifacts[role] = path

    bind("candidate-apk", candidate)
    bind("qualification-rom", rom)
    bind("core-artifact", core)
    bind("launch-video", launch_video["videoPath"])
    bind("launch-input-trace", launch_clock["tracePath"])
    bind("launch-menu-reference", menu)
    paths = fixture["paths"]
    bind("geometry", paths["geometry"])
    bind("motion-before", paths["motionBefore"])
    bind("motion-after", paths["motionAfter"])
    bind("control-neutral", paths["controlNeutral"])
    for name, path in paths["controls"].items():
        bind(f"control-{name.lower()}", path)
    for name, path in resume["paths"].items():
        bind(f"resume-{name}", path)
    bind("cheat-before", cheat["paths"]["before"])
    bind("cheat-enabled", cheat["paths"]["enabled"])
    bind("cheat-disabled", cheat["paths"]["disabled"])
    bind("cheat-initial", cheat["paths"]["initial"])
    bind("cheat-panel", cheat["paths"]["panel"])
    bind("logcat", log_path)
    moving = resume["movingReturn"]
    bind("stop-video", moving["visibleReturnVideo"]["videoPath"])
    bind("stop-input-trace", moving["deviceStopClock"]["tracePath"])
    bind("stop-menu-reference", menu)
    bind("stop-menu-first", moving["firstMenuPath"])
    bind("stop-menu-interactive", moving["interactivePath"])
    bind("stop-menu-selection", moving["selectionPath"])
    for key, value in controller_identity["paths"].items():
        if key != "inputTrace":
            bind("controller-" + key, value)
    if kernel_trace_path is None:
        raise RuntimeError("NES continuous kernel input trace was not finalized")
    bind("controller-input-trace", kernel_trace_path)
    bind("framegen-log", framegen["log"])
    bind("framegen-tier-input-schedule", framegen["schedule"])
    for name, entry in framegen["segments"].items():
        bind(f"framegen-{name}-qualification", entry["qualification"])
        bind(f"framegen-{name}-latency", entry["latency"])
        bind(f"framegen-{name}-report", entry["report"])
    launch_frames = []
    for index, item in enumerate(launch_video["frames"]):
        role = f"launch-frame-{index:06d}"
        bind(role, item["path"])
        launch_frames.append({"role": role, "index": int(item["index"]),
                              "elapsedNs": int(item["elapsedNs"])})
    stop_frames = []
    for index, item in enumerate(moving["frameSimilarities"]):
        role = f"stop-frame-{index:06d}"
        bind(role, item["path"])
        stop_frames.append({"role": role, "index": int(item["frameIndex"]),
                            "elapsedNs": int(item["elapsedNs"])})
    inventory = [{"role": role, "path": path.name,
                  "sha256": sha256_file(path), "bytes": path.stat().st_size}
                 for role, path in sorted(artifacts.items())]
    manifest = {
        "schemaVersion": 1, "profile": nes_qa.PROFILE,
        "identity": {"engine": "mesen", "system": "nes",
                     "gameTitle": "Lucent Callback Test",
                     "pid": pid,
                     "apkSha256": expected_apk_sha256,
                     "installedApkSha256": expected_apk_sha256,
                     "romSha256": rom_identity["sha256"],
                     "coreArtifactSha256": core_sha256},
        "artifacts": inventory,
        "measurements": {
            "motion": {"spanMs": int(fixture["motion"]["spanMs"])},
            "cheat": {"initialEnabled": bool(cheat["initialEnabled"]),
                      "panelOcr": str(cheat["panelOcr"])},
            "launch": {"inputLowerBoundElapsedNs":
                       int(launch_clock["inputLowerBoundElapsedNs"]),
                       "frames": launch_frames},
            "stop": {"thresholdElapsedNs": int(
                moving["deviceStopClock"]["thresholdLowerBoundElapsedNs"]),
                     "frames": stop_frames,
                     "selectionOcr": moving["selectionOcr"],
                     "immediateInputChangedPixels":
                     moving["immediateInputChangedPixels"]},
            "controller": {key: value for key, value in controller_identity.items()
                           if key != "paths"},
            "logcatCapture": {"pid": pid, "arguments":
                              ["logcat", "--pid", str(pid), "-v", "threadtime"]},
            "frameGeneration": {
                "calibrationOnly": True,
                "contentQualificationEligible": False,
                "contentQualityPassed": bool(framegen["contentQualityPassed"]),
                "segmentCount": len(framegen["segments"]),
            },
        },
    }
    manifest_path = output / f"{prefix}-nes-qualification-artifacts.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    report = nes_qa.verify_manifest(manifest_path)
    report_path = output / f"{prefix}-nes-qualification-offline-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    if not report["passed"]:
        raise RuntimeError("offline NES qualification failed: " +
                           "; ".join(report["errors"]))
    return {"manifest": str(manifest_path), "report": str(report_path),
            "result": report}


def write_real_nes_title_manifest(
        output: Path, prefix: str, title: str, pid: int,
        expected_apk_sha256: str, rom_identity: dict[str, str],
        core_sha256: str, controller_node: str,
        launch_video: dict[str, object], launch_clock: dict[str, object],
        gameplay_frame: Path, runtime_geometry: dict[str, object],
        framegen: dict[str, object], resume: dict[str, object],
        log_path: Path,
        readiness: dict[str, object],
        kernel_trace: Optional[Path]) -> dict[str, object]:
    """Hash and independently re-open a sampled owner's NES-title evidence.

    Fixture-only controls/audio/cheats remain in the stronger qualification
    profile. Every sampled owner title nevertheless gets raw launch, exact
    presentation geometry, framegen, moving Stop, and semantic resume closure.
    """
    moving = resume["movingReturn"]
    roles: dict[str, Path] = {
        "launch-video": Path(str(launch_video["videoPath"])),
        "launch-input": Path(str(launch_clock["tracePath"])),
        "gameplay-frame": gameplay_frame,
        "logcat": log_path,
        "framegen-log": Path(str(framegen["log"])),
        "framegen-latency": Path(str(framegen["latency"])),
        "framegen-qualification": Path(str(framegen["qualificationManifest"])),
        "framegen-report": Path(str(framegen["reportPath"])),
        "resume-before": Path(str(resume["paths"]["before"])),
        "resume-after": Path(str(resume["paths"]["after"])),
        "resume-stability": Path(str(resume["paths"]["stabilityProbe"])),
        "stop-video": Path(str(moving["visibleReturnVideo"]["videoPath"])),
        "stop-input": Path(str(moving["deviceStopClock"]["tracePath"])),
        "gameplay-readiness-report": Path(str(readiness["reportPath"])),
    }
    if kernel_trace is None:
        raise RuntimeError("real NES readiness lacks its physical input trace")
    roles["controller-input-trace"] = kernel_trace
    for index, item in enumerate(launch_video["frames"]):
        roles[f"launch-frame-{index:06d}"] = Path(str(item["path"]))
    for index, item in enumerate(moving["frameSimilarities"]):
        roles[f"stop-frame-{index:06d}"] = Path(str(item["path"]))
    readiness_frames = [Path(str(item["path"]))
                        for item in readiness["gameplay"]["frames"]]
    for index, path in enumerate(readiness_frames):
        roles[f"gameplay-readiness-frame-{index:02d}"] = path
    for attempt in readiness.get("attempts", []):
        sequence = int(attempt["sequence"])
        for index, sample in enumerate(attempt.get("samples", [])):
            roles[f"gameplay-readiness-attempt-{sequence:02d}-{index:02d}"] = \
                Path(str(sample["path"]))
    for index, action in enumerate(readiness.get("actions", [])):
        trace_path = action.get("actionTracePath")
        if not isinstance(trace_path, str):
            raise RuntimeError("real NES activation lacks action-specific raw input")
        roles[f"gameplay-readiness-action-{index:02d}"] = Path(trace_path)
    proof_spec = framegen.get("realNesGameplayProof")
    if not isinstance(proof_spec, dict):
        raise RuntimeError("real NES framegen report lacks gameplay persistence")
    proof_frames = [Path(str(item["path"]))
                    for item in proof_spec.get("frames", [])]
    for index, path in enumerate(proof_frames):
        roles[f"gameplay-proof-frame-{index:02d}"] = path
    for role, path in roles.items():
        if not path.is_file() or path.parent.resolve() != output.resolve():
            raise RuntimeError(f"real NES evidence {role} is absent/outside output")

    launch_input = nes_qa.analyze_device_clock_input(
        roles["launch-input"], action="launch-a", key_code=PhysicalController.A,
        expected_node=controller_node,
    )
    launch_frames = [nes_qa.TimedImage(
        int(item["index"]), int(item["elapsedNs"]), Path(str(item["path"])))
        for item in launch_video["frames"]]
    nes_qa.verify_video_frame_binding(
        roles["launch-video"], launch_frames,
        int(launch_input["originElapsedNs"]), launch=True,
    )
    stop_input = nes_qa.analyze_device_clock_input(
        roles["stop-input"], action="held-stop", key_code=PhysicalController.STOP,
        expected_node=controller_node,
    )
    stop_frames = [nes_qa.TimedImage(
        int(item["frameIndex"]), int(item["elapsedNs"]), Path(str(item["path"])))
        for item in moving["frameSimilarities"]]
    nes_qa.verify_video_frame_binding(
        roles["stop-video"], stop_frames,
        int(stop_input["originElapsedNs"]), launch=False,
    )
    semantic = nes_qa.analyze_resume(
        roles["resume-before"], roles["resume-after"],
        log_path.read_text(encoding="utf-8", errors="replace"),
    )
    if not runtime_geometry.get("fullHeight") or not framegen.get("passed"):
        raise RuntimeError("real NES geometry/framegen summary is not qualified")
    readiness_recomputed = analyze_real_nes_gameplay_frames(
        readiness_frames, title, minimum_changed_pairs=5
    )
    proof_recomputed = analyze_real_nes_gameplay_frames(proof_frames, title)
    health_spec = proof_spec.get("health")
    if not isinstance(health_spec, dict):
        raise RuntimeError("real NES proof lacks bound HEALTH-window evidence")
    framegen_records = _framegen_health_records(
        roles["framegen-log"].read_text(encoding="utf-8", errors="replace"),
        "primary", 0,
    )
    baselines = [record for record in framegen_records
                 if int(record["window_end_ns"]) ==
                 int(health_spec.get("baselineWindowEndNs", -1)) and
                 int(record["pid"]) == int(health_spec.get("pid", -1)) and
                 int(record["generator"]) ==
                 int(health_spec.get("generator", -1))]
    if len(baselines) != 1:
        raise RuntimeError("real NES proof HEALTH baseline is not raw-log bound")
    health_recomputed = require_real_nes_proof_health(
        framegen_records, baselines[0]
    )
    if health_recomputed != health_spec:
        raise RuntimeError("real NES saved HEALTH proof differs from recomputation")
    proof_recomputed["health"] = health_recomputed
    artifacts = [{"role": role, "path": path.name,
                  "sha256": sha256_file(path), "bytes": path.stat().st_size}
                 for role, path in sorted(roles.items())]
    manifest = {
        "schemaVersion": 1, "profile": "emufusion-nes-real-title-v1",
        "identity": {"title": title, "pid": pid,
                     "apkSha256": expected_apk_sha256,
                     "romSha256": rom_identity["sha256"],
                     "coreSha256": core_sha256},
        "artifacts": artifacts,
        "recomputed": {"launchInput": launch_input, "stopInput": stop_input,
                       "geometry": runtime_geometry, "resume": semantic,
                       "gameplayReadiness": readiness_recomputed,
                       "gameplayPersistenceDuringProof": proof_recomputed,
                       "frameGenerationPassed": True},
    }
    path = output / f"{prefix}-nes-real-title-artifacts.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    verification = nes_qa.verify_real_title_manifest(path, title)
    if not verification["passed"]:
        raise RuntimeError("real NES offline title verification failed: " +
                           "; ".join(verification["errors"]))
    return {"manifest": str(path), "artifactCount": len(artifacts),
            "semanticResume": semantic, "offline": verification, "passed": True}


def write_nes_real_game_closure(
        output: Path, games: list[dict[str, object]]) -> dict[str, object]:
    """Bind all three commercial-title full frame-generation qualifications."""
    entries = []
    for title in NES_REAL_QUALIFICATION_TITLES:
        matches = [game for game in games
                   if (game.get("qualificationRole") or {}).get("realGame") is True and
                   normalize(str(game.get("expectedTitle", ""))) == normalize(title)]
        if len(matches) != 1:
            raise RuntimeError(f"NES real-game closure lacks exactly one {title}")
        game = matches[0]
        framegen = game.get("frameGeneration") or {}
        qualification = game.get("nesRealTitleQualification") or {}
        if framegen.get("passed") is not True or qualification.get("passed") is not True:
            raise RuntimeError(f"NES real-game full qualification failed for {title}")
        manifest = Path(str(qualification.get("manifest", "")))
        if not manifest.is_file() or manifest.parent.resolve() != output.resolve():
            raise RuntimeError(f"NES real-game manifest is missing for {title}")
        entries.append({"title": title, "manifest": manifest.name,
                        "sha256": sha256_file(manifest)})
    document = {"schemaVersion": 1,
                "profile": nes_qa.REAL_GAME_CLOSURE_PROFILE,
                "games": entries}
    path = output / "nes-real-game-closure.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    result = nes_qa.verify_real_game_closure(path)
    if not result["passed"]:
        raise RuntimeError("NES real-game closure failed: " +
                           "; ".join(result["errors"]))
    return {"manifest": str(path), "passed": True, "result": result}


def same_identity(expected: dict[str, object], observed: dict[str, object]) -> bool:
    keys = ("activityToken", "taskId", "packagePids")
    return all(expected.get(key) == observed.get(key) for key in keys)


def identity(adb: Path, serial: str) -> dict[str, object]:
    result = qa.strict_gameplay_identity(adb, serial)
    if not result:
        raise RuntimeError("Lucent is not the sole foreground app/task/window/process")
    return result


def go_to_cover_system(controller: PhysicalController, visible_order: list[str],
                       folder: str) -> None:
    if folder not in visible_order:
        raise RuntimeError(f"{folder} is not a visible Lucent system")
    # Force Cover, then use the mapped right-stick shortcut to enter All Systems
    # and physical B to return to Cover with All Systems selected. This is a
    # deterministic origin even though the cover rail intentionally wraps.
    controller.stick("up")
    controller.stick("left")
    controller.key(controller.B, "physical-b-return-cover", hold=0.055)
    time.sleep(0.35)
    for _ in range(visible_order.index(folder)):
        controller.key(controller.RIGHT, "dpad-right", hold=0.07)


def inject_display4_tap(adb: Path, serial: str, x: int, y: int,
                        hold_ms: int = 180) -> None:
    """Tap the Thor lower display in display-4 pixel coordinates."""
    qa.adb(adb, serial, "shell", "input", "touchscreen", "-d", "4",
           "swipe", str(x), str(y), str(x), str(y), str(hold_ms))


def inject_display4_swipe(adb: Path, serial: str, x1: int, y1: int,
                          x2: int, y2: int, hold_ms: int = 500) -> None:
    """Draw a bounded stroke in physical display-4 pixel coordinates."""
    qa.adb(adb, serial, "shell", "input", "touchscreen", "-d", "4",
           "swipe", str(x1), str(y1), str(x2), str(y2), str(hold_ms))


def inject_lower_touch(adb: Path, serial: str) -> None:
    # Touch is the one intentionally non-controller input in this black-box
    # suite: it targets the actual physical lower display and proves that
    # EmuFusion routes lower-panel interaction into the in-process emulator.
    inject_display4_tap(adb, serial, 960, 270, hold_ms=220)


def inject_lower_motion(adb: Path, serial: str, phase: int) -> None:
    """Exercise changing lower-panel UI during dual-screen interpolation proof."""
    paths = (
        (820, 300, 940, 520),
        (940, 520, 700, 700),
        (700, 700, 860, 900),
        (860, 900, 820, 300),
    )
    x1, y1, x2, y2 = paths[phase % len(paths)]
    qa.adb(adb, serial, "shell", "input", "touchscreen", "-d", "4",
           "swipe", str(x1), str(y1), str(x2), str(y2), "260")


def dual_screen_evidence(adb: Path, serial: str, case: SystemCase,
                         top_frame: Path, output: Path,
                         prefix: str) -> dict[str, object]:
    token = secondary_token(adb, serial)
    first = output / f"{prefix}-lower-1.png"
    second = output / f"{prefix}-lower-2.png"
    first_metrics = screenshot(adb, serial, first, token)
    time.sleep(0.45)
    second_metrics = screenshot(adb, serial, second, token)
    delta = changed_pixels(first, second, threshold=10)
    top_lower_delta = changed_pixels(top_frame, first, threshold=10)
    touch_delta = 0
    touch_frames: list[dict[str, object]] = []
    if case.dual_screen:
        if not first_metrics["visible"] or not second_metrics["visible"]:
            raise RuntimeError(f"{case.folder} did not render on the Thor lower display")
        # A static pause/title frame is legitimate, so motion is evidence but
        # not the sole acceptance criterion. The private display-4 EmuFusion window
        # and nontrivial lower pixels are mandatory.
        state = qa.strict_gameplay_identity(adb, serial)
        if not state or state.get("previewActivityDisplay") != 4:
            raise RuntimeError(f"{case.folder} has no Lucent secondary gameplay window")
        if top_lower_delta < 3_000:
            raise RuntimeError(
                f"{case.folder} duplicated the same gameplay on both Thor displays"
            )
        if case.lower_touch:
            inject_lower_touch(adb, serial)
            for index in range(10):
                touched = output / f"{prefix}-lower-touch-{index + 1:02d}.png"
                metrics = screenshot(adb, serial, touched, token)
                candidate_delta = changed_pixels(second, touched, threshold=10)
                touch_delta = max(touch_delta, candidate_delta)
                touch_frames.append({"frame": metrics,
                                     "changedPixels": candidate_delta})
                time.sleep(0.08)
            # Hunters radar / ALBW map stay nearly static. Requiring a
            # touch-driven pixel change invents lower-screen motion and
            # smears HUD (plan deviation; nds13 sat on the Scan Visor
            # tutorial card). Dual-screen identity + primary 2x is the bar.
            if touch_delta < 800 and case.folder not in {"nds", "n3ds"}:
                raise RuntimeError(
                    f"{case.folder} lower touch produced no visible lower-screen response"
                )
    else:
        if float(first_metrics["visibleFraction"]) > 0.025:
            raise RuntimeError(
                f"single-screen {case.folder} left content on Thor's lower display"
            )
    return {"displayToken": token, "first": first_metrics,
            "second": second_metrics, "changedPixels": delta,
            "topLowerChangedPixels": top_lower_delta,
            "lowerTouchRequired": case.lower_touch,
            "lowerTouchChangedPixels": touch_delta,
            "lowerTouchFrames": touch_frames,
            "samePackageProcessAcrossDisplays": case.dual_screen,
            "requiredGameplay": case.dual_screen}


def navigate_handheld_dual_screen_to_visible_ui(
        adb: Path, serial: str, controller: PhysicalController,
        case: SystemCase, output: Path, prefix: str,
        expected_title: Optional[str] = None) -> Optional[dict[str, object]]:
    """Leave DS/3DS attract/title states before lower-panel qualification.

    Metroid Prime Hunters and A Link Between Worlds can both render a moving,
    valid top-screen attract sequence while intentionally leaving the touch
    screen black. A motion worker cannot distinguish that state from a broken
    lower-screen crop. Drive the two reviewed physical title controls in
    bounded START/A rounds and require consecutive visible display-4 frames
    before arming frame-generation proof. This is navigation, not evidence:
    the later compositor, touch-response and v5+ proof gates stay unchanged.

    Run nds-b57 (2026-09-01) handed off on Portrait of Ruin's animated KONAMI
    boot logo: two consecutive frames were both bright yet differed on
    essentially every pixel. A round is therefore accepted only when its
    frame is rendered (``lower_panel_rendered``: bright UI or legible text on
    black), the previous round's frame was rendered too, and the pair differs
    on fewer than 1500 downsampled pixels. Portrait of Ruin receives START
    only: A on its SELECT DATA screen opens slot one and resumes an old save.
    """
    if case.folder not in {"nds", "n3ds"}:
        return None
    start_only = "portraitofruin" in normalize(expected_title or "")
    token = secondary_token(adb, serial)
    observations: list[dict[str, object]] = []
    consecutive_visible = 0
    previous: Optional[Path] = None
    for round_index in range(10):
        controller.key(
            controller.START,
            f"physical-start-dual-gameplay-{round_index + 1}",
            hold=0.055,
        )
        time.sleep(0.55)
        if not start_only:
            controller.key(
                controller.A,
                f"physical-a-dual-gameplay-{round_index + 1}",
                hold=0.055,
            )
        time.sleep(0.80)
        frame = output / (
            f"{prefix}-dual-gameplay-ready-{round_index + 1:02d}.png"
        )
        metrics = screenshot(adb, serial, frame, token)
        rendered = lower_panel_rendered(frame)
        delta = (changed_pixels(previous, frame, threshold=10)
                 if previous is not None else None)
        observations.append({
            **metrics, "rendered": rendered, "changedPixels": delta,
        })
        if rendered:
            consecutive_visible += 1
            # A real game screen may animate forever (Portrait of Ruin's
            # title menu on the touch screen, run nds-b98: 5,000-7,000
            # distinct colours, 40-85/255 mean change between rounds), so
            # stability is one way to prove it is not a boot card; a rich
            # palette (boot cards and notices stay under 300 colours) is
            # the other.
            rich = int(metrics.get("distinctColors", 0) or 0) >= 2000
            if (consecutive_visible >= 2 and delta is not None and
                    (delta < 1500 or rich)):
                return {
                    "displayToken": token,
                    "physicalControls": (
                        ["START"] if start_only else ["START", "A"]
                    ),
                    "rounds": round_index + 1,
                    "consecutiveVisibleFrames": consecutive_visible,
                    "stableChangedPixels": delta,
                    "observations": observations,
                }
        else:
            consecutive_visible = 0
        previous = frame
    raise RuntimeError(
        f"{case.folder} never settled on a rendered, stable lower-screen "
        "frame (black, boot-logo or animating title/attract state) after ten "
        "bounded physical " + ("START" if start_only else "START/A") +
        " navigation rounds"
    )


# Metroid Prime Hunters, measured on Thor display-4 (1240x1080) in run nds7:
# the title lower screen is a "TOUCH TO START" banner (dark rows 494-633,
# midpoint 563) and the Alimbic crawl's SKIP glyph sits at red-text centroid
# 1193,1032. Controller START/A made that lower screen visible but never
# left the crawl; only these taps do.
NDS_HUNTERS_TOUCH_TO_START = (620, 563)
NDS_HUNTERS_SKIP = (1193, 1032)
NDS_HUNTERS_MENU_TAPS = (
    NDS_HUNTERS_TOUCH_TO_START,
    (400, 500),
    (620, 420),
    (620, 700),
    NDS_HUNTERS_SKIP,
)


def drive_nds_hunters_past_touch_menus(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str) -> dict[str, object]:
    """Thread Hunters through its touch-only title and skippable crawl.

    Run nds7 armed framegen on the DATA CONFIRMATION card / SKIP cinematic
    because START/A only satisfied the visible-lower-screen gate. Tap the
    measured title banner, then cycle the reviewed menu and SKIP hotspots
    with the two physical confirm keys so a later scene is live gameplay.
    """
    token = secondary_token(adb, serial)
    observations: list[dict[str, object]] = []
    inject_display4_tap(
        adb, serial,
        NDS_HUNTERS_TOUCH_TO_START[0], NDS_HUNTERS_TOUCH_TO_START[1],
    )
    time.sleep(1.4)
    for round_index in range(10):
        x, y = NDS_HUNTERS_MENU_TAPS[round_index % len(NDS_HUNTERS_MENU_TAPS)]
        inject_display4_tap(adb, serial, x, y)
        time.sleep(0.45)
        if round_index % 2 == 1:
            controller.key(
                controller.A if round_index % 4 == 1 else controller.START,
                f"physical-nds-hunters-confirm-{round_index + 1}",
                hold=0.055,
            )
            time.sleep(0.35)
        frame = output / f"{prefix}-nds-touch-menu-{round_index + 1:02d}.png"
        metrics = screenshot(adb, serial, frame, token)
        observations.append({
            "tap": {"x": x, "y": y},
            "frame": metrics,
        })
        time.sleep(0.70)
    return {
        "displayToken": token,
        "touchToStart": list(NDS_HUNTERS_TOUCH_TO_START),
        "skip": list(NDS_HUNTERS_SKIP),
        "menuTaps": [list(point) for point in NDS_HUNTERS_MENU_TAPS],
        "rounds": len(observations),
        "observations": observations,
    }


# Portrait of Ruin's first new-game setup has one mandatory stylus-only
# screen. These are measured physical Thor display-4 coordinates (1240x1080,
# rotation-aware input): a line wholly inside the emblem canvas, followed by
# the game's OK button. The stroke is setup navigation, never proof evidence.
NDS_POR_EMBLEM_STROKE = (520, 400, 700, 520)
NDS_POR_EMBLEM_OK = (620, 742)


def nds_por_name_keyboard_visible(path: Path) -> bool:
    """Recognize PoR's dense neutral-gray name keyboard without OCR."""
    image = Image.open(path).convert("RGB")
    pixels = list(image.crop((0, 180, image.width, 800)).getdata())
    neutral = sum(
        55 <= red <= 210 and abs(red - green) < 15 and
        abs(green - blue) < 15
        for red, green, blue in pixels
    )
    return neutral / max(1, len(pixels)) >= 0.35


def lower_panel_rendered(path: Path) -> bool:
    """Classify a lower-panel capture as rendered UI, including text on black.

    ``image_metrics`` requires 8 % bright samples. Run nds-b57 (2026-09-01)
    captured Portrait of Ruin's ESRB notice at 7.8 % and its "Licensed by
    Nintendo" card at 2.9 %: both are legible, deliberately rendered frames,
    yet the slot gate reported "rendered no lower UI". Accept the ordinary
    bright classification, else require a sparse but wide, multi-coloured
    bright region: at least 1.5 % of a 4-pixel lattice above the black floor,
    48 distinct colours, and a bright bounding box spanning 40 % of the width
    and 3 % of the height. A black panel, a single dot, or a thin vertical
    tear line remain unrendered.
    """
    image = Image.open(path).convert("RGB")
    metrics = image_metrics(image, path)
    # A uniform bright frame (the DS boot's white/grey flashes, run
    # nds-b98b title-settle-12/13 at one distinct colour) is not rendered
    # UI even though it is "visible"; every path needs some palette.
    if int(metrics["distinctColors"]) < 48:
        return False
    if metrics["visible"]:
        return True
    pixels = image.load()
    columns = range(0, image.width, 4)
    rows = range(0, image.height, 4)
    bright = [
        (x, y) for y in rows for x in columns if max(pixels[x, y]) >= 18
    ]
    samples = max(1, len(columns) * len(rows))
    if (len(bright) < 0.015 * samples or
            int(metrics["distinctColors"]) < 48):
        return False
    xs = [x for x, _ in bright]
    ys = [y for _, y in bright]
    return ((max(xs) - min(xs)) >= 0.40 * image.width and
            (max(ys) - min(ys)) >= 0.03 * image.height)


def nds_por_data_screen_visible(path: Path) -> bool:
    """Detect PoR's data screen by its column of six grey slot boxes.

    On the 1240x1080 lower capture the boxes occupy x = 7.5-17.5 % and
    y = 10-60 % (run nds-b98b slot-poll-01: 87k grey pixels, 60 % of them
    inside that column, the rest of the screen dark red).  The title menu
    has far more grey (the moon, 211k pixels) spread across 12-40 % of the
    width, so a large grey share confined to the left column is the
    discriminator.  Grey means all channels in [110, 235] within 30 of each
    other.
    """
    image = Image.open(path).convert("RGB")
    pixels = image.load()
    x_lo, x_hi = round(image.width * 0.05), round(image.width * 0.20)
    grey_total = grey_column = 0
    for y in range(0, image.height, 3):
        for x in range(0, image.width, 3):
            r, g, b = pixels[x, y]
            if (110 <= r <= 235 and 110 <= g <= 235 and 110 <= b <= 235 and
                    abs(r - g) < 30 and abs(g - b) < 30):
                grey_total += 1
                if x_lo <= x < x_hi:
                    grey_column += 1
    # 87k grey pixels at 1240x1080 sampled every third pixel is about 9.7k.
    return grey_total >= 1500 and grey_column / grey_total >= 0.55


def nds_por_dialogue_visible(path: Path) -> bool:
    """Detect PoR's full-width gold dialogue divider on the lower panel."""
    image = Image.open(path).convert("RGB")
    for y in range(round(image.height * 0.57), round(image.height * 0.65)):
        row = [image.getpixel((x, y)) for x in range(image.width)]
        gold = sum(
            red > 100 and green > 70 and blue < 90 and red > green * 1.05
            for red, green, blue in row
        )
        if gold / max(1, len(row)) >= 0.90:
            return True
    return False


NDS_POR_RESET_MARKER = "Reset applied engine=melonds-ds"


def _nds_por_settle_lower_panel(
        adb: Path, serial: str, token: str, output: Path, prefix: str,
        state: str, observations: list[dict[str, object]],
        timeout: float = 45.0, interval: float = 0.5) -> dict[str, object]:
    """Poll display 4 until two consecutive frames are rendered and static.

    Boot logos after a core reset are either black on the lower panel or
    animate (the KONAMI card differs on ~100 % of pixels between captures);
    the title's lower screen is the first pair of frames that is rendered
    (``lower_panel_rendered``) AND differs on fewer than 1500 downsampled
    pixels. The poll is hard-bounded so a stuck boot cannot hold the OLED.
    """
    deadline = time.monotonic() + timeout
    previous: Optional[Path] = None
    previous_rendered = False
    samples = 0
    while True:
        samples += 1
        frame = output / f"{prefix}-nds-por-{state}-settle-{samples:02d}.png"
        metrics = screenshot(adb, serial, frame, token)
        rendered = lower_panel_rendered(frame)
        delta = (changed_pixels(previous, frame, threshold=10)
                 if previous is not None else None)
        observations.append({
            "state": f"{state}-settle", "sample": samples,
            "rendered": rendered, "changedPixels": delta, "frame": metrics,
        })
        rich = int(metrics.get("distinctColors", 0) or 0) >= 2000
        if (rendered and previous_rendered and delta is not None and
                (delta < 1500 or rich)):
            return {"frame": str(frame), "samples": samples,
                    "changedPixels": delta, "rich": rich}
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Portrait of Ruin lower panel never settled on a rendered "
                f"{state} frame within {timeout:.0f} s of the host reset "
                f"(samples={samples}, last={frame})"
            )
        previous = frame
        previous_rendered = rendered
        time.sleep(interval)


def drive_nds_portrait_of_ruin_new_game_setup(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str) -> dict[str, object]:
    """Leave PoR's data/name/emblem setup through reviewed real inputs.

    Runs b50b/b51/b57 (2026-09-01) inherited whatever Quick Resume snapshot
    the previous run left (a mid-save room that self-rebooted ~8 s later), so
    every slot gate measured a different game state. Entry is now
    deterministic: the host's reviewed Select+Start chord resets the core
    without deleting save data and melonDS must acknowledge it; the lower
    panel is then polled to a rendered, static title frame, START opens
    SELECT DATA, that screen is polled to stability the same way, and only
    then is A sent. Select slot six to avoid qualification's older saved
    rooms. If that slot is still empty, finish its name screen and mandatory
    stylus emblem; if it already exists, selecting it legitimately resumes
    the game and no setup touches are injected. Every transition is bounded
    and a failed emblem confirmation rejects before frame-generation proof is
    armed.
    """
    token = secondary_token(adb, serial)
    observations: list[dict[str, object]] = []

    reset_baseline = qa.logs(adb, serial).count(NDS_POR_RESET_MARKER)
    controller.chord(
        (controller.STOP, controller.START), "physical-nds-por-host-reset",
        hold=2.20,
    )
    reset_deadline = time.monotonic() + 5.0
    while qa.logs(adb, serial).count(NDS_POR_RESET_MARKER) <= reset_baseline:
        if time.monotonic() > reset_deadline:
            raise RuntimeError(
                "Portrait of Ruin host reset was not applied by melonds-ds"
            )
        time.sleep(0.25)

    title_settle = _nds_por_settle_lower_panel(
        adb, serial, token, output, prefix, "title", observations,
    )
    controller.key(controller.START, "physical-nds-por-title-start",
                   hold=0.055)
    time.sleep(0.65)
    select_data_settle = _nds_por_settle_lower_panel(
        adb, serial, token, output, prefix, "select-data", observations,
    )

    origin = output / f"{prefix}-nds-por-setup-origin.png"
    origin_metrics = screenshot(adb, serial, origin, token)
    observations.append({"state": "select-data", "frame": origin_metrics})
    if not lower_panel_rendered(origin):
        raise RuntimeError("Portrait of Ruin SELECT DATA screen is not visible")
    # A cold boot (host reset) shows the title MENU (RANKING / GAME START /
    # SHOP MODE / ...) after START; A on GAME START opens the data-MODE menu
    # (SELECT DATA / COPY DATA / DELETE DATA); A on SELECT DATA opens the
    # slot screen with its six-box column (physical explorations ds-b98x and
    # ds-b99x, 2026-09-03).  Press A until the slot column is visible, at
    # most twice; a resumed snapshot may already be on the slot screen.
    game_start_presses = 0
    for step_name in ("game-start", "select-data"):
        if origin.exists() and nds_por_data_screen_visible(origin):
            break
        controller.key(controller.A, f"physical-nds-por-{step_name}", hold=0.055)
        game_start_presses += 1
        time.sleep(0.65)
        _nds_por_settle_lower_panel(
            adb, serial, token, output, prefix, step_name, observations,
        )
        origin_metrics = screenshot(adb, serial, origin, token)
        observations.append({"state": step_name, "frame": origin_metrics})
    if origin.exists() and not nds_por_data_screen_visible(origin):
        raise RuntimeError(
            "Portrait of Ruin slot screen (slot column) did not appear after "
            "GAME START and SELECT DATA"
        )
    for slot_step in range(5):
        controller.hat(
            "down", f"physical-nds-por-select-slot-{slot_step + 2}",
            hold=0.055,
        )
        time.sleep(0.12)
    controller.key(controller.A, "physical-nds-por-open-slot-6", hold=0.055)
    time.sleep(0.90)

    # The slot list / name keyboard replaces SELECT DATA across essentially
    # the whole DS screen. Poll briefly so a marginal dark frame (b57's ESRB
    # notice measured 7.8 % bright) or one late compositor frame cannot be
    # mistaken for "no lower UI"; the two misses are reported by name.
    slot_result = output / f"{prefix}-nds-por-slot-result.png"
    slot_deadline = time.monotonic() + 3.0
    slot_samples = 0
    slot_rendered_seen = False
    slot_gate: Optional[dict[str, object]] = None
    while True:
        slot_samples += 1
        probe = output / f"{prefix}-nds-por-slot-poll-{slot_samples:02d}.png"
        probe_metrics = screenshot(adb, serial, probe, token)
        rendered = lower_panel_rendered(probe)
        delta = changed_pixels(origin, probe, threshold=10)
        slot_rendered_seen = slot_rendered_seen or rendered
        observations.append({
            "state": "slot-poll", "sample": slot_samples,
            "rendered": rendered, "changedPixels": delta,
            "frame": probe_metrics,
        })
        if rendered and delta >= 3_000:
            slot_gate = {"frame": str(probe), "samples": slot_samples,
                         "changedPixels": delta}
            break
        if time.monotonic() >= slot_deadline:
            break
        time.sleep(0.25)
    slot_metrics = screenshot(adb, serial, slot_result, token)
    observations.append({"state": "slot-result", "frame": slot_metrics})
    if slot_gate is None:
        if not slot_rendered_seen:
            raise RuntimeError(
                "Portrait of Ruin slot selection rendered no lower UI"
            )
        raise RuntimeError(
            "Portrait of Ruin lower panel rendered but did not reach the "
            "slot list / name keyboard"
        )

    new_game = nds_por_name_keyboard_visible(slot_result)
    emblem_attempts = 0
    if new_game:
        # Type the highlighted 0, move to the keyboard's OK control, and
        # confirm. This exact sequence was physically reproduced on Thor.
        controller.key(controller.A, "physical-nds-por-type-name", hold=0.055)
        controller.key(controller.START, "physical-nds-por-name-ok", hold=0.055)
        controller.key(controller.A, "physical-nds-por-confirm-name", hold=0.055)
        time.sleep(0.90)
        emblem = output / f"{prefix}-nds-por-emblem.png"
        emblem_metrics = screenshot(adb, serial, emblem, token)
        observations.append({"state": "emblem", "frame": emblem_metrics})

        confirmed = False
        for emblem_attempts in range(1, 4):
            inject_display4_swipe(
                adb, serial, *NDS_POR_EMBLEM_STROKE, hold_ms=500,
            )
            time.sleep(0.20)
            inject_display4_tap(
                adb, serial, *NDS_POR_EMBLEM_OK, hold_ms=180,
            )
            time.sleep(1.20)
            result = output / (
                f"{prefix}-nds-por-emblem-result-{emblem_attempts:02d}.png"
            )
            result_metrics = screenshot(adb, serial, result, token)
            delta = changed_pixels(emblem, result, threshold=10)
            observations.append({
                "state": "emblem-result", "attempt": emblem_attempts,
                "changedPixels": delta, "frame": result_metrics,
            })
            # The accepted transition replaces the editor across essentially
            # the whole DS screen. A failed/empty OK remains pixel-identical.
            if result_metrics["visible"] and delta >= 3_000:
                confirmed = True
                break
        if not confirmed:
            raise RuntimeError(
                "Portrait of Ruin did not accept its mandatory drawn emblem"
            )

    # PoR follows setup/resume with a long A-gated story conversation. The
    # generic motion gate previously mistook animated portraits and changing
    # text for controllable gameplay and armed proof on that dialogue. Advance
    # it rapidly but at real key edges, then require two consecutive lower-
    # screen right-movement probes with no full-width dialogue divider.
    story_presses = 0
    gameplay_observations = 0
    exit_motion = 0.0
    previous_candidate: Optional[Path] = None
    for story_presses in range(1, 401):
        controller.key(
            controller.A,
            f"physical-nds-por-advance-story-{story_presses}",
            hold=0.035,
        )
        time.sleep(0.12)
        # PoR's opening is a multi-page narration on the touch screen followed
        # by a cutscene (run nds-b99 was still on the narration after 180 A
        # presses).  START skips the cutscene; send it every 24 presses while
        # dialogue is still on screen (the loop leaves as soon as controllable
        # gameplay is observed, so START never reaches gameplay's pause menu).
        if story_presses % 24 == 0:
            controller.key(controller.START,
                           f"physical-nds-por-skip-cutscene-{story_presses}",
                           hold=0.035)
            time.sleep(0.4)
        if story_presses < 48 or story_presses % 8 != 0:
            continue
        before = output / (
            f"{prefix}-nds-por-gameplay-probe-{story_presses:03d}-a.png"
        )
        before_metrics = screenshot(adb, serial, before, token)
        if not before_metrics["visible"] or nds_por_dialogue_visible(before):
            gameplay_observations = 0
            previous_candidate = None
            continue
        controller.hat(
            "right", "physical-nds-por-gameplay-right", hold=1.2,
        )
        time.sleep(0.25)
        after = output / (
            f"{prefix}-nds-por-gameplay-probe-{story_presses:03d}-b.png"
        )
        after_metrics = screenshot(adb, serial, after, token)
        if not after_metrics["visible"] or nds_por_dialogue_visible(after):
            gameplay_observations = 0
            previous_candidate = None
            continue
        exit_motion = mean_absolute_difference(before, after)
        if exit_motion < 0.5:
            gameplay_observations = 0
            previous_candidate = None
            continue
        gameplay_observations += 1
        previous_candidate = after
        observations.append({
            "state": "controllable-gameplay", "storyPresses": story_presses,
            "motionMeanDiff": exit_motion, "frame": after_metrics,
        })
        if gameplay_observations >= 2:
            break
    if gameplay_observations < 2 or previous_candidate is None:
        raise RuntimeError(
            "Portrait of Ruin did not reach dialogue-free controllable gameplay"
        )

    return {
        "displayToken": token,
        "hostActions": ["select-start-core-reset"],
        "resetMarker": NDS_POR_RESET_MARKER,
        "titleSettle": title_settle,
        "selectDataSettle": select_data_settle,
        "slotGate": slot_gate,
        "selectedSlot": 6,
        "newGameSetup": new_game,
        "emblemStroke": list(NDS_POR_EMBLEM_STROKE) if new_game else None,
        "emblemOk": list(NDS_POR_EMBLEM_OK) if new_game else None,
        "emblemAttempts": emblem_attempts,
        "storyPresses": story_presses,
        "consecutiveGameplayObservations": gameplay_observations,
        "exitMotionMeanDiff": exit_motion,
        "gameplayFrame": str(previous_candidate),
        "observations": observations,
    }


def flicker_evidence(adb: Path, serial: str, output: Path,
                     prefix: str) -> dict[str, object]:
    frames = []
    complete = 0
    for index in range(24):
        path = output / f"{prefix}-flicker-{index + 1:02d}.png"
        metrics = screenshot(adb, serial, path)
        frames.append(metrics)
        if metrics["visible"] and float(metrics["visibleFraction"]) >= 0.20:
            complete += 1
        time.sleep(0.09 if index % 3 else 0.14)
    if complete != len(frames):
        raise RuntimeError(
            f"incomplete/flickering gameplay frames: {complete}/{len(frames)}"
        )
    return {"captured": len(frames), "complete": complete, "frames": frames}


def runtime_checkpoint_outcome(log_before: str, current_log: str,
                               engine: str, system: str,
                               commit_baseline: int,
                               quarantine_baseline: int,
                               save_failure_baseline: int = 0,
                               visible_failure_baseline: int = 0) -> Optional[str]:
    """Classify the exact post-Stop runtime-state disposition.

    A production engine that explicitly cold-booted with runtime-state restore
    quarantined must not subsequently write an unqualified Quick Resume state.
    For that engine the matching post-Stop skip marker is the successful,
    fail-closed outcome. Engines that did not declare quarantine still require
    the ordinary committed marker.
    """
    commit_marker = f"Quick Resume committed engine={engine} system={system}"
    if current_log.count(commit_marker) > commit_baseline:
        return "committed"
    cold_boot_marker = (
        f"Runtime state restore is quarantined; cold booting engine={engine} "
        "marker=state-restore-quarantined"
    )
    skipped_marker = (
        f"Skipped unqualified runtime-state checkpoint engine={engine} "
        "marker=state-restore-quarantined"
    )
    if (cold_boot_marker in log_before and
            current_log.count(skipped_marker) > quarantine_baseline):
        return "quarantined"
    # The library is intentionally revealed before an asynchronous checkpoint
    # finishes. A failed save is still a completed, fail-closed disposition
    # when (and only when) the exact engine reports that it did not replace the
    # prior verified state and the in-window host reports that the matching
    # failure was surfaced after return. Requiring both post-baseline markers
    # prevents a stale or swallowed save exception from satisfying QA.
    save_failure_marker = (
        f"Quick Resume was not updated for {engine} marker=save-failure"
    )
    visible_failure_marker = (
        "Background exit checkpoint failure shown in library "
        f"engine={engine} system={system} marker=exit-save-failure-visible"
    )
    if (current_log.count(save_failure_marker) > save_failure_baseline and
            current_log.count(visible_failure_marker) >
            visible_failure_baseline):
        return "failed-visible"
    # An engine that declared no Quick Resume capability at adapter-ready can
    # never write a checkpoint; its completed fail-closed disposition is that
    # nothing was written. The declaration is engine-owned (Cemu reports
    # quickResume=false, the first such engine through this gate,
    # 2026-08-16), and the commit count staying at baseline proves nothing
    # was written anyway.
    unsupported_marker = (
        f"Adapter ready engine={engine} system={system} quickResume=false"
    )
    if (unsupported_marker in current_log and
            current_log.count(commit_marker) == commit_baseline):
        return "unsupported"
    return None


def stop_and_return(adb: Path, serial: str, controller: PhysicalController,
                    case: SystemCase, engine: str, system: str,
                    menu_reference: Path, before_identity: dict[str, object],
                    output: Path, prefix: str,
                    expected_title: Optional[str] = None) -> dict[str, object]:
    log_before = qa.logs(adb, serial)
    commit_marker = f"Quick Resume committed engine={engine} system={system}"
    commit_baseline = log_before.count(commit_marker)
    quarantine_marker = (
        f"Skipped unqualified runtime-state checkpoint engine={engine} "
        "marker=state-restore-quarantined"
    )
    quarantine_baseline = log_before.count(quarantine_marker)
    save_failure_marker = (
        f"Quick Resume was not updated for {engine} marker=save-failure"
    )
    visible_failure_marker = (
        "Background exit checkpoint failure shown in library "
        f"engine={engine} system={system} marker=exit-save-failure-visible"
    )
    save_failure_baseline = log_before.count(save_failure_marker)
    visible_failure_baseline = log_before.count(visible_failure_marker)
    return_baseline = len(RETURN.findall(log_before))
    recorder, remote_video = begin_visible_return_recording(
        adb, serial, prefix
    )
    try:
        stop_clock = inject_held_stop_device_clocked(
            adb, serial, controller, output, prefix
        )
        video_report, first_menu_path, similarities, interstitial = \
            finish_visible_return_recording(
                adb, serial, recorder, remote_video, output, prefix,
                int(stop_clock["thresholdLowerBoundElapsedNs"]), menu_reference,
                expected_title if case.folder == "nes" else None,
            )
    except Exception:
        if recorder.poll() is None:
            recorder.kill()
            recorder.communicate(timeout=2.0)
        # Remove only the uniquely named QA recording.  A partially finalized
        # file is not evidence and must not be mistaken for one on a rerun.
        qa.adb(adb, serial, "shell", "rm", "-f", remote_video)
        raise

    after_log = qa.logs(adb, serial)
    returned = RETURN.findall(after_log)
    if len(returned) <= return_baseline:
        raise RuntimeError("physical Stop did not log an immediate in-window return")
    returned_engine, returned_system, internal_latency = returned[-1]
    if normalize(returned_engine) != normalize(engine) or normalize(returned_system) != normalize(system):
        raise RuntimeError("physical Stop returned a different engine/system session")

    visible_latency = int(video_report["visibleReturnLatencyUpperBoundMs"])
    if visible_latency > 500 or int(internal_latency) > 500:
        raise RuntimeError(
            f"Stop return exceeded 500 ms: visible={visible_latency}, internal={internal_latency}"
        )
    returned_identity = identity(adb, serial)
    if not same_identity(before_identity, returned_identity):
        raise RuntimeError("Stop return replaced Lucent's Activity/task/PID")

    # A confirmed physical menu move after the first restored frame proves an
    # input-blocking splash is not merely hidden behind a similar screenshot.
    # The first key after the Activity transition can legitimately reach the
    # device while the library is still input-gated.  Never issue the opposite
    # "restore" key merely because wallpaper animation changed pixels: doing
    # so can move away from an already-correct selection.  Poll the selected
    # header after each bounded DOWN attempt and restore only after observing a
    # different title.
    moved = output / f"{prefix}-return-interactive.png"
    moved_ocr = ""
    input_delta = 0
    move_confirmed = False
    for move_attempt in range(3):
        if case.folder == "ps3":
            # The Thor library has one PS3 title (1/1). DOWN cannot leave
            # ICO's header (ps3-14). Y switches cover ↔ list, which is a
            # real library input the wallpaper clock cannot fake.
            controller.key(
                controller.Y,
                f"physical-y-list-view-after-stop-{move_attempt + 1}",
                hold=0.055,
            )
        else:
            controller.key(
                controller.DOWN,
                f"dpad-down-after-stop-{move_attempt + 1}",
                hold=0.04,
            )
        move_deadline = time.monotonic() + 1.25
        while time.monotonic() < move_deadline:
            screenshot(adb, serial, moved)
            input_delta = changed_pixels(first_menu_path, moved, threshold=10)
            moved_ocr = selected_header_ocr(moved)
            title_left = expected_title is None or not selected_title_matches(
                expected_title, moved_ocr)
            single_title_library = (
                case.folder == "ps3" and input_delta >= 750 and bool(moved_ocr)
            )
            if input_delta >= 750 and moved_ocr and (
                    title_left or single_title_library):
                move_confirmed = True
                break
            time.sleep(0.10)
        if move_confirmed:
            break
    if not move_confirmed:
        raise RuntimeError(
            "restored menu did not confirm physical selection movement; "
            f"changedPixels={input_delta}, OCR={moved_ocr!r}"
        )

    controller.key(controller.UP, "dpad-up-restore", hold=0.04)
    selection_frame = output / f"{prefix}-return-selection.png"
    selection_ocr = ""
    # 1.5 s intermittently expired while the row's animated preview defeated
    # every OCR pass (run 2026-08-17-wiiu4); the conditions are unchanged.
    restore_deadline = time.monotonic() + 5.0
    while time.monotonic() < restore_deadline:
        screenshot(adb, serial, selection_frame)
        selection_ocr = selected_header_ocr(selection_frame)
        if (expected_title is None or selected_title_matches(
                expected_title, selection_ocr)):
            break
        time.sleep(0.10)
    else:
        raise RuntimeError(
            "Stop returned to a different library selection; "
            f"expected={expected_title!r}, OCR={selection_ocr!r}"
        )

    checkpoint_outcome: Optional[str] = None
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        checkpoint_outcome = runtime_checkpoint_outcome(
            log_before, qa.logs(adb, serial), engine, system,
            commit_baseline, quarantine_baseline,
            save_failure_baseline, visible_failure_baseline,
        )
        if checkpoint_outcome is not None:
            break
        time.sleep(0.10)
    else:
        raise RuntimeError(
            "background runtime-state disposition did not complete"
        )
    final_log = qa.logs(adb, serial)
    # The count comparison above is the stable chronology proof. Independent
    # `logcat -d` snapshots can differ in prefix formatting and buffer length,
    # so a character offset from `log_before` is not meaningful in final_log.
    qa.assert_no_crash(final_log)
    return {
        "downMonotonicMs": stop_clock["hostDownLowerBoundMs"],
        "deviceStopClock": stop_clock,
        "visibleReturnVideo": video_report,
        "visibleReturnLatencyMs": visible_latency,
        "hostReturnLatencyMs": int(internal_latency),
        "sameActivityTaskPid": True,
        "immediateInputChangedPixels": input_delta,
        "backgroundAutosaveCommitted": checkpoint_outcome == "committed",
        "runtimeStateCheckpointQuarantined":
            checkpoint_outcome == "quarantined",
        "backgroundAutosaveFailureVisible":
            checkpoint_outcome == "failed-visible",
        "exactSelectionRestored": expected_title is None or
            selected_title_matches(expected_title, selection_ocr),
        "selectionOcr": selection_ocr,
        "firstMenuPath": str(first_menu_path),
        "interactivePath": str(moved),
        "selectionPath": str(selection_frame),
        "frameSimilarities": similarities,
        "interstitialOcr": interstitial,
    }


# The split health record (schema >= 43) carries the cadence fields on its
# "Presentation health base" line; the legacy single-line form has no token.
PS2_CADENCE_HEALTH = re.compile(
    r"Presentation health (?:base )?generator=(?P<generator>\d+) "
    r"role=primary displayId=0 .*? presents=(?P<presents>\d+) .*? "
    r"producerHz=(?P<producer_hz>[0-9.]+) "
    r"lockedFps=(?P<locked>\d+) outputFps=(?P<output>\d+)"
)

# DS games choose their own gameplay screen (Hunters top / Castlevania
# touch), so the readiness counter must see BOTH streams' windows: PoR ran
# 40->80 on the secondary while the idle top-screen map's 0-Hz rows reset
# the primary-only counter forever (run nds14, 2026-08-17).
PS2_CADENCE_HEALTH_ANY = re.compile(
    r"Presentation health (?:base )?generator=(?P<generator>\d+) "
    r"role=(?P<role>\w+) displayId=(?P<display>\d+) .*? "
    r"presents=(?P<presents>\d+) .*? "
    r"producerHz=(?P<producer_hz>[0-9.]+) "
    r"lockedFps=(?P<locked>\d+) outputFps=(?P<output>\d+)"
)


PS2_TITLE_DEPARTURE_MEAN_DIFF = 22.0
PS2_LIVE_MOTION_MEAN_DIFF = 2.0
PS2_SUSTAINED_GAMEPLAY_WINDOWS = 8

# Dense content gates that starve on a slow or low-motion scene while pacing
# remains perfect. Only these justify recollecting proof on a later scene.
CONTENT_STARVED_FRAMEGEN_FAILURES = (
    "too few genuinely changing pixels were sampled",
    "too few synthesized samples contain measurable selected motion",
    "independent vector trajectory and non-crossfade output are not correlated",
    "too few changing pixels have a confident selected motion vector",
    # Scene-dependent like the classes above: an FMV's hard cuts and
    # occlusion-heavy motion legitimately fail bidirectional validation,
    # while the same title's in-engine demo fights pass it. The 50% gate
    # itself is never weakened — a later scene is simply sampled.
    "dense bidirectional final-valid coverage is below 50 percent",
    # A load transient inside the sampled window breaks the latch lattice for
    # that window only; a later steady window presents cleanly. Persistent
    # pacing failures still fail the final attempt.
    "SurfaceFlinger did not latch at the reported output cadence",
    "SurfaceFlinger latch cadence is not a balanced panel-vsync subset",
    # On a near-static scene the honest midpoint between two identical
    # endpoints IS the endpoint (SMG1's dark drifting intro cutscene, run
    # wii4 2026-08-17). Scene-dependent like the motion classes: an engine
    # that truly fakes generation repeats endpoints on EVERY scene and
    # still fails the final attempt.
    "synthesized frames repeat a real endpoint too often",
    # The same static-scene family, observed on OoE's ornament/dialogue
    # cards (run nds10, 2026-08-17): a held frame has no motion field, its
    # sampled output doesn't change, and any synthetic between identical
    # endpoints is indistinguishable from crossfade. Real pacing/validity
    # failures (v31/v32 evidence, nonmonotonic repair) remain immediate.
    "motion field is effectively zero",
    "sampled output content does not change often enough",
    "most synthetic output is indistinguishable from fixed-pixel crossfade",
)


def _is_content_starved_framegen_failure(text: str) -> bool:
    """True when the frame-generation failure is scene-dependent.

    Two shapes qualify: the steady-tier wait timing out (a heavy combat scene
    can hold motion without an 11-second correction-free window, while a later
    calmer scene steadies), and the gate rejecting every candidate purely on
    content-starvation classes. The gate's message embeds each rejected
    candidate's failure list; the second shape requires at least one
    content-starvation class and no other failure class — a pacing, atlas,
    timer, or visible-output failure must raise immediately.
    """
    if text.startswith("timed out waiting for a current >=11-second "
                       "frame-generation steady tier"):
        return True
    if text.startswith("timed out capturing latency for a current steady "
                       "frame-generation segment"):
        return True
    # Run nds8 armed proof across the 20→50 lock upgrade after Hunters
    # entered morph-ball gameplay. The compositor snapshot then missed the
    # later settled 50→100 stretch. A later attempt on the same live scene
    # is the same class as a late steady epoch.
    if "has no latency-overlapping real >=11-second steady tier" in text:
        return True
    if "frame-generation gate needs one uniquely strongest" not in text:
        return False
    # Evaluate PER CANDIDATE, not over the pooled message: a DS title whose
    # gameplay screen content-starved mid-dialogue is retryable even while
    # the idle map screen's candidate accrues static-scene validity classes
    # (nonmonotonic repair, too few framebuffer proof samples) that are not
    # in the content set (run nds12, 2026-08-17). A retry never weakens the
    # gates — the final attempt still fails honestly.
    candidates = re.findall(r"'failures': \[([^\]]*)\]", text)
    if not candidates:
        return False
    for failures_text in candidates:
        failure_reasons = re.findall(r"'([^']+)'", failures_text)
        if not failure_reasons:
            continue
        if all(reason in CONTENT_STARVED_FRAMEGEN_FAILURES
               for reason in failure_reasons):
            return True
    return False


def screenshot_mean_abs_diff(left_path: Path, right_path: Path) -> float:
    """Mean absolute RGB difference between two screenshots, 0..255."""
    left = Image.open(left_path).convert("RGB")
    right = Image.open(right_path).convert("RGB")
    if right.size != left.size:
        right = right.resize(left.size)
    return sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3.0


PS2_PLATFORM_GREEN_FRACTION = 0.05
PS2_PLATFORM_GREEN_FRACTION_MAX = 0.45
PS2_PLATFORM_DARK_FRACTION = 0.5
# Attract-scene acceptance (Tekken 5): proof needs bright, fast full-frame
# motion for the dense vector gates. Probes two seconds apart during the
# intro FMV/demo fights measure large diffs; dark card transitions and slow
# scenes are skipped rather than sampled.
PS2_ATTRACT_MOTION_MEAN_DIFF = 6.0
PS2_ATTRACT_DARK_FRACTION_MAX = 0.6
# A full-screen cutscene fade changes every pixel (large diff, bright) but
# has no texture for the vector gates. Live scene structure is required:
# grayscale standard deviation of the probe.
PS2_SCENE_STRUCTURE_MIN_STDDEV = 35.0


def probe_gray_stddev(path: Path) -> float:
    image = Image.open(path).convert("L").resize((480, 270))
    stat = ImageStat.Stat(image)
    return float(stat.stddev[0])


def ps2_platform_signature(path: Path) -> tuple[float, float]:
    """(vivid-green fraction, dark fraction) of a screenshot, each 0..1.

    Kingdom Hearts' first playable platform is a vivid green stained-glass
    disc surrounded by black void. Physically calibrated on the Thor
    (2026-08-15): platform green ~0.17 dark ~0.61; movie/menu scenes have
    green <= 0.002; the movie's one green-lit face closeup measures green
    ~0.17 but dark only ~0.38, so the dark axis rejects it.
    """
    image = Image.open(path).convert("RGB").resize((480, 270))
    pixels = image.load()
    total = 480 * 270
    green = 0
    dark = 0
    for y in range(270):
        for x in range(480):
            r, g, b = pixels[x, y]
            if g > r * 1.25 and g > b * 1.25 and g > 60:
                green += 1
            if 0.299 * r + 0.587 * g + 0.114 * b < 40.0:
                dark += 1
    return green / total, dark / total


def ps2_platform_signature_matches(green: float, dark: float) -> bool:
    return (PS2_PLATFORM_GREEN_FRACTION <= green <=
            PS2_PLATFORM_GREEN_FRACTION_MAX and
            dark >= PS2_PLATFORM_DARK_FRACTION)


def ps2_sustained_gameplay_windows(log: str, baseline_presents: int) -> int:
    """Count trailing consecutive fresh windows on any supported stable tier.

    Reads only the compact prefix of HEALTH, which remains available even when
    a proof-off v22 diagnostic tail is logcat-truncated. Every supported tier
    (20/30/40/50/60) qualifies — Kingdom Hearts' first playable scene runs the
    30 tier and is a physically verified qualification scene (Thor,
    2026-08-15) — but the measured producer rate must actually support the
    locked tier. A fresh window whose producer falls below 90% of its locked
    tier resets the trailing count.
    """
    windows = 0
    for match in PS2_CADENCE_HEALTH.finditer(log):
        if int(match.group("presents")) <= baseline_presents:
            continue
        locked = int(match.group("locked"))
        producer_hz = float(match.group("producer_hz"))
        # Membership, not >=20: a raw pre-acquisition lock (51, 55, 111 —
        # round(measured), runs nds1-5 2026-08-17) means the tier
        # controller has NOT settled, so proof armed on it restarts the
        # dense epoch mid-capture and voids v31/v32 evidence. Only an
        # acquired supported tier is gameplay-ready.
        if locked in (20, 30, 40, 50, 60) and producer_hz >= locked * 0.9:
            windows += 1
        else:
            windows = 0
    return windows


def ps2_any_stream_gameplay_windows(log: str, baseline_presents: int) -> int:
    """Trailing tier-locked window count of the healthiest stream.

    DS titles pick their own gameplay screen; the other screen legitimately
    idles at zero unique rate. Count each (role, display) stream separately
    with the same acquired-tier membership rule and report the best trailing
    run — the layer gate still decides which stream qualifies.
    """
    trailing: dict[tuple[str, str], int] = {}
    for match in PS2_CADENCE_HEALTH_ANY.finditer(log):
        if int(match.group("presents")) <= baseline_presents:
            continue
        stream = (match.group("role"), match.group("display"))
        locked = int(match.group("locked"))
        output = int(match.group("output"))
        # An acquired tier with ACTIVE generation (output = 2x lock) is the
        # readiness signal here — the engine's own worst-second machinery
        # already vouched for sustainability. The per-window producer >=
        # 0.9*lock rule (right for PS2's steady 60) reset every 2-5 windows
        # on PoR, whose unique rate honestly swings 27-60 around a correct
        # 40 lock (run nds19: best trailing 36 in dialogue, 1-11 in live
        # gameplay). The >=11 s cadence-healthy steady segment downstream
        # still owns the actual evidence bar.
        if locked in (20, 30, 40, 50, 60) and output > locked:
            trailing[stream] = trailing.get(stream, 0) + 1
        else:
            trailing[stream] = 0
    return max(trailing.values(), default=0)


def ps2_best_gameplay_windows(log: str, baseline_presents: int) -> int:
    """Longest consecutive eligible-tier run after baseline, not the trailing one.

    Trailing count drops to zero the moment a later 15 Hz ICO window lands,
    even if the same launch already posted fourteen 20→40 windows. PS3 uses
    the peak so a collection-to-cinematic 20+ burst during entry presses
    still arms once a structured ICO frame is on screen.
    """
    windows = 0
    best = 0
    for match in PS2_CADENCE_HEALTH.finditer(log):
        if int(match.group("presents")) <= baseline_presents:
            continue
        locked = int(match.group("locked"))
        producer_hz = float(match.group("producer_hz"))
        if locked >= 20 and producer_hz >= locked * 0.9:
            windows += 1
            best = max(best, windows)
        else:
            windows = 0
    return best


def ps2_navigation_cadence_phase(log: str, baseline_presents: int) -> str:
    """Classify boot vs title-ready using fresh compact cadence prefixes.

    The historical third phase ("movie-started", a locked<=40 dip after title
    cadence) was removed after physical recalibration on the Thor
    (God of War, schema-39 checkpoint, 2026-08-15): the emulated PS2 scans out
    continuously near 60 Hz, so the unskippable opening movie holds
    lockedFps=60 on the endpoint-measurement architecture and the dip never
    occurs. Title departure is proven visually instead — see
    drive_ps2_title_past_title_menu.
    """
    consecutive_high = 0
    title_ready = False
    for match in PS2_CADENCE_HEALTH.finditer(log):
        if int(match.group("presents")) <= baseline_presents:
            continue
        locked = int(match.group("locked"))
        producer_hz = float(match.group("producer_hz"))
        # Tier protocol 2026-09-01: there is no 50 tier; a title that scans
        # near 60 but sustains 50-59 locks 40.  The producer clock still has
        # to be near the title's 60-Hz scan.
        if locked >= 40 and producer_hz >= 50.0:
            consecutive_high += 1
            if consecutive_high >= 2:
                title_ready = True
        else:
            consecutive_high = 0
    return "title-ready" if title_ready else "boot"


def drive_ps2_title_past_title_menu(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str, timeout: float = 150.0) -> dict[str, object]:
    """Wait through real boot logos until the title cadence is live.

    The qualified matrix title is Grand Theft Auto III: two Cross presses
    from the title reach a new game, and sustained held-forward street
    traversal then provides continuous bright textured full-frame motion —
    the only content class that filled a whole proof capture on PS2. The
    2026-08-15 experiments disqualified every attract/cinematic lottery:
    SotC's attract is too dark too often, Tekken 5's FMV fails
    bidirectional coverage at its hard cuts, and Kingdom Hearts' platform
    orbit leaves per-frame displacement below vector confidence. The first
    Cross is sent here at title-ready; the rest of the sequence lives in
    wait_ps2_post_cinematic_gameplay.
    """
    initial_log = qa.logs(adb, serial)
    baseline_presents = max(
        (int(match.group("presents"))
         for match in PS2_CADENCE_HEALTH.finditer(initial_log)),
        default=-1,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        log = qa.logs(adb, serial)
        if ps2_navigation_cadence_phase(log, baseline_presents) == "title-ready":
            title_reference = output / f"{prefix}-ps2-title-reference.png"
            screenshot(adb, serial, title_reference)
            controller.key(
                controller.B, "physical-cross-ps2-title-menu",
                hold=0.055,
            )
            return {
                "baselinePresents": baseline_presents,
                "titleCadenceObserved": True,
                "crossPresses": 1,
                "titleReference": str(title_reference),
                "screenshot": str(title_reference),
            }
        time.sleep(0.25)
    raise RuntimeError(
        "PS2 never reached its title cadence"
    )


def wait_ps2_post_cinematic_gameplay(
        adb: Path, serial: str, controller: PhysicalController,
        output: Path, prefix: str,
        baseline_presents: int, title_reference: Optional[Path],
        timeout: float = 480.0, entry_presses: int = 3,
        skip_key: Optional[int] = None,
        skip_label: str = "physical-cross-ps2",
        confirm_key: Optional[int] = None,
        skip_cycle: Optional[tuple[object, ...]] = None,
        probe_motion: tuple[str, str] = ("up", "up"),
        loop_cycle: Optional[tuple[object, ...]] = None,
        motion_min: Optional[float] = None,
        use_best_windows: bool = False,
        min_structure: float = 0.0,
        probe_hat: bool = False,
        skip_press_every: int = 4,
        skip_press_limit: int = 20,
        any_stream: bool = False) -> dict[str, object]:
    """Require sustained gameplay-tier cadence with live on-screen motion.

    Replaces the historical movie-dip transition (physically unobservable on
    the current endpoint-measurement architecture — see
    drive_ps2_title_past_title_menu). Proof arming now needs all three of:
    at least PS2_SUSTAINED_GAMEPLAY_WINDOWS trailing consecutive fresh
    >=50-tier windows; the current frame differing from the title reference
    (never parked back on the menu); and two probes two seconds apart
    differing from each other (live motion, not a frozen frame or a static
    loading card).

    Grand Theft Auto III's fixed post-title sequence: one more Cross
    confirms New Game (the default menu row), the intro cutscene plays, and
    bounded spaced Cross presses skip through it into street gameplay.
    Acceptance needs a sustained stable tier plus BRIGHT, fast inter-probe
    motion produced by a held-forward stick pulse — the brightness floor
    keeps proof off dark transitions, which is what starved the content
    gates on every attract/cinematic candidate.
    """
    leave_reference = title_reference
    if motion_min is None:
        motion_min = PS2_ATTRACT_MOTION_MEAN_DIFF
    if skip_key is None:
        skip_key = controller.B
    # The confirm half of the alternation is the SYSTEM's accept action, not
    # a fixed raw key: the Thor's raw south B resolves to PS2/PSP Cross and
    # Dreamcast A (accept on those layouts), but to Wii U B — cancel — which
    # physically bounced NES Remix between title and menu forever (run 7,
    # 2026-08-16). Wii U passes raw east A, its accept.
    if confirm_key is None:
        confirm_key = controller.B
    # Some prompt chains need more than a two-key alternation: NES Remix's
    # one-time Miiverse dialog focuses no button by default, so bare accept
    # presses are inert — a directional focus press followed by accept is
    # the only way through (run 8, 2026-08-16). A cycle keeps that sequence
    # bounded and repeatable without special-casing the loop below.
    cycle = skip_cycle if skip_cycle is not None else (skip_key, confirm_key)
    # Once the entry presses have threaded into (or near) gameplay, the
    # in-loop presses run while the acceptance gates are sampling. A system
    # may need a different set there: NES Remix's + is PAUSE in a running
    # challenge, so the entry cycle's START froze the picture on the exact
    # probes that were about to prove live motion (run wiiu15, 2026-08-16).
    in_loop_cycle = loop_cycle if loop_cycle is not None else cycle

    def press_cycle_entry(entry: object, label: str) -> None:
        # A string entry is a physical HAT d-pad direction (the Thor's d-pad
        # is axes, not keys); a ("lower-tap", x, y) tuple is a physical touch
        # on the Thor's lower display in display-4 coordinates (the GamePad
        # view forwards it as Wii U touchscreen input — the only control the
        # touch-first Miiverse applet dialogs respond to); an int is a raw
        # controller key code.
        if isinstance(entry, str):
            controller.hat(entry, label)
        elif isinstance(entry, tuple):
            qa.adb(adb, serial, "shell", "input", "touchscreen", "-d", "4",
                   "swipe", str(entry[1]), str(entry[2]),
                   str(entry[1]), str(entry[2]), "150")
        else:
            controller.key(int(entry), label, hold=0.055)

    deadline = time.monotonic() + timeout
    time.sleep(4.0)
    for press in range(1, entry_presses + 1):
        # Alternate the system skip key with the confirm action so a chain
        # of mixed prompts (Start-gated cards, A-gated menu rows) threads
        # through to gameplay.
        press_cycle_entry(
            cycle[(press - 1) % len(cycle)],
            f"{skip_label}-menu-or-skip-{press}",
        )
        time.sleep(10.0)
    probes = [output / f"{prefix}-ps2-gameplay-probe-a.png",
              output / f"{prefix}-ps2-gameplay-probe-b.png"]
    probe_index = 0
    previous_probe: Optional[Path] = None
    previous_secondary_probe: Optional[Path] = None
    consecutive_live = 0
    skip_presses = 0
    while time.monotonic() < deadline:
        log_now = qa.logs(adb, serial)
        if any_stream:
            windows = ps2_any_stream_gameplay_windows(
                log_now, baseline_presents)
        elif use_best_windows:
            windows = ps2_best_gameplay_windows(log_now, baseline_presents)
        else:
            windows = ps2_sustained_gameplay_windows(
                log_now, baseline_presents)
        # GTA III's intro plays several scenes; each skips on a button press
        # but a press is consumed per scene. Keep skipping (bounded) until a
        # live controlled scene passes acceptance — once in gameplay, Cross
        # is merely sprint and cannot break the traversal.
        if (consecutive_live == 0 and
                probe_index % skip_press_every == skip_press_every - 1 and
                skip_presses < skip_press_limit):
            # Alternate the system's skip key with the confirm action so
            # mixed prompt chains (Crazy Taxi: VMU wants Start, the name
            # registration wants A) both clear.
            press_cycle_entry(
                in_loop_cycle[skip_presses % len(in_loop_cycle)],
                f"{skip_label}-cutscene-skip-{skip_presses + 1}",
            )
            skip_presses += 1
        # The held pulse must move THIS system's representative gameplay: a
        # forward push walks GTA III's player, but a 2D platformer needs a
        # lateral hold (NES Remix's Mario stood still through the whole wait
        # on an up-stick pulse, run wiiu14, 2026-08-16).
        if probe_hat:
            # melonDS reads the DS d-pad from the Thor's HAT axes; the
            # analog pulse never reaches the game (nds1-5, 2026-08-17).
            controller.hat(probe_motion[0], "physical-probe-hat", hold=1.2)
        else:
            controller.motion_pair(probe_motion[0], probe_motion[1], hold=1.5)
        probe = probes[probe_index % 2]
        secondary_probe = probe.with_name(
            probe.stem + "-secondary" + probe.suffix) if any_stream else None
        probe_index += 1
        screenshot(adb, serial, probe)
        motion = screenshot_mean_abs_diff(previous_probe, probe) \
            if previous_probe is not None else 0.0
        if secondary_probe is not None:
            # The gameplay screen may be the LOWER display (Castlevania on
            # DS): its live motion is what proves the scene, while the top
            # map idles (run nds14). Use the livelier of the two panels.
            screenshot(adb, serial, secondary_probe,
                       secondary_token(adb, serial))
            if previous_secondary_probe is not None:
                motion = max(motion, screenshot_mean_abs_diff(
                    previous_secondary_probe, secondary_probe))
            previous_secondary_probe = secondary_probe
        previous_probe = probe
        green, dark = ps2_platform_signature(probe)
        structure = probe_gray_stddev(probe)
        left_reference = True
        if leave_reference is not None and (
                use_best_windows or min_structure > 0.0):
            left_reference = screenshot_mean_abs_diff(
                leave_reference, probe) >= PS2_LIVE_MOTION_MEAN_DIFF
        # Brightness/structure pre-gates mispredicted the verifier on
        # GTA III's dawn streets (dark 0.70, std 27 on live walking) — the
        # dense gates themselves are the arbiter; scene retries resample.
        if (windows >= PS2_SUSTAINED_GAMEPLAY_WINDOWS and
                motion >= motion_min and
                structure >= min_structure and
                left_reference):
            consecutive_live += 1
            if consecutive_live >= 2:
                path = output / f"{prefix}-ps2-gameplay-cadence-ready.png"
                screenshot(adb, serial, path)
                return {
                    "baselinePresents": baseline_presents,
                    "consecutiveGameplayWindows": windows,
                    "interProbeMotionMeanDiff": motion,
                    "probeDarkFraction": dark,
                    "probeStructureStddev": structure,
                    "screenshot": str(path),
                }
        else:
            consecutive_live = 0
        time.sleep(2.0)
    raise RuntimeError(
        "PS2 never sustained a stable tier with bright live motion on its "
        "self-playing attract before frame-generation proof"
    )


def run_game_from_system_menu(adb: Path, serial: str,
                              controller: PhysicalController, case: SystemCase,
                              output: Path, prefix: str,
                              expected_title: Optional[str] = None,
                              expected_sha: str = "",
                              nes_fixture: Optional[dict[str, str]] = None,
                              rom_identity: Optional[dict[str, str]] = None,
                              core_hashes: Optional[dict[str, str]] = None,
                              apk: Optional[Path] = None,
                              smoke_no_framegen: bool = False
                              ) -> dict[str, object]:
    menu = output / f"{prefix}-system-menu.png"
    screenshot(adb, serial, menu)
    layer_baseline = main_activity_surface_layers(adb, serial)
    (output / f"{prefix}-surface-layers-before.txt").write_text(
        "\n".join(layer_baseline) + "\n", encoding="utf-8"
    )
    library_identity = identity(adb, serial)
    # A prior interrupted qualification must never leave proof armed for this
    # title's boot logos or menus. Proof is enabled only after the visible-game
    # gate below and is unconditionally removed in the matching finally block.
    qa.adb(adb, serial, "shell", "settings", "delete", "global",
           "emufusion_framegen_proof")
    # Bound all runtime/log assertions to this one physical menu launch. This
    # also makes the N64 hardware-render verifier's exactly-one-route contract
    # unambiguous.
    qa.adb(adb, serial, "logcat", "-c")
    if case.folder == "nes" and len(library_identity.get("packagePids", [])) != 1:
        raise RuntimeError("NES qualification requires exactly one package PID")
    nes_kernel_capture = begin_nes_kernel_capture(
        adb, serial, controller, output, prefix
    ) if case.folder == "nes" else None
    nes_logcat_capture = begin_nes_logcat_capture(
        adb, serial, output, prefix,
        int(library_identity["packagePids"][0])
    ) if case.folder == "nes" else None
    nes_kernel_trace = None
    launch_log = qa.logs(adb, serial)
    route_baseline = len(ROUTE.findall(launch_log))
    interceptor_baseline = launch_log.count(
        "Intercepted lifecycle-neutral menu launch"
    )
    start_baseline = len(ACTIVITY_START.findall(launch_log))
    resume_baseline = launch_log.count(
        "performResumeActivity com.thorium.preview displayId 0"
    )
    qt_surface_baseline = launch_log.count("QtActivityDelegate.createSurface")
    launch_recorder = None
    launch_remote = ""
    launch_clock = None
    if case.folder == "nes":
        launch_recorder, launch_remote, launch_clock = begin_nes_launch_capture(
            adb, serial, controller, output, prefix
        )
    else:
        controller.key(controller.A, "physical-a-launch", hold=0.055)
    try:
        launch_frames = []
        launch_deadline = time.monotonic() + 1.2
        while time.monotonic() < launch_deadline:
            path = output / f"{prefix}-launch-{len(launch_frames) + 1:02d}.png"
            screenshot(adb, serial, path)
            launch_frames.append(path)
        launch_ocr = classify_nes_immediate_launch_frames(
            launch_frames, menu, expected_title
        ) if case.folder == "nes" else assert_no_interstitial(launch_frames)
        engine, system = wait_new_route(adb, serial, route_baseline, case)
        routed_log = qa.logs(adb, serial)
        launch_video = finish_nes_launch_recording(
            adb, serial, launch_recorder, launch_remote, output, prefix,
            int(launch_clock["inputLowerBoundElapsedNs"]), menu,
            expected_title,
        ) if launch_recorder is not None and launch_clock is not None else None
    except Exception as failure:
        if launch_recorder is not None:
            if launch_recorder.poll() is None:
                launch_recorder.kill()
                launch_recorder.communicate(timeout=2.0)
            qa.adb(adb, serial, "shell", "rm", "-f", launch_remote, check=False)
        if nes_kernel_capture is not None:
            finish_nes_kernel_capture(nes_kernel_capture)
            nes_kernel_capture = None
        if nes_logcat_capture is not None:
            finish_nes_logcat_capture(nes_logcat_capture)
            nes_logcat_capture = None
        failed_log = qa.logs(adb, serial)
        if failed_log.count("Intercepted lifecycle-neutral menu launch") <= interceptor_baseline:
            raise RuntimeError(
                "physical A did not reach the in-process launch interceptor"
            ) from failure
        raise
    lifecycle_delta = {
        "activityStart": len(ACTIVITY_START.findall(routed_log)) - start_baseline,
        "performResume": routed_log.count(
            "performResumeActivity com.thorium.preview displayId 0"
        ) - resume_baseline,
        "qtCreateSurface": routed_log.count(
            "QtActivityDelegate.createSurface"
        ) - qt_surface_baseline,
    }
    secondary_starts, foreign_starts = classify_new_activity_starts(
        routed_log, launch_log, case
    )
    if foreign_starts:
        raise RuntimeError("menu A launch started an Activity instead of staying in-process")
    if case.dual_screen:
        # A dual-screen launch stays in-process on display 0 (the top screen)
        # and opens exactly one of EmuFusion's OWN PreviewActivity windows on the
        # physical lower panel (act=SECONDARY_GAMEPLAY, resumed on a non-primary
        # display). Any other new Activity, any activity on display 0, and any
        # non-Lucent package already landed in foreign_starts above.
        if secondary_starts not in {0, 1}:
            raise RuntimeError(
                "dual-screen launch did not open exactly one Lucent secondary "
                f"gameplay window on the physical lower display (saw {secondary_starts})"
            )
        secondary_ready = SECONDARY_GAMEPLAY_RESUME.search(routed_log) is not None
        if secondary_starts == 0:
            # PreviewActivity normally remains resumed on the Thor lower panel
            # between games. Reusing that existing same-package window is the
            # desired no-flicker path, so there is intentionally no new
            # Activity START/performResume line. Require the router, nonzero
            # display and an attached secondary generator as proof instead.
            secondary_ready = SECONDARY_GAMEPLAY_REUSED.search(routed_log) is not None
        if not secondary_ready:
            raise RuntimeError(
                "dual-screen secondary gameplay window never resumed on the "
                "physical lower display"
            )
    elif lifecycle_delta["activityStart"] != 0:
        raise RuntimeError("menu A launch started an Activity instead of staying in-process")
    if lifecycle_delta["performResume"] != 0:
        raise RuntimeError("menu A launch resumed MainActivity instead of using the live window")
    if lifecycle_delta["qtCreateSurface"] != 0:
        raise RuntimeError("menu A launch recreated Qt's library surface")
    gameplay_identity = identity(adb, serial)
    if not same_identity(library_identity, gameplay_identity):
        raise RuntimeError("physical A created another Activity/task/PID")
    # A fresh PPSSPP boot can legitimately expose only a nearly-black
    # autosave warning before it receives PSP Cross.  Waiting for the generic
    # bright-frame threshold before sending Cross deadlocks qualification on
    # exactly that prompt and misreports a working renderer as black.  The
    # Thor's Odin-style raw B event is the reviewed south/PSP Cross mapping; send one
    # real controller event before visual readiness, then retain the normal
    # post-readiness navigation below to reach sustained motion.
    if case.folder == "psp":
        # PSP cold boots alternate between Cross-gated legal/autosave prompts,
        # skippable movies, and a Start-gated title screen. Drive both reviewed
        # controls at human pace before applying a brightness threshold; none
        # of these inputs can manufacture a rendered frame, but they prevent a
        # mostly-black prompt/movie from deadlocking the renderer gate.
        for attempt in range(8):
            key = controller.B if attempt % 2 == 0 else controller.START
            controller.key(key, f"physical-advance-psp-render-gate-{attempt + 1}",
                           hold=0.055)
            time.sleep(1.0)
    presented_path = output / f"{prefix}-gameplay.png"
    slow_disc_boot = case.folder in {"wiiu", "ps3"}
    boot_assist_count = [0]

    def slow_disc_boot_assist() -> None:
        # NES Remix Pack boots into a GamePad-only two-title selector while
        # the TV stays black BY DESIGN; the selector's list is unfocused, so
        # bare A presses are inert until a d-pad focus press lands
        # (physically verified 2026-08-16: HAT-left then A selects NES
        # REMIX and the TV engages on the title). Alternate focus and
        # accept so the gate's visible-TV requirement can ever be met.
        boot_assist_count[0] += 1
        if case.folder == "wiiu" and boot_assist_count[0] % 2 == 1:
            controller.hat("left", f"physical-advance-{case.folder}-boot-focus")
        else:
            # aPS3e ICO collection (ps3-4): Circle (raw A) is cancel on the
            # Thor Odin mapping. Cross (raw south B) is the collection confirm.
            boot_key = controller.B if case.folder == "ps3" else controller.A
            controller.key(
                boot_key, f"physical-advance-{case.folder}-boot-gate",
                hold=0.055)

    presented = wait_presented_frame(
        adb, serial, engine, system, menu, presented_path,
        timeout=360.0 if slow_disc_boot else 60.0,
        assist=slow_disc_boot_assist if slow_disc_boot else None,
    )
    # The primary proof above says nothing about the physical lower panel.
    # Name a zero-present secondary generator here, before any DS/3DS/Wii U
    # lower-screen navigation can misreport that stall as game state.
    dual_screen_lower_presentation = require_dual_screen_lower_presentation(
        lambda: qa.logs(adb, serial)
    ) if case.dual_screen else None
    nes_runtime_geometry = require_nes_runtime_geometry(
        qa.logs(adb, serial), presented_path,
        calibration_fixture=nes_fixture is not None,
    ) \
        if case.folder == "nes" else None
    nes_fixture_result = nes_fixture_evidence(
        adb, serial, controller, output, prefix, presented_path
    ) if nes_fixture is not None else None
    dual_gameplay_navigation = navigate_handheld_dual_screen_to_visible_ui(
        adb, serial, controller, case, output, prefix,
        expected_title=expected_title,
    )
    nds_navigation = drive_nds_hunters_past_touch_menus(
        adb, serial, controller, output, prefix
    ) if (case.folder == "nds" and
          "hunters" in normalize(expected_title or "")) else None
    nds_por_navigation = drive_nds_portrait_of_ruin_new_game_setup(
        adb, serial, controller, output, prefix
    ) if (case.folder == "nds" and
          "portraitofruin" in normalize(expected_title or "")) else None
    lower_rotation = require_n3ds_clockwise_lower(qa.logs(adb, serial)) \
        if case.folder == "n3ds" else None
    switch_navigation = navigate_switch_to_gameplay(
        adb, serial, controller, output, prefix
    ) if case.folder == "switch" else None
    # Cold first launches for these systems commonly stop at a title, legal,
    # autosave, or profile prompt. Drive real mapped confirm presses so interpolation
    # is audited on controllable gameplay rather than a logo, dissolve, or menu.
    ps2_navigation = drive_ps2_title_past_title_menu(
        adb, serial, controller, output, prefix
    ) if case.folder == "ps2" else None
    if case.folder in {"psp", "wii", "windows", "dreamcast", "wiiu"}:
        # This physical harness is bound to the Thor's reviewed Odin-style
        # controller identity (2020:0111). Its raw BTN_GAMEPAD/A event is the
        # east position and resolves to PlayStation Circle; raw BTN_EAST/B is
        # the south position and resolves to Cross. Castlevania and God of War
        # both wait for Cross, so raw A previously left qualification on a
        # static menu while the engine correctly logged control=EAST/button=8.
        # Disc-based PS2 cold boots can spend more than thirty seconds in
        # logos, profile setup, an intro movie and a loading screen on Thor.
        # Switch does not use this blind-navigation path. Its title-video and
        # recognized-menu state machine above must prove gameplay first.
        # PSP needs more than the three cold-launch taps used by Switch/Wii:
        # the representative God of War title has studio logos, a skippable
        # cinematic, a Start-gated title screen, and Cross-gated menu rows.
        # Alternate the two reviewed controls long enough to reach a scene the
        # analog-motion worker can actually drive. A cinematic dissolve is not
        # accepted as gameplay motion and previously produced only crossfade.
        advance_attempts = 12 if case.folder in {"psp", "dreamcast"} else (
            1 if case.folder == "wii" else 3
        )
        # Super Mario 3D World's title and file-select screens are both
        # cleared by Wii U A (Thor raw EAST); the wired gameplay wait below
        # supplies the +/A alternation for its skippable opening cinematic.
        for attempt in range(advance_attempts):
            label = f"physical-advance-gameplay-{attempt + 1}"
            if case.folder == "wii":
                # Both Galaxy titles explicitly require a simultaneous A+B
                # chord. Galaxy 2 can animate its logo for several seconds
                # before the prompt exists. Wait for the prompt region, then
                # retry only while that same prompt remains visible; an
                # unproven chord could press B/Cancel in the file selector.
                if attempt == 0:
                    chord_attempt = 0
                    prompt_seen = False
                    prompt_cleared = False
                    # Galaxy 1 on the Thor (run wii-b32, 2026-09-01) held its
                    # strap-warning screen for ~20 s and then ran its space
                    # intro before the prompt existed; 25 s expired on the
                    # intro with chords=0.  The window only bounds waiting for
                    # the prompt to APPEAR; clearance keeps its own 12 s.
                    prompt_deadline = time.monotonic() + 90.0
                    prompt_text = ""
                    probe = 0
                    while time.monotonic() < prompt_deadline:
                        probe += 1
                        prompt_frame = output / (
                            f"{prefix}-wii-title-prompt-probe-"
                            f"{probe:02d}.png"
                        )
                        screenshot(adb, serial, prompt_frame)
                        visible, prompt_text = wii_galaxy_title_prompt(
                            prompt_frame
                        )
                        if not visible:
                            if prompt_seen:
                                time.sleep(0.75)
                                confirm_frame = output / (
                                    f"{prefix}-wii-title-prompt-clear-"
                                    f"{probe:02d}.png"
                                )
                                screenshot(adb, serial, confirm_frame)
                                confirm_visible, prompt_text = (
                                    wii_galaxy_title_prompt(confirm_frame)
                                )
                                if not confirm_visible:
                                    prompt_cleared = True
                                    break
                                # The first frame was an OCR miss, not a state
                                # transition. Treat the confirmed prompt as
                                # visible so the bounded chord retry below is
                                # actually issued.
                                visible = True
                            if not visible:
                                time.sleep(0.75)
                                continue
                        if not prompt_seen:
                            # Appearance and clearance are separate bounded
                            # states. Galaxy 2 can expose the prompt at the end
                            # of its long logo animation; always leave enough
                            # time to observe the result of an authorized chord.
                            prompt_deadline = max(
                                prompt_deadline, time.monotonic() + 12.0
                            )
                        prompt_seen = True
                        if chord_attempt >= 3:
                            break
                        chord_attempt += 1
                        controller.chord(
                            (controller.A, controller.B),
                            f"{label}-chord-{chord_attempt}", hold=0.12,
                        )
                        time.sleep(1.5)
                    if not prompt_seen or not prompt_cleared:
                        raise RuntimeError(
                            "Wii title did not expose and clear its OCR-proven "
                            f"A+B prompt; chords={chord_attempt}, "
                            f"last OCR={prompt_text!r}"
                        )
                    continue
            else:
                advance_key = controller.START if (
                    case.folder in {"psp", "dreamcast"} and attempt % 2 == 0
                ) else (controller.B if case.folder in {"ps2", "psp", "dreamcast"}
                        else controller.A)
                controller.key(advance_key, label, hold=0.055)
            time.sleep(1.0)
        if case.folder == "wii":
            # Dolphin's in-window Wii route currently presents an empty file
            # chooser on each cold qualification launch. Reproduce Galaxy's
            # complete new-file flow at the measured Thor IR hotspots instead
            # of assuming a persistent save or clicking through transitions.
            # Earlier qualification launches create a persistent save, so the
            # chooser may show an EXISTING file whose submenu default is
            # Start. Interleave the measured slot and confirm hotspots so the
            # same bounded sequence completes both trees: empty-slot create
            # (slot -> yes -> icon -> confirm -> play) and existing-file
            # start (slot -> start; the surplus clicks land on the one-time
            # storybook/letter pages, which the SOUTH presses below already
            # clear on any path).
            wii_steps = (
                (-0.28, 0.11, "physical-wii-a-select-save-slot-1"),
                (0.27, -0.10, "physical-wii-a-confirm-or-create-yes"),
                (-0.28, 0.11, "physical-wii-a-slot-or-start"),
                (0.27, -0.10, "physical-wii-a-confirm-2"),
                (-0.55, 0.18, "physical-wii-a-select-mario-icon"),
                (0.27, -0.10, "physical-wii-a-confirm-mario-icon"),
                (0.27, -0.10, "physical-wii-a-play-file"),
            )
            for horizontal, vertical, label in wii_steps:
                controller.aim_right(
                    horizontal, vertical, "physical-wii-aim-" + label,
                    settle=0.90,
                )
                controller.key(controller.B, label, hold=0.18)
                time.sleep(3.0)
            # A newly-created Galaxy file does not enter controllable gameplay
            # after Play This File.  It first presents a bounded storybook and
            # Peach's letter, each advanced by Wii A.  Previous qualification
            # armed proof immediately here and consequently measured the file
            # selector/title artwork instead of the game.  Human-paced SOUTH
            # presses clear every one-time page; on an existing save they are
            # harmless jumps/actions during the warm-up before proof is armed.
            for page in range(24):
                controller.key(
                    controller.B,
                    f"physical-wii-a-story-or-gameplay-{page + 1}",
                    hold=0.10,
                )
                time.sleep(0.65)
            time.sleep(8.0)
    n64_entry_presses = 0
    n64_twine_entry = None
    n64_fzero_entry = None
    if case.folder == "n64":
        normalized_n64_title = normalize(str(expected_title or ""))
        if normalized_n64_title == normalize("007: The World Is Not Enough"):
            n64_twine_entry = prepare_n64_twine_gameplay(
                adb, serial, controller, output, prefix,
            )
        elif normalized_n64_title == normalize("F-Zero X"):
            rife_attract_warmup = qa.adb(
                adb, serial, "shell", "settings", "get", "global",
                "emufusion_framegen_rife_qualification",
            ).stdout.strip() == "1"
            n64_fzero_entry = prepare_n64_fzero_attract_race(
                adb, serial, controller, output, prefix,
                warmup_cycles=0 if rife_attract_warmup else 1,
            )
        else:
            n64_entry_presses = capture_n64_start_entry_presses(
                adb, serial, output, prefix,
            )

    # The proven-live-gameplay wait is generic (stable-tier windows + live
    # inter-probe motion, action presses only on statically held frames):
    # Wii physically needed it too — nine Galaxy runs sampled idle/cutscene
    # windows without it (2026-08-15). Wii passes a fresh baseline (the
    # bounded launch log begins at this menu launch) and no title reference.
    ps2_gameplay_readiness = wait_ps2_post_cinematic_gameplay(
        adb, serial, controller, output, prefix,
        int(ps2_navigation["baselinePresents"]),
        Path(str(ps2_navigation["titleReference"])),
    ) if case.folder == "ps2" else (wait_ps2_post_cinematic_gameplay(
        adb, serial, controller, output, prefix, -1, None,
        # 007: The World Is Not Enough parks on its PRESS START title art
        # forever under the generic wait (run n64-2 sampled that static
        # card through all seven retries — the default cycle never presses
        # START). TWINE's state-owned profile/menu sequence is completed above
        # before this generic live-motion wait; other N64 titles retain their
        # OCR-authorized START plus A-only progression.
        entry_presses=n64_entry_presses, skip_key=controller.START,
        skip_label="physical-start-n64",
        confirm_key=n64_console_a_key(controller),
        loop_cycle=(n64_console_a_key(controller),),
        skip_press_every=1, skip_press_limit=40,
        # TWINE's dark mission scenes measured 1.84 mean-diff of REAL
        # motion at a steady 30->60 lock (run n64-3) against the generic
        # 2.0 full-brightness floor; static screens on this stack measure
        # <=0.31 (DS calibration). Same sprite-scale floor as nds.
        motion_min=0.5,
    ) if (case.folder == "n64" and n64_fzero_entry is None and
          normalized_n64_title !=
          normalize("The Legend of Zelda: Ocarina of Time")) else (wait_ps2_post_cinematic_gameplay(
        adb, serial, controller, output, prefix, -1, None,
        # SMG2's Star Festival opening is a CONTROLLABLE 2D side-scroll
        # walk: the default up-stick pulse leaves Mario standing until he
        # falls asleep (run wii3, 2026-08-17 — probes caught the Zzz idle
        # on a 97%-static card and the wait starved). A lateral hold walks
        # him right, produces real probe motion, and advances the intro
        # toward the dense-motion-rich 3D scenes.
        probe_motion=("right", "right"),
    ) if case.folder == "wii" else (wait_ps2_post_cinematic_gameplay(
        adb, serial, controller, output, prefix, -1, None,
        entry_presses=10, skip_key=controller.START,
        skip_label="physical-start-dreamcast",
        skip_cycle=(controller.START, controller.A, controller.B),
        # Crazy Taxi's attract cycles title card -> SELF-DRIVING demo ->
        # scores. In-loop A/START presses inserted a credit mid-attract and
        # parked qualification on the idle driver-select countdown (the
        # ~25% pass lottery across dreamcast5-10); B only ever backs out to
        # the attract. The static cards between demo segments reset a
        # trailing window count, so credit the PEAK run instead — the
        # probes' live-motion requirement still lands arming inside a demo
        # segment (the exact scene the dreamcast8 PASS sampled at 30→60).
        loop_cycle=(controller.B,),
        use_best_windows=True,
    ) if case.folder == "dreamcast" else (wait_ps2_post_cinematic_gameplay(
        adb, serial, controller, output, prefix, -1, None,
        # Super Mario 3D World: START clears the title, A accepts the file
        # select (raw east A is Wii U accept; raw south B is CANCEL and
        # bounced earlier runs), and the opening cutscene plays out under
        # the in-loop presses. The sampling loop presses only A — + would
        # PAUSE running gameplay on the exact probes proving live motion
        # (physically observed on this title's sibling flow, run wiiu15).
        # The lateral probe pulse runs Mario so the platformer's camera and
        # sprite motion register; the up-stick pulse left him standing
        # still for entire waits.
        entry_presses=8, skip_key=controller.START,
        skip_label="physical-plus-wiiu", confirm_key=controller.A,
        probe_motion=("right", "right"),
        loop_cycle=(controller.A,),
    ) if case.folder == "wiiu" else (wait_ps2_post_cinematic_gameplay(
        adb, serial, controller, output, prefix, -1, None,
        entry_presses=10, skip_key=controller.START,
        skip_label="physical-start-n3ds", confirm_key=controller.A,
        # ALBW's retained file opens a "Start with this file?" sheet with
        # Rename highlighted. Physical Down+A selects Begin; the prior
        # A/START-first cycle stayed on Rename for the whole bounded wait.
        skip_cycle=(
            "down", controller.A, controller.A, controller.START,
            ("lower-tap", 620, 540),
            ("lower-tap", 620, 720),
        ),
        probe_motion=("right", "right"),
        loop_cycle=(controller.A, ("lower-tap", 620, 540)),
    ) if case.folder == "n3ds" else (wait_ps2_post_cinematic_gameplay(
        adb, serial, controller, output, prefix, -1, presented_path,
        # ICO & Shadow of the Colossus Collection is the first packaged
        # aPS3e title. It lands on a two-game selector with ICO already
        # highlighted. Circle (raw A) and START left that screen unchanged
        # for the whole 8-minute wait (run ps3-4); Cross (raw south B, the
        # same Thor Odin mapping as PS2/PSP) is the collection confirm.
        # START is required on ICO's own "PRESS START BUTTON" title during
        # entry. It is NOT a cinematic skip — ps3-6 opened ICO's pause
        # sheet (Options / Back / Return to title) and froze the wait.
        # Cross advances collection confirm, New Game, and dialogue; the
        # opening cinematic is unskippable and ran ~12 minutes in ps3-5
        # with brief 20→40 locks, so the wait stays Cross-only and long
        # enough to reach the playable cage.
        timeout=1080.0, entry_presses=4, skip_key=controller.START,
        skip_label="physical-cross-ps3", confirm_key=controller.B,
        skip_cycle=(controller.B, controller.START, "left"),
        probe_motion=("up", "up"),
        loop_cycle=(controller.B,),
        # ICO's opening is dark and often nearly still (wagon bars, idol
        # wall). ps3-5/7/8 posted 14–25 consecutive 20→40 windows during
        # entry, then dropped to 15 Hz before the first probe, so the
        # trailing count was 0. Use the peak lock, ignore the PS2 attract
        # motion floor, and require a structured frame that is not the
        # collection selector (rejects black loads and the still menu).
        motion_min=0.0,
        use_best_windows=True,
        min_structure=8.0,
    ) if case.folder == "ps3" else None))))))
    if n64_fzero_entry is not None:
        # The F-Zero attract preparation itself proves a full-screen moving
        # race and deliberately supplies no game input.  Running the generic
        # N64 readiness loop here would inject A/START and cancel the attract.
        ps2_gameplay_readiness = n64_fzero_entry
    elif (case.folder == "n64" and normalized_n64_title ==
          normalize("The Legend of Zelda: Ocarina of Time")):
        # The generic cadence+pixel-motion probe can see an animated Ocarina
        # close-up as "live" even though the player has no control and the HUD
        # is absent.  Bind the 20-fps qualification scene to the visible
        # top-screen gameplay contract before proof can be armed.
        ocarina_hud = wait_n64_ocarina_gameplay_hud(
            adb, serial, controller, output, prefix,
        )
        if ps2_gameplay_readiness is None:
            ps2_gameplay_readiness = {}
        ps2_gameplay_readiness["ocarinaGameplay"] = ocarina_hud
    if case.folder == "nds":
        if nds_navigation is not None:
            # The Hunters touch driver already reached morph-ball on
            # nds8–10. The generic PS2 wait then held START/A for minutes,
            # crashed the process to the launcher (nds11), and never armed
            # proof.
            ps2_gameplay_readiness = nds_navigation
            time.sleep(8.0)
        else:
            # Button-navigable DS titles (Castlevania DoS pinned
            # 2026-08-17: Hunters' dark, input-gated morph-ball room
            # honestly starves the dense content gates at ~30 Hz) go
            # through the generic gameplay wait. melonDS reads the DS
            # d-pad from HAT axes, so the probe pulse must be a held HAT
            # leg — the analog sweep never reaches the game.
            # Castlevania: Order of Ecclesia threads its ENTIRE first-boot
            # flow on buttons (physically verified by hand, 2026-08-17):
            # START/A clear title and data select, and the EDIT NAME
            # keyboard is d-pad-driven — A types the highlighted key, START
            # jumps the cursor to OK, A confirms; A then advances the
            # story crawl into Shanoa's 60 fps side-scrolling gameplay.
            # (Dawn of Sorrow was abandoned: its SIGN YOUR NAME canvas is
            # stylus-only and injected taps drew strokes without ever
            # registering a clean OK tap, runs nds6-7.) No lower-taps here:
            # a stray tap types random keyboard letters.
            # OoE's intro keeps the TOP screen on a static ornament frame
            # while the story/dialogue (and its A-gated advance) runs on
            # the BOTTOM screen; the default one-press-per-four-probes
            # bound of 20 exhausted mid-dialogue and the wait starved on
            # a screen the intro never animates (run nds8). Press A every
            # probe with a wide bound — in Shanoa's gameplay A is merely
            # attack.
            # Portrait of Ruin's deterministic data/name/emblem setup is
            # completed above before this generic live-motion wait. Do not
            # replay title/file inputs here: they previously opened COPY
            # DATA or paused gameplay. B/A only advance story dialogue and
            # become harmless attacks once the lateral gameplay probe lands.
            ps2_gameplay_readiness = wait_ps2_post_cinematic_gameplay(
                adb, serial, controller, output, prefix, -1, None,
                entry_presses=0, skip_key=controller.START,
                skip_label="physical-start-nds", confirm_key=controller.A,
                probe_motion=("right", "right"), probe_hat=True,
                loop_cycle=(controller.B, controller.A),
                skip_press_every=1, skip_press_limit=80,
                any_stream=True,
                # 2D sprite motion moves ~5% of a DS screen's pixels: live
                # PoR gameplay measured 0.81 mean-diff (run nds18) while
                # every static screen measured <=0.31 (map 0.18, pause
                # 0.30, dialogue 0.30). The full-screen 3D floor of 2.0
                # starved the wait on real gameplay; 0.5 separates the two
                # populations with margin on both sides. Navigation
                # heuristic only — the dense gates stay the arbiter.
                motion_min=0.5,
            )
    real_nes_readiness = prepare_real_nes_gameplay(
        adb, serial, controller, output, prefix, str(expected_title),
        nes_logcat_capture,
    ) if (case.folder == "nes" and nes_fixture is None and expected_title) else None
    # Arm proof only after cold-launch/title navigation. The running generator
    # observes this shell-only switch once per health interval, resets its
    # bounded counters, and leaves normal user sessions on the proof-off path.
    # PS2 titles may still be inside a slow, low-motion opening cinematic when
    # navigation hands over (physically observed with God of War's cliff
    # cinematic on the Thor, 2026-08-15): the dense content gates then starve
    # even though pacing is perfect. Collection is therefore retried on a
    # later scene, but ONLY when every recorded failure is a scene-content
    # starvation class — pacing, atlas, timer, or any other failure raises
    # immediately and the gates themselves are unchanged.
    # Five attempts spaced 75 s apart span past the longest observed PS2
    # opening movie (Kingdom Hearts' dive sequence runs about four minutes
    # of slow, low-contrast content that legitimately starves the dense
    # motion gates before the first playable scene appears).
    scene_attempts = 7 if case.folder in {
        "ps2", "wii", "wiiu", "switch", "nds", "n3ds", "dreamcast", "ps3",
        "n64",
    } else 1
    if (case.folder == "n64" and normalized_n64_title ==
            normalize("The Legend of Zelda: Ocarina of Time")):
        # Ocarina has deterministic, title-owned HUD navigation and the N64
        # proof loop itself advances its one mandatory Saria greeting.  A
        # failed moving-gameplay capture is therefore a real diagnostic, not
        # evidence that a blind 75-second wait will find a different scene.
        # r10 otherwise left the OLED on through up to six identical retry
        # delays after the first complete compositor-bound rejection.
        scene_attempts = 1
    generated = None
    # The list-view smoke verifies RELAUNCH health: route, visible frames,
    # engine telemetry, stop/return. It does not drive gameplay, so the
    # relaunched title legitimately idles on a static title screen where
    # presents pause and the dense motion gates cannot be satisfied —
    # neither state distinguishes relaunch failure. The MAIN qualification
    # (which just ran the full evidence on this exact launch stack) owns
    # the frame-generation bar; the smoke skips only this phase.
    if smoke_no_framegen:
        scene_attempts = 0
    if (not smoke_no_framegen and case.folder == "n64" and
            normalized_n64_title ==
                    normalize("The Legend of Zelda: Ocarina of Time")):
        # Stage the save into post-greeting controllable gameplay before proof
        # begins. Physical r13 proved the camera/orbit path produces an exact
        # 20-Hz unique clock and 40-Hz physical output, but its short evidence
        # window ended on Saria's first dialogue page and therefore contained
        # no representative traversal. These exact long legs physically reach
        # the house exit. Clear every bounded dialogue page with N64 A, then
        # require the ordinary gameplay HUD before setting the shell-only
        # proof switch.
        staging_vectors = (
            (-0.720, -0.720, 4.0),
            (-0.720, 0.000, 3.0),
            (0.000, -0.720, 3.0),
        )
        try:
            for horizontal, vertical, hold in staging_vectors:
                controller.set_left_stick_vector(
                    horizontal, vertical,
                    "physical-n64-ocarina-preproof-exit", hold=hold,
                )
                controller.key(
                    n64_console_a_key(controller),
                    "physical-n64-a-preproof-dialogue", hold=0.055,
                )
            for _ in range(12):
                controller.key(
                    n64_console_a_key(controller),
                    "physical-n64-a-preproof-dialogue", hold=0.055,
                )
        finally:
            controller.center_left_stick(
                "physical-n64-ocarina-preproof-exit-release"
            )
        for settle_attempt in range(20):
            staged_ocarina = output / (
                f"{prefix}-n64-ocarina-motion-ready-"
                f"{settle_attempt:02d}.png"
            )
            screenshot(adb, serial, staged_ocarina)
            if n64_ocarina_gameplay_hud(staged_ocarina):
                break
            if settle_attempt % 4 == 3:
                controller.key(
                    n64_console_a_key(controller),
                    "physical-n64-a-preproof-settle", hold=0.055,
                )
            time.sleep(0.25)
        else:
            raise RuntimeError(
                "Ocarina pre-proof staging did not reach dialogue-free "
                "controllable gameplay"
            )
    # Proof is armed exactly once across every scene attempt: the verifier's
    # exactly-once generator-proof contract reads the bounded per-launch log,
    # and per-attempt re-arming physically tripped it on the first retried
    # Wii run (2026-08-15). The single delete in the finally block still
    # guarantees no following title inherits instrumentation state.
    qa.adb(adb, serial, "shell", "settings", "put", "global",
           "emufusion_framegen_proof", "1")
    try:
        for scene_attempt in range(1, scene_attempts + 1):
            try:
                generated = frame_generation_evidence(
                    adb, serial, controller, output, prefix, layer_baseline,
                    case,
                    qualification_identity={
                        # The verifier joins these exact values to the single
                        # routed engine/system log record; separator-stripping
                        # would sever that identity binding for engines such
                        # as mesen-s.
                        "systemId": system.lower(),
                        "gameId": normalize(expected_title) or "unknown",
                        "coreId": engine.lower(), "packageName": PACKAGE,
                        "romSha256": str((rom_identity or {}).get("sha256", "")),
                        "coreSha256": str(
                            (core_hashes or {}).get(normalize(engine), "")),
                        "apkSha256": expected_sha.lower(),
                    },
                    continuous_log=nes_logcat_capture,
                )
                break
            except RuntimeError as failure:
                if (scene_attempt >= scene_attempts or
                        not _is_content_starved_framegen_failure(str(failure))):
                    raise
                # Content-starved scenes are frequently dialog- or
                # prompt-gated: SMG2's Star Festival intro holds a
                # 95%-static 2D card until A is pressed, and with nothing
                # pressed between attempts all seven sampled the exact same
                # held card (run wii2, 2026-08-17). Drive the SYSTEM's
                # accept control a few times, spaced, so the next attempt
                # samples a later scene; in live gameplay these presses are
                # the harmless primary action, never pause (START is what
                # froze probes on SM3DW, run wiiu15).
                advance_key = {
                    "wii": controller.B, "ps2": controller.B,
                    "ps3": controller.B, "psp": controller.B,
                    "wiiu": controller.A, "n3ds": controller.A,
                    "dreamcast": controller.A, "switch": controller.A,
                    "nds": controller.A,
                    "n64": n64_console_a_key(controller),
                }.get(case.folder)
                # DS dialogue scenes hold dozens of A-gated lines (OoE's
                # Albus scene, run nds12); spend the same 75 s pressing
                # more often there.
                advance_count = 8 if case.folder == "nds" else 4
                for advance in range(advance_count):
                    if advance_key is not None:
                        controller.key(
                            advance_key,
                            f"physical-scene-advance-{scene_attempt}-"
                            f"{advance + 1}",
                            hold=0.055,
                        )
                    time.sleep(8.0)
                time.sleep(75.0 - 8.0 * advance_count)
    finally:
        # Also runs when layer discovery, SurfaceFlinger capture, or the
        # strict verifier rejects the title. No following title may inherit
        # this shell-only instrumentation state.
        qa.adb(adb, serial, "shell", "settings", "delete", "global",
               "emufusion_framegen_proof")
    n64_runtime = n64_gameplay_evidence(
        adb, serial, controller, output, prefix, presented_path
    ) if case.folder == "n64" else None
    displays = dual_screen_evidence(
        adb, serial, case, presented_path, output, prefix
    )
    flicker = flicker_evidence(adb, serial, output, prefix) \
        if case.flicker_burst else None
    package_pids = library_identity.get("packagePids", [])
    volume = quick_tap_volume_evidence(
        adb, serial, controller, output, prefix, expected_sha,
        int(package_pids[0]) if len(package_pids) == 1 else -1,
    ) \
        if case.folder == "gc" else None
    nes_cheat = nes_cheat_evidence(
        adb, serial, controller, output, prefix
    ) if nes_fixture is not None else None
    if nes_fixture is not None:
        nes_resume = nes_resume_evidence(
            adb, serial, controller, case, menu, library_identity, output, prefix,
            str(expected_title or nes_fixture.get("title", "")),
        )
    elif case.folder == "nes" and expected_title:
        nes_resume = nes_real_title_resume_evidence(
            adb, serial, controller, case, menu, library_identity, output, prefix,
            str(expected_title),
        )
    else:
        nes_resume = None
    returned = (nes_resume["movingReturn"] if nes_resume is not None else
                stop_and_return(
                    adb, serial, controller, case, engine, system, menu,
                    library_identity, output, prefix, expected_title,
                ))
    if nes_kernel_capture is not None:
        nes_kernel_trace = finish_nes_kernel_capture(nes_kernel_capture)
        nes_kernel_capture = None
    nes_continuous_log = None
    if nes_logcat_capture is not None:
        nes_continuous_log = finish_nes_logcat_capture(nes_logcat_capture)
        nes_logcat_capture = None
    bounded_log = (nes_continuous_log.read_text(encoding="utf-8", errors="replace")
                   if nes_continuous_log is not None else qa.logs(adb, serial))
    log_path = output / f"{prefix}-logcat.txt"
    log_path.write_text(bounded_log, encoding="utf-8")
    nes_offline = None
    if nes_fixture is not None:
        if apk is None or launch_video is None or launch_clock is None or \
                nes_fixture_result is None or nes_cheat is None or nes_resume is None:
            raise RuntimeError("NES offline qualification inputs are incomplete")
        nes_offline = write_nes_qualification_manifest(
            adb, serial, controller, apk, output, prefix,
            rom_identity or {}, str((core_hashes or {}).get("mesen", "")),
            expected_sha.lower(), menu, launch_video, launch_clock,
            nes_fixture_result, generated, nes_cheat, nes_resume, log_path,
            nes_kernel_trace, int(library_identity["packagePids"][0]),
        )
    n64_report = None
    if case.folder == "n64":
        audit = n64_hw.audit(bounded_log)
        n64_report = {
            "pass": audit.passed,
            "errors": list(audit.errors),
            "routeCount": audit.route_count,
            "hardwareContexts": list(audit.hardware_contexts),
            "contextResetCount": audit.context_reset_count,
            "presentedFrameCount": audit.presented_frame_count,
            "negotiationRejected": audit.negotiation_rejected,
            "evidenceLog": str(log_path),
        }
        if not audit.passed:
            raise RuntimeError("N64 hardware-render evidence failed: " +
                               "; ".join(audit.errors))
    real_nes_manifest = None
    if (case.folder == "nes" and nes_fixture is None and nes_resume is not None and
            nes_resume.get("sampledRealTitle")):
        real_nes_manifest = write_real_nes_title_manifest(
            output, prefix, str(expected_title),
            int(library_identity["packagePids"][0]), expected_sha.lower(),
            rom_identity or {}, str((core_hashes or {}).get("mesen", "")),
            controller.node, launch_video or {}, launch_clock or {},
            presented_path, nes_runtime_geometry or {}, generated, nes_resume,
            log_path, real_nes_readiness or {}, nes_kernel_trace,
        )
    return {
        "system": case.folder, "engine": engine,
        "expectedTitle": expected_title,
        "routeSystem": system, "sameMainActivityWindowPid": True,
        "lifecycleNeutralBroadcast": True,
        "lifecycleDelta": lifecycle_delta,
        "launchInterstitialOcr": launch_ocr,
        "launchVideo": launch_video,
        "launchInputClock": launch_clock,
        "presentedFrame": presented,
        "dualScreenLowerPresentation": dual_screen_lower_presentation,
        "nesRuntimeGeometry": nes_runtime_geometry,
        "nesQualification": nes_fixture_result,
        "nesCheat": nes_cheat,
        "nesResume": nes_resume,
        "nesOfflineQualification": nes_offline,
        "nesRealTitleQualification": real_nes_manifest,
        "nesRealGameplayReadiness": real_nes_readiness,
        "ps2TitleNavigation": ps2_navigation,
        "ps2GameplayReadiness": ps2_gameplay_readiness,
        "n64FzeroScene": n64_fzero_entry,
        "dualGameplayNavigation": dual_gameplay_navigation,
        "ndsNavigation": nds_navigation,
        "ndsPortraitOfRuinNavigation": nds_por_navigation,
        "switchNavigation": switch_navigation,
        "frameGeneration": generated,
        "lowerDisplayRotation": lower_rotation,
        "n64Gameplay": n64_runtime,
        "n64HardwareAudit": n64_report,
        "displays": displays,
        "flickerBurst": flicker,
        "quickTapVolume": volume,
        "heldStop": returned,
    }


def main_activity_surface_layers(adb: Path, serial: str) -> list[str]:
    listing = qa.adb(adb, serial, "shell", "dumpsys", "SurfaceFlinger",
                     "--list").stdout.splitlines()
    return list(dict.fromkeys(line.strip() for line in listing
                if "SurfaceView[com.thorium.preview/" in line and
                "MainActivity](BLAST)" in line))


def secondary_gameplay_layers(adb: Path, serial: str,
                              clockwise_texture: bool) -> list[str]:
    """Return only the physical lower-display gameplay compositor layer.

    Rotation is an internal presentation detail: both DS and 3DS ultimately
    latch the generated lower-screen frames through PreviewActivity's gameplay
    SurfaceView.  The activity/window layers can exist alongside it but do not
    own a frame timeline (physically verified on the Thor: those layers return
    only zero latency rows while the BLAST SurfaceView returns real fences).
    Select only that independently latched SurfaceView so a parent window can
    never be mistaken for the secondary generator's visible output.
    """
    listing = qa.adb(adb, serial, "shell", "dumpsys", "SurfaceFlinger",
                     "--list").stdout.splitlines()
    return list(dict.fromkeys(line.strip() for line in listing
                if "SurfaceView[com.thorium.preview/"
                   "com.thorium.preview.PreviewActivity](BLAST)" in line))


def require_independent_dual_generators(
        primary: dict[str, object], secondary: dict[str, object]) -> None:
    """Reject a lower-display report aliased to the primary generator.

    Each verifier invocation already binds telemetry to one role/display and
    one compositor timeline. This final cross-report check proves they are two
    generator instances in the same one-app process, rather than one identity
    relabelled for both screens.
    """
    first = primary.get("generator")
    second = secondary.get("generator")
    if not isinstance(first, dict) or not isinstance(second, dict):
        raise RuntimeError("dual-screen frame-generation report has no generator identity")
    if first.get("generator") == second.get("generator"):
        raise RuntimeError("primary and secondary frame generation share one generator")
    if first.get("pid") != second.get("pid"):
        raise RuntimeError("primary and secondary frame generation crossed app processes")


MOTION_BOUNDS = re.compile(
    r"Motion bounds generator=(?P<generator>\d+) "
    r"role=(?P<role>[a-z0-9_-]+) displayId=(?P<display_id>-?\d+) "
    r"source=(?P<width>\d+)x(?P<height>\d+) "
    r"maxFlowPixels=(?P<pixels>[0-9.]+) "
    r"maxFlowFraction=(?P<fraction>[0-9.eE+-]+)"
)


def require_safe_motion_bound(log: str, report: dict[str, object]) -> dict[str, object]:
    """Bind generated pixels to a source-resolution-safe displacement limit.

    The v5 shader replay proves that output follows its decoded vectors; it
    cannot prove those vectors are sane.  A fixed 80-pixel range on a 192-line
    DS crop produced the e3f run's melted picture while all internal counters
    passed.  Qualification therefore requires the exact generator identity to
    attest the bounded range used for its latest source allocation.
    """
    generator = report.get("generator")
    if not isinstance(generator, dict):
        raise RuntimeError("frame-generation report has no generator identity")
    expected_identity = (
        int(generator.get("generator", -1)),
        str(report.get("role", "")),
        int(report.get("displayId", -1)),
    )
    matches = []
    for found in MOTION_BOUNDS.finditer(log):
        identity = (int(found.group("generator")), found.group("role"),
                    int(found.group("display_id")))
        if identity == expected_identity:
            matches.append(found)
    if not matches:
        raise RuntimeError(
            "frame-generation proof has no identity-matched motion bound"
        )
    found = matches[-1]
    width = int(found.group("width"))
    height = int(found.group("height"))
    pixels = float(found.group("pixels"))
    fraction = float(found.group("fraction"))
    shorter = min(width, height)
    if shorter < 1:
        raise RuntimeError("frame-generation motion bound has invalid source geometry")
    # Reviewed source-relative limit: 10 % of the shorter source dimension,
    # capped at MAX_FLOW_PIXELS (108, raised from 80 on 2026-09-02 for the
    # dense reach; 1080p sources report exactly 108.0, 720p sources 72.0).
    # 2026-09-04: MAX_FLOW_PIXELS 216 and MAX_FLOW_SOURCE_FRACTION 0.20 (a
    # 20-Hz N64 pan moves ~200 px per source frame at 1080p; FSR 3 tracks
    # 512).  The validated planes now use a signed square-root encoding so
    # sub-pixel precision near zero survives the doubled range.
    expected_pixels = min(216.0, max(4.0, shorter * 0.20))
    expected_fraction = expected_pixels / shorter
    if abs(pixels - expected_pixels) > 0.05 or abs(fraction - expected_fraction) > 0.001:
        raise RuntimeError(
            "frame-generation motion bound does not match the reviewed "
            "source-relative limit"
        )
    if shorter >= 40 and fraction > 0.201:
        raise RuntimeError(
            "frame-generation motion range exceeds twenty percent of the source"
        )
    return {
        "sourceWidth": width,
        "sourceHeight": height,
        "maxFlowPixels": pixels,
        "maxFlowFraction": fraction,
    }


def require_visible_frame_generation_output(
        metrics: dict[str, object], role: str, display_id: int) -> None:
    """Reject internal proof when the corresponding physical panel is blank."""
    if (not metrics.get("visible") or
            float(metrics.get("visibleFraction", 0.0)) < 0.08 or
            int(metrics.get("distinctColors", 0)) < 48):
        raise RuntimeError(
            f"{role}/display-{display_id} frame generation has no visible "
            "compositor output"
        )


def require_n3ds_clockwise_lower(log: str) -> dict[str, object]:
    """Bind physical 3DS acceptance to the rotated display-4 presentation."""
    shown = re.search(
        r"showGameplaySurface generation=(\d+) displayId=4 "
        r"clockwiseQuarterTurn=true",
        log,
    )
    surface = re.search(
        r"clockwise gameplay surfaceCreated generation=(\d+) "
        r"buffer=(\d+)x(\d+)",
        log,
    )
    if shown is None or surface is None or shown.group(1) != surface.group(1):
        raise RuntimeError("3DS lower display did not activate its clockwise surface path")
    width, height = int(surface.group(2)), int(surface.group(3))
    if width >= height:
        raise RuntimeError("3DS clockwise lower-display producer is not portrait")
    return {"clockwiseQuarterTurn": True, "displayId": 4,
            "generation": int(shown.group(1)),
            "producerBuffer": f"{width}x{height}"}


_FRAMEGEN_HEALTH_STRING_FIELDS = frozenset((
    "role", "proof_contract", "dense_variant", "dense_diagnostic_mask_layout",
    "presentation_timing_mode", "source_clock_kind",
))
_FRAMEGEN_OPTIONAL_WORKLOAD_FIELDS = (
    "dense_variant",
    "dense_analysis_width",
    "dense_analysis_height",
    "dense_solve_texels",
    "dense_total_texels",
)
_FRAMEGEN_OPTIONAL_WALL_TIMING_FIELDS = (
    "dense_combined_pair_warp_us",
    "dense_promotion_wall_samples",
    "dense_promotion_wall_total_us",
    "dense_promotion_wall_p95_us",
    "dense_promotion_wall_max_us",
    "dense_signature_wall_samples",
    "dense_signature_wall_total_us",
    "dense_signature_wall_p95_us",
    "dense_signature_wall_max_us",
    "dense_proof_wall_samples",
    "dense_proof_wall_total_us",
    "dense_proof_wall_p95_us",
    "dense_proof_wall_max_us",
)
_FRAMEGEN_OPTIONAL_SIGNATURE_QUEUE_FIELDS = (
    "dense_signature_sequence",
    "dense_signature_ready",
    "dense_signature_unavailable",
    "dense_signature_max_queue_age",
    "dense_signature_pending",
)
_FRAMEGEN_OPTIONAL_SIGNATURE_CONTEXT_FIELDS = (
    # Capability is the pre-existing identity word that prefixes the four new
    # GLES context values in the verifier's one atomic optional regex block.
    "dense_signature_capability",
    "dense_signature_requested_gles",
    "dense_signature_actual_gles_major",
    "dense_signature_actual_gles_minor",
    "dense_signature_self_tests",
)
_FRAMEGEN_OPTIONAL_V33_SCHEDULER_FIELDS = (
    "window_due_selected",
    "window_due_no_endpoint",
    "window_due_phase_clamped",
    "window_real_priority",
    "window_synthetic_quota_skipped",
    "window_presentation_epoch",
    "window_synthetic_quota_opening",
    "synthetic_quota_pending",
    "window_synthetic_selected",
    "window_synthetic_pair_created",
    "window_synthetic_not_ready",
    "window_duplicate_pair_selection",
    "last_selected_synthetic_pair",
)
_FRAMEGEN_OPTIONAL_V34_BASE_DIAGNOSTIC_FIELDS = (
    "window_presentation_callbacks",
    "dense_backward_active",
    "dense_backward_in_bounds",
    "dense_backward_cycle_valid",
    "dense_backward_photometric_valid",
    "dense_backward_texture_valid",
    "dense_backward_saturated",
    "dense_backward_out_of_bounds",
    "dense_backward_covered_tiles",
    "dense_backward_covered_tile_mask",
    "dense_forward_active",
    "dense_forward_in_bounds",
    "dense_forward_cycle_valid",
    "dense_forward_photometric_valid",
    "dense_forward_texture_valid",
    "dense_forward_saturated",
    "dense_forward_out_of_bounds",
    "dense_forward_covered_tiles",
    "dense_forward_covered_tile_mask",
)
_FRAMEGEN_OPTIONAL_V34_EXTENSION_DIAGNOSTIC_FIELDS = (
    "dense_diagnostic_cells",
    "dense_diagnostic_tiles",
    "dense_diagnostic_mask_errors",
    "dense_diagnostic_last_atlas_sequence",
    "dense_diagnostic_last_pair_sequence",
    "dense_diagnostic_last_previous_endpoint",
    "dense_diagnostic_last_current_endpoint",
)
_FRAMEGEN_OPTIONAL_V34_DIAGNOSTIC_FIELDS = (
    _FRAMEGEN_OPTIONAL_V34_BASE_DIAGNOSTIC_FIELDS +
    _FRAMEGEN_OPTIONAL_V34_EXTENSION_DIAGNOSTIC_FIELDS
)
_FRAMEGEN_OPTIONAL_V35_PACKED_MASK_FIELDS = (
    "dense_diagnostic_packed_cells",
    "dense_diagnostic_mask_layout",
    "dense_diagnostic_partition_errors",
    "dense_diagnostic_reserved_bit_errors",
)
_FRAMEGEN_OPTIONAL_ATOMIC_BLOCKS = (
    ("dense workload identity", _FRAMEGEN_OPTIONAL_WORKLOAD_FIELDS),
    ("dense wall timing", _FRAMEGEN_OPTIONAL_WALL_TIMING_FIELDS),
    ("dense signature queue", _FRAMEGEN_OPTIONAL_SIGNATURE_QUEUE_FIELDS),
    ("dense signature context", _FRAMEGEN_OPTIONAL_SIGNATURE_CONTEXT_FIELDS),
    ("v33 scheduler telemetry", _FRAMEGEN_OPTIONAL_V33_SCHEDULER_FIELDS),
    ("v34 diagnostic telemetry", _FRAMEGEN_OPTIONAL_V34_DIAGNOSTIC_FIELDS),
    ("v35 packed-mask telemetry", _FRAMEGEN_OPTIONAL_V35_PACKED_MASK_FIELDS),
)
_FRAMEGEN_OPTIONAL_FIELDS = frozenset(
    key for _label, fields in _FRAMEGEN_OPTIONAL_ATOMIC_BLOCKS
    for key in fields
)


def _decode_framegen_health_groups(
        groups: dict[str, Optional[str]]) -> dict[str, object]:
    """Decode one complete HEALTH group map without fabricating optional data.

    Legacy records predate the reduced-analysis workload identity and the v31
    wall-timing/signature blocks. Every other named field in the shared
    verifier regex is normative and must remain present. Treating an absent
    optional field as ``int(None)`` crashes after an otherwise complete
    physical run; treating it as zero would instead fabricate evidence. Keep
    each regex block typed and atomic so neither outcome is possible.
    """
    schema = int(groups.get("proof_schema_version") or 0)
    for label, fields in _FRAMEGEN_OPTIONAL_ATOMIC_BLOCKS:
        if schema in _FRAMEGEN_TIMESTAMP_SCHEMA_VERSIONS and label == "v33 scheduler telemetry":
            # Schema37 deliberately removes obsolete one-midpoint quota
            # fields. Its smaller timestamp-scheduler block is mandatory in
            # the exact V37 grammar and validated below the transport join.
            continue
        optional_present = [groups.get(key) is not None for key in fields]
        if any(optional_present) and not all(optional_present):
            raise RuntimeError(
                f"frame-generation HEALTH record has partial {label}"
            )
    missing = sorted(
        key for key, value in groups.items()
        if value is None and key not in _FRAMEGEN_OPTIONAL_FIELDS
    )
    if missing:
        raise RuntimeError(
            "frame-generation HEALTH record is missing required fields: " +
            ", ".join(missing)
        )

    decoded: dict[str, object] = {}
    try:
        for key, value in groups.items():
            if key in _FRAMEGEN_HEALTH_STRING_FIELDS:
                decoded[key] = value
            else:
                # Only the reviewed atomic compatibility blocks may be absent.
                decoded[key] = None if value is None else int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "frame-generation HEALTH record has malformed numeric telemetry"
        ) from error
    return decoded


def _decode_framegen_health_match(health: re.Match[str]) -> dict[str, object]:
    """Compatibility wrapper for one legacy single-line HEALTH match."""
    return _decode_framegen_health_groups(health.groupdict())


_FRAMEGEN_SPLIT_COMMON_KEY_FIELDS = (
    "generator", "role", "display_id", "proof_contract",
    "proof_schema_version", "health_sequence", "presents",
    "window_start_ns", "window_end_ns", "proof_evidence_presentation_epoch",
)
_FRAMEGEN_SPLIT_SCHEMA_VERSIONS = (32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 54, 55, 56, 57, 58, 59, 60, 61, 62) + (62,)
_FRAMEGEN_EPOCH_SCHEMA_VERSIONS = tuple(range(36, 52)) + (54, 55, 56, 57, 58, 59, 60, 61, 62) + (62,)
_FRAMEGEN_TIMESTAMP_SCHEMA_VERSIONS = tuple(range(37, 52)) + (54, 55, 56, 57, 58, 59, 60, 61, 62) + (62,)
_FRAMEGEN_RATIONAL_SCHEMA_VERSIONS = tuple(range(43, 52)) + (54, 55, 56, 57, 58, 59, 60, 61, 62)
_FRAMEGEN_V33_CONTRACT = (
    "dense-fragment-160x90-v33-pair-quota-scheduler-qualification-x2-presented"
)
_FRAMEGEN_V34_CONTRACT = (
    "dense-fragment-160x90-v34-diagnostic-funnel-qualification-x2-presented"
)
_FRAMEGEN_V35_CONTRACT = (
    "dense-fragment-160x90-v35-packed-mask-qualification-x2-presented"
)
_FRAMEGEN_V36_CONTRACT = (
    "dense-fragment-160x90-v36-epoch-bound-packed-mask-qualification-x2-presented"
)
_FRAMEGEN_V37_CONTRACT = (
    "dense-fragment-128x72-v37-timestamp-resample-qualification-x2-presented"
)
_FRAMEGEN_V38_CONTRACT = (
    "dense-fragment-128x72-v38-vector-trajectory-qualification-x2-presented"
)
_FRAMEGEN_V39_CONTRACT = (
    "dense-fragment-128x72-v39-present-timed-vector-trajectory-qualification-x2-presented"
)
_FRAMEGEN_V40_CONTRACT = (
    "dense-fragment-128x72-v40-temporal-flow-guidance-present-timed-vector-trajectory-qualification-x2-presented"
)
_FRAMEGEN_V41_CONTRACT = (
    "dense-fragment-128x72-v41-strict-temporal-flow-guidance-present-timed-vector-trajectory-qualification-x2-presented"
)
_FRAMEGEN_V42_CONTRACT = (
    "dense-fragment-128x72-v42-uniform-timestamp-resample-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V43_CONTRACT = (
    "dense-fragment-128x72-v43-rational-source-panel-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V44_CONTRACT = (
    "dense-fragment-128x72-v44-unique-endpoint-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V45_CONTRACT = (
    "dense-fragment-128x72-v45-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V46_CONTRACT = (
    "dense-fragment-128x72-v46-independent-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V47_CONTRACT = (
    "dense-fragment-128x72-v47-stamped-pts-loss-bound-independent-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V48_CONTRACT = (
    "dense-fragment-128x72-v48-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V49_CONTRACT = (
    "dense-fragment-128x72-v49-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V50_CONTRACT = (
    "dense-fragment-128x72-v50-iterated-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V51_CONTRACT = (
    "dense-fragment-128x72-v51-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V54_CONTRACT = (
    "dense-fragment-128x72-v54-cycle-aware-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V55_CONTRACT = (
    "dense-fragment-128x72-v55-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V56_CONTRACT = (
    "dense-fragment-128x72-v56-strong-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
)
_FRAMEGEN_V57_CONTRACT = "dense-v57-joint-cycle-rational-max2x-presented"
_FRAMEGEN_V58_CONTRACT = "dense-v58-joint-cycle-rational-max2x-presented"
_FRAMEGEN_V59_CONTRACT = "dense-v59-edge-aware-neighbor-rational-max2x-presented"
_FRAMEGEN_V60_CONTRACT = "dense-v60-independent-global-seed-rational-max2x-presented"
_FRAMEGEN_V61_CONTRACT = "dense-v61-parallel-global-seed-rational-max2x-presented"
_FRAMEGEN_V62_CONTRACT = "dense-v62-parallel-global-seed-rational-tiered-max3x-presented"
_FRAMEGEN_EMPTY_DIAGNOSTIC_COMMON_FIELDS = (
    "window_presents", "proof", "dense_proof_cells",
    "dense_diagnostic_cells", "dense_diagnostic_tiles",
    "dense_proof_atlas_enqueued", "dense_proof_atlas_completed",
    "dense_proof_atlas_pending", "dense_promotions",
    "dense_diagnostic_last_atlas_sequence",
    "dense_diagnostic_last_pair_sequence",
    "dense_diagnostic_last_previous_endpoint",
    "dense_diagnostic_last_current_endpoint",
    "dense_diagnostic_mask_errors",
) + tuple(
    f"dense_{direction}_{suffix}"
    for direction in ("backward", "forward")
    for suffix in (
        "active", "in_bounds", "cycle_valid", "photometric_valid",
        "texture_valid", "saturated", "out_of_bounds", "covered_tiles",
        "covered_tile_mask", "valid",
    )
)
_FRAMEGEN_EMPTY_DIAGNOSTIC_V35_FIELDS = (
    "dense_diagnostic_packed_cells",
    "dense_diagnostic_partition_errors",
    "dense_diagnostic_reserved_bit_errors",
)


def _require_framegen_diagnostic_callback_window(
        values: dict[str, int], *, schema: int) -> None:
    """Accept zero callbacks only for the exact post-reset empty snapshot."""
    callbacks = values["window_presentation_callbacks"]
    if callbacks > 0:
        if callbacks < values["window_presents"]:
            raise RuntimeError(
                f"frame-generation schema{schema} HEALTH has impossible "
                "diagnostic callback window"
            )
        return
    empty_fields = _FRAMEGEN_EMPTY_DIAGNOSTIC_COMMON_FIELDS
    if schema == 35:
        empty_fields += _FRAMEGEN_EMPTY_DIAGNOSTIC_V35_FIELDS
    if callbacks < 0 or any(values[key] != 0 for key in empty_fields):
        raise RuntimeError(
            f"frame-generation schema{schema} HEALTH has impossible "
            "diagnostic callback window"
        )


def _require_framegen_v34_diagnostic_hierarchy(
        groups: dict[str, Optional[str]]) -> None:
    """Reject an incomplete or internally impossible schema-34 snapshot."""
    try:
        values = {key: int(groups[key])
                  for key in _FRAMEGEN_OPTIONAL_V34_DIAGNOSTIC_FIELDS}
        for key in (
                "proof", "dense_proof_cells", "dense_backward_valid",
                "dense_forward_valid", "dense_proof_atlas_layout",
                "dense_proof_atlas_enqueued", "dense_proof_atlas_completed",
                "dense_proof_atlas_pending", "dense_promotions", "promoted",
                "window_presents"):
            values[key] = int(groups[key])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "frame-generation schema34 HEALTH lacks atomic diagnostic telemetry"
        ) from error

    cells = values["dense_diagnostic_cells"]
    tiles = values["dense_diagnostic_tiles"]
    proof = values["proof"]
    _require_framegen_diagnostic_callback_window(values, schema=34)
    if (values["dense_proof_atlas_layout"] != 2 or
            cells != proof * 48 * 27 or tiles != proof * 18 or
            values["dense_proof_cells"] != cells or
            values["dense_diagnostic_mask_errors"] != 0):
        raise RuntimeError(
            "frame-generation schema34 HEALTH has impossible diagnostic hierarchy"
        )
    for direction in ("backward", "forward"):
        counts = [values[f"dense_{direction}_{suffix}"] for suffix in (
            "active", "in_bounds", "cycle_valid", "photometric_valid",
            "texture_valid", "saturated", "out_of_bounds",
        )]
        valid = values[f"dense_{direction}_valid"]
        covered = values[f"dense_{direction}_covered_tiles"]
        mask = values[f"dense_{direction}_covered_tile_mask"]
        if (any(count < 0 or count > cells for count in counts) or
                values[f"dense_{direction}_in_bounds"] +
                values[f"dense_{direction}_out_of_bounds"] != cells or
                any(valid > values[f"dense_{direction}_{suffix}"]
                    for suffix in ("active", "in_bounds", "cycle_valid",
                                   "photometric_valid", "texture_valid")) or
                covered < 0 or covered > tiles or
                mask < 0 or mask >= (1 << 18) or
                bin(mask).count("1") > min(18, covered)):
            raise RuntimeError(
                "frame-generation schema34 HEALTH has impossible diagnostic hierarchy"
            )
    last = tuple(values[key] for key in (
        "dense_diagnostic_last_atlas_sequence",
        "dense_diagnostic_last_pair_sequence",
        "dense_diagnostic_last_previous_endpoint",
        "dense_diagnostic_last_current_endpoint",
    ))
    if proof == 0:
        binding_valid = not any(last)
    else:
        binding_valid = (
            last[0] == values["dense_proof_atlas_completed"] and
            0 < last[1] <= values["dense_promotions"] and
            0 < last[2] < last[3] <= values["promoted"] and
            last[3] == last[2] + 1
        )
    if not binding_valid:
        raise RuntimeError(
            "frame-generation schema34 HEALTH has impossible diagnostic binding"
        )


def _require_framegen_v35_diagnostic_hierarchy(
        groups: dict[str, Optional[str]]) -> None:
    """Reject an incomplete or internally impossible schema-35 snapshot.

    Layout 3 preserves the linearly sampled RG/B proof atlas and transports
    the factor masks in a distinct nearest-sampled packed tile. Consequently,
    final B validity and the individual factor-bit counts share a population
    but do not have a mathematically valid subset relationship.
    """
    numeric_fields = (
        _FRAMEGEN_OPTIONAL_V34_DIAGNOSTIC_FIELDS +
        tuple(key for key in _FRAMEGEN_OPTIONAL_V35_PACKED_MASK_FIELDS
              if key != "dense_diagnostic_mask_layout")
    )
    try:
        values = {key: int(groups[key]) for key in numeric_fields}
        for key in (
                "proof", "dense_proof_cells", "dense_backward_valid",
                "dense_forward_valid", "dense_proof_atlas_layout",
                "dense_proof_atlas_enqueued", "dense_proof_atlas_completed",
                "dense_proof_atlas_pending", "dense_promotions", "promoted",
                "window_presents"):
            values[key] = int(groups[key])
        mask_layout = groups["dense_diagnostic_mask_layout"]
        dense_variant = groups["dense_variant"]
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "frame-generation schema35 HEALTH lacks atomic packed-mask telemetry"
        ) from error

    cells = values["dense_diagnostic_cells"]
    tiles = values["dense_diagnostic_tiles"]
    proof = values["proof"]
    _require_framegen_diagnostic_callback_window(values, schema=35)
    if (values["dense_proof_atlas_layout"] != 3 or
            dense_variant != "fragment-160x90-v35-packed-mask" or
            mask_layout != "packed-nearest-bf-v1" or
            cells != proof * 48 * 27 or
            values["dense_diagnostic_packed_cells"] != cells or
            tiles != proof * 18 or
            values["dense_proof_cells"] != cells or
            values["dense_diagnostic_partition_errors"] != 0 or
            values["dense_diagnostic_reserved_bit_errors"] != 0 or
            values["dense_diagnostic_mask_errors"] != 0):
        raise RuntimeError(
            "frame-generation schema35 HEALTH has impossible packed-mask hierarchy"
        )
    for direction in ("backward", "forward"):
        counts = [values[f"dense_{direction}_{suffix}"] for suffix in (
            "active", "in_bounds", "cycle_valid", "photometric_valid",
            "texture_valid", "saturated", "out_of_bounds",
        )]
        valid = values[f"dense_{direction}_valid"]
        covered = values[f"dense_{direction}_covered_tiles"]
        mask = values[f"dense_{direction}_covered_tile_mask"]
        if (any(count < 0 or count > cells for count in counts) or
                values[f"dense_{direction}_in_bounds"] +
                values[f"dense_{direction}_out_of_bounds"] != cells or
                valid < 0 or valid > cells or
                covered < 0 or covered > tiles or
                mask < 0 or mask >= (1 << 18) or
                bin(mask).count("1") > min(18, covered)):
            raise RuntimeError(
                "frame-generation schema35 HEALTH has impossible packed-mask hierarchy"
            )
    last = tuple(values[key] for key in (
        "dense_diagnostic_last_atlas_sequence",
        "dense_diagnostic_last_pair_sequence",
        "dense_diagnostic_last_previous_endpoint",
        "dense_diagnostic_last_current_endpoint",
    ))
    if proof == 0:
        binding_valid = not any(last)
    else:
        binding_valid = (
            last[0] == values["dense_proof_atlas_completed"] and
            0 < last[1] <= values["dense_promotions"] and
            0 < last[2] < last[3] <= values["promoted"] and
            last[3] == last[2] + 1
        )
    if not binding_valid:
        raise RuntimeError(
            "frame-generation schema35 HEALTH has impossible diagnostic binding"
        )


def _require_framegen_v36_evidence_hierarchy(
        groups: dict[str, Optional[str]]) -> None:
    """Reject cross-epoch or non-conserving schema-36 proof transport."""
    try:
        values = {key: int(groups[key]) for key in (
            "proof", "window_presentation_epoch",
            "proof_evidence_presentation_epoch",
            "proof_evidence_enqueued_in_epoch", "proof_evidence_accepted",
            "proof_evidence_excluded",
            "proof_evidence_last_accepted_atlas_sequence",
            "dense_proof_atlas_layout", "dense_proof_atlas_completed",
            "dense_proof_atlas_enqueued", "dense_proof_atlas_pending",
            "dense_diagnostic_last_atlas_sequence",
            "dense_diagnostic_last_pair_sequence",
            "dense_diagnostic_last_previous_endpoint",
            "dense_diagnostic_last_current_endpoint", "dense_promotions",
            "real",
            "panel", "locked", "output", "window_presents",
            "window_generated", "window_promoted", "window_real_priority",
            "window_synthetic_selected", "window_synthetic_quota_opening",
            "window_synthetic_pair_created",
            "window_synthetic_quota_skipped", "synthetic_quota_pending",
        )}
        dense_variant = groups["dense_variant"]
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "frame-generation schema36 HEALTH lacks atomic epoch evidence"
        ) from error
    # Reuse the immutable schema35 packed-mask proof after translating only
    # the transport identity fields that schema36 intentionally supersedes.
    normalized = dict(groups)
    normalized["dense_proof_atlas_layout"] = "3"
    normalized["dense_variant"] = "fragment-160x90-v35-packed-mask"
    normalized["dense_proof_atlas_completed"] = str(
        values["proof_evidence_last_accepted_atlas_sequence"])
    # Schema36 transports accepted endpointSequence ordinals. Coalesced FIFO
    # inputs may outrun visible promotions, while lifetime realFrameCount is
    # still the exact accepted-endpoint upper bound.
    normalized["promoted"] = groups["real"]
    _require_framegen_v35_diagnostic_hierarchy(normalized)
    accepted = values["proof_evidence_accepted"]
    excluded = values["proof_evidence_excluded"]
    completed = values["dense_proof_atlas_completed"]
    last_accepted = values["proof_evidence_last_accepted_atlas_sequence"]
    binding = (last_accepted == 0 if accepted == 0 else
               0 < last_accepted <= completed and
               values["dense_diagnostic_last_atlas_sequence"] == last_accepted)
    endpoint_binding = (
        not any(values[key] for key in (
            "dense_diagnostic_last_pair_sequence",
            "dense_diagnostic_last_previous_endpoint",
            "dense_diagnostic_last_current_endpoint"))
        if accepted == 0 else
        0 < values["dense_diagnostic_last_pair_sequence"] <=
            values["dense_promotions"] and
        0 < values["dense_diagnostic_last_previous_endpoint"] <
            values["dense_diagnostic_last_current_endpoint"] <= values["real"] and
        values["dense_diagnostic_last_current_endpoint"] ==
            values["dense_diagnostic_last_previous_endpoint"] + 1
    )
    output_failures = frame_gen._v36_output_accounting_hierarchy(values)
    if (values["dense_proof_atlas_layout"] != 4 or
            dense_variant != "fragment-160x90-v36-epoch-bound-packed-mask" or
            values["proof_evidence_presentation_epoch"] !=
                values["window_presentation_epoch"] or
            not 0 <= values["proof_evidence_enqueued_in_epoch"] <= 120 or
            accepted != values["proof"] or
            completed != accepted + excluded or
            values["dense_proof_atlas_enqueued"] !=
                completed + values["dense_proof_atlas_pending"] or
            not binding or not endpoint_binding or output_failures):
        raise RuntimeError(
            "frame-generation schema36 HEALTH has impossible epoch evidence"
        )


def _framegen_health_transport_records(
        log: str) -> list[dict[str, object]]:
    """Parse complete legacy or split schema-32..51/54..57 HEALTH records in order.

    A split record exists only after its base and immediately following dense
    extension have both been observed. Interleaved unrelated logcat records
    are harmless, but another frame-generator health/attach/proof transport
    record makes the pending base stale and is rejected. This prevents a
    truncated or later-session extension from being joined by coincidence.
    """
    base_patterns = tuple(pattern for pattern in (
        getattr(frame_gen, "HEALTH_BASE_V62", None),
        getattr(frame_gen, "HEALTH_BASE_V61", None),
        getattr(frame_gen, "HEALTH_BASE_V60", None),
        getattr(frame_gen, "HEALTH_BASE_V59", None),
        getattr(frame_gen, "HEALTH_BASE_V58", None),
        getattr(frame_gen, "HEALTH_BASE_V57", None),
        getattr(frame_gen, "HEALTH_BASE_V56", None),
        getattr(frame_gen, "HEALTH_BASE_V55", None),
        getattr(frame_gen, "HEALTH_BASE_V54", None),
        getattr(frame_gen, "HEALTH_BASE_V51", None),
        getattr(frame_gen, "HEALTH_BASE_V50", None),
        getattr(frame_gen, "HEALTH_BASE_V49", None),
        getattr(frame_gen, "HEALTH_BASE_V48", None),
        getattr(frame_gen, "HEALTH_BASE_V47", None),
        getattr(frame_gen, "HEALTH_BASE_V46", None),
        getattr(frame_gen, "HEALTH_BASE_V45", None),
        getattr(frame_gen, "HEALTH_BASE_V44", None),
        getattr(frame_gen, "HEALTH_BASE_V43", None),
        getattr(frame_gen, "HEALTH_BASE_V42", None),
        getattr(frame_gen, "HEALTH_BASE_V41", None),
        getattr(frame_gen, "HEALTH_BASE_V40", None),
        getattr(frame_gen, "HEALTH_BASE_V39", None),
        getattr(frame_gen, "HEALTH_BASE_V38", None),
        getattr(frame_gen, "HEALTH_BASE_V37", None),
        getattr(frame_gen, "HEALTH_BASE_V36", None),
        getattr(frame_gen, "HEALTH_BASE_V35", None),
        getattr(frame_gen, "HEALTH_BASE_V34", None),
        getattr(frame_gen, "HEALTH_BASE_V33", None),
        getattr(frame_gen, "HEALTH_BASE", None),
    ) if pattern is not None)
    extension_patterns = tuple(pattern for pattern in (
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V62", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V61", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V60", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V59", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V58", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V57", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V56", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V55", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V54", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V51", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V50", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V49", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V48", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V47", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V46", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V45", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V44", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V43", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V42", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V41", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V40", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V39", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V38", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V37", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V36", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V35", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION_V34", None),
        getattr(frame_gen, "HEALTH_DENSE_EXTENSION", None),
    ) if pattern is not None)
    rational_clock_patterns = tuple(pattern for pattern in (
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V62", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V61", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V60", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V59", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V58", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V57", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V56", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V55", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V54", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V51", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V50", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V49", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V48", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V47", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V46", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V45", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V44", None),
        getattr(frame_gen, "HEALTH_RATIONAL_CLOCK_V43", None),
    ) if pattern is not None)
    records: list[dict[str, object]] = []
    # Split base/extension pairing is per generator stream: each generator
    # emits its base and dense extension adjacently on its own handler
    # thread, but two live generators (the dual-screen GamePad pair) publish
    # into one shared logcat, so another stream's records may legitimately
    # land between one stream's base and extension. Keying by strict process
    # identity plus generator id keeps every anti-splicing guarantee within
    # a stream while tolerating exactly that physical interleaving.
    pending: dict[tuple[int, str],
                  tuple[dict[str, Optional[str]], int, int,
                        Optional[dict[str, Optional[str]]]]] = {}

    def strict_pid(line: str) -> int:
        pid = frame_gen.framegen_line_pid(line)
        if pid is None:
            raise RuntimeError(
                "frame-generation HEALTH record has no strict process identity"
            )
        return pid

    def stale_pending(key: tuple[int, str], reason: str) -> None:
        if key in pending:
            if pending[key][3] is not None:
                raise RuntimeError(
                    "frame-generation rational-clock HEALTH lacks its required "
                    f"rational-clock completion before {reason}"
                )
            raise RuntimeError(
                "frame-generation split HEALTH base lacks its immediate dense "
                f"extension before {reason}"
            )

    for line_index, line in enumerate(log.splitlines()):
        base_matches = [pattern.search(line) for pattern in base_patterns]
        base_matches = [match for match in base_matches if match is not None]
        if len(base_matches) > 1:
            raise RuntimeError("ambiguous frame-generation HEALTH base record")
        base = base_matches[0] if base_matches else None
        extension_matches = [pattern.search(line)
                             for pattern in extension_patterns]
        extension_matches = [match for match in extension_matches
                             if match is not None]
        if len(extension_matches) > 1:
            raise RuntimeError(
                "ambiguous frame-generation HEALTH dense extension record"
            )
        extension = extension_matches[0] if extension_matches else None
        rational_matches = [pattern.search(line)
                            for pattern in rational_clock_patterns]
        rational_matches = [match for match in rational_matches
                            if match is not None]
        if len(rational_matches) > 1:
            raise RuntimeError(
                "ambiguous frame-generation rational-clock HEALTH record")
        rational_clock = rational_matches[0] if rational_matches else None
        legacy = frame_gen.HEALTH.search(line)

        if "Presentation health base" in line and base is None:
            raise RuntimeError(
                "frame-generation split HEALTH base is malformed or truncated"
            )
        if "Presentation health dense-extension" in line and extension is None:
            raise RuntimeError(
                "frame-generation split HEALTH dense extension is malformed or truncated"
            )
        if ("Presentation health rational-clock" in line and
                rational_clock is None):
            raise RuntimeError(
                "frame-generation rational-clock HEALTH is malformed or truncated"
            )
        matches = sum(value is not None for value in (
            base, extension, rational_clock, legacy))
        if matches > 1:
            raise RuntimeError("ambiguous frame-generation HEALTH transport record")

        if base is not None:
            base_stream = (strict_pid(line), str(base.group("generator")))
            stale_pending(base_stream, "another base for this generator")
            groups = base.groupdict()
            schema = int(groups.get("proof_schema_version", "0"))
            scheduler_present = [groups.get(key) is not None
                                 for key in _FRAMEGEN_OPTIONAL_V33_SCHEDULER_FIELDS]
            diagnostic_present = [groups.get(key) is not None for key in
                                  _FRAMEGEN_OPTIONAL_V34_BASE_DIAGNOSTIC_FIELDS]
            if (schema not in _FRAMEGEN_SPLIT_SCHEMA_VERSIONS or
                    groups.get("dense_extension_required") != "1"):
                raise RuntimeError(
                    "frame-generation split HEALTH base has an invalid schema contract"
                )
            if schema == 32 and any(scheduler_present):
                raise RuntimeError(
                    "frame-generation schema32 HEALTH carries v33 scheduler telemetry"
                )
            if schema in (32, 33) and any(diagnostic_present):
                raise RuntimeError(
                    "frame-generation pre-v34 HEALTH carries diagnostic telemetry"
                )
            if schema == 33 and (
                    not all(scheduler_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V33_CONTRACT):
                raise RuntimeError(
                    "frame-generation schema33 HEALTH lacks its exact scheduler contract"
                )
            if schema == 33 and (
                    int(groups["window_synthetic_selected"]) >
                    int(groups["window_synthetic_pair_created"]) or
                    int(groups["window_duplicate_pair_selection"]) != 0):
                raise RuntimeError(
                    "frame-generation schema33 HEALTH has impossible pair telemetry"
                )
            if schema == 34 and (
                    not all(scheduler_present) or
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V34_CONTRACT):
                raise RuntimeError(
                    "frame-generation schema34 HEALTH lacks its exact diagnostic contract"
                )
            if schema == 35 and (
                    not all(scheduler_present) or
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V35_CONTRACT):
                raise RuntimeError(
                    "frame-generation schema35 HEALTH lacks its exact packed-mask contract"
                )
            if schema == 36 and (
                    not all(scheduler_present) or
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V36_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None):
                raise RuntimeError(
                    "frame-generation schema36 HEALTH lacks its exact epoch-bound contract"
                )
            if schema == 37 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V37_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema37 HEALTH lacks its exact timestamp contract"
                )
            if schema == 38 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V38_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema38 HEALTH lacks its exact vector-trajectory contract"
                )
            if schema == 39 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V39_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema39 HEALTH lacks its exact present-timed contract"
                )
            if schema == 40 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V40_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema40 HEALTH lacks its exact temporal-flow contract"
                )
            if schema == 41 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V41_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema41 HEALTH lacks its exact strict-temporal-flow contract"
                )
            if schema == 42 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V42_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema42 HEALTH lacks its exact uniform timestamp-resample contract"
                )
            if schema == 43 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V43_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema43 HEALTH lacks its exact rational-clock contract"
                )
            if schema == 44 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V44_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema44 HEALTH lacks its exact unique-endpoint rational-clock contract"
                )
            if schema == 45 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V45_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema45 HEALTH lacks its exact spatial-consensus rational-clock contract"
                )
            if schema == 46 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V46_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema46 HEALTH lacks its exact independent-bidirectional spatial-consensus rational-clock contract"
                )
            if schema == 47 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V47_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema47 HEALTH lacks its exact stamped-PTS loss-bound contract"
                )
            if schema == 48 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V48_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema48 HEALTH lacks its exact reciprocal-proposal stamped-PTS loss-bound contract"
                )
            if schema == 49 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V49_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema49 HEALTH lacks its exact multilevel-reciprocal-proposal stamped-PTS loss-bound contract"
                )
            if schema == 50 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V50_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema50 HEALTH lacks its exact iterated-multilevel-reciprocal-proposal stamped-PTS loss-bound contract"
                )
            if schema == 51 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V51_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema51 HEALTH lacks its exact cost-tested bidirectional-refinement stamped-PTS loss-bound contract"
                )
            if schema == 54 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V54_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema54 HEALTH lacks its exact cycle-aware cost-tested bidirectional-refinement stamped-PTS loss-bound contract"
                )
            if schema == 55 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V55_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema55 HEALTH lacks its exact cycle-regularized cost-tested bidirectional-refinement stamped-PTS loss-bound contract"
                )
            if schema == 56 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V56_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema56 HEALTH lacks its exact strong-cycle-regularized cost-tested bidirectional-refinement stamped-PTS loss-bound contract"
                )
            if schema == 57 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V57_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema57 HEALTH lacks its exact joint-cycle rational max2x contract"
                )
            if schema == 58 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V58_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema58 HEALTH lacks its exact joint-cycle rational max2x contract"
                )
            if schema == 59 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V59_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema59 HEALTH lacks its exact edge-aware-neighbor rational max2x contract"
                )
            if schema == 60 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V60_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema60 HEALTH lacks its exact independent-global-seed rational max2x contract"
                )
            if schema == 61 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V61_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema61 HEALTH lacks its exact parallel-global-seed rational max2x contract"
                )
            if schema == 62 and (
                    not all(diagnostic_present) or
                    groups.get("proof_contract") != _FRAMEGEN_V62_CONTRACT or
                    groups.get("proof_evidence_presentation_epoch") is None or
                    groups.get("proof_evidence_enqueued_in_epoch") is None or
                    groups.get("presentation_timing_mode") !=
                        "egl-android-next-vsync" or
                    groups.get("cadence_reject_consecutive_windows") != "3" or
                    any(groups.get(key) is None for key in (
                        "window_real_priority", "window_presentation_epoch",
                        "window_synthetic_selected",
                        "window_duplicate_pair_selection",
                        "endpoint_fifo_coalesced",
                        "endpoint_timestamp_corrections",
                        "dense_diagnostic_last_target_source_ns"))):
                raise RuntimeError(
                    "frame-generation schema62 HEALTH lacks its exact parallel-global-seed rational tiered max3x contract"
                )
            pending[base_stream] = (groups, base_stream[0], line_index, None)
            continue

        if extension is not None:
            extension_pid = strict_pid(line)
            extension_groups = extension.groupdict()
            extension_stream = (extension_pid,
                                str(extension_groups.get("generator")))
            if extension_stream not in pending:
                raise RuntimeError(
                    "frame-generation split HEALTH has an orphan dense extension"
                )
            base_groups, base_pid, _base_line_index, prior_extension = \
                pending[extension_stream]
            if prior_extension is not None:
                raise RuntimeError(
                    "frame-generation split HEALTH has a duplicate dense extension"
                )
            mismatched = [
                key for key in _FRAMEGEN_SPLIT_COMMON_KEY_FIELDS
                if base_groups.get(key) != extension_groups.get(key)
            ]
            if extension_pid != base_pid or mismatched:
                detail = ", ".join(mismatched) if mismatched else "pid"
                raise RuntimeError(
                    "frame-generation split HEALTH extension identity mismatch: " +
                    detail
                )
            if int(extension_groups["proof_schema_version"]) in _FRAMEGEN_RATIONAL_SCHEMA_VERSIONS:
                pending[extension_stream] = (
                    base_groups, base_pid, _base_line_index, extension_groups)
                continue
            # Decode the exact grammar that matched this schema. Unioning all
            # version grammars would fabricate absent v34 names in a v32/33
            # record and make immutable older evidence appear truncated.
            names = (set(frame_gen.HEALTH.groupindex) |
                     set(base_groups) | set(extension_groups))
            merged: dict[str, Optional[str]] = {}
            for key in names:
                base_value = base_groups.get(key)
                extension_value = extension_groups.get(key)
                if (base_value is not None and extension_value is not None and
                        base_value != extension_value):
                    raise RuntimeError(
                        "frame-generation split HEALTH duplicates a conflicting " + key
                    )
                merged[key] = (base_value if base_value is not None
                               else extension_value)
            record = _decode_framegen_health_groups(merged)
            if int(record["proof_schema_version"]) == 34:
                _require_framegen_v34_diagnostic_hierarchy(merged)
            elif int(record["proof_schema_version"]) == 35:
                _require_framegen_v35_diagnostic_hierarchy(merged)
            elif int(record["proof_schema_version"]) == 36:
                _require_framegen_v36_evidence_hierarchy(merged)
            elif int(record["proof_schema_version"]) == 37:
                failures = (frame_gen._v37_diagnostic_hierarchy(record) +
                            frame_gen._v37_output_accounting_hierarchy(record))
                if failures:
                    raise RuntimeError(
                        "frame-generation schema37 HEALTH is impossible: " +
                        "; ".join(failures)
                    )
            elif int(record["proof_schema_version"]) == 38:
                failures = (frame_gen._v37_diagnostic_hierarchy(record) +
                            frame_gen._v37_output_accounting_hierarchy(record))
                if failures:
                    raise RuntimeError(
                        "frame-generation schema38 HEALTH is impossible: " +
                        "; ".join(failures)
                    )
            elif int(record["proof_schema_version"]) == 39:
                failures = (frame_gen._v37_diagnostic_hierarchy(record) +
                            frame_gen._v37_output_accounting_hierarchy(record))
                if failures:
                    raise RuntimeError(
                        "frame-generation schema39 HEALTH is impossible: " +
                        "; ".join(failures)
                    )
            elif int(record["proof_schema_version"]) == 40:
                failures = (frame_gen._v37_diagnostic_hierarchy(record) +
                            frame_gen._v37_output_accounting_hierarchy(record))
                if failures:
                    raise RuntimeError(
                        "frame-generation schema40 HEALTH is impossible: " +
                        "; ".join(failures)
                    )
            elif int(record["proof_schema_version"]) == 41:
                failures = (frame_gen._v37_diagnostic_hierarchy(record) +
                            frame_gen._v37_output_accounting_hierarchy(record))
                if failures:
                    raise RuntimeError(
                        "frame-generation schema41 HEALTH is impossible: " +
                        "; ".join(failures)
                    )
            elif int(record["proof_schema_version"]) == 42:
                failures = (frame_gen._v37_diagnostic_hierarchy(record) +
                            frame_gen._v37_output_accounting_hierarchy(record))
                if failures:
                    raise RuntimeError(
                        "frame-generation schema42 HEALTH is impossible: " +
                        "; ".join(failures)
                    )
            record.update({"pid": base_pid, "line_index": line_index})
            records.append(record)
            del pending[extension_stream]
            continue

        if rational_clock is not None:
            clock_pid = strict_pid(line)
            clock_groups = rational_clock.groupdict()
            clock_stream = (clock_pid, str(clock_groups.get("generator")))
            if clock_stream not in pending or pending[clock_stream][3] is None:
                raise RuntimeError(
                    "frame-generation HEALTH has an orphan rational-clock record"
                )
            base_groups, base_pid, _base_line_index, extension_groups = \
                pending[clock_stream]
            assert extension_groups is not None
            mismatched = [
                key for key in _FRAMEGEN_SPLIT_COMMON_KEY_FIELDS
                if base_groups.get(key) != clock_groups.get(key)
            ]
            if clock_pid != base_pid or mismatched:
                detail = ", ".join(mismatched) if mismatched else "pid"
                raise RuntimeError(
                    "frame-generation rational-clock HEALTH identity mismatch: " +
                    detail
                )
            names = (set(frame_gen.HEALTH.groupindex) | set(base_groups) |
                     set(extension_groups) | set(clock_groups))
            merged: dict[str, Optional[str]] = {}
            for key in names:
                values = [groups.get(key) for groups in (
                    base_groups, extension_groups, clock_groups)]
                present_values = [value for value in values if value is not None]
                if len(set(present_values)) > 1:
                    raise RuntimeError(
                        "frame-generation rational-clock HEALTH duplicates a conflicting " +
                        key
                    )
                merged[key] = present_values[0] if present_values else None
            record = _decode_framegen_health_groups(merged)
            failures = (frame_gen._v37_diagnostic_hierarchy(record) +
                        frame_gen._v37_output_accounting_hierarchy(record) +
                        frame_gen._v43_rational_clock_hierarchy(record))
            if failures:
                raise RuntimeError(
                    "frame-generation rational-clock HEALTH is impossible: " +
                    "; ".join(failures)
                )
            record.update({"pid": base_pid, "line_index": line_index})
            records.append(record)
            del pending[clock_stream]
            continue

        if legacy is not None:
            stale_pending((strict_pid(line), str(legacy.group("generator"))),
                          "a legacy HEALTH record")
            if int(legacy.group("proof_schema_version")) >= 32:
                raise RuntimeError(
                    "frame-generation schema32+ HEALTH is not split into base/extension"
                )
            record = _decode_framegen_health_match(legacy)
            record.update({"pid": strict_pid(line), "line_index": line_index})
            records.append(record)
            continue


        if pending:
            lifecycle = (frame_gen.ATTACHED.search(line) or
                         frame_gen.PROOF_STATE.search(line))
            if lifecycle is not None:
                stale_pending((strict_pid(line), str(lifecycle.group(1))),
                              "a generator lifecycle record")

    for key in pending:
        stale_pending(key, "end of log")
    return records


def _framegen_health_records(log: str, role: str,
                             display_id: int) -> list[dict[str, object]]:
    """Decode the verifier's exact health records without inventing time."""
    records = [
        record for record in _framegen_health_transport_records(log)
        if record["role"] == role and int(record["display_id"]) == display_id
    ]
    records.sort(key=lambda value: int(value["window_end_ns"]))
    return records


def _framegen_health_schema(record: dict[str, object]) -> int:
    """Return zero only for pre-schema synthetic/legacy health fixtures."""
    value = record.get("proof_schema_version")
    return 0 if value is None else int(value)


def _steady_framegen_segment(
        records: list[dict[str, object]], role: str, display_id: int, *,
        actual_present_timestamps: Optional[list[int]] = None,
) -> tuple[dict, dict]:
    """Select a current or raw-latency-bound >=11-second steady segment."""
    if not records:
        raise RuntimeError(f"no {role}/display-{display_id} health records")
    identities = {(int(row["pid"]), int(row["generator"])) for row in records}
    if len(identities) != 1:
        raise RuntimeError(
            f"{role}/display-{display_id} health mixes generator identities"
        )
    # Every tier the goal's panel policy names is a legal steady tier: on the
    # 120 Hz panel 20/30/40/50/60 -> 40/60/80/100/120. The verifier accepts
    # 20 in every check; omitting it here made a genuinely settled,
    # churn-free 20-tier stream (SM3DW after starvation demotion, run
    # wiiu20) unqualifiable despite 30-second clean segments.
    allowed = {20, 30, 40, 50, 60}

    def candidate(end_index: int) -> Optional[tuple[dict, dict]]:
        end = records[end_index]
        tier = int(end["locked"])
        if tier not in allowed:
            return None
        # Hand-authored legacy/unit-test records predate schema-tagged HEALTH.
        # Treat only explicit epoch-bound schemas as such; never let one fall
        # through into the backward-compatible legacy run.
        schema = _framegen_health_schema(end)
        presentation_epoch = (int(end["window_presentation_epoch"])
                              if schema in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS else None)
        evidence_epoch = (int(end["proof_evidence_presentation_epoch"])
                          if schema in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS else None)
        if schema in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS and presentation_epoch != evidence_epoch:
            return None

        def same_run(record: dict[str, object]) -> bool:
            if int(record["locked"]) != tier:
                return False
            if schema not in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS:
                return _framegen_health_schema(record) not in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS
            same_epoch = (_framegen_health_schema(record) == schema and
                    int(record["window_presentation_epoch"]) ==
                        presentation_epoch and
                    int(record["proof_evidence_presentation_epoch"]) ==
                        evidence_epoch)
            if not same_epoch:
                return False
            if schema in _FRAMEGEN_RATIONAL_SCHEMA_VERSIONS:
                return all(record.get(key) == end.get(key) for key in (
                    "target_millihz", "panel_millihz",
                    "panel_scans_per_output", "source_clock_kind"))
            return True

        baseline_index = end_index
        while baseline_index > 0 and same_run(records[baseline_index - 1]):
            baseline_index -= 1
        if schema in _FRAMEGEN_TIMESTAMP_SCHEMA_VERSIONS:
            # A buffered-source underrun does not change the presentation
            # epoch: the renderer deliberately leaves that output slot empty
            # and resumes when the exact successor arrives.  It must not be
            # hidden inside a supposedly steady qualification segment,
            # though.  Treat the last affected HEALTH record as the evidence
            # baseline so only the clean suffix after it can qualify.  The
            # duration and proof-delta checks below/at the caller then force a
            # genuinely new >=11-second, >=30-proof run instead of accepting
            # historical evidence from before the gap.
            last_unbuffered = None
            for index in range(baseline_index, end_index + 1):
                record = records[index]
                elapsed_ns = (int(record["window_end_ns"]) -
                              int(record["window_start_ns"]))
                presents = int(record.get("window_presents", 0))
                output = int(record.get("output", 0))
                cadence_healthy = (elapsed_ns > 0 and output > 0 and
                                   presents * 1_000_000_000 * 100 >=
                                   output * elapsed_ns * 96)
                if (int(record["window_due_no_endpoint"]) != 0 and
                        not cadence_healthy):
                    last_unbuffered = index
                # A BURST of timestamp corrections / FIFO coalesces (>=3 in
                # one window) is material source loss for that stretch; a
                # JIT warm-up commonly accrues such bursts and then stays
                # frozen for a long steady scene (psp1 2026-08-17: 40 in the
                # first windows, then 28+ clean seconds). Advance the
                # baseline past the last burst so the loss-free suffix can
                # qualify. A sparse drip (1-2 in a window) is bounded jitter
                # the resampler repaired truthfully; the caller's segment
                # check tolerates a bounded total instead of demanding zero
                # (psp2: one correction every ~20 s starved the 30-sample
                # proof budget under a zero-tolerance baseline reset).
                if index > 0:
                    previous = records[index - 1]
                    if ("endpoint_fifo_coalesced" in record and
                            "endpoint_fifo_coalesced" in previous):
                        accrual = (abs(int(record["endpoint_fifo_coalesced"]) -
                                       int(previous[
                                           "endpoint_fifo_coalesced"])) +
                                   abs(int(record[
                                       "endpoint_timestamp_corrections"]) -
                                       int(previous[
                                           "endpoint_timestamp_corrections"])))
                        if accrual >= 3:
                            last_unbuffered = index
            if last_unbuffered is not None:
                baseline_index = last_unbuffered
        baseline = records[baseline_index]
        if (end_index - baseline_index < 2 or
                int(end["window_end_ns"]) -
                int(baseline["window_end_ns"]) < 11_000_000_000):
            return None
        if schema in _FRAMEGEN_RATIONAL_SCHEMA_VERSIONS:
            clock_failures = frame_gen._v43_segment_clock_hierarchy(
                records[baseline_index:end_index + 1])
            if clock_failures:
                return None
        segment_id = f"steady-{role}-display-{display_id}-{tier}"
        segment = {
            "segmentId": segment_id,
            "kind": "steady",
            "startWindowEndNs": int(baseline["window_end_ns"]),
            "proofBaselineWindowEndNs": int(baseline["window_end_ns"]),
            "endWindowEndNs": int(end["window_end_ns"]),
            "maxFallbackPresents": 0,
            "expectedLockedFps": tier,
        }
        if schema in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS:
            segment["expectedPresentationEpoch"] = presentation_epoch
        return segment, end

    if actual_present_timestamps is None:
        selected = candidate(len(records) - 1)
        if selected is None:
            raise RuntimeError(
                f"{role}/display-{display_id} current tier is not steady for 11 seconds"
            )
        return selected

    minimum_overlap = max(31, int(len(actual_present_timestamps) * 0.25))
    candidates: list[tuple[int, dict, dict]] = []
    for end_index, row in enumerate(records):
        overlap = sum(
            int(row["window_start_ns"]) <= timestamp <=
            int(row["window_end_ns"])
            for timestamp in actual_present_timestamps
        )
        if overlap < minimum_overlap:
            continue
        selected = candidate(end_index)
        if selected is not None:
            candidates.append((overlap, selected[0], selected[1]))
    if not candidates:
        raise RuntimeError(
            f"{role}/display-{display_id} has no latency-overlapping "
            "real >=11-second steady tier"
        )
    maximum_overlap = max(item[0] for item in candidates)
    best = [item for item in candidates if item[0] == maximum_overlap]
    if len(best) != 1:
        raise RuntimeError(
            f"{role}/display-{display_id} latency overlap is ambiguous"
        )
    return best[0][1], best[0][2]


# A title may legitimately traverse several measured source tiers during
# launch/tutorial automation before settling.  At roughly two asynchronous
# proof samples per second, a late stable epoch still needs fifteen seconds
# after the 11-second tier requirement.  Keep one hard shared deadline, but
# leave enough bounded headroom for that honest post-transition evidence.
# PS2's second physical launch can spend roughly a minute in the opening movie
# before the source tier and epoch settle, after which the unchanged evidence
# contract still needs 11 clean seconds and 30 asynchronous proof samples.
# Leave a bounded capture margin for the immediate SurfaceFlinger snapshot;
# this changes no cadence, content, overlap, or proof threshold.
# 90 s was too tight for phase-2 titles that JIT-warm through their opening
# scene (God of War on ARMSX2 needed most of that before an 11-second
# correction-free steady window could exist). The evidence requirements are
# unchanged; only the wall-clock allowance grew. Latency capture receives its
# own bounded window from the latest steady confirmation so a slow warm-up
# cannot starve it, under an absolute hard cap for the whole capture phase.
FRAMEGEN_CURRENT_STEADY_DEADLINE_SECONDS = 180.0
FRAMEGEN_ADAPTER_STEADY_DEADLINE_SECONDS = 480.0
FRAMEGEN_ADAPTER_TOTAL_CAPTURE_CAP_SECONDS = 720.0
FRAMEGEN_LATENCY_CAPTURE_SECONDS = 90.0
FRAMEGEN_TOTAL_CAPTURE_CAP_SECONDS = 420.0
# F-Zero's input-free attract loop can place roughly 140 seconds of title,
# split-screen, and non-race material between independently usable one-player
# races.  A three-segment/60-second campaign can therefore need two complete
# inter-race gaps after its first component.  This is wall-clock allowance
# only: every component still needs its own >=11-second timing epoch, raw
# SurfaceFlinger overlap, moving generated proof, and unique identity.  Stay
# below the physical harness's independent eighteen-minute process watchdog.
# Five observed ~13-second one-player attract components are needed to exceed
# sixty moving seconds; the prior 600-second cap ended only seconds before the
# fifth component could be captured after four honest proof/core rearms.
FZERO_RIFE_CAMPAIGN_TOTAL_CAPTURE_CAP_SECONDS = 690.0


def _framegen_deadline_remaining(deadline: float, failure: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(failure)
    return remaining


def _framegen_bounded_capture(
        deadline: float, failure: str,
        capture: Callable[[float], object]) -> object:
    """Run one capture inside the shared absolute frame-proof deadline."""
    remaining = _framegen_deadline_remaining(deadline, failure)
    try:
        result = capture(remaining)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(failure) from error
    _framegen_deadline_remaining(deadline, failure)
    return result


def _wait_for_current_framegen_steady(
        log_reader: Callable[[], str], streams: list[tuple[str, int]], *,
        deadline: float, poll_seconds: float = 0.1,
        any_of: bool = False,
) -> str:
    """Wait boundedly for every live stream's current trailing steady tier.

    With ``any_of`` (DS only), ONE steady stream satisfies the wait: DS games
    choose their own gameplay screen (Hunters top / Castlevania touch), and
    the non-gameplay screen legitimately idles static with no proof-schema
    tier at all. The gate afterwards still demands full evidence from a
    stream that qualifies.
    """
    last_failure = "no complete HEALTH record"
    while True:
        timeout_failure = (
            "timed out waiting for a current >=11-second frame-generation "
            f"steady tier: {last_failure}"
        )
        _framegen_deadline_remaining(deadline, timeout_failure)
        log = log_reader()
        ready = True
        any_ready = False
        for role, display_id in streams:
            try:
                records = _framegen_health_records(log, role, display_id)
                segment, end = _steady_framegen_segment(
                    records, role, display_id,
                )
                # Live pre-proof HEALTH is schema 22. Accepting that trailing
                # 20-lock as "steady" lets capture fire before qualification
                # proof exists (nds8/nds9 v31/v32). Legacy unit fixtures have
                # no schema tag (0) and remain valid.
                schema = _framegen_health_schema(end)
                if schema != 0 and schema not in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS:
                    raise RuntimeError(
                        f"{role}/display-{display_id} current trailing HEALTH "
                        "is not a qualification proof schema"
                    )
                baseline = next(
                    row for row in records
                    if int(row["window_end_ns"]) ==
                    int(segment["proofBaselineWindowEndNs"])
                )
                if int(end["proof"]) - int(baseline["proof"]) < 30:
                    raise RuntimeError(
                        f"{role}/display-{display_id} current steady tier "
                        "has fewer than 30 segment proof samples"
                    )
                if _framegen_health_schema(end) in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS:
                    proof_delta = int(end["proof"]) - int(baseline["proof"])
                    accepted_delta = int(end["proof_evidence_accepted"]) - int(
                        baseline["proof_evidence_accepted"])
                    excluded_delta = int(end["proof_evidence_excluded"]) - int(
                        baseline["proof_evidence_excluded"])
                    if (int(baseline["dense_proof_atlas_pending"]) != 0 or
                            accepted_delta != proof_delta or
                            excluded_delta != 0):
                        raise RuntimeError(
                            f"{role}/display-{display_id} current steady tier "
                            "has cross-epoch or incomplete proof evidence"
                        )
                if _framegen_health_schema(end) in _FRAMEGEN_TIMESTAMP_SCHEMA_VERSIONS:
                    # Bounded tolerance (<=2 total): a repaired one-off
                    # timestamp jitter is counted, visible evidence — not
                    # hidden — while material loss still fails. Zero
                    # tolerance starved the proof budget on a source with
                    # one correction every ~20 s (psp2, 2026-08-17).
                    source_loss = (
                        abs(int(end["endpoint_fifo_coalesced"]) -
                            int(baseline["endpoint_fifo_coalesced"])) +
                        abs(int(end["endpoint_timestamp_corrections"]) -
                            int(baseline["endpoint_timestamp_corrections"])))
                    if source_loss > 2:
                        raise RuntimeError(
                            f"{role}/display-{display_id} current steady tier "
                            "contains timestamp-resampler source loss"
                        )
            except RuntimeError as failure:
                ready = False
                # Under any_of report the FIRST stream's failure: the
                # secondary's "no health records" otherwise masked why the
                # primary never qualified (Wii U run wiiu-b50, 2026-09-02).
                if not any_of or (role, display_id) == streams[0]:
                    last_failure = str(failure)
                if not any_of:
                    break
                continue
            any_ready = True
        if ready or (any_of and any_ready):
            _framegen_deadline_remaining(deadline, timeout_failure)
            return log
        timeout_failure = (
            "timed out waiting for a current >=11-second frame-generation "
            f"steady tier: {last_failure}"
        )
        remaining = _framegen_deadline_remaining(deadline, timeout_failure)
        time.sleep(min(poll_seconds, remaining))


def _wait_for_current_rife_steady(
        log_reader: Callable[[], str], role: str, display_id: int, *,
        deadline: float, poll_seconds: float = 0.5,
        excluded_identities: frozenset[tuple[int, int, int]] = frozenset(),
) -> str:
    """Wait for the latest app-owned RIFE epoch to span eleven seconds.

    RIFE deliberately emits ``App swap cadence`` rather than the built-in
    generator's split HEALTH records.  Treating the two transports as if they
    were interchangeable made the strict runner wait forever after the RIFE
    renderer had already established a healthy physical cadence.
    """
    last_failure = "no complete app-owned RIFE timing record"
    while True:
        timeout_failure = (
            "timed out waiting for a current >=11-second app-owned RIFE "
            f"timing epoch: {last_failure}"
        )
        _framegen_deadline_remaining(deadline, timeout_failure)
        log = log_reader()
        try:
            report = rife_timing.verify_timing(
                log, role=role, display_id=display_id,
                minimum_span_ns=rife_timing.MIN_RUNTIME_SPAN_NS,
            )
        except (ValueError, RuntimeError) as failure:
            last_failure = str(failure)
        else:
            identity = (int(report["generator"]),
                        int(report["presentationEpoch"]),
                        int(report["timingWindow"]))
            if identity in excluded_identities:
                last_failure = (
                    "latest app-owned RIFE timing window was already "
                    f"captured: {identity}"
                )
                remaining = _framegen_deadline_remaining(
                    deadline, timeout_failure)
                time.sleep(min(poll_seconds, remaining))
                continue
            _framegen_deadline_remaining(deadline, timeout_failure)
            return log
        remaining = _framegen_deadline_remaining(deadline, timeout_failure)
        time.sleep(min(poll_seconds, remaining))


def _set_rife_campaign_proof_state(
        adb: Path, serial: str, log_reader: Callable[[], str],
        generator: int, enabled: bool, *, deadline: float,
        poll_seconds: float = 0.1) -> dict[str, object]:
    """Publish and observe one real RIFE qualification boundary.

    The proof global is already the renderer's shell-only live authorization
    switch. Turning it off makes the external path Direct, drains retained
    presentation state, and publishes a scheduler epoch; turning it back on
    requires the ordinary cold prime before generated output is selectable.
    A core reset alone does none of those things, so it cannot make two timing
    campaign components independent. Require both renderer-emitted state
    markers here rather than treating a successful settings write as proof
    that the GL thread consumed it.
    """
    if generator <= 0:
        raise RuntimeError("RIFE campaign proof boundary has no generator")
    desired = bool(enabled)
    initial_events = [
        event for event in frame_gen.framegen_proof_state_events(log_reader())
        if int(event["generator"]) == generator
    ]
    if not initial_events:
        raise RuntimeError(
            "RIFE campaign proof boundary has no renderer state marker"
        )
    initial = initial_events[-1]
    if bool(initial["enabled"]) == desired:
        raise RuntimeError(
            "RIFE campaign proof boundary did not request a state change"
        )
    pid = int(initial["pid"])
    command = (
        ("settings", "put", "global", "emufusion_framegen_proof", "1")
        if desired else
        ("settings", "delete", "global", "emufusion_framegen_proof")
    )
    failure = (
        "timed out waiting for the RIFE qualification renderer to "
        f"publish enabled={str(desired).lower()}"
    )
    remaining = _framegen_deadline_remaining(deadline, failure)
    qa.adb(adb, serial, "shell", *command, timeout=remaining)
    while True:
        _framegen_deadline_remaining(deadline, failure)
        events = [
            event for event in frame_gen.framegen_proof_state_events(log_reader())
            if int(event["generator"]) == generator and
            int(event["pid"]) == pid
        ]
        if events and bool(events[-1]["enabled"]) == desired:
            marker = events[-1]
            return {
                "pid": pid,
                "generator": generator,
                "enabled": desired,
                "proofContract": str(marker["proofContract"]),
                "proofSchemaVersion": int(marker["proofSchemaVersion"]),
            }
        remaining = _framegen_deadline_remaining(deadline, failure)
        time.sleep(min(poll_seconds, remaining))


def _rife_latency_candidates(
        captured_log: str,
        records: list[tuple[str, Path, str, int]],
        role: str = "primary", display_id: int = 0,
) -> tuple[list[tuple[str, Path, dict[str, object]]], list[dict[str, object]]]:
    """Join RIFE's physical epoch to raw SurfaceFlinger actual-present rows."""
    passing: list[tuple[str, Path, dict[str, object]]] = []
    rejected: list[dict[str, object]] = []
    for layer, latency_path, candidate_role, candidate_display_id in records:
        if candidate_role != role or candidate_display_id != display_id:
            continue
        try:
            latency = frame_gen.parse_latency(latency_path)
            report = rife_timing.verify_timing(
                captured_log, role=role, display_id=display_id,
                actual_present_timestamps=latency["actualPresentTimestamps"],
                minimum_span_ns=rife_timing.MIN_RUNTIME_SPAN_NS,
            )
        except (OSError, ValueError, RuntimeError) as failure:
            rejected.append({
                "layer": layer, "latency": str(latency_path),
                "role": candidate_role, "displayId": candidate_display_id,
                "failures": [str(failure)],
            })
            continue
        passing.append((layer, latency_path, report))
    return passing, rejected


def _require_rife_latency_coverage(
        captured_log: str,
        records: list[tuple[str, Path, str, int]],
        role: str = "primary", display_id: int = 0,
) -> tuple[str, Path, dict[str, object]]:
    passing, rejected = _rife_latency_candidates(
        captured_log, records, role, display_id)
    selected = _unique_strongest_framegen_candidate(
        passing, role, display_id)
    if selected is None:
        raise RuntimeError(
            "no uniquely strongest latency-overlapping app-owned RIFE layer "
            f"for {role}/display-{display_id}: {rejected}"
        )
    return selected


def _require_latency_coverage_for_streams(
        captured_log: str,
        records: list[tuple[str, Path, str, int]],
        streams: list[tuple[str, int]],
        any_of: bool = False) -> None:
    """Require one fresh SurfaceFlinger layer for every logical display.

    SurfaceFlinger may retain a stale SurfaceView name when an emulator
    recreates its Activity surface.  Candidate discovery intentionally keeps
    both names so the final verifier can identify the empirically active one;
    requiring *every* candidate to overlap the same HEALTH window makes that
    safe discovery policy impossible.  Accept the capture set only when at
    least one candidate per required role/display has the exact raw-clock
    overlap.  Individual stale candidates remain in the set and are rejected
    later, while final acceptance still requires exactly one passing primary
    layer.
    """
    covered: set[tuple[str, int]] = set()
    failures: list[str] = []
    for layer, latency_path, role, display_id in records:
        try:
            latency = frame_gen.parse_latency(latency_path)
            _steady_framegen_segment(
                _framegen_health_records(captured_log, role, display_id),
                role, display_id,
                actual_present_timestamps=
                    latency["actualPresentTimestamps"],
            )
            covered.add((role, display_id))
        except (OSError, ValueError, RuntimeError) as failure:
            failures.append(f"{role}/display-{display_id} {layer}: {failure}")
    missing = [stream for stream in streams if stream not in covered]
    if any_of:
        # DS any-of semantics (see _wait_for_current_framegen_steady): the
        # non-gameplay screen may idle static with no overlapping steady
        # segment at all; one covered stream is what the gate can qualify.
        missing = [] if covered else missing
    if missing:
        labels = ", ".join(
            f"{role}/display-{display_id}" for role, display_id in missing)
        detail = "; ".join(failures[-4:])
        raise RuntimeError(
            "no latency-overlapping active SurfaceFlinger layer for " +
            labels + (f": {detail}" if detail else ""))





def _unique_strongest_framegen_candidate(
        passing: list[tuple[str, Path, dict[str, object]]],
        role: str, display_id: int,
) -> Optional[tuple[str, Path, dict[str, object]]]:
    """Select one compositor alias by its raw HEALTH-window overlap."""
    matches = [item for item in passing
               if item[2].get("role") == role and
               item[2].get("displayId") == display_id]
    if not matches:
        return None
    strongest = max(int(item[2].get("surfaceFlingerRawOverlapFrames", 0))
                    for item in matches)
    best = [item for item in matches
            if int(item[2].get("surfaceFlingerRawOverlapFrames", 0)) ==
            strongest]
    return best[0] if len(best) == 1 else None


def _write_framegen_qualification(
        log_path: Path, latency_path: Path, output: Path, prefix: str,
        role: str, display_id: int, identity: dict[str, object]) -> tuple[Path, str]:
    log = log_path.read_text(encoding="utf-8", errors="replace")
    records = _framegen_health_records(log, role, display_id)
    latency = frame_gen.parse_latency(latency_path)
    segment, end = _steady_framegen_segment(
        records, role, display_id,
        actual_present_timestamps=latency["actualPresentTimestamps"],
    )
    pid = int(end["pid"])
    generator = int(end["generator"])
    session_id = re.sub(r"[^A-Za-z0-9._:-]+", "-", prefix).strip("-")
    session_id = (session_id or "runtime")[:96] + f"-g{generator}"
    bound_identity = dict(identity)
    bound_identity.update({
        "sessionId": session_id,
        "pid": pid,
        "generator": generator,
        "role": role,
        "displayId": display_id,
        "sessionStartNs": max(1, min(
            min(int(row["window_start_ns"]) for row in records),
            int(latency["firstActualPresentNs"]),
        ) - 1),
        "sessionEndNs": max(
            max(int(row["window_end_ns"]) for row in records),
            int(latency["lastActualPresentNs"]),
        ) + 1,
    })
    document = {
        "schemaVersion": 1,
        "evidence": {
            "logSha256": sha256_file(log_path),
            "latencySha256": sha256_file(latency_path),
        },
        "identity": bound_identity,
        "segments": [segment],
    }
    path = output / (
        f"{prefix}-framegen-qualification-{role}-display-{display_id}.json"
    )
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path, str(segment["segmentId"])


def _select_nes_cadence(controller: PhysicalController, tier: int) -> dict[str, object]:
    directions = {
        60: (controller.HAT_Y, -1, "up"),
        50: (controller.HAT_X, 1, "right"),
        40: (controller.HAT_Y, 1, "down"),
        30: (controller.HAT_X, -1, "left"),
    }
    if tier not in directions:
        raise ValueError(f"unsupported NES cadence tier: {tier}")
    axis, value, direction = directions[tier]
    started = time.monotonic_ns()
    label = f"nes-cadence-select-{tier}"
    controller.trace.append(InputTrace(label + ":hat-down", started // 1_000_000))
    monitor = subprocess.Popen(
        [str(controller.adb), "-s", controller.serial, "shell", "getevent",
         "-t", "-c", "8", controller.node],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(0.10)
    script = (
        "cat /proc/uptime\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_ABS} {axis} {value}\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} {controller.SYN_REPORT} 0\n"
        "sleep 0.080\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_KEY} {controller.STOP} 1\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} {controller.SYN_REPORT} 0\n"
        "sleep 0.080\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_KEY} {controller.STOP} 0\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} {controller.SYN_REPORT} 0\n"
        "sleep 0.080\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_ABS} {axis} 0\n"
        f"sendevent {shlex.quote(controller.node)} {controller.EV_SYN} {controller.SYN_REPORT} 0\n"
        "cat /proc/uptime\n"
    )
    completed = subprocess.run(
        [str(controller.adb), "-s", controller.serial, "shell", "sh"],
        input=script, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=5.0,
    )
    time.sleep(0.10)
    monitor.terminate()
    try:
        observed, _ = monitor.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        monitor.kill()
        observed, _ = monitor.communicate(timeout=2.0)
    if completed.returncode != 0:
        raise RuntimeError("NES cadence selection device script failed")
    uptime = [line for line in completed.stdout.splitlines()
              if re.fullmatch(r"\s*\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s*", line)]
    if len(uptime) != 2:
        raise RuntimeError("NES cadence selection lacks a device uptime bracket")
    before = return_video.parse_uptime_seconds(uptime[0])
    after = return_video.parse_uptime_seconds(uptime[1])
    if not 0.20 <= after - before <= 0.50:
        raise RuntimeError("NES cadence selection has an invalid device duration")
    expected_sequence = [(3, axis, value), (1, controller.STOP, 1),
                         (1, controller.STOP, 0), (3, axis, 0)]
    relevant = [event for event in nes_qa._kernel_timed_events(observed)
                if event[0] in (1, 3)]
    if [event[:3] for event in relevant] != expected_sequence:
        raise RuntimeError(
            f"NES cadence selection kernel sequence mismatch: {relevant}"
        )
    ended = time.monotonic_ns()
    controller.trace.append(InputTrace(label + ":hat-up", ended // 1_000_000))
    return {"tier": tier, "combo": f"Select+{direction.title()}",
            "hostStartNs": started, "hostEndNs": ended,
            "deviceStartMonotonicNs": relevant[0][3],
            "deviceEndMonotonicNs": relevant[-1][3],
            "physicalEventNode": controller.node}


def _live_nes_log_text(capture: dict[str, object]) -> str:
    handle = capture["handle"]
    handle.flush()
    os.fsync(handle.fileno())
    return Path(capture["path"]).read_text(encoding="utf-8", errors="replace")


def _nes_framegen_records_with_lines(log_text: str) -> list[dict[str, object]]:
    return _framegen_health_transport_records(log_text)


def _nes_primary_generator_identity(log_text: str, pid: int) -> int:
    generators = set()
    for line in log_text.splitlines():
        attached = frame_gen.ATTACHED.search(line)
        if attached is None or frame_gen.framegen_line_pid(line) != pid:
            continue
        if attached.group(2) == "primary" and int(attached.group(3)) == 0:
            generators.add(int(attached.group(1)))
    if len(generators) != 1:
        raise RuntimeError(
            "NES proof reset requires exactly one attached primary generator"
        )
    return next(iter(generators))


def _reset_nes_qualification_proof(
        adb: Path, serial: str, capture: dict[str, object], tier: int,
        timeout: float = 8.0) -> dict[str, object]:
    """Perform and observe one real false→true reset for a tier interval."""
    pid = int(capture["pid"])
    initial_log = _live_nes_log_text(capture)
    generator = _nes_primary_generator_identity(initial_log, pid)

    def matching_events() -> tuple[str, list[dict[str, object]]]:
        text = _live_nes_log_text(capture)
        events = [event for event in frame_gen.framegen_proof_state_events(text)
                  if event["pid"] == pid and event["generator"] == generator]
        return text, events

    def wait_event(enabled: bool, after_line: int) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _text, events = matching_events()
            matches = [event for event in events
                       if int(event["lineIndex"]) > after_line and
                       event["enabled"] is enabled]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise RuntimeError("NES proof reset emitted duplicate state markers")
            time.sleep(0.10)
        raise RuntimeError(
            f"NES proof reset did not observe enabled={str(enabled).lower()} marker"
        )

    _text, existing = matching_events()
    last_line = max((int(event["lineIndex"]) for event in existing), default=-1)
    if not existing or existing[-1]["enabled"] is not True:
        qa.adb(adb, serial, "shell", "settings", "put", "global",
               "emufusion_framegen_proof", "1")
        armed = wait_event(True, last_line)
        last_line = int(armed["lineIndex"])

    qa.adb(adb, serial, "shell", "settings", "delete", "global",
           "emufusion_framegen_proof")
    disabled = wait_event(False, last_line)
    qa.adb(adb, serial, "shell", "settings", "put", "global",
           "emufusion_framegen_proof", "1")
    enabled = wait_event(True, int(disabled["lineIndex"]))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = _live_nes_log_text(capture)
        records = [record for record in _nes_framegen_records_with_lines(text)
                   if record["pid"] == pid and
                   record["generator"] == generator and
                   record["role"] == "primary" and
                   int(record["display_id"]) == 0 and
                   int(record["line_index"]) > int(enabled["lineIndex"])]
        if records:
            baseline = records[0]
            if any(int(baseline[key]) != 0
                   for key in frame_gen.RESET_COUNTER_FIELDS):
                raise RuntimeError(
                    "NES proof reset baseline counters are nonzero"
                )
            return {
                "tier": tier, "pid": pid, "generator": generator,
                "disabledLineIndex": int(disabled["lineIndex"]),
                "enabledLineIndex": int(enabled["lineIndex"]),
                "baselineWindowEndNs": int(baseline["window_end_ns"]),
            }
        time.sleep(0.10)
    raise RuntimeError("NES proof reset has no following HEALTH baseline")


def _nes_health_runs(log_text: str,
                     campaign_start_line: Optional[int] = None) \
        -> list[list[dict[str, object]]]:
    lines = log_text.splitlines()
    if campaign_start_line is None:
        markers = [index for index, line in enumerate(lines)
                   if "Qualification proof generator=" in line]
        campaign_start_line = markers[-1] if markers else -1
    if (campaign_start_line < 0 or campaign_start_line >= len(lines)):
        raise RuntimeError("NES cadence campaign has no proof-enable marker")
    records = _framegen_health_records(
        "\n".join(lines[campaign_start_line:]), "primary", 0
    )
    runs: list[list[dict[str, object]]] = []
    for record in records:
        tier = int(record["locked"])
        if tier not in nes_qa.STEADY_TIERS:
            continue
        if not runs or int(runs[-1][-1]["locked"]) != tier:
            runs.append([])
        runs[-1].append(record)
    expected = [60, 50, 40, 30, 40, 50, 60]
    for start in range(len(runs) - len(expected), -1, -1):
        candidate = runs[start:start + len(expected)]
        if [int(run[0]["locked"]) for run in candidate] != expected:
            continue
        if all(len(run) >= 3 and
               int(run[-1]["window_end_ns"]) - int(run[0]["window_end_ns"]) >=
               11_000_000_000 for run in candidate):
            return candidate
    raise RuntimeError(
        "NES cadence campaign did not produce seven real >=11-second HEALTH runs "
        "in order 60->50->40->30->40->50->60"
    )


def _nes_latency_bound_health(
        run: list[dict[str, object]], latency_path: Path, tier: int,
        baseline_window_end_ns: int) -> dict[str, object]:
    latency = frame_gen.parse_latency(latency_path)
    timestamps = latency["actualPresentTimestamps"]
    candidates = []
    for record in run:
        if (int(record["window_end_ns"]) <= baseline_window_end_ns or
                int(record["locked"]) != tier):
            continue
        seconds = int(record["window_ms"]) / 1000.0
        if seconds <= 0:
            continue
        promoted_rate = int(record["window_promoted"]) / seconds
        generated_rate = int(record["window_generated"]) / seconds
        schema = _framegen_health_schema(record)
        if schema in _FRAMEGEN_EPOCH_SCHEMA_VERSIONS:
            expected_output = (int(math.floor(
                int(record["target_millihz"]) / 1000.0 + 0.5))
                if schema in _FRAMEGEN_RATIONAL_SCHEMA_VERSIONS else frame_gen._schema42_output_fps(
                int(record["panel"]), tier) if schema == 42 else
                frame_gen._schema37_output_fps(
                int(record["panel"]), tier) if schema in (37, 38, 39, 40, 41) else
                frame_gen._schema36_output_fps(int(record["panel"]), tier))
            if schema in _FRAMEGEN_RATIONAL_SCHEMA_VERSIONS:
                expected_exact_real = None
                expected_generated = None
            else:
                expected_exact_real, expected_generated = \
                    frame_gen._schema36_rational_rates(
                        tier, int(record["output"]))
            exact_real_rate = int(record["window_real_priority"]) / seconds
            fallback = (int(record["window_presents"]) -
                        int(record["window_generated"]) -
                        int(record["window_real_priority"]))
            rational_mismatch = int(record["output"]) != expected_output
            if schema in _FRAMEGEN_RATIONAL_SCHEMA_VERSIONS:
                source_hz = int(record["source_millihz"]) / 1000.0
                target_hz = int(record["target_millihz"]) / 1000.0
                # Exact endpoint coincidences depend on the phase between the
                # two rational clocks.  Bind successful classes and their
                # physical rates without fabricating a gcd from rounded labels.
                rational_mismatch = (rational_mismatch or
                    exact_real_rate > source_hz * 1.08 + 2.5 or
                    generated_rate + 2.5 < max(0.0, target_hz - source_hz))
            else:
                rational_mismatch = (rational_mismatch or
                    abs(exact_real_rate - expected_exact_real) >
                        max(2.5, expected_exact_real * 0.08))
        else:
            expected_generated = int(record["output"]) - tier
            fallback = (int(record["window_presents"]) -
                        int(record["window_generated"]) -
                        int(record["window_promoted"]))
            rational_mismatch = False
        if (fallback != 0 or rational_mismatch or
                abs(promoted_rate - tier) > max(2.5, tier * 0.08) or
                (schema not in _FRAMEGEN_RATIONAL_SCHEMA_VERSIONS and abs(generated_rate - expected_generated) >
                    max(2.5, expected_generated * 0.08))):
            continue
        overlap = sum(int(record["window_start_ns"]) <= timestamp <=
                      int(record["window_end_ns"]) for timestamp in timestamps)
        if overlap >= max(31, int(len(timestamps) * 0.25)):
            candidates.append((overlap, record))
    if not candidates:
        raise RuntimeError(
            f"NES tier {tier} has no cadence-correct HEALTH window bound to "
            "its raw SurfaceFlinger trace"
        )
    maximum = max(value[0] for value in candidates)
    winners = [record for overlap, record in candidates if overlap == maximum]
    if len(winners) != 1:
        raise RuntimeError(
            f"NES tier {tier} SurfaceFlinger trace ambiguously overlaps HEALTH"
        )
    return winners[0]


def _write_nes_framegen_segment(
        log_path: Path, latency_source: Path, output: Path, prefix: str,
        name: str, segment: dict[str, object], records: list[dict[str, object]],
        qualification_identity: dict[str, object]) -> dict[str, object]:
    latency_path = output / f"{prefix}-framegen-{name}-latency.txt"
    latency_path.write_bytes(latency_source.read_bytes())
    end = records[-1]
    identity = dict(qualification_identity)
    identity.update({
        "sessionId": (re.sub(r"[^A-Za-z0-9._:-]+", "-", prefix).strip("-") or
                      "nes-runtime")[:96] + f"-g{int(end['generator'])}",
        "pid": int(end["pid"]), "generator": int(end["generator"]),
        "role": "primary", "displayId": 0,
        "sessionStartNs": max(1, min(int(row["window_start_ns"])
                                      for row in records) - 1),
        "sessionEndNs": max(int(row["window_end_ns"])
                            for row in records) + 1,
    })
    qualification = output / f"{prefix}-framegen-{name}-qualification.json"
    qualification.write_text(json.dumps({
        "schemaVersion": 1,
        "evidence": {"logSha256": sha256_file(log_path),
                     "latencySha256": sha256_file(latency_path)},
        "identity": identity, "segments": [segment],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = frame_gen.verify(
        log_path, latency_path, role="primary", display_id=0,
        qualification_path=qualification, segment_id=str(segment["segmentId"]),
    )
    persisted = calibration_framegen_result(result, name)
    report_path = output / f"{prefix}-framegen-{name}-report.json"
    report_path.write_text(json.dumps(persisted, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return {"name": name, "qualification": str(qualification),
            "latency": str(latency_path), "report": str(report_path),
            "result": persisted}


def calibration_framegen_result(
        result: dict[str, object], name: str) -> dict[str, object]:
    """Annotate, but never convert, a fixture-only full-verifier verdict."""
    failures = result.get("failures")
    if not isinstance(result.get("passed"), bool) or not isinstance(failures, list) or \
            any(not isinstance(value, str) for value in failures):
        raise RuntimeError(f"NES frame-generation {name} returned a malformed result")
    unexpected = sorted(set(failures) - NES_CALIBRATION_CONTENT_FAILURES)
    persisted = dict(result)
    persisted.update({
        "calibrationOnly": True,
        "contentQualificationEligible": False,
        "contentQualityPassed": bool(result["passed"]),
    })
    if unexpected or (result["passed"] and failures) or \
            (not result["passed"] and not failures):
        raise RuntimeError(
            f"NES calibration frame-generation {name} has non-content failures: "
            f"{unexpected or failures}"
        )
    return persisted


def nes_frame_generation_campaign(
        adb: Path, serial: str, controller: PhysicalController, output: Path,
        prefix: str, layer: str,
        qualification_identity: dict[str, object],
        continuous_log: dict[str, object]) -> dict[str, object]:
    """Exercise real 60/50/40/30 visual tiers and both adjacent directions."""
    schedule = [60, 50, 40, 30, 40, 50, 60]
    raw_latency: list[Path] = []
    inputs: list[dict[str, object]] = []
    proof_resets: list[dict[str, object]] = []
    for index, tier in enumerate(schedule):
        # Every interval, including the first 60-Hz interval, has an explicit
        # physical direct-mode selection. Earlier control QA legitimately taps
        # Select and can leave the fixture in 50-Hz mode; inferred initial state
        # is therefore never qualification evidence.
        inputs.append(_select_nes_cadence(controller, tier))
        time.sleep(1.0)
        proof_resets.append(_reset_nes_qualification_proof(
            adb, serial, continuous_log, tier
        ))
        qa.adb(adb, serial, "shell",
               f"dumpsys SurfaceFlinger --latency-clear '{layer}'")
        # HEALTH is emitted every five seconds. Twenty-two seconds guarantees
        # a baseline plus >=2 later target records spanning >=11 seconds even
        # when the mode input lands immediately after a window boundary.
        time.sleep(22.0)
        raw = output / f"{prefix}-nes-tier-interval-{index:02d}-{tier}-latency.txt"
        raw.write_text(qa.adb(
            adb, serial, "shell",
            f"dumpsys SurfaceFlinger --latency '{layer}'",
        ).stdout, encoding="utf-8")
        raw_latency.append(raw)
    time.sleep(1.2)
    log_path = snapshot_nes_logcat_capture(
        continuous_log, output / f"{prefix}-framegen-logcat.txt"
    )
    runs = _nes_health_runs(
        log_path.read_text(encoding="utf-8", errors="replace"),
        int(proof_resets[0]["disabledLineIndex"]),
    )
    cadence_ends = [_nes_latency_bound_health(
        run, raw_latency[index], schedule[index],
        int(proof_resets[index]["baselineWindowEndNs"]),
    ) for index, run in enumerate(runs)]
    all_records = [row for run in runs for row in run]
    artifacts: dict[str, dict[str, object]] = {}

    # One steady proof for every user-visible tier. The first occurrence is
    # used for 60/50/40; 30 occurs once at the direction reversal.
    first_index = {60: 0, 50: 1, 40: 2, 30: 3}
    for tier in nes_qa.STEADY_TIERS:
        index = first_index[tier]
        run = runs[index]
        reset = proof_resets[index]
        baseline_matches = [row for row in run
                            if int(row["window_end_ns"]) ==
                            int(reset["baselineWindowEndNs"])]
        if len(baseline_matches) != 1:
            raise RuntimeError(
                f"NES steady-{tier} reset baseline is outside its HEALTH run"
            )
        baseline = baseline_matches[0]
        name = f"steady-{tier}"
        segment = {"segmentId": name, "kind": "steady",
                   "startWindowEndNs": int(baseline["window_end_ns"]),
                   "proofBaselineWindowEndNs": int(baseline["window_end_ns"]),
                   "endWindowEndNs": int(cadence_ends[index]["window_end_ns"]),
                   "maxFallbackPresents": 0, "expectedLockedFps": tier,
                   "proofReset": {key: reset[key] for key in (
                       "pid", "generator", "disabledLineIndex",
                       "enabledLineIndex", "baselineWindowEndNs")}}
        artifacts[name] = _write_nes_framegen_segment(
            log_path, raw_latency[index], output, prefix, name, segment,
            all_records, qualification_identity,
        )
    for index, (left, right) in enumerate(zip(schedule, schedule[1:])):
        source, target = runs[index], runs[index + 1]
        reset = proof_resets[index + 1]
        baseline_matches = [row for row in target
                            if int(row["window_end_ns"]) ==
                            int(reset["baselineWindowEndNs"])]
        if len(baseline_matches) != 1:
            raise RuntimeError(
                f"NES transition-{left}-{right} reset baseline is outside its HEALTH run"
            )
        baseline = baseline_matches[0]
        name = f"transition-{left}-{right}"
        segment = {"segmentId": name, "kind": "transition",
                   "startWindowEndNs": int(cadence_ends[index]["window_end_ns"]),
                   "proofBaselineWindowEndNs": int(baseline["window_end_ns"]),
                   "endWindowEndNs":
                       int(cadence_ends[index + 1]["window_end_ns"]),
                   "maxFallbackPresents": 0, "expectedFromFps": left,
                   "expectedToFps": right, "maxTransitionMs": 10_000,
                   "proofReset": {key: reset[key] for key in (
                       "pid", "generator", "disabledLineIndex",
                       "enabledLineIndex", "baselineWindowEndNs")}}
        artifacts[name] = _write_nes_framegen_segment(
            log_path, raw_latency[index + 1], output, prefix, name, segment,
            all_records, qualification_identity,
        )
    schedule_path = output / f"{prefix}-nes-tier-input-schedule.json"
    schedule_path.write_text(json.dumps({
        "schemaVersion": 1, "tiers": schedule, "directSelections": inputs,
        "proofResets": proof_resets,
        "source": "physical Odin Controller Select+direction",
        "noClockOverride": True,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    visible = screenshot(adb, serial,
                         output / f"{prefix}-framegen-visible-primary.png")
    require_visible_frame_generation_output(visible, "primary", 0)
    content_passed = all(bool(entry["result"]["passed"])
                         for entry in artifacts.values())
    return {"passed": content_passed, "calibrationPassed": True,
            "calibrationOnly": True, "contentQualificationEligible": False,
            "contentQualityPassed": content_passed,
            "tiers": schedule, "segments": artifacts,
            "log": str(log_path), "schedule": str(schedule_path),
            "visibleOutput": visible}


def frame_generation_evidence(adb: Path, serial: str,
                              controller: PhysicalController, output: Path,
                              prefix: str,
                              layer_baseline: list[str],
                              case: SystemCase,
                              qualification_identity: dict[str, object],
                              continuous_log: Optional[dict[str, object]] = None) -> dict[str, object]:
    """Prove novel intermediate pixels and real panel-cadence latches.

    The FPS overlay is deliberately not evidence.  This joins GPU-side hashes
    of the actual synthesized framebuffer with SurfaceFlinger's timestamps for
    the exact MainActivity gameplay layer.  Physical motion supplies repeatable
    gameplay for most systems; F-Zero uses its explicitly identified AI attract
    race because open-loop steering is not repeatable and can pin the craft.
    """
    after_layers = main_activity_surface_layers(adb, serial)
    (output / f"{prefix}-surface-layers-after.txt").write_text(
        "\n".join(after_layers) + "\n", encoding="utf-8"
    )
    baseline = set(layer_baseline)
    new_layers = [layer for layer in after_layers if layer not in baseline]
    # Dolphin may reuse the Activity's retained SurfaceView across launches
    # while also creating a short-lived auxiliary SurfaceView.  r56 proved
    # that the retained layer can be the only 120-Hz gameplay compositor and
    # the newly named layer can be sparse.  Preserve every current candidate;
    # raw timestamp overlap and the final exactly-one-passing rule identify
    # the empirical gameplay layer without guessing from creation order.
    layers = list(after_layers)
    if not layers:
        raise RuntimeError(
            "frame-generation gate requires at least one current "
            "MainActivity gameplay SurfaceView"
        )
    (output / f"{prefix}-new-surface-layers.txt").write_text(
        "\n".join(new_layers) + ("\n" if new_layers else ""),
        encoding="utf-8",
    )
    secondary_layers = secondary_gameplay_layers(
        adb, serial, clockwise_texture=case.folder == "n3ds"
    ) if case.dual_screen else []
    if case.dual_screen and len(secondary_layers) != 1:
        raise RuntimeError(
            "frame-generation gate requires exactly one physical lower "
            f"gameplay layer; found {len(secondary_layers)}"
        )
    (output / f"{prefix}-secondary-surface-layers.txt").write_text(
        "\n".join(secondary_layers) + ("\n" if secondary_layers else ""),
        encoding="utf-8",
    )
    if (case.folder == "nes" and
            qualification_identity.get("romSha256") == NES_QUALIFICATION_SHA256):
        if continuous_log is None:
            raise RuntimeError("NES tier campaign lacks continuous logcat capture")
        return nes_frame_generation_campaign(
            adb, serial, controller, output, prefix, layers[0],
            qualification_identity, continuous_log,
        )
    # Qt's layer existed in the baseline. Only the one new SurfaceView created
    # after physical A is accepted as gameplay; cadence can no longer select a
    # pre-existing fast Qt layer by inference. The verifier then uses that
    # layer's actual-present fences, never requested/desired timestamps.
    for layer in layers + secondary_layers:
        qa.adb(adb, serial, "shell",
               f"dumpsys SurfaceFlinger --latency-clear '{layer}'")
    rife_qualification_requested = qa.adb(
        adb, serial, "shell", "settings", "get", "global",
        "emufusion_framegen_rife_qualification",
    ).stdout.strip() == "1"
    motion_stop = threading.Event()
    n64_fzero_qualification = (
        case.folder == "n64" and
        str(qualification_identity.get("gameId", "")) ==
        normalize("F-Zero X")
    )
    n64_ocarina_qualification = (
        case.folder == "n64" and
        str(qualification_identity.get("gameId", "")) ==
        normalize("The Legend of Zelda: Ocarina of Time")
    )

    def sustain_physical_motion() -> None:
        if n64_fzero_qualification:
            # Any controller edge exits the attract race.  Its AI is the
            # declared motion source, so remain completely input-free until
            # capture finishes or fails.
            while not motion_stop.wait(0.25):
                pass
            return
        if n64_ocarina_qualification:
            # Physical r13 proved this exact analog C-UP plus octagonal
            # left-stick orbit produces Ocarina's immutable 20-Hz image clock
            # and a physical 40-Hz presentation stream.  It previously ran
            # before Saria's greeting was cleared, so its evidence window
            # eventually became dialogue-static.  The owned pre-proof staging
            # above now clears that dialogue first.  Do not press A here: the
            # camera path itself is the motion source and A can reopen an NPC
            # interaction.  Consecutive vectors meet without neutral; both
            # sticks are released exactly once in finally.
            camera_orbit = (
                (-0.720, 0.000),
                (-0.720, -0.720),
                (0.000, -0.720),
                (0.720, -0.720),
                (0.720, 0.000),
                (0.720, 0.720),
                (0.000, 0.720),
                (-0.720, 0.720),
            )
            orbit_index = 0
            controller.set_right_stick_vector(
                0.000, -1.000, "physical-n64-c-up-camera-orbit"
            )
            try:
                while not motion_stop.is_set():
                    horizontal, vertical = camera_orbit[orbit_index]
                    orbit_index = (orbit_index + 1) % len(camera_orbit)
                    controller.set_left_stick_vector(
                        horizontal, vertical,
                        "physical-n64-first-person-camera-orbit",
                    )
            finally:
                controller.center_left_stick(
                    "physical-n64-first-person-camera-orbit-release"
                )
                controller.center_right_stick(
                    "physical-n64-c-up-camera-orbit-release"
                )
            return
        if case.folder == "n64":
            # N64's strict source contract classifies immutable unique images,
            # not callbacks. The former 0.45-second eight-way orbit kept Link
            # circling inside his single-screen house: only his tiny sprite
            # moved, the 16x9 source classifier saw long duplicate stretches,
            # and the exact timestamp contract correctly refused to bridge
            # 100-1200 ms gaps (physical r9). Use long direct traversal legs
            # instead. The first diagonal/left legs reach the house exit; the
            # remaining legs traverse the forest and pan the full camera.
            # Consecutive vectors still meet directly (never through neutral).
            # Leaving Link's house starts Saria's mandatory greeting: r10
            # reached that real gameplay trigger, then spent the whole proof
            # window on the static "Yahoo! Hi" dialogue because this loop sent
            # no action input.  N64 A is the visible context/advance action in
            # Ocarina and a harmless roll/action during free movement; send one
            # bounded tap after each long leg so traversal cannot become a
            # dialogue-locked motion fixture.  START/C/menu inputs remain
            # forbidden.
            traversal = (
                (-0.720, -0.720, 4.0),
                (-0.720, 0.000, 3.0),
                (0.000, -0.720, 3.0),
                (0.720, 0.720, 2.5),
                (0.000, 0.720, 2.5),
                (0.720, 0.000, 2.5),
            )
            traversal_index = 0
            try:
                while not motion_stop.is_set():
                    horizontal, vertical, hold = traversal[traversal_index]
                    traversal_index = (traversal_index + 1) % len(traversal)
                    controller.set_left_stick_vector(
                        horizontal, vertical,
                        "physical-n64-continuous-traversal", hold=hold,
                    )
                    controller.key(
                        n64_console_a_key(controller),
                        "physical-n64-a-dialogue-or-action", hold=0.055,
                    )
            finally:
                controller.center_left_stick(
                    "physical-n64-continuous-traversal-release"
                )
            return
        # Galaxy's tiny spherical platforms turn forward/back input into
        # mostly depth/scale changes.  The frame-generation content proof is
        # intentionally screen-space, so use repeatable lateral traversal for
        # Wii while retaining the four-axis coverage used by other systems.
        pattern = (("left", "right"), ("right", "left")) \
            if case.folder in {"wii", "switch", "nds"} else (
                ("left", "right"), ("right", "left"),
                ("up", "down"), ("down", "up"),
            )
        lower_phase = 0
        pattern_index = 0
        while not motion_stop.is_set():
                left, right = pattern[pattern_index]
                pattern_index = (pattern_index + 1) % len(pattern)
                if motion_stop.is_set():
                    return
                # Exercise the system's mapped primary gameplay action as well
                # as both sticks. This prevents action games from idling in a
                # stance/cutscene while the proof window falsely reports that
                # there was no visual motion to interpolate.
                if case.folder == "wii":
                    # Both qualified Galaxy discs gate the title behind A+B,
                    # which the bounded pre-proof navigation above has already
                    # supplied. Once the file selector is visible, however,
                    # holding B with A is a cancel chord and traps qualification
                    # in animated menus. Keep the IR cursor aimed with the
                    # right stick but click only Wii A throughout the proof
                    # window so file/character prompts can reach gameplay.
                    # Thor's flipped face-button layout names Linux BTN_EAST
                    # ``A`` in this harness, but Android resolves that raw key
                    # as Canonical EAST / Dolphin Wii B.  BTN_SOUTH is exposed
                    # here as ``B`` and resolves to Canonical SOUTH / Wii A.
                    # The full physical right-stick range also lies far beyond
                    # Dolphin's usable IR rectangle: Galaxy responds with
                    # "Point at the screen" and never clicks a file.  The
                    # measured safe ±30% window reaches every file/menu target
                    # while keeping the cursor on-screen.
                    controller.motion_pair(
                        left,
                        right,
                        # Short 0.45 s reversals kept Galaxy oscillating in
                        # almost the same screen-space pocket (wii-r46a), so
                        # the proof saw a mostly static starfield even though
                        # gameplay was controllable.  Long symmetric legs
                        # traverse the small planetoid and force sustained
                        # character/camera motion without biasing into one
                        # permanent obstacle.
                        hold=2.5,
                        chord_codes=(controller.B,),
                        chord_label="physical-wii-a-gameplay-action",
                        right_scale=0.30,
                    )
                elif case.folder in {"switch", "wiiu", "nds"}:
                    # The navigation gate has already selected a recognized
                    # playable row. Keep qualification incapable of entering
                    # Options/Accessibility if the title unexpectedly returns
                    # to a menu during this long capture: no A, no right stick.
                    # Switch sweeps LONG alternating lateral legs: persistent
                    # one-way walking pinned the Penitent One against a wall
                    # for a whole capture ("motion field is effectively
                    # zero", run switch7), while long left/right traversal
                    # pans the camera across the room every leg regardless
                    # of walls, and a short wiggle starved the gates first
                    # (run switch5).
                    # The legs are BIASED for switch: symmetric 1.5 s legs
                    # kept the Penitent One oscillating inside the one-screen
                    # altar room, whose bounded camera produced "motion field
                    # is effectively zero" (run switch10). A long left leg
                    # with a short right recovery drifts net-leftward out of
                    # the shrine, crossing rooms for sustained parallax and
                    # full-screen transitions, while the recovery leg still
                    # escapes walls.
                    controller.motion_left(
                        left, hold=(3.5 if left == "left" else 1.2)
                        if case.folder == "switch" else 0.45)
                    if case.folder == "nds":
                        # melonDS reads the DS d-pad from the Thor's HAT
                        # axes; the analog sweep above never reaches it, so
                        # Hunters' morph-ball sat idle in a static training
                        # room for the whole proof window and the honest
                        # unique-frame clock starved at ~5 samples (runs
                        # nds1-3, 2026-08-17). A held HAT leg rolls the ball
                        # across the room, keeping the TOP screen's 3D view
                        # in sustained motion.
                        # LONG symmetric legs: PoR's resume pocket is three
                        # rooms wide (entrance stairs <-> windowed corridor
                        # <-> save room, walked by hand 2026-08-17). Short
                        # legs wiggled in place (nds20) and one-way biases
                        # parked against either dead end (nds21-23). A 4 s
                        # leg crosses the full corridor, so every leg drags
                        # the camera across rooms in both directions —
                        # sustained full-screen scroll for the motion field.
                        controller.hat(left, "physical-nds-dpad-roll",
                                       hold=4.0)
                        # PoR's scripted entrance dialogue held every proof
                        # window static (run nds15): the walk-in armed the
                        # wait, then nothing pressed A during capture. In
                        # gameplay A is merely attack; in dialogue it is the
                        # only way forward. B first closes a pause menu if
                        # one was ever opened (run nds17) — in gameplay it
                        # is jump, which only adds honest motion.
                        controller.key(controller.B,
                                       "physical-nds-b-close", hold=0.05)
                        controller.key(controller.A,
                                       "physical-nds-a-advance", hold=0.05)
                    if case.folder == "switch":
                        # Raw south resolves to Switch B: it advances the
                        # new-game intro's dialogue/narration cards (which
                        # otherwise hold slow pans through every retry, run
                        # switch8), jumps in gameplay, and in a menu is only
                        # ever BACK — it cannot accept an Options row, which
                        # is why A stays forbidden here.
                        controller.key(controller.B,
                                       "physical-switch-b-advance", hold=0.05)
                elif case.folder == "ps2":
                    # The qualified PS2 scene is Grand Theft Auto III street
                    # traversal. Forward-only holds physically wedged the
                    # player against vehicles and walls (walking-in-place
                    # with a static camera starves the motion gates —
                    # observed 2026-08-15), so the four-direction pattern is
                    # held long per leg: the player walks, turns, and
                    # escapes obstacles, keeping locomotion and the
                    # following camera continuously moving. Buttons are
                    # never pressed except Cross, which is SPRINT on foot:
                    # sprinting roughly doubles traversal speed and thereby
                    # the changing-pixel population with strong vectors —
                    # the exact numerator of the one remaining confidence
                    # gate (run 6, 2026-08-15). Other buttons risk vehicle
                    # entry or combat.
                    controller.key(controller.B,
                            "physical-cross-ps2-sprint", hold=0.04)
                    controller.motion_pair(left, right, hold=2.0)
                else:
                    controller.motion_pair(left, right)
                    action_key = (controller.B if case.folder in {"psp", "ps3"}
                                  else controller.A)
                    action_label = ("physical-cross-gameplay-action" if
                                    case.folder in {"psp", "ps3"}
                                    else "physical-a-gameplay-action")
                    controller.key(action_key, action_label, hold=0.04)
                if case.lower_touch:
                    inject_lower_motion(adb, serial, lower_phase)
                    lower_phase += 1

    motion_thread = threading.Thread(target=sustain_physical_motion, daemon=True)
    real_nes_title = next(
        (title for title in NES_REAL_QUALIFICATION_TITLES
         if normalize(title) == str(qualification_identity.get("gameId", ""))),
        None,
    ) if case.folder == "nes" else None
    real_nes_health_baseline = None
    if case.folder == "nes":
        initial_health = _framegen_health_records(
            qa.logs(adb, serial), "primary", 0
        )
        if not initial_health:
            raise RuntimeError("real NES proof has no pre-proof HEALTH baseline")
        real_nes_health_baseline = initial_health[-1]

    def collect_latency_records(
    ) -> tuple[list[tuple[str, Path, str, int]], Path,
               Optional[dict[str, object]], Optional[dict[str, object]]]:
        # HEALTH is emitted every 120 presents and SurfaceFlinger's latency
        # history retains only its latest bounded ring. A fixed sleep can leave
        # the ring newer than the first historical steady run after a transient
        # tier change. Poll the *current* trailing tier until it meets both the
        # unchanged 11-second span and 30-sample proof minimum, then take the
        # compositor snapshot immediately.
        proof_gameplay = None
        if case.folder == "nes":
            if real_nes_title is None:
                raise RuntimeError(
                    "real NES frame-generation proof has an unreviewed title"
                )
            proof_frames = []
            for index, delay in enumerate((0.0, 10.0, 10.0)):
                if delay:
                    time.sleep(delay)
                path = output / (
                    f"{prefix}-real-nes-proof-motion-{index + 1:02d}.png"
                )
                screenshot(adb, serial, path)
                proof_frames.append(path)
            proof_gameplay = analyze_real_nes_gameplay_frames(
                proof_frames, real_nes_title
            )
        # Dual-screen handheld HUDs (Hunters radar, ALBW map) can stay
        # nearly static. Qualify 2x on the primary stream; the secondary
        # layer is still captured for identity, not dense motion.
        streams = [("primary", 0)]
        steady_any_of = False
        if (not rife_qualification_requested and secondary_layers and
                case.folder not in {"nds", "n3ds"}):
            streams.append(("secondary", 4))
        elif secondary_layers and case.folder in {"nds", "wiiu"}:
            # DS gameplay lives on whichever screen the game chose (Hunters
            # top / Castlevania touch); the other screen legitimately idles
            # static. Wait for EITHER stream's steady tier — the layer gate
            # afterwards still demands full evidence from one of them.
            # Wii U (2026-09-02, run wiiu-b48): the GamePad stream on the
            # 60-Hz secondary panel runs direct at the game's ~44-fps pad
            # view, which the tier protocol never generates; the TV stream
            # held a 94-second qualified 60->120 segment that this gate
            # never captured while it waited for both.
            streams.append(("secondary", 4))
            steady_any_of = True
        start_clock = time.monotonic()
        # Native-adapter systems (2026-09-02, run wiiu-b50): the 60-Hz
        # lattice funds through the 30-second canonical window after the
        # first tier votes, and the title's opening scenes still burst
        # "due but no endpoint" slots; the TV stream's steady 60->120 segment
        # first formed ~240 s after generation began and then held 97 s.
        steady_deadline_seconds = (
            FRAMEGEN_ADAPTER_STEADY_DEADLINE_SECONDS
            if case.folder in {"wiiu", "switch"}
            else FRAMEGEN_CURRENT_STEADY_DEADLINE_SECONDS
        )
        deadline = start_clock + steady_deadline_seconds
        rife_campaign_enabled = (
            rife_qualification_requested and n64_fzero_qualification
        )
        capture_cap_seconds = (
            FZERO_RIFE_CAMPAIGN_TOTAL_CAPTURE_CAP_SECONDS
            if rife_campaign_enabled else
            (FRAMEGEN_ADAPTER_TOTAL_CAPTURE_CAP_SECONDS
             if case.folder in {"wiiu", "switch"}
             else FRAMEGEN_TOTAL_CAPTURE_CAP_SECONDS)
        )
        hard_cap = start_clock + capture_cap_seconds
        last_failure = "no latency-overlapping steady segment"
        records: list[tuple[str, Path, str, int]] = []
        rife_campaign_reports: list[dict[str, object]] = []
        rife_campaign_artifacts: list[dict[str, object]] = []
        rife_captured_identities: set[tuple[int, int, int]] = set()
        rife_capture_attempt = 0
        current_fzero_checkpoint: Optional[Path] = None
        pending_campaign_rearm: Optional[dict[str, object]] = None

        def timeout_failure() -> str:
            return (
                "timed out capturing latency for a current steady "
                f"frame-generation segment: {last_failure}"
            )

        def bounded_adb(*args: str):
            failure = timeout_failure()
            return _framegen_bounded_capture(
                deadline, failure,
                lambda remaining: qa.adb(
                    adb, serial, *args, timeout=remaining,
                ),
            )

        def bounded_log() -> str:
            return bounded_adb("logcat", "-d", "-v", "brief").stdout

        def bounded_health_log() -> str:
            # Readiness polling only needs the frame-generation transport.
            # Re-reading every unrelated Android log line ten times per second
            # made long strict-source campaigns grow quadratically on the host.
            # The final evidence capture below remains the complete log.
            return bounded_adb(
                "logcat", "-d", "-v", "brief",
                "EmuFusionFrameGen:V", "*:S",
            ).stdout

        while True:
            _framegen_deadline_remaining(deadline, timeout_failure())
            # No per-system fallbacks around this wait: the 2026-08-16 audit
            # removed the ps3/nds "any 2x HEALTH segment" acceptances
            # because they fabricated the SurfaceFlinger overlap field,
            # skipped every dense content gate, and one variant filtered
            # below-floor schema-39 rows out of the log before parsing.
            # Every system earns the same steady-wait + SurfaceFlinger +
            # dense evidence.
            if rife_qualification_requested:
                _wait_for_current_rife_steady(
                    bounded_health_log, "primary", 0, deadline=deadline,
                    excluded_identities=frozenset(rife_captured_identities),
                )
            else:
                _wait_for_current_framegen_steady(
                    bounded_health_log, streams, deadline=deadline,
                    any_of=steady_any_of,
                )
            if n64_fzero_qualification:
                checkpoint_suffix = (
                    f"-rife-campaign-segment-"
                    f"{len(rife_campaign_reports) + 1:02d}"
                    if rife_campaign_enabled else ""
                )
                checkpoint = output / (
                    f"{prefix}-n64-fzero-proof-race-checkpoint"
                    f"{checkpoint_suffix}.png"
                )
                screenshot(adb, serial, checkpoint)
                if not n64_fzero_single_player_race_hud(checkpoint):
                    # 2026-09-01: the built-in generator takes the same bounded
                    # new-race retry the RIFE campaign always had.  F-Zero's
                    # input-free attract loop ends a race roughly every
                    # 13 seconds, so a steady 11-second epoch can legitimately
                    # complete just as the race ends (run n64-60first); the
                    # hard cap still bounds the whole capture phase and every
                    # retried course must earn its own new epoch.
                    # Do not capture a later scene against the already-proven
                    # epoch. Title/split transitions may reset source
                    # admission, and a new one-player course can therefore
                    # begin in Direct mode. Find that course input-free, then
                    # restart this outer loop so the same *new* RIFE epoch must
                    # independently earn eleven seconds before compositor
                    # capture. Never splice timing across attract courses.
                    deadline = min(
                        hard_cap,
                        max(deadline, time.monotonic() +
                            FZERO_RIFE_SCENE_RETRY_SECONDS),
                    )
                    remaining = _framegen_deadline_remaining(
                        deadline, timeout_failure())
                    wait_n64_fzero_moving_attract_race(
                        adb, serial, output, prefix,
                        timeout=min(FZERO_RIFE_SCENE_RETRY_SECONDS, remaining),
                    )
                    deadline = min(
                        hard_cap,
                        max(deadline, time.monotonic() +
                            FRAMEGEN_LATENCY_CAPTURE_SECONDS),
                    )
                    continue
                current_fzero_checkpoint = checkpoint
            # A slow JIT warm-up may consume most of the steady deadline;
            # give the capture pass a fresh bounded window from this steady
            # confirmation, never beyond the absolute hard cap.
            deadline = min(hard_cap,
                           max(deadline, time.monotonic() +
                               FRAMEGEN_LATENCY_CAPTURE_SECONDS))
            rife_capture_attempt += 1
            capture_suffix = (
                f"-rife-campaign-attempt-{rife_capture_attempt:02d}"
                if rife_campaign_enabled else ""
            )
            records: list[tuple[str, Path, str, int]] = []
            for index, layer in enumerate(layers):
                latency_path = output / (
                    f"{prefix}{capture_suffix}-surfaceflinger-latency-"
                    f"{index:02d}.txt"
                )
                latency = bounded_adb(
                    "shell",
                    f"dumpsys SurfaceFlinger --latency '{layer}'",
                ).stdout
                _framegen_deadline_remaining(deadline, timeout_failure())
                latency_path.write_text(latency, encoding="utf-8")
                _framegen_deadline_remaining(deadline, timeout_failure())
                records.append((layer, latency_path, "primary", 0))
            for index, layer in enumerate(secondary_layers):
                latency_path = output / (
                    f"{prefix}{capture_suffix}-secondary-surfaceflinger-"
                    f"latency-{index:02d}.txt"
                )
                latency = bounded_adb(
                    "shell",
                    f"dumpsys SurfaceFlinger --latency '{layer}'",
                ).stdout
                _framegen_deadline_remaining(deadline, timeout_failure())
                latency_path.write_text(latency, encoding="utf-8")
                _framegen_deadline_remaining(deadline, timeout_failure())
                records.append((layer, latency_path, "secondary", 4))
            captured_log = output / (
                f"{prefix}{capture_suffix}-framegen-logcat.txt"
            )
            captured = bounded_log()
            _framegen_deadline_remaining(deadline, timeout_failure())
            captured_log.write_text(captured, encoding="utf-8")
            _framegen_deadline_remaining(deadline, timeout_failure())
            fatal_rife_campaign_failure = False
            try:
                if rife_qualification_requested:
                    rife_selected = _require_rife_latency_coverage(
                        captured, records)
                else:
                    _require_latency_coverage_for_streams(
                        captured, records, streams, any_of=steady_any_of)
                _framegen_deadline_remaining(deadline, timeout_failure())
                if not rife_campaign_enabled:
                    return records, captured_log, proof_gameplay, None

                rife_layer, rife_latency_path, rife_report = rife_selected
                identity = (
                    int(rife_report["generator"]),
                    int(rife_report["presentationEpoch"]),
                    int(rife_report["timingWindow"]),
                )
                if identity in rife_captured_identities:
                    fatal_rife_campaign_failure = True
                    raise RuntimeError(
                        "RIFE campaign reused a captured timing identity"
                    )
                if current_fzero_checkpoint is None:
                    fatal_rife_campaign_failure = True
                    raise RuntimeError(
                        "RIFE campaign segment lacks its active-race checkpoint"
                    )
                rife_captured_identities.add(identity)
                rife_campaign_reports.append(rife_report)
                rife_campaign_artifacts.append({
                    "segment": len(rife_campaign_reports),
                    "generator": identity[0],
                    "presentationEpoch": identity[1],
                    "timingWindow": identity[2],
                    "layer": rife_layer,
                    "log": str(captured_log),
                    "latency": str(rife_latency_path),
                    "logSha256": sha256_file(captured_log),
                    "latencySha256": sha256_file(rife_latency_path),
                    "raceCheckpoint": str(current_fzero_checkpoint),
                    "raceCheckpointSha256": sha256_file(
                        current_fzero_checkpoint),
                    "timingStartNs": int(rife_report["timingStartNs"]),
                    "timingEndNs": int(rife_report["timingEndNs"]),
                    "preSegmentRearm": pending_campaign_rearm,
                })
                pending_campaign_rearm = None
                campaign_span_ns = sum(
                    int(report["timingEndNs"]) -
                    int(report["timingStartNs"])
                    for report in rife_campaign_reports
                )
                if (len(rife_campaign_reports) <
                        rife_timing.MIN_CAMPAIGN_SEGMENTS or
                        campaign_span_ns < rife_timing.MIN_CAMPAIGN_SPAN_NS):
                    last_failure = (
                        "RIFE long moving-game campaign is incomplete: "
                        f"segments={len(rife_campaign_reports)}/"
                        f"{rife_timing.MIN_CAMPAIGN_SEGMENTS} "
                        f"spanNs={campaign_span_ns}/"
                        f"{rife_timing.MIN_CAMPAIGN_SPAN_NS}"
                    )
                    deadline = min(
                        hard_cap,
                        max(deadline, time.monotonic() +
                            FZERO_RIFE_SCENE_RETRY_SECONDS),
                    )
                    remaining = _framegen_deadline_remaining(
                        deadline, timeout_failure())
                    # F-Zero returns to a static PUSH START screen after one
                    # attract race and does not automatically launch another
                    # demo (physical r270: 126 identical title samples over
                    # the entire 180-second natural-scene wait). First make
                    # the qualification path Direct and observe the renderer's
                    # disabled marker. A core reset by itself leaves RIFE's
                    # scheduler/timing identity unchanged (physical r271), so
                    # it can never establish an independent campaign segment.
                    disabled_proof = _set_rife_campaign_proof_state(
                        adb, serial, bounded_health_log, identity[0], False,
                        deadline=deadline,
                    )
                    remaining = _framegen_deadline_remaining(
                        deadline, timeout_failure())
                    scene_rearm = prepare_n64_fzero_attract_race(
                            adb, serial, controller, output,
                            f"{prefix}-rife-campaign-rearm-"
                            f"{len(rife_campaign_reports) + 1:02d}",
                            timeout=min(240.0, remaining),
                            # Arm on the first complete moving race found by
                            # the scene helper. Physical r275 proved that
                            # consuming an additional attract cycle does not
                            # make the initial race deterministic, while r274
                            # captured four independent components with no
                            # extra warm-up. Keep this bounded and let the
                            # strict HUD/window checks reject a short tail.
                            warmup_cycles=0,
                        )
                    # Arm proof only after the next moving one-player race is
                    # visibly established. The ordinary external cold-prime
                    # path then publishes a fresh scheduler/timing identity;
                    # the excluded-identity wait above independently proves
                    # that this transition really happened.
                    enabled_proof = _set_rife_campaign_proof_state(
                        adb, serial, bounded_health_log, identity[0], True,
                        deadline=deadline,
                    )
                    pending_campaign_rearm = {
                        "scene": scene_rearm,
                        "proofCycle": {
                            "disabled": disabled_proof,
                            "enabled": enabled_proof,
                        },
                    }
                    deadline = min(
                        hard_cap,
                        max(deadline, time.monotonic() +
                            FRAMEGEN_LATENCY_CAPTURE_SECONDS),
                    )
                    continue
                fatal_rife_campaign_failure = True
                campaign = rife_timing.verify_campaign(
                    rife_campaign_reports)
                campaign["artifacts"] = rife_campaign_artifacts
                campaign["hardCaptureCapSeconds"] = capture_cap_seconds
                return records, captured_log, proof_gameplay, campaign
            except (OSError, ValueError, RuntimeError) as failure:
                if fatal_rife_campaign_failure:
                    raise
                last_failure = str(failure)
                remaining = _framegen_deadline_remaining(
                    deadline, timeout_failure())
                time.sleep(min(0.1, remaining))

    motion_thread.start()
    try:
        (latency_records, log_path, real_nes_proof_gameplay,
         rife_long_campaign) = \
            collect_latency_records()
    finally:
        # An ADB/dumpsys/logcat failure must stop physical input before control
        # returns to the per-system runner. A daemon surviving into the next
        # title would invalidate both its input trace and frame proof.
        motion_stop.set()
        motion_thread.join(timeout=2.0)
    real_nes_proof_health = None
    if case.folder == "nes":
        if real_nes_health_baseline is None:
            raise RuntimeError("real NES proof lost its HEALTH baseline")
        real_nes_proof_health = require_real_nes_proof_health(
            _framegen_health_records(
                log_path.read_text(encoding="utf-8", errors="replace"),
                "primary", 0,
            ),
            real_nes_health_baseline,
        )
    # The shader verifier samples an internal FBO and SurfaceFlinger proves
    # latches, neither of which proves that the Activity's final composition is
    # visible on the panel. Capture each physical display in the same evidence
    # window and bind those pixels to its role before a report may pass.
    visible_outputs: dict[tuple[str, int], dict[str, object]] = {
        ("primary", 0): screenshot(
            adb, serial, output / f"{prefix}-framegen-visible-primary.png"
        )
    }
    if n64_fzero_qualification:
        final_fzero = Path(str(visible_outputs[("primary", 0)]["path"]))
        if not n64_fzero_single_player_race_hud(final_fzero):
            raise RuntimeError(
                "F-Zero frame-generation proof did not end in the active "
                "one-player race HUD"
            )
    if case.dual_screen:
        visible_outputs[("secondary", 4)] = screenshot(
            adb, serial,
            output / f"{prefix}-framegen-visible-secondary.png",
            secondary_token(adb, serial),
        )
    if case.folder == "nes":
        if real_nes_title is None or real_nes_proof_gameplay is None:
            raise RuntimeError("real NES proof lacks gameplay-readiness evidence")
        proof_paths = [Path(str(item["path"]))
                       for item in real_nes_proof_gameplay["frames"]]
        final_visible = visible_outputs[("primary", 0)]
        proof_paths.append(Path(str(final_visible["path"])))
        # The compositor-bound end capture must still be gameplay and must
        # materially differ from the preceding proof checkpoint. This catches
        # r31's attract/demo -> static title regression after early motion.
        real_nes_proof_gameplay = analyze_real_nes_gameplay_frames(
            proof_paths, real_nes_title
        )
        real_nes_proof_gameplay["health"] = real_nes_proof_health
    report_path = output / f"{prefix}-framegen-report.json"
    if rife_qualification_requested:
        rife_passing, rife_rejected = _rife_latency_candidates(
            log_path.read_text(encoding="utf-8", errors="replace"),
            latency_records,
        )
        rife_selected = _unique_strongest_framegen_candidate(
            rife_passing, "primary", 0)
        if rife_selected is None:
            raise RuntimeError(
                "RIFE timing gate needs one uniquely strongest primary "
                f"gameplay layer; rejected={rife_rejected}"
            )
        rife_layer, rife_latency_path, rife_report = rife_selected
        if n64_fzero_qualification:
            if rife_long_campaign is None:
                raise RuntimeError(
                    "F-Zero RIFE proof lacks its required long moving-game "
                    "campaign"
                )
            final_identity = (
                int(rife_report["generator"]),
                int(rife_report["presentationEpoch"]),
                int(rife_report["timingWindow"]),
            )
            campaign_identities = {
                (int(segment["generator"]),
                 int(segment["presentationEpoch"]),
                 int(segment["timingWindow"]))
                for segment in rife_long_campaign["segments"]
            }
            if final_identity not in campaign_identities:
                raise RuntimeError(
                    "final F-Zero RIFE segment is not bound to the long "
                    "moving-game campaign"
                )
        visible_output = visible_outputs.get(("primary", 0))
        if visible_output is None:
            raise RuntimeError("RIFE timing proof has no primary visible capture")
        require_visible_frame_generation_output(visible_output, "primary", 0)
        rife_report.update({
            "passed": False,
            "layer": rife_layer,
            "candidateLayers": layers,
            "rejectedLayers": rife_rejected,
            "log": str(log_path),
            "latency": str(rife_latency_path),
            "visibleOutput": visible_output,
            "evidence": {
                "logSha256": sha256_file(log_path),
                "latencySha256": sha256_file(rife_latency_path),
            },
            "identity": {
                **qualification_identity,
                "generator": int(rife_report["generator"]),
                "presentationEpoch": int(
                    rife_report["presentationEpoch"]),
                "timingWindow": int(rife_report["timingWindow"]),
                "role": "primary",
                "displayId": 0,
                "timingStartNs": int(rife_report["timingStartNs"]),
                "timingEndNs": int(rife_report["timingEndNs"]),
            },
        })
        if rife_long_campaign is not None:
            rife_report["longMovingGameCampaign"] = rife_long_campaign
        report_path.write_text(
            json.dumps(rife_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            "app-owned RIFE timing and numeric content passed, but final "
            "qualification requires moving-game visual inspection; report=" +
            str(report_path)
        )
    passing: list[tuple[str, Path, dict[str, object]]] = []
    rejected: list[dict[str, object]] = []
    for layer, latency_path, role, display_id in latency_records:
        try:
            qualification_path, segment_id = _write_framegen_qualification(
                log_path, latency_path, output, prefix, role, display_id,
                qualification_identity,
            )
            candidate = frame_gen.verify(
                log_path, latency_path, role=role, display_id=display_id,
                qualification_path=qualification_path, segment_id=segment_id,
            )
            candidate["qualificationManifest"] = str(qualification_path)
        except (OSError, ValueError, RuntimeError) as failure:
            candidate = {"passed": False, "failures": [str(failure)]}
        visible_output = visible_outputs.get((role, display_id))
        if candidate["passed"]:
            try:
                if visible_output is None:
                    raise RuntimeError(
                        f"no visible-output capture for {role}/display-{display_id}"
                    )
                require_visible_frame_generation_output(
                    visible_output, role, display_id
                )
                candidate["motionBound"] = require_safe_motion_bound(
                    log_path.read_text(encoding="utf-8", errors="replace"),
                    candidate,
                )
            except RuntimeError as failure:
                candidate["passed"] = False
                candidate.setdefault("failures", []).append(str(failure))
        if visible_output is not None:
            candidate["visibleOutput"] = visible_output
        if candidate["passed"]:
            passing.append((layer, latency_path, candidate))
        else:
            rejected.append({"layer": layer, "latency": str(latency_path),
                             "role": role, "displayId": display_id,
                             "failures": candidate["failures"]})
    primary_passing = [item for item in passing
                       if item[2].get("role") == "primary" and
                       item[2].get("displayId") == 0]
    primary_selected = _unique_strongest_framegen_candidate(
        passing, "primary", 0)
    # No soft fallback selection here — the 2026-08-16 audit removed the
    # fabricated-overlap paths. The DS branch below is NOT that: the
    # secondary candidate passed the exact same dense gates, latency
    # capture, and visible-output binding as any primary; only the display
    # it played on differs.
    if primary_selected is None and case.folder == "nds":
        # DS games choose their own gameplay screen: Hunters plays on the
        # DS top screen (Thor main display 0), Castlevania PoR/OoE play on
        # the DS touch screen (Thor lower display 4, faithful to hardware).
        # Qualify the display that actually carries the gameplay — the
        # full evidence contract, unweakened, just on role=secondary. The
        # top-screen map legitimately idles at 1x there.
        primary_selected = _unique_strongest_framegen_candidate(
            passing, "secondary", 4)
        if primary_selected is not None:
            primary_selected[2]["qualifyingRole"] = "secondary"
            primary_selected[2]["qualifyingDisplayId"] = 4
    if primary_selected is None:
        raise RuntimeError(
            "frame-generation gate needs one uniquely strongest primary "
            f"gameplay layer; passed={len(primary_passing)} rejected={rejected}"
        )
    layer, latency_path, report = primary_selected
    report["layer"] = layer
    report["candidateLayers"] = layers
    report["rejectedLayers"] = rejected
    report["log"] = str(log_path)
    report["latency"] = str(latency_path)
    if real_nes_proof_gameplay is not None:
        report["realNesGameplayProof"] = real_nes_proof_gameplay
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    report["reportPath"] = str(report_path)
    if not report["passed"]:
        raise RuntimeError("frame-generation evidence failed: " +
                           "; ".join(report["failures"]))
    if case.dual_screen and case.folder in {"nds", "n3ds"}:
        report["secondaryIdentityOnly"] = True
        report["secondaryLayerCount"] = len(secondary_layers)
    elif case.dual_screen:
        secondary_passing = [item for item in passing
                             if item[2].get("role") == "secondary" and
                             item[2].get("displayId") == 4]
        secondary_selected = _unique_strongest_framegen_candidate(
            passing, "secondary", 4)
        if secondary_selected is None:
            raise RuntimeError(
                "frame-generation gate needs one uniquely strongest secondary "
                "display-4 gameplay layer; "
                f"passed={len(secondary_passing)} rejected={rejected}"
            )
        secondary_layer, secondary_latency, secondary_report = secondary_selected
        require_independent_dual_generators(report, secondary_report)
        if secondary_layer == layer:
            raise RuntimeError(
                "primary and secondary cadence were read from the same compositor layer"
            )
        secondary_report["layer"] = secondary_layer
        secondary_report["candidateLayers"] = secondary_layers
        secondary_report["rejectedLayers"] = rejected
        secondary_report["log"] = str(log_path)
        secondary_report["latency"] = str(secondary_latency)
        secondary_path = output / f"{prefix}-framegen-secondary-report.json"
        secondary_path.write_text(
            json.dumps(secondary_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report["secondary"] = secondary_report
    return report


def _music_volume(adb: Path, serial: str) -> int:
    text = qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
                  "--stream", "3", "--get").stdout
    match = re.search(r"volume is (\d+) in range", text)
    if match is None:
        raise RuntimeError("unable to read STREAM_MUSIC volume")
    return int(match.group(1))


def _log_delta(before: str, after: str) -> str:
    return after[len(before):] if after.startswith(before) else after


def _capture_exact_volume_pair(adb: Path, serial: str,
                               controller: PhysicalController, output: Path,
                               prefix: str, sequence: int,
                               direction: str,
                               device_sleep_ms: float) -> tuple[dict[str, object], str]:
    code = controller.VOLUME_DOWN if direction == "down" else controller.VOLUME_UP
    expected_delta = -1 if direction == "down" else 1
    # adb shell latency occasionally stretches the intended 40 ms hold past
    # the verifier's 35-60 ms quick-tap band (physically hit 2026-08-15).
    # An out-of-band tap is discarded: the volume state is restored and the
    # tap re-attempted, bounded. The recorded pair is always a genuine
    # kernel-timed in-band tap — the acceptance band itself is unchanged.
    before = _music_volume(adb, serial)
    baseline_log = qa.logs(adb, serial)
    edge = None
    for attempt in range(3):
        before = _music_volume(adb, serial)
        baseline_log = qa.logs(adb, serial)
        try:
            edge = controller.exact_quick_key_pair(
                code, f"physical-volume-{direction}-exact-40ms", hold_ms=40,
                device_sleep_ms=device_sleep_ms,
            )
        except RuntimeError:
            # A truncated getevent capture (missing UP edge) is a capture
            # artefact, not tap evidence; restore and retry bounded. The
            # final attempt still surfaces the parser's error verbatim.
            if attempt >= 2:
                raise
            qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
                   "--stream", "3", "--set", str(before), check=False)
            time.sleep(0.25)
            continue
        if 35.0 <= float(edge.get("holdMs", 0.0)) <= 60.0:
            break
        qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
               "--stream", "3", "--set", str(before), check=False)
        time.sleep(0.25)
    # AppVolumeController's vendor-route reconciliation is posted at 32 ms.
    # Read once after it and once again after the key has been up long enough
    # to catch a forbidden late/default adjustment.
    time.sleep(0.08)
    after = _music_volume(adb, serial)
    time.sleep(0.08)
    settled = _music_volume(adb, serial)
    delta_log = _log_delta(baseline_log, qa.logs(adb, serial))
    expected = before + expected_delta
    level_changes = [int(value) for value in re.findall(
        r"writeEvent level_changed STREAM_MUSIC (\d+)", delta_log
    )]
    applied = [int(value) for value in re.findall(
        r"Applied STREAM_MUSIC gain index=(\d+)", delta_log
    )]
    kernel_trace = str(edge.pop("kernelTrace", ""))
    trace_path = output / f"{prefix}-volume-pair-{sequence:02d}-getevent.txt"
    log_path = output / f"{prefix}-volume-pair-{sequence:02d}-logcat.txt"
    trace_path.write_text(kernel_trace, encoding="utf-8")
    log_path.write_text(delta_log, encoding="utf-8")
    pair = {
        "direction": direction,
        "before": before,
        "after": after,
        "settledAfter": settled,
        "levelChangedIndices": level_changes,
        "controllerAppliedIndices": applied,
        "kernelTrace": str(trace_path),
        "logcat": str(log_path),
        **edge,
    }
    # Fail at the pair boundary, before a later tap can hide this tap's skip or
    # double adjustment by eventually reaching the same final index.
    pair_errors = volume_proof.verify_pair(pair, sequence - 1)
    if pair_errors:
        raise RuntimeError("; ".join(pair_errors))
    if after != expected:
        raise RuntimeError(
            f"exact quick {direction} moved {before}->{after}; expected {expected}"
        )
    return pair, delta_log


def quick_tap_volume_evidence(adb: Path, serial: str,
                              controller: PhysicalController, output: Path,
                              prefix: str, apk_sha256: str,
                              pid: int) -> dict[str, object]:
    """Prove discrete key-up/key-down taps control live EmuFusion audio.

    Every pair is timed by the kernel's getevent timestamps, not the host.  The
    stream index and SystemUI transition log are isolated per pair so a later
    tap cannot conceal a skip, duplicate adjustment, ACTION_UP adjustment, or
    long-press repeat.
    """
    original = _music_volume(adb, serial)
    start = 5
    pairs: list[dict[str, object]] = []
    pair_logs: list[str] = []
    try:
        qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
               "--stream", "3", "--set", str(start))
        time.sleep(0.25)
        # Android's shell starts one native sendevent process for every edge.
        # Measure that fixed device-side launch cost once, then shorten only
        # the sleep between the real evidence edges. The kernel timestamps,
        # never this estimate, remain the acceptance clock.
        calibration = controller.exact_quick_key_pair(
            controller.VOLUME_DOWN, "physical-volume-calibration",
            hold_ms=1, device_sleep_ms=1,
        )
        shell_overhead_ms = max(0.0, float(calibration["holdMs"]) - 1.0)
        device_sleep_ms = max(1.0, 40.0 - shell_overhead_ms)
        qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
               "--stream", "3", "--set", str(start))
        time.sleep(0.20)
        before_audio = qa.adb(adb, serial, "shell", "dumpsys",
                              "media.audio_flinger").stdout
        for sequence in range(1, start + 1):
            pair, delta = _capture_exact_volume_pair(
                adb, serial, controller, output, prefix, sequence, "down",
                device_sleep_ms,
            )
            pairs.append(pair)
            pair_logs.append(delta)
        muted = _music_volume(adb, serial)
        muted_audio = qa.adb(adb, serial, "shell", "dumpsys",
                             "media.audio_flinger").stdout
        for sequence in range(start + 1, start * 2 + 1):
            pair, delta = _capture_exact_volume_pair(
                adb, serial, controller, output, prefix, sequence, "up",
                device_sleep_ms,
            )
            pairs.append(pair)
            pair_logs.append(delta)
        restored = _music_volume(adb, serial)
        restored_audio = qa.adb(adb, serial, "shell", "dumpsys",
                                "media.audio_flinger").stdout
    finally:
        # Restore the owner's setting even if an individual pair fails closed.
        qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
               "--stream", "3", "--set", str(original), check=False)

    complete_delta = "\n".join(pair_logs)
    (output / f"{prefix}-volume-logcat.txt").write_text(
        complete_delta, encoding="utf-8"
    )
    (output / f"{prefix}-audio-before.txt").write_text(
        before_audio, encoding="utf-8"
    )
    (output / f"{prefix}-audio-muted.txt").write_text(
        muted_audio, encoding="utf-8"
    )
    (output / f"{prefix}-audio-restored.txt").write_text(
        restored_audio, encoding="utf-8"
    )
    muted_gain_proved = bool(re.search(
        r"Applied STREAM_MUSIC gain index=0 gain=0(?:\.0+)?\b", complete_delta
    ))
    report = {
        "schemaVersion": volume_proof.SCHEMA,
        "package": PACKAGE,
        "apkSha256": apk_sha256.lower(),
        "pid": pid,
        "original": original,
        "start": start,
        "muted": muted,
        "restored": restored,
        "quickPairs": pairs,
        "systemStreamIndexAtMute": muted,
        "controllerGainAtMute": 0.0 if muted_gain_proved else None,
        # Sink-family evidence is accumulated by dedicated menu/preview and
        # engine-family trials. This gameplay trial must never pretend that its
        # one active Dolphin sink is the complete app inventory.
        "sinkInventoryComplete": False,
        "sinks": [],
        "registeredSinkIdsAtMute": [],
    }
    quick_errors = volume_proof.verify_quick_pairs(
        report, expected_apk_sha256=apk_sha256
    )
    report_path = output / f"{prefix}-volume-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    if quick_errors:
        raise RuntimeError("exact quick-tap volume evidence failed: " +
                           "; ".join(quick_errors))
    return report


def run_system(adb: Path, serial: str, controller: PhysicalController,
               case: SystemCase, visible_order: list[str], index: dict,
               output: Path, titles: int, expected_sha: str,
               hash_guards: list[dict[str, object]], apk: Path,
               display_names: dict[str, str]) -> dict[str, object]:
    hash_guards.append({"system": case.folder, "point": "before-system",
                        **assert_installed_hash(adb, serial, expected_sha)})
    # Resolve every slow filesystem/metadata prerequisite before opening the
    # interactive Alpha list.  Once Alpha row zero is established, the only
    # work before navigation must be immediate controller/screenshot proof;
    # otherwise the enabled OLED screensaver is entitled to move the cursor.
    keys = alpha_keys(index, case)
    requested_titles = max(titles, 4) if case.folder == "nes" else titles
    playable_keys = playable_alpha_keys(
        adb, serial, case, keys, requested_titles,
        (("Lucent Callback Test", *NES_REAL_QUALIFICATION_TITLES)
         if case.folder == "nes" else ()),
    )
    nes_fixture = indexed_nes_qualification(adb, serial, case, playable_keys) \
        if case.folder == "nes" else None
    if nes_fixture is None:
        planned_titles = acceptance_titles(case, playable_keys, requested_titles)
    else:
        # The synthetic ROM is a deterministic controls/audio/frame-generation
        # calibration fixture, never a substitute for real-game acceptance.
        planned_titles = [nes_fixture["title"], *NES_REAL_QUALIFICATION_TITLES]
        playable_titles = {
            normalize(title_from_key(key)) for key in playable_keys
        }
        missing_real = [title for title in NES_REAL_QUALIFICATION_TITLES
                        if normalize(title) not in playable_titles]
        if missing_real:
            raise RuntimeError(
                "NES real-game qualification ROMs are absent: " +
                ", ".join(missing_real)
            )
    # Hashing a packaged engine can take many seconds on the host.  It is a
    # launch prerequisite, not interactive UI work, so finish it before the
    # frontend list is opened.  Physical N64 r5 otherwise left the proven A-Z
    # row idle for ~17 seconds and the enabled screensaver legitimately moved
    # the cursor before the first navigation checkpoint.
    core_hashes = {normalize(engine): packaged_engine_sha256(apk, engine)
                   for engine in case.engines}
    # The stepped origin can land systematically short: once enough recent
    # sessions exist the Cover screen grows a Continue Playing rail that
    # shifts the deterministic All-Systems origin by one (physically hit
    # three times in a row, landing on WINDOWS instead of switch, runs
    # switch14-16, 2026-08-16). Blindly rebuilding the same origin repeats
    # the same offset, so correct RELATIVELY: OCR the system actually landed
    # on and step the exact signed difference — still fail-closed, because
    # the final OCR proof must name the requested system.
    go_to_cover_system(controller, visible_order, case.folder)
    for origin_attempt in range(4):
        cover = output / f"{case.folder}-cover.png"
        screenshot(adb, serial, cover)
        try:
            assert_cover_system(cover, case.folder, display_names)
            break
        except AlphaNavigationDrift:
            if origin_attempt == 3:
                raise
            observed_header = " ".join(
                " ".join(ocr_region(cover, (35, 135, 1120, 255), psm).split())
                for psm in (6, 7, 11)
            )
            landed = resolve_list_folder(observed_header, display_names)
            if landed in visible_order and landed != case.folder:
                delta = (visible_order.index(case.folder) -
                         visible_order.index(landed))
                key = controller.RIGHT if delta > 0 else controller.LEFT
                for _ in range(abs(delta)):
                    controller.key(key, "dpad-origin-correct", hold=0.07)
            else:
                go_to_cover_system(controller, visible_order, case.folder)
            time.sleep(1.0)
    controller.key(controller.A, "physical-a-open-system", hold=0.055)
    time.sleep(0.35)
    _, current_position = force_alpha_list(
        adb, serial, controller, output, case.folder,
        case.folder, display_names, keys,
    )
    results = []
    for title_index, title in enumerate(planned_titles):
        current_position = select_title_alpha(
            adb, serial, controller, case, visible_order, display_names, keys,
            current_position, title, output,
            f"{case.folder}-title-{title_index + 1:02d}",
        )
        qualification = nes_fixture if (nes_fixture is not None and
            normalize(title) == normalize(nes_fixture["title"])) else None
        rom_identity = (qualification if qualification is not None else
                        indexed_title_rom_identity(adb, serial, case, title))
        original_volume = None
        try:
            if qualification is not None:
                original_volume = _music_volume(adb, serial)
                # The r2 failure started muted. Audio qualification controls an
                # audible STREAM_MUSIC index and restores the owner's exact
                # prior index even when any later gate fails.
                if original_volume != 5:
                    qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
                           "--stream", "3", "--set", "5")
                    time.sleep(0.20)
                    if _music_volume(adb, serial) != 5:
                        raise RuntimeError("NES qualification could not establish audible volume")
            game = run_game_from_system_menu(
                adb, serial, controller, case, output,
                f"{case.folder}-title-{title_index + 1:02d}",
                title, expected_sha, qualification, rom_identity, core_hashes,
                apk,
            )
            if title_index < len(case.required_source_tiers):
                require_frame_generation_source_tier(
                    game, case.required_source_tiers[title_index],
                    case.folder, title,
                )
            if qualification is not None:
                game["controlledMusicVolume"] = {
                    "ownerIndex": original_volume,
                    "qualificationIndex": 5,
                    "restoredInFinally": True,
                }
                game["qualificationRole"] = {
                    "calibrationFixture": True, "realGame": False,
                }
            elif case.folder == "nes":
                game["qualificationRole"] = {
                    "calibrationFixture": False, "realGame": True,
                }
            results.append(game)
        finally:
            if original_volume is not None:
                qa.adb(adb, serial, "shell", "cmd", "media_session", "volume",
                       "--stream", "3", "--set", str(original_volume), check=False)
            cleanup_failures = finish_abandoned_nes_captures()
            if cleanup_failures:
                active_failure = sys.exc_info()[1]
                message = "NES capture cleanup failed: " + "; ".join(cleanup_failures)
                if active_failure is not None and hasattr(active_failure, "add_note"):
                    active_failure.add_note(message)
                elif active_failure is None:
                    raise RuntimeError(message)
        hash_guards.append({"system": case.folder, "title": title,
                            "point": "after-game",
                            **assert_installed_hash(adb, serial, expected_sha)})
    real_game_closure = write_nes_real_game_closure(output, results) \
        if nes_fixture is not None else None
    return {"status": "PASS", "system": case.folder, "phase": case.phase,
            "coverEntryPhysical": True, "systemMenuPhysical": True,
            "alphaIndexPhysical": True,
            "requiredTitles": list(case.required_titles),
            "requiredSourceTiers": list(case.required_source_tiers),
            "nesQualificationFixture": nes_fixture,
            "nesFixtureRole": "calibration-only" if nes_fixture else None,
            "nesRequiredRealTitles": (list(NES_REAL_QUALIFICATION_TITLES)
                                       if nes_fixture else []),
            "nesRealGameClosure": real_game_closure,
            "testedTitles": planned_titles,
            "titles": results}


def run_list_view_smoke(adb: Path, serial: str,
                        controller: PhysicalController, case: SystemCase,
                        visible_order: list[str], display_names: dict[str, str],
                        output: Path, expected_sha: str, apk: Path) -> dict[str, object]:
    # The List view's left system column does NOT share the Cover view's
    # origin/order (visibleSystemOrder): the aggregate "all" entry is absent and
    # the column stays scrolled to the previously-selected system. Counting UP
    # then DOWN by Cover-view indices therefore lands on the wrong system (a run
    # targeting n64 launched gba/mgba). Instead navigate in the List view's own
    # space by OCR'ing the highlighted system after every move.
    #
    # 25 ms pulses are documented as loseable on the Thor (handover QA lessons);
    # a dropped press leaves the cursor short of its target. Use the proven
    # >=40 ms duration the rest of this harness uses.
    controller.stick("down")
    bound = len(visible_order) + 3

    # Press UP until the highlighted system stops changing (the true top of the
    # left column), tolerating unreadable frames without treating them as the
    # top.
    top_frame = output / f"list-view-{case.folder}-top.png"
    settled = None
    for _ in range(bound):
        screenshot(adb, serial, top_frame)
        observed = list_view_highlighted_folder(top_frame, display_names)
        if observed is not None and observed == settled:
            break
        settled = observed
        controller.key(controller.UP, "dpad-up-list-system", hold=0.045)

    # Press DOWN until the highlighted system's canonical folder == case.folder.
    list_frame = output / f"list-view-{case.folder}.png"
    reached = False
    observed = None
    for _ in range(bound):
        screenshot(adb, serial, list_frame)
        observed = list_view_highlighted_folder(list_frame, display_names)
        if observed == case.folder:
            reached = True
            break
        controller.key(controller.DOWN, "dpad-down-list-system", hold=0.045)
    if not reached:
        screenshot(adb, serial, list_frame)
        observed = list_view_highlighted_folder(list_frame, display_names)
        reached = observed == case.folder
    if not reached:
        raise RuntimeError(
            f"list view never highlighted {case.folder}; last resolved system "
            f"was {observed!r} (bounded by {bound} moves)"
        )

    controller.key(controller.A, "physical-a-lock-list-system", hold=0.055)
    time.sleep(0.25)
    # run_system() leaves every system on the exact title it just qualified,
    # and visible-return acceptance proves that selection was restored. The
    # List-view smoke deliberately reopens the first system, so bind this
    # second launch to that same required title and immutable ROM/core hashes.
    # Calling the gameplay verifier with empty hashes made an otherwise valid
    # list launch fail only because the harness labelled its identity unknown.
    expected_title = case.required_titles[0]
    rom_identity = indexed_title_rom_identity(
        adb, serial, case, expected_title
    )
    core_hashes = {
        normalize(engine): packaged_engine_sha256(apk, engine)
        for engine in case.engines
    }
    # The smoke verifies RELAUNCH health — route, visible frames, engine
    # telemetry, volume, dual-screen visibility, stop/return. It does not
    # drive gameplay, so the relaunched title legitimately idles on a static
    # title screen where presents pause and dense motion cannot exist;
    # neither state distinguishes relaunch failure. The MAIN qualification
    # that just ran on this exact launch stack owns the frame-generation
    # bar, so the smoke skips only that phase (physically hit on wiiu7 and
    # ps2-1 relaunches, 2026-08-17).
    result = run_game_from_system_menu(
        adb, serial, controller, case, output,
        f"list-view-{case.folder}-title-01",
        expected_title=expected_title, expected_sha=expected_sha,
        rom_identity=rom_identity, core_hashes=core_hashes, apk=apk,
        smoke_no_framegen=True,
    )
    return {"status": "PASS", "system": case.folder,
            "listEntryPhysical": True,
            "listHighlightResolved": observed,
            "framegenPhaseSkipped": "smoke-relaunch-health-only",
            "game": result}


def persist(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def external_route_systems(route_text: str) -> set[str]:
    """Canonical systems whose startup launch line is a legitimate EXTERNAL route.

    Per-system external routing (docs/external-emulator-routing.md) is now a
    product feature: a system with no packaged internal engine — or one a user
    deliberately set to external — emits a plain ``am start`` (VIEW install page,
    external component, or the RomLaunchActivity trampoline) instead of EmuFusion's
    internal in-window launch. Those systems have no internal engine to match,
    so they are exempt from the strict internal route-closure comparison.

    The exemption is derived only from ``verify_menu_route_closure.launcher_audit``
    classifying the line as ``external-route``; the strict internal contract for
    every internal in-window launch line is untouched, and a non-Lucent / stale
    launcher never audits as ``external-route`` so it is never exempted here.
    """
    externals: set[str] = set()
    current_shortnames: list[str] = []
    for raw in route_text.splitlines():
        line = raw.strip()
        if line.startswith("collection:"):
            current_shortnames = []
        elif line.startswith("shortname:"):
            shortname = route_closure.normalized(line.split(":", 1)[1])
            if shortname:
                current_shortnames.append(shortname)
        elif line.startswith("launch:"):
            audit = route_closure.launcher_audit(line)
            if audit and audit[0]["kind"] == "external-route":
                for shortname in current_shortnames:
                    externals.add(route_closure.canonical_system_id(shortname))
    return externals


def _runtime_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix", type=Path,
                        default=Path(__file__).with_name("runtime-acceptance-matrix.json"))
    parser.add_argument("--system", action="append")
    parser.add_argument("--titles-per-system", type=int, default=3,
                        choices=(1, 2, 3))
    parser.add_argument(
        "--nes-qualification-fixture", type=Path,
        default=ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes",
        help="exact frozen fixture staged and ownership-cleaned when NES is selected",
    )
    parser.add_argument("--skip-list-view-smoke", action="store_true")
    parser.add_argument("--stop-on-first-failure", action="store_true")
    parser.add_argument("--allow-physical-thor", action="store_true")
    parser.add_argument("--already-installed", action="store_true",
                        help="verify the installed base hash without replacing it again")
    parser.add_argument("--allow-research-phase3", action="store_true",
                        help="device-qualify exact packaged Eden/Cemu/aPS3e routes without "
                             "claiming their registry release gates are complete")
    parser.add_argument("--adb", type=Path,
                        default=Path.home() / ".codex/tools/android-platform-tools/adb")
    args = parser.parse_args()
    if not args.allow_physical_thor:
        raise SystemExit("runtime acceptance requires --allow-physical-thor")
    apk = args.apk.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, stat.S_IRWXU)
    manufacturer = qa.adb(args.adb, args.serial, "shell", "getprop",
                          "ro.product.manufacturer").stdout.strip()
    model = qa.adb(args.adb, args.serial, "shell", "getprop",
                   "ro.product.model").stdout.strip()
    if "ayn" not in manufacturer.lower() or "thor" not in model.lower():
        raise SystemExit(f"target is not an AYN Thor: {manufacturer=} {model=}")

    report: dict[str, object] = {
        "schemaVersion": 1,
        "target": {"serial": args.serial, "manufacturer": manufacturer,
                   "model": model},
        "apk": str(apk), "expectedSha256": args.expected_sha256.lower(),
        "menuThemeFrozen": False, "routeClosure": {}, "systems": [],
        "installedHashGuards": [],
        "listViewSmoke": None, "counts": {"PASS": 0, "FAIL": 0},
    }
    result_path = output / "results.json"
    persist(result_path, report)

    frozen_errors = verify_frozen_menu(apk)
    if frozen_errors:
        report["preflightFailure"] = frozen_errors
        persist(result_path, report)
        raise RuntimeError("; ".join(frozen_errors))
    report["menuThemeFrozen"] = True

    sdk_build_tools = Path.home() / "Library/Android/sdk/build-tools"
    dexdump = latest_tool(sdk_build_tools, "dexdump")
    # Crucially, collection shortnames come from the owner's installed metadata.
    # A host-only predecessor may intentionally have no launch lines, so model
    # exactly what this candidate's GameLaunchRouter will write at startup.
    metadata_text = route_closure.device_route_text(args.adb, args.serial)
    metadata_systems = route_closure.collection_shortnames(metadata_text)
    routes, simulation_report = route_closure.simulate_candidate_routes(
        apk, metadata_systems, dexdump
    )
    closure_errors, closure_report = route_closure.verify(apk, routes, dexdump)
    if args.allow_research_phase3:
        allowed_research = {
            ("switch", "eden"), ("wiiu", "cemu"), ("ps3", "aps3e")
        }
        closure_errors = [error for error in closure_errors if not any(
            error.startswith(f"{system}/{engine}: not eligible")
            for system, engine in allowed_research
        )]
    closure_report["preinstallSimulation"] = simulation_report
    preinstall_launchers = route_closure.launcher_audit(metadata_text)
    closure_report["installedLauncherStateBeforeReplacement"] = {
        "total": len(preinstall_launchers),
        "interceptedSameActivityStart": sum(
            row["kind"] == "intercepted-same-activity-start"
            for row in preinstall_launchers
        ),
        "staleAmStart": sum(row["kind"] == "stale-am-start"
                            for row in preinstall_launchers),
        "staleAmBroadcast": sum(row["kind"] == "stale-am-broadcast"
                                for row in preinstall_launchers),
        "externalOrInvalid": sum(row["kind"] == "external-or-invalid"
                                 for row in preinstall_launchers),
        "commands": preinstall_launchers,
    }
    if not simulation_report["candidateDexAliasContract"]["pass"]:
        closure_errors.append(
            simulation_report["candidateDexAliasContract"]["detail"]
        )
    closure_errors.extend(simulation_report["aliasContractFailures"])
    closure_report["existingLaunchLineCount"] = len(
        re.findall(r"^launch:", metadata_text, re.M)
    )
    report["routeClosure"] = closure_report
    persist(result_path, report)
    if closure_errors:
        raise RuntimeError("menu route/core closure failed before install")

    verifier = ROOT / "unified-android/tools/verify_one_app_apk.py"
    aapt = latest_tool(sdk_build_tools, "aapt")
    subprocess.run(one_app_verifier_command(verifier, aapt, apk),
                   cwd=ROOT, check=True)
    report["exactInstall"] = exact_install(
        args.adb, args.serial, apk, args.expected_sha256, output,
        perform_install=not args.already_installed,
    )
    # Keep the digest evidence, not a redundant hundreds-of-megabytes copy.
    (output / "installed-base.apk").unlink(missing_ok=True)

    qa.adb(args.adb, args.serial, "shell", "am", "force-stop", PACKAGE)
    # The identity binding requires the launch-time "In-window route
    # accepted" line to still be in the ring when the framegen logcat is
    # dumped. Flycast's audio-drop telemetry rotated it out of the default
    # buffer (run dreamcast5, 2026-08-20: zero route lines in a 28-route
    # grep of the bounded log). Size the ring once per run; -G does not
    # survive a device reboot.
    qa.adb(args.adb, args.serial, "logcat", "-G", "16M")
    qa.adb(args.adb, args.serial, "logcat", "-c")
    qa.ensure_library(args.adb, args.serial)
    deadline = time.monotonic() + 30.0
    index = None
    while time.monotonic() < deadline:
        try:
            index = library_index(args.adb, args.serial)
            if isinstance(index.get("systems"), dict):
                break
        except Exception:
            pass
        time.sleep(0.5)
    if index is None:
        raise RuntimeError("Lucent library index did not become available")

    # Recheck after installation/startup in case the candidate regenerated any
    # launch metadata. A newly exposed route cannot bypass exact core closure.
    installed_route_text = route_closure.device_route_text(args.adb, args.serial)
    installed_routes = route_closure.routes_from_text(installed_route_text)
    post_errors, post_report = route_closure.verify(apk, installed_routes, dexdump)
    if args.allow_research_phase3:
        allowed_research = {
            ("switch", "eden"), ("wiiu", "cemu"), ("ps3", "aps3e")
        }
        post_errors = [error for error in post_errors if not any(
            error.startswith(f"{system}/{engine}: not eligible")
            for system, engine in allowed_research
        )]
    post_launchers = route_closure.launcher_audit(installed_route_text)
    post_report["startupLauncherState"] = {
        "total": len(post_launchers),
        "interceptedSameActivityStart": sum(
            row["kind"] == "intercepted-same-activity-start"
            for row in post_launchers
        ),
        "staleAmStart": sum(row["kind"] == "stale-am-start"
                            for row in post_launchers),
        "staleAmBroadcast": sum(row["kind"] == "stale-am-broadcast"
                                for row in post_launchers),
        "externalOrInvalid": sum(row["kind"] == "external-or-invalid"
                                 for row in post_launchers),
        "commands": post_launchers,
    }
    post_invalid = route_closure.invalid_launch_lines(installed_route_text)
    if post_invalid:
        post_report["invalidMetadataLaunchers"] = post_invalid
        post_errors.extend(
            "startup metadata has a non-Lucent launcher: " + row["commandSha256"]
            for row in post_invalid
        )
    # Per-system EXTERNAL routing is legitimate: a system that resolves external
    # (its startup launch line audits as an "external-route") intentionally has
    # no packaged internal engine, so it must NOT be required to match one. The
    # strict internal closure below still holds for every INTERNAL in-window
    # route — installed_routes only ever carries engine_id lines, which verify()
    # already binds to an exact packaged engine, and invalidMetadataLaunchers
    # still fails any non-Lucent launcher.
    external_systems = external_route_systems(installed_route_text)
    post_report["externalRoutedSystems"] = sorted(external_systems)
    internal_installed_routes = {
        route for route in installed_routes if route.system not in external_systems
    }
    expected_internal_routes = {
        route for route in routes if route.system not in external_systems
    }
    if args.allow_research_phase3:
        expected_internal_routes |= {
            route for route in internal_installed_routes
            if (route.system, route.engine) in
               {("switch", "eden"), ("wiiu", "cemu"), ("ps3", "aps3e")}
        }
    if internal_installed_routes != expected_internal_routes:
        post_report["expectedCandidateRoutes"] = [
            {"system": route.system, "engine": route.engine}
            for route in sorted(expected_internal_routes)
        ]
        post_report["actualStartupRoutes"] = [
            {"system": route.system, "engine": route.engine}
            for route in sorted(internal_installed_routes)
        ]
        post_errors.append("startup internal routes differ from preinstall GameLaunchRouter simulation")
    report["routeClosureAfterStartup"] = post_report
    persist(result_path, report)
    if post_errors:
        raise RuntimeError("startup exposed a menu route without an exact packaged engine")

    matrix = load_matrix(args.matrix)
    selected = {normalize(value) for value in (args.system or [])}
    if args.system:
        cases = []
        for requested in args.system:
            key = normalize(requested)
            match = next((case for case in matrix
                          if case.folder == key or key in case.aliases), None)
            if match is None:
                raise RuntimeError(f"unknown requested runtime system: {requested}")
            if match not in cases:
                cases.append(match)
    else:
        cases = list(matrix)
    nes_stage = None
    if any(case.folder == "nes" for case in cases):
        nes_stage = stage_nes_qualification_fixture(
            args.adb, args.serial, args.nes_qualification_fixture
        )
        report["nesFixtureLifecycle"] = {"stage": nes_stage, "cleanup": None}
        global ACTIVE_NES_STAGE_CONTEXT
        ACTIVE_NES_STAGE_CONTEXT = {
            "adb": args.adb, "serial": args.serial, "stage": nes_stage,
            "report": report, "resultPath": result_path,
        }
        index = library_index(args.adb, args.serial)
    visible_order = visible_system_order(apk, index)
    report["visibleSystemOrder"] = visible_order
    display_names = catalog_display_names(apk)
    missing = [case.folder for case in cases if case.folder not in visible_order]
    if missing:
        raise RuntimeError("required Thor library systems are not visible: " +
                           ", ".join(missing))

    event_node = qa.thor_controller_events(args.adb, args.serial)[0]
    controller = PhysicalController(args.adb, args.serial, event_node)
    report["controller"] = {"node": event_node, "physicalOnly": True,
                            "rightStickAxes": controller.axes}
    controller.neutralize("physical-neutralize-before-menu")
    # Import/staging can legitimately outlive the menu's idle timeout. Wake a
    # previewing screensaver through the same physical controller path a person
    # uses before asking OCR to prove the interactive library is visible.
    # go_to_cover_system() subsequently establishes its own deterministic
    # navigation origin, so this wake tap cannot bias a title selection.
    controller.key(
        controller.DOWN, "physical-wake-after-import", hold=0.045
    )
    time.sleep(0.35)
    report["visibleMenuReadyFrame"] = str(
        wait_visible_menu(args.adb, args.serial, output)
    )
    persist(result_path, report)
    records = report["systems"]
    for case in cases:
        try:
            record = run_system(args.adb, args.serial, controller, case,
                                visible_order, index, output,
                                args.titles_per_system, args.expected_sha256,
                                report["installedHashGuards"], apk,
                                display_names)
        except Exception as error:
            record = {"status": "FAIL", "system": case.folder,
                      "phase": case.phase, "reason": str(error)}
            (output / f"{case.folder}-failure-logcat.txt").write_text(
                qa.logs(args.adb, args.serial), encoding="utf-8")
            (output / f"{case.folder}-failure-activities.txt").write_text(
                qa.activity_dump(args.adb, args.serial), encoding="utf-8")
            (output / f"{case.folder}-failure-windows.txt").write_text(
                qa.window_dump(args.adb, args.serial), encoding="utf-8")
        records.append(record)
        report["counts"] = {
            "PASS": sum(row["status"] == "PASS" for row in records),
            "FAIL": sum(row["status"] == "FAIL" for row in records),
        }
        persist(result_path, report)
        print(f"{record['status']:4} {case.folder}", flush=True)
        if args.stop_on_first_failure and record["status"] == "FAIL":
            break

    if not args.skip_list_view_smoke and cases and report["counts"]["FAIL"] == 0:
        try:
            report["listViewSmoke"] = run_list_view_smoke(
                args.adb, args.serial, controller, cases[0], visible_order,
                display_names, output, args.expected_sha256, apk
            )
        except Exception as error:
            report["listViewSmoke"] = {"status": "FAIL", "reason": str(error)}
            report["counts"]["FAIL"] += 1

    controller.neutralize("physical-neutralize-after-run")
    report["inputTrace"] = [trace.__dict__ for trace in controller.trace]
    report["complete"] = report["counts"]["FAIL"] == 0
    persist(result_path, report)
    return 0 if report["complete"] else 1


def main() -> int:
    global ACTIVE_NES_STAGE_CONTEXT
    try:
        return _runtime_main()
    finally:
        active_failure = sys.exc_info()[1]
        context = ACTIVE_NES_STAGE_CONTEXT
        ACTIVE_NES_STAGE_CONTEXT = None
        if context is not None:
            try:
                cleanup = cleanup_nes_qualification_fixture(
                    Path(context["adb"]), str(context["serial"]),
                    context["stage"],
                )
                report = context["report"]
                report["nesFixtureLifecycle"]["cleanup"] = cleanup
                persist(Path(context["resultPath"]), report)
            except Exception as error:
                message = "NES qualification fixture cleanup failed: " + str(error)
                report = context["report"]
                report["nesFixtureLifecycle"]["cleanup"] = {
                    "performed": False, "error": str(error),
                    "absenceVerified": False,
                }
                report["complete"] = False
                persist(Path(context["resultPath"]), report)
                if active_failure is not None and hasattr(active_failure, "add_note"):
                    active_failure.add_note(message)
                elif active_failure is None:
                    raise RuntimeError(message) from error


if __name__ == "__main__":
    raise SystemExit(main())
