"""Require same-build, same-input exact pixels across two RIFE transports.

Transport equivalence is not interpolation-quality or presentation acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path


def verify(first: Path, second: Path):
    manifests = [json.loads((p/'inference.json').read_text()) for p in (first, second)]
    identities = [json.loads((p/'identity.json').read_text()) for p in (first, second)]
    if manifests[0]['input_manifest'] != manifests[1]['input_manifest']:
        raise ValueError('different endpoint manifests')
    for field in ('native_library', 'flownet.param', 'flownet.bin'):
        if identities[0][field] != identities[1][field]:
            raise ValueError('different build/model: '+field)
    outputs = []
    for path, manifest in zip((first, second), manifests):
        data = (path/'generated.rgba').read_bytes()
        geometry = manifest['input_manifest']
        if len(data) != geometry['width']*geometry['height']*4:
            raise ValueError('incorrect image size')
        if hashlib.sha256(data).hexdigest() != manifest['generated_sha256']:
            raise ValueError('output identity mismatch')
        outputs.append(data)
    if outputs[0] != outputs[1]:
        raise ValueError('transport pixels differ')
    return {'transport_equivalent': True, 'image_quality_qualified': False,
            'presentation_qualified': False, 'sha256': manifests[0]['generated_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.first, args.second), indent=2))
