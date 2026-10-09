"""Locate severe errors in saved controlled-motion output, not an acceptance gate."""
import argparse,json
from pathlib import Path
import numpy as np

def analyze(reference,generated,margin=16):
    if reference.shape!=generated.shape or reference.shape!=(192,256,4):
        raise ValueError('Expected matching 256x192 RGBA images')
    error=np.max(abs(reference[:,:,:3].astype(int)-generated[:,:,:3].astype(int)),axis=2)
    mask=error>40
    mask[:16]=False;mask[176:]=False;mask[:,:margin]=False;mask[:,256-margin:]=False
    regions=[]
    for y in range(16,176,16):
        for x in range(margin,256-margin,16):
            tile=mask[y:y+16,x:min(x+16,256-margin)]
            if tile.any():
                regions.append({'x':x,'y_bottom_up':y,'severe_pixels':int(tile.sum()),
                    'max_error':int(error[y:y+16,x:min(x+16,256-margin)].max())})
    regions.sort(key=lambda r:r['severe_pixels'],reverse=True)
    return {'severe_pixels':int(mask.sum()),'tiles':regions,'image_quality_qualified':False,
            'coordinate_system':'RGBA bottom-up','threshold':40,'margin':margin}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('images',type=Path);args=p.parse_args()
    def read(name):return np.fromfile(args.images/name,dtype=np.uint8).reshape(192,256,4)
    result=analyze(read('reference.rgba'),read('old-false-round-2.rgba'))
    (args.images/'error-regions.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
