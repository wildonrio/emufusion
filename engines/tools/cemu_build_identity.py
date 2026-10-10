#!/usr/bin/env python3
"""Verify the staged Wii U binary against its recorded, locked source inputs.

This is a configured-build receipt, not an independent reproducibility claim.
The receipt is kept beside the local .so, never included in user diagnostics.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def locked_sources(root, lock):
    sources = {}
    for row in lock['patches']:
        path = (Path(row.get('pathIsRelativeTo', str(root))) / row['path']).resolve()
        if str(path) in sources:
            raise ValueError('Duplicate Wii U locked source: ' + row['path'])
        actual = sha256(path)
        if actual != row['sha256']:
            raise ValueError('Wii U source differs from its lock: ' + row['path'])
        sources[str(path)] = actual
    if not sources:
        raise ValueError('Wii U source lock has no recorded inputs')
    return sources


def relocated(recorded, root, lock):
    """Receipt hashes keyed by today's paths.

    An input inside this repository that was recorded under an earlier
    checkout location (the folder was renamed from pegasus-lucent to
    emufusion) is matched by its repository-relative path. Hashes are not
    touched, and inputs in external trees (pathIsRelativeTo) must not move.
    """
    in_repo = {'/' + row['path']: str((root / row['path']).resolve())
               for row in lock['patches'] if not row.get('pathIsRelativeTo')}
    result = {}
    for key, value in recorded.items():
        target = next((path for suffix, path in in_repo.items() if key.endswith(suffix)), key)
        result[target] = value
    return result


def verify(root, core):
    root = root.resolve()
    lock = json.loads((root / 'engines/cemu-source-lock.json').read_text())
    receipt = core.with_suffix(core.suffix + '.build.json')
    if not receipt.is_file():
        raise ValueError('Wii U build identity missing; verify a current source build: ' + str(core))
    data = json.loads(receipt.read_text())
    actual = sha256(core)
    if (data.get('schemaVersion') != 1 or data.get('sha256') != actual or
            lock['artifact']['sha256'] != actual):
        raise ValueError('Wii U staged binary does not match its build receipt/source lock')
    if relocated(data.get('sourceHashes') or {}, root, lock) != locked_sources(root, lock):
        raise ValueError('Wii U binary predates the current locked sources; rebuild before packaging')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--core', type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(args.root, args.core)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
