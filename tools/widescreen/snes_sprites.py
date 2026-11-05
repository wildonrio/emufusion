#!/usr/bin/env python3
"""List SNES sprites from an OAM dump (trace core), to find a game's HUD sprites."""
import sys

oam = open(sys.argv[1], 'rb').read()
for n in range(128):
    x, y, tile, attr = oam[n * 4:n * 4 + 4]
    high = oam[512 + n // 4] >> (n % 4 * 2) & 3
    x |= (high & 1) << 8
    if x >= 352:
        x -= 512
    if y >= 224 or y == 0:
        continue
    print(f'{n:3} x={x:4} y={y:3} tile={tile | (attr & 1) << 8:03X} pal={attr >> 1 & 7} pri={attr >> 4 & 3} big={high >> 1}')
