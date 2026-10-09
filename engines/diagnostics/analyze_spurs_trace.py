#!/usr/bin/env python3
"""Validate the bounded taskset journal; absence of a trigger is never a pass."""
import argparse
import collections
import json
from pathlib import Path
import re


def analyze(log):
    messages = [line.split('SPURS_TRACE ', 1)[1] for line in log.splitlines()
                if 'SPURS_TRACE ' in line]
    ready = [line for line in messages if line.startswith('READY ')]
    target = [line for line in messages if line.startswith('TARGET ')]
    begin = [line for line in messages if line.startswith('BEGIN ')]
    end = [line for line in messages if line == 'END']
    records = []
    for line in messages:
        if not line.startswith('seq='):
            continue
        r = dict(re.findall(r'(\w+)=([^ ]+)', line))
        data = bytes.fromhex(r['data'])
        if len(data) != 128:
            raise ValueError('payload must contain exactly 128 bytes')
        r['invalid'] = (int(r['offset']) == 0 and int(r['length']) == 128 and
                        any(a & b for a, b in zip(data[:16], data[80:96])))
        records.append(r)
    result = {'readHookObserved': bool(ready), 'targetObserved': bool(target),
              'status': 'not_observed' if ready and target else 'unproven_liveness',
              'runtimeQualified': False, 'records': len(records)}
    if not begin and not end and not records:
        return result
    if len(begin) != 1 or len(end) != 1:
        raise ValueError('expected exactly one complete BEGIN/END dump')
    header = dict(re.findall(r'(\w+)=([^ ]+)', begin[0]))
    count, retained = int(header['count']), int(header['retained'])
    sequence = [int(r['seq']) for r in records]
    if retained > 256 or len(records) != retained or sequence != list(range(count-retained+1, count+1)):
        raise ValueError('missing, duplicate, or reordered records')
    if not records or records[-1]['outcome'] != '2' or not records[-1]['invalid']:
        raise ValueError('dump does not end in the declared invalid accepted read')
    result.update(status='invalid_accepted_read', firstSequence=sequence[0],
                  lastSequence=sequence[-1],
                  counts=dict(collections.Counter(r['kind'] + '/' + r['outcome'] for r in records)),
                  invalidRecords=[{k: r[k] for k in ('seq', 'kind', 'outcome', 'tid', 'pc', 'saved_res')}
                                  for r in records if r['invalid']])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.log.read_text()), indent=2))
