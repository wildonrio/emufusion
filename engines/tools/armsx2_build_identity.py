#!/usr/bin/env python3
"""Prevent reuse of a PS2 engine compiled before the current locked patches.

Receipts accompany local compiler output, not runtime data. The recipe digest
is retained for attribution; reuse depends on locked sources/patches, page size,
and the actual binary bytes. Unrelated edits to another engine's recipe do not
invalidate this core.
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


def source_inputs(root):
    lock_path = root / 'engines/armsx2-source-lock.json'
    lock = json.loads(lock_path.read_text())
    patches = []
    for patch in lock['patches']:
        actual = sha256(root / patch['path'])
        if actual != patch['sha256']:
            raise ValueError('PS2 patch differs from its source lock: ' + patch['path'])
        patches.append(dict(path=patch['path'], sha256=actual))
    return dict(sourceLockSha256=sha256(lock_path), patches=patches)


def receipt_path(core):
    return core.with_suffix(core.suffix + '.build.json')


def make_receipt(root, core, pages, snapshot):
    if snapshot['sourceInputs'] != source_inputs(root):
        raise ValueError('PS2 locked sources changed during compilation')
    if snapshot['hostPageSize'] != pages or pages not in (4096, 16384):
        raise ValueError('PS2 build host-page size mismatch')
    if snapshot['recipeSha256'] != sha256(root/'engines/build_core.sh'):
        raise ValueError('PS2 recipe changed during compilation')
    return dict(schemaVersion=1, **snapshot, coreSha256=sha256(core))


def verify(root, core, pages):
    receipt = receipt_path(core)
    if not receipt.is_file():
        raise ValueError('PS2 build identity missing; rebuild the current locked core: ' + str(core))
    data = json.loads(receipt.read_text())
    if (data.get('schemaVersion') != 1 or data.get('hostPageSize') != pages or
            pages not in (4096, 16384) or data.get('sourceInputs') != source_inputs(root) or
            data.get('coreSha256') != sha256(core)):
        raise ValueError('PS2 cached core does not match current locked source/page size: ' + str(core))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('begin', 'finish', 'verify'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pages', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--core', type=Path)
    args = parser.parse_args()
    if args.action == 'begin':
        if args.pages not in (4096, 16384):
            raise ValueError('Unsupported PS2 host-page size')
        args.snapshot.write_text(json.dumps(dict(sourceInputs=source_inputs(args.root),
            recipeSha256=sha256(args.root/'engines/build_core.sh'),
            hostPageSize=args.pages), indent=2)+'\n')
    elif args.action == 'finish':
        data = make_receipt(args.root, args.core, args.pages,
                            json.loads(args.snapshot.read_text()))
        receipt_path(args.core).write_text(json.dumps(data, indent=2)+'\n')
    else:
        verify(args.root, args.core, args.pages)


if __name__ == '__main__':
    main()
