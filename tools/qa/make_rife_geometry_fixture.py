"""Synthetic motion workload with optional analytically rendered midpoint references.

References test this scene only; they cannot qualify game image quality.
"""
import argparse
import hashlib
import json
from pathlib import Path

def render(width, height, tick):
    """Integer-time scene: translating texture behind a separately moving square."""
    rgba = bytearray()
    for y in range(height):
        for x in range(width):
            shifted = (x + tick * 3) % 256
            square = 70 + tick * 4 <= x < 110 + tick * 4 and 60 <= y < 110
            rgba.extend((240, 60, 30, 255) if square else
                        (shifted, (y * 3) % 256,
                         ((shifted // 16 + y // 16) % 2) * 200, 255))
    return bytes(rgba)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--width', type=int, default=256)
    parser.add_argument('--height', type=int, default=240)
    parser.add_argument('--reference', action='store_true',
                        help='Render endpoints two ticks apart and retain the exact middle tick')
    args = parser.parse_args()
    if not 1 <= args.width <= 1920 or not 1 <= args.height <= 1080:
        parser.error('geometry must be within 1920x1080')
    args.output.mkdir(parents=True, exist_ok=False)
    step = 2 if args.reference else 1
    frames = [render(args.width, args.height, tick) for tick in range(2 * step + 1)]
    for index in range(2):
        out = args.output / str(index)
        out.mkdir()
        inputs = {}
        for name, tick in (('left.rgba', index * step),
                           ('right.rgba', (index + 1) * step)):
            data = frames[tick]
            (out / name).write_bytes(data)
            inputs[name] = {'sha256': hashlib.sha256(data).hexdigest()}
        manifest = {
            'width': args.width, 'height': args.height, 'phase': .5,
            'format': 'RGBA8-bottom-up', 'synthetic_workload': True,
            'image_quality_reference': False, 'inputs': inputs,
            'endpoint_sequences': [index + 1, index + 2],
            'game_quality_qualified': False,
        }
        if args.reference:
            reference = frames[index * step + 1]
            (out / 'reference.rgba').write_bytes(reference)
            manifest['synthetic_midpoint_reference'] = {
                'file': 'reference.rgba',
                'sha256': hashlib.sha256(reference).hexdigest(),
                'tick': index * step + 1,
                'scope': 'integer-time analytic scene only, not native game evidence',
            }
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
