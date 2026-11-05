#!/usr/bin/env python3
"""List a Game Gear sprite table from a video RAM dump, to find a game's HUD sprites.

Coordinates are the VDP's: the handheld showed x 48-207, y 24-167. Those are what
emufusion_ws_hud rules use.

usage: gg_sprites.py DUMP.vram [--sat 0x3F00]
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dump')
    parser.add_argument('--sat', type=lambda text: int(text, 0), default=0x3F00)
    args = parser.parse_args()
    vram = open(args.dump, 'rb').read()
    for index in range(64):
        y = vram[args.sat + index]
        if y == 0xD0:
            break
        x = vram[args.sat + 0x80 + index * 2]
        tile = vram[args.sat + 0x81 + index * 2]
        print(f'{index:2} x={x:3} y={y + 1:3} tile={tile:02X}')


if __name__ == '__main__':
    main()
