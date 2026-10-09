"""Exact-hash isolated graph experiment; preserve original graph and all weights."""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED='d5d23140a466df28d6f2286337a6a2bbbc745543a8c9432e717bf98c0e855ca6'
FOLDED='b7e284f3782c2b6b2f213a0c70b163f0555d2d79bca6d7282765f4ed716f0ed8'
FINAL_FINE='1c4e2be0f808a7fef5fa981f384518cc926b5ad6ce131bb7401e1be6a9c07ce1'


def convert(data):
    if hashlib.sha256(data).hexdigest() not in (EXPECTED,FOLDED,FINAL_FINE):
        raise ValueError('unreviewed graph; refusing pattern rewrite')
    lines=data.decode().splitlines();producers={};nodes=[]
    for line in lines[2:]:
        parts=line.split();ni,no=map(int,parts[2:4])
        node=dict(kind=parts[0],name=parts[1],inputs=parts[4:4+ni],
                  outputs=parts[4+ni:4+ni+no],params=parts[4+ni+no:])
        nodes.append(node)
        for blob in node['outputs']:producers[blob]=node
    replacements=[]
    for index,node in enumerate(nodes):
        if node['kind']!='GridSample':continue
        if node['params']!=['0=1','1=2','2=1','3=1']:raise ValueError('unsupported sampler')
        add=producers[node['inputs'][1]]
        if add['kind']!='BinaryOp' or add['params']!=['0=0']:raise ValueError('not normalized grid addition')
        cat=producers[add['inputs'][1]]
        if cat['kind']!='Concat' or cat['params']!=['0=0']:raise ValueError('not XY concatenation')
        divs=[producers[b] for b in cat['inputs']]
        for div,denom in zip(divs,('127.5','95.5')):
            if div['kind']!='BinaryOp' or div['params']!=['0=3','1=1','2='+denom]:
                raise ValueError('wrong coordinate normalization')
        slices=[producers[d['inputs'][0]] for d in divs]
        if slices[0] is not slices[1] or slices[0]['kind']!='Slice':raise ValueError('unpaired XY flow')
        flow=slices[0]['inputs'][0]
        lines[index+2]=' '.join(['rife.Warp',node['name'],'2','1',node['inputs'][0],flow,*node['outputs']])
        replacements.append(dict(layer=node['name'],flow=flow,image=node['inputs'][0]))
    if len(replacements)!=8:raise ValueError('expected eight warps')
    return ('\n'.join(lines)+'\n').encode(),replacements


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path)
    p.add_argument('output',type=Path);a=p.parse_args()
    data,changes=convert(a.source.read_bytes())
    with a.output.open('xb') as f:f.write(data)
    print(json.dumps(dict(replacements=changes,sha256=hashlib.sha256(data).hexdigest(),
                         qualified=False,weights_unchanged=True),indent=2))
