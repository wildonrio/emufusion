#!/usr/bin/env python3
"""Recover enriched Pegasus fields without rolling back ROMs or media.

The recovery is keyed by each game's exact ``file:`` path.  A known-good
metadata snapshot supplies titles, ratings, release dates, and provenance;
the current metadata remains authoritative for ROM membership, launch rules,
and every ``assets.*`` field.  New games that do not exist in the donor are
retained and their display titles are cleaned conservatively.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


FIELD = re.compile(r"^([^:#][^:]*):\s*(.*)$")
GAME_SPLIT = re.compile(r"(?=^game:\s)", re.MULTILINE)
DATE_CHAIN = re.compile(r"\s*\((?:19|20)[0-9x]{2}(?:[-.][0-9x]{1,2}){0,2}\).*$", re.I)
TRAILING_TAG = re.compile(
    r"\s*(?:"
    r"\((?:(?:USA|Europe|Japan|World)(?:,\s*(?:USA|Europe|Japan|World))*|"
    r"US|U|EU|E|JP|J|W|UE|Beta|Proto(?:type)?|Demo|Kiosk|Bonus Disc|"
    r"Virtual Console|Unl(?:icensed)?|NTSC|PAL|Rev(?:ision)?[^)]*|"
    r"Disc\s+\d+(?:\s+of\s+\d+)?|v?\d+(?:[ .]\d+)*|[!nph]|"
    r"T-En[^)]*|En(?:,[A-Za-z]+)*)\)"
    r"|\[(?:(?:USA|Europe|Japan|World)(?:,\s*(?:USA|Europe|Japan|World))*|"
    r"US|U|EU|E|JP|J|W|UE|Beta|Proto(?:type)?|Demo|Kiosk|Bonus Disc|"
    r"Unl(?:icensed)?|NTSC|PAL|Rev(?:ision)?[^]]*|"
    r"Disc\s+\d+(?:\s+of\s+\d+)?|v?\d+(?:[ .]\d+)*|[!nph]|T-En[^]]*)\]"
    r")\s*$",
    re.I,
)
ARTICLE = re.compile(r"^(.+),\s+(The|A|An)$", re.I)
EMBEDDED_ARTICLE = re.compile(r"^(.+),\s+(The|A|An)(\s*[:\-].*)$", re.I)

CORE_FIELDS = {"sort-by", "rating", "release", "developer", "publisher"}


def parse_fields(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        match = FIELD.match(line)
        if match:
            result[match.group(1).strip().lower()] = match.group(2).strip()
    return result


def game_blocks(text: str) -> tuple[str, list[list[str]]]:
    parts = GAME_SPLIT.split(text)
    header = parts[0]
    return header, [part.rstrip("\n").splitlines() for part in parts[1:]]


def file_stem(value: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def strip_title_tags(value: str) -> str:
    title = value.replace("_", ": ").strip()
    title = re.sub(r"(?i)(?:\s*[:\-]\s*)copy$", "", title).strip()
    title = re.sub(r"(?i)[.\s-]*[0-9a-f]{16}(?:[.\s-]*v\d+)?$", "", title)
    title = re.sub(r"(?i)\s*\[[0-9a-f]{16}\]", "", title)
    title = re.sub(r"(?i)\s*\[v\d+\]", "", title)
    title = re.sub(r"(?i)\s+v\d+(?:[ .]\d+)+$", "", title)
    title = re.sub(r"(?i)\s+[—:-]\s+disc\s+\d+(?:\s+of\s+\d+)?$", "", title)
    title = DATE_CHAIN.sub("", title).strip()
    # Repair truncated ROM-set suffixes such as "(U" or "(U) (V1.".
    title = re.sub(r"(?i)\s*\((?:USA|US|U|Europe|EU|E|Japan|JP|J|W|UE)\b.*$",
                   "", title).strip()
    while True:
        cleaned = TRAILING_TAG.sub("", title).strip()
        if cleaned == title:
            break
        title = cleaned
    title = re.sub(r"\s+", " ", title).strip(" -:_")
    article = ARTICLE.match(title)
    if article:
        title = f"{article.group(2)} {article.group(1)}"
    else:
        article = EMBEDDED_ARTICLE.match(title)
        if article:
            title = f"{article.group(2)} {article.group(1)}{article.group(3)}"
    return title or "Untitled Game"


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def clean_display_title(title: str, rom_path: str) -> str:
    cleaned = strip_title_tags(title)
    # Archive/catalog titles sometimes append date, publisher, and territory
    # groups while the exact ROM filename already contains the well-punctuated
    # title.  Prefer that filename only when both normalize to the same game.
    had_dump_chain = bool(DATE_CHAIN.search(title))
    from_file = strip_title_tags(file_stem(rom_path))
    if had_dump_chain and normalize_title(cleaned) == normalize_title(from_file):
        return from_file
    return cleaned


def donor_index(directory: Path) -> dict[str, tuple[str, dict[str, str]]]:
    index: dict[str, tuple[str, dict[str, str]]] = {}
    for path in sorted(directory.glob("*.metadata.pegasus.txt")):
        _, blocks = game_blocks(path.read_text(encoding="utf-8", errors="replace"))
        for lines in blocks:
            fields = parse_fields(lines)
            rom_path = fields.get("file", "")
            if rom_path:
                index[rom_path] = (fields.get("game", ""), fields)
    return index


def donor_managed(fields: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in fields.items()
        if key in CORE_FIELDS or (key.startswith("x-") and key != "x-emufusion-id")
    }


def rewrite_block(
    lines: list[str], donor: tuple[str, dict[str, str]] | None
) -> tuple[list[str], bool, bool]:
    current = parse_fields(lines)
    rom_path = current.get("file", "")
    old_title = current.get("game", "")
    donor_title = donor[0] if donor else ""
    title = clean_display_title(donor_title or old_title, rom_path)
    managed = donor_managed(donor[1]) if donor else {}

    # Preserve current metadata unless the donor has an authoritative value.
    # Any managed donor field is emitted once, immediately after ``game:``.
    replace_keys = set(managed)
    output = [f"game: {title}"]
    for key, value in managed.items():
        output.append(f"{key}: {value}")
    for line in lines[1:]:
        match = FIELD.match(line)
        if match and match.group(1).strip().lower() in replace_keys:
            continue
        output.append(line)

    # A cleaned title changes the stable tie-breaker but must not destroy the
    # score prefix used for native user sorting.
    for index, line in enumerate(output):
        if line.startswith("sort-by:"):
            match = re.match(r"sort-by:\s*(\d{5})\s+", line)
            if match:
                output[index] = f"sort-by: {match.group(1)} {title.casefold()}"
            break
    return output, title != old_title, donor is not None


def coverage(path: Path) -> dict[str, int | str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    header, blocks = game_blocks(text)
    shortname_match = re.search(r"^shortname:\s*(.+)$", header, re.MULTILINE)
    counts: Counter[str] = Counter()
    counts["games"] = len(blocks)
    for lines in blocks:
        fields = parse_fields(lines)
        counts["critic"] += int(bool(fields.get("x-critic-composite") or fields.get("x-critic")))
        counts["user"] += int(bool(fields.get("x-user-composite") or fields.get("x-user-score")))
        counts["release"] += int(bool(fields.get("release")))
    return {
        "system": shortname_match.group(1).strip() if shortname_match else path.stem,
        "games": counts["games"],
        "critic": counts["critic"],
        "user": counts["user"],
        "release": counts["release"],
    }


def recover(current: Path, donor_dir: Path, output: Path) -> list[dict[str, int | str]]:
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing output directory: {output}")
    output.mkdir(parents=True)
    donors = donor_index(donor_dir)
    total_restored = total_renamed = 0
    report: list[dict[str, int | str]] = []
    for source in sorted(current.glob("*.metadata.pegasus.txt")):
        text = source.read_text(encoding="utf-8", errors="replace")
        header, blocks = game_blocks(text)
        if source.name == "08-windows.metadata.pegasus.txt":
            header = re.sub(r"^collection:\s*Windows 10$", "collection: Microsoft Windows",
                            header, flags=re.MULTILINE)
        elif source.name == "99-emufusion-auto-pcenginecd.metadata.pegasus.txt":
            header = re.sub(r"^collection:\s*NEC PC Engine CD$",
                            "collection: Microsoft Windows", header, flags=re.MULTILINE)
        rewritten: list[str] = []
        restored = renamed = 0
        for lines in blocks:
            fields = parse_fields(lines)
            new_lines, did_rename, did_restore = rewrite_block(
                lines, donors.get(fields.get("file", ""))
            )
            rewritten.append("\n".join(new_lines) + "\n\n")
            renamed += int(did_rename)
            restored += int(did_restore)
        destination = output / source.name
        destination.write_text(header.rstrip("\n") + "\n\n" + "".join(rewritten), encoding="utf-8")
        row = coverage(destination)
        row.update({"restored": restored, "renamed": renamed})
        report.append(row)
        total_restored += restored
        total_renamed += renamed
    print(json.dumps({
        "donorGames": len(donors),
        "restoredGames": total_restored,
        "renamedGames": total_renamed,
        "systems": report,
    }, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--donor", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    recover(args.current, args.donor, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
