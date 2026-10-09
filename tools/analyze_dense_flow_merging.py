#!/usr/bin/env python3
"""Analyze exact transport merging in LFD1 diagnostic dumps; no timing claims."""
import argparse
import json
import struct
from pathlib import Path


def read_dump(path):
    data = memoryview(Path(path).read_bytes())
    offset = 0

    def take(n):
        nonlocal offset
        if n < 0 or offset + n > len(data):
            raise ValueError("Truncated flow dump")
        result = data[offset:offset+n]
        offset += n
        return result

    def integer():
        return struct.unpack(">i", take(4))[0]

    if integer() != 0x4C464431:
        raise ValueError("Expected LFD1 dump")
    limits = struct.unpack(">ff", take(8))
    fps, width, height, count = [integer() for _ in range(4)]
    if not (0 < width <= 16384 and 0 < height <= 16384 and 0 < count <= 32):
        raise ValueError("Invalid dump geometry/count")
    planes = {}
    for _ in range(count):
        size = integer()
        if not 0 < size <= 128:
            raise ValueError("Invalid plane name")
        name = bytes(take(size)).decode("ascii")
        w, h = integer(), integer()
        if name in planes or not (0 < w <= 16384 and 0 < h <= 16384):
            raise ValueError("Invalid/duplicate plane")
        planes[name] = (w, h, bytes(take(w*h*4)))
    if offset != len(data):
        raise ValueError("Trailing dump data")
    full = {"previousFull", "currentFull"}
    if full.intersection(planes):
        if not full.issubset(planes) or any(planes[n][:2] != (width, height) for n in full):
            raise ValueError("Full endpoints must both match native history dimensions")
    return {"history_width": width, "history_height": height, "locked_fps": fps,
            "flow_limits": limits}, planes


def merging(validated, raw, width, height):
    """Nearest sample at each source-pixel center, as in compact compute."""
    if width <= 0 or height <= 0:
        raise ValueError("Positive source grid required")
    if validated[:2] != raw[:2]:
        raise ValueError("Raw/validated dimensions differ")
    w, h, valid = validated
    raw_bytes = raw[2]
    counts = {1: 0, 2: 0, 4: 0, 8: 0}
    def sample(x, y):
        # Integer form of floor((source coordinate + .5)*analysis/source).
        sx, sy = ((2*x+1)*w)//(2*width), ((2*y+1)*h)//(2*height)
        i = (sy*w+sx)*4
        return valid[i:i+4] + raw_bytes[i:i+4]
    def region(x, y, side):
        if x >= width or y >= height:
            return
        first = sample(x, y)
        if x+side <= width and y+side <= height and all(
                sample(xx, yy) == first for yy in range(y, y+side)
                for xx in range(x, x+side)):
            counts[side] += 1
        else:
            for dy in (0, side//2):
                for dx in (0, side//2):
                    region(x+dx, y+dy, side//2)
    for y in range(0, height, 8):
        for x in range(0, width, 8):
            region(x, y, 8)
    nodes = sum(counts.values())
    return {"nodes_by_side": counts, "nodes": nodes, "pixels": width*height,
            "geometry_reduction": width*height/nodes,
            "covered_pixels": sum(side*side*n for side, n in counts.items())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    args = parser.parse_args()
    metadata, planes = read_dump(args.dump)
    result = {"metadata": metadata, "source_grid": [args.width, args.height],
              "instrumented_image_diagnostic": True, "timing_qualified": False}
    for direction in range(2):
        result[str(direction)] = merging(planes[f"validated{direction}"],
                                        planes[f"final{direction}"], args.width, args.height)
    print(json.dumps(result, indent=2))
