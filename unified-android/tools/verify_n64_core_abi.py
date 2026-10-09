#!/usr/bin/env python3
"""Fail-closed APK ABI audit for EmuFusion's Mupen64Plus-Next core.

This verifier intentionally does not execute the APK or use a connected device.
It inspects the exact bytes packaged in the APK and rejects the regression where
an NDK-r27 core resolves C++ symbols against the older process-wide Qt runtime.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import sys
import zipfile


CORE_MEMBER = "lib/arm64-v8a/liblucent_core_mupen64plus_next.so"
ELF_MAGIC = b"\x7fELF"
ELFCLASS64 = 2
ELFDATA2LSB = 1
PT_LOAD = 1
SHT_DYNAMIC = 6
SHT_DYNSYM = 11
SHN_UNDEF = 0
DT_NULL = 0
DT_NEEDED = 1
MIN_ANDROID_ALIGNMENT = 0x4000

# Bionic owns these two symbols. They are C ABI entry points despite the name,
# so a self-contained static libc++ core may legitimately leave them undefined.
BIONIC_CXX_ABI_ALLOWLIST = frozenset({
    "__cxa_atexit",
    "__cxa_atexit@LIBC",
    "__cxa_finalize",
    "__cxa_finalize@LIBC",
})


class ElfError(ValueError):
    """The candidate is not a structurally valid ELF64 little-endian object."""


@dataclass(frozen=True)
class Section:
    name_offset: int
    section_type: int
    offset: int
    size: int
    link: int
    entry_size: int


@dataclass(frozen=True)
class ElfAbi:
    needed: tuple[str, ...]
    undefined_symbols: tuple[str, ...]
    load_alignments: tuple[int, ...]


@dataclass(frozen=True)
class Verification:
    apk_sha256: str
    core_sha256: str
    needed: tuple[str, ...]
    unresolved_cpp_runtime_symbols: tuple[str, ...]
    load_alignments: tuple[int, ...]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checked_slice(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ElfError(f"truncated {label}")
    return data[offset:offset + size]


def _cstring(table: bytes, offset: int, label: str) -> str:
    if offset < 0 or offset >= len(table):
        raise ElfError(f"invalid {label} string offset {offset}")
    end = table.find(b"\0", offset)
    if end < 0:
        raise ElfError(f"unterminated {label} string at offset {offset}")
    return table[offset:end].decode("utf-8", errors="surrogateescape")


def parse_elf64(data: bytes) -> ElfAbi:
    if len(data) < 64 or data[:4] != ELF_MAGIC:
        raise ElfError("not an ELF file")
    if data[4] != ELFCLASS64:
        raise ElfError("expected ELF64")
    if data[5] != ELFDATA2LSB:
        raise ElfError("expected little-endian ELF")

    program_offset = struct.unpack_from("<Q", data, 32)[0]
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    program_entry_size = struct.unpack_from("<H", data, 54)[0]
    program_count = struct.unpack_from("<H", data, 56)[0]
    section_entry_size = struct.unpack_from("<H", data, 58)[0]
    section_count = struct.unpack_from("<H", data, 60)[0]

    if program_entry_size < 56:
        raise ElfError("invalid program-header entry size")
    if section_entry_size < 64 or section_count == 0:
        raise ElfError("missing ELF64 section table")

    load_alignments: list[int] = []
    for index in range(program_count):
        offset = program_offset + index * program_entry_size
        entry = _checked_slice(data, offset, 56, "program-header table")
        if struct.unpack_from("<I", entry, 0)[0] == PT_LOAD:
            load_alignments.append(struct.unpack_from("<Q", entry, 48)[0])
    if not load_alignments:
        raise ElfError("ELF has no PT_LOAD segments")

    sections: list[Section] = []
    for index in range(section_count):
        offset = section_offset + index * section_entry_size
        entry = _checked_slice(data, offset, 64, "section-header table")
        sections.append(Section(
            name_offset=struct.unpack_from("<I", entry, 0)[0],
            section_type=struct.unpack_from("<I", entry, 4)[0],
            offset=struct.unpack_from("<Q", entry, 24)[0],
            size=struct.unpack_from("<Q", entry, 32)[0],
            link=struct.unpack_from("<I", entry, 40)[0],
            entry_size=struct.unpack_from("<Q", entry, 56)[0],
        ))

    needed: list[str] = []
    dynamic_sections = [section for section in sections if section.section_type == SHT_DYNAMIC]
    if not dynamic_sections:
        raise ElfError("missing SHT_DYNAMIC section")
    for section in dynamic_sections:
        if section.link >= len(sections):
            raise ElfError("SHT_DYNAMIC has invalid string-table link")
        string_section = sections[section.link]
        strings = _checked_slice(data, string_section.offset, string_section.size, "dynamic string table")
        entry_size = section.entry_size or 16
        if entry_size < 16 or section.size % entry_size:
            raise ElfError("invalid SHT_DYNAMIC entry layout")
        entries = _checked_slice(data, section.offset, section.size, "dynamic section")
        for offset in range(0, len(entries), entry_size):
            tag, value = struct.unpack_from("<qQ", entries, offset)
            if tag == DT_NULL:
                break
            if tag == DT_NEEDED:
                needed.append(_cstring(strings, value, "DT_NEEDED"))

    undefined: list[str] = []
    dynamic_symbols = [section for section in sections if section.section_type == SHT_DYNSYM]
    if not dynamic_symbols:
        raise ElfError("missing SHT_DYNSYM section")
    for section in dynamic_symbols:
        if section.link >= len(sections):
            raise ElfError("SHT_DYNSYM has invalid string-table link")
        string_section = sections[section.link]
        strings = _checked_slice(data, string_section.offset, string_section.size, "symbol string table")
        entry_size = section.entry_size or 24
        if entry_size < 24 or section.size % entry_size:
            raise ElfError("invalid SHT_DYNSYM entry layout")
        symbols = _checked_slice(data, section.offset, section.size, "dynamic symbol table")
        for offset in range(0, len(symbols), entry_size):
            name_offset = struct.unpack_from("<I", symbols, offset)[0]
            section_index = struct.unpack_from("<H", symbols, offset + 6)[0]
            if section_index != SHN_UNDEF or name_offset == 0:
                continue
            undefined.append(_cstring(strings, name_offset, "dynamic symbol"))

    return ElfAbi(
        needed=tuple(sorted(set(needed))),
        undefined_symbols=tuple(sorted(set(undefined))),
        load_alignments=tuple(load_alignments),
    )


def is_cpp_runtime_abi_symbol(symbol: str) -> bool:
    if symbol in BIONIC_CXX_ABI_ALLOWLIST:
        return False
    bare = symbol.split("@", 1)[0]
    return (
        bare.startswith("_Z")
        or bare.startswith("__cxa_")
        or bare.startswith("__gxx_")
        or bare.startswith("_Unwind_")
        or "St6__ndk1" in bare
        or "__cxxabiv1" in bare
    )


def verify_apk(
    apk: Path,
    *,
    expected_apk_sha256: str,
    expected_core_sha256: str,
) -> Verification:
    errors: list[str] = []
    actual_apk_sha256 = sha256_file(apk)
    if actual_apk_sha256 != expected_apk_sha256.lower():
        errors.append(
            f"APK SHA-256 mismatch: expected {expected_apk_sha256.lower()}, "
            f"found {actual_apk_sha256}"
        )

    core_data = b""
    try:
        with zipfile.ZipFile(apk) as archive:
            matches = [name for name in archive.namelist() if name == CORE_MEMBER]
            if len(matches) != 1:
                errors.append(f"expected exactly one {CORE_MEMBER}, found {len(matches)}")
            else:
                core_data = archive.read(CORE_MEMBER)
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        errors.append(f"cannot read APK: {exc}")

    actual_core_sha256 = sha256_bytes(core_data)
    if actual_core_sha256 != expected_core_sha256.lower():
        errors.append(
            f"N64 core SHA-256 mismatch: expected {expected_core_sha256.lower()}, "
            f"found {actual_core_sha256}"
        )

    needed: tuple[str, ...] = ()
    unresolved_cpp: tuple[str, ...] = ()
    alignments: tuple[int, ...] = ()
    if core_data:
        try:
            abi = parse_elf64(core_data)
            needed = abi.needed
            alignments = abi.load_alignments
            unresolved_cpp = tuple(
                symbol for symbol in abi.undefined_symbols
                if is_cpp_runtime_abi_symbol(symbol)
            )
            if "libc++_shared.so" in needed:
                errors.append("N64 core has forbidden DT_NEEDED dependency on libc++_shared.so")
            if unresolved_cpp:
                preview = ", ".join(unresolved_cpp[:8])
                suffix = "" if len(unresolved_cpp) <= 8 else f" (+{len(unresolved_cpp) - 8} more)"
                errors.append(f"N64 core has unresolved C++ runtime ABI symbols: {preview}{suffix}")
            for index, alignment in enumerate(alignments):
                if alignment < MIN_ANDROID_ALIGNMENT:
                    errors.append(
                        f"N64 core PT_LOAD[{index}] alignment 0x{alignment:x} "
                        f"is below 0x{MIN_ANDROID_ALIGNMENT:x}"
                    )
        except ElfError as exc:
            errors.append(f"cannot inspect N64 core ELF: {exc}")

    return Verification(
        apk_sha256=actual_apk_sha256,
        core_sha256=actual_core_sha256,
        needed=needed,
        unresolved_cpp_runtime_symbols=unresolved_cpp,
        load_alignments=alignments,
        errors=tuple(errors),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the exact packaged Lucent N64 core is C++-ABI self-contained."
    )
    parser.add_argument("apk", type=Path)
    parser.add_argument("--expected-apk-sha256", required=True)
    parser.add_argument("--expected-core-sha256", required=True)
    args = parser.parse_args()

    result = verify_apk(
        args.apk,
        expected_apk_sha256=args.expected_apk_sha256,
        expected_core_sha256=args.expected_core_sha256,
    )
    print(f"APK SHA-256: {result.apk_sha256}")
    print(f"N64 core SHA-256: {result.core_sha256}")
    print(f"DT_NEEDED: {', '.join(result.needed)}")
    print("PT_LOAD alignments: " + ", ".join(f"0x{x:x}" for x in result.load_alignments))
    if result.errors:
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Lucent N64 packaged C++ ABI: PASS")


if __name__ == "__main__":
    main()
