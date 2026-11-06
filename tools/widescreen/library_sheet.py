#!/usr/bin/env python3
"""Contact sheet of the games library_triage.py shortlisted, two gameplay frames each, to look at.

usage: library_sheet.py SYSTEM ROM_DIR TRIAGE.json OUT_PREFIX [--per 24] [--min-real 0.9] [--skip N]
Prints each sheet's row order, so a row can be matched back to its game.
"""
import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from library_triage import LEADS, ROOT, SYSTEMS, script


def frames(system, roms, row):
    spec = SYSTEMS[system]
    out = tempfile.mkdtemp(prefix='ef-sheet-')
    try:
        subprocess.run(['nice', '-n', '10', sys.executable, str(ROOT / 'tools/widescreen/retro_play.py'), str(spec['core']),
                        str(Path(roms) / row['rom']), '--out', out, '--opt', spec['option'],
                        '--play', script(LEADS[row.get('way', 0)])], capture_output=True, timeout=240, cwd=str(ROOT))
        paths = sorted(Path(out).glob('*.png'))
        return [Image.open(paths[i]).convert('RGB').copy() for i in (30, 66) if i < len(paths)]
    except Exception:  # One bad game must not cost the sheet.
        return []
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('system', choices=SYSTEMS)
    parser.add_argument('roms')
    parser.add_argument('triage')
    parser.add_argument('prefix')
    parser.add_argument('--per', type=int, default=24)
    parser.add_argument('--min-real', type=float, default=0.9)
    parser.add_argument('--skip', type=int, default=0)
    args = parser.parse_args()
    rows = [r for r in json.loads(Path(args.triage).read_text())
            if r.get('real', 0) >= args.min_real and r.get('blank', 1) <= 0.5 and r.get('pairs', 0) >= 10]
    rows = sorted(rows, key=lambda r: r['rom'])[args.skip:]
    print(len(rows), 'games')
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        shots = list(pool.map(lambda r: frames(args.system, args.roms, r), rows))
    cell = (250, 150)
    for page in range((len(rows) + args.per - 1) // args.per):
        part = list(zip(rows, shots))[page * args.per:(page + 1) * args.per]
        columns = 3
        sheet = Image.new('RGB', (columns * 2 * cell[0], ((len(part) + columns - 1) // columns) * (cell[1] + 14)), (40, 40, 40))
        draw = ImageDraw.Draw(sheet)
        for index, (row, images) in enumerate(part):
            x, y = (index % columns) * 2 * cell[0], (index // columns) * (cell[1] + 14)
            draw.text((x + 2, y), f"{args.skip + page * args.per + index} {row['rom'][:44]} {row['real']:.2f}", fill=(255, 255, 0))
            for slot, image in enumerate(images[:2]):
                thumb = image.resize((cell[0] - 4, int(image.height * (cell[0] - 4) / image.width)), Image.BILINEAR)
                sheet.paste(thumb, (x + slot * cell[0], y + 14))
        target = f'{args.prefix}-{page:02d}.png'
        sheet.save(target)
        print(target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
