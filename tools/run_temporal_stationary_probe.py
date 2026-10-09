"""Offscreen candidate validation only; no APK install or display wake."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from run_pyramid_gpu_probe import ROOT,JAVA,SDK,ADB,run
from evaluate_rife_temporal_stationary import runtime_available_candidate


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('case',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--scale',type=int,choices=(1,2,4,6),default=1,
                   help='Nearest-expanded input fixture; preserve native neighborhood spacing')
    p.add_argument('--uniform-stress',action='store_true',
                   help='Replace fixture RGB with uniform sources and erroneous output, forcing all taps')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    meta=json.loads((a.case/'rife/inference.json').read_text());m=meta['input_manifest']
    h,w=m['height'],m['width']
    following=a.case.parent/str(int(a.case.name)+1)
    fm=json.loads((following/'rife/inference.json').read_text())['input_manifest']
    if fm['endpoint_sequences'][1]!=m['endpoint_sequences'][1]+1: raise ValueError('lookahead sequence')
    files={'left':(a.case/'native-left.rgba',m['inputs']['left.rgba']['sha256']),
           'right':(a.case/'native-right.rgba',m['inputs']['right.rgba']['sha256']),
           'following':(following/'native-right.rgba',fm['inputs']['right.rgba']['sha256']),
           'generated':(a.case/'rife/generated.rgba',meta['generated_sha256'])}
    arrays={}
    for name,(path,sha) in files.items():
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('input hash')
        arrays[name]=np.frombuffer(raw,np.uint8).reshape(h,w,4).copy()
    if a.uniform_stress:
        for name,array in arrays.items():array[...,:3]=128 if name=='generated' else 42
    expected,mask=runtime_available_candidate(*(arrays[k][...,:3].astype(float) for k in ('left','right','following','generated')))
    expected_rgba=arrays['generated'].copy();expected_rgba[...,:3]=expected
    def expand(array):return np.repeat(np.repeat(array,a.scale,axis=0),a.scale,axis=1)
    expected_rgba=expand(expected_rgba)
    for name,array in arrays.items():(out/(name+'.rgba')).write_bytes(expand(array).tobytes())
    shader=ROOT/'tools/qa/temporal_stationary_guard.glsl'
    (out/'guard.glsl').write_bytes(shader.read_bytes())
    (out/'composite.glsl').write_bytes((ROOT/'tools/qa/temporal_stationary_composite.glsl').read_bytes())
    for folder in ('classes','dex'):(out/folder).mkdir()
    run(JAVA/'javac','-cp',SDK/'platforms/android-35/android.jar','-d',out/'classes',ROOT/'tools/qa/DensePyramidDeviceTest.java',ROOT/'tools/qa/TemporalStationaryDeviceTest.java')
    run(JAVA/'jar','cf',out/'classes.jar','-C',out/'classes','.')
    run('env','JAVA_HOME='+str(JAVA.parent),SDK/'build-tools/36.0.0/d8','--lib',SDK/'platforms/android-35/android.jar','--output',out/'dex',out/'classes.jar')
    run(JAVA/'jar','cf',out/'probe.jar','-C',out/'dex','classes.dex')
    remote=run(*ADB,'shell','mktemp -d /data/local/tmp/emufusion-stationary-XXXXXX').strip()
    (out/'remote.txt').write_text(remote+'\n')
    run(*ADB,'push',out/'probe.jar',out/'guard.glsl',out/'composite.glsl',*[out/(k+'.rgba') for k in files],remote+'/')
    result=subprocess.run(ADB+['shell',f'CLASSPATH={remote}/probe.jar timeout 30 app_process / com.thorium.preview.game.TemporalStationaryDeviceTest {remote} {w*a.scale} {h*a.scale} {a.scale}'],text=True,capture_output=True,timeout=40)
    (out/'device.log').write_text(result.stdout+result.stderr);result.check_returncode()
    for i in (0,1):run(*ADB,'pull',remote+f'/output-{i}.rgba',out/f'output-{i}.rgba')
    for i in (0,1):run(*ADB,'pull',remote+f'/split-{i}.rgba',out/f'split-{i}.rgba')
    actual=(out/'output-1.rgba').read_bytes();disabled=(out/'output-0.rgba').read_bytes()
    report=dict(gpu_matches_reference=actual==expected_rgba.tobytes(),
                split_matches_reference=(out/'split-1.rgba').read_bytes()==expected_rgba.tobytes(),
                split_passthrough=(out/'split-0.rgba').read_bytes()==disabled,
                no_lookahead_passthrough=disabled==expand(arrays['generated']).tobytes(),
                native_size=[w,h],surface_size=[w*a.scale,h*a.scale],scale=a.scale,
                uniform_stress=a.uniform_stress,
                uploaded_hashes={k:hashlib.sha256((out/(k+'.rgba')).read_bytes()).hexdigest() for k in files},
                corrected_pixels=int(mask.sum()),shader_sha256=hashlib.sha256(shader.read_bytes()).hexdigest(),
                input_hashes={k:sha for k,(_,sha) in files.items()},
                presentation_qualified=False,artifact_free_qualified=False)
    (out/'result.json').write_text(json.dumps(report,indent=2))
    print(result.stdout);print(json.dumps(report,indent=2))
    if not all(report[k] for k in ('gpu_matches_reference','no_lookahead_passthrough','split_matches_reference','split_passthrough')):raise ValueError('GPU/reference mismatch')


if __name__=='__main__':main()
