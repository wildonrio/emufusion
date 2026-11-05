#!/usr/bin/env python3
"""List a Mega Drive sprite table from a video RAM dump, to find a game's HUD sprites.

usage: md_sprites.py DUMP.vram [--sat 0xF800]
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dump')
    parser.add_argument('--sat', type=lambda text: int(text, 0), default=0xF800)
    args = parser.parse_args()
    vram = open(args.dump, 'rb').read()
    # BlastEm's video RAM is byte-addressed in 68000 order.
    word = lambda address: vram[address & 0xFFFF] << 8 | vram[(address + 1) & 0xFFFF]
    index = 0
    for _ in range(80):
        entry = args.sat + index * 8
        y = word(entry) & 0x1FF
        size_link = word(entry + 2)
        tile_word = word(entry + 4)
        x = word(entry + 6) & 0x1FF
        width = ((size_link >> 10 & 3) + 1) * 8
        height = ((size_link >> 8 & 3) + 1) * 8
        print(f'{index:2} x={x - 128:4} y={y - 128:4} {width}x{height} tile={tile_word & 0x7FF:03X} pal={tile_word >> 13 & 3} pri={tile_word >> 15}')
        index = size_link & 0x7F
        if not index:
            break


if __name__ == '__main__':
    main()
