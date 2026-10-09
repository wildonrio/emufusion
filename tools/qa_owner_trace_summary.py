#!/usr/bin/env python3
"""Summarize completed owner-thread atrace slices; never a cadence pass gate."""
import argparse
import collections
import json
import re


def summarize(lines, owner_tid):
    stack = []
    spans = collections.defaultdict(list)
    unmatched_ends = 0
    owner = re.compile(r"-" + str(owner_tid) + r"\s")
    for line in lines:
        if not owner.search(line):
            continue
        match = re.search(r" (\d+\.\d+): tracing_mark_write: (.*)", line)
        if not match:
            continue
        timestamp = float(match[1])
        payload = match[2]
        if payload.startswith("B|"):
            fields = payload.split("|", 2)
            if len(fields) == 3:
                stack.append((timestamp, fields[2]))
        elif payload == "E" or payload.startswith("E|"):
            if not stack:
                unmatched_ends += 1
                continue
            start, name = stack.pop()
            spans[name].append((timestamp - start) * 1000)
    result = {}
    for name, values in spans.items():
        values.sort()
        result[name] = dict(count=len(values), totalMs=sum(values),
                            medianMs=values[len(values) // 2],
                            p95Ms=values[int(len(values) * .95)],
                            maxMs=values[-1],
                            overOne120HzScan=sum(v > 1000 / 120 for v in values))
    return dict(ownerTid=owner_tid, unmatchedEnds=unmatched_ends,
                unfinishedSpans=len(stack), spans=result,
                limitation="Completed wall-time slices only; not a smoothness or CPU-time proof.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace")
    parser.add_argument("owner_tid", type=int)
    args = parser.parse_args()
    with open(args.trace) as source:
        print(json.dumps(summarize(source, args.owner_tid), indent=2))
