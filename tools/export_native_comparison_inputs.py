"""Export endpoint-only inputs for backend comparison; never copy hidden truth."""
import argparse,hashlib,json
from pathlib import Path

def export(case,output):
    proof=json.loads((case/'native-proof.json').read_text())
    if abs(proof['reference_phase']-.5)>.001:raise ValueError('Unsupported phase')
    output.mkdir(parents=True,exist_ok=False)
    files={}
    for source,target in [('native-left.rgba','left.rgba'),('native-right.rgba','right.rgba')]:
        data=(case/source).read_bytes()
        if len(data)!=256*192*4:raise ValueError('Invalid RGBA size')
        (output/target).write_bytes(data)
        files[target]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    manifest={'width':256,'height':192,'format':'RGBA8-bottom-up','phase':proof['reference_phase'],
        'endpoint_sequences':[proof['sequence_ids'][0],proof['sequence_ids'][2]],
        'inputs':files,'reference_included':False,'image_quality_qualified':False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();print(json.dumps(export(a.case,a.output),indent=2))
