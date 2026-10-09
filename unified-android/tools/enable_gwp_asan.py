#!/usr/bin/env python3
"""Opt a generated diagnostic manifest into Android's sampled heap checker.

This does not change target SDK, debuggability, or any rendering policy. It is
not memory-safety proof: GWP-ASan samples allocations and can miss a violation.
"""
import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ANDROID = "{http://schemas.android.com/apk/res/android}"


def enable(text: str) -> str:
    root = ET.fromstring(text)
    applications = root.findall("application")
    if len(applications) != 1:
        raise ValueError("expected exactly one application")
    # The apktool input uses this namespace prefix. Refuse an unknown spelling
    # rather than emitting an attribute whose namespace is undefined.
    if not re.search(r'xmlns:android\s*=\s*[\"\']http://schemas.android.com/apk/res/android[\"\']', text):
        raise ValueError("expected the Android namespace prefix")
    pattern = re.compile(r'<application\b(?:[^>\"\']|\"[^\"]*\"|\'[^\']*\')*>')
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("expected one unambiguous application opening tag")
    match = matches[0]
    opening = re.sub(r'\s+android:gwpAsanMode\s*=\s*(?:\"[^\"]*\"|\'[^\']*\')', '', match.group())
    opening = opening.replace("<application", '<application android:gwpAsanMode="always"', 1)
    result = text[:match.start()] + opening + text[match.end():]
    parsed = ET.fromstring(result)
    if parsed.find("application").get(ANDROID + "gwpAsanMode") != "always":
        raise ValueError("GWP-ASan attribute was not applied")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    original = args.manifest.read_text(encoding="utf-8")
    updated = enable(original)
    if updated != original:
        args.manifest.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
