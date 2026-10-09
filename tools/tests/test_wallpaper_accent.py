"""The "by wallpaper" accent grouping (backend derivation + theme wiring).

Three layers of coverage:

1. Structural (always run): source-scanning assertions in the established
   tools/tests house style that lock the contract between the three files that
   have to agree - WallpaperAccent (the algorithm), ImportManager (precompute
   and persist), and theme.qml (read, fall back, and drive the stick LEDs).

2. Executing (skipped when JDK17 is absent): compiles the real
   WallpaperAccent.java and drives it with synthetic wallpapers, so the
   properties the feature depends on - determinism, greyscale rejection, a
   genuinely complementary hue, and legibility on dark chrome - cannot regress
   silently. WallpaperAccent is platform neutral, so this needs no Android SDK.

3. Round trip: the derived accent is rendered exactly as ImportManager writes
   it into a Pegasus metafile, parsed back with the importer's own
   `key: value` prefix rule, and matched against the validator the theme
   actually contains (extracted from theme.qml rather than restated here).
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
UNIFIED = ROOT / "unified-android"
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
ACCENT_PATH = (UNIFIED / "src" / "com" / "thorium" / "lucent" / "metadata" /
               "WallpaperAccent.java")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


ACCENT = _read(ACCENT_PATH)
IMPORTER = _read(COMPANION / "ImportManager.java")
THEME = _read(ROOT / "theme" / "theme.qml")
TEST_SH = _read(UNIFIED / "test.sh")

METADATA_FIELD = "x-lucent-accent"
REGISTRY_FIELD = "accent"
REGISTRY_SOURCE_FIELD = "accentSource"

JAVA_HOME = Path(os.environ.get(
    "JAVA_HOME",
    "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"))
JAVAC = JAVA_HOME / "bin" / "javac"
JAVA = JAVA_HOME / "bin" / "java"


def metadata_field(stanza: str, key: str) -> str:
    """ImportManager.field(): first line with the `key:` prefix, trimmed."""
    prefix = key + ":"
    for line in stanza.split("\n"):
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


class AccentAlgorithmContractTest(unittest.TestCase):
    def test_field_names_are_declared_once_and_shared(self):
        self.assertIn(f'METADATA_FIELD = "{METADATA_FIELD}"', ACCENT)
        self.assertIn(f'REGISTRY_FIELD = "{REGISTRY_FIELD}"', ACCENT)
        self.assertIn(f'REGISTRY_SOURCE_FIELD = "{REGISTRY_SOURCE_FIELD}"', ACCENT)
        # The importer must reference the shared constants, never its own
        # spelling of the same field.
        self.assertIn("WallpaperAccent.METADATA_FIELD", IMPORTER)
        self.assertIn("WallpaperAccent.REGISTRY_FIELD", IMPORTER)
        self.assertIn("WallpaperAccent.REGISTRY_SOURCE_FIELD", IMPORTER)
        self.assertNotIn(f'"{METADATA_FIELD}"', IMPORTER)

    def test_result_is_deterministic_by_construction(self):
        # No randomness and no hash-order iteration: a rescan of an unchanged
        # wallpaper has to produce the identical accent.
        for forbidden in ("Math.random", "java.util.Random", "new Random",
                          "System.currentTimeMillis", "hashCode()",
                          "HashMap", "HashSet"):
            self.assertNotIn(forbidden, ACCENT)

    def test_low_information_pixels_are_discarded_before_the_histogram(self):
        self.assertIn("MIN_SATURATION = 0.18", ACCENT)
        self.assertIn("MIN_LIGHTNESS = 0.08", ACCENT)
        self.assertIn("MAX_LIGHTNESS = 0.94", ACCENT)
        self.assertIn("MIN_ALPHA = 128", ACCENT)
        body = ACCENT.split("public static String fromPixels", 1)[1]
        self.assertIn("if (lightness < MIN_LIGHTNESS || lightness > MAX_LIGHTNESS) continue;",
                      body)
        self.assertIn("if (saturation < MIN_SATURATION) continue;", body)

    def test_survivors_are_weighted_by_saturation_and_mid_lightness(self):
        body = ACCENT.split("public static String fromPixels", 1)[1]
        self.assertIn("double weight = saturation * midLightnessPreference(lightness);",
                      body)
        preference = ACCENT.split("private static double midLightnessPreference", 1)[1]
        preference = preference.split("private static", 1)[0]
        self.assertIn("(lightness - 0.5) / 0.5", preference)

    def test_the_accent_is_split_complementary_not_plain_opposition(self):
        self.assertIn("SPLIT_COMPLEMENT_DEGREES = 150.0", ACCENT)
        chooser = ACCENT.split("private static double chooseComplement", 1)[1]
        chooser = chooser.split("private static double midLightnessPreference", 1)[0]
        self.assertIn("baseHue + SPLIT_COMPLEMENT_DEGREES", chooser)
        self.assertIn("baseHue - SPLIT_COMPLEMENT_DEGREES", chooser)
        # The variant furthest from the wallpaper's other significant hues wins.
        self.assertIn("SECONDARY_SHARE", chooser)
        self.assertIn("positiveScore = Math.min(positiveScore, hueDistance(positive, hue));",
                      chooser)
        self.assertIn("negativeScore = Math.min(negativeScore, hueDistance(negative, hue));",
                      chooser)
        self.assertIn("return negativeScore > positiveScore ? negative : positive;",
                      chooser)

    def test_saturation_and_lightness_stay_inside_a_legible_band(self):
        self.assertIn("MIN_ACCENT_SATURATION = 0.55", ACCENT)
        self.assertIn("MAX_ACCENT_SATURATION = 0.86", ACCENT)
        self.assertIn("MIN_ACCENT_LIGHTNESS = 0.50", ACCENT)
        self.assertIn("MAX_ACCENT_LIGHTNESS = 0.72", ACCENT)
        self.assertIn("MIN_CONTRAST = 4.5", ACCENT)
        self.assertIn('UI_BACKGROUND_HEX = "#0d121a"', ACCENT)
        # The theme really does paint that surface behind accent text (it
        # spells it with a leading alpha byte, e.g. "#fa0d121a").
        self.assertIn("0d121a", THEME)

    def test_degenerate_wallpapers_report_no_accent(self):
        body = ACCENT.split("public static String fromPixels", 1)[1]
        self.assertIn("MIN_CHROMATIC_RATIO", body)
        self.assertIn("MIN_DOMINANT_SHARE", body)
        self.assertIn("if (sampled == 0 || weightSum <= 0) return null;", body)

    def test_the_host_suite_runs_the_algorithm_test(self):
        self.assertIn("com.thorium.lucent.metadata.WallpaperAccentTest", TEST_SH)
        self.assertTrue((UNIFIED / "test" / "com" / "thorium" / "lucent" /
                         "metadata" / "WallpaperAccentTest.java").is_file())


class ImporterPrecomputesTheAccentTest(unittest.TestCase):
    def test_the_accent_is_derived_where_the_wallpaper_is_enriched(self):
        block = IMPORTER.split("private void enrichBackground(", 1)[1]
        block = block.split("private static String wallpaperAccent(", 1)[0]
        self.assertIn("resolveBackground(game, cacheRoot, mediaRoot);", block)
        self.assertIn("game.accent = wallpaperAccent(game.background);", block)
        self.assertIn("game.accentSource = accentSourceKey(game.background);", block)

    def test_a_replaced_wallpaper_at_the_same_path_is_re_derived(self):
        block = IMPORTER.split("private static String accentSourceKey(", 1)[1]
        block = block.split("private static String wallpaperAccent(", 1)[0]
        self.assertIn("wallpaper.length()", block)
        self.assertIn("wallpaper.lastModified()", block)

    def test_derivation_downsamples_with_exact_power_of_two_subsampling(self):
        block = IMPORTER.split("private static String wallpaperAccent(", 1)[1]
        block = block.split("private void resolveBackground(", 1)[0]
        self.assertIn("options.inSampleSize *= 2", block)
        self.assertIn("WallpaperAccent.SAMPLE_EDGE", block)
        self.assertIn("WallpaperAccent.fromPixels(pixels, width, height)", block)
        # A failed decode must never become an invented color.
        self.assertIn("return accent == null ? \"\" : accent;", block)
        self.assertIn("sample.recycle()", block)

    def test_every_library_update_backfills_rows_that_were_never_evaluated(self):
        self.assertIn("registryChanged |= refreshWallpaperAccents(registry);", IMPORTER)
        block = IMPORTER.split("private static boolean refreshWallpaperAccents(", 1)[1]
        block = block.split("private static boolean hydrateRegistryFromExistingMetadata", 1)[0]
        # Keyed by the wallpaper the accent came from, so an unchanged library
        # never decodes an image twice and a browsing session never decodes at all.
        self.assertIn("row.has(WallpaperAccent.REGISTRY_SOURCE_FIELD)", block)
        self.assertIn("String key = accentSourceKey(background);", block)
        self.assertIn("key.equals(row.optString(WallpaperAccent.REGISTRY_SOURCE_FIELD))",
                      block)
        self.assertIn("row.put(WallpaperAccent.REGISTRY_FIELD, wallpaperAccent(background));",
                      block)
        self.assertIn("row.put(WallpaperAccent.REGISTRY_SOURCE_FIELD, key);", block)

    def test_the_accent_is_written_into_the_generated_metadata(self):
        block = IMPORTER.split("private boolean writeMetadata(", 1)[1]
        block = block.split("private static boolean refreshWallpaperAccents(", 1)[0]
        self.assertIn("String accent = WallpaperAccent.sanitize(", block)
        self.assertIn('out.append(WallpaperAccent.METADATA_FIELD).append(": ")', block)

    def test_a_stored_accent_survives_a_registry_loss(self):
        block = IMPORTER.split("private static boolean hydrateRegistryFromExistingMetadata",
                               1)[1]
        block = block.split("private static boolean ensureBackgroundProvenance", 1)[0]
        # Both hydration paths - the row rebuilt from a metafile and the merge
        # into an existing row - re-read the stored accent instead of decoding.
        self.assertEqual(
            2, block.count("field(stanza, WallpaperAccent.METADATA_FIELD)"))
        self.assertEqual(
            2, block.count("WallpaperAccent.sanitize("))
        self.assertIn("row.put(WallpaperAccent.REGISTRY_FIELD, recoveredAccent);", block)
        self.assertIn("row.put(WallpaperAccent.REGISTRY_FIELD, storedAccent);", block)

    def test_the_registry_row_round_trips_through_the_imported_game(self):
        self.assertIn("String accent = \"\";", IMPORTER)
        self.assertIn("String accentSource = \"\";", IMPORTER)
        self.assertIn("value.put(WallpaperAccent.REGISTRY_FIELD, accent);", IMPORTER)
        self.assertIn("value.put(WallpaperAccent.REGISTRY_SOURCE_FIELD, accentSource);",
                      IMPORTER)
        self.assertIn("game.accent = WallpaperAccent.sanitize(", IMPORTER)


class ThemeWallpaperGroupingTest(unittest.TestCase):
    def test_the_grouping_accepts_the_wallpaper_value(self):
        self.assertIn('property string accentGrouping: "system" '
                      '// family, system, wallpaper', THEME)
        self.assertIn('return ["family", "system", "wallpaper"]', THEME)
        normalizer = THEME.split("function normalizedAccentGrouping(value) {", 1)[1]
        normalizer = normalizer.split("}", 1)[0]
        self.assertIn('if (value === "family") return "family"', normalizer)
        self.assertIn('if (value === "wallpaper") return "wallpaper"', normalizer)
        self.assertIn('return "system"', normalizer)
        # Persisted values go through the same normalizer, so an unknown or
        # hand-edited setting can never leave the theme in a fourth mode.
        self.assertIn(
            'normalizedAccentGrouping(String(api.memory.get("lucentAccentGrouping")))',
            THEME)
        self.assertIn("accentGrouping = normalizedAccentGrouping(value)", THEME)

    def test_the_settings_row_offers_all_three_groupings(self):
        self.assertIn('"BY WALLPAPER"', THEME)
        self.assertIn('"BY SYSTEM"', THEME)
        self.assertIn('"BY PLATFORM FAMILY"', THEME)
        self.assertIn("cycleAccentGrouping(direction === 0 ? 1 : direction)", THEME)
        self.assertIn("By platform family, per system, "
                      "or each game's wallpaper complement", THEME)

    def test_the_theme_only_reads_a_precomputed_value(self):
        reader = THEME.split("function storedWallpaperAccent(game) {", 1)[1]
        reader = reader.split("\n    }", 1)[0]
        self.assertIn('game.extra["lucent-accent"]', reader)
        # No image, canvas, or pixel work anywhere in the resolution path.
        for forbidden in ("ShaderEffect", "grabToImage", "Canvas", "getContext"):
            self.assertNotIn(forbidden, reader)

    def test_a_missing_accent_falls_back_to_the_system_accent(self):
        block = THEME.split("function accentForGame(game) {", 1)[1]
        block = block.split("\n    }", 1)[0]
        self.assertIn('if (accentGrouping === "wallpaper") {', block)
        self.assertIn('if (wallpaperAccent !== "") return wallpaperAccent', block)
        self.assertIn("return index >= 0 ? systemModel.get(index).accent : root.accent",
                      block)
        # The system palette stays live underneath, so the fallback is a real
        # per-system hue and not a neutral placeholder.
        self.assertIn('return accentGrouping === "family" ? "family" : "system"', THEME)
        self.assertIn("if (baseAccentGrouping() === \"system\") {", THEME)

    def test_the_stick_leds_receive_the_identical_resolved_accent(self):
        binding = THEME.split("property color accent: {", 1)[1]
        binding = binding.split("\n    }", 1)[0]
        self.assertIn('accentGrouping === "wallpaper" && !showSystemBackdrop', binding)
        self.assertIn("storedWallpaperAccent(activeGame)", binding)
        self.assertIn("return systemModel.get(displaySystemIndex).accent", binding)
        # /led is fed by colorByteHex of that same accent, and any change to it
        # re-commits, so the sticks track the on-screen color exactly.
        led = THEME.split("function selectedLedColor() {", 1)[1]
        led = led.split("\n    }", 1)[0]
        self.assertIn("colorByteHex(accent.r) + colorByteHex(accent.g) + "
                      "colorByteHex(accent.b)", led)
        self.assertIn("onAccentChanged: {\n        if (systemLedEnabled) "
                      "systemLedCommit.restart()", THEME)
        self.assertIn('requestPreviewEndpoint("led?enabled=1&brightness="', THEME)
        self.assertIn('"&color=" + selectedLedColor()', THEME)

    def test_the_custom_hsl_editor_still_works_for_family_and_system(self):
        # The editor targets the base palette in all three modes; in wallpaper
        # mode that palette is the fallback layer, so editing stays meaningful.
        for function in ("accentTargets", "accentTargetLabel",
                         "loadAccentEditorTarget", "storeAccentEditorColor",
                         "resetAccentEditorColor", "resolvedAccentForSystem"):
            block = THEME.split(f"function {function}(", 1)[1]
            block = block.split("\n    }", 1)[0]
            self.assertIn("baseAccentGrouping()", block,
                          f"{function} must resolve through the base grouping")
        self.assertIn("Games use their wallpaper complement; "
                      "edit the system fallback", THEME)


HARNESS = r'''
import com.thorium.lucent.metadata.WallpaperAccent;

/** Drives the real accent derivation with synthetic wallpapers. */
public final class WallpaperAccentHarness {
    static final int W = 240;
    static final int H = 135;

    static void check(boolean ok, String label) {
        if (!ok) throw new AssertionError("FAIL: " + label);
    }

    public static void main(String[] args) {
        // Deterministic: repeated passes, a fresh buffer, and the same
        // wallpaper at another resolution all agree.
        String first = WallpaperAccent.fromPixels(fill(24, 0.72, 0.40, W, H), W, H);
        check(first != null, "a saturated wallpaper resolves an accent");
        for (int pass = 0; pass < 8; pass++)
            check(first.equals(WallpaperAccent.fromPixels(
                    fill(24, 0.72, 0.40, W, H), W, H)), "deterministic pass " + pass);
        check(first.equals(WallpaperAccent.fromPixels(
                fill(24, 0.72, 0.40, 1920, 1080), 1920, 1080)),
                "stride sampling is resolution independent");

        // Complementary, and never a near-miss of the source hue.
        for (int hue = 0; hue < 360; hue += 15) {
            String accent = WallpaperAccent.fromPixels(
                    fill(hue, 0.70, 0.42, W, H), W, H);
            check(accent != null, "hue " + hue + " resolves");
            double distance = WallpaperAccent.hueDistance(
                    WallpaperAccent.hueOf(accent), hue);
            check(distance > 120.0, "hue " + hue + " distance " + distance + " > 120");
            check(distance < 175.0, "hue " + hue + " distance " + distance + " < 175");
            check(WallpaperAccent.contrastAgainstChrome(accent) >= WallpaperAccent.MIN_CONTRAST,
                    "hue " + hue + " accent " + accent + " is legible");
        }

        // Degenerate wallpapers report nothing so the caller can fall back.
        check(WallpaperAccent.fromPixels(fill(0, 0.0, 0.50, W, H), W, H) == null,
                "flat grey has no hue");
        check(WallpaperAccent.fromPixels(fill(190, 0.10, 0.50, W, H), W, H) == null,
                "near-grey is below the chroma floor");
        check(WallpaperAccent.fromPixels(greyRamp(), W, H) == null,
                "a greyscale ramp has no hue");
        check(WallpaperAccent.fromPixels(new int[W * H], W, H) == null,
                "a transparent buffer has no hue");
        check(WallpaperAccent.fromPixels(null, W, H) == null,
                "a missing wallpaper has no hue");

        // The value the importer persists.
        System.out.println("ACCENT=" + first);
        System.out.println("FIELD=" + WallpaperAccent.METADATA_FIELD);
        System.out.println("REGISTRY=" + WallpaperAccent.REGISTRY_FIELD);
        System.out.println("HARNESS_OK");
    }

    static int[] fill(double hue, double saturation, double lightness,
                      int width, int height) {
        int[] pixels = new int[width * height];
        java.util.Arrays.fill(pixels, argb(hue, saturation, lightness));
        return pixels;
    }

    static int[] greyRamp() {
        int[] pixels = new int[W * H];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++)
                pixels[y * W + x] = argb(0, 0.0, (x + 1.0) / (W + 1.0));
        return pixels;
    }

    static int argb(double hue, double saturation, double lightness) {
        double chroma = (1.0 - Math.abs(2.0 * lightness - 1.0)) * saturation;
        double sector = ((hue % 360.0) + 360.0) % 360.0 / 60.0;
        double second = chroma * (1.0 - Math.abs(sector % 2.0 - 1.0));
        double red = 0, green = 0, blue = 0;
        if (sector < 1) { red = chroma; green = second; }
        else if (sector < 2) { red = second; green = chroma; }
        else if (sector < 3) { green = chroma; blue = second; }
        else if (sector < 4) { green = second; blue = chroma; }
        else if (sector < 5) { red = second; blue = chroma; }
        else { red = chroma; blue = second; }
        double match = lightness - chroma / 2.0;
        return 0xff000000 | (byteOf(red + match) << 16) |
                (byteOf(green + match) << 8) | byteOf(blue + match);
    }

    static int byteOf(double value) {
        int scaled = (int) Math.round(value * 255.0);
        return scaled < 0 ? 0 : (scaled > 255 ? 255 : scaled);
    }
}
'''


@unittest.skipUnless(JAVAC.is_file() and JAVA.is_file(),
                     "JDK17 not available for the executing accent harness")
class AccentDerivationExecutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.mkdtemp(prefix="lucent-wallpaper-accent-")
        classes = Path(cls.workdir) / "classes"
        classes.mkdir()
        harness = Path(cls.workdir) / "WallpaperAccentHarness.java"
        harness.write_text(HARNESS, encoding="utf-8")
        compiled = subprocess.run(
            [str(JAVAC), "--release", "8", "-encoding", "UTF-8",
             "-d", str(classes), str(ACCENT_PATH), str(harness)],
            cwd=cls.workdir, text=True, capture_output=True)
        if compiled.returncode != 0:
            shutil.rmtree(cls.workdir, ignore_errors=True)
            raise AssertionError(f"javac failed:\n{compiled.stderr}")
        cls.result = subprocess.run(
            [str(JAVA), "-cp", str(classes), "WallpaperAccentHarness"],
            cwd=cls.workdir, text=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def values(self) -> dict:
        return dict(line.split("=", 1) for line in self.result.stdout.splitlines()
                    if "=" in line)

    def test_the_derivation_holds_its_properties(self):
        self.assertEqual(
            0, self.result.returncode,
            f"harness failed:\n{self.result.stdout}\n{self.result.stderr}")
        self.assertIn("HARNESS_OK", self.result.stdout)

    def test_the_metadata_field_round_trips_into_the_theme(self):
        self.assertEqual(0, self.result.returncode, self.result.stderr)
        values = self.values()
        accent = values["ACCENT"]
        self.assertEqual(METADATA_FIELD, values["FIELD"])
        self.assertEqual(REGISTRY_FIELD, values["REGISTRY"])

        # Rendered exactly as writeMetadata emits it, next to the fields it
        # sits beside, then read back with the importer's own prefix rule.
        stanza = ("game: Synthetic\n"
                  "file: /roms/nes/synthetic.nes\n"
                  "assets.background: /media/game-wallpapers/nes/synthetic.jpg\n"
                  "x-background-source: exact-wallpaper\n"
                  f"{METADATA_FIELD}: {accent}\n")
        self.assertEqual(accent, metadata_field(stanza, METADATA_FIELD))
        self.assertEqual("", metadata_field(stanza, "x-lucent-id"))

        # Pegasus drops the x- prefix, so the theme reads it as "lucent-accent"
        # and validates it with the pattern theme.qml actually contains.
        reader = THEME.split("function storedWallpaperAccent(game) {", 1)[1]
        reader = reader.split("\n    }", 1)[0]
        pattern = re.search(r"/(\^#\[0-9a-f\]\{6\}\$)/", reader)
        self.assertIsNotNone(pattern, "theme.qml validates the stored accent")
        self.assertRegex(accent, pattern.group(1))
        self.assertNotRegex("#dce4f2ff", pattern.group(1))


if __name__ == "__main__":
    unittest.main()
