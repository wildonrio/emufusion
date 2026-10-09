"""Summarize observed delivery intervals; never infer generated-image quality."""
import argparse,json,statistics
from pathlib import Path


def analyze(text):
    windows=[];periods=[]
    for block in text.split('\n---capture---\n'):
        lines=block.strip().splitlines()
        if lines and lines[0].isdigit() and int(lines[0])>0:periods.append(int(lines[0]))
        values=set()
        for line in lines[1:]:
            cols=line.split()
            if len(cols)==3 and all(v.isdigit() for v in cols):
                actual=int(cols[1])
                if 0<actual<(1<<63)-1:values.add(actual)
        if values:windows.append(sorted(values))
    if not periods or not windows:raise ValueError('No physical timestamp evidence')
    period=statistics.median(periods)
    # Only intervals actually observed within a ring window. Never invent
    # adjacency across a gap in collection, and count overlaps just once.
    edges=set()
    for values in windows:edges.update(zip(values,values[1:]))
    deltas=sorted(b-a for a,b in edges)
    if not deltas:raise ValueError('No observed intervals')
    histogram={}
    for delta in deltas:
        slots=int(delta/period+.5);histogram[str(slots)]=histogram.get(str(slots),0)+1
    return dict(image_quality_qualified=False,windows=len(windows),observed_intervals=len(deltas),
        nonoverlapping_window_boundaries=sum(not(set(a)&set(b)) for a,b in zip(windows,windows[1:])),
        reported_period_ns=period,period_range_ns=[min(periods),max(periods)],
        median_interval_ns=statistics.median(deltas),max_interval_ns=max(deltas),
        p99_interval_ns=deltas[min(len(deltas)-1,int(.99*len(deltas)))],
        intervals_over_one_and_half_scans=sum(d>period*1.5 for d in deltas),
        scan_slot_histogram=histogram,
        max_scan_lattice_residual_ns=max(abs(d-round(d/period)*period) for d in deltas))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();r=analyze(args.capture.read_text());args.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
