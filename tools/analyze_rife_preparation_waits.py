#!/usr/bin/env python3
"""Summarize sampled pending-job stages; never infer GPU completion or a pass."""
import argparse
import json
from pathlib import Path
import re


def analyze(text, panel_period_ns):
    jobs = {}
    ready_jobs = []
    for line in text.splitlines():
        if 'RIFE preparation ready ' in line and 'readinessTiming=proof:' in line:
            timing = line.split('readinessTiming=', 1)[1].split(' ', 1)[0]
            values = {k: int(v) for k, v in re.findall(r'(\w+):(-?\d+)', timing)}
            fields = {k: int(v) for k, v in re.findall(r'(\w+)=(-?\d+)', line)}
            if all(k in values for k in ('proof', 'observedNs', 'dispatchedNs')):
                ready_jobs.append(dict(
                    proof=values['proof'], epoch=fields.get('epoch'),
                    left=fields.get('left'), readyCache=fields.get('readyCache'),
                    readyObservedAfterDispatchNs=values['observedNs']-values['dispatchedNs'],
                    nativeCallNs=values.get('nativeCallNs', -1),
                    gpuWorkNs=fields.get('gpuWorkNs'),
                    observationIsExactGpuCompletion=False))
            continue
        if 'jobTiming=proof:' not in line:
            continue
        identity = re.search(r'\s(\d+)\s+(\d+)\s+[A-Z]\s', line)
        timing = line.split('jobTiming=', 1)[1].split(' ', 1)[0]
        values = {k: int(v) for k, v in re.findall(r'(\w+):(-?\d+)', timing)}
        if not all(k in values for k in ('proof', 'observedNs', 'dispatchedNs', 'deadlineNs')):
            continue
        # Proof IDs restart with a process/transport. Include dispatch identity.
        key = (identity.group(1) if identity else 'unknown',
               values['proof'], values['dispatchedNs'])
        old = jobs.get(key)
        if old is None or values['observedNs'] > old['observedNs']:
            jobs[key] = values
    rows = []
    for (pid, proof, dispatched), values in sorted(jobs.items()):
        # EGL driver deadline = physical target - 2ms. Conservative admission
        # target = physical target - (panel period + 8ms), hence this delta.
        admission = values['deadlineNs'] - panel_period_ns - 6_000_000
        rows.append(dict(pid=pid, proof=proof, dispatchedNs=dispatched,
                         lastObservedPendingNs=values['observedNs'],
                         pendingAfterDispatchNs=values['observedNs'] - dispatched,
                         admissionBudgetFromDispatchNs=admission - dispatched,
                         pendingPastAdmissionNs=max(0, values['observedNs'] - admission),
                         queueNs=values.get('queueNs', -1),
                         dependencyWaitNs=values.get('dependencyWaitNs', -1),
                         nativeCallNs=values.get('nativeCallNs', -1)))
    return dict(qualificationPassed=False,
                limitation='Power-of-two sampled unavailability, not completion times or an unbiased latency distribution.',
                panelPeriodNs=panel_period_ns, jobs=rows, readyJobs=ready_jobs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--panel-period-ns', type=int, required=True)
    args = parser.parse_args()
    if args.panel_period_ns <= 0:
        parser.error('panel period must be positive')
    print(json.dumps(analyze(args.log.read_text(), args.panel_period_ns), indent=2))
