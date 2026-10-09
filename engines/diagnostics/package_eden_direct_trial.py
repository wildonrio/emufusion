#!/usr/bin/env python3
"""Package the isolated presentation experiment on the verified current APK."""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile
from package_spurs_trace import ROOT, SDK, digest, signature
from build_eden_direct_pacing_trial import LLVM

BASE = ROOT/'engines/build/candidates/frontend-rescan-quiescence-2026-09-09/emufusion-rescan-quiescence.apk'
BASE_SHA = '340803c0098cabda12b9b7c65273f0762b876c962a84f2db10e149a5b3390c3d'
SO = 'lib/arm64-v8a/liblucent_native_adapter_eden.so'
LOCK = 'assets/phase3-eden-source-lock.json'
INDEX = 'assets/phase3-engine-artifacts.json'
NOTE = 'assets/local-eden-direct-pacing-trial.json'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-dir',type=Path,required=True)
    p.add_argument('--output-name',default='apk')
    p.add_argument('--coupled-clock',action='store_true',help='Package coordinated guest clock/audio trial with accurate provenance')
    p.add_argument('--dispatch-only',action='store_true',help='Native callback dispatch only; no clock/audio/presentation scheduling changes')
    args = p.parse_args()
    candidate = args.candidate_dir.resolve()
    if args.dispatch_only and args.coupled_clock:p.error('choose one candidate profile')
    generator = 'build_eden_coupled_clock_trial.py' if args.coupled_clock else 'build_eden_direct_pacing_trial.py'
    purpose = ('Device-unqualified coordinated guest clock, fractional audio and native direct pacing trial; no FG qualification'
               if args.coupled_clock else 'Device-unqualified native direct pacing candidate; no frame generation or guest retiming')
    note_path = 'assets/local-eden-coupled-clock-trial.json' if args.coupled_clock else NOTE
    helpers = ['eden_direct_present_pacer.h']
    if args.coupled_clock:
        helpers += ['eden_coupled_clock.h','eden_coupled_clock_native.h','eden_clocked_audio.h']
        if (candidate/'eden_missed_present_trace.h').exists():
            helpers += ['eden_missed_present_trace.h']
            purpose += '; bounded missed-presentation trace (diagnostic overhead, not clean performance qualification)'
    if args.dispatch_only:
        generator='build_eden_coupled_clock_trial.py'
        helpers=[]
        purpose='Isolated immediate native presentation callback dispatch; unchanged guest/audio clock and native presentation scheduling; device unqualified'
        note_path='assets/local-eden-present-dispatch-trial.json'
        identities=json.loads((candidate/'source-identity.json').read_text())
        assert len(identities)==1 and identities[0]['path']=='src/video_core/renderer_vulkan/vk_present_manager.cpp'
    if Path(args.output_name).name != args.output_name: p.error('output-name must be one component')
    out = candidate/args.output_name
    if out.exists(): p.error('output already exists')
    assert digest(BASE.read_bytes()) == BASE_SHA
    so = candidate/'liblucent_native_adapter_eden.so'
    data = so.read_bytes()
    sha = digest(data)
    symbols = subprocess.check_output([str(LLVM/'llvm-nm'),'-D','--defined-only',str(so)],text=True).splitlines()
    with zipfile.ZipFile(BASE) as old:
        lock = json.loads(old.read(LOCK))
        assert all(any(s.endswith(' '+name) for s in symbols) for name in lock['artifact']['requiredExports'])
        lock['artifact'].update(sha256=sha,sizeBytes=len(data),stagedPath=str(so.relative_to(ROOT)),
            definedDynamicSymbolCount=len(symbols),note=purpose+'. Production staging unchanged.')
        lock['patches'].append({'path':'engines/diagnostics/'+generator,
            'sha256':digest((ROOT/'engines/diagnostics'/generator).read_bytes()),
            'role':'isolated-trial-generator','note':purpose})
        index=json.loads(old.read(INDEX))
        matches=[e for e in index['artifacts'] if e['engineId']=='eden']
        assert len(matches)==1
        matches[0]['sha256']=sha
        note=dict(baseApkSha256=BASE_SHA,trialLibrarySha256=sha,sourceIdentity=json.loads((candidate/'source-identity.json').read_text()),
            purpose=purpose,helperSha256={name:digest((candidate/name).read_bytes()) for name in helpers})
        updates={SO:data,LOCK:json.dumps(lock,indent=2).encode(),INDEX:json.dumps(index,indent=2).encode()}
        out.mkdir()
        with zipfile.ZipFile(out/'unsigned.apk','w') as new:
            for entry in old.infolist():
                if not signature(entry.filename):
                    new.writestr(entry,updates.get(entry.filename,old.read(entry.filename)))
            new.writestr(note_path,json.dumps(note,indent=2))
    bt=SDK/'build-tools/36.0.0'
    subprocess.run([str(bt/'zipalign'),'-f','4',str(out/'unsigned.apk'),str(out/'aligned.apk')],check=True)
    signed=out/'emufusion-direct-trial.apk'
    subprocess.run([str(bt/'apksigner'),'sign','--ks',str(ROOT/'android-companion/debug.keystore'),
        '--ks-pass','pass:android','--key-pass','pass:android','--ks-key-alias','androiddebugkey',
        '--out',str(signed),str(out/'aligned.apk')],check=True)
    subprocess.run([str(bt/'apksigner'),'verify','--verbose',str(signed)],check=True)
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(signed) as new:
        changed=[n for n in old.namelist() if not signature(n) and old.read(n)!=new.read(n)]
        added=[n for n in new.namelist() if n not in old.namelist() and not signature(n)]
        assert set(changed)==set(updates) and added==[note_path]
    # Retain the verified signed candidate, not two reproducible full-size APK
    # intermediates per experiment. Keep intermediates on failure for diagnosis.
    (out/'unsigned.apk').unlink()
    (out/'aligned.apk').unlink()
    print(json.dumps(dict(apk=str(signed),sha256=digest(signed.read_bytes()),changed=changed,added=added),indent=2))

if __name__=='__main__':main()
