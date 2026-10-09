"""Read-only live SurfaceFlinger pacing sample after actual generation starts.

Caller owns launch, mode restoration and OLED deadline guard. No pass verdict:
timestamps measure delivery, not whether generated content is useful.
"""
import argparse,json,re,shlex,subprocess,time
from pathlib import Path

ADB='/Users/tyleryoung/.codex/tools/android-platform-tools/adb'

def run(*args):
    return subprocess.check_output([ADB,'-s','427c87b2',*args],text=True,timeout=15)

def fields(line):return dict(re.findall(r'([A-Za-z0-9]+)=([^ ]+)',line))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--layer',help='Exact visible layer independently identified from SurfaceFlinger dump')
    p.add_argument('--windows',type=int,default=40,help='Half-second observation windows (1-600)')
    args=p.parse_args();out=args.output;assert out.is_dir()
    if not 1<=args.windows<=600:p.error('--windows must be between 1 and 600')
    pid=run('shell','pidof','com.thorium.preview').strip();assert pid.isdigit()
    deadline=time.monotonic()+90
    while True:
        log=run('logcat','-d','--pid='+pid)
        rows=[s for s in log.splitlines() if 'App swap cadence' in s]
        last=fields(rows[-1]) if rows else {}
        if float(last.get('target','0'))>100 and last.get('panelMeasured')=='1' and int(last.get('schedulerSynthetic','0'))>0:break
        if time.monotonic()>deadline:raise RuntimeError('No measured generated cadence within90s')
        time.sleep(2)
    print('Generated cadence active; collecting physical timestamps',flush=True)
    layers=[s.strip() for s in run('shell','dumpsys','SurfaceFlinger','--list').splitlines()
            if 'SurfaceView[com.thorium.preview/' in s and 'MainActivity](BLAST)' in s]
    if args.layer:
        if args.layer not in layers:raise RuntimeError('Requested layer not present')
        layers=[args.layer]
    if len(layers)!=1:raise RuntimeError(f'Ambiguous game layer: {layers}')
    layer=layers[0];captures=[]
    # Consecutive half-second pulls overlap the 128-entry ring at120Hz.
    for i in range(args.windows):
        captures.append(run('shell',shlex.join(['dumpsys','SurfaceFlinger','--latency',layer])))
        if (i+1)%40==0:print(f'Captured {i+1}/{args.windows} windows',flush=True)
        time.sleep(.5)
    (out/'surfaceflinger-latency.txt').write_text('\n---capture---\n'.join(captures))
    (out/'runtime.log').write_text(run('logcat','-d','--pid='+pid))
    (out/'capture.json').write_text(json.dumps({'pid':pid,'layer':layer,'captures':len(captures),
        'cadence_at_start':last,'image_quality_qualified':False},indent=2)+'\n')
    print(f'Captured{len(captures)} physical timestamp windows',flush=True)


if __name__=='__main__':main()
