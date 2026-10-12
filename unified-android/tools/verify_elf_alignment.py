#!/usr/bin/env python3
"""Verify that every packaged 64-bit ELF supports 16 KiB Android pages."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys
import zipfile


ELF_MAGIC = b"\x7fELF"
PT_LOAD = 1
MIN_ALIGNMENT = 0x4000


def load_alignments(data: bytes) -> list[int]:
    if len(data) < 64 or data[:4] != ELF_MAGIC:
        raise ValueError("not an ELF file")
    elf_class = data[4]
    byte_order = data[5]
    if elf_class != 2:
        raise ValueError("expected a 64-bit ELF")
    if byte_order == 1:
        endian = "<"
    elif byte_order == 2:
        endian = ">"
    else:
        raise ValueError("invalid ELF byte order")
    program_offset = struct.unpack_from(endian + "Q", data, 32)[0]
    entry_size = struct.unpack_from(endian + "H", data, 54)[0]
    entry_count = struct.unpack_from(endian + "H", data, 56)[0]
    if entry_size < 56:
        raise ValueError("invalid ELF program-header size")
    alignments: list[int] = []
    for index in range(entry_count):
        offset = program_offset + index * entry_size
        if offset + 56 > len(data):
            raise ValueError("truncated ELF program-header table")
        segment_type = struct.unpack_from(endian + "I", data, offset)[0]
        if segment_type == PT_LOAD:
            alignments.append(struct.unpack_from(endian + "Q", data, offset + 48)[0])
    if not alignments:
        raise ValueError("ELF has no PT_LOAD segments")
    return alignments


def verify(apk: Path, allow_4k: "frozenset[str] | set[str] | tuple[str, ...]" = ()) -> list[str]:
    """Return blocking errors; allowlisted 4 KiB offenders become warnings.

    ``allow_4k`` entries are bare library names (``libssl.so``); a matching
    library that is only 4 KiB aligned is reported through :func:`warnings_for`
    instead of failing the check. Everything else must be 16 KiB aligned.
    """
    errors, _warnings = verify_report(apk, allow_4k)
    return errors


def verify_report(
    apk: Path, allow_4k: "frozenset[str] | set[str] | tuple[str, ...]" = ()
) -> tuple[list[str], list[str]]:
    allowed = {Path(name).name for name in allow_4k}
    errors: list[str] = []
    warnings: list[str] = []
    with zipfile.ZipFile(apk) as archive:
        libraries = sorted(
            name for name in archive.namelist()
            if name.startswith("lib/arm64-v8a/") and name.endswith(".so")
        )
        if not libraries:
            return ["APK contains no ARM64 libraries"], warnings
        for name in libraries:
            try:
                alignments = load_alignments(archive.read(name))
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
                continue
            low = min(alignments)
            if low < MIN_ALIGNMENT:
                message = (
                    f"{name}: PT_LOAD alignment 0x{low:x} is below 0x{MIN_ALIGNMENT:x}"
                )
                if Path(name).name in allowed:
                    warnings.append(message + " (allowlisted; must be fixed before release)")
                else:
                    errors.append(message)
    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument(
        "--allow-4k-lib", action="append", default=[], metavar="NAME",
        help="library name whose 4 KiB alignment is a known, temporary "
             "offender; reported as a warning instead of an error "
             "(repeatable)",
    )
    args = parser.parse_args()
    errors, warnings = verify_report(args.apk, args.allow_4k_lib)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    if warnings:
        print(
            f"EmuFusion 16 KiB ELF alignment: PASS with {len(warnings)} "
            "allowlisted 4 KiB offender(s)"
        )
    else:
        print("EmuFusion 16 KiB ELF alignment: PASS")


if __name__ == "__main__":
    main()
