"""Known-motion textured diagnostic, not evidence of actual game-frame accuracy."""
import argparse,json
from pathlib import Path
import numpy as np
from analyze_dense_flow_merging import read_dump
from prepare_held_out_case import outer_planes,write_dump


def pan(image, pixels):
    """Integer camera pan with edge clamp; no interpolation-generated reference."""
    return image[:,np.clip(np.arange(image.shape[1])+pixels,0,image.shape[1]-1)].copy()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();meta,p=read_dump(args.capture)
    w,h,data=p['previousFull'];texture=np.frombuffer(data,np.uint8).reshape(h,w,4)
    a,b,c=pan(texture,0),pan(texture,2),pan(texture,4)
    args.output.mkdir(parents=True,exist_ok=False)
    write_dump(args.output/'outer-initial.bin',meta,outer_planes((w,h,a.tobytes()),(w,h,c.tobytes())))
    (args.output/'reference.rgba').write_bytes(b.tobytes())
    (args.output/'case.json').write_text(json.dumps({'reference_phase':.5,
        'controlled_translation_pixels':[0,2,4],'actual_game_sequence':False,
        'image_quality_qualified':False,'reference_excluded_from_input':True},indent=2)+'\n')


if __name__=='__main__':main()
