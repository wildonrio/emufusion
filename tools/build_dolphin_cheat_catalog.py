#!/usr/bin/env python3
"""Build the exact GameCube/Wii cheat index shipped by the pinned Dolphin core.

Only Action Replay and Gecko sections are indexed. OnFrame patches are emulator
configuration, not toggleable cheat slots. Invalid/annotated source lines are
rejected rather than repaired: the runtime enables a Dolphin code by comparing
the submitted serialized body to the code Dolphin itself parsed from these INIs.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "engines" / "phase2-registry.json"
OUTPUT = ROOT / "engines" / "cheats" / "dolphin-cheats.json"
HEX_LINE = re.compile(r"^[0-9A-Fa-f]{8}\s+[0-9A-Fa-f]{8}$")
ENCRYPTED_AR = re.compile(r"^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{5}$")


def source_root() -> tuple[Path, str]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next(row for row in registry["engines"] if row["id"] == "dolphin")
    commit = entry["source"]["commit"]
    root = ROOT / "engines" / "build" / "sources" / f"dolphin-{commit}"
    if not root.is_dir():
        raise SystemExit(f"pinned Dolphin source is absent: {root}")
    return root, commit


def valid_line(raw: str) -> str | None:
    line = raw.strip()
    if HEX_LINE.fullmatch(line) or ENCRYPTED_AR.fullmatch(line):
        return line.upper()
    # Dolphin accepts comments after a conventional hex pair, but stores the
    # original code token pair. Preserve only that exact parseable portion.
    before_comment = line.split("#", 1)[0].strip()
    if HEX_LINE.fullmatch(before_comment):
        return before_comment.upper()
    return None


def parse_ini(path: Path) -> list[dict[str, str]]:
    section = ""
    current_name = ""
    current_lines: list[str] = []
    current_valid = True
    cheats: list[dict[str, str]] = []

    def finish() -> None:
        nonlocal current_name, current_lines, current_valid
        if current_name and current_lines and current_valid:
            code = "+".join(current_lines)
            digest = hashlib.sha256(
                (path.stem + "\n" + code).encode("utf-8")
            ).hexdigest()[:24]
            cheats.append({
                "id": f"dolphin-{digest}",
                "name": current_name,
                "description": f"Dolphin {section} • {path.stem}",
                "code": code,
            })
        current_name = ""
        current_lines = []
        current_valid = True

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            finish()
            section = line[1:-1]
            continue
        if section not in ("ActionReplay", "Gecko"):
            continue
        if line.startswith("$"):
            finish()
            current_name = line[1:].strip()
            continue
        if not current_name or not line or line.startswith(("#", "*", "+")):
            continue
        parsed = valid_line(line)
        if parsed is None:
            current_valid = False
        else:
            current_lines.append(parsed)
    finish()
    # Several upstream INIs give two labels to the same serialized body. The
    # core compares the body, not the label, so presenting both would create
    # two switches that control one slot. Preserve the first upstream label.
    unique: dict[str, dict[str, str]] = {}
    for cheat in cheats:
        unique.setdefault(cheat["code"], cheat)
    return list(unique.values())


def main() -> None:
    source, commit = source_root()
    settings = source / "Data" / "Sys" / "GameSettings"
    games = []
    total = 0
    for ini in sorted(settings.glob("*.ini")):
        cheats = parse_ini(ini)
        if not cheats:
            continue
        games.append({"gameId": ini.stem, "cheats": cheats})
        total += len(cheats)
    document = {
        "schemaVersion": 1,
        "source": "https://github.com/dolphin-emu/dolphin",
        "sourceCommit": commit,
        "license": "GPL-2.0-or-later",
        "games": games,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False,
                                 separators=(",", ":")) + "\n",
                      encoding="utf-8")
    print(f"wrote {len(games)} Dolphin game IDs / {total} cheats to {OUTPUT}")


if __name__ == "__main__":
    main()
