"""Audited shader-only replacement of the current recovered diagnostic APK."""
import hashlib,json,os,re,subprocess,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'docs/qa/recovered-baseline-2026-09-15'
OUT=ROOT/'docs/qa/smoothing-apk-2026-09-15'
BT=Path('/Users/tyleryoung/Library/Android/sdk/build-tools/36.0.0')
OLD='b=mix(b,smooth,w);gl_FragColor=enc(b);'
NEW='vec2 proposed=floor(mix(b,smooth,w)*256.0+.5)/256.0;if(objective(proposed)+.000001<objective(b))b=proposed;gl_FragColor=enc(b);'

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def signature(name):
    return name.startswith('META-INF/') and (name.endswith(('.RSA','.SF','.DSA','.EC')) or name=='META-INF/MANIFEST.MF')

def run(*args):
    env=dict(os.environ,JAVA_HOME='/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home')
    return subprocess.check_output([str(x) for x in args],text=True,env=env)

def main():
    base=BASE/'contiguous-package/flow-export.apk'
    assert sha(base)=='2b24f1afbcb09995871a863e4f81e8375d5a5c6f9b1d6f8393c499005e312f88'
    # Java versions format explanatory float comments differently; retain the
    # exact hexadecimal payload and all directives/instructions/string content.
    def normalize(text):return re.sub(r'(?m)^(\s*(?:const-wide/high16 v\d+, )?-?0x[0-9a-fA-F]+L?)\s+# [^\n]*$',r'\1',text)
    def tree(root):return {p.relative_to(root):normalize(p.read_text()) for p in root.rglob('*.smali')}
    before=tree(BASE/'contiguous-check/smali');after=tree(OUT/'check/smali')
    assert len(before)==2183 and before.keys()==after.keys()
    target=Path('com/thorium/preview/game/DisplayFrameGenerator.smali')
    assert [p for p in before if before[p]!=after[p]]==[target]
    assert before[target].count(OLD)==2 and NEW not in before[target]
    assert before[target].replace(OLD,NEW)==after[target]
    source=(ROOT/'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
    assert NEW in source
    with zipfile.ZipFile(OUT/'dex.zip') as z:dex=z.read('classes.dex')
    unsigned=OUT/'unsigned.apk';aligned=OUT/'aligned.apk';apk=OUT/'smoothing.apk'
    assert not aligned.exists() and not apk.exists()
    with zipfile.ZipFile(base) as a,zipfile.ZipFile(unsigned,'x') as b:
        for item in a.infolist():
            if not signature(item.filename):b.writestr(item,dex if item.filename=='classes2.dex' else a.read(item.filename))
    run(BT/'zipalign','-P','16','4',unsigned,aligned)
    run(BT/'apksigner','sign','--ks',ROOT/'android-companion/debug.keystore',
        '--ks-pass','pass:android','--key-pass','pass:android','--ks-key-alias','androiddebugkey','--out',apk,aligned)
    cert=lambda path:[s for s in run(BT/'apksigner','verify','--print-certs',path).splitlines() if 'certificate SHA-256 digest:' in s]
    assert cert(base) and cert(base)==cert(apk)
    run(BT/'zipalign','-c','-P','16','4',apk)
    with zipfile.ZipFile(base) as a,zipfile.ZipFile(apk) as b:
        names={n for n in a.namelist() if not signature(n)}
        assert names=={n for n in b.namelist() if not signature(n)}
        assert {n for n in names if a.read(n)!=b.read(n)}=={'classes2.dex'}
    record=dict(baseSha256=sha(base),sha256=sha(apk),classesAudited=len(before),
        changedClass=str(target),shaderLiteralCopies=2,certificateMatched=True,
        installed=False,gameplayQualified=False)
    (OUT/'verification.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))

if __name__=='__main__':main()
