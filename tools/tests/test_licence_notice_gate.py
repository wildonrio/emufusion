"""Licence gate: no bundled third-party library may ship undocumented.

Qt 5.15.10 and OpenSSL 1.1.1t were packaged in every Lucent APK for several
releases while being named nowhere in `LICENSE`, `LICENSING.md`,
`SOURCE_OFFER.md`, `THIRD_PARTY_NOTICES.md` or `README.md`. Nothing tied the
set of libraries actually packaged to the set of libraries actually documented,
so the omission was invisible.

This binds the two. `unified-android/build.sh` runs a shell gate at package
time; the classification rules in that gate are the single source of truth and
are parsed back out of the script here, so a rule added to the build without a
matching notice - or a notice heading renamed out from under the build - fails
the suite rather than a release audit.

Three layers, in the established tools/tests house style:

1. Structural (always run): the build.sh gate exists and still runs, every
   notice heading it demands exists in THIRD_PARTY_NOTICES.md, and the
   documented library inventory covers everything the build allowlists.
2. Content: the Qt and OpenSSL entries carry the facts their licences require -
   version, licence identifier, upstream source, relinking rights - and do not
   restate the common Apache-2.0 error for pre-3.0 OpenSSL.
3. Binary cross-check (skipped when no decoded APK tree is present): the
   versions in the notices still match the strings in the packaged binaries,
   and the Qt Gamepad dependency the notes describe is still real.
"""

import fnmatch
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
BUILD_SH = ROOT / "unified-android" / "build.sh"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
LICENSING = ROOT / "LICENSING.md"
SOURCE_OFFER = ROOT / "SOURCE_OFFER.md"
README = ROOT / "README.md"
QT_NOTES = ROOT / "docs" / "qt-dependency-notes.md"
LGPL_TEXT = ROOT / "docs" / "licenses" / "LGPL-3.0.txt"
DECODED_LIBS = (
    ROOT / "unified-android" / "build" / "work" / "apk" / "lib" / "arm64-v8a"
)

# The exact versions the notices commit to. Both were read from the packaged
# binaries; see docs/qt-dependency-notes.md.
QT_VERSION = "5.15.10"
OPENSSL_VERSION = "1.1.1t"


def build_sh() -> str:
    return BUILD_SH.read_text(encoding="utf-8")


def gate_block() -> str:
    """The licence-gate section of build.sh, ending at the version checks."""
    text = build_sh()
    start = text.index("UNDOCUMENTED_LIBS=")
    end = text.index("PACKAGED_OPENSSL_VERSION=")
    return text[start:end]


def unwrapped(text: str) -> str:
    """Prose comparison that survives the 79-column wrapping of these files."""
    return re.sub(r"\s+", " ", text)


def notice_rules() -> "list[tuple[list[str], str]]":
    """(glob patterns, required notice heading) parsed out of the build gate."""
    return [
        ([pattern.strip() for pattern in patterns.split("|")], heading)
        for patterns, heading in re.findall(
            r"^\s*([^)\n]+)\)\s*notice_heading='([^']*)'",
            gate_block(),
            re.M,
        )
    ]


def exempt_patterns() -> "list[str]":
    """Library families the gate deliberately skips (Lucent's own, Pegasus)."""
    match = re.search(r"^\s*([^)\n]+)\)\s*continue ;;", gate_block(), re.M)
    assert match is not None, "the build gate no longer exempts any library"
    return [pattern.strip() for pattern in match.group(1).split("|")]


def required_heading(lib_name: str) -> "str | None":
    """Mirror of the build gate's case statement, driven by build.sh itself."""
    for pattern in exempt_patterns():
        if fnmatch.fnmatchcase(lib_name, pattern):
            return None
    for patterns, heading in notice_rules():
        if any(fnmatch.fnmatchcase(lib_name, pattern) for pattern in patterns):
            return heading
    return ""  # classified by nothing: undocumented


def allowlisted_libs() -> "list[str]":
    """Library names from build.sh's 4 KiB-alignment allowlist."""
    text = build_sh()
    start = text.index('ALLOWED_4K_LIBS="')
    body = text[start + len('ALLOWED_4K_LIBS="') :]
    return [line for line in body[: body.index('"')].split("\n") if line.strip()]


def packaged_libs() -> "list[str]":
    if not DECODED_LIBS.is_dir():
        return []
    return sorted(path.name for path in DECODED_LIBS.glob("*.so"))


def notice_headings() -> "set[str]":
    return {
        line.rstrip()
        for line in NOTICES.read_text(encoding="utf-8").split("\n")
        if line.startswith("#")
    }


def has_heading(heading: str) -> bool:
    return any(line.startswith(heading) for line in notice_headings())


class BuildGateStructureTest(unittest.TestCase):
    """The build actually refuses to package an undocumented library."""

    def test_build_runs_the_gate_and_fails_closed(self) -> None:
        block = gate_block()
        self.assertIn('NOTICES="$DECODED/assets/THIRD_PARTY_NOTICES.md"', build_sh())
        self.assertIn('for lib_path in "$DECODED/lib/arm64-v8a/"*.so', block)
        self.assertIn("exit 1", block)

    def test_gate_classifies_every_family_it_needs_to(self) -> None:
        rules = notice_rules()
        self.assertTrue(rules, "the build gate no longer maps libraries to notices")
        headings = {heading for _, heading in rules}
        self.assertIn("## The Qt Toolkit", headings)
        self.assertIn("## OpenSSL", headings)
        self.assertIn("## LLVM libc++", headings)

    def test_every_heading_the_gate_demands_exists(self) -> None:
        for _, heading in notice_rules():
            with self.subTest(heading=heading):
                self.assertTrue(
                    has_heading(heading),
                    f"build.sh requires a {heading!r} section that "
                    "THIRD_PARTY_NOTICES.md does not have",
                )

    def test_lgpl_text_is_packaged_with_the_binaries(self) -> None:
        self.assertIn(
            'cp "$ROOT_DIR/docs/licenses/LGPL-3.0.txt" '
            '"$DECODED/assets/LICENSE-LGPL-3.0.txt"',
            build_sh(),
            "LGPLv3 requires the licence text to travel with the Qt binaries",
        )
        text = LGPL_TEXT.read_text(encoding="utf-8")
        self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 3, 29 June 2007", text)
        self.assertIn("4. Combined Works.", text)

    def test_version_pins_are_enforced_at_build_time(self) -> None:
        text = build_sh()
        self.assertIn("PACKAGED_QT_VERSION=", text)
        self.assertIn("PACKAGED_OPENSSL_VERSION=", text)
        for marker in ("PACKAGED_QT_VERSION", "PACKAGED_OPENSSL_VERSION"):
            with self.subTest(marker=marker):
                self.assertRegex(
                    text,
                    rf'grep -q "[^"]*{marker}[^"]*" "\$NOTICES"',
                    f"{marker} is computed but never checked against the notices",
                )


class InventoryCoverageTest(unittest.TestCase):
    """Every library the build knows about maps to a notice."""

    def assert_all_covered(self, lib_names: "list[str]", source: str) -> None:
        undocumented = [
            name for name in lib_names if required_heading(name) == ""
        ]
        self.assertEqual(
            [],
            undocumented,
            f"{source} contains libraries with no THIRD_PARTY_NOTICES.md entry: "
            f"{undocumented}",
        )

    def test_alignment_allowlist_is_fully_documented(self) -> None:
        libs = allowlisted_libs()
        self.assertGreater(len(libs), 50, "the alignment allowlist failed to parse")
        self.assert_all_covered(libs, "build.sh's 4 KiB alignment allowlist")

    def test_decoded_apk_tree_is_fully_documented(self) -> None:
        libs = packaged_libs()
        if not libs:
            self.skipTest("no decoded APK tree; run unified-android/build.sh first")
        self.assert_all_covered(libs, "the decoded APK tree")

    def test_known_third_party_libraries_route_to_the_right_notice(self) -> None:
        expected = {
            "libQt5Core_arm64-v8a.so": "## The Qt Toolkit",
            "libQt5Gamepad_arm64-v8a.so": "## The Qt Toolkit",
            "libplugins_platforms_qtforandroid_arm64-v8a.so": "## The Qt Toolkit",
            "libqml_QtQuick.2_qtquick2plugin_arm64-v8a.so": "## The Qt Toolkit",
            "libqml_QtQuick_Timeline_qtquicktimelineplugin_arm64-v8a.so": (
                "### Qt Quick Timeline"
            ),
            "libcrypto.so": "## OpenSSL",
            "libssl.so": "## OpenSSL",
            "libc++_shared.so": "## LLVM libc++",
        }
        for lib_name, heading in expected.items():
            with self.subTest(lib=lib_name):
                self.assertEqual(heading, required_heading(lib_name))

    def test_lucent_and_pegasus_binaries_are_exempt(self) -> None:
        for lib_name in ("liblucent_core_mgba.so", "libpegasus-fe_arm64-v8a.so"):
            with self.subTest(lib=lib_name):
                self.assertIsNone(required_heading(lib_name))

    def test_an_undocumented_library_is_rejected(self) -> None:
        """The gate has to be capable of failing, or it proves nothing."""
        for lib_name in ("libbrotli.so", "libavcodec.so", "libfreetype.so"):
            with self.subTest(lib=lib_name):
                self.assertEqual(
                    "",
                    required_heading(lib_name),
                    f"{lib_name} would ship without any notice entry",
                )

    def test_every_packaged_qt_module_is_named_in_the_notice(self) -> None:
        """A blanket libQt5* rule would wave through Qt WebEngine or Qt Charts,
        which do not carry the plain LGPL terms the rest of Qt does."""
        modules = [
            name[len("lib") : -len("_arm64-v8a.so")]
            for name in allowlisted_libs() + packaged_libs()
            if name.startswith("libQt5") and name.endswith("_arm64-v8a.so")
        ]
        self.assertTrue(modules, "no Qt modules found to check")
        notices = NOTICES.read_text(encoding="utf-8")
        for module in sorted(set(modules)):
            with self.subTest(module=module):
                self.assertIn(module, notices)

    def test_the_build_enforces_the_qt_module_enumeration(self) -> None:
        self.assertIn('qt_module=${qt_module%_arm64-v8a.so}', build_sh())


class NoticeContentTest(unittest.TestCase):
    """The entries carry what LGPL-3.0 and the OpenSSL licence actually ask for."""

    def setUp(self) -> None:
        self.text = NOTICES.read_text(encoding="utf-8")
        self.prose = unwrapped(self.text)

    def test_qt_entry_states_version_licence_and_source(self) -> None:
        self.assertIn(f"Qt {QT_VERSION}", self.text)
        self.assertIn("Lesser General Public License version 3", self.prose)
        self.assertIn("LGPL-3.0", self.text)
        self.assertIn("code.qt.io/cgit/qt/qt5.git", self.text)
        self.assertIn(f"v{QT_VERSION}-lts-lgpl", self.text)

    def test_qt_entry_preserves_the_right_to_relink(self) -> None:
        """LGPL-3.0 s4: a recipient must be able to run their own Qt build."""
        self.assertIn("Relinking rights", self.text)
        for fact in ("SONAME", "lib/arm64-v8a/", "re-sign"):
            with self.subTest(fact=fact):
                self.assertIn(fact, self.text)

    def test_qt_quick_timeline_is_not_claimed_to_be_lgpl(self) -> None:
        """qtquicktimeline 5.15 ships no LGPL option; only GPL2/GPL3."""
        self.assertIn("Qt Quick Timeline", self.text)
        self.assertIn("GPL-3.0-or-later", self.text)
        self.assertIn("code.qt.io/cgit/qt/qtquicktimeline.git", self.text)

    def test_openssl_entry_uses_the_pre_3_licence(self) -> None:
        self.assertIn(f"OpenSSL {OPENSSL_VERSION}", self.text)
        self.assertIn("SSLeay", self.text)
        self.assertIn(f"OpenSSL_{OPENSSL_VERSION.replace('.', '_')}", self.text)
        openssl_section = self.text[self.text.index("## OpenSSL") :]
        openssl_section = openssl_section[: openssl_section.index("\n## ")]
        self.assertNotIn(
            "Apache",
            openssl_section.replace(
                "The\n  Apache-2.0 relicensing applies only from OpenSSL 3.0 onward", ""
            ),
            "Apache-2.0 covers OpenSSL 3.0 and later, not 1.1.1",
        )

    def test_libcxx_entry_names_the_llvm_exception(self) -> None:
        self.assertIn("Apache License 2.0 with the LLVM exception", self.text)


class CrossDocumentTest(unittest.TestCase):
    """The user-facing documents point at the notices instead of omitting Qt."""

    def test_licensing_names_qt_and_the_lgpl(self) -> None:
        text = unwrapped(LICENSING.read_text(encoding="utf-8"))
        self.assertIn(f"Qt toolkit, version {QT_VERSION}", text)
        self.assertIn("Lesser General Public License version 3", text)
        self.assertIn("LGPL-3.0", text)
        self.assertIn("docs/licenses/LGPL-3.0.txt", text)

    def test_licensing_resolves_the_gpl_only_ambiguity(self) -> None:
        """LICENSE's FSF boilerplate says "or later"; LICENSING.md says only."""
        text = unwrapped(LICENSING.read_text(encoding="utf-8"))
        self.assertIn("GPL-3.0-only", text)
        self.assertIn("any later version", text)
        self.assertIn("intended and governing license", text)

    def test_source_offer_covers_qt_and_openssl(self) -> None:
        text = SOURCE_OFFER.read_text(encoding="utf-8")
        self.assertIn(QT_VERSION, text)
        self.assertIn(OPENSSL_VERSION, text)
        self.assertIn("Replacing the bundled Qt", text)

    def test_readme_states_the_qt_lgpl_usage_prominently(self) -> None:
        text = unwrapped(README.read_text(encoding="utf-8"))
        self.assertIn("Qt toolkit", text)
        self.assertIn("Lesser General Public License version 3", text)

    def test_notes_record_the_open_compliance_decisions(self) -> None:
        text = QT_NOTES.read_text(encoding="utf-8")
        for decision in ("tyler-bam-ai", "wildonrio", "release-manifest.json"):
            with self.subTest(decision=decision):
                self.assertIn(decision, text)


class PackagedBinaryTest(unittest.TestCase):
    """Skipped without a decoded tree; otherwise the notices must still be true."""

    def read_lib(self, name: str) -> bytes:
        path = DECODED_LIBS / name
        if not path.is_file():
            self.skipTest(f"{name} is not present; run unified-android/build.sh first")
        return path.read_bytes()

    def test_packaged_qt_matches_the_documented_version(self) -> None:
        blob = self.read_lib("libQt5Core_arm64-v8a.so")
        found = re.search(rb"Qt (5\.\d+\.\d+)", blob)
        self.assertIsNotNone(found, "no Qt build string in the packaged libQt5Core")
        assert found is not None
        self.assertEqual(QT_VERSION, found.group(1).decode())

    def test_packaged_openssl_matches_the_documented_version(self) -> None:
        blob = self.read_lib("libcrypto.so")
        found = re.search(rb"OpenSSL (\d+\.\d+\.\d+[a-z]*)", blob)
        self.assertIsNotNone(found, "no OpenSSL version string in the packaged libcrypto")
        assert found is not None
        self.assertEqual(OPENSSL_VERSION, found.group(1).decode())

    def test_qt_gamepad_is_still_a_hard_frontend_dependency(self) -> None:
        """The notes say it cannot be dropped; that must stay true or be rewritten."""
        blob = self.read_lib("libpegasus-fe_arm64-v8a.so")
        linked = b"libQt5Gamepad_arm64-v8a.so\x00" in blob
        documented = "cannot be removed" in QT_NOTES.read_text(encoding="utf-8")
        self.assertEqual(
            linked,
            documented,
            "docs/qt-dependency-notes.md and libpegasus-fe disagree about "
            "whether libQt5Gamepad is a hard dependency",
        )


if __name__ == "__main__":
    unittest.main()
