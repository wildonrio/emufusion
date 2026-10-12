#!/usr/bin/env python3
"""Zip the theme folder so identical content always gives identical bytes.

`zip -r` stores each file's modification and access times, so the bundled
theme's SHA-256 (and with it the installer's "bundled theme changed" check)
changed on every build even when no theme file had changed, and every update
re-installed an identical theme. Entries are sorted, timestamps fixed and
permissions normalized; only paths and contents decide the archive.

usage: zip_theme_deterministic.py THEME_DIR OUTPUT_ZIP
"""
import os
import sys
import zipfile

FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def main(theme_dir, output):
    entries = []
    for root, dirs, files in os.walk(theme_dir):
        dirs.sort()
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                raise SystemExit(f"refusing symlink in theme: {path}")
            entries.append(os.path.relpath(path, theme_dir).replace(os.sep, "/"))
    entries.sort()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in entries:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, so the permission bits below are honoured
            info.external_attr = 0o100644 << 16
            with open(os.path.join(theme_dir, name), "rb") as source:
                archive.writestr(info, source.read())


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
