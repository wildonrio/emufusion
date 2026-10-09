#!/usr/bin/env python3
"""Build the locked Android 3DS core, preserving unknown local changes.

The normal engine recipe uses this source build instead of the upstream 4 KiB
release binary. A matching artifact is compiler evidence, not runtime approval.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with Path(path).open('rb') as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
        return result.hexdigest()


def run(*args, **kwargs):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()


def verify_source(source, lock):
    if git(source, 'rev-parse', 'HEAD') != lock['core']['commit']:
        raise ValueError('Azahar source commit differs from the lock; source left untouched')
    status = git(source, 'submodule', 'status', '--recursive')
    # check_output.strip removes the first status space; inspect raw output here.
    raw = subprocess.check_output(['git', '-C', str(source), 'submodule', 'status', '--recursive'], text=True)
    if any(not line.startswith(' ') for line in raw.splitlines()):
        raise ValueError('Azahar recursive submodule checkout differs from its gitlink')
    observed = {line.split()[1]: line.split()[0] for line in status.splitlines()}
    expected = {row['path']: row['commit'] for row in lock['dependencies']}
    if observed != expected:
        raise ValueError('Azahar recursive dependency set differs from the lock')
    for row in lock['dependencies']:
        module = source / row['path']
        if (git(module, 'rev-parse', 'HEAD^{tree}') != row['gitTreeSha1'] or
                git(module, 'status', '--porcelain', '--untracked-files=no')):
            raise ValueError('Modified Azahar dependency: ' + row['path'])
    patch_row, = lock['patches']
    patch = ROOT / patch_row['path']
    if digest(patch) != patch_row['sha256']:
        raise ValueError('Azahar patch differs from locked input')
    dirty = git(source, 'diff', '--name-only', 'HEAD').splitlines()
    if dirty and dirty != ['src/common/error.cpp']:
        raise ValueError('Unexpected Azahar edits; source left untouched: ' + repr(dirty))
    # Compare the entire patched file, not just whether reverse-apply succeeds.
    with tempfile.TemporaryDirectory(prefix='azahar-patch-check-') as name:
        temp = Path(name)
        target = temp / 'src/common/error.cpp'
        target.parent.mkdir(parents=True)
        target.write_bytes(subprocess.check_output(['git', '-C', str(source), 'show', 'HEAD:src/common/error.cpp']))
        run('patch', '-p1', '-i', patch, cwd=temp)
        if not dirty:
            run('git', '-C', source, 'apply', '--check', patch)
            run('git', '-C', source, 'apply', patch)
        if digest(target) != digest(source / 'src/common/error.cpp'):
            raise ValueError('Unexpected edits in Azahar error.cpp; source left untouched')


def publish_artifact(candidate, destination, lock):
    actual = digest(candidate)
    if actual != lock['sourceBuild']['artifactSha256']:
        raise ValueError('Azahar build differs from tested artifact: ' + actual)
    if destination.exists() and digest(destination) != actual:
        previous = digest(destination)
        if previous != lock['referenceReleaseArtifact']['memberSha256']:
            raise ValueError('Unknown Azahar output differs; left untouched: ' + str(destination))
        backup = destination.with_name(destination.name + '.previous-' + previous)
        if backup.exists() and digest(backup) != previous:
            raise ValueError('Azahar backup differs; outputs left untouched')
        if not backup.exists():
            shutil.copy2(destination, backup)
        if digest(backup) != previous:
            raise ValueError('Azahar backup verification failed')
    candidate.replace(destination)
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    lock = json.loads((ROOT / 'engines/azahar-source-lock.json').read_text())
    stage = args.work.resolve()
    source, build = stage / 'source', stage / 'build'
    if not source.exists():
        source.mkdir(parents=True)
        run('git', 'init', '-q', source)
        run('git', '-C', source, 'remote', 'add', 'origin', lock['core']['repository'])
        run('git', '-C', source, 'fetch', '--depth=1', 'origin', lock['core']['commit'])
        run('git', '-C', source, 'checkout', '-q', '--detach', 'FETCH_HEAD')
        run('git', '-C', source, 'submodule', 'update', '--init', '--recursive', '--depth=1', '--jobs=4')
    verify_source(source, lock)
    ndk = args.sdk / 'ndk' / lock['sourceBuild']['ndkVersion']
    cmake = args.sdk / 'cmake/3.31.6/bin/cmake'
    ninja = args.sdk / 'cmake/3.31.6/bin/ninja'
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(lock['sourceDateEpoch']), TZ='UTC', LC_ALL='C', GIT_TAG_NAME=lock['core']['tag'])
    flags = f'-ffile-prefix-map={stage}=/usr/src/azahar -fdebug-prefix-map={stage}=/usr/src/azahar'
    configure = [cmake, '-S', source, '-B', build, '-G', 'Ninja',
        '-DCMAKE_MAKE_PROGRAM=' + str(ninja),
        '-DCMAKE_TOOLCHAIN_FILE=' + str(ndk / 'build/cmake/android.toolchain.cmake'),
        '-DANDROID_ABI=arm64-v8a', '-DANDROID_PLATFORM=android-23', '-DANDROID_STL=c++_static',
        '-DCMAKE_BUILD_TYPE=Release', '-DENABLE_LIBRETRO=ON', '-DENABLE_TESTS=OFF',
        '-DENABLE_BUILTIN_KEYBLOB=OFF', '-DCITRA_WARNINGS_AS_ERRORS=OFF',
        '-DCMAKE_C_FLAGS=' + flags, '-DCMAKE_CXX_FLAGS=' + flags,
        '-DCMAKE_SHARED_LINKER_FLAGS=-Wl,--build-id=none,-z,max-page-size=16384,-z,common-page-size=16384',
        '-DCMAKE_MODULE_LINKER_FLAGS=-Wl,--build-id=none,-z,max-page-size=16384,-z,common-page-size=16384']
    run(*configure, env=env)
    run(cmake, '--build', build, '--target', 'azahar_libretro', '--parallel', str(args.jobs), env=env)
    artifact = build / 'bin/Release/azahar_libretro.so'
    args.output.mkdir(parents=True, exist_ok=True)
    # Verify before publishing; never replace an existing core with a mismatched build.
    with tempfile.TemporaryDirectory(prefix='azahar-output-', dir=args.output) as name:
        candidate = Path(name) / 'azahar_libretro.so'
        run(ndk / 'toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip', '--strip-unneeded', '-o', candidate, artifact)
        destination = args.output / candidate.name
        actual = publish_artifact(candidate, destination, lock)
    shutil.copy2(source / 'license.txt', args.output / 'azahar-LICENSE.txt')
    print('Azahar pinned source build verified: ' + actual)


if __name__ == '__main__':
    main()
