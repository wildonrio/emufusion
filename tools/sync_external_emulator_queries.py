#!/usr/bin/env python3
"""Keeps AndroidManifest.xml's <queries> block in step with the emulator directory.

Android 11+ filters package queries for apps targeting API 30 and above: an
undeclared package is reported as "not installed" with no error and no prompt.
The Settings route picker is entirely built on that answer, so every package id
EmuFusion may ask about has to be declared, and the declaration has to be
derived from the same file the picker reads rather than maintained by hand.

Run with --write to regenerate the block, or with no arguments to check it.
tools/tests/test_external_emulator_routing.py runs the check, so a package id
added to engines/external-emulators.json without re-running this fails the suite
instead of silently becoming undetectable on a future target-SDK bump.
"""

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "engines" / "external-emulators.json"
MANIFEST = ROOT / "android-companion" / "AndroidManifest.xml"

BEGIN = "    <!-- BEGIN generated external-emulator queries -->"
END = "    <!-- END generated external-emulator queries -->"
INTEGRATION_PACKAGES = set()


def package_ids():
    """Every package id the picker may ask the device about, sorted."""
    document = json.loads(DIRECTORY.read_text(encoding="utf-8"))
    names = set()
    for emulator in document["emulators"]:
        names.update(emulator["packages"])
    # Optional frame-generation companions are queried through an exported,
    # read-only capability provider rather than the emulator picker.
    names.update(INTEGRATION_PACKAGES)
    return sorted(names)


def block():
    lines = [
        BEGIN,
        "    <!-- Package-visibility declarations. An app targeting Android 11",
        "         (API 30) or later can only see packages it declares here;",
        "         everything else answers \"not installed\" silently, which would",
        "         turn the Settings emulator picker into a dead end. The package",
        "         list is generated from engines/external-emulators.json by",
        "         tools/sync_external_emulator_queries.py - do not hand-edit.",
        "",
        "         The MAIN/LAUNCHER intent filter is not redundant with the list:",
        "         it is what makes a user-supplied CUSTOM emulator visible, since",
        "         a package chosen at runtime cannot appear in a static list.",
        "         QUERY_ALL_PACKAGES is deliberately not requested - Play treats",
        "         it as restricted, and these two declarations already answer the",
        "         only question EmuFusion asks. -->",
        "    <queries>",
        "        <intent>",
        "            <action android:name=\"android.intent.action.MAIN\" />",
        "            <category android:name=\"android.intent.category.LAUNCHER\" />",
        "        </intent>",
    ]
    for name in package_ids():
        lines.append('        <package android:name="%s" />' % name)
    lines.append("    </queries>")
    lines.append(END)
    return "\n".join(lines)


def replace(text, generated):
    start = text.find(BEGIN)
    stop = text.find(END)
    if start < 0 or stop < 0:
        raise SystemExit(
            "AndroidManifest.xml has no generated-queries markers; add\n"
            "%s\n%s\naround the block first." % (BEGIN, END))
    return text[:start] + generated + text[stop + len(END):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="rewrite the block instead of only checking it")
    arguments = parser.parse_args()

    generated = block()
    text = MANIFEST.read_text(encoding="utf-8")
    updated = replace(text, generated)
    if arguments.write:
        if updated != text:
            MANIFEST.write_text(updated, encoding="utf-8")
            print("Updated %s" % MANIFEST)
        else:
            print("Already up to date")
        return 0
    if updated != text:
        print("AndroidManifest.xml <queries> is stale. Run:\n"
              "  python3 tools/sync_external_emulator_queries.py --write",
              file=sys.stderr)
        return 1
    print("<queries> matches engines/external-emulators.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
