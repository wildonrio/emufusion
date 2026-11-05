#!/usr/bin/env python3
"""Flag frames whose revealed columns meet the original picture at a hard vertical edge.

A game that only refreshes the columns its console showed leaves old tiles beside them, and
the join is a straight line at the old screen edge. A real picture has no stronger line there
than anywhere else, so this finds the join without knowing what the correct picture is. The
strongest edges elsewhere in the frame set the bar, so a checkerboard floor does not trip it.
Still look at the flagged frames.

usage: seam_check.py --left 48 --right 208 [--slack 8] [--min-rows 0.45] FRAME.png...
"""
import argparse

from PIL import Image


def changes(image):
    """For each x, the share of rows whose pixel differs from the one to its left."""
    width, height = image.size
    pixels = image.load()
    share = [0.0] * width
    for x in range(1, width):
        share[x] = sum(pixels[x, y] != pixels[x - 1, y] for y in range(height)) / height
    return share


def seam(share, edge, slack, min_rows):
    """The strongest edge within slack of x if it stands far above the columns around it."""
    near = range(max(1, edge - slack), min(len(share), edge + slack + 1))
    best = max(near, key=lambda x: share[x])
    others = sorted(share[x] for x in range(1, len(share)) if x not in near)
    baseline = others[len(others) * 9 // 10] if others else 0.0
    return best if share[best] >= min_rows and share[best] >= baseline * 1.5 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left', type=int, default=48)
    parser.add_argument('--right', type=int, default=208)
    parser.add_argument('--slack', type=int, default=8)
    parser.add_argument('--min-rows', type=float, default=0.45)
    parser.add_argument('frames', nargs='+')
    args = parser.parse_args()
    flagged = []
    for path in args.frames:
        image = Image.open(path).convert('RGB')
        share = changes(image)
        found = [(name, seam(share, edge, args.slack, args.min_rows))
                 for name, edge in (('left', args.left), ('right', args.right))]
        found = [f'{name}@{x}' for name, x in found if x is not None]
        if found:
            flagged.append((path, found))
    print(f'{len(flagged)} of {len(args.frames)} frames with a seam')
    for path, found in flagged[:12]:
        print(' ', path.rsplit('/', 1)[-1], ' '.join(found))


if __name__ == '__main__':
    main()
