#!/usr/bin/env python3
"""Bind a generated debug APK registry to verified candidate bytes, not stale staging."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'engines/tools'))
import armsx2_build_identity as identity


def stage(root, core_dir, decoded):
    lock = json.loads((root / 'engines/armsx2-source-lock.json').read_text())
    registry_path = decoded / 'assets/phase2-engine-registry.json'
    registry = json.loads(registry_path.read_text())
    rows = [row for row in registry['engines'] if row['id'] == 'armsx2']
    if len(rows) != 1 or rows[0]['source']['commit'] != lock['core']['commit']:
        raise ValueError('PS2 candidate source commit differs from generated registry')
    row = rows[0]
    if row['shipped'] is not False:
        raise ValueError('PS2 candidate cannot update a shipped registry')
    for name, pages in [('armsx2', 4096), ('armsx2_16k', 16384)]:
        source = core_dir / (name + '_libretro.so')
        identity.verify(root, source, pages)
        packaged = decoded / 'lib/arm64-v8a' / ('liblucent_core_' + name + '.so')
        if identity.sha256(source) != identity.sha256(packaged):
            raise ValueError('PS2 packaged bytes differ from verified candidate')
    row['build'].update(
        proofArtifactSha256=identity.sha256(core_dir / 'armsx2_libretro.so'),
        proofArtifactPath='lib/arm64-v8a/liblucent_core_armsx2.so',
        reproducible=False,
        notes='Debug qualification inputs: both page-specific compiler receipts match locked sources and packaged bytes. Not normal-staging promotion, independent reproducibility, performance or release acceptance.')
    registry_path.write_text(json.dumps(registry, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--core-dir', type=Path, required=True)
    parser.add_argument('--decoded', type=Path, required=True)
    args = parser.parse_args()
    stage(args.root, args.core_dir, args.decoded)
