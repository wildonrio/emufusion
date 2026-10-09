"""Package recovered Thor baseline with the audited flow-export DEX only."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "docs/qa/recovered-baseline-2026-09-15"
BT = Path("/Users/tyleryoung/Library/Android/sdk/build-tools/36.0.0")
os.environ["JAVA_HOME"] = "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def run(*args):
    return subprocess.check_output([str(x) for x in args], text=True)

def signature(name):
    return name.startswith("META-INF/") and (name.endswith((".RSA", ".SF", ".DSA", ".EC")) or name == "META-INF/MANIFEST.MF")

parser = argparse.ArgumentParser()
parser.add_argument("--throttled", action="store_true")
parser.add_argument("--low-motion", action="store_true")
parser.add_argument("--full-endpoints", action="store_true")
parser.add_argument("--contiguous", action="store_true")
args = parser.parse_args()
assert not args.low_motion or args.throttled
assert not args.full_endpoints or args.low_motion
assert not args.contiguous or args.full_endpoints
variant = "low-motion" if args.low_motion else ("throttled-v2" if args.throttled else "candidate")
if args.full_endpoints:
    variant = "full-endpoints"
if args.contiguous:
    variant = "contiguous"
base = P / "installed.apk"
assert sha(base) == "2988c6149d284a4def9ab02202e13da23be79520976cf6c916f3764f393aefd1"
a, b = P / "roundtrip/smali", P / (variant + "-check/smali")
left = {f.relative_to(a): f.read_bytes() for f in a.rglob("*.smali")}
right = {f.relative_to(b): f.read_bytes() for f in b.rglob("*.smali")}
assert len(left) == 2182
helper = Path("com/thorium/preview/game/FlowDumpCaptureMetadata.smali")
assert set(right) == set(left) | ({helper} if args.contiguous else set())
if args.contiguous:
    assert right[helper] == (ROOT / "docs/qa/contiguous-build-2026-09-15/helper-check/smali" / helper).read_bytes()
target = Path("com/thorium/preview/game/DisplayFrameGenerator.smali")
assert [n for n in left if left[n] != right[n]] == [target]
expected = left[target].replace(b"/data/user/0/com.thorium.preview/files/flowdump", b"/sdcard/Android/data/com.thorium.preview/files/flowdump")
if args.throttled:
    # Compare the disassembled DEX against the exact reviewed input, then
    # constrain that input's changes to this one diagnostic method and path.
    edited = (P / "decoded/smali_classes2" / target).read_bytes()
    prefix = b".method private maybeDumpDenseFlow(II)V"
    before, method = expected.split(prefix, 1)
    method, after = method.split(b".end method", 1)
    new_before, new_method = edited.split(prefix, 1)
    new_method, new_after = new_method.split(b".end method", 1)
    assert before == new_before and after == new_after
    assert new_method.count(b"->denseFlowDumpLastNs:J") == 2
    assert new_method.index(b"iput-wide v0, p0") < new_method.index(b"->readDenseCoarseDifference()F")
    # apktool normalizes whitespace when disassembling; compare instructions,
    # directives, and labels rather than blank-line placement.
    normalize = lambda data: [line.strip() for line in data.splitlines() if line.strip()]
    assert normalize(edited) == normalize(right[target])
else:
    assert expected == right[target]
dex = (P / "decoded/build/apk/classes2.dex").read_bytes()
dex_zip = "throttled-dex-v2.zip" if variant == "throttled-v2" else variant + "-dex.zip"
with zipfile.ZipFile(P / dex_zip) as checked:
    assert dex == checked.read("classes.dex")
out = P / ("low-motion-package" if args.low_motion else ("throttled-package" if args.throttled else "diagnostic-package"))
if args.full_endpoints:
    out = P / "full-endpoints-package"
if args.contiguous:
    out = P / "contiguous-package"
out.mkdir()
unsigned, aligned, apk = [out / n for n in ("unsigned.apk", "aligned.apk", "flow-export.apk")]
with zipfile.ZipFile(base) as original, zipfile.ZipFile(unsigned, "x") as result:
    for item in original.infolist():
        if not signature(item.filename):
            result.writestr(item, dex if item.filename == "classes2.dex" else original.read(item.filename))
run(BT / "zipalign", "-P", "16", "4", unsigned, aligned)
run(BT / "apksigner", "sign", "--ks", ROOT / "android-companion/debug.keystore",
    "--ks-pass", "pass:android", "--key-pass", "pass:android", "--ks-key-alias", "androiddebugkey", "--out", apk, aligned)
verification = run(BT / "apksigner", "verify", "--verbose", "--print-certs", apk)
baseline = run(BT / "apksigner", "verify", "--print-certs", base)
cert = lambda s: [line for line in s.splitlines() if "certificate SHA-256 digest:" in line]
assert cert(verification) and cert(verification) == cert(baseline)
run(BT / "zipalign", "-c", "-P", "16", "4", apk)
with zipfile.ZipFile(base) as original, zipfile.ZipFile(apk) as candidate:
    names = {n for n in original.namelist() if not signature(n)}
    assert names == {n for n in candidate.namelist() if not signature(n)}
    assert {n for n in names if original.read(n) != candidate.read(n)} == {"classes2.dex"}
record = dict(sha256=sha(apk), baseSha256=sha(base), changedEntries=["classes2.dex"],
              certificateMatched=True, installed=False, experimentalTransportEnabled=False)
(out / "verification.json").write_text(json.dumps(record, indent=2)+"\n")
print(verification)
print(json.dumps(record, indent=2))
