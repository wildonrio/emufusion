"""Rebuild the aPS3e source a locked patch applies to, from the pinned archive.

Several closed PS3 diagnostics were reviewed against docs/qa "native-source"
snapshots: the pinned aPS3e archive with the locked patches applied in lock
order. Those local snapshots were removed by the build disk cleanup. Applying
the same patches to the same archive reproduces their bytes exactly (the
diagnostics' own SHA-256 pins confirm it), so the tests rebuild that state
instead of depending on the snapshot.

The archive is a git-ignored build input; without it the callers skip.
"""
import atexit
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMMIT = 'b5ae1af50d5e2f3b705506e7380a4504e086840b'
ARCHIVE = ROOT / 'engines/build/sources' / f'aps3e-{COMMIT}.tar.gz'
_PREFIX = f'aps3e-{COMMIT}'
_cache = {}


def available():
    return ARCHIVE.is_file()


def locked_patches():
    lock = json.loads((ROOT / 'engines/aps3e-source-lock.json').read_text())
    return [row['path'] for row in lock['patches'] if row['path'].endswith('.patch')]


def _touched(patch):
    return {line[len('+++ b/'):] for line in (ROOT / patch).read_text(errors='replace').splitlines()
            if line.startswith('+++ b/')}


def _pristine(extra):
    """Extract every file the locked patches touch (and `extra`) once per process."""
    key = ('pristine', tuple(sorted(extra)))
    if key in _cache:
        return _cache[key]
    wanted = set(extra)
    for patch in locked_patches():
        wanted |= _touched(patch)
    listing = set(subprocess.run(['tar', '-tzf', str(ARCHIVE)], check=True,
                                 capture_output=True, text=True).stdout.splitlines())
    members = sorted(f'{_PREFIX}/{name}' for name in wanted if f'{_PREFIX}/{name}' in listing)
    directory = tempfile.mkdtemp(prefix='aps3e-locked-')
    atexit.register(shutil.rmtree, directory, True)
    subprocess.run(['tar', '-xzf', str(ARCHIVE), '-C', directory, *members], check=True)
    _cache[key] = Path(directory) / _PREFIX
    return _cache[key]


def state_before(patch, extra=()):
    """Directory holding the archive plus every locked patch before `patch`.

    `patch` is a repository path such as 'engines/patches/aps3e-input-lifetime.patch'.
    `extra` names further archive files (relative to the archive root) to include.
    Each call returns a fresh copy the caller may modify.
    """
    patches = locked_patches()
    if patch not in patches:
        raise ValueError(f'{patch} is not in the locked aPS3e patch list')
    pristine = _pristine(tuple(extra))
    directory = Path(tempfile.mkdtemp(prefix='aps3e-state-'))
    atexit.register(shutil.rmtree, directory, True)
    root = directory / _PREFIX
    shutil.copytree(pristine, root)
    for earlier in patches[:patches.index(patch)]:
        subprocess.run(['git', 'apply', '--unsafe-paths', str(ROOT / earlier)],
                       cwd=root, check=True, capture_output=True)
    return root
