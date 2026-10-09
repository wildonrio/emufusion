"""Evaluate every verified overlapping triplet in one capture sequence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from analyze_dense_flow_merging import read_dump
from export_native_comparison_inputs import export
from verify_held_out_triplet import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    tools = Path(__file__).resolve().parent
    files = sorted(args.capture.glob('*.bin.json'),
                   key=lambda p: (p.name.rsplit('-', 1)[0], int(p.name.rsplit('-', 1)[1].split('.')[0])))
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    for left, right in zip(files, files[1:]):
        left, right = Path(str(left)[:-5]), Path(str(right)[:-5])
        try:
            proof = verify(left, right)
        except ValueError as error:
            rows.append({'first': left.name, 'second': right.name, 'rejected': str(error)})
            continue
        case = args.output / str(proof['sequence_ids'][1])
        case.mkdir()
        _, a = read_dump(left)
        _, b = read_dump(right)
        for name, plane in [('native-left.rgba', a['previousFull']),
                            ('native-right.rgba', b['currentFull']),
                            ('withheld-reference.rgba', a['currentFull'])]:
            (case/name).write_bytes(plane[2])
        (case/'native-proof.json').write_text(json.dumps(proof, indent=2))
        export(case, case/'inputs')
        for command in [
                [sys.executable, str(tools/'run_native_rife_comparison.py'), str(case/'inputs'), str(case/'rife')],
                [sys.executable, str(tools/'score_native_backend_comparison.py'), str(case), str(case/'rife')]]:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        scores = json.loads((case/'rife/comparison.json').read_text())
        row = {'middle_sequence': proof['sequence_ids'][1],
               'changing_pixels': scores['changing_pixels'],
               'scores': {name: {key: value for key, value in score.items() if key != 'spatial'}
                          for name, score in scores['scores'].items()}}
        rows.append(row)
        print(json.dumps(row), flush=True)
    (args.output/'sequence.json').write_text(json.dumps(rows, indent=2)+'\n')


if __name__ == '__main__':
    main()
