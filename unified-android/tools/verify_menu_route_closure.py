#!/usr/bin/env python3
"""Fail closed when a EmuFusion menu route has no exact packaged engine factory.

This verifier is deliberately independent of Android launch success.  A route
can reach EmuFusion's in-window host and still fail one frame later because the
APK does not contain the named core or because no bootstrap factory registered
it.  The verifier joins the *installed metadata routes* to the signed APK's
catalog, opt-in, artifact-manifest, native-library, and DEX bootstrap evidence
before any game is launched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "com.thorium.preview"
MAIN_ACTIVITY = "com.thorium.preview/org.pegasus_frontend.android.MainActivity"
METADATA_ROOTS = (
    "/storage/emulated/0/pegasus-frontend",
    "/storage/emulated/0/Android/data/org.pegasus_frontend.android/files/pegasus-frontend",
    "/storage/emulated/0/Android/data/com.thorium.preview/files/pegasus-frontend",
)
PHASE3_SYSTEMS = frozenset({"ps3", "wiiu", "switch"})
SYSTEM_SHORTNAME_ALIASES = {
    "dc": "dreamcast",
    "ds": "nds",
    "famicom": "nes",
    "fba": "arcade",
    "fbneo": "arcade",
    "fc": "nes",
    "finalburnneo": "arcade",
    "gc": "gamecube",
    "genesis": "megadrive",
    "mame": "arcade",
    "markiii": "mastersystem",
    "n3ds": "3ds",
    "ngc": "gamecube",
    "nintendo3ds": "3ds",
    "nintendods": "nds",
    "nintendogamecube": "gamecube",
    "playstation": "psx",
    "ps1": "psx",
    "segadreamcast": "dreamcast",
    "segagenesis": "megadrive",
    "segamastersystem": "mastersystem",
    "segamegadrive": "megadrive",
    "sms": "mastersystem",
    "sonyplaystation": "psx",
    "superfamicom": "snes",
    "supernintendo": "snes",
    "tg16": "pcengine",
    "turbografx16": "pcengine",
    "win": "windows",
    "windows10": "windows",
    "pc": "windows",
}
SYSTEM_SHORTNAME_ALIASES_SHA256 = \
    "3b0d421b6399c4b33b513335e11c3587b0d960aa577c538f996fc50ef122eb87"
REQUIRED_ALIAS_ROUTES = {
    "gc": ("gamecube", "dolphin"),
    "genesis": ("megadrive", "blastem"),
    "n3ds": ("3ds", "azahar"),
}


@dataclass(frozen=True, order=True)
class Route:
    system: str
    engine: str


def normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def routes_from_text(value: str) -> set[Route]:
    routes: set[Route] = set()
    for line in value.splitlines():
        if "engine_id" not in line:
            continue
        engine = re.search(r"--es\s+(?:lucent\.)?engine_id\s+[\"']?([^\s\"']+)", line)
        system = re.search(r"--es\s+(?:lucent\.)?(?:system|system_id)\s+[\"']?([^\s\"']+)", line)
        if engine is not None and system is not None:
            routes.add(Route(normalized(system.group(1)), normalized(engine.group(1))))
    return routes


def collection_shortnames(value: str) -> set[str]:
    """Extract only top-level collection shortnames from redacted device data."""
    return {normalized(match.group(1)) for match in re.finditer(
        r"^shortname:\s*([^\s]+)\s*$", value, re.M,
    ) if normalized(match.group(1))}


def alias_map_sha256() -> str:
    encoded = json.dumps(SYSTEM_SHORTNAME_ALIASES, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def canonical_system_id(value: str) -> str:
    system = normalized(value)
    return SYSTEM_SHORTNAME_ALIASES.get(system, system)


def launcher_audit(value: str) -> list[dict[str, object]]:
    """Classify metadata launchers without exposing paths or game names."""
    rows: list[dict[str, object]] = []
    for line in value.splitlines():
        command = line.strip()
        if not command:
            continue
        if command.startswith("collection:") or command.startswith("shortname:"):
            continue
        if command.startswith("launch:"):
            command = command[len("launch:"):].strip()
        if not command:
            continue
        reasons = []
        am_start = bool(re.search(r"\bam\s+start\b", command))
        am_broadcast = bool(re.search(r"\bam\s+broadcast\b", command))
        internal_action = "-a com.thorium.preview.LAUNCH_INTERNAL_GAME" in command
        cross_user = bool(re.search(r"(?:^|\s)--user(?:\s|=)", command))
        # A per-system EXTERNAL route is now a legitimate product feature. It is
        # a plain `am start` that either opens the emulator's install page
        # (-a VIEW -d https://... or market://...), launches the emulator via its
        # own deep-link scheme (e.g. -d dolphinemu://...), or hands a content URI
        # through EmuFusion's own RomLaunchActivity trampoline. Any VIEW intent with
        # a scheme'd data URI is a legitimate external open/launch/install route;
        # it deliberately does NOT target MainActivity or the internal action.
        external_view_install = bool(
            re.search(r"-a\s+android\.intent\.action\.VIEW", command) and
            re.search(r"-d\s+[A-Za-z][A-Za-z0-9+.-]*://", command))
        # An external component target must NOT be EmuFusion's own MainActivity: a
        # bare am-start onto the singleTask MainActivity without the internal
        # action is the historical stale route, not an external launch. The
        # RomLaunchActivity trampoline (a different EmuFusion component) still
        # counts as external.
        external_component = (bool(re.search(r"-n\s+\S+/\S+", command)) and
                              not internal_action and MAIN_ACTIVITY not in command)
        kind = "intercepted-same-activity-start"
        if internal_action:
            # Internal in-window route: keep the full strict contract.
            if MAIN_ACTIVITY not in command:
                reasons.append("does not target Lucent MainActivity")
            if not am_start:
                reasons.append("does not use Pegasus-compatible am-start syntax")
            if cross_user:
                reasons.append("uses a forbidden cross-user flag")
            if re.search(r"--es\s+(?:lucent\.)?engine_id\s+", command) is None:
                reasons.append("has no in-window engine_id")
            if re.search(r"--es\s+(?:lucent\.)?(?:system|system_id)\s+", command) is None:
                reasons.append("has no in-window system id")
        elif am_start and (external_view_install or external_component) and not am_broadcast:
            # External route: still forbid the cross-user flag, but the internal
            # in-window contract does not apply.
            kind = "external-route"
            if cross_user:
                reasons.append("uses a forbidden cross-user flag")
        elif MAIN_ACTIVITY in command:
            # Targets the singleTask MainActivity but not via the internal
            # action — the historical stale same-activity route.
            reasons.append("does not use Lucent's internal launch action")
        else:
            reasons.append("is neither the internal in-window route nor a "
                           "recognized external route")
        if reasons:
            kind = ("stale-am-start" if am_start else (
                "stale-am-broadcast" if am_broadcast else "external-or-invalid"))
        rows.append({
            "commandSha256": sha256_bytes(command.encode("utf-8")),
            "kind": kind,
            "pass": not reasons,
            "reason": "; ".join(reasons),
        })
    return rows


def invalid_launch_lines(value: str) -> list[dict[str, object]]:
    """Return path-redacted failures for every non-intercepted launcher."""
    return [row for row in launcher_audit(value) if row["pass"] is not True]


def device_route_command() -> str:
    roots = " ".join(shlex.quote(root) for root in METADATA_ROOTS)
    # Android's adb shell concatenates argv before invoking the remote shell.
    # Iterate existing roots explicitly so one optional/missing metadata root
    # cannot turn an otherwise valid read-only scan into find(1) exit status 1.
    return (
        "for root in " + roots + "; do "
        "[ -d \"$root\" ] || continue; "
        "find \"$root\" -type f \\( -name '*.pegasus.txt' "
        "-o -name 'metadata.pegasus.txt' \\) "
        "! -path '*/backup/*' ! -path '*/backups/*' "
        "! -path '*/.backup/*' ! -path '*.bak*' ! -path '*.backup*' "
        "-exec awk 'BEGIN { header=0 } "
        "/^collection:/{header=1; print; next} "
        "/^game:/{header=0; next} "
        "header && (/^shortname:/ || /^launch:/){print}' {} +; "
        "done"
    )


def device_route_text(adb: Path, serial: str) -> str:
    command = device_route_command()
    # Pass the complete `sh -c` program as one adb remote-command argument.
    # Supplying `sh`, `-c`, and the program as separate adb argv entries is not
    # equivalent: adb's client-side joining lets the remote shell consume only
    # the first word as sh's command string.
    remote = "sh -c " + shlex.quote(command)
    completed = subprocess.run(
        [str(adb), "-s", serial, "shell", remote],
        check=True, capture_output=True, text=True,
    )
    return completed.stdout


def json_assets(archive: zipfile.ZipFile, suffix: str) -> list[tuple[str, dict]]:
    result = []
    for name in sorted(archive.namelist()):
        if not name.startswith("assets/") or not name.endswith(suffix) or name.endswith(".schema.json"):
            continue
        try:
            result.append((name, json.loads(archive.read(name).decode("utf-8"))))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            result.append((name, {"__invalid__": True}))
    return result


def dex_bootstrap_evidence(apk: Path, dexdump: Path) -> tuple[bool, str]:
    required = (
        "com.thorium.preview.game.InternalEngineBootstrap.register",
        "com.thorium.preview.game.EngineSessionRegistry.register",
        "com.thorium.preview.game.LibretroEngineSession",
        "com.thorium.preview.game.PpssppGlesEngineSession",
    )
    with zipfile.ZipFile(apk) as archive, tempfile.TemporaryDirectory(
            prefix="lucent-route-closure-") as directory:
        combined = []
        for name in archive.namelist():
            if not re.fullmatch(r"classes\d*\.dex", name):
                continue
            destination = Path(directory) / Path(name).name
            destination.write_bytes(archive.read(name))
            completed = subprocess.run(
                [str(dexdump), "-d", str(destination)],
                check=False, capture_output=True,
            )
            combined.append(completed.stdout.decode("utf-8", errors="replace"))
    disassembly = "\n".join(combined)
    missing = [value for value in required if value not in disassembly]
    if missing:
        return False, "missing DEX bootstrap evidence: " + ", ".join(missing)
    bootstrap = re.search(
        r"com\.thorium\.preview\.game\.InternalEngineBootstrap\.register:.*?"
        r"(?=Class descriptor|\Z)", disassembly, re.S,
    )
    if bootstrap is None or "EngineSessionRegistry;.register" not in bootstrap.group(0):
        return False, "InternalEngineBootstrap.register does not register a factory"
    return True, "InternalEngineBootstrap -> EngineSessionRegistry factory call present"


def dex_alias_contract_evidence(apk: Path, dexdump: Path) -> tuple[bool, str]:
    """Prove the exact APK canonicalizes metadata before catalog lookup/output."""
    if alias_map_sha256() != SYSTEM_SHORTNAME_ALIASES_SHA256:
        return False, "QA shortname alias contract checksum differs from locked value"
    with zipfile.ZipFile(apk) as archive, tempfile.TemporaryDirectory(
            prefix="lucent-alias-contract-") as directory:
        combined = []
        for name in archive.namelist():
            if not re.fullmatch(r"classes\d*\.dex", name):
                continue
            destination = Path(directory) / Path(name).name
            destination.write_bytes(archive.read(name))
            completed = subprocess.run(
                [str(dexdump), "-d", str(destination)],
                check=False, capture_output=True,
            )
            combined.append(completed.stdout.decode("utf-8", errors="replace"))
    disassembly = "\n".join(combined)
    match = re.search(
        r"Class descriptor\s+: 'Lcom/thorium/preview/GameLaunchRouter;'.*?"
        r"(?=\nClass #|\Z)", disassembly, re.S,
    )
    if match is None:
        return False, "GameLaunchRouter class is absent from candidate DEX"
    router = match.group(0)
    resolver_match = re.search(
        r"Class descriptor\s+: 'Lcom/thorium/lucent/metadata/"
        r"EngineSystemIdResolver;'.*?(?=\nClass #|\Z)",
        disassembly, re.S,
    )
    if resolver_match is None:
        return False, "EngineSystemIdResolver class is absent from candidate DEX"
    resolver = resolver_match.group(0)
    command_match = re.search(
        r"Class descriptor\s+: 'Lcom/thorium/lucent/metadata/"
        r"MetadataGameLaunchCommand;'.*?(?=\nClass #|\Z)",
        disassembly, re.S,
    )
    if command_match is None:
        return False, "MetadataGameLaunchCommand class is absent from candidate DEX"
    command = command_match.group(0)
    if "am start -a " not in command or \
            "org.pegasus_frontend.android.MainActivity" not in command:
        return False, "metadata command is not compatible with Pegasus Android launching"
    bridge_match = re.search(
        r"Class descriptor\s+: 'Lcom/thorium/preview/"
        r"InProcessGameLaunchCommand;'.*?(?=\nClass #|\Z)",
        disassembly, re.S,
    )
    if bridge_match is None or \
            "InWindowGameHost;.handleIntent:" not in bridge_match.group(0):
        return False, "lifecycle-neutral in-process launch bridge is absent"
    main_match = re.search(
        r"Class descriptor\s+: 'Lorg/pegasus_frontend/android/MainActivity;'.*?"
        r"(?=\nClass #|\Z)", disassembly, re.S,
    )
    if main_match is None:
        return False, "inherited MainActivity class is absent"
    launch_method = re.search(
        r"MainActivity\.launchAmCommand:.*?(?=\n\s+#\d+\s+:|\n  Virtual methods|\Z)",
        main_match.group(0), re.S,
    )
    if launch_method is None or \
            "InProcessGameLaunchCommand;.tryLaunch:" not in launch_method.group(0):
        return False, "MainActivity.launchAmCommand lacks the in-process interception hook"
    missing_literals = []
    for alias, canonical in sorted(SYSTEM_SHORTNAME_ALIASES.items()):
        for literal in (alias, canonical):
            if re.search(r'const-string[^\n]*, "' + re.escape(literal) + r'"',
                         resolver) is None:
                missing_literals.append(literal)
    if missing_literals:
        return False, "EngineSystemIdResolver lacks locked alias literals: " + ", ".join(
            missing_literals
        )
    metadata = re.search(
        r"GameLaunchRouter\.metadataCommand:.*?"
        r"(?=\n\s+#\d+\s+: \(in Lcom/thorium/preview/GameLaunchRouter;\)|"
        r"\n  Virtual methods|\Z)", router, re.S,
    )
    if metadata is None or re.search(
            r"EngineSystemIdResolver;\.canonical:", metadata.group(0)) is None:
        return False, "metadataCommand does not invoke EngineSystemIdResolver"
    return True, (
        "locked alias contract present: gc->gamecube, genesis->megadrive, "
        "n3ds->3ds"
    )


def llvm_nm_tool() -> Path | None:
    root = Path.home() / "Library/Android/sdk/ndk"
    candidates = sorted(root.glob(
        "*/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-nm"
    ))
    return candidates[-1] if candidates else None


def nm_symbols(output: bytes) -> set[str]:
    """Extract the final symbol column from llvm-nm's stable text output."""
    symbols = set()
    for raw in output.decode("utf-8", errors="replace").splitlines():
        fields = raw.split()
        if fields:
            symbols.add(fields[-1])
    return symbols


def libcxx_abi_evidence(archive: zipfile.ZipFile,
                        core_path: str) -> tuple[bool, str]:
    """Prove a packaged C++ core's libc++ imports resolve in this same APK.

    File/hash closure alone cannot catch a core built against a different NDK
    libc++ ABI. Android then accepts the menu route but dlopen fails only after
    the user presses A. Every undefined `std::__ndk1` symbol is owned by the
    packaged libc++ runtime, so require that exact runtime to export it.
    """
    core = archive.read(core_path)
    if not core.startswith(b"\x7fELF"):
        # Unit fixtures deliberately use tiny opaque blobs. Real APK native
        # libraries are ELF and take the strict path below.
        return True, "non-ELF test fixture; native ABI inspection not applicable"
    runtime_path = "lib/arm64-v8a/libc++_shared.so"
    if runtime_path not in archive.namelist():
        return False, "packaged C++ runtime is absent"
    tool = llvm_nm_tool()
    if tool is None:
        return False, "llvm-nm is unavailable for packaged C++ ABI closure"
    with tempfile.TemporaryDirectory(prefix="lucent-libcxx-closure-") as directory:
        core_file = Path(directory) / "core.so"
        runtime_file = Path(directory) / "libc++_shared.so"
        core_file.write_bytes(core)
        runtime_file.write_bytes(archive.read(runtime_path))
        undefined_run = subprocess.run(
            [str(tool), "-D", "--undefined-only", str(core_file)],
            check=False, capture_output=True,
        )
        defined_run = subprocess.run(
            [str(tool), "-D", "--defined-only", str(runtime_file)],
            check=False, capture_output=True,
        )
    if undefined_run.returncode != 0 or defined_run.returncode != 0:
        return False, "llvm-nm could not inspect packaged C++ ABI closure"
    required = {
        symbol for symbol in nm_symbols(undefined_run.stdout)
        if "__ndk1" in symbol
    }
    provided = nm_symbols(defined_run.stdout)
    missing = sorted(required - provided)
    if missing:
        preview = ", ".join(missing[:3])
        suffix = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
        return False, (
            f"packaged C++ runtime ABI misses {len(missing)} required symbol(s): "
            + preview + suffix
        )
    return True, f"packaged C++ runtime resolves {len(required)} std::__ndk1 imports"


def verify(apk: Path, routes: set[Route], dexdump: Path) -> tuple[list[str], dict]:
    errors: list[str] = []
    report: dict[str, object] = {
        "apk": str(apk.resolve()),
        "apkSha256": sha256_file(apk),
        "routes": [],
    }
    try:
        archive = zipfile.ZipFile(apk)
    except (OSError, zipfile.BadZipFile) as error:
        return [f"cannot open APK: {error}"], report

    with archive:
        names = set(archive.namelist())
        registries: dict[str, dict] = {}
        for asset, root in json_assets(archive, "engine-registry.json"):
            if root.get("__invalid__"):
                errors.append(f"invalid registry JSON: {asset}")
            for row in root.get("engines", []):
                engine_id = normalized(row.get("id")) if isinstance(row, dict) else ""
                if engine_id:
                    copy = dict(row)
                    copy["__asset"] = asset
                    registries[engine_id] = copy

        artifacts: dict[str, dict] = {}
        for asset, root in json_assets(archive, "engine-artifacts.json"):
            if root.get("__invalid__"):
                errors.append(f"invalid artifact JSON: {asset}")
            for row in root.get("artifacts", []):
                engine_id = normalized(row.get("engineId")) if isinstance(row, dict) else ""
                if engine_id:
                    artifacts[engine_id] = row

        opt_ins: dict[str, list[dict]] = {}
        for asset, root in json_assets(archive, "qualification-opt-in.json"):
            if root.get("__invalid__"):
                errors.append(f"invalid opt-in JSON: {asset}")
                continue
            for row in root.get("engines", []):
                if not isinstance(row, dict):
                    continue
                engine_id = normalized(row.get("id"))
                if not engine_id:
                    continue
                copy = dict(row)
                copy["__asset"] = asset
                copy["__globalAutoSelect"] = bool(root.get("autoSelect", False))
                opt_ins.setdefault(engine_id, []).append(copy)

        bootstrap_ok, bootstrap_detail = dex_bootstrap_evidence(apk, dexdump)
        if not bootstrap_ok:
            errors.append(bootstrap_detail)
        report["bootstrap"] = {"pass": bootstrap_ok, "detail": bootstrap_detail}

        abi_cache: dict[str, tuple[bool, str]] = {}
        for route in sorted(routes):
            row_errors: list[str] = []
            registry = registries.get(route.engine)
            artifact = artifacts.get(route.engine)
            candidates = opt_ins.get(route.engine, [])
            systems = {normalized(value) for value in
                       ((registry or {}).get("systems") or [])}
            approved = bool(
                registry and registry.get("__asset") == "assets/engine-registry.json" and
                registry.get("status") == "approved" and
                registry.get("shipped") is True and
                (registry.get("state") or {}).get("qualified") is True and
                (registry.get("build") or {}).get("reproducible") is True and
                route.system in systems
            )
            opted = False
            selected_opt_in: dict | None = None
            for candidate in candidates:
                explicit = {normalized(value) for value in
                            candidate.get("libraryRouteSystems", [])}
                phase1_loader = (
                    candidate.get("__asset") == "assets/engine-qualification-opt-in.json" and
                    registry is not None and
                    registry.get("__asset") == "assets/engine-registry.json"
                )
                phase2_loader = (
                    candidate.get("__asset") == "assets/phase2-qualification-opt-in.json" and
                    registry is not None and
                    registry.get("__asset") == "assets/phase2-engine-registry.json"
                )
                if (phase1_loader or phase2_loader) and (
                        route.system in explicit or (
                            candidate.get("__globalAutoSelect") and route.system in systems)):
                    opted = True
                    selected_opt_in = candidate
                    break
            if registry is None:
                row_errors.append("no signed engine registry row")
            if not approved and not opted:
                row_errors.append("not eligible for a normal menu route")
            if artifact is None:
                row_errors.append("no packaged artifact identity")

            file_name = ""
            if selected_opt_in is not None:
                file_name = str(selected_opt_in.get("libraryName") or "")
            if not file_name and artifact is not None:
                file_name = str(artifact.get("fileName") or "")
            core_path = "lib/arm64-v8a/" + file_name if file_name else ""
            if not file_name or core_path not in names:
                row_errors.append("registered core library is absent from arm64-v8a payload")
            elif artifact is not None:
                actual = sha256_bytes(archive.read(core_path))
                if actual != str(artifact.get("sha256") or "").lower():
                    row_errors.append("packaged core hash differs from artifact identity")

            abi_ok, abi_detail = True, "core library unavailable for ABI inspection"
            if core_path in names:
                if core_path not in abi_cache:
                    abi_cache[core_path] = libcxx_abi_evidence(archive, core_path)
                abi_ok, abi_detail = abi_cache[core_path]
                if not abi_ok:
                    row_errors.append(abi_detail)

            if not bootstrap_ok:
                row_errors.append("bootstrap factory proof is absent")
            record = {
                "system": route.system,
                "engine": route.engine,
                "core": core_path,
                "nativeAbi": {"pass": abi_ok, "detail": abi_detail},
                "pass": not row_errors,
                "errors": row_errors,
            }
            report["routes"].append(record)
            errors.extend(f"{route.system}/{route.engine}: {error}"
                          for error in row_errors)
    if not routes:
        errors.append("installed metadata exposes no Lucent in-window routes")
    report["pass"] = not errors
    report["errors"] = errors
    return errors, report


def candidate_route_pairs(apk: Path, systems: set[str]) -> list[tuple[str, Route]]:
    """Return ordered Phase 1/2 candidates the APK catalogs could consider."""
    candidates: list[tuple[str, Route]] = []
    with zipfile.ZipFile(apk) as archive:
        try:
            phase1 = json.loads(archive.read(
                "assets/engine-registry.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            phase1 = {}
        for row in phase1.get("engines", []):
            if not isinstance(row, dict):
                continue
            engine = normalized(row.get("id"))
            for system in row.get("systems", []):
                system_id = normalized(system)
                if engine and system_id in systems:
                    candidates.append(("phase1", Route(system_id, engine)))

        try:
            phase2 = json.loads(archive.read(
                "assets/phase2-qualification-opt-in.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            phase2 = {}
        # This is deliberately the explicit library route allow-list, not the
        # broader Phase 2 registry systems field. GameLaunchRouter cannot expose
        # qualification-only systems that are merely packaged for developer QA.
        for row in phase2.get("engines", []):
            if not isinstance(row, dict):
                continue
            engine = normalized(row.get("id"))
            for system in row.get("libraryRouteSystems", []):
                system_id = normalized(system)
                if engine and system_id in systems:
                    candidates.append(("phase2", Route(system_id, engine)))
    return candidates


def simulate_candidate_routes(apk: Path, systems: set[str],
                              dexdump: Path) -> tuple[set[Route], dict]:
    """Model GameLaunchRouter after candidate startup, without touching Android."""
    scoped = {normalized(system) for system in systems if normalized(system)}
    canonical_by_shortname = {
        system: canonical_system_id(system) for system in sorted(scoped)
    }
    canonical_scoped = set(canonical_by_shortname.values())
    alias_dex_ok, alias_dex_detail = dex_alias_contract_evidence(apk, dexdump)
    candidates = candidate_route_pairs(
        apk, canonical_scoped - PHASE3_SYSTEMS
    ) if alias_dex_ok else []
    candidate_set = {route for _phase, route in candidates}
    _errors, qualification = verify(apk, candidate_set, dexdump)
    passing = {
        Route(str(row.get("system", "")), str(row.get("engine", "")))
        for row in qualification.get("routes", []) if row.get("pass") is True
    }

    selected: dict[str, Route] = {}
    # InternalEngineCatalog wins and uses first qualified registry order.
    for phase, route in candidates:
        if phase == "phase1" and route in passing and route.system not in selected:
            selected[route.system] = route
    ambiguous: list[str] = []
    # Phase2QualificationCatalog requires exactly one explicit library match.
    for system in sorted(canonical_scoped - set(selected) - PHASE3_SYSTEMS):
        matches = []
        for phase, route in candidates:
            if phase == "phase2" and route.system == system and route in passing and \
                    route not in matches:
                matches.append(route)
        if len(matches) == 1:
            selected[system] = matches[0]
        elif len(matches) > 1:
            ambiguous.append(system)

    routes = set(selected.values())
    unsupported_shortnames = {
        shortname for shortname, canonical in canonical_by_shortname.items()
        if canonical not in selected
    }
    alias_contracts = []
    alias_failures = []
    for alias, (canonical, engine) in sorted(REQUIRED_ALIAS_ROUTES.items()):
        if alias not in scoped:
            continue
        actual = selected.get(canonical)
        passed = alias_dex_ok and actual == Route(canonical, engine)
        alias_contracts.append({
            "shortname": alias, "canonicalSystem": canonical,
            "expectedEngine": engine,
            "actualEngine": actual.engine if actual is not None else "",
            "pass": passed,
        })
        if not passed:
            alias_failures.append(
                f"{alias}->{canonical}/{engine} is not present in the exact candidate"
            )
    report = {
        "mode": "candidate-GameLaunchRouter-simulation",
        "metadataCollectionSystems": sorted(scoped),
        "shortnameCanonicalization": canonical_by_shortname,
        "aliasMapSha256": alias_map_sha256(),
        "candidateDexAliasContract": {
            "pass": alias_dex_ok, "detail": alias_dex_detail,
        },
        "requiredAliasRoutes": alias_contracts,
        "aliasContractFailures": alias_failures,
        "candidateSupportedRoutes": [
            {"system": route.system, "engine": route.engine}
            for route in sorted(routes)
        ],
        "unsupportedPhase3Systems": sorted(
            system for system in unsupported_shortnames
            if canonical_by_shortname[system] in PHASE3_SYSTEMS
        ),
        "unsupportedOtherSystems": sorted(
            system for system in unsupported_shortnames
            if canonical_by_shortname[system] not in PHASE3_SYSTEMS
        ),
        "ambiguousPhase2Systems": ambiguous,
        "candidatePairsInspected": [
            {"phase": phase, "system": route.system, "engine": route.engine,
             "qualified": route in passing}
            for phase, route in candidates
        ],
    }
    return routes, report


def default_adb() -> Path:
    candidates = (
        Path.home() / ".codex/tools/android-platform-tools/adb",
        Path.home() / "Library/Android/sdk/platform-tools/adb",
    )
    return next((path for path in candidates if path.is_file()), candidates[-1])


def default_dexdump() -> Path:
    root = Path.home() / "Library/Android/sdk/build-tools"
    candidates = sorted(root.glob("*/dexdump"))
    return candidates[-1] if candidates else Path("dexdump")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--serial")
    parser.add_argument("--adb", type=Path, default=default_adb())
    parser.add_argument("--dexdump", type=Path, default=default_dexdump())
    parser.add_argument("--metadata", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                     for path in args.metadata)
    if args.serial:
        text += "\n" + device_route_text(args.adb, args.serial)
    routes = routes_from_text(text)
    simulation = None
    shortnames = collection_shortnames(text)
    if not routes and shortnames:
        routes, simulation = simulate_candidate_routes(
            args.apk.resolve(), shortnames, args.dexdump
        )
    errors, report = verify(args.apk.resolve(), routes, args.dexdump)
    if simulation is not None:
        report["preinstallSimulation"] = simulation
        if not simulation["candidateDexAliasContract"]["pass"]:
            errors.append(simulation["candidateDexAliasContract"]["detail"])
        errors.extend(simulation["aliasContractFailures"])
    invalid = invalid_launch_lines(text)
    if invalid:
        report["invalidMetadataLaunchers"] = invalid
        errors.extend("metadata launcher " + row["commandSha256"] + ": " + row["reason"]
                      for row in invalid)
        report["pass"] = False
        report["errors"] = errors
    elif errors:
        report["pass"] = False
        report["errors"] = errors
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
