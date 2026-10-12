package com.thorium.emufusion.metadata;

import com.thorium.emufusion.TestSupport;

/**
 * Synthetic-wallpaper coverage for the precomputed accent derivation.
 *
 * The images are generated arithmetically so the expectations describe the
 * algorithm rather than a fixture file: a dominant hue plus optional secondary
 * hues, greyscale, transparency, and the degenerate cases that must fall back
 * to the system accent instead of inventing a color.
 */
public final class WallpaperAccentTest {
    private static final int WIDTH = 320;
    private static final int HEIGHT = 180;

    public static void main(String[] args) {
        deterministic();
        complementIsFarFromSource();
        splitComplementAvoidsSecondaryHue();
        greyscaleAndMonochromeFallBack();
        transparentAndEmptyFallBack();
        everyHueStaysLegibleOnDarkChrome();
        sanitizeAcceptsOnlyEmittedSpelling();
        System.out.println("WallpaperAccentTest ok");
    }

    private static void deterministic() {
        int[] first = solid(28.0, 0.72, 0.42);
        int[] second = solid(28.0, 0.72, 0.42);
        String initial = WallpaperAccent.fromPixels(first, WIDTH, HEIGHT);
        TestSupport.truth(initial != null, "a saturated wallpaper resolves an accent");
        TestSupport.equal(initial, WallpaperAccent.fromPixels(first, WIDTH, HEIGHT),
                "a repeated pass over the same buffer is stable");
        TestSupport.equal(initial, WallpaperAccent.fromPixels(second, WIDTH, HEIGHT),
                "an identical wallpaper resolves the same accent");
        TestSupport.truth(WallpaperAccent.isAccent(initial),
                "the accent uses the exact #rrggbb spelling: " + initial);

        // A different wallpaper must not collapse onto the same accent.
        String other = WallpaperAccent.fromPixels(solid(210.0, 0.72, 0.42), WIDTH, HEIGHT);
        TestSupport.truth(other != null && !other.equals(initial),
                "distinct wallpapers resolve distinct accents");
    }

    private static void complementIsFarFromSource() {
        double[] sources = {0.0, 30.0, 95.0, 150.0, 205.0, 275.0, 330.0};
        for (double source : sources) {
            String accent = WallpaperAccent.fromPixels(
                    solid(source, 0.68, 0.45), WIDTH, HEIGHT);
            TestSupport.truth(accent != null, "hue " + source + " resolves an accent");
            double distance = WallpaperAccent.hueDistance(
                    WallpaperAccent.hueOf(accent), source);
            TestSupport.truth(distance > 120.0,
                    "hue " + source + " accent " + accent + " is complementary, not similar" +
                            " (distance " + distance + ")");
            TestSupport.truth(distance < 175.0,
                    "hue " + source + " accent " + accent + " stays split-complementary" +
                            " rather than harsh opposition (distance " + distance + ")");
        }
    }

    private static void splitComplementAvoidsSecondaryHue() {
        // Dominant red with a strong secondary at 150 degrees. The +150
        // candidate would land on that secondary, so the -150 variant wins.
        int[] pixels = twoTone(0.0, 150.0, 0.70);
        String accent = WallpaperAccent.fromPixels(pixels, WIDTH, HEIGHT);
        TestSupport.truth(accent != null, "a two-tone wallpaper resolves an accent");
        double hue = WallpaperAccent.hueOf(accent);
        TestSupport.truth(WallpaperAccent.hueDistance(hue, 150.0) > 45.0,
                "the accent avoids the wallpaper's secondary hue: " + accent);
        TestSupport.truth(WallpaperAccent.hueDistance(hue, 210.0) < 20.0,
                "the accent takes the free split-complementary variant: " + accent);
    }

    private static void greyscaleAndMonochromeFallBack() {
        TestSupport.equal(null, WallpaperAccent.fromPixels(greyscaleRamp(), WIDTH, HEIGHT),
                "a greyscale wallpaper has no hue to complement");
        TestSupport.equal(null, WallpaperAccent.fromPixels(solid(0.0, 0.0, 0.5), WIDTH, HEIGHT),
                "a flat grey wallpaper has no hue to complement");
        TestSupport.equal(null, WallpaperAccent.fromPixels(solid(40.0, 0.10, 0.5), WIDTH, HEIGHT),
                "a near-grey wallpaper is below the chroma floor");
        TestSupport.equal(null, WallpaperAccent.fromPixels(solid(200.0, 0.9, 0.02), WIDTH, HEIGHT),
                "a near-black wallpaper carries no usable hue");
        TestSupport.equal(null, WallpaperAccent.fromPixels(solid(200.0, 0.9, 0.98), WIDTH, HEIGHT),
                "a near-white wallpaper carries no usable hue");
        TestSupport.equal(null, WallpaperAccent.fromPixels(hueSoup(), WIDTH, HEIGHT),
                "an even spread across the wheel has no dominant family");

        // A mostly grey wallpaper with a small saturated logo is still grey.
        int[] pixels = solid(0.0, 0.0, 0.45);
        for (int index = 0; index < pixels.length / 40; index++)
            pixels[index] = argb(120.0, 0.9, 0.5);
        TestSupport.equal(null, WallpaperAccent.fromPixels(pixels, WIDTH, HEIGHT),
                "a stray chromatic sliver does not make a monochrome wallpaper colorful");
    }

    private static void transparentAndEmptyFallBack() {
        int[] transparent = new int[WIDTH * HEIGHT];
        TestSupport.equal(null, WallpaperAccent.fromPixels(transparent, WIDTH, HEIGHT),
                "a fully transparent buffer resolves no accent");
        TestSupport.equal(null, WallpaperAccent.fromPixels(null, WIDTH, HEIGHT),
                "a missing wallpaper resolves no accent");
        TestSupport.equal(null, WallpaperAccent.fromPixels(new int[4], 0, 0),
                "an empty wallpaper resolves no accent");
        TestSupport.equal(null, WallpaperAccent.fromPixels(new int[4], WIDTH, HEIGHT),
                "a truncated buffer resolves no accent");
    }

    private static void everyHueStaysLegibleOnDarkChrome() {
        for (int hue = 0; hue < 360; hue += 5) {
            for (double lightness : new double[]{0.18, 0.45, 0.80}) {
                String accent = WallpaperAccent.fromPixels(
                        solid(hue, 0.85, lightness), WIDTH, HEIGHT);
                TestSupport.truth(accent != null,
                        "hue " + hue + " at lightness " + lightness + " resolves an accent");
                double contrast = WallpaperAccent.contrastAgainstChrome(accent);
                TestSupport.truth(contrast >= WallpaperAccent.MIN_CONTRAST,
                        "accent " + accent + " from hue " + hue + " is legible on " +
                                WallpaperAccent.UI_BACKGROUND_HEX + " (contrast " + contrast + ")");
            }
        }
    }

    private static void sanitizeAcceptsOnlyEmittedSpelling() {
        String accent = WallpaperAccent.fromPixels(solid(200.0, 0.7, 0.4), WIDTH, HEIGHT);
        TestSupport.equal(accent, WallpaperAccent.sanitize(accent),
                "a freshly derived accent survives persistence unchanged");
        TestSupport.equal(accent, WallpaperAccent.sanitize("  " + accent.toUpperCase() + " "),
                "a hand-edited spelling normalizes to the emitted one");
        TestSupport.equal("", WallpaperAccent.sanitize("#abc"), "shorthand hex is rejected");
        TestSupport.equal("", WallpaperAccent.sanitize("red"), "color names are rejected");
        TestSupport.equal("", WallpaperAccent.sanitize("#12345g"), "non-hex digits are rejected");
        TestSupport.equal("", WallpaperAccent.sanitize(null), "a missing accent is rejected");
        TestSupport.truth(!WallpaperAccent.isAccent("#AABBCC"),
                "isAccent describes exactly what the importer writes");
    }

    private static int[] solid(double hue, double saturation, double lightness) {
        int[] pixels = new int[WIDTH * HEIGHT];
        int value = argb(hue, saturation, lightness);
        for (int index = 0; index < pixels.length; index++) pixels[index] = value;
        return pixels;
    }

    /** Two thirds of the canvas at {@code dominant}, one third at {@code secondary}. */
    private static int[] twoTone(double dominant, double secondary, double saturation) {
        int[] pixels = new int[WIDTH * HEIGHT];
        int first = argb(dominant, saturation, 0.45);
        int second = argb(secondary, saturation, 0.45);
        for (int index = 0; index < pixels.length; index++)
            pixels[index] = index % 3 == 0 ? second : first;
        return pixels;
    }

    private static int[] greyscaleRamp() {
        int[] pixels = new int[WIDTH * HEIGHT];
        for (int y = 0; y < HEIGHT; y++)
            for (int x = 0; x < WIDTH; x++)
                pixels[y * WIDTH + x] = argb(0.0, 0.0, (x + 1.0) / (WIDTH + 1.0));
        return pixels;
    }

    private static int[] hueSoup() {
        int[] pixels = new int[WIDTH * HEIGHT];
        for (int y = 0; y < HEIGHT; y++)
            for (int x = 0; x < WIDTH; x++)
                pixels[y * WIDTH + x] = argb(360.0 * x / WIDTH, 0.75, 0.45);
        return pixels;
    }

    private static int argb(double hue, double saturation, double lightness) {
        double chroma = (1.0 - Math.abs(2.0 * lightness - 1.0)) * saturation;
        double sector = ((hue % 360.0) + 360.0) % 360.0 / 60.0;
        double second = chroma * (1.0 - Math.abs(sector % 2.0 - 1.0));
        double red = 0;
        double green = 0;
        double blue = 0;
        if (sector < 1) { red = chroma; green = second; }
        else if (sector < 2) { red = second; green = chroma; }
        else if (sector < 3) { green = chroma; blue = second; }
        else if (sector < 4) { green = second; blue = chroma; }
        else if (sector < 5) { red = second; blue = chroma; }
        else { red = chroma; blue = second; }
        double match = lightness - chroma / 2.0;
        return 0xff000000 | (byteOf(red + match) << 16) | (byteOf(green + match) << 8) |
                byteOf(blue + match);
    }

    private static int byteOf(double value) {
        int scaled = (int) Math.round(value * 255.0);
        return scaled < 0 ? 0 : (scaled > 255 ? 255 : scaled);
    }
}
