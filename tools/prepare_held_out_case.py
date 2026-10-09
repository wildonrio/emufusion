"""Prepare leakage-free outer-pair inputs for the offline local-flow prototype.

Adjacent captured flow is deliberately discarded: it depends on the hidden
frame. Zero flow and a neutral confidence ceiling are initialization, not proof.
"""
import argparse,json,struct
from pathlib import Path
import numpy as np
from analyze_dense_flow_merging import read_dump
from verify_held_out_triplet import verify


def outer_planes(previous,current):
    w,h,a=previous
    if current[:2]!=(w,h):raise ValueError("Endpoint geometry mismatch")
    planes={"previousFull":previous,"currentFull":current}
    for name,full in [("previousHalf",previous),("currentHalf",current)]:
        image=np.frombuffer(full[2],np.uint8).reshape(h,w,4)
        # Replay does not consume these pyramids; retain a truthful downsample.
        small=image[::2,::2].copy()
        planes[name]=(small.shape[1],small.shape[0],small.tobytes())
    for d in range(2):
        planes[f"final{d}"]=(w,h,bytes(w*h*4))
        planes[f"validated{d}"]=(w,h,bytes([128,128,255,0])*(w*h))
        planes[f"seed{d}"]=(1,1,bytes(4))
    return planes


def write_dump(path,meta,planes):
    with Path(path).open("xb") as out:
        out.write(struct.pack(">iffiiii",0x4c464431,*meta["flow_limits"],meta["locked_fps"],
                              meta["history_width"],meta["history_height"],len(planes)))
        for name,(w,h,data) in planes.items():
            label=name.encode();out.write(struct.pack(">i",len(label))+label+struct.pack(">ii",w,h)+data)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first",type=Path);parser.add_argument("second",type=Path)
    parser.add_argument("output",type=Path);args=parser.parse_args()
    proof=verify(args.first,args.second)
    meta,a=read_dump(args.first);_,b=read_dump(args.second)
    planes=outer_planes(a["previousFull"],b["currentFull"])
    args.output.mkdir(parents=True,exist_ok=False)
    write_dump(args.output/"outer-initial.bin",meta,planes)
    (args.output/"reference.rgba").write_bytes(a["currentFull"][2])
    proof.update(initialization="zero flow; confidence ceiling only; not validated",
                 source_resolution=[meta["history_width"],meta["history_height"]],
                 adjacent_flow_used=False,reference_excluded_from_input=True)
    (args.output/"case.json").write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof))


if __name__=="__main__":main()
