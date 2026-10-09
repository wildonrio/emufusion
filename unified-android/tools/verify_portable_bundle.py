#!/usr/bin/env python3
"""Require the owned-library's internal system routes in one qualification APK.

This adds completeness to the existing per-phase payload checks, which allow
intentional subsets. It does not establish device compatibility or gameplay.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

import verify_phase1_apk as phase1
import verify_phase2_apk as phase2
import verify_phase3_apk as phase3

REQUIRED = {
    'switch': (3, 'eden'), 'wiiu': (3, 'cemu'), 'ps3': (3, 'aps3e'),
    'wii': (2, 'dolphin'), 'gamecube': (2, 'dolphin'), 'ps2': (2, 'armsx2'),
    'psp': (2, 'ppsspp'), 'dreamcast': (2, 'flycast'), '3ds': (2, 'azahar'),
    'psx': (1, 'swanstation'), 'nds': (1, 'melonds-ds'),
    'n64': (1, 'mupen64plus-next'), 'snes': (1, 'mesen-s'), 'nes': (1, 'mesen'),
    'gb': (1, 'sameboy'), 'gbc': (1, 'sameboy'), 'gba': (1, 'mgba'),
    'megadrive': (1, 'blastem'), 'gamegear': (1, 'gearsystem'),
    'pcenginecd': (1, 'beetle-pce-fast'),
}
PHASES = {1: phase1, 2: phase2, 3: phase3}
SUPPORT_LIBRARIES = (
    'liblucent_libretro_host.so', 'liblucent_vulkan_host.so',
    'liblucent_native_adapter_host.so', 'libhook_impl.so', 'libmain_hook.so',
)

def rows(archive, asset, key, id_key):
    document = json.loads(archive.read(asset))
    if not isinstance(document, dict) or not isinstance(document.get(key), list):
        raise ValueError(f'invalid {asset}')
    indexed = {}
    for row in document[key]:
        if (not isinstance(row, dict) or not isinstance(row.get(id_key), str)
                or row[id_key] in indexed):
            raise ValueError(f'duplicate/invalid {id_key} in {asset}')
        indexed[row[id_key]] = row
    return document, indexed

def coverage_errors(archive):
    errors = []
    names = archive.namelist()
    if len(names) != len(set(names)):
        errors.append('APK contains duplicate archive entries')
    for library in SUPPORT_LIBRARIES:
        name = 'lib/arm64-v8a/' + library
        if name not in names:
            errors.append(f'missing internal host/driver support: {library}')
    catalogs = {}
    for number, module in PHASES.items():
        opt, enabled = rows(archive, module.OPT_IN, 'engines', 'id')
        _, registry = rows(archive, module.REGISTRY, 'engines', 'id')
        _, artifacts = rows(archive, module.ARTIFACTS, 'artifacts', 'engineId')
        if number == 1 and opt.get('autoSelect') is not True:
            errors.append('Phase 1 cores are packaged but disabled for normal-library selection')
        catalogs[number] = enabled, registry, artifacts
    for system, (number, engine) in REQUIRED.items():
        enabled, registry, artifacts = catalogs[number]
        if engine not in enabled or engine not in registry or engine not in artifacts:
            errors.append(f'{system}: required internal {engine} is absent from Phase {number}')
            continue
        row = enabled[engine]
        routes = registry[engine].get('systems', []) if number == 1 else row.get('libraryRouteSystems', [])
        if not isinstance(routes, list) or system not in routes:
            errors.append(f'{system}: {engine} has no normal-library route')
        library = row.get('libraryName')
        if not isinstance(library, str) or 'lib/arm64-v8a/' + library not in names:
            errors.append(f'{system}: packaged {engine} library is missing')
    return errors

def verify(apk: Path):
    try:
        with zipfile.ZipFile(apk) as archive:
            errors = coverage_errors(archive)
        # Keep all existing hash, source, prerequisite-exclusion and asset gates.
        for number, module in PHASES.items():
            errors.extend(f'Phase {number}: {error}' for error in module.verify(apk))
        return errors
    except (OSError, KeyError, ValueError, TypeError, AttributeError, zipfile.BadZipFile) as exc:
        return [f'invalid portable bundle: {exc}']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    args = parser.parse_args()
    errors = verify(args.apk)
    for error in errors:
        print(error)
    if errors:
        return 1
    print(f'EmuFusion portable bundle: {len(REQUIRED)} internal system routes and pinned payloads present. '
          'Packaging only; not gameplay, hardware compatibility or release acceptance.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
