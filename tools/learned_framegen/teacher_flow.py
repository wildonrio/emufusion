"""Privileged teacher flows for training: the withheld real frame B against A and C.

usage: /opt/homebrew/bin/python3 tools/learned_framegen/teacher_flow.py ROOT [ROOT...]

For each triplet folder writes teacher.npy (float16, H x W x 5): flow B->A
(2), flow B->C (2) in pixels, and a reliability weight in [0, 1] (forward-
backward consistency of both flows). B is the frame at the generated time,
so these are exactly the displacements the network's fields must produce
(A source = x + flow_BA, C source = x + flow_BC). OpenCV DIS optical flow;
existing teacher files are kept.
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np


def gray(path):
    return cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)


def flow(dis, a, b):
    return dis.calc(a, b, None)


def warp(field, flow_xy):
    h, w = flow_xy.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(field, gx + flow_xy[..., 0], gy + flow_xy[..., 1], cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def consistency(forward, backward):
    """Weight where following forward then backward returns to the start."""
    back = warp(backward, forward)
    error = np.linalg.norm(forward + back, axis=2)
    limit = 0.75 + 0.05 * np.linalg.norm(forward, axis=2)
    h, w = forward.shape[:2]
    gx, gy = np.meshgrid(np.arange(w), np.arange(h))
    inside = ((gx + forward[..., 0] >= 0) & (gx + forward[..., 0] <= w - 1) &
              (gy + forward[..., 1] >= 0) & (gy + forward[..., 1] <= h - 1))
    return np.clip(1.5 - error / limit, 0, 1) * inside


def one(folder):
    folder = Path(folder)
    out = folder / 'teacher.npy'
    if out.exists():
        return 0
    a, b, c = (gray(folder / f'{k}.png') for k in 'ABC')
    if a.shape != b.shape or b.shape != c.shape:
        return 0
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    ba, ab = flow(dis, b, a), flow(dis, a, b)
    bc, cb = flow(dis, b, c), flow(dis, c, b)
    weight = np.minimum(consistency(ba, ab), consistency(bc, cb))
    np.save(out, np.concatenate([ba, bc, weight[..., None]], 2).astype(np.float16))
    return 1


def main():
    folders = []
    for root in sys.argv[1:]:
        folders += [m.parent for m in sorted(Path(root).glob('*/*/meta.json'))
                    if not m.parent.parent.name.startswith('_')]
    with ProcessPoolExecutor(8) as pool:
        done = sum(pool.map(one, folders, chunksize=8))
    print(f'teacher flows written for {done} of {len(folders)} triplets')


if __name__ == '__main__':
    main()
