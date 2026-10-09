"""Package the audited four-hook submission-timing diagnostic only."""
import json,zipfile
from audit_submission_overlay import main as audit,OUT,ROOT
from package_smoothing_candidate import sha,signature,run,BT


def main():
    audit()
    base=ROOT/'docs/qa/smoothing-apk-2026-09-15/smoothing.apk'
    assert sha(base)=='2c6fe3dc8abb39f6fae9419bff12aa34cdd6173c9e4b5faa7a1d64990c9a2330'
    with zipfile.ZipFile(OUT/'dex.zip') as z:dex=z.read('classes.dex')
    unsigned,aligned,apk=[OUT/name for name in ['unsigned.apk','aligned.apk','submission.apk']]
    assert not aligned.exists() and not apk.exists()
    with zipfile.ZipFile(base) as a,zipfile.ZipFile(unsigned,'x') as b:
        for item in a.infolist():
            if not signature(item.filename):b.writestr(item,dex if item.filename=='classes2.dex' else a.read(item.filename))
    run(BT/'zipalign','-P','16','4',unsigned,aligned)
    run(BT/'apksigner','sign','--ks',ROOT/'android-companion/debug.keystore',
        '--ks-pass','pass:android','--key-pass','pass:android','--ks-key-alias','androiddebugkey','--out',apk,aligned)
    cert=lambda path:[s for s in run(BT/'apksigner','verify','--print-certs',path).splitlines() if 'certificate SHA-256 digest:' in s]
    before,after=cert(base),cert(apk);assert before and before==after
    run(BT/'zipalign','-c','-P','16','4',apk)
    with zipfile.ZipFile(base) as a,zipfile.ZipFile(apk) as b:
        names={n for n in a.namelist() if not signature(n)}
        assert names=={n for n in b.namelist() if not signature(n)}
        assert {n for n in names if a.read(n)!=b.read(n)}=={'classes2.dex'}
    result={'sha256':sha(apk),'base_sha256':sha(base),'certificate_matched':True,
            'installed':False,'gameplay_qualified':False,'diagnostic_only':True}
    (OUT/'package-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
