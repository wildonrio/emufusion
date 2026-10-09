#!/usr/bin/env python3
"""Restore the tracked Eden timing subset; this is not a full Eden builder.

Default is read-only verification. --apply handles an upstream or already
patched timing tree, refusing mismatched contexts rather than overwriting them.
Other source-lock patches and the existing CMake/NDK checkout are prerequisites.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PATCHES = [ROOT / "engines/patches/eden-lucent-clock.patch",
           ROOT / "engines/patches/eden-lucent-audio-observation.patch",
           ROOT / "engines/patches/eden-lucent-adreno-descriptors.patch"]
COPIES = {
    ROOT / "engines/patches/eden-lucent-pacing.h": "src/common/lucent_pacing.h",
    ROOT / "engines/patches/eden-lucent-audio-observation.h":
        "src/common/lucent_audio_observation.h",
    ROOT / "engines/patches/eden-lucent-adapter.cpp":
        "src/android/app/src/main/jni/lucent_adapter.cpp",
    ROOT / "engines/patches/eden-lucent-source-image.h": "src/common/lucent_source_image.h",
    ROOT / "unified-android/native/include/lucent_native_source_image.h":
        "src/common/lucent_source_image_types.h",
}


def apply_check(tree, patch, reverse=False):
    command = ["git", "-C", str(tree), "apply", "--check"]
    if reverse:
        command.append("--reverse")
    return subprocess.run(command + [str(patch)], capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path,
                        default=ROOT / "engines/build/switch-src/eden")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    tree = args.tree.resolve()
    if not (tree / "src/core/hle/service/vi/conductor.cpp").is_file():
        parser.error("expected the existing Eden source checkout")
    pending = []
    for patch in PATCHES:
        if apply_check(tree, patch, reverse=True).returncode == 0:
            continue
        check = apply_check(tree, patch)
        if not args.apply or check.returncode:
            sys.stderr.write(f"Timing patch not verified: {patch.name}\n")
            sys.stderr.write(check.stderr)
            return 1
        pending.append(patch)
    # Preflight every patch before changing any source. These patches touch
    # disjoint hunks; do not use this as an order-dependent patch series runner.
    for patch in pending:
        subprocess.run(["git", "-C", str(tree), "apply", str(patch)], check=True)
    for source, relative in COPIES.items():
        target = tree / relative
        if args.apply:
            if not target.parent.is_dir():
                raise RuntimeError(f"missing configured adapter directory: {target.parent}")
            # Preserve unchanged header mtimes: touching them needlessly
            # recompiles most of the engine on every verification/apply run.
            if not target.is_file() or source.read_bytes() != target.read_bytes():
                shutil.copyfile(source, target)
        if not target.is_file() or source.read_bytes() != target.read_bytes():
            sys.stderr.write(f"Canonical timing source differs: {relative}\n")
            return 1
    print("Eden timing source subset matches; artifact rebuild and device evidence still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
