#!/usr/bin/env python3
"""Build EmuFusion's compact, device-independent text metadata lookup.

Input is one or more Pegasus metadata trees.  ROM and media paths are never
copied into the package; only canonical title, scores, date, and credits are
retained.  Duplicate stanzas are merged by field so the richer record wins.
"""

from __future__ import annotations

import argparse
import pathlib
import re


FIELDS = {
    "x-critic": "critic",
    "x-user-score": "user",
    "release": "release",
    "developer": "developer",
    "publisher": "publisher",
    "x-critic-sources": "critic_sources",
    "x-user-sources": "user_sources",
}


def normalized(value: str) -> str:
    value = value.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def clean(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def folder_from(stanza: dict[str, str], source: pathlib.Path) -> str:
    path = stanza.get("file", "").replace("\\", "/")
    match = re.search(r"/Games/([^/]+)/", path, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    match = re.search(r"(?:^|-)auto-([a-z0-9]+)\.metadata", source.name)
    return match.group(1).lower() if match else ""


def parse_file(path: pathlib.Path, rows: dict[tuple[str, str], dict[str, str]]) -> None:
    def save(stanza: dict[str, str]) -> None:
        title = clean(stanza.get("game", ""))
        folder = folder_from(stanza, path)
        key = normalized(title)
        if not title or not folder or not key:
            return
        row = rows.setdefault((folder, key), {"folder": folder, "key": key, "title": title})
        if len(title) < len(row.get("title", "")) + 30:
            row["title"] = title
        for peg_field, output_field in FIELDS.items():
            value = clean(stanza.get(peg_field, ""))
            if value and (not row.get(output_field) or len(value) > len(row[output_field])):
                row[output_field] = value

    stanza: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("game:"):
            if stanza:
                save(stanza)
            stanza = {"game": line.split(":", 1)[1].strip()}
            continue
        if not stanza or ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        stanza[key.strip()] = value.strip()
    if stanza:
        save(stanza)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    rows: dict[tuple[str, str], dict[str, str]] = {}
    for root in args.inputs:
        paths = root.rglob("*.metadata.pegasus.txt") if root.is_dir() else [root]
        for path in paths:
            parse_file(path, rows)
    columns = ["folder", "key", "title", "critic", "user", "release", "developer",
               "publisher", "critic_sources", "user_sources"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        output.write("\t".join(columns) + "\n")
        for key in sorted(rows):
            row = rows[key]
            # Blank trailing fields do not need serialized tab padding. This
            # keeps the catalog diff-friendly while intermediate blanks retain
            # their exact column positions.
            line = "\t".join(clean(row.get(column, "")) for column in columns)
            output.write(line.rstrip("\t") + "\n")
    print(f"wrote {len(rows)} records to {args.output}")


if __name__ == "__main__":
    main()
