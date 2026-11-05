#!/usr/bin/env python3
"""Pull a system's top 20 critic-rated ROMs from the Thor's library for host testing.

ROMs stay in the cache, never in git. Prefers a USA/World file when a title has several.

usage: pull_top20.py SYSTEM [--out DIR] [--dry-run]
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ADB = ['/tmp/claude-501/thor']
ROOT = Path(__file__).resolve().parents[2]


def words(text):
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", ' ', text)
    return re.sub(r'[^a-z0-9]+', ' ', text.lower().replace("'", '')).split()


def rank(name):
    """Lower is better: the region a player in English would want first."""
    lower = name.lower()
    for score, tag in enumerate(('(usa', '(world', '(u)', '(ue)', '(europe', '(e)')):
        if tag in lower:
            return score, len(name)
    return 9, len(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('system')
    parser.add_argument('--out')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    top = json.loads((ROOT / 'docs/widescreen/top20-by-critic.json').read_text())[args.system]
    folder = f'/sdcard/Games/{args.system}'
    listing = subprocess.run(ADB + ['shell', f'ls -1 {folder}'], capture_output=True, text=True).stdout
    files = [line.strip() for line in listing.splitlines() if line.strip()]
    by_words = {}
    for name in files:
        by_words.setdefault(' '.join(words(name.rsplit('.', 1)[0])), []).append(name)
    out = Path(args.out or os.path.expanduser(f'~/.cache/emufusion-widescreen/roms/{args.system}'))
    out.mkdir(parents=True, exist_ok=True)
    found, missing = [], []
    for game in top:
        want = words(game['title'])
        key = ' '.join(want)
        names = by_words.get(key)
        if not names:
            bare = [w for w in want if w != 'the']
            names = [name for other, group in by_words.items() for name in group
                     if [w for w in other.split() if w != 'the'] == bare]
        if names:
            found.append((game['title'], sorted(names, key=rank)[0]))
        else:
            missing.append(game['title'])
    for title, name in found:
        print(f'{title[:40]:40} {name[:60]}')
        if not args.dry_run and not (out / name).exists():
            subprocess.run(ADB + ['pull', f'{folder}/{name}', str(out / name)], capture_output=True, check=True)
    print(f'{len(found)} of {len(top)} found, {len(files)} files in the library')
    if missing:
        print('not in library or not matched:', '; '.join(missing))


if __name__ == '__main__':
    main()
