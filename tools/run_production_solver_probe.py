"""Headless probe extracting real production solver methods, not rewriting passes."""
import argparse,json,re,subprocess
from pathlib import Path
from run_pyramid_gpu_probe import ROOT,JAVA,SDK,ADB,run

def method(source,name):
    start=source.index(name);brace=source.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--shift',type=int,default=4,choices=(0,2,4,8,32,38))
    parser.add_argument('--flat',action='store_true',help='Constant RGB fixture to test tied minima')
    parser.add_argument('--mixed',action='store_true',help='Opposing horizontal motion in upper/lower halves')
    parser.add_argument('--coarse-step',type=float,default=4.5,choices=(1.0,2.0,4.5))
    parser.add_argument('--global-seed',action='store_true')
    parser.add_argument('--exhaustive-seed',action='store_true')
    parser.add_argument('--fine-seed',action='store_true',help='Probe-only seed proposal on first pass of every level')
    parser.add_argument('--seed-last-level',action='store_true',help='Probe-only global proposal at finest level only')
    parser.add_argument('--gpu-seed',action='store_true',help='GPU argmin; CPU comparison only validates output')
    parser.add_argument('--skip-fill',action='store_true',help='Diagnostic: omit motion hole filling')
    parser.add_argument('--nearest-field',action='store_true',help='Diagnostic: nearest validated-field sampling for synthesis only')
    parser.add_argument('--edge-field',action='store_true',help='Diagnostic: avoid bilinear sampling across motion discontinuities')
    parser.add_argument('--source-dump',type=Path,help='Use previousFull from a 256x192 LFD1 capture as fixture image')
    parser.add_argument('--multi-seed',action='store_true',help='Diagnostic: two non-neighboring GPU-derived proposals')
    parser.add_argument('--endpoint-walk',action='store_true',help='Diagnostic: invert endpoint flow to locate midpoint correspondence')
    parser.add_argument('--endpoint-peers',action='store_true',help='Diagnostic: consistency checks in corrected endpoint coordinates')
    parser.add_argument('--walk-iterations',type=int,choices=(1,2,3,4),default=3)
    parser.add_argument('--walk-best-residual',action='store_true',help='Diagnostic: retain lowest reprojection residual candidate')
    parser.add_argument('--walk-image-cost',action='store_true',help='Diagnostic: source RGB correspondence plus reprojection cost')
    parser.add_argument('--walk-discontinuity-guard',action='store_true',help='Diagnostic: reject walks changing initial motion by over 2 source pixels')
    parser.add_argument('--native-pair',type=Path,nargs=2,help='Two verified contiguous captures; middle withheld on host')
    args=parser.parse_args()
    if args.walk_image_cost and args.walk_best_residual:
        parser.error('Choose image cost or residual-only selection, not both')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'DENSE_EXHAUSTIVE_REDUCE_SHADER.glsl').write_text((ROOT/'tools/qa/DENSE_EXHAUSTIVE_REDUCE_SHADER.glsl').read_text())
    source=(ROOT/'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
    for name in ('DENSE_PYRAMID_SHADER','DENSE_SOLVE_SHADER','DENSE_GLOBAL_COST_SHADER','DENSE_GLOBAL_REDUCE_SHADER','DENSE_GLOBAL_CUT_SHADER','DENSE_CYCLE_SHADER','DENSE_FILL_SHADER','MOTION_INTERPOLATE_SHADER'):
        block=source.split('private static final String '+name+' =',1)[1].split('private static final String',1)[0]
        # Stop at the terminating Java string expression, before following comments.
        tokens=re.findall(r'"(?:\\.|[^"\\])*"\s*[+;]',block)
        result=[]
        for token in tokens:
            result.append(json.loads(token.rstrip('+;').strip()))
            if token.rstrip().endswith(';'):break
        shader=''.join(result)
        if args.multi_seed and name=='DENSE_SOLVE_SHADER':
            old='if(uUseGlobalSeed>.5){vec2 g=clamp(dec(texture2D(uGlobalSeed,vec2(.5))),vec2(-uTemporalLimit),vec2(uTemporalLimit));float gc=objective(g);if(length(g)>.25&&gc+.002<bc){bc=gc;c=g;b=g;}}'
            if shader.count(old)!=1:raise ValueError('Global proposal shader changed')
            new=old.replace('if(uUseGlobalSeed>.5){','if(uUseGlobalSeed>.5){for(int seedIndex=0;seedIndex<2;seedIndex++){').replace('vec2(.5)','vec2((float(seedIndex)+.5)/2.0,.5)')+'}'
            shader=shader.replace(old,new)
        if args.edge_field and name=='MOTION_INTERPOLATE_SHADER':
            for field in ('uBackwardMotion','uForwardMotion','uGlobalBackwardMotion','uGlobalForwardMotion'):
                shader=shader.replace('texture2D('+field+',','edgeField('+field+',')
            if shader.count('void main(){')!=1:raise ValueError('Synthesis entry changed')
            helper=(ROOT/'tools/qa/edge_field_sampling.glsl').read_text()
            shader=shader.replace('void main(){',helper+'\nvoid main(){')
        if args.endpoint_walk and name=='MOTION_INTERPOLATE_SHADER':
            sample='edgeField' if args.edge_field else 'texture2D'
            helper='vec4 endpointWalk(sampler2D field,vec2 uv,float phase){vec2 q=uv;for(int i=0;i<3;i++){q=clamp(uv-decodeFlow('+sample+'(field,q))*phase,0.0,1.0);}return '+sample+'(field,q);}\n'
            helper=helper.replace('i<3','i<'+str(args.walk_iterations))
            if args.walk_image_cost:
                helper='vec4 endpointWalk(sampler2D field,sampler2D sourceImage,sampler2D peerImage,vec2 uv,float phase){vec2 q=uv;vec4 best='+sample+'(field,q);float bestError=1.0e20;for(int i=0;i<'+str(args.walk_iterations+1)+';i++){vec4 value='+sample+'(field,q);vec2 flow=decodeFlow(value);vec2 r=(q+flow*phase-uv)*uDenseSeedSourceSize;vec3 delta=texture2D(sourceImage,q).rgb-texture2D(peerImage,clamp(q+flow,0.0,1.0)).rgb;float error=dot(r,r)+16.0*dot(delta,delta);if(error<bestError){bestError=error;best=value;}q=clamp(uv-flow*phase,0.0,1.0);}return best;}\n'
            if args.walk_best_residual:
                helper='vec4 endpointWalk(sampler2D field,vec2 uv,float phase){vec2 q=uv;vec4 best='+sample+'(field,q);float bestError=1.0e20;for(int i=0;i<'+str(args.walk_iterations+1)+';i++){vec4 value='+sample+'(field,q);vec2 flow=decodeFlow(value);vec2 r=(q+flow*phase-uv)*uDenseSeedSourceSize;float error=dot(r,r);if(error<bestError){bestError=error;best=value;}q=clamp(uv-flow*phase,0.0,1.0);}return best;}\n'
                (out/'walk-best-residual.txt').write_text('Minimum squared reprojection residual over initial and iterated candidates, in source pixels.\n')
            (out/'walk-iterations.txt').write_text(str(args.walk_iterations)+'\n')
            if args.walk_discontinuity_guard:
                if not (args.walk_image_cost or args.walk_best_residual):parser.error('Discontinuity guard requires best-candidate walk')
                old='return best;}'
                if helper.count(old)!=1:raise ValueError('Walk return changed')
                helper=helper.replace(old,'vec4 initial='+sample+'(field,uv);return length((decodeFlow(best)-decodeFlow(initial))*uDenseSeedSourceSize)>2.0?initial:best;}')
                (out/'walk-discontinuity-guard.txt').write_text('Reject candidate when its vector differs from initial by >2 source pixels. No ground truth used.\n')
            shader=shader.replace('void main(){',helper+'void main(){')
            for field,phase in [('uBackwardMotion','(1.0-uPhase)'),('uForwardMotion','uPhase')]:
                old=sample+'('+field+',vTexCoord)'
                if shader.count(old)!=1:raise ValueError('Initial field sample changed')
                shader=shader.replace(old,'endpointWalk('+field+',vTexCoord,'+phase+')')
            if args.walk_image_cost:
                shader=shader.replace('endpointWalk(uBackwardMotion,vTexCoord,','endpointWalk(uBackwardMotion,uCurrent,uPrevious,vTexCoord,')
                shader=shader.replace('endpointWalk(uForwardMotion,vTexCoord,','endpointWalk(uForwardMotion,uPrevious,uCurrent,vTexCoord,')
                (out/'walk-image-cost.txt').write_text('Squared reprojection pixels +16*squared source RGB mismatch; diagnostic coefficient, no midpoint truth.\n')
            (out/'endpoint-walk.txt').write_text(str(args.walk_iterations)+' fixed-point iterations for initial field samples; peer correction controlled separately.\n')
            if args.endpoint_peers:
                old='vec2 forward=decodeFlow(forwardField);'
                if shader.count(old)!=1:raise ValueError('Flow decode binding changed')
                shader=shader.replace(old,old+'\nvec2 previousEndpoint=clamp(vTexCoord-forward*uPhase,0.0,1.0);vec2 currentEndpoint=clamp(vTexCoord-backward*(1.0-uPhase),0.0,1.0);')
                # Restrict replacement to initial local cycle/reliability block.
                start=shader.index('vec2 backwardAtForward=');end=shader.index('if(uDenseEncoding<0.5)',start)
                block=shader[start:end]
                if block.count('vTexCoord+forward')!=2 or block.count('vTexCoord+backward')!=2:
                    raise ValueError('Peer coordinate contract changed')
                block=block.replace('vTexCoord+forward','previousEndpoint+forward').replace('vTexCoord+backward','currentEndpoint+backward')
                shader=shader[:start]+block+shader[end:]
                (out/'endpoint-peers.txt').write_text('Initial cycle and peer-confidence samples use endpoint coordinates; later fallback unchanged.\n')
        (out/(name+'.glsl')).write_text(shader)
    template=(ROOT/'tools/qa/DensePyramidDeviceTest.java').read_text().replace('DensePyramidDeviceTest','ProductionSolverProbe')
    template=template.replace('System.out.println("PASS shader-only spatial-detail fixture; not full motion or timing acceptance");',
        'new ProductionSolverProbe().runSolver(args[1],Integer.parseInt(args[2]),Float.parseFloat(args[3]),Boolean.parseBoolean(args[4]),Boolean.parseBoolean(args[5]),Boolean.parseBoolean(args[6]));')
    methods='\n'.join(method(source,name) for name in ('private void buildDensePyramid(', 'private void drawDensePyramid(', 'private void solveDenseDirection(', 'private void refineDenseReciprocalDirection(', 'private void attachDenseTarget('))
    methods+='\n'+'\n'.join(method(source,name) for name in ('private void buildDenseGlobalSeed(', 'private void drawDenseGlobalCut(', 'private void drawDenseGlobalCosts(', 'private void reduceDenseGlobalCosts('))
    methods+='\n'+'\n'.join(method(source,name) for name in ('private void validateDenseDirection(', 'private void fillDenseDirection(', 'private float[] denseActiveRect('))
    if args.fine_seed or args.seed_last_level:
        old='denseV28ReducedAnalysisRequested && coarsestFirst ? 1f : 0f'
        if methods.count(old)!=1:raise ValueError('Seed gate changed; inspect before ablation')
        gate='denseV28ReducedAnalysisRequested && iteration == 0'
        if args.seed_last_level:gate+=' && level == 0'
        methods=methods.replace(old,gate+' ? 1f : 0f')
    (out/'probe-config.json').write_text(json.dumps({'shift':args.shift,'coarse_step':args.coarse_step,
        'global_seed':args.global_seed,'exhaustive_seed':args.exhaustive_seed,'fine_seed':args.fine_seed,
        'gpu_seed':args.gpu_seed,'seed_last_level':args.seed_last_level,'mixed':args.mixed,'flat':args.flat,
        'skip_fill':args.skip_fill,'nearest_field':args.nearest_field,'edge_field':args.edge_field,
        'runtime_modified':False},indent=2)+'\n')
    template=template.rstrip()[:-1]+(ROOT/'tools/qa/ProductionSolverProbe.fragment').read_text()+methods+'\n}'
    if args.native_pair:
        if args.source_dump or args.mixed or args.flat:parser.error('Native pair cannot combine with transformed fixtures')
        from verify_held_out_triplet import verify
        from analyze_dense_flow_merging import read_dump
        proof=verify(*args.native_pair);meta,first=read_dump(args.native_pair[0]);_,second=read_dump(args.native_pair[1])
        if (meta['history_width'],meta['history_height'])!=(256,192):raise ValueError('Native probe requires 256x192')
        if abs(proof['reference_phase']-.5)>.001:raise ValueError('Captured middle not sufficiently close to half phase')
        (out/'native-left.rgba').write_bytes(first['previousFull'][2]);(out/'native-right.rgba').write_bytes(second['currentFull'][2])
        (out/'withheld-reference.rgba').write_bytes(first['currentFull'][2]);(out/'native-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
        old='ByteBuffer a=ByteBuffer.allocateDirect(original.length),b=ByteBuffer.allocateDirect(original.length);'
        template=template.replace(old,'original=Files.readAllBytes(Paths.get(shaderPath).getParent().resolve("native-left.rgba"));'+old)
        template=template.replace('b.flip();int left=', 'b.clear();b.put(Files.readAllBytes(Paths.get(shaderPath).getParent().resolve("native-right.rgba")));b.flip();int left=')
        # Suppress synthetic truth scoring while retaining synthesis and field capture.
        template=template.replace('System.out.println("PRODUCTION_SOLVER shift="','System.out.println("UNSCORED_NATIVE_VECTOR synthetic_truth_invalid shift="')
        template=template.replace('System.out.println("MIDPOINT old_pyramid="','System.out.println("UNSCORED_NATIVE_IMAGE synthetic_truth_invalid old_pyramid="')
    if args.multi_seed:
        if not args.gpu_seed:raise ValueError('multi-seed requires gpu-seed')
        template=template.replace('boolean multiSeed=false;','boolean multiSeed=true;')
        (out/'multi-seed.txt').write_text('Two GPU argmin proposals separated by >3px; local objective accepts/rejects.\n')
    if args.source_dump:
        from analyze_dense_flow_merging import read_dump
        meta,planes=read_dump(args.source_dump)
        if (meta['history_width'],meta['history_height'])!=(256,192):raise ValueError('Fixture requires 256x192 capture')
        plane=planes['previousFull']
        if plane[:2]!=(256,192):raise ValueError('Plane dimensions mismatch')
        (out/'fixture.rgba').write_bytes(plane[2])
        old='ByteBuffer a=ByteBuffer.allocateDirect(original.length),b=ByteBuffer.allocateDirect(original.length);'
        if template.count(old)!=1:raise ValueError('Fixture input binding changed')
        template=template.replace(old,'original=Files.readAllBytes(Paths.get(shaderPath).getParent().resolve("fixture.rgba"));\n'+old)
        (out/'source-fixture.txt').write_text(str(args.source_dump.resolve())+'\npreviousFull only; captured flows and other endpoint not used.\n')
    if args.nearest_field:
        old='int output=texture(256,192,null);attachDenseTarget(output,256,192);'
        if template.count(old)!=1:raise ValueError('Synthesis binding changed')
        template=template.replace(old,'''for(int field:denseValidatedTextures){
            glBindTexture(GL_TEXTURE_2D,field);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        }
        '''+old)
        # Restore filtering before the next cycle/fill to isolate synthesis.
        template=template.replace('validateDenseDirection(0,left,right);validateDenseDirection(1,right,left);','''for(int field:denseValidatedTextures){
            glBindTexture(GL_TEXTURE_2D,field);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        }
        validateDenseDirection(0,left,right);validateDenseDirection(1,right,left);''')
        (out/'nearest-field.txt').write_text('Synthesis only nearest validated field; cycle/fill retain linear.\n')
    if args.skip_fill:
        old='fillDenseDirection(0);fillDenseDirection(1);'
        if template.count(old)!=1:raise ValueError('Fill call site changed')
        template=template.replace(old,'/* Diagnostic: fill omitted. */')
        (out/'skip-fill.txt').write_text('Diagnostic only: cycle validation retained, six fill passes per direction omitted.\n')
    if args.mixed:
        template=template.replace('boolean mixedMidpoint=false;','boolean mixedMidpoint=true;')
        replacements={
            'Math.max(0,x-displacement)':'Math.max(0,Math.min(255,x-(y<96?displacement:-displacement)))',
            'int i=(y*192+x)*4;':'if(y>=60&&y<84)continue; int i=(y*192+x)*4;',
            '(d==0?-displacement:displacement)':'(d==0?-1:1)*(y<72?displacement:-displacement)'}
        for old,new in replacements.items():
            if template.count(old)!=1:raise ValueError('Mixed fixture binding changed: '+old)
            template=template.replace(old,new)
        (out/'mixed-fixture.txt').write_text('Upper half moves right; lower half left. Scoring excludes 12 analysis rows each side of seam and displaced image boundaries.\n')
    if args.flat:
        old='(40+rng.nextInt(100)+((x/17+y/13)%2)*70)'
        if template.count(old)!=1:raise ValueError('Fixture changed')
        template=template.replace(old,'128')
        (out/'flat-fixture.txt').write_text('Constant RGB128; translation is unobservable. Expected selected seed is zero.\n')
    (out/'ProductionSolverProbe.java').write_text(template)
    for name in ('classes','dex'):(out/name).mkdir(exist_ok=True)
    run(JAVA/'javac','-cp',SDK/'platforms/android-35/android.jar','-d',out/'classes',out/'ProductionSolverProbe.java')
    run(JAVA/'jar','cf',out/'classes.jar','-C',out/'classes','.')
    run(SDK/'build-tools/36.0.0/d8','--lib',SDK/'platforms/android-35/android.jar','--output',out/'dex',out/'classes.jar')
    run(JAVA/'jar','cf',out/'probe.jar','-C',out/'dex','classes.dex')
    remote=run(*ADB,'shell','mktemp -d /data/local/tmp/emufusion-solver-XXXXXX').strip()
    (out/'remote.txt').write_text(remote+'\n')
    run(*ADB,'push',out/'probe.jar',*sorted(out.glob('*.glsl')),remote+'/')
    if args.source_dump:run(*ADB,'push',out/'fixture.rgba',remote+'/fixture.rgba')
    if args.native_pair:run(*ADB,'push',out/'native-left.rgba',out/'native-right.rgba',remote+'/')
    result=subprocess.run(ADB+['shell',f'CLASSPATH={remote}/probe.jar app_process / com.thorium.preview.game.ProductionSolverProbe {remote}/DENSE_PYRAMID_SHADER.glsl {remote}/DENSE_SOLVE_SHADER.glsl {args.shift} {args.coarse_step} {str(args.global_seed or args.exhaustive_seed or args.gpu_seed).lower()} {str(args.exhaustive_seed or args.gpu_seed).lower()} {str(args.gpu_seed).lower()}'],text=True,capture_output=True,timeout=45)
    (out/'device.log').write_text(result.stdout+result.stderr);print(result.stdout+result.stderr);result.check_returncode()
    run(*ADB,'pull',remote+'/images',out/'images')
    if args.native_pair:
        import numpy as np
        reference=np.fromfile(out/'withheld-reference.rgba',np.uint8).reshape(192,256,4)[...,:3].astype(float)
        scores={}
        for path in sorted((out/'images').glob('old-*-round-?.rgba')):
            generated=np.fromfile(path,np.uint8).reshape(192,256,4)[...,:3].astype(float)
            error=abs(generated-reference)
            scores[path.name]={'rgb_mae':float(error.mean()),'severe_pixels':int((error.max(axis=2)>40).sum()),'image_quality_qualified':False}
        (out/'native-scores.json').write_text(json.dumps(scores,indent=2)+'\n');print(json.dumps(scores,indent=2))

if __name__=='__main__':main()
