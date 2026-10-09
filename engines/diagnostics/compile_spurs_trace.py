#!/usr/bin/env python3
"""Compile one isolated diagnostic object; never mutate normal Ninja outputs."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--commands", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--without-trace", action="store_true")
parser.add_argument("--source-suffix", default="/Emu/Cell/SPUThread.cpp",
                    help="Unique translation-unit suffix in the pinned compile database")
parser.add_argument("--source-copy", type=Path,
                    help="Compile an explicit isolated source copy, retaining original quote-include lookup")
parser.add_argument("--include-overlay", type=Path,
                    help="Prepend an isolated source-header root; requires --source-copy")
args = parser.parse_args()
output = args.output.resolve()
if output.exists():
    parser.error("output already exists; choose a new isolated path")
entries = json.loads(args.commands.read_text())
matches = [e for e in entries if e["file"].endswith(args.source_suffix)]
if len(matches) != 1:
    parser.error("expected exactly one matching compile command")
entry = matches[0]
command = entry.get("arguments") or shlex.split(entry["command"])
isolated = []
index = 0
while index < len(command):
    word = command[index]
    if word in ("-o", "-MF", "-MT", "-MQ"):
        index += 2
        continue
    if word in ("-MD", "-MMD", "-MP"):
        index += 1
        continue
    isolated.append(word)
    index += 1
if args.source_copy is not None:
    source_copy = args.source_copy.resolve()
    if not source_copy.is_file() or isolated.count(entry["file"]) != 1:
        parser.error("source copy absent or original source argument ambiguous")
    isolated[isolated.index(entry["file"])] = str(source_copy)
    isolated += ["-iquote", str(Path(entry["file"]).parent)]
if args.include_overlay is not None:
    overlay = args.include_overlay.resolve()
    if args.source_copy is None or not overlay.is_dir():
        parser.error("include overlay requires source copy and an existing directory")
    source_copy.relative_to(overlay)
    isolated[1:1] = ["-I", str(overlay)]
if not args.without_trace:
    isolated += ["-DLUCENT_SPURS_TASKSET_TRACE=1", "-I" + str(Path(__file__).resolve().parent)]
isolated += ["-o", str(output)]
print("cwd:", entry["directory"], flush=True)
print(shlex.join(isolated), flush=True)
subprocess.run(isolated, cwd=entry["directory"], check=True)
