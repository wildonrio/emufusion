#!/usr/bin/env python3
"""Compare raw RGBA output variants; similarity is not interpolation quality."""
import argparse
import json
from pathlib import Path


def compare(reference, candidate):
    if not reference or len(reference) != len(candidate) or len(reference) % 4:
        raise ValueError('RGBA byte sizes must be equal and nonempty')
    errors = [abs(a-b) for i, (a,b) in enumerate(zip(reference,candidate)) if i%4 != 3]
    pixels = len(reference)//4
    return {'pixels': pixels, 'rgb_mae_255': sum(errors)/len(errors),
            'rgb_max_error_255': max(errors),
            'rgb_components_over_8': sum(x>8 for x in errors),
            'different_pixels': sum(reference[i:i+3] != candidate[i:i+3] for i in range(0,len(reference),4)),
            'alpha_equal': reference[3::4] == candidate[3::4],
            'image_quality_qualified': False,
            'limitation': 'Variant comparison only; neither input is a ground-truth intermediate frame.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference',type=Path)
    parser.add_argument('candidate',type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.reference.read_bytes(),args.candidate.read_bytes()),indent=2))
