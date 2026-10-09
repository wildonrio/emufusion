"""Headless Thor RIFE staging benchmark; no APK installation or presentation."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import zipfile
from run_pyramid_gpu_probe import ADB, JAVA, ROOT, SDK


def verify_changing_content(log, context_count=2, adjacent=False, jobs=140):
    content=[tuple(map(int,line.split(',')[1:])) for line in log.splitlines() if line.startswith('CONTENT,')]
    if len(content)!=jobs or any(len(row)!=6 for row in content):
        raise ValueError('missing content trace')
    if {row[0] for row in content}!=set(range(1,jobs+1)):
        raise ValueError('duplicate or missing content sequence')
    if any(row[1] not in range(context_count) or row[2]!=((row[0]-1)%3 if adjacent else (row[0]-1)//2%2) for row in content):
        raise ValueError('incorrect pair or context')
    pairs=set(range(3 if adjacent else 2))
    signatures={pair:{row[3:] for row in content if row[2]==pair} for pair in pairs}
    if any(len(values)!=1 for values in signatures.values()): raise ValueError('unstable per-pair content')
    if len({next(iter(values))[2] for values in signatures.values()})!=len(pairs):
        raise ValueError('changing inputs produced identical output checksum')
    if any({row[2] for row in content if row[1]==slot}!=pairs for slot in range(context_count)):
        raise ValueError('each context must process both pairs')
    return {'jobs':jobs,'stable_per_pair':True,'distinct_pair_signatures':True,
            'both_pairs_per_context':True,'buffer_recycling_tested':False,
            'presentation_qualified':False,
            'signatures':{str(k):list(next(iter(v))) for k,v in signatures.items()}}


def validate_geometry(manifest, analysis_width, pipeline):
    width, height = manifest['width'], manifest['height']
    if (type(width) is not int or type(height) is not int or
            not 1 <= width <= 1920 or not 1 <= height <= 1080 or
            manifest['phase'] != .5 or manifest['format'] != 'RGBA8-bottom-up'):
        raise ValueError('unsupported input geometry/phase')
    analysis_width = width if analysis_width is None else analysis_width
    if (type(analysis_width) is not int or not 1 <= analysis_width <= width or
            analysis_width * height % width):
        raise ValueError('analysis geometry must preserve exact endpoint aspect ratio')
    if not pipeline and (width, height, analysis_width) != (256, 192, 256):
        raise ValueError('non-default geometry requires pipeline probe')
    return width, height, analysis_width


def earlier_refinement_param(data):
    """Diagnostic only: retain weights/graph but bypass the final residual updates.

    NCNN evaluates dependencies lazily. Scalar multiplication by one preserves
    the earlier cumulative flow and mask logits; the existing sigmoid remains.
    Validate exact locked nodes rather than silently patching another model.
    """
    expected = {
        'add_73': ['BinaryOp', 'add_73', '2', '1', '247', '326', '327'],
        'add_74': ['BinaryOp', 'add_74', '2', '1', '254', '330', '331'],
    }
    lines = data.decode().splitlines()
    seen = set()
    for i, line in enumerate(lines):
        fields = line.split()
        if len(fields) < 2 or fields[1] not in expected:
            continue
        name = fields[1]
        if fields != expected[name] or name in seen:
            raise ValueError('unexpected final refinement node: ' + name)
        seen.add(name)
        lines[i] = ' '.join(['BinaryOp', name, '1', '1', fields[4],
                             fields[6], '0=2', '1=1', '2=1.000000e+00'])
    if seen != set(expected):
        raise ValueError('missing final refinement nodes')
    if not any(line.split() == ['Sigmoid', 'sigmoid_8', '1', '1', '331', '332']
               for line in lines):
        raise ValueError('missing mask probability conversion')
    return ('\n'.join(lines) + '\n').encode()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--cached',action='store_true',help='Retained AHardwareBuffer path; no output-quality claim')
    parser.add_argument('--pipeline',action='store_true',help='Two independent private-output contexts; saturation only')
    parser.add_argument('--cpu-mask',choices=('38','80'),help='Thor-only diagnostic: temporary process cores 3-5 or core 7')
    parser.add_argument('--prewarm',action='store_true',help='Report bounded private model warm-up before starting source arrivals')
    parser.add_argument('--worker-cpu',action='store_true',help='Run on dedicated worker with device-derived lifetime affinity')
    parser.add_argument('--scoped-cpu-probe',action='store_true',help='Device-derived per-call affinity with restoration')
    parser.add_argument('--independent-inputs',action='store_true',help='Bounded one-frame source queue independent of inference slots')
    parser.add_argument('--paced',action='store_true',help='60Hz input arrivals for the pipeline probe')
    parser.add_argument('--analysis-width',type=int,help='Defaults to native input width; reduced analysis is diagnostic only')
    parser.add_argument('--following-inputs',type=Path,help='Following pair manifest; right endpoint used only in untimed output capture')
    parser.add_argument('--time-following',action='store_true',help='Use following source in timed jobs as well as capture')
    parser.add_argument('--alternate-inputs',type=Path,help='Alternate immutable endpoint pairs in the same pipeline')
    parser.add_argument('--contexts',type=int,choices=(1,2),default=2)
    parser.add_argument('--input-hz',type=int,choices=(30,60),default=60)
    parser.add_argument('--shared-model',action='store_true')
    parser.add_argument('--recycle-inputs',action='store_true',help='Upload fresh producer images per job; readback fixture invalidates performance acceptance')
    parser.add_argument('--no-upload-readback',action='store_true')
    parser.add_argument('--async-producer',action='store_true')
    parser.add_argument('--queued-producer',action='store_true')
    parser.add_argument('--adjacent-stream',action='store_true')
    parser.add_argument('--adjacent-queued',action='store_true')
    parser.add_argument('--jobs',type=int,choices=(140,620,2420),default=140)
    parser.add_argument('--hold-output',action='store_true')
    parser.add_argument('--verify-held',action='store_true')
    parser.add_argument('--profile-native',action='store_true')
    parser.add_argument('--fp16-probe',action='store_true',help='Explicit diagnostic arithmetic comparison; not qualification')
    parser.add_argument('--concat-probe',action='store_true',help='Diagnostic 8x8x1 concat dispatch')
    parser.add_argument('--warp-probe',action='store_true',help='Diagnostic 8x8x1 warp dispatch')
    parser.add_argument('--binary-probe',action='store_true',help='Diagnostic 8x8x1 binary-op dispatch')
    parser.add_argument('--interp-probe',action='store_true',help='Diagnostic 8x8x1 resize dispatch')
    parser.add_argument('--convolution-probe',choices=('winograd23','direct'),help='Diagnostic convolution path, native geometry unchanged')
    parser.add_argument('--dispatch-budget-probe',action='store_true',
                        help='Diagnostic build only: bounded 512K dispatch experiment, not qualification')
    parser.add_argument('--benchmark-apk',type=Path,help='Explicit benchmark build for optimized/debug comparisons')
    parser.add_argument('--earlier-refinement',action='store_true',
                        help='Diagnostic model ablation; bypass final residual refinement, never qualification')
    args=parser.parse_args()
    if args.time_following and not args.following_inputs:raise ValueError('timed following requires following inputs')
    if args.following_inputs and (not args.pipeline or args.alternate_inputs or args.recycle_inputs):
        raise ValueError('following capture requires simple non-recycling pipeline')
    if args.worker_cpu and (not args.pipeline or not args.benchmark_apk or args.cpu_mask or args.scoped_cpu_probe):
        raise ValueError('worker CPU requires pipeline, explicit APK and no competing affinity probe')
    if args.prewarm and not args.pipeline:
        raise ValueError('prewarm requires pipeline probe')
    if args.scoped_cpu_probe and (args.cpu_mask or not args.pipeline or not args.benchmark_apk):
        raise ValueError('scoped CPU requires pipeline and explicit APK without process mask')
    if args.interp_probe and (not args.pipeline or not args.benchmark_apk):
        raise ValueError('interp diagnostic requires pipeline and explicit APK')
    if args.binary_probe and (not args.pipeline or not args.benchmark_apk):
        raise ValueError('binary diagnostic requires pipeline and explicit APK')
    if args.warp_probe and (not args.pipeline or not args.benchmark_apk):
        raise ValueError('warp diagnostic requires pipeline and explicit APK')
    if args.concat_probe and (not args.pipeline or not args.benchmark_apk):
        raise ValueError('concat diagnostic requires pipeline and explicit APK')
    if args.convolution_probe and (not args.pipeline or not args.benchmark_apk):
        raise ValueError('convolution diagnostic requires pipeline and explicit APK')
    if args.fp16_probe and (not args.pipeline or not args.benchmark_apk):
        raise ValueError('FP16 diagnostic requires pipeline and explicit APK')
    if args.independent_inputs and (not args.adjacent_queued or not args.paced):
        raise ValueError('independent inputs require paced adjacent queue')
    if args.dispatch_budget_probe and (not args.pipeline or not args.profile_native or not args.benchmark_apk):
        raise ValueError('dispatch budget diagnostic requires pipeline, native profiling and explicit APK')
    if args.paced and not args.pipeline: raise ValueError('--paced requires --pipeline')
    if args.alternate_inputs and not args.pipeline: raise ValueError('alternate inputs require pipeline')
    if args.contexts!=2 and not args.pipeline: raise ValueError('context count requires pipeline')
    if args.input_hz!=60 and not args.paced: raise ValueError('input Hz requires paced pipeline')
    if args.shared_model and (not args.pipeline or args.contexts!=2): raise ValueError('shared model requires two pipeline contexts')
    if args.recycle_inputs and not args.shared_model: raise ValueError('recycle probe requires shared model')
    if args.no_upload_readback and not args.recycle_inputs: raise ValueError('readback option requires recycled inputs')
    if args.async_producer and not args.no_upload_readback: raise ValueError('async producer requires no upload readback')
    if args.queued_producer and not args.async_producer: raise ValueError('queued producer requires async producer')
    if args.adjacent_stream and (not args.async_producer or args.queued_producer or not args.alternate_inputs):
        raise ValueError('adjacent stream requires async producer and alternate inputs, without queued mode')
    if args.adjacent_queued and not args.adjacent_stream: raise ValueError('adjacent queued requires adjacent stream')
    if args.jobs!=140 and not args.adjacent_queued: raise ValueError('extended run requires adjacent queued mode')
    if args.hold_output and not args.adjacent_queued: raise ValueError('held output requires adjacent queued mode')
    if args.verify_held and not args.hold_output: raise ValueError('held verification requires held output')
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ, JAVA_HOME=str(JAVA.parent))
    def run(*cmd):
        result=subprocess.run([str(x) for x in cmd],env=env,text=True,capture_output=True,timeout=90)
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        return result.stdout
    experiment=ROOT/'experiments/rife-ncnn-vulkan-android'
    benchmark=experiment/'android-benchmark'
    manifest=json.loads((args.inputs/'manifest.json').read_text())
    width, height, args.analysis_width = validate_geometry(
        manifest, args.analysis_width, args.pipeline)
    def sha(data): return hashlib.sha256(data).hexdigest()
    identities={}
    for name in ('left.rgba','right.rgba'):
        data=(args.inputs/name).read_bytes()
        if len(data)!=width*height*4 or sha(data)!=manifest['inputs'][name]['sha256']: raise ValueError(name)
        (out/name).write_bytes(data)
    if args.alternate_inputs:
        alternate=json.loads((args.alternate_inputs/'manifest.json').read_text())
        if any(alternate[k]!=manifest[k] for k in ('width','height','phase','format')):
            raise ValueError('alternate geometry mismatch')
        if alternate['inputs']==manifest['inputs']: raise ValueError('alternate pair must differ')
        if args.adjacent_stream and alternate['inputs']['left.rgba']['sha256']!=manifest['inputs']['right.rgba']['sha256']:
            raise ValueError('adjacent source pairs must share the exact endpoint')
        for name in ('left.rgba','right.rgba'):
            data=(args.alternate_inputs/name).read_bytes()
            if len(data)!=width*height*4 or sha(data)!=alternate['inputs'][name]['sha256']: raise ValueError(name)
            (out/('alternate-'+name)).write_bytes(data)
        (out/'alternate-input-manifest.json').write_text(json.dumps(alternate,indent=2))
    if args.following_inputs:
        following=json.loads((args.following_inputs/'manifest.json').read_text())
        if any(following[k]!=manifest[k] for k in ('width','height','phase','format')) or following['endpoint_sequences'][1]!=manifest['endpoint_sequences'][1]+1:
            raise ValueError('following geometry/sequence mismatch')
        data=(args.following_inputs/'right.rgba').read_bytes()
        if len(data)!=width*height*4 or sha(data)!=following['inputs']['right.rgba']['sha256']:raise ValueError('following hash')
        (out/'following.rgba').write_bytes(data)
        (out/'following-input-manifest.json').write_text(json.dumps(following,indent=2))
    lock=json.loads((experiment/'upstream-lock.json').read_text())
    for spec in lock['components']['rifeV46Model']['files']:
        data=(benchmark/'build/upstream-cache'/spec['path']).read_bytes()
        if len(data)!=spec['bytes'] or sha(data)!=spec['sha256']: raise ValueError('model mismatch')
        name=Path(spec['path']).name; (out/name).write_bytes(data); identities[name]=sha(data)
    if args.earlier_refinement:
        model_path = out/'flownet.param'
        identities['original_flownet.param'] = identities['flownet.param']
        diagnostic = earlier_refinement_param(model_path.read_bytes())
        model_path.write_bytes(diagnostic)
        identities['flownet.param'] = sha(diagnostic)
    apk=args.benchmark_apk or benchmark/'app/build/outputs/apk/debug/app-debug.apk'
    apk_bytes=apk.read_bytes()
    identities['benchmark_apk']=sha(apk_bytes)
    with zipfile.ZipFile(io.BytesIO(apk_bytes)) as archive:
        data=archive.read('lib/arm64-v8a/librife_benchmark.so')
    diagnostic_model_build = b'EMUFUSION_RIFE_EARLIER_REFINEMENT_DIAGNOSTIC' in data
    if args.earlier_refinement != diagnostic_model_build:
        raise ValueError('earlier-refinement model and explicit diagnostic APK must match')
    if args.dispatch_budget_probe and b'EMUFUSION_RIFE_DISPATCH_PROBE' not in data:
        raise ValueError('APK does not contain the explicit dispatch diagnostic')
    if args.fp16_probe and b'EMUFUSION_RIFE_FP16_PROBE' not in data:
        raise ValueError('APK does not contain the explicit precision diagnostic')
    if args.concat_probe and b'EMUFUSION_RIFE_CONCAT_PROBE' not in data:
        raise ValueError('APK does not contain concat diagnostic')
    if args.warp_probe and b'EMUFUSION_RIFE_WARP_PROBE' not in data:
        raise ValueError('APK does not contain warp diagnostic')
    if args.binary_probe and b'EMUFUSION_RIFE_BINARY_PROBE' not in data:
        raise ValueError('APK does not contain binary diagnostic')
    if args.scoped_cpu_probe and b'EMUFUSION_RIFE_SCOPED_CPU_PROBE' not in data:
        raise ValueError('APK does not contain scoped CPU diagnostic')
    if args.interp_probe and b'EMUFUSION_RIFE_INTERP_PROBE' not in data:
        raise ValueError('APK does not contain interp diagnostic')
    if args.convolution_probe and b'EMUFUSION_RIFE_CONV_PROBE' not in data:
        raise ValueError('APK does not contain convolution diagnostic')
    (out/'librife_benchmark.so').write_bytes(data); identities['native_library']=sha(data)
    bridge=benchmark/'app/src/main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java'
    if args.cached and args.pipeline: raise ValueError('select one probe mode')
    class_name='NativeRifePipelineProbe' if args.pipeline else ('NativeRifeCachedProbe' if args.cached else 'NativeRifeHeadlessProbe')
    probe=ROOT/'tools/qa'/f'{class_name}.java'
    sources=[bridge,probe]
    if args.pipeline: sources.append(ROOT/'tools/qa/NativeRifeGpuInputs.java')
    for path in sources:
        (out/path.name).write_bytes(path.read_bytes()); identities[path.name]=sha(path.read_bytes())
    for name in ('classes','dex'): (out/name).mkdir()
    run(JAVA/'javac','-cp',SDK/'platforms/android-35/android.jar','-d',out/'classes',*sources)
    run(JAVA/'jar','cf',out/'classes.jar','-C',out/'classes','.')
    run(SDK/'build-tools/36.0.0/d8','--lib',SDK/'platforms/android-35/android.jar','--output',out/'dex',out/'classes.jar')
    run(JAVA/'jar','cf',out/'probe.jar','-C',out/'dex','classes.dex')
    remote=run(*ADB,'shell','mktemp -d /data/local/tmp/emufusion-rife-probe-XXXXXX').strip()
    (out/'remote.txt').write_text(remote+'\n')
    files=['probe.jar','librife_benchmark.so','flownet.param','flownet.bin','left.rgba','right.rgba']
    if args.following_inputs:files+=['following.rgba']
    if args.alternate_inputs: files+=['alternate-left.rgba','alternate-right.rgba']
    run(*ADB,'push',*[out/name for name in files],remote+'/')
    pushed=run(*ADB,'shell', 'sha256sum '+ ' '.join(shlex.quote(remote+'/'+n) for n in files))
    (out/'pushed-sha256.txt').write_text(pushed)
    observed={Path(line.split()[1]).name:line.split()[0] for line in pushed.splitlines()}
    if observed != {name:sha((out/name).read_bytes()) for name in files}:
        raise ValueError('device payload hash mismatch')
    command=f'CLASSPATH={remote}/probe.jar timeout 60 app_process -Demufusion.probe.timeFollowing={str(args.time_following).lower()} -Demufusion.probe.prewarm={str(args.prewarm).lower()} -Demufusion.probe.independentInputs={str(args.independent_inputs).lower()} -Demufusion.probe.width={width} -Demufusion.probe.height={height} -Djava.library.path={remote} / com.emufusion.rifebenchmark.{class_name} {remote}'
    if args.worker_cpu:
        command=command.replace('app_process ', 'app_process -Demufusion.probe.workerCpu=true ', 1)
    if args.cpu_mask:
        command=command.replace('timeout 60 app_process','timeout 60 taskset '+args.cpu_mask+' app_process',1)
    if args.pipeline: command+=f' {"paced" if args.paced else "unpaced"} {args.analysis_width}'
    if args.pipeline: command+=f' {"alternate" if args.alternate_inputs else "repeat"} {args.contexts} {args.input_hz}'
    if args.shared_model: command+=' shared'
    if args.recycle_inputs: command+=' recycle'
    if args.no_upload_readback: command+=' no-readback'
    if args.async_producer: command+=' async-producer'
    if args.queued_producer: command+=' queued'
    if args.adjacent_stream: command+=' adjacent'
    if args.adjacent_queued: command+=' adjacent-queued'
    if args.adjacent_queued: command+=f' {args.jobs}'
    if args.hold_output: command+=' hold-output'
    if args.verify_held: command+=' verify-held'
    if args.profile_native: command='EMUFUSION_RIFE_CPU_PROFILE=1 '+command
    if args.dispatch_budget_probe: command='EMUFUSION_RIFE_DISPATCH_PROBE=1 '+command
    if args.fp16_probe: command='EMUFUSION_RIFE_FP16_PROBE=1 '+command
    if args.concat_probe: command='EMUFUSION_RIFE_CONCAT_PROBE=1 '+command
    if args.warp_probe: command='EMUFUSION_RIFE_WARP_PROBE=1 '+command
    if args.binary_probe: command='EMUFUSION_RIFE_BINARY_PROBE=1 '+command
    if args.scoped_cpu_probe: command='EMUFUSION_RIFE_SCOPED_CPU_PROBE=1 '+command
    if args.interp_probe: command='EMUFUSION_RIFE_INTERP_PROBE=1 '+command
    if args.convolution_probe: command='EMUFUSION_RIFE_CONV_PROBE='+('2' if args.convolution_probe=='winograd23' else '0')+' '+command
    (out/'invocation.json').write_text(json.dumps({'command':command,
        'dispatch_budget_probe':args.dispatch_budget_probe,'profile_native':args.profile_native},indent=2))
    telemetry_command='cat /sys/class/kgsl/kgsl-3d0/devfreq/cur_freq /sys/class/kgsl/kgsl-3d0/throttling'
    def performance_snapshot():
        snapshot=subprocess.run(ADB+['shell',telemetry_command],env=env,text=True,
                                capture_output=True,timeout=10)
        return {'returncode':snapshot.returncode,'stdout':snapshot.stdout,'stderr':snapshot.stderr,
                'fields':['gpu_frequency_hz','driver_throttling_flag'],
                'continuous_measurement':False}
    (out/'performance-before.json').write_text(json.dumps(performance_snapshot(),indent=2))
    result=subprocess.run(ADB+['shell',command],env=env,text=True,capture_output=True,timeout=75)
    (out/'performance-after.json').write_text(json.dumps(performance_snapshot(),indent=2))
    (out/'device.log').write_text(result.stdout+result.stderr)
    (out/'identity.json').write_text(json.dumps(identities,indent=2))
    if result.returncode: raise RuntimeError(result.stdout+result.stderr)
    if args.prewarm:
        warm_rows=[line for line in (result.stdout+result.stderr).splitlines()
                   if line.startswith('PREWARM,')]
        expected_prefix=f'PREWARM,contexts={args.contexts},elapsedNs='
        if len(warm_rows)!=1 or not warm_rows[0].startswith(expected_prefix):
            raise ValueError('private prewarm completion not verified')
        warm_elapsed=int(warm_rows[0][len(expected_prefix):])
        if not 0 < warm_elapsed <= 5_000_000_000:
            raise ValueError('private prewarm exceeded bound')
    if args.scoped_cpu_probe or args.worker_cpu:
        log=result.stdout+result.stderr
        if 'RIFE_SCOPED_CPU,selected=' not in log or 'RIFE_SCOPED_CPU_RESTORED' not in log or 'RIFE_SCOPED_CPU_RESTORE_FAILED' in log:
            raise ValueError('scoped CPU application/restoration not verified')
        if args.worker_cpu and any(marker not in log for marker in (
                'WORKER_EXCEPTION_RESTORATION=verified',
                'WORKER_NORMAL_RESTORATION=verified')):
            raise ValueError('worker normal/exception affinity restoration not verified')
    if args.fp16_probe and 'RIFE_FP16_DIAGNOSTIC=enabled' not in result.stdout+result.stderr:
        raise ValueError('FP16 diagnostic activation not verified')
    if args.concat_probe and 'RIFE_CONCAT_DIAGNOSTIC=8x8x1' not in result.stdout+result.stderr:
        raise ValueError('concat diagnostic activation not verified')
    if args.warp_probe and 'RIFE_WARP_DIAGNOSTIC=8x8x1' not in result.stdout+result.stderr:
        raise ValueError('warp diagnostic activation not verified')
    if args.binary_probe and 'RIFE_BINARY_DIAGNOSTIC=8x8x1' not in result.stdout+result.stderr:
        raise ValueError('binary diagnostic activation not verified')
    if args.interp_probe and 'RIFE_INTERP_DIAGNOSTIC=8x8x1' not in result.stdout+result.stderr:
        raise ValueError('interp diagnostic activation not verified')
    if args.convolution_probe and 'RIFE_CONV_DIAGNOSTIC='+args.convolution_probe not in result.stdout+result.stderr:
        raise ValueError('convolution diagnostic activation not verified')
    if args.pipeline:
        if args.shared_model:
            caps=[json.loads(line.split('=',1)[1]) for line in result.stdout.splitlines() if line.startswith('MODEL_CAPABILITIES=')]
            if len(caps)!=1 or caps[0].get('modelOwnerCount')!=2: raise ValueError('model sharing not verified')
            survivor=[json.loads(line.split('=',1)[1]) for line in result.stdout.splitlines() if line.startswith('SURVIVING_MODEL_CAPABILITIES=')]
            if len(survivor)!=1 or survivor[0].get('modelOwnerCount')!=1: raise ValueError('shared model survival not verified')
        rows=[list(map(int,line.split(',')[1:])) for line in result.stdout.splitlines() if line.startswith('PIPE,')]
        if len(rows)!=args.jobs or f'PIPELINE_COMPLETED={args.jobs}' not in result.stdout: raise ValueError('incomplete pipeline')
        if args.recycle_inputs:
            hits=[int(line.split('=')[1]) for line in result.stdout.splitlines() if line.startswith('RECYCLED_IMPORT_HITS=')]
            if len(hits)!=1 or hits[0]<20: raise ValueError('producer reuse not observed')
            phases=[list(map(int,line.split(',')[1:])) for line in result.stdout.splitlines() if line.startswith('UPLOAD_PHASES,')]
            phases=[row for row in phases if row[0]>=3_840_000_000]
            if phases:
                phase_summary={name:{'median_ms':sorted(row[index]/1e6 for row in phases)[len(phases)//2],
                    'max_ms':max(row[index]/1e6 for row in phases)}
                    for index,name in enumerate(('draw_upload','swap','acquire','fence_and_log'),1)}
                (out/'upload-phases.json').write_text(json.dumps(phase_summary,indent=2))
        if args.alternate_inputs:
            content_summary=verify_changing_content(result.stdout,args.contexts,args.adjacent_stream,args.jobs)
            if args.recycle_inputs:
                content_summary.update(buffer_recycling_tested=True,recycled_import_hits=hits[0],
                                       fixture_readback_each_upload=not args.no_upload_readback,performance_qualified=False)
            (out/'changing-content.json').write_text(json.dumps(content_summary,indent=2))
        measured=sorted([row for row in rows if row[0]>20],key=lambda row:row[4])
        duration=(measured[-1][4]-measured[0][4])/1e9
        count=len(measured)
        if args.hold_output:
            held=[list(map(int,line.split(',')[1:])) for line in result.stdout.splitlines() if line.startswith('HELD_OUTPUTS,')]
            if len(held)!=1: raise ValueError('missing held output evidence')
            if args.verify_held and f'HELD_PIXELS_VERIFIED={args.jobs}' not in result.stdout:
                raise ValueError('incomplete held-pixel verification')
            (out/'held-output.json').write_text(json.dumps({'maximum_held':held[0][0],
                'late_ready':held[0][1],'lead_ns':66666668,'physical_presentation':False,
                'held_pixel_readback_tested':args.verify_held},indent=2))
        summary={'completed':args.jobs,'measured':count,'completion_rate_fps':(count-1)/duration,
                 'independent_inputs':args.independent_inputs,
                 'cpu_mask':args.cpu_mask,
                 'scoped_cpu_probe':args.scoped_cpu_probe,
                 'prewarm':args.prewarm,
                 'worker_cpu':args.worker_cpu,
                 'fp16_probe':args.fp16_probe,
                 'concat_probe':args.concat_probe,
                 'warp_probe':args.warp_probe,
                 'binary_probe':args.binary_probe,
                 'interp_probe':args.interp_probe,
                 'convolution_probe':args.convolution_probe,
                 'dispatch_budget_probe':args.dispatch_budget_probe,
                 'endpoint_width':width,'endpoint_height':height,
                 'analysis_width':args.analysis_width,'analysis_height':args.analysis_width*height//width,
                 'presentation_qualified':False,'two_model_contexts':args.contexts==2,'model_context_count':args.contexts,
                 'shared_model':args.shared_model,'loaded_model_count':1 if args.shared_model else args.contexts,
                 'recycled_inputs':args.recycle_inputs,'performance_qualified':False,
                 'upload_readback':args.recycle_inputs and not args.no_upload_readback,
                 'producer_fence_wait_on_cpu':args.recycle_inputs and not args.async_producer,
                 'queued_producer':args.queued_producer,
                 'adjacent_stream':args.adjacent_stream,
                 'adjacent_queued':args.adjacent_queued,
                 'median_gpu_ms':sorted(row[5]/1e6 for row in measured)[count//2],
                 'median_record_ms':sorted(row[3]/1e6 for row in measured)[count//2]}
        if args.paced:
            arrivals={int(parts[1]):int(parts[2]) for line in result.stdout.splitlines()
                      if line.startswith('ARRIVAL,') for parts in [line.split(',')]}
            if len(arrivals)!=args.jobs: raise ValueError('incomplete arrival trace')
            latencies=sorted((row[4]-arrivals[row[0]])/1e6 for row in measured)
            summary.update(input_hz=args.input_hz,arrival_to_completion_ms={'median':latencies[count//2],'p95':latencies[int(count*.95)-1],'max':latencies[-1]},
                           misses_16_667ms=sum(v>16.666667 for v in latencies),misses_33_333ms=sum(v>33.333334 for v in latencies))
        (out/'pipeline-timing.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))
        if 'POST_TIMING_CAPTURE=141' not in result.stdout: raise ValueError('missing post-timing capture')
        closes=[line.split(',')[1:] for line in result.stdout.splitlines() if line.startswith('INFLIGHT_CLOSE,')]
        if len(closes)!=1: raise ValueError('missing native drain evidence')
        (out/'inflight-close.json').write_text(json.dumps({'pending_at_close':closes[0][0]=='true',
            'close_ns':int(closes[0][1]),'native_closed':True,'app_transport_lifecycle_tested':False},indent=2))
        for name in ('generated.rgba','private-output-storage.rgba'):
            run(*ADB,'pull',remote+'/'+name,out/name)
        (out/'inference.json').write_text(json.dumps({'input_manifest':manifest,'generated_sha256':sha((out/'generated.rgba').read_bytes()),
            'following_input_manifest':following if args.following_inputs else None,
            'timed_jobs_use_following':args.time_following,
            'backend':'ncnn-vulkan-private-async-output','image_quality_qualified':False,'capture_excluded_from_timing':True},indent=2))
        return
    if args.cached:
        rows=[json.loads(line[len('CACHED='):]) for line in result.stdout.splitlines() if line.startswith('CACHED=')]
        if len(rows)!=1 or not rows[0].get('passed') or rows[0].get('measuredIterations')!=120:
            raise ValueError('cached run incomplete or failed')
        (out/'cached-timing.json').write_text(json.dumps(rows[0],indent=2))
        print(json.dumps(rows[0],indent=2))
        return
    run(*ADB,'pull',remote+'/generated.rgba',out/'generated.rgba')
    rows=[list(map(int,line.split(',')[1:])) for line in result.stdout.splitlines() if line.startswith('TIMING,')]
    if len(rows)!=150 or 'COMPLETED_CALLS=150' not in result.stdout: raise ValueError('incomplete run')
    times=sorted(row[4]/1e6 for row in rows[30:])
    summary={'warmup':30,'measured':120,'staging_end_to_end_ms':{'min':times[0],'median':times[60],'p95':times[113],'max':times[-1]},
             'presentation_qualified':False,'gpu_only_timing':False}
    (out/'timing.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))
    (out/'inference.json').write_text(json.dumps({'input_manifest':manifest,'generated_sha256':sha((out/'generated.rgba').read_bytes()),'backend':'ncnn-vulkan-headless','image_quality_qualified':False},indent=2))


if __name__=='__main__': main()
