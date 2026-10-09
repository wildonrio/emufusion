#!/usr/bin/env python3
"""Fail closed unless an APK preserves EmuFusion's one-app emulation boundary."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import zipfile


PACKAGE = "com.thorium.preview"
MAIN_ACTIVITY = "org.pegasus_frontend.android.MainActivity"
EXTERNAL_STOP_SERVICE = "com.thorium.preview.ExternalStopAccessibilityService"
LSFG_SELF_TEST_ACTIVITY = (
    "com.thorium.preview.game.LsfgQualificationSelfTestActivity"
)
LSFG_QUALIFICATION_LIBRARY = (
    "lib/arm64-v8a/liblucent_lsfg_qualification.so"
)
VOICE_FEEDBACK_ACTIVITY = "com.thorium.preview.VoiceFeedbackActivity"
ALLOWED_ACTIVITIES = {
    MAIN_ACTIVITY,
    "com.thorium.preview.FrontendRestartActivity",
    "com.thorium.preview.PreviewActivity",
    "com.thorium.preview.BrowserActivity",
    VOICE_FEEDBACK_ACTIVITY,
    # Non-exported, no-launcher content-URI trampoline for the per-system
    # EXTERNAL route. It grants a one-time read URI and finishes immediately;
    # its manifest properties are asserted below so it can never become a
    # second launcher, a display-0 window, or a recents entry.
    "com.thorium.preview.RomLaunchActivity",
    # Conditional, shell-launched in-process surface for the bounded LSFG
    # feasibility test. Its exact transient/debug-only boundary is checked
    # below and cross-bound to the qualification native library in verify().
    LSFG_SELF_TEST_ACTIVITY,
}

# Standalone-emulator FRONTEND code must never be compiled into EmuFusion: EmuFusion
# implements its own libretro host and never embeds another emulator's classes.
# NOTE: since the per-system EXTERNAL route is now an allowed product feature,
# a bare package STRING (e.g. "com.retroarch" as an `am start` target inside
# EmulatorCatalog) is legitimate DATA. What stays forbidden is a compiled CLASS
# from those packages, so the check below matches only the class-descriptor
# form ("Lcom/retroarch/..."), never the dotted string constant.
FORBIDDEN_DEX_CLASS_PACKAGES = (
    "com/retroarch",
    "org/retroarch",
    "org/ppsspp/ppsspp",
    "org/dolphinemu",
    "org/azahar_emu",
    "org/citra/emu",
    "com/flycast/emulator",
    "com/reicast/emulator",
    "org/yuzu/yuzu_emu",
    "org/vita3k/emulator",
)

# The single, exhaustive exception to the rule above.
#
# The Phase 3 Eden adapter is opened with dlopen, so EmuFusion performs the
# JNI_OnLoad call Android would otherwise make. Eden's JNI_OnLoad caches these
# classes by exact name and leaves a pending ClassNotFoundException if any is
# absent, which aborts the process before a game can boot. The names are fixed
# by FindClass and cannot be relocated into a Lucent package.
#
# What ships under them is EmuFusion's own code -- see unified-android/stubs -- not
# Eden's frontend: plain data holders, three real filesystem helpers, and
# callbacks that log and return. The rule the guard actually enforces is
# unchanged, because the check below still fails on ANY other class in these
# packages, so genuinely vendored frontend code cannot slip in behind this.
ALLOWED_EMULATOR_SHIM_CLASSES = frozenset({
    "Lorg/yuzu/yuzu_emu/NativeLibrary;",
    "Lorg/yuzu/yuzu_emu/applets/keyboard/SoftwareKeyboard;",
    "Lorg/yuzu/yuzu_emu/applets/keyboard/SoftwareKeyboard$KeyboardConfig;",
    "Lorg/yuzu/yuzu_emu/applets/keyboard/SoftwareKeyboard$KeyboardData;",
    "Lorg/yuzu/yuzu_emu/disk_shader_cache/DiskShaderCacheProgress;",
    "Lorg/yuzu/yuzu_emu/disk_shader_cache/DiskShaderCacheProgress$LoadCallbackStage;",
    "Lorg/yuzu/yuzu_emu/features/input/YuzuInputDevice;",
    "Lorg/yuzu/yuzu_emu/features/input/model/PlayerInput;",
    "Lorg/yuzu/yuzu_emu/model/Game;",
    "Lorg/yuzu/yuzu_emu/model/GameDir;",
    "Lorg/yuzu/yuzu_emu/model/Patch;",
    "Lorg/yuzu/yuzu_emu/overlay/model/OverlayControlData;",
})

# Superseded pre-bridge Activity trampolines. RomLaunchActivity is intentionally
# NOT here anymore: it is EmuFusion's own external-route trampoline (see above).
FORBIDDEN_DEX_CLASSES = (
    "InternalGameLaunchActivity",
    "LucentGameActivity",
    "QualificationLaunchActivity",
    "SessionReturnRouter",
    "com/thorium/launchbridge/LaunchActivity",
    "com/thorium/launchbridge/StopButtonService",
)

# The user-facing product name. Internal identifiers (the Application class,
# native library prefixes, the JNI Activity, metadata suffixes and storage
# migration keys) still read Lucent on purpose: renaming those is a separate,
# far larger change that touches the native ABI symbol compiled into both
# adapters, and it must not be conflated with the visible branding.
APP_LABEL = "EmuFusion"

# Product-facing failure messages must not name Pegasus.  Internal
# compatibility names (the upstream JNI Activity, metadata suffixes, and
# storage migration keys) deliberately remain allowed.
FORBIDDEN_VISIBLE_DEX_TEXT = (
    "Unable to commit Pegasus settings",
    "Unable to replace Pegasus settings",
)

FRONTEND_LAUNCH_PATCH_OFFSET = 0x75FD8
FRONTEND_LAUNCH_PATCH = bytes.fromhex(
    "600640f9" "3b3f0094" "601240f9" "79170094"
    "fd7b41a9" "f30742f8" "c0035fd6"
)


def _blocks(xmltree: str, element: str) -> list[str]:
    lines = xmltree.splitlines()
    result: list[str] = []
    marker = f"E: {element} "
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not (stripped == f"E: {element}" or stripped.startswith(marker)):
            continue
        indent = len(line) - len(stripped)
        block = [line]
        for following in lines[index + 1:]:
            following_stripped = following.lstrip()
            following_indent = len(following) - len(following_stripped)
            if following_stripped.startswith("E: ") and following_indent <= indent:
                break
            block.append(following)
        result.append("\n".join(block))
    return result


def _raw_attribute(block: str, name: str) -> str | None:
    match = re.search(
        rf'^\s*A: (?:android:)?{re.escape(name)}(?:\([^\n]*?\))?="([^"]*)"',
        block,
        re.MULTILINE,
    )
    return None if match is None else match.group(1)


def verify_manifest(xmltree: str, expected_label: str = APP_LABEL) -> list[str]:
    errors: list[str] = []
    for authority in (
            "android.permission.QUERY_ALL_PACKAGES",
            "android.permission.KILL_BACKGROUND_PROCESSES"):
        if authority in xmltree:
            errors.append(
                f"one-app Lucent must not request legacy authority {authority}"
            )
    if "android.permission.RECORD_AUDIO" not in xmltree:
        errors.append("voice feedback requires explicit RECORD_AUDIO permission")
    manifests = _blocks(xmltree, "manifest")
    applications = _blocks(xmltree, "application")
    activities = _blocks(xmltree, "activity")
    receivers = _blocks(xmltree, "receiver")
    services = _blocks(xmltree, "service")
    if len(manifests) != 1:
        return [f"expected one manifest, found {len(manifests)}"]
    if _raw_attribute(manifests[0], "package") != PACKAGE:
        errors.append("APK package is not Lucent's com.thorium.preview identity")
    if len(applications) != 1:
        errors.append(f"expected one application, found {len(applications)}")
    else:
        if _raw_attribute(applications[0], "name") != \
                "com.thorium.preview.LucentApplication":
            errors.append("application class is not LucentApplication")
        # The product is branded EmuFusion. The Application CLASS above stays
        # LucentApplication deliberately: it is an internal identifier, and
        # renaming it is part of the wider package rename rather than of the
        # user-facing branding, so the two are asserted separately.
        if _raw_attribute(applications[0], "label") != expected_label:
            errors.append(f"application label is not {expected_label}")

    by_name: dict[str, str] = {}
    for block in activities:
        name = _raw_attribute(block, "name")
        if not name:
            errors.append("manifest contains an unnamed Activity")
            continue
        if name in by_name:
            errors.append(f"manifest repeats Activity {name}")
        by_name[name] = block
    # Every declared Activity must be one EmuFusion owns; the external-route
    # trampoline is permitted but not required, so this is a subset check.
    unexpected = set(by_name) - ALLOWED_ACTIVITIES
    if unexpected:
        errors.append(
            "manifest declares Activities outside the Lucent boundary: "
            + repr(sorted(unexpected))
        )
    if MAIN_ACTIVITY not in by_name:
        errors.append("manifest is missing the Lucent MainActivity")

    main = by_name.get(MAIN_ACTIVITY, "")
    if 'android:launchMode' not in main or \
            not re.search(r'android:launchMode[^\n]*\(type 0x10\)0x2', main):
        errors.append("Lucent MainActivity is not singleTask")
    if '"android.intent.action.MAIN"' not in main or \
            '"android.intent.category.LAUNCHER"' not in main:
        errors.append("Lucent MainActivity is not the sole launcher")
    launcher_count = sum(
        '"android.intent.category.LAUNCHER"' in block for block in by_name.values())
    if launcher_count != 1:
        errors.append(f"expected one launcher Activity, found {launcher_count}")

    preview = by_name.get("com.thorium.preview.PreviewActivity", "")
    if not re.search(r'android:exported[^\n]*\(type 0x12\)0x0', preview):
        errors.append("Thor PreviewActivity must be non-exported")
    if not re.search(r'android:excludeFromRecents[^\n]*0xffffffff', preview):
        errors.append("Thor PreviewActivity must be excluded from recents")
    if _raw_attribute(preview, "taskAffinity") != "com.thorium.preview.preview":
        errors.append("Thor PreviewActivity must use its private display task affinity")

    browser = by_name.get("com.thorium.preview.BrowserActivity", "")
    if not re.search(r'android:exported[^\n]*\(type 0x12\)0x0', browser):
        errors.append("Lucent BrowserActivity must be non-exported")

    voice = by_name.get(VOICE_FEEDBACK_ACTIVITY, "")
    if not voice:
        errors.append("manifest is missing the voice-feedback permission Activity")
    else:
        if not re.search(r'android:exported[^\n]*\(type 0x12\)0x0', voice):
            errors.append("voice-feedback Activity must be non-exported")
        if not re.search(r'android:excludeFromRecents[^\n]*0xffffffff', voice):
            errors.append("voice-feedback Activity must be excluded from recents")
        if not re.search(r'android:noHistory[^\n]*0xffffffff', voice):
            errors.append("voice-feedback Activity must be no-history")
        if 'E: intent-filter' in voice:
            errors.append("voice-feedback Activity must have no intent filter")

    restart = by_name.get("com.thorium.preview.FrontendRestartActivity", "")
    if not restart:
        errors.append("manifest is missing the clean-process frontend restart bridge")
    else:
        if not re.search(r'android:exported[^\n]*\(type 0x12\)0x0', restart):
            errors.append("frontend restart bridge must be non-exported")
        if not re.search(r'android:excludeFromRecents[^\n]*0xffffffff', restart):
            errors.append("frontend restart bridge must be excluded from recents")
        if not re.search(r'android:noHistory[^\n]*0xffffffff', restart):
            errors.append("frontend restart bridge must be no-history")
        if _raw_attribute(restart, "process") != ":frontend_restart":
            errors.append("frontend restart bridge must use its dedicated app process")

    # The external-route trampoline must be a transient, non-exported, no-recents
    # Activity with no launcher/home category, so it cannot become a second
    # display-0 window or a second recents entry.
    trampoline = by_name.get("com.thorium.preview.RomLaunchActivity", "")
    if trampoline:
        if not re.search(r'android:exported[^\n]*\(type 0x12\)0x0', trampoline):
            errors.append("RomLaunchActivity trampoline must be non-exported")
        if not re.search(r'android:excludeFromRecents[^\n]*0xffffffff', trampoline):
            errors.append("RomLaunchActivity trampoline must be excluded from recents")
        if '"android.intent.category.LAUNCHER"' in trampoline or \
                '"android.intent.category.HOME"' in trampoline or \
                '"android.intent.category.LEANBACK_LAUNCHER"' in trampoline:
            errors.append("RomLaunchActivity trampoline must not carry a launcher category")

    lsfg_self_test = by_name.get(LSFG_SELF_TEST_ACTIVITY, "")
    if lsfg_self_test:
        if not re.search(
                r'android:exported[^\n]*\(type 0x12\)0xffffffff',
                lsfg_self_test):
            errors.append("LSFG self-test Activity must be shell-launchable")
        if not re.search(
                r'android:excludeFromRecents[^\n]*0xffffffff',
                lsfg_self_test):
            errors.append("LSFG self-test Activity must be excluded from recents")
        if not re.search(
                r'android:noHistory[^\n]*0xffffffff', lsfg_self_test):
            errors.append("LSFG self-test Activity must be no-history")
        if _raw_attribute(lsfg_self_test, "taskAffinity") != \
                "com.thorium.preview.lsfg.selftest":
            errors.append("LSFG self-test Activity has the wrong task affinity")
        if 'E: intent-filter' in lsfg_self_test:
            errors.append("LSFG self-test Activity must have no intent filter")
        application = applications[0] if len(applications) == 1 else ""
        if not re.search(
                r'android:debuggable[^\n]*\(type 0x12\)0xffffffff',
                application):
            errors.append("LSFG self-test APK must be explicitly debuggable")
    # Internal game launches are intercepted inside MainActivity.launchAmCommand;
    # no exported receiver or second Activity is part of the product boundary.
    if any(_raw_attribute(block, "name") ==
           "com.thorium.preview.GameLaunchReceiver" for block in receivers):
        errors.append("manifest retains obsolete exported GameLaunchReceiver")

    stop_services = [block for block in services
                     if _raw_attribute(block, "name") == EXTERNAL_STOP_SERVICE]
    if len(stop_services) != 1:
        errors.append(
            "APK must declare exactly one same-package external Stop accessibility service"
        )
    else:
        stop = stop_services[0]
        if not re.search(r'android:exported[^\n]*\(type 0x12\)0xffffffff', stop):
            errors.append("external Stop accessibility service must be exported")
        if _raw_attribute(stop, "permission") != \
                "android.permission.BIND_ACCESSIBILITY_SERVICE":
            errors.append("external Stop service lacks BIND_ACCESSIBILITY_SERVICE")
        if '"android.accessibilityservice.AccessibilityService"' not in stop:
            errors.append("external Stop service lacks its accessibility intent filter")
        if '"android.accessibilityservice"' not in stop or \
                not re.search(r'android:resource[^\n]*0x[0-9a-f]+', stop):
            errors.append("external Stop service lacks accessibility configuration metadata")
    return errors


def verify_dex(apk: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(apk) as archive:
        dex_names = sorted(
            name for name in archive.namelist()
            if re.fullmatch(r"classes(?:\d+)?\.dex", name)
        )
        if not dex_names:
            return ["APK contains no DEX payload"]
        dex = b"\n".join(archive.read(name) for name in dex_names)
    for package in FORBIDDEN_DEX_CLASS_PACKAGES:
        # Class descriptors appear as "L<slashed package>/...;". A dotted
        # package string used only as an am-start target never produces this.
        # Enumerate the descriptors rather than substring-matching the package,
        # so the allowlist can admit named classes without blinding the check to
        # every other class beside them.
        found = {
            match.decode("ascii")
            for match in re.findall(
                rb"L" + re.escape(package.encode()) + rb"/[A-Za-z0-9_$/]*;", dex)
        }
        for descriptor in sorted(found - ALLOWED_EMULATOR_SHIM_CLASSES):
            errors.append(
                f"DEX embeds standalone emulator classes {package}: {descriptor}")
    for class_name in FORBIDDEN_DEX_CLASSES:
        if class_name.encode() in dex:
            errors.append(f"DEX contains legacy game-launch component {class_name}")
    for phrase in FORBIDDEN_VISIBLE_DEX_TEXT:
        if phrase.encode() in dex:
            errors.append(f"DEX retains visible upstream phrase {phrase!r}")
    return errors


def _branding_replacements() -> dict[str, str]:
    module_path = Path(__file__).with_name("patch_emufusion_branding.py")
    spec = importlib.util.spec_from_file_location("lucent_branding_patch", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load branding policy: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.VISIBLE_REPLACEMENTS)


def verify_branding(apk: Path) -> list[str]:
    errors: list[str] = []
    frontend = "lib/arm64-v8a/libpegasus-fe_arm64-v8a.so"
    with zipfile.ZipFile(apk) as archive:
        if frontend not in archive.namelist():
            return [f"APK is missing pinned frontend library {frontend}"]
        data = archive.read(frontend)
    for before, after in _branding_replacements().items():
        for encoding in ("utf-8", "utf-16le", "utf-16be"):
            if before.encode(encoding) in data:
                errors.append(f"frontend retains visible upstream phrase {before!r}")
            # The pinned binary contains multiple language/resource copies, but
            # not necessarily every encoding for every string.  Requiring the
            # replacement in at least one encoding below proves the patch ran.
        if not any(after.encode(encoding) in data
                   for encoding in ("utf-8", "utf-16le", "utf-16be")):
            errors.append(f"frontend lacks Lucent replacement {after!r}")
    for malformed in (
            "Lucent  ", "Lucent have permission", "Lucent yet?",
            "games. on your device", "Lucent, can use"):
        if malformed.encode() in data:
            errors.append(f"frontend contains malformed Lucent text {malformed!r}")
    return errors


def verify_frontend_launch_lifecycle(apk: Path) -> list[str]:
    frontend = "lib/arm64-v8a/libpegasus-fe_arm64-v8a.so"
    with zipfile.ZipFile(apk) as archive:
        if frontend not in archive.namelist():
            return [f"APK is missing pinned frontend library {frontend}"]
        data = archive.read(frontend)
    found = data[
        FRONTEND_LAUNCH_PATCH_OFFSET:
        FRONTEND_LAUNCH_PATCH_OFFSET + len(FRONTEND_LAUNCH_PATCH)
    ]
    if found != FRONTEND_LAUNCH_PATCH:
        return [
            "frontend does not preserve QML across an in-process game launch"
        ]
    return []


def verify_qt_gamepad_null_guard(apk: Path) -> list[str]:
    module_path = Path(__file__).with_name(
        "patch_qt_android_gamepad_null_guard.py"
    )
    spec = importlib.util.spec_from_file_location("qt_gamepad_guard", module_path)
    if spec is None or spec.loader is None:
        return [f"cannot load Qt gamepad guard policy: {module_path}"]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    library = (
        "lib/arm64-v8a/"
        "libplugins_gamepads_androidgamepad_arm64-v8a.so"
    )
    with zipfile.ZipFile(apk) as archive:
        if library not in archive.namelist():
            return [f"APK is missing Qt Android gamepad plugin {library}"]
        data = archive.read(library)
    errors: list[str] = []
    for offset, _expected, replacement in module.PATCHES:
        found = data[offset:offset + len(replacement)]
        if found != replacement:
            errors.append(
                f"Qt Android gamepad null guard missing at 0x{offset:x}"
            )
    return errors


def verify_external_stop_payload(apk: Path) -> list[str]:
    """Require the exact-APK code/config backing the manifest declaration."""
    errors: list[str] = []
    with zipfile.ZipFile(apk) as archive:
        names = set(archive.namelist())
        if "res/xml/external_stop_accessibility.xml" not in names:
            errors.append("APK lacks external Stop accessibility configuration")
        dex_names = sorted(name for name in names
                           if re.fullmatch(r"classes(?:\d+)?\.dex", name))
        dex = b"\n".join(archive.read(name) for name in dex_names)
    for descriptor in (
            b"Lcom/thorium/preview/ExternalStopAccessibilityService;",
            b"Lcom/thorium/preview/ExternalEmulationSession;"):
        if descriptor not in dex:
            errors.append(
                "APK lacks external Stop implementation " +
                descriptor.decode("ascii")
            )
    return errors


def verify_frontend_restart_payload(apk: Path) -> list[str]:
    """Bind the manifest bridge to the implementation that performs the restart."""
    with zipfile.ZipFile(apk) as archive:
        dex_names = sorted(name for name in archive.namelist()
                           if re.fullmatch(r"classes(?:\d+)?\.dex", name))
        dex = b"\n".join(archive.read(name) for name in dex_names)
    descriptor = b"Lcom/thorium/preview/FrontendRestartActivity;"
    return [] if descriptor in dex else [
        "APK lacks the clean-process frontend restart implementation"
    ]


def verify_voice_feedback_payload(apk: Path) -> list[str]:
    """Bind the microphone Activity to review/report code in the same APK."""
    with zipfile.ZipFile(apk) as archive:
        dex_names = sorted(name for name in archive.namelist()
                           if re.fullmatch(r"classes(?:\d+)?\.dex", name))
        dex = b"\n".join(archive.read(name) for name in dex_names)
    required = (
        b"Lcom/thorium/preview/VoiceFeedbackActivity;",
        b"Lcom/thorium/preview/VoiceFeedbackManager;",
        b"Landroid/speech/SpeechRecognizer;",
        b"wildonrio/emufusion",
    )
    missing = [value.decode("ascii") for value in required if value not in dex]
    return [] if not missing else [
        "APK lacks complete voice-feedback implementation: " + repr(missing)
    ]


def verify_lsfg_self_test_boundary(apk: Path, xmltree: str) -> list[str]:
    """Bind the conditional shell surface, DEX and native host atomically."""
    errors: list[str] = []
    manifest_has = LSFG_SELF_TEST_ACTIVITY in xmltree
    with zipfile.ZipFile(apk) as archive:
        names = set(archive.namelist())
        native_has = LSFG_QUALIFICATION_LIBRARY in names
        dex_names = sorted(name for name in names
                           if re.fullmatch(r"classes(?:\d+)?\.dex", name))
        dex = b"\n".join(archive.read(name) for name in dex_names)
    descriptor = (
        "L" + LSFG_SELF_TEST_ACTIVITY.replace(".", "/") + ";"
    ).encode("ascii")
    dex_has = descriptor in dex
    if manifest_has != native_has or manifest_has != dex_has:
        errors.append(
            "LSFG self-test Activity, implementation and native host must "
            "appear together only in the qualification APK"
        )
    return errors


def verify(apk: Path, aapt: Path,
           internal_lsfg_plus: bool = False,
           source_frontend_lock: Path | None = None) -> list[str]:
    if not apk.is_file():
        return [f"missing APK: {apk}"]
    if not aapt.is_file():
        return [f"missing aapt: {aapt}"]
    result = subprocess.run(
        [str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        return [f"aapt could not inspect AndroidManifest.xml: {result.stderr.strip()}"]
    expected_label = "EmuFusion+" if internal_lsfg_plus else APP_LABEL
    if source_frontend_lock is not None:
        # Explicit isolated qualification only: pin the entire native cohort,
        # rather than accepting an APK-provided assertion or skipping guards.
        from verify_source_frontend import verify as verify_source
        native_frontend_errors = verify_source(apk, source_frontend_lock)
    else:
        native_frontend_errors = (verify_frontend_launch_lifecycle(apk) +
                                  verify_qt_gamepad_null_guard(apk))
    errors = (verify_manifest(result.stdout, expected_label) + verify_dex(apk) +
            verify_branding(apk) + native_frontend_errors +
            verify_external_stop_payload(apk) +
            verify_frontend_restart_payload(apk) +
            verify_voice_feedback_payload(apk) +
            verify_lsfg_self_test_boundary(apk, result.stdout))
    if internal_lsfg_plus:
        if "emufusion-plus-lsfg-internal" not in apk.name:
            errors.append("EmuFusion+ must use the internal LSFG artifact name")
        with zipfile.ZipFile(apk) as archive:
            native_has = LSFG_QUALIFICATION_LIBRARY in archive.namelist()
        if LSFG_SELF_TEST_ACTIVITY not in result.stdout or not native_has:
            errors.append("EmuFusion+ requires the complete internal LSFG payload")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("--aapt", required=True, type=Path)
    parser.add_argument("--internal-lsfg-plus", action="store_true")
    parser.add_argument("--source-frontend-lock", type=Path,
                        help="Explicit reviewed source-cohort lock for isolated qualification; not runtime/release acceptance")
    args = parser.parse_args()
    errors = verify(args.apk, args.aapt, args.internal_lsfg_plus, args.source_frontend_lock)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Lucent one-app APK boundary: PASS")


if __name__ == "__main__":
    main()
