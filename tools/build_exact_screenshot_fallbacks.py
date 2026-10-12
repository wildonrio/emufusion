#!/usr/bin/env python3
"""Build exact-game screenshot fallbacks for wallpaper gaps.

This is deliberately a second-tier pipeline. It reads only entries still
reported as missing, requires an exact LaunchBox game/platform match, accepts
only media explicitly labelled ``Screenshot - Gameplay``, and writes to a
separate output tree so screenshot fallbacks can never be confused with real
wallpapers. The imported renderer uses ImageOps.fit to fill 1920x1080 without
stretching.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import importlib.util
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def load_pipeline(path: Path):
    spec = importlib.util.spec_from_file_location("emufusion_wallpaper_pipeline", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load wallpaper pipeline: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--missing-report", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    pipeline = load_pipeline(args.pipeline)
    missing = {
        row["file"] for row in read_tsv(args.missing_report)
        if row.get("status") == "missing-field"
    }
    rows = [row for row in read_tsv(args.manifest) if row["rom_path"] in missing]
    games: list[dict[str, str]] = []
    for row in rows:
        games.append({
            "title": row["title"],
            "system": row["system"],
            "file": row["rom_path"],
            "digest": row["digest"],
            "output": str(args.output_root / row["system"] / f"{row['digest']}.jpg"),
            "device_output": (
                "/storage/6432-6661/PegasusMedia/"
                f"game-wallpapers-screenshot-fallback/{row['system']}/{row['digest']}.jpg"
            ),
        })

    pipeline.apply_launchbox_file_aliases(pipeline.LAUNCHBOX_ZIP, games)
    exact, normalized, records = pipeline.load_launchbox_games(
        pipeline.LAUNCHBOX_ZIP, games
    )
    pipeline.match_games(games, exact, normalized, records)
    pipeline.IMAGE_TYPE_RANK = {"Screenshot - Gameplay": 0}
    images = pipeline.load_images(
        pipeline.LAUNCHBOX_ZIP,
        {game["launchbox_id"] for game in games if game.get("launchbox_id")},
    )
    candidates = [game for game in games if images.get(game.get("launchbox_id", ""))]
    print(f"exact gameplay screenshot candidates: {len(candidates)}/{len(games)}", flush=True)

    results: dict[str, dict[str, str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                pipeline.build_launchbox_game,
                game,
                images[game["launchbox_id"]],
            ): game
            for game in candidates
        }
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            game = futures[future]
            try:
                results[game["file"]] = future.result()
            except Exception as error:
                results[game["file"]] = {
                    "status": "error",
                    "source": "launchbox",
                    "source_path": repr(error),
                }
            if completed % 100 == 0:
                print(f"rendered {completed}/{len(candidates)}", flush=True)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "system", "title", "rom_path", "digest", "status", "source_type",
        "source_url", "source_size", "output", "device_output", "launchbox_id",
    )
    with args.report.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for game in games:
            result = results.get(game["file"], {})
            writer.writerow({
                "system": game["system"],
                "title": game["title"],
                "rom_path": game["file"],
                "digest": game["digest"],
                "status": result.get("status", "no-exact-gameplay-screenshot"),
                "source_type": result.get("source_type", ""),
                "source_url": result.get("source_url", ""),
                "source_size": result.get("source_size", ""),
                "output": game["output"] if result.get("status") == "built" else "",
                "device_output": game["device_output"] if result.get("status") == "built" else "",
                "launchbox_id": game.get("launchbox_id", ""),
            })
    built = sum(result.get("status") == "built" for result in results.values())
    print(f"built exact screenshot fallbacks: {built}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
