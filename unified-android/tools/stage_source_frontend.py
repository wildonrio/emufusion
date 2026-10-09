"""Stage a complete reviewed source frontend in the ordinary APK build path.

Qualification-only explicit inputs; no inferred lock from APK assets and no
legacy binary-offset patching of newly linked code. The final one-app verifier
must receive the same host-side lock, and all other gates remain mandatory.
"""
import argparse
from pathlib import Path
import shutil

from verify_source_frontend import PREFIX, cohort, locked_payloads, verify_directory


def stage(source: Path, lock: Path, decoded: Path):
    errors = verify_directory(source, lock)
    if errors:
        raise ValueError('; '.join(errors))
    payloads = locked_payloads(lock)
    destination = decoded / PREFIX
    existing = {PREFIX+p.name for p in destination.glob('*.so')}
    if cohort(existing) != set(payloads):
        raise ValueError('decoded frontend and source cohort differ; refusing a partial migration')
    if source.resolve() == destination.resolve():
        raise ValueError('source frontend kit cannot be its own staging destination')
    for name in sorted(payloads):
        shutil.copy2(source / Path(name).name, decoded / name)
    # The decoded directory can contain engine libraries; only verify this cohort.
    for name in payloads:
        if (decoded / name).read_bytes() != (source / Path(name).name).read_bytes():
            raise ValueError('source frontend changed during staging: '+name)
    return len(payloads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--decoded', type=Path, required=True)
    args = parser.parse_args()
    print('Staged %d source frontend libraries (qualification only)' % stage(args.source, args.lock, args.decoded))


if __name__ == '__main__':
    main()
