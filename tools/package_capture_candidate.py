"""Audit bounded capture hooks and compiled readback helpers, preserving gameplay."""
import json,shutil,sys,zipfile
from pathlib import Path
from audit_submission_overlay import canonical
from package_smoothing_candidate import ROOT,BT,sha,signature,run

OUT=ROOT/'docs/qa/capture-apk-2026-09-16'
BASE=ROOT/'docs/qa/guidance-apk-2026-09-16'
APK=BASE/'async-signature.apk'
EXPECTED='8c3431dab9656b79c1b3dadf440853e8d3494b5b525b2b55fca9bbc5bc361adb'
TARGET=Path('com/thorium/preview/game/DisplayFrameGenerator.smali')
D='Lcom/thorium/preview/game/DisplayFrameGenerator;'
R='Lcom/thorium/preview/game/FullResolutionFrameReadback;'
PATCHES=[
 (f'    iget-boolean p1, p0, {D}->qualificationProofEnabled:Z\n\n    if-eqz p1, :cond_1\n\n    const-wide/16 v0, 0x0',
  '    const-wide/16 v0, 0x0'),
 (f'    invoke-static {{}}, {R}->nativeBackend()Lcom/thorium/preview/game/FullResolutionFrameReadback$Backend;',
  f'    iget v4, p0, {D}->actualEglContextMajor:I\n\n    invoke-static {{v4}}, {R}->backendForContext(I)Lcom/thorium/preview/game/FullResolutionFrameReadback$Backend;'),
 (f'    .line 9983\n    int-to-float v0, p1\n\n    invoke-direct {{p0, v0}}, {D}->drawMotionFrame(F)V',
  f'''    .line 9983
    iget-object v0, p0, {D}->historyTextures:[I
    if-nez p1, :capture_reference_current
    iget v7, p0, {D}->previousIndex:I
    goto :capture_reference_ready
    :capture_reference_current
    iget v7, p0, {D}->currentIndex:I
    :capture_reference_ready
    aget v0, v0, v7
    invoke-direct {{p0, v0}}, {D}->drawTexture2d(I)V'''),
 (r'    const-string p3, "\nformat=RGBA8-bottom-up\ninstrumentedTiming=true\npresentationOutcome=unresolved-use-physical-frame-log\n"',
  r'    const-string p3, "\nformat=RGBA8-bottom-up\ninstrumentedTiming=true\nreadback="'+'\n'+f'''
    invoke-virtual {{p2, p3}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object p2
    iget p3, p0, {D}->actualEglContextMajor:I
    invoke-static {{p3}}, {R}->readbackName(I)Ljava/lang/String;
    move-result-object p3
    invoke-virtual {{p2, p3}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object p2
'''+r'    const-string p3, "\npresentationOutcome=unresolved-use-physical-frame-log\n"')]

def tree(path):return {p.relative_to(path):p.read_text() for p in path.rglob('*.smali')}
def expected():
    assert sha(APK)==EXPECTED
    before=tree(BASE/'input/smali');after=dict(before)
    for old,new in PATCHES:
        assert after[TARGET].count(old)==1,old
        after[TARGET]=after[TARGET].replace(old,new)
    helpers={p:t for p,t in tree(OUT/'helper-check/smali').items() if p.name.startswith('FullResolutionFrameReadback')}
    assert len(helpers)==4
    after.update(helpers)
    assert len(before)==2187 and len(after)==2188
    return after

def main():
    wanted=expected()
    if sys.argv[1:]==['--prepare']:
        shutil.copytree(BASE/'input',OUT/'input')
        # Mechanical, audited generated-disassembly replacement only.
        for name,text in wanted.items():
            path=OUT/'input/smali'/name
            if not path.exists() or path.read_text()!=text:path.write_text(text)
        return
    assert not sys.argv[1:]
    entered=tree(OUT/'input/smali');built=tree(OUT/'check/smali')
    assert entered==wanted and entered.keys()==built.keys()
    def instructions(text):return [s for s in canonical(text) if not s.startswith('.line ')]
    for name in entered:assert instructions(entered[name])==instructions(built[name]),name
    with zipfile.ZipFile(OUT/'dex.zip') as z:dex=z.read('classes.dex')
    unsigned,aligned,apk=[OUT/n for n in ('unsigned.apk','aligned.apk','capture.apk')]
    assert not aligned.exists() and not apk.exists()
    with zipfile.ZipFile(APK) as a,zipfile.ZipFile(unsigned,'x') as b:
        for item in a.infolist():
            if not signature(item.filename):b.writestr(item,dex if item.filename=='classes2.dex' else a.read(item.filename))
    run(BT/'zipalign','-P','16','4',unsigned,aligned)
    run(BT/'apksigner','sign','--ks',ROOT/'android-companion/debug.keystore','--ks-pass','pass:android',
        '--key-pass','pass:android','--ks-key-alias','androiddebugkey','--out',apk,aligned)
    def cert(path):return [s for s in run(BT/'apksigner','verify','--print-certs',path).splitlines() if 'certificate SHA-256 digest:' in s]
    assert cert(APK) and cert(APK)==cert(apk)
    run(BT/'zipalign','-c','-P','16','4',apk)
    with zipfile.ZipFile(APK) as a,zipfile.ZipFile(apk) as b:
        names={n for n in a.namelist() if not signature(n)}
        assert names=={n for n in b.namelist() if not signature(n)}
        assert {n for n in names if a.read(n)!=b.read(n)}=={'classes2.dex'}
    result=dict(sha256=sha(apk),base_sha256=EXPECTED,classes_audited=len(entered),
                renderer_hooks=4,compiled_capture_classes=4,installed=False,gameplay_qualified=False)
    (OUT/'package-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
