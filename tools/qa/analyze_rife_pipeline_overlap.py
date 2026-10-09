#!/usr/bin/env python3
"""Analyze observed prepare/retirement overlap, not physical presentation."""
import argparse
import json
from pathlib import Path
from statistics import median


def analyze(text):
    rows = [list(map(int, line.split(',')[1:])) for line in text.splitlines()
            if line.startswith('PIPE,')]
    rows.sort(key=lambda row: row[0])
    samples = []
    for previous, current in zip(rows, rows[1:]):
        if current[0] <= 20 or current[0] != previous[0] + 1:
            continue
        # Completion is host-observed fence retirement, not a GPU end timestamp.
        samples.append((current[2] - previous[4]) / 1e6)
    if not samples:
        raise ValueError('no adjacent measured jobs')
    result = {'adjacent_pairs': len(samples),
            'prepare_before_previous_retirement': sum(x < 0 for x in samples),
            'median_start_minus_previous_retirement_ms': median(samples),
            'min_start_minus_previous_retirement_ms': min(samples),
            'max_start_minus_previous_retirement_ms': max(samples),
            'physical_presentation_qualified': False,
            'caveat': 'Host retirement may lag GPU completion; overlap is not proof of simultaneous GPU work.'}
    uploads = [list(map(int, line.split(',')[1:])) for line in text.splitlines()
               if line.startswith('QUEUED_UPLOAD_PHASES,')][20:]
    if uploads:
        result['queued_upload_samples'] = len(uploads)
        for index, name in ((1, 'draw'), (2, 'swap')):
            values = sorted(row[index] / 1e6 for row in uploads)
            result[name + '_ms'] = {'median': median(values),
                                   'p95': values[int((len(values)-1)*.95)],
                                   'max': max(values)}
    readiness = [list(map(int, line.split(',')[1:])) for line in text.splitlines()
                 if line.startswith('INPUT_READINESS,')]
    readiness = [row for row in readiness if row[0] > 20]
    if readiness:
        values = sorted(row[3] / 1e6 for row in readiness)
        result['input_readiness'] = {'samples': len(values),
            'jobs_retried': sum(row[2] > 0 for row in readiness),
            'retry_count': sum(row[2] for row in readiness),
            'median_elapsed_ms': median(values), 'max_elapsed_ms': max(values)}
    stages = [list(map(int, line.split(',')[1:])) for line in text.splitlines()
              if line.startswith('INPUT_STAGES,')]
    stages = [row for row in stages if row[0] > 20]
    if stages:
        result['input_stages'] = {}
        for index, name in ((1, 'upload_to_acquired'), (2, 'import'), (3, 'acquired_to_prepare')):
            values = sorted(row[index] / 1e6 for row in stages)
            result['input_stages'][name] = {'median_ms': median(values),
                'p95_ms': values[int((len(values)-1)*.95)], 'max_ms': max(values)}
    gpu_stages = [list(map(float, line.split(',')[1:])) for line in text.splitlines()
                  if line.startswith('RIFE_GPU_PHASES,')]
    if gpu_stages:
        result['gpu_stage_sample_count'] = len(gpu_stages)
        result['gpu_stage_median_ms'] = {
            name: median(row[index]/1e6 for row in gpu_stages)
            for index,name in ((1,'input_conversion'),(2,'model'),(3,'output_and_proof'))}
    arrivals = {int(parts[1]):int(parts[2]) for line in text.splitlines()
                if line.startswith('ARRIVAL,') for parts in [line.split(',')]}
    if arrivals:
        measured = [row for row in rows if row[0]>20]
        if any(row[0] not in arrivals for row in measured):
            raise ValueError('missing measured arrival')
        result['backlog_windows'] = []
        for offset in range(0,len(measured),100):
            chunk=measured[offset:offset+100]
            latency=[(row[4]-arrivals[row[0]])/1e6 for row in chunk]
            elapsed=(chunk[-1][4]-chunk[0][4])/1e9
            result['backlog_windows'].append({
                'first_sequence':chunk[0][0],'last_sequence':chunk[-1][0],
                'first_latency_ms':latency[0],'last_latency_ms':latency[-1],
                'max_latency_ms':max(latency),'late_at_66_667_ms':sum(x>66.666668 for x in latency),
                'completion_fps':(len(chunk)-1)/elapsed if elapsed>0 else None})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.log.read_text()), indent=2))
