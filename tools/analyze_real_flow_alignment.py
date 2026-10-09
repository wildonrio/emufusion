"""Measure captured endpoint correspondence; not a ground-truth midpoint test."""
import argparse
import json
import math
from analyze_dense_flow_merging import read_dump


def analyze(path):
    meta, planes = read_dump(path)
    w, h = meta["history_width"], meta["history_height"]
    endpoints = [planes["previousFull"][2], planes["currentFull"][2]]

    def rgb(data, x, y):
        i = (min(h-1, max(0, y))*w + min(w-1, max(0, x)))*4
        return data[i:i+3]

    def bilinear(data, x, y):
        ix, iy = math.floor(x), math.floor(y)
        fx, fy = x-ix, y-iy
        return [sum(rgb(data, ix+dx, iy+dy)[c] *
                    (fx if dx else 1-fx) * (fy if dy else 1-fy)
                    for dy in (0, 1) for dx in (0, 1)) for c in range(3)]

    result = {"metadata": meta, "midpoint_correctness_proven": False, "directions": []}
    for direction in (0, 1):
        # 0 maps current->previous; 1 maps previous->current.
        source, peer = endpoints[1-direction], endpoints[direction]
        aw, ah, raw = planes[f"final{direction}"]
        valid = planes[f"validated{direction}"][2]
        groups = {name: [] for name in ("changed", "changed_supported", "changed_strong", "lightning_roi",
                                        "confidence_48_raw", "confidence_48_filled", "confidence_above_48_raw")}
        for y in range(h):
            for x in range(w):
                color = rgb(source, x, y)
                baseline = max(abs(a-b) for a,b in zip(color, rgb(peer,x,y)))
                if baseline < 20:
                    continue
                i = (((2*y+1)*ah//(2*h))*aw + (2*x+1)*aw//(2*w))*4
                dx = int.from_bytes(raw[i:i+2], "big", signed=True)/256
                dy = int.from_bytes(raw[i+2:i+4], "big", signed=True)/256
                warped = bilinear(peer, x+dx, y+dy)
                error = max(abs(a-b) for a,b in zip(color,warped))
                entry = (baseline, error, valid[i+2], math.hypot(dx,dy))
                groups["changed"].append(entry)
                if valid[i+2] >= 6:
                    groups["changed_supported"].append(entry)
                if valid[i+2] >= 48:
                    groups["changed_strong"].append(entry)
                if valid[i+2] == 48:
                    groups["confidence_48_raw"].append(entry)
                    # Final validated RG can be replaced by neighbour fill;
                    # its confidence no longer necessarily describes raw Q8.8.
                    limit=meta["flow_limits"][0]
                    vx,vy=[(v-128)/127 for v in valid[i:i+2]]
                    fx,fy=math.copysign(vx*vx*limit,vx),math.copysign(vy*vy*limit,vy)
                    filled=bilinear(peer,x+fx,y+fy)
                    filled_error=max(abs(a-b) for a,b in zip(color,filled))
                    groups["confidence_48_filled"].append((baseline,filled_error,48,math.hypot(fx,fy)))
                elif valid[i+2]>48:
                    groups["confidence_above_48_raw"].append(entry)
                # Explicit diagnostic ROI in this DS scene; not a general detector.
                if 150 <= x < 185 and 10 <= h-1-y < 180:
                    groups["lightning_roi"].append(entry)
        stats = {}
        for name, entries in groups.items():
            n=len(entries)
            stats[name] = {"pixels":n}
            if n:
                stats[name].update(mean_unwarped_error=sum(e[0] for e in entries)/n,
                                  mean_warped_error=sum(e[1] for e in entries)/n,
                                  warp_worse_pixels=sum(e[1]>e[0]+1 for e in entries),
                                  error_over_40_pixels=sum(e[1]>40 for e in entries),
                                  mean_motion_pixels=sum(e[3] for e in entries)/n)
        result["directions"].append(stats)
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump")
    args=parser.parse_args()
    print(json.dumps(analyze(args.dump), indent=2))
