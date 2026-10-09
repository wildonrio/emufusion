"""Install a reviewed source-built frontend kit for build-portable.sh.

This does not rebuild or qualify the libraries. It copies the exact reviewed
49-library set into generated build storage, never replaces an unknown kit,
and leaves release qualification to the existing build/runtime gates.
"""
import argparse
from pathlib import Path
import shutil
import tempfile

from verify_source_frontend import locked_payloads, verify_directory

PROJECT = Path(__file__).resolve().parents[1]


def install(source: Path, lock: Path, destination: Path):
    errors = verify_directory(source, lock)
    if errors:
        raise ValueError('; '.join(errors))
    if destination.exists():
        errors = verify_directory(destination, lock)
        if errors:
            raise ValueError('Refusing to overwrite an existing frontend kit: ' + '; '.join(errors))
        return 'already installed'
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Only temporary files created by this invocation are cleaned on failure.
    with tempfile.TemporaryDirectory(prefix='source-frontend-', dir=destination.parent) as temp:
        prepared = Path(temp) / 'kit'
        prepared.mkdir()
        for name in locked_payloads(lock):
            shutil.copy2(source / Path(name).name, prepared / Path(name).name)
        errors = verify_directory(prepared, lock)
        if errors:
            raise ValueError('Source kit changed while copying: ' + '; '.join(errors))
        if destination.exists():
            raise ValueError('Frontend destination appeared during staging; preserving it')
        prepared.rename(destination)
    return 'installed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=PROJECT / 'source-frontend-artifact-lock.json')
    parser.add_argument('--destination', type=Path, default=PROJECT / 'build/source-frontend')
    args = parser.parse_args()
    print('Source frontend: ' + install(args.source, args.lock, args.destination))


if __name__ == '__main__':
    main()
