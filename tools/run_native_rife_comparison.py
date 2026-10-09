"""Offline pinned RIFE inference on endpoint-only exports; no reference input."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import hashlib
import zipfile
import sys
import types

import numpy as np
import torch


def load_experimental_network(archive, warplayer, temporary):
    """Host-only v4.25 loader; leaves hash-pinned v4.6 verifier untouched."""
    with zipfile.ZipFile(archive) as package:
        for name in ('train_log/IFNet_HDv3.py','train_log/flownet.pkl'):
            package.extract(name,temporary)
    model=types.ModuleType('model');model.__path__=[];sys.modules['model']=model
    def load(name,path):
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module
        spec.loader.exec_module(module)
        return module
    load('model.warplayer',warplayer)
    module=load('emufusion_experimental_ifnet',temporary/'train_log/IFNet_HDv3.py')
    network=module.IFNet().eval()
    checkpoint=torch.load(temporary/'train_log/flownet.pkl',map_location='cpu',weights_only=True)
    if not checkpoint or not all(isinstance(k,str) and k.startswith('module.') for k in checkpoint):
        raise ValueError('experimental checkpoint key mismatch')
    normalized={k.removeprefix('module.'):v for k,v in checkpoint.items()}
    normalized={k:v for k,v in normalized.items() if not k.startswith(('teacher.','caltime.'))}
    network.load_state_dict(normalized,strict=True)
    return network


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path)
    parser.add_argument('output', type=Path)
    models = parser.add_mutually_exclusive_group()
    models.add_argument('--experimental-425-lite-archive', type=Path,
                        help='Host-only isolated comparison; never changes the app model')
    models.add_argument('--experimental-425-archive', type=Path,
                        help='Host-only full v4.25 comparison')
    parser.add_argument('--analysis-scale',type=float,choices=[.5,1.0,2.0],default=1.0)
    parser.add_argument('--block-scales',type=float,nargs=4,choices=(.5,1.,2.,4.,8.),
                        help='Host-only pinned v4.6 per-stage analysis experiment')
    parser.add_argument('--ensemble',action='store_true',help='Host-only pinned v4.6 bidirectional model ensemble')
    parser.add_argument('--dump-motion',action='store_true',help='Save final flow, blend mask and warped endpoints for offline diagnosis')
    parser.add_argument('--export-trace',action='store_true',help='Export isolated fixed-geometry TorchScript conversion input; not an Android model')
    parser.add_argument('--fold-residual-scale',action='store_true',help='Experimental copied-network constant-scale folding')
    parser.add_argument('--endpoint-analysis-width',type=int,choices=[128],
                        help='Host-only v4.6 coarse-flow isolation; reconstruct full-size endpoints without safety heuristics')
    args = parser.parse_args()
    if args.block_scales and (args.analysis_scale!=1 or args.experimental_425_archive or
                             args.experimental_425_lite_archive or args.endpoint_analysis_width):
        raise ValueError('explicit stage scales require plain full-size pinned v4.6')
    if args.ensemble and (args.experimental_425_archive or args.experimental_425_lite_archive):
        raise ValueError('ensemble comparison is scoped to pinned v4.6')
    if args.endpoint_analysis_width and (args.experimental_425_archive or args.experimental_425_lite_archive or args.analysis_scale != 1.0):
        raise ValueError('coarse endpoint isolation requires default pinned v4.6 scales')
    root = Path(__file__).resolve().parents[1]
    verifier_path = root / 'experiments/rife-ncnn-vulkan-android/tools/verify_v46_conversion.py'
    spec = importlib.util.spec_from_file_location('rife_verifier', verifier_path)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    manifest = verifier.load_json(args.inputs / 'manifest.json')
    if (manifest['format'] != 'RGBA8-bottom-up' or manifest['phase'] != 0.5
            or manifest['reference_included'] is not False
            or set(manifest['inputs']) != {'left.rgba', 'right.rgba'}):
        raise ValueError('unsupported endpoint manifest')
    width, height = manifest['width'], manifest['height']
    if width != 256 or height != 192:
        raise ValueError('this comparison is qualified only for 256x192 inputs')
    tensors = []
    for name in ('left.rgba', 'right.rgba'):
        path = args.inputs / name
        verifier.verify_file(path, manifest['inputs'][name])
        pixels = np.fromfile(path, np.uint8).reshape(height, width, 4)
        # Network sees conventional top-down RGB. Return raw output bottom-up.
        rgb = pixels[::-1, :, :3].astype(np.float32).copy() / 255.0
        tensors.append(torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0))
    lock = verifier.load_json(verifier.DEFAULT_LOCK)
    original = lock['components']['practicalRifeV46Original']
    archive_spec = original['trainedModelArchive']
    archive = verifier.DEFAULT_CACHE / archive_spec['path']
    verifier.verify_file(archive, archive_spec)
    verifier.verify_archive_members(archive, archive_spec['members'])
    version = '4.6'
    if args.experimental_425_lite_archive or args.experimental_425_archive:
        archive = args.experimental_425_lite_archive or args.experimental_425_archive
        expected = ('e84366c23e0eb1a637a55aad2e4f3442ec2bf4c388043b4aabbf590be289e6e8'
                    if args.experimental_425_lite_archive else
                    'e63d481b7ae5d4a4e6ad7ac5b410ff78f3bf7be3b51b2e38ca8152747abde5b4')
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise ValueError('experimental model archive hash mismatch')
        with zipfile.ZipFile(archive) as package:
            members=[]
            for name in ('train_log/IFNet_HDv3.py','train_log/flownet.pkl'):
                data=package.read(name)
                members.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        archive_spec=dict(sha256=expected,checkpointPath='train_log/flownet.pkl',members=members)
        version = '4.25-lite' if args.experimental_425_lite_archive else '4.25'
    support = original['runtimeSupportFiles'][0]
    warplayer = verifier.DEFAULT_CACHE / support['path']
    verifier.verify_file(warplayer, support)
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    with tempfile.TemporaryDirectory(prefix='emufusion-rife-network-') as temporary:
        network = (load_experimental_network(archive,warplayer,Path(temporary))
                   if version.startswith('4.25') else
                   verifier.load_original_network(archive,archive_spec,warplayer,Path(temporary)))
        folded_blocks=0
        if args.fold_residual_scale:
            if version!='4.6':raise ValueError('folding is scoped to pinned v4.6')
            from fold_rife_residual_scale import fold
            network,folded_blocks=fold(network)
        started = time.monotonic()
        with torch.inference_mode():
            inputs = torch.cat(tensors, 1)
            if args.endpoint_analysis_width:
                # Match the Android endpoint resize: half-pixel bilinear,
                # then round to RGB8 before model normalization.
                inputs = torch.nn.functional.interpolate(inputs,size=(96,128),mode='bilinear',align_corners=False)
                inputs = torch.floor(inputs*255+.5)/255
            scales = [8,4,2,1]
            if version == '4.25-lite':
                inputs = torch.nn.functional.pad(inputs,(0,(-width)%128,0,(-height)%128))
                scales = [32,16,8,4,1]
            elif version == '4.25':
                inputs = torch.nn.functional.pad(inputs,(0,(-width)%64,0,(-height)%64))
                scales = [16,8,4,2,1]
            scales = [scale/args.analysis_scale for scale in scales]
            if args.block_scales:scales=list(args.block_scales)
            # Lowest-resolution block requires a multiple of four after resize.
            alignment=int(max(scales)*4)
            inputs=torch.nn.functional.pad(inputs,(0,(-inputs.shape[3])%alignment,
                                                   0,(-inputs.shape[2])%alignment))
            flows, mask, merged = network(inputs, 0.5, scales, False, True, args.ensemble)
            if args.dump_motion and args.endpoint_analysis_width:
                raise ValueError('motion dump currently requires full-size endpoints')
            if args.endpoint_analysis_width:
                from model.warplayer import warp
                flow = torch.nn.functional.interpolate(flows[-1],size=(height,width),mode='bilinear',align_corners=False)*2
                mask = torch.nn.functional.interpolate(mask,size=(height,width),mode='bilinear',align_corners=False)
                reconstructed = warp(tensors[0],flow[:,:2])*mask + warp(tensors[1],flow[:,2:])*(1-mask)
                merged[-1] = reconstructed
        elapsed = time.monotonic() - started
        output = merged[-1][0,:,:height,:width].permute(1, 2, 0).numpy()
        trace_errors=None
        if args.export_trace:
            if version!='4.6' or args.endpoint_analysis_width or args.ensemble:
                raise ValueError('trace export supports plain full-size pinned v4.6 only')
            class Export(torch.nn.Module):
                def __init__(self,net):
                    super().__init__();self.net=net
                def forward(self,a,b):
                    flow,blend,frames=self.net(torch.cat((a,b),1),.5,scales,False,True,False)
                    return flow[-1],blend,frames[-1]
            wrapper=Export(network).eval()
            # Both inputs already have the model-required padded dimensions.
            pair=(inputs[:,:3],inputs[:,3:6])
            with torch.inference_mode():
                traced=torch.jit.trace(wrapper,pair,check_trace=False)
                trace_path=args.output/'model-fixed.pt';traced.save(str(trace_path))
                loaded=torch.jit.load(str(trace_path))
                expected=wrapper(*pair);actual=loaded(*pair)
                trace_errors=[float((a-b).abs().max()) for a,b in zip(expected,actual)]
                if max(trace_errors)>1e-6:raise ValueError('exported trace differs from original')
        if args.dump_motion:
            from model.warplayer import warp
            final_flow=flows[-1]
            warped_left=warp(inputs[:,:3],final_flow[:,:2])
            warped_right=warp(inputs[:,3:6],final_flow[:,2:])
            def array(tensor):
                return tensor[0,:,:height,:width].permute(1,2,0).numpy()
            np.savez_compressed(args.output/'motion.npz',flow=array(final_flow),
                                mask=array(mask),left=array(warped_left),right=array(warped_right))
    if output.shape != (height, width, 3) or not np.isfinite(output).all():
        raise ValueError('invalid network output')
    rgba = np.full((height, width, 4), 255, np.uint8)
    rgba[:, :, :3] = np.clip(np.round(output[::-1] * 255), 0, 255).astype(np.uint8)
    target = args.output / 'generated.rgba'
    target.write_bytes(rgba.tobytes())
    result = {'backend': 'pinned-original-rife-v'+version+'-pytorch-cpu',
              'torch_version': torch.__version__, 'input_manifest': manifest,
              'model_archive_sha256': archive_spec['sha256'],
              'analysis_scale':args.analysis_scale,'block_scales':scales,
              'folded_residual_blocks':folded_blocks,
              'ensemble':args.ensemble,
              'endpoint_analysis_width':args.endpoint_analysis_width,
              'reconstruction':'unmodified-flow-mask' if args.endpoint_analysis_width else 'original-network',
              'padded_input_size':[int(inputs.shape[3]),int(inputs.shape[2])],
              'generated_sha256': verifier.digest_file(target)[1],
              'host_single_inference_seconds': elapsed,
              'android_performance_qualified': False, 'image_quality_qualified': False}
    if args.dump_motion:
        result['motion_dump']=dict(path='motion.npz',sha256=verifier.digest_file(args.output/'motion.npz')[1],
                                   orientation='top-down',flow_units='pixels',colors='RGB float 0..1')
    if args.export_trace:
        result['experimental_trace']=dict(path='model-fixed.pt',sha256=verifier.digest_file(trace_path)[1],
                                          max_errors=trace_errors,fixed_geometry=True,
                                          android_graph_qualified=False)
    (args.output / 'inference.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
