"""Explicit identity gate for isolated source-built Qt/frontend qualification.

The caller supplies a reviewed host-side lock; APK contents cannot select it.
This substitutes source-build identity for legacy fixed-offset native patches,
not for manifest/DEX, branding, emulator completeness or runtime checks.
Normal builds continue to use the legacy gate until migration is qualified.
"""
import hashlib
import json
from pathlib import Path
import re
import zipfile

from verify_elf_alignment import load_alignments

PREFIX = 'lib/arm64-v8a/'
EXTRA = {'libpegasus-fe_arm64-v8a.so', 'libcrypto.so', 'libssl.so', 'libc++_shared.so'}

def cohort(names):
    return {n for n in names if n.startswith(PREFIX) and n.endswith('.so')
            and (Path(n).name.startswith(('libQt5', 'libplugins_', 'libqml_')) or Path(n).name in EXTRA)}

def locked_payloads(lock_path: Path):
    lock = json.loads(lock_path.read_text())
    if lock.get('format') != 1 or lock.get('scope') != 'isolated-source-frontend-qualification':
        raise ValueError('source frontend lock has an unsupported format/scope')
    payloads = lock.get('payloads')
    if (not isinstance(payloads, dict) or len(payloads) != 49 or cohort(payloads) != set(payloads)
            or not {PREFIX+n for n in EXTRA}.issubset(payloads)
            or any(n != PREFIX + Path(n).name for n in payloads)
            or any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in payloads.values())):
        raise ValueError('source frontend lock must pin the complete 49-library cohort')
    return payloads


def verify_directory(directory: Path, lock_path: Path):
    """Check an explicit flattened source kit before altering decoded payloads."""
    try:
        payloads = locked_payloads(lock_path)
        names = {PREFIX+p.name for p in directory.glob('*.so')}
        errors = []
        if names != set(payloads):
            errors.append('source frontend directory and locked cohort differ')
        for name, expected in payloads.items():
            path = directory / Path(name).name
            if not path.is_file():
                errors.append('missing source frontend library: '+name)
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                errors.append('source frontend hash mismatch: '+name)
            if min(load_alignments(data)) < 16384:
                errors.append('source frontend library is not 16KiB-aligned: '+name)
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return ['invalid source frontend qualification: '+str(error)]


def verify(apk: Path, lock_path: Path):
    try:
        payloads = locked_payloads(lock_path)
        errors = []
        with zipfile.ZipFile(apk) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                errors.append('source frontend APK contains duplicate entries')
            if cohort(archive.namelist()) != set(payloads):
                errors.append('source frontend APK and locked cohort differ')
            for name, expected in payloads.items():
                if name not in archive.namelist():
                    errors.append('missing source frontend library: '+name)
                    continue
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != expected:
                    errors.append('source frontend hash mismatch: '+name)
                if min(load_alignments(data)) < 16384:
                    errors.append('source frontend library is not 16KiB-aligned: '+name)
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile) as error:
        return ['invalid source frontend qualification: '+str(error)]
