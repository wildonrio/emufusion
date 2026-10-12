#!/usr/bin/env python3
"""Convert the live missing-wallpaper audit into source-pipeline rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


ALIASES = {"megadrive": "genesis", "3ds": "n3ds"}


def system_from_metadata(name: str) -> str:
    stem = name.split(".metadata.pegasus.txt", 1)[0]
    if stem.startswith("99-emufusion-auto-"):
        system = stem.removeprefix("99-emufusion-auto-")
    elif "-" in stem:
        system = stem.split("-", 1)[1]
    else:
        system = stem
    return ALIASES.get(system, system)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.audit.open(encoding="utf-8", newline="") as stream:
        missing = [row for row in csv.DictReader(stream, delimiter="\t")
                   if row.get("status") == "missing-field"]
    fields = (
        "system", "title", "rom_path", "digest", "output", "device_output",
        "launchbox_id", "launchbox_title", "match_status", "status", "source",
        "source_type", "source_url", "source_path", "source_size",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in missing:
            system = system_from_metadata(row["metadata"])
            digest = hashlib.sha1(row["file"].encode("utf-8")).hexdigest()[:20]
            output = (Path("/Users/tyleryoung/Code/ayn-thor-work-20260731/artwork-pipeline/output") /
                      system / f"{digest}.jpg")
            writer.writerow({
                "system": system,
                "title": row["title"],
                "rom_path": row["file"],
                "digest": digest,
                "output": str(output),
                "device_output": f"/storage/6432-6661/PegasusMedia/game-wallpapers/{system}/{digest}.jpg",
                "match_status": "live-exact-rom-path",
            })
    print(f"missing wallpaper rows: {len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
