#!/usr/bin/env python3
"""Rewrite upstream user-facing branding without touching ABI identifiers.

EmuFusion currently consumes the pinned upstream Android binary, so its C++ and
QML ABI names (Pegasus.Model, PegasusProvider, the JNI class, and filenames)
must remain intact.  These equal-length edits are deliberately limited to
sentences a user can see.  Pegasus attribution remains in EmuFusion's splash,
About page, notices, and source offer.
"""

from pathlib import Path
import sys


VISIBLE_REPLACEMENTS = {
    # The pinned frontend is patched in place, so each replacement must retain
    # the source string's exact byte/code-unit length.  Each replacement is a
    # complete, naturally worded phrase of that exact length; padding after the
    # shorter EmuFusion name caused visible double spaces and broken grammar.
    "Exit Pegasus": "Close Lucent",
    "Pegasus Frontend, version": "Lucent Frontend - version",
    "Pegasus couldn't find any games on your device. If you have not set up "
    "Pegasus yet,":
        "Lucent could not find your games on your device. If you have not set "
        "up Lucent yet,",
    "When looking for games, Pegasus can use":
        "While looking for games, Lucent can use",
    "Pegasus tried to load the selected theme":
        "Lucent tried to load your selected theme",
    "Pegasus will look for collection files":
        "Lucent can search for collection files",
    "in both Pegasus and the launched app. Pegasus have permission for":
        "in Lucent and also in the launched app. Lucent has permission for",
    "name: Pegasus Grid": "name: Lucent Theme",
    "summary: The default grid theme of Pegasus":
        "summary: The default grid theme of Lucent.",

    # The frontend also embeds the original QML source.  Those strings are
    # split at source-level concatenation boundaries, so the complete runtime
    # sentence replacements above cannot match them.  Keep each corresponding
    # fragment byte-for-byte the same length while making the concatenated
    # result read naturally.
    "Pegasus couldn't find any games on your device. If you have not":
        "Lucent could not find any games on your device. If you have not",
    " set up Pegasus yet, you can find the documentation here: <i>%1</i>.":
        " configured Lucent yet, use the setup documentation here: <i>%1</i>.",
    "Some Android apps may not launch games unless you manually allow access ":
        "Lucent keeps all emulation inside this app. To read game files stored ou",
    "to the game's directory, in both Pegasus and the launched app. Pegasus ":
        "tside its private folder, Lucent needs access to each game's directory.",
    "have permission for the following locations:":
        " It currently has access to these locations:",
}


# These are user-reachable English source strings, not ABI identifiers or
# required upstream attribution.  Failing the build is safer than silently
# shipping a newly changed upstream resource under the old product name.
FORBIDDEN_VISIBLE_FRAGMENTS = (
    "Pegasus couldn't find any games on your device.",
    " set up Pegasus yet, you can find the documentation",
    "in both Pegasus and the launched app. Pegasus",
    "have permission for the following locations:",
)


def patch(path: Path) -> int:
    data = path.read_bytes()
    changes = 0
    for phrase, updated in VISIBLE_REPLACEMENTS.items():
        if len(updated) != len(phrase):
            raise RuntimeError(f"non-equal branding replacement: {phrase!r}")
        for encoding in ("utf-8", "utf-16le", "utf-16be"):
            before = phrase.encode(encoding)
            after = updated.encode(encoding)
            count = data.count(before)
            if count:
                data = data.replace(before, after)
                changes += count
    if not changes:
        raise RuntimeError("no user-facing upstream branding was found")
    for phrase in FORBIDDEN_VISIBLE_FRAGMENTS:
        for encoding in ("utf-8", "utf-16le", "utf-16be"):
            if phrase.encode(encoding) in data:
                raise RuntimeError(
                    f"user-facing upstream branding survived: {phrase!r}"
                )
    path.write_bytes(data)
    return changes


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_emufusion_branding.py <libpegasus-fe.so>")
    path = Path(sys.argv[1])
    if not path.is_file():
        raise SystemExit(f"missing frontend library: {path}")
    count = patch(path)
    print(f"Patched {count} user-facing upstream branding occurrence(s)")


if __name__ == "__main__":
    main()
