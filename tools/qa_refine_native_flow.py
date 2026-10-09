"""Offline native-grid refinement experiment. Never used by the game renderer."""
import argparse
import json
import struct
from pathlib import Path
import numpy as np
from analyze_dense_flow_merging import read_dump


def sample(image, x, y):
    h,w=image.shape[:2]
    x=np.clip(x,0,w-1);y=np.clip(y,0,h-1)
    ix=np.floor(x).astype(int);iy=np.floor(y).astype(int)
    fx=(x-ix)[...,None];fy=(y-iy)[...,None]
    return ((image[iy,ix]*(1-fx)+image[iy,np.minimum(ix+1,w-1)]*fx)*(1-fy)+
            (image[np.minimum(iy+1,h-1),ix]*(1-fx)+image[np.minimum(iy+1,h-1),np.minimum(ix+1,w-1)]*fx)*fy)


def refine(source, peer, initial, shared_candidates=False):
    h,w=source.shape[:2];y,x=np.mgrid[:h,:w]
    def cost(flow):
        total=np.max(np.abs(source-sample(peer,x+flow[...,0],y+flow[...,1])),axis=2)
        # An edge-aware cross patch discourages isolated same-color matches.
        for dx,dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            guide=sample(source,x+dx,y+dy)
            weight=.125*np.exp(-np.max(np.abs(source-guide),axis=2)/20)
            total+=weight*np.max(np.abs(guide-sample(peer,x+dx+flow[...,0],y+dy+flow[...,1])),axis=2)
        total+=.05*np.linalg.norm(flow-initial,axis=2)
        outside=(x+flow[...,0]<0)|(x+flow[...,0]>w-1)|(y+flow[...,1]<0)|(y+flow[...,1]>h-1)
        return total+outside*255
    best=initial.copy();best_cost=cost(best)
    if shared_candidates:
        # Propose, never force, common motions from this outer-pair field.
        # This bridges local-search basins while retaining independent motion.
        vectors,counts=np.unique(np.round(initial).reshape(-1,2),axis=0,return_counts=True)
        for index in np.argsort(-counts,kind='stable')[:4]:
            candidate=np.broadcast_to(vectors[index],initial.shape)
            c=cost(candidate);take=c<best_cost-1e-5
            best[take]=candidate[take];best_cost[take]=c[take]
    zero=np.zeros_like(initial);z=cost(zero);take=z<best_cost
    best[take]=zero[take];best_cost=np.minimum(best_cost,z)
    for step,radius in [(1.,2),(.5,1),(.25,1)]:
        # Search integer correspondences explicitly before subpixel descent.
        # Keeping the seed's fractional offset can miss an exact integer match
        # and descend into another color basin before ever evaluating it.
        center=np.round(initial) if step==1. else best.copy()
        for dy in range(-radius,radius+1):
            for dx in range(-radius,radius+1):
                candidate=center+np.array([dx*step,dy*step]);c=cost(candidate)
                take=c<best_cost-1e-5
                best[take]=candidate[take];best_cost[take]=c[take]
    return np.round(best*256)/256


def multiscale(source, peer, levels=4, shared_candidates=False):
    """Outer-image-only coarse-to-fine search; no captured/reference flow."""
    pyramid=[(source,peer)]
    def half(image):
        h,w=image.shape[:2]
        padded=np.pad(image,((0,h%2),(0,w%2),(0,0)),mode='edge')
        return (padded[::2,::2]+padded[1::2,::2]+padded[::2,1::2]+padded[1::2,1::2])/4
    while len(pyramid)<levels and min(pyramid[-1][0].shape[:2])>=16:
        a,b=pyramid[-1];pyramid.append((half(a),half(b)))
    flow=None
    for a,b in reversed(pyramid):
        h,w=a.shape[:2]
        if flow is None:flow=np.zeros((h,w,2))
        else:
            oh,ow=flow.shape[:2];y,x=np.mgrid[:h,:w]
            flow=sample(flow,(x+.5)*ow/w-.5,(y+.5)*oh/h-.5)*np.array([w/ow,h/oh])
        flow=refine(a,b,flow,shared_candidates=shared_candidates)
    return flow


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path);parser.add_argument("output",type=Path)
    parser.add_argument("--multiscale",action="store_true",help="Recompute from outer images only")
    parser.add_argument("--shared-candidates",action="store_true",help="Evaluate common outer-pair motion proposals")
    parser.add_argument("--diagnostic-retain-confidence",action="store_true",
                        help="Ablation only: original confidence is NOT validation of refined vectors")
    args=parser.parse_args();meta,planes=read_dump(args.input)
    w,h=meta["history_width"],meta["history_height"];y,x=np.mgrid[:h,:w]
    def image(name):
        a,b,data=planes[name];return np.frombuffer(data,np.uint8).reshape(b,a,4)
    frames=[image("previousFull")[...,:3].astype(float),image("currentFull")[...,:3].astype(float)]
    flows=[];confidence=[]
    for d in range(2):
        packed=image(f"final{d}");ah,aw=packed.shape[:2]
        iy=((2*y+1)*ah)//(2*h);ix=((2*x+1)*aw)//(2*w)
        native=packed[iy,ix].astype(np.int32)
        raw=np.stack([native[...,0]*256+native[...,1],native[...,2]*256+native[...,3]],axis=2)
        raw=np.where(raw>=32768,raw-65536,raw)/256
        flows.append(multiscale(frames[1-d],frames[d],shared_candidates=args.shared_candidates) if args.multiscale else refine(frames[1-d],frames[d],raw,shared_candidates=args.shared_candidates))
        confidence.append(image(f"validated{d}")[iy,ix,2].astype(float))
    for d in range(2):
        flow=flows[d];qx=x+flow[...,0];qy=y+flow[...,1]
        cycle=np.linalg.norm(flow+sample(flows[1-d],qx,qy),axis=2)
        error=np.max(np.abs(frames[1-d]-sample(frames[d],qx,qy)),axis=2)
        # Do not promote previously weak/unsupported estimates to strong.
        if not args.diagnostic_retain_confidence:
            confidence[d]=np.minimum(confidence[d],255*np.clip((40-error)/32,0,1)*np.clip((2-cycle)/1.5,0,1))
        n=flow/meta["flow_limits"][0]
        rg=np.clip(np.round(128+127*np.sign(n)*np.sqrt(np.abs(n))),0,255).astype(np.uint8)
        valid=np.concatenate([rg,np.round(confidence[d])[...,None].astype(np.uint8),np.zeros((h,w,1),np.uint8)],axis=2)
        packed=np.round(flow*256).astype(np.int32)&65535
        raw=np.stack([packed[...,0]>>8,packed[...,0]&255,packed[...,1]>>8,packed[...,1]&255],axis=2).astype(np.uint8)
        planes[f"final{d}"]=(w,h,raw.tobytes());planes[f"validated{d}"]=(w,h,valid.tobytes())
    with args.output.open("xb") as out:
        out.write(struct.pack(">iffiiii",0x4c464431,*meta["flow_limits"],meta["locked_fps"],w,h,len(planes)))
        for name,(pw,ph,data) in planes.items():
            label=name.encode("ascii");out.write(struct.pack(">i",len(label))+label+struct.pack(">ii",pw,ph)+data)
    print(json.dumps({"offline_experiment":True,"runtime_timing_qualified":False,
                      "multiscale":args.multiscale,
                      "shared_candidates":args.shared_candidates,
                      "diagnostic_retain_confidence":args.diagnostic_retain_confidence,"output":str(args.output)}))


if __name__=="__main__":main()
