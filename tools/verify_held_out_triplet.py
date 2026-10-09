"""Verify overlapping captured pairs before using their middle as reference.

This does not solve outer-pair motion or qualify any synthesized image.
"""
import json
from pathlib import Path
from analyze_dense_flow_merging import read_dump


def verify(first, second):
    first,second=Path(first),Path(second)
    a=json.loads(Path(str(first)+".json").read_text())
    b=json.loads(Path(str(second)+".json").read_text())
    for record in (a,b):
        if not record["contiguousCapture"] or record["leftSequence"]<=0:
            raise ValueError("Not an explicitly armed contiguous capture")
        for field in ("Sequence","Submission"):
            if record["right"+field]!=record["left"+field]+1:
                raise ValueError("Skipped source "+field)
        if record["rightTimestampNs"]<=record["leftTimestampNs"]:
            raise ValueError("Invalid timestamp order")
    for field in ("Sequence","Submission","TimestampNs"):
        if a["right"+field]!=b["left"+field]:
            raise ValueError("Pairs do not share middle "+field)
    ma,pa=read_dump(first);mb,pb=read_dump(second)
    if ma!=mb or pa["currentFull"]!=pb["previousFull"]:
        raise ValueError("Middle bytes or capture geometry disagree")
    phase=(a["rightTimestampNs"]-a["leftTimestampNs"])/(b["rightTimestampNs"]-a["leftTimestampNs"])
    return {"reference_phase":phase,"sequence_ids":[a["leftSequence"],a["rightSequence"],b["rightSequence"]],
            "outer_flow_must_be_recomputed":True,"image_quality_qualified":False}


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first");parser.add_argument("second")
    args=parser.parse_args();print(json.dumps(verify(args.first,args.second),indent=2))
