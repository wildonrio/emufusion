"""Correlate saved mixed8 fixture errors with nearby fields; not causal proof."""
import argparse,json
import numpy as np
from pathlib import Path

def raw_vectors(a):
    a=a.astype(np.int32)
    q=np.stack((a[...,0]*256+a[...,1],a[...,2]*256+a[...,3]),axis=-1)
    return np.where(q>=32768,q-65536,q)/256.

def validated_vectors(a,limit=38.4):
    dc=(a[...,:2].astype(float)-128)/127
    return np.sign(dc)*dc*dc*limit

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('images',type=Path);args=p.parse_args()
    def read(name,w,h):return np.fromfile(args.images/name,dtype=np.uint8).reshape(h,w,4)
    prefix='old-false-round-2'
    ref=read('reference.rgba',256,192);g=read(prefix+'.rgba',256,192)
    error=np.max(abs(g[...,:3].astype(int)-ref[...,:3].astype(int)),axis=2)
    mask=error>40;mask[:16]=False;mask[176:]=False;mask[:,:16]=False;mask[:,240:]=False
    fields={stage:[read(f'{prefix}-{stage}-{d}.rgba',192,144) for d in range(2)] for stage in ('raw','validated','filled')}
    raw=[raw_vectors(a) for a in fields['raw']]
    rows=[]
    for y,x in np.argwhere(mask):
        row={'x':int(x),'y_bottom_up':int(y),'error':int(error[y,x]),'directions':[]}
        for d in range(2):
            # Endpoint texture coordinate at the known midpoint correspondence.
            # Used for analysis ONLY; never fed into estimator or synthesis.
            motion=8 if y<96 else -8
            ex=x+(motion/2 if d==0 else -motion/2)
            fx=int(np.clip(np.floor((ex+.5)*192/256),0,191));fy=int(np.floor((y+.5)*144/192))
            expected=np.array([-motion if d==0 else motion,0])
            v=raw[d][fy,fx]
            row['directions'].append({'field_xy':[fx,fy],'raw':v.tolist(),
                'raw_error':float(np.linalg.norm(v-expected)),
                'validated_error':float(np.linalg.norm(validated_vectors(fields['validated'][d][fy,fx])-expected)),
                'filled_error':float(np.linalg.norm(validated_vectors(fields['filled'][d][fy,fx])-expected)),
                'validated_rgba':fields['validated'][d][fy,fx].tolist(),
                'filled_rgba':fields['filled'][d][fy,fx].tolist()})
        rows.append(row)
    result={'scope':'Nearest field samples at truth-derived correspondences; not actual shader sample replay',
        'pixels':len(rows),'both_raw_within_half_pixel':sum(all(d['raw_error']<=.5 for d in r['directions']) for r in rows),
        'either_raw_over_half_pixel':sum(any(d['raw_error']>.5 for d in r['directions']) for r in rows),'rows':rows}
    result['stage_counts']={stage:{
        'either_vector_over_half_pixel':sum(any(d[stage+'_error']>.5 for d in r['directions']) for r in rows),
        'either_confidence_below_48':sum(any(d[stage+'_rgba'][2]<48 for d in r['directions']) for r in rows)
        } for stage in ('validated','filled')}
    (args.images/'field-error-correlation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))

if __name__=='__main__':main()
