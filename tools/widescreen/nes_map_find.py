#!/usr/bin/env python3
"""Find an NES game's level map in RAM: memory whose bytes always predict the same 2x2 screen tiles.

A game with its level in RAM holds one byte per 16-pixel block, and each block value always draws
the same four tiles. So for each candidate address, row stride and screen offset, check that the
same byte always goes with the same four nametable tiles, on a screen with enough different blocks
that a chance match is unlikely. A hit still needs its block table found and a look in play.

usage: nes_map_find.py NAMETABLE.vram MEMORY [MEMORY...] [--min-blocks 6]
"""
import argparse


def score(mem, base, stride, nt, ox, oy, rows=6, cols=14):
    """Distinct blocks seen if the mapping is consistent, else 0."""
    seen = {}
    for row in range(rows):
        for col in range(cols):
            address = base + row * stride + col
            if address >= len(mem):
                return 0
            nr, nc = oy + row * 2, ox + col * 2
            if nr + 1 >= 30 or nc + 1 >= 32:
                continue
            tiles = (nt[nr * 32 + nc], nt[nr * 32 + nc + 1], nt[(nr + 1) * 32 + nc], nt[(nr + 1) * 32 + nc + 1])
            if seen.setdefault(mem[address], tiles) != tiles:
                return 0
    return len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('nametable')
    parser.add_argument('memory', nargs='+')
    parser.add_argument('--min-blocks', type=int, default=6)
    args = parser.parse_args()
    nametable = open(args.nametable, 'rb').read()
    results = []
    for page in (0, 0x400, 0x800, 0xC00):
        nt = nametable[page:page + 0x3C0]
        if len(nt) < 0x3C0 or len(set(nt)) < 8:
            continue
        for path in args.memory:
            mem = open(path, 'rb').read()
            for stride in (16, 32, 64, 128, 0xF0 // 15 * 15, 256):
                for base in range(len(mem) - stride * 6):
                    for oy in (0, 1):
                        for ox in (0, 1):
                            blocks = score(mem, base, stride, nt, ox, oy)
                            if blocks >= args.min_blocks:
                                results.append((blocks, path.rsplit('/', 1)[-1], hex(base), stride, ox, oy, hex(page)))
    results.sort(reverse=True)
    print(f'{len(results)} candidates')
    for result in results[:8]:
        print(' ', result)


if __name__ == '__main__':
    main()
