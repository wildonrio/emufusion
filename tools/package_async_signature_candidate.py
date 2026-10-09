"""Audit and package capability-selected async signatures, no other changes."""
import json
import zipfile
from pathlib import Path
from audit_submission_overlay import canonical
from package_smoothing_candidate import ROOT, BT, sha, signature, run

OUT = ROOT / 'docs/qa/async-signature-2026-09-15'
BASE = ROOT / 'docs/qa/submission-overlay-2026-09-15'
BASE_APK = BASE / 'submission.apk'
EXPECTED_BASE_SHA = '30bc2043cd5cb3894e78489965aeb4a4ec0d78dbcb873eaaf813572262fd5bd0'
EXPECTED_OCCURRENCES = 1
TARGET = Path('com/thorium/preview/game/DisplayFrameGenerator.smali')
PREFIX = 'Lcom/thorium/preview/game/DisplayFrameGenerator;'
OLD = '    if-eqz v0, :cond_4\n\n    .line 4079'
NEW = f'''    if-nez v0, :signature_async_ready

    iget-object v0, v1, {PREFIX}->denseGpuTimer:Lcom/thorium/preview/game/DenseGpuTimer;

    if-eqz v0, :cond_4

    invoke-direct {{v1, v0}}, {PREFIX}->signatureCapability(Lcom/thorium/preview/game/DenseGpuTimer;)I

    move-result v2

    const/16 v0, 0x3f

    if-ne v2, v0, :cond_4

    :signature_async_ready

    .line 4079'''


def main():
    base = BASE_APK
    assert sha(base) == EXPECTED_BASE_SHA
    def tree(path):
        return {p.relative_to(path): p.read_text() for p in path.rglob('*.smali')}
    before = tree(BASE / 'input/smali')
    entered = tree(OUT / 'input/smali')
    built = tree(OUT / 'check/smali')
    assert len(before) == 2187 and before.keys() == entered.keys() == built.keys()
    assert before[TARGET].count(OLD) == EXPECTED_OCCURRENCES and entered[TARGET].count(NEW) == EXPECTED_OCCURRENCES
    assert before[TARGET].replace(OLD, NEW) == entered[TARGET]
    for name in before:
        if name != TARGET:
            assert before[name] == entered[name], name
        # Baksmali moves .line 4079 across the new zero-width branch label.
        # Compare executable instructions; the entered edit is exact above.
        executable = lambda text: [s for s in canonical(text) if not s.startswith('.line ')]
        assert executable(entered[name]) == executable(built[name]), name
    with zipfile.ZipFile(OUT / 'dex.zip') as archive:
        dex = archive.read('classes.dex')
    unsigned, aligned, apk = [OUT / n for n in ('unsigned.apk', 'aligned.apk', 'async-signature.apk')]
    assert not aligned.exists() and not apk.exists()
    with zipfile.ZipFile(base) as a, zipfile.ZipFile(unsigned, 'x') as b:
        for item in a.infolist():
            if not signature(item.filename):
                b.writestr(item, dex if item.filename == 'classes2.dex' else a.read(item.filename))
    run(BT / 'zipalign', '-P', '16', '4', unsigned, aligned)
    run(BT / 'apksigner', 'sign', '--ks', ROOT / 'android-companion/debug.keystore',
        '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--ks-key-alias',
        'androiddebugkey', '--out', apk, aligned)
    def cert(path):
        return [s for s in run(BT / 'apksigner', 'verify', '--print-certs', path).splitlines()
                if 'certificate SHA-256 digest:' in s]
    assert cert(base) and cert(base) == cert(apk)
    run(BT / 'zipalign', '-c', '-P', '16', '4', apk)
    with zipfile.ZipFile(base) as a, zipfile.ZipFile(apk) as b:
        names = {n for n in a.namelist() if not signature(n)}
        assert names == {n for n in b.namelist() if not signature(n)}
        assert {n for n in names if a.read(n) != b.read(n)} == {'classes2.dex'}
    result = dict(sha256=sha(apk), base_sha256=sha(base), classes_audited=len(before),
                  changed_class=str(TARGET), installed=False, gameplay_qualified=False)
    (OUT / 'package-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
