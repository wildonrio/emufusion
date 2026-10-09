#!/usr/bin/env python3
"""Package the bounded N64 context-setup trial without claiming clean rebuilds."""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile

from package_spurs_trace import ROOT, SDK, digest, signature

BASE = '8b99a4d2320c7daf56512014685da1103b96c614ac3c96bddcd83b15c8675bb0'
APPROVED_BASES = (BASE, '3e09a8d3991a060d069134f2549396935d6cac18a56ce27f519d07ec2ec06cc7')
OLD_CORE = '4d1ddf5c2d0be9d70cc6dcd069fb598840e3aacbba1489ca005e683260c5bdf0'
NEW_CORE = '4f8024294eb5dd565a8c868f8929dcd39e04f36e761be13a7e9d0a8e4924f6ff'
MEMBER = 'lib/arm64-v8a/liblucent_core_mupen64plus_next.so'
PATCH = 'engines/patches/mupen64plus-next-context-setup.patch'
PATCH_SHA = '8396947b663386db0eb1358dd201c2bcc3005e6faf3fd64d010a1287ea7be066'
NOTE = 'assets/local-n64-context-setup-diagnostic.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--base-sha256', choices=APPROVED_BASES, default=BASE,
                        help='Pinned normal build; 3e09 retains the black-band crop fix.')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists():
        parser.error('output exists; refusing overwrite')
    base = ROOT / ('unified-android/build/lucent-3.2.16-phase2-phase3-qualification-' + args.base_sha256 + '.apk')
    core = ROOT / 'engines/build/work/mupen64plus-next-arm64-v8a/mupen64plus_next_gles3_libretro_android.so'
    assert digest(base.read_bytes()) == args.base_sha256
    assert digest(core.read_bytes()) == NEW_CORE
    assert digest((ROOT/PATCH).read_bytes()) == PATCH_SHA
    note = dict(purpose='LOCAL N64 CONTEXT-SETUP TRIAL; device qualification pending',
                baseApkSha256=args.base_sha256, coreSha256=NEW_CORE, sourcePatch=PATCH,
                patchSha256=PATCH_SHA, independentCleanBuilds=0,
                buildMethod='One pinned libretro.c translation unit recompiled and existing objects relinked',
                normalBuildToRestore=str(base.relative_to(ROOT)))
    out.mkdir(parents=True)
    with zipfile.ZipFile(base) as old:
        assert digest(old.read(MEMBER)) == OLD_CORE
        replacements = {MEMBER: core.read_bytes()}
        for name in ('assets/phase1-engine-artifacts.json', 'assets/engine-artifacts.json'):
            index = json.loads(old.read(name))
            changed = False
            for item in index['artifacts']:
                if item['engineId'] == 'mupen64plus-next':
                    assert item['sha256'] == OLD_CORE
                    item['sha256'] = NEW_CORE
                    changed = True
            if changed:
                replacements[name] = json.dumps(index, indent=2).encode()
        registry = json.loads(old.read('assets/engine-registry.json'))
        item = next(row for row in registry['engines'] if row['id'] == 'mupen64plus-next')
        item['build']['reproducible'] = False
        item['build']['todo'] = 'Local context-setup trial; independent clean rebuild proof and device qualification pending.'
        item['statusReason'] = 'Local incremental context-setup candidate; see local-n64-context-setup-diagnostic.json.'
        replacements['assets/engine-registry.json'] = json.dumps(registry, indent=2).encode()
        with zipfile.ZipFile(out/'unsigned.apk', 'w') as new:
            for entry in old.infolist():
                if not signature(entry.filename):
                    new.writestr(entry, replacements.get(entry.filename, old.read(entry.filename)))
            new.writestr(NOTE, json.dumps(note, indent=2))
    build_tools = SDK/'build-tools/36.0.0'
    subprocess.run([str(build_tools/'zipalign'), '-f', '4', str(out/'unsigned.apk'), str(out/'aligned.apk')], check=True)
    signed = out/'emufusion-n64-context-setup.apk'
    subprocess.run([str(build_tools/'apksigner'), 'sign', '--ks', str(ROOT/'android-companion/debug.keystore'),
                    '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--ks-key-alias', 'androiddebugkey',
                    '--out', str(signed), str(out/'aligned.apk')], check=True)
    subprocess.run([str(build_tools/'apksigner'), 'verify', '--verbose', str(signed)], check=True)
    with zipfile.ZipFile(base) as old, zipfile.ZipFile(signed) as new:
        changed = [n for n in old.namelist() if not signature(n) and old.read(n) != new.read(n)]
        added = [n for n in new.namelist() if n not in old.namelist() and not signature(n)]
        assert sorted(changed) == sorted(replacements) and added == [NOTE]
        print('Only changed payloads:', json.dumps(changed))
        print('All other payloads byte-identical; diagnostic note added.')
    print('APK:', signed)
    print('SHA256:', digest(signed.read_bytes()))


if __name__ == '__main__':
    main()
