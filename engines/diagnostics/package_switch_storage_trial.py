#!/usr/bin/env python3
"""Package only the compiled Java change on the exact current device baseline."""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile

from package_spurs_trace import ROOT, SDK, digest, signature

BASE_SHA = "eb3c40836062d48f2b65fb9a6a51a9a4a8aedf192bb399248cdba157de6eeb40"
JAVA_SHA = "242a120235feccedb5e6a995f44a1a369c571d38c486ad5cdce3d4244cbf1983"
BASE = ROOT / "engines/build/candidates/aps3e-wrapper-sync-clean-apk-2026-09-09/emufusion-spurs-trace.apk"
JAVA = ROOT / f"unified-android/build/lucent-3.2.16-phase2-phase3-qualification-{JAVA_SHA}.apk"
NOTE = "assets/local-switch-storage-trial.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists():
        parser.error("output already exists")
    assert digest(BASE.read_bytes()) == BASE_SHA
    assert digest(JAVA.read_bytes()) == JAVA_SHA
    with zipfile.ZipFile(BASE) as old, zipfile.ZipFile(JAVA) as compiled:
        assert NOTE not in old.namelist()
        dex = compiled.read("classes2.dex")
        assert dex.startswith(b"dex\n")
        note = dict(baseApkSha256=BASE_SHA, javaBuildApkSha256=JAVA_SHA,
                    dexSha256=digest(dex), purpose="Isolated Switch storage trial; device unverified",
                    preserved="Every existing non-signature payload except classes2.dex")
        out.mkdir(parents=True)
        with zipfile.ZipFile(out / "unsigned.apk", "w") as new:
            for entry in old.infolist():
                if not signature(entry.filename):
                    new.writestr(entry, dex if entry.filename == "classes2.dex" else old.read(entry.filename))
            new.writestr(NOTE, json.dumps(note, indent=2))
    bt = SDK / "build-tools/36.0.0"
    subprocess.run([str(bt / "zipalign"), "-f", "4", str(out / "unsigned.apk"), str(out / "aligned.apk")], check=True)
    signed = out / "emufusion-switch-storage.apk"
    subprocess.run([str(bt / "apksigner"), "sign", "--ks", str(ROOT / "android-companion/debug.keystore"),
                    "--ks-pass", "pass:android", "--key-pass", "pass:android", "--ks-key-alias", "androiddebugkey",
                    "--out", str(signed), str(out / "aligned.apk")], check=True)
    subprocess.run([str(bt / "apksigner"), "verify", "--verbose", str(signed)], check=True)
    with zipfile.ZipFile(BASE) as old, zipfile.ZipFile(signed) as new:
        changed = [n for n in old.namelist() if not signature(n) and old.read(n) != new.read(n)]
        added = [n for n in new.namelist() if n not in old.namelist() and not signature(n)]
        assert changed == ["classes2.dex"] and added == [NOTE]
    print(json.dumps(dict(apk=str(signed), sha256=digest(signed.read_bytes()), changed=changed, added=added), indent=2))


if __name__ == "__main__":
    main()
