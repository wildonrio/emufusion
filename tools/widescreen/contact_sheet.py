#!/usr/bin/env python3
"""Tile harness screenshots into one image with names, for looking at many at once."""
import argparse
import os
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out')
    parser.add_argument('images', nargs='+')
    parser.add_argument('--cols', type=int, default=3)
    parser.add_argument('--scale', type=int, default=2)
    args = parser.parse_args()
    shots = [(os.path.basename(path), Image.open(path).convert('RGB')) for path in args.images]
    cell_w = max(image.width for _, image in shots) * args.scale + 6
    cell_h = max(image.height for _, image in shots) * args.scale + 20
    rows = (len(shots) + args.cols - 1) // args.cols
    sheet = Image.new('RGB', (cell_w * args.cols, cell_h * rows), (40, 40, 48))
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(shots):
        x = (index % args.cols) * cell_w
        y = (index // args.cols) * cell_h
        draw.text((x + 3, y + 3), name, fill=(255, 255, 0))
        sheet.paste(image.resize((image.width * args.scale, image.height * args.scale), Image.NEAREST),
                    (x + 3, y + 17))
    sheet.save(args.out)


if __name__ == '__main__':
    main()
