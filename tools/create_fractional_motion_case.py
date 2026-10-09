"""Analytic supersampled motion reference, independent of any interpolator."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def render(time, kind, scale=8):
    h,w=192,256
    y,x=np.mgrid[:h*scale,:w*scale].astype(float)
    x=(x+.5)/scale;y=(y+.5)/scale
    sx=x-3*time if kind=='camera' else x
    background=np.stack([100+60*np.sin(sx*.7),110+70*np.cos(y*.45),
                         110+50*np.sin(sx*.3+y*.3)],axis=2)
    if kind=='camera':
        object_mask=(sx>70)&(sx<110)&(y>45)&(y<145)
    elif kind=='occlusion':
        object_mask=(x>70+8*time)&(x<110+8*time)&(y>45)&(y<145)
    else: raise ValueError('unknown scene')
    background[object_mask]=[235,35,65]
    # Static HUD is deliberately distinct from the moving world.
    hud=(x>15)&(x<95)&(y>10)&(y<20)
    background[hud]=[250,240,30]
    rgb=background.reshape(h,scale,w,scale,3).mean((1,3))
    rgba=np.full((h,w,4),255,np.uint8)
    rgba[...,:3]=np.clip(np.round(rgb),0,255).astype(np.uint8)
    return rgba[::-1].copy()


def create(output,kind):
    output.mkdir(parents=True,exist_ok=False)
    inputs=output/'inputs';inputs.mkdir()
    manifest=dict(width=256,height=192,format='RGBA8-bottom-up',phase=.5,
                  endpoint_sequences=[0,2],reference_included=False,inputs={},
                  image_quality_qualified=False)
    for name,t in [('left',0),('right',1)]:
        data=render(t,kind).tobytes()
        (output/('native-'+name+'.rgba')).write_bytes(data)
        (inputs/(name+'.rgba')).write_bytes(data)
        manifest['inputs'][name+'.rgba']=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    (inputs/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (output/'withheld-reference.rgba').write_bytes(render(.5,kind).tobytes())
    (output/'analytic-reference.json').write_text(json.dumps(dict(kind=kind,supersample=8,
        reference_time=.5,endpoint_times=[0,1],camera_displacement=3 if kind=='camera' else 0,
        object_displacement=3 if kind=='camera' else 8,production_qualified=False),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path);p.add_argument('--kind',choices=['camera','occlusion'],required=True)
    a=p.parse_args();create(a.output,a.kind)
