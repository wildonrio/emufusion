package com.thorium.lucent.metadata;

/**
 * Deterministic, complementary accent derivation from a game wallpaper.
 *
 * The accent is precomputed by the importer and persisted, so the theme never
 * touches an image while the owner is browsing. Everything here is integer and
 * double arithmetic over an ARGB buffer: no randomness, no hash-order
 * iteration, and no platform image APIs, so the same wallpaper always resolves
 * to the same accent across rescans, devices, and the host test suite.
 *
 * Pipeline:
 *
 *  1. Stride-sample the buffer down to roughly {@link #SAMPLE_EDGE} on its
 *     longest edge. A fixed integer stride is deterministic, unlike a filtered
 *     rescale whose rounding can differ between platform versions.
 *  2. Discard near-black, near-white and near-grey pixels; they carry no
 *     usable hue and would only drag the result toward mud. The survivors are
 *     weighted by saturation times a mid-lightness preference, so the image's
 *     chromatic character wins instead of its average.
 *  3. Take the dominant hue from a 36-bin histogram, refined by the circular
 *     mean of the winning bin and its two neighbours.
 *  4. Offer the two split-complementary candidates (base hue +/- 150 degrees)
 *     and keep whichever lands furthest from the wallpaper's other significant
 *     hues. Straight 180-degree opposition reads harsh and collides with the
 *     secondary hue that most artwork already places opposite its subject;
 *     split-complementary keeps the accent unmistakably "other" while staying
 *     harmonious, and choosing between the two variants by distance keeps it
 *     distinct on artwork that is already two-toned.
 *  5. Clamp saturation and lightness into a band that reads as UI accent text
 *     on EmuFusion's dark chrome, then raise lightness (and, if a deep blue still
 *     falls short, lower saturation) until the accent clears
 *     {@link #MIN_CONTRAST} against {@link #UI_BACKGROUND_HEX}.
 *
 * A wallpaper with no meaningful hue - greyscale, monochrome, or a hue soup
 * with no dominant family - returns {@code null}. Callers persist an empty
 * field for that case and the theme falls back to the game's system accent.
 */
public final class WallpaperAccent {
    /** Pegasus metafile field written by the importer and read by the theme. */
    public static final String METADATA_FIELD = "x-lucent-accent";
    /** Importer registry key holding the resolved accent. */
    public static final String REGISTRY_FIELD = "accent";
    /**
     * Importer registry key holding the identity (path, size, and modified
     * time) of the wallpaper the accent was derived from. Equality with the
     * current wallpaper means "already evaluated", so a library update never
     * decodes the same image twice - and a wallpaper replaced at the same path
     * still re-derives.
     */
    public static final String REGISTRY_SOURCE_FIELD = "accentSource";

    /** Longest edge, in pixels, that the histogram pass samples. */
    public static final int SAMPLE_EDGE = 96;
    /** Darkest UI surface an accent has to stay legible against. */
    public static final String UI_BACKGROUND_HEX = "#0d121a";
    /** Minimum WCAG contrast ratio against {@link #UI_BACKGROUND_HEX}. */
    public static final double MIN_CONTRAST = 4.5;
    /** Split-complementary offset applied to the wallpaper's dominant hue. */
    public static final double SPLIT_COMPLEMENT_DEGREES = 150.0;

    private static final int HUE_BINS = 36;
    private static final int MIN_ALPHA = 128;
    private static final double MIN_SATURATION = 0.18;
    private static final double MIN_LIGHTNESS = 0.08;
    private static final double MAX_LIGHTNESS = 0.94;
    /** Share of sampled pixels that must carry a usable hue. */
    private static final double MIN_CHROMATIC_RATIO = 0.08;
    /** Share of the chromatic weight the dominant hue cluster must hold. */
    private static final double MIN_DOMINANT_SHARE = 0.12;
    /** Weight, relative to the dominant bin, that makes a hue "significant". */
    private static final double SECONDARY_SHARE = 0.25;
    /** Hues this close to the dominant hue belong to it, not to a second one. */
    private static final double DOMINANT_SPAN_DEGREES = 30.0;

    private static final double MIN_ACCENT_SATURATION = 0.55;
    private static final double MAX_ACCENT_SATURATION = 0.86;
    private static final double MIN_ACCENT_LIGHTNESS = 0.50;
    private static final double MAX_ACCENT_LIGHTNESS = 0.72;
    /** Ceiling for the contrast-recovery pass; beyond this an accent bleaches. */
    private static final double CONTRAST_LIGHTNESS_CEILING = 0.86;
    /** Floor for the contrast-recovery pass on hues that cannot get brighter. */
    private static final double CONTRAST_SATURATION_FLOOR = 0.34;

    private WallpaperAccent() {}

    /**
     * Resolves the accent for one wallpaper.
     *
     * @param argb   packed ARGB pixels, row major
     * @param width  pixel width of {@code argb}
     * @param height pixel height of {@code argb}
     * @return {@code "#rrggbb"}, or {@code null} when the image carries no
     *         usable hue and the caller should fall back to the system accent
     */
    public static String fromPixels(int[] argb, int width, int height) {
        if (argb == null || width <= 0 || height <= 0 ||
                argb.length < width * height) return null;

        int stride = stride(width, height);
        double[] binWeight = new double[HUE_BINS];
        double[] binSin = new double[HUE_BINS];
        double[] binCos = new double[HUE_BINS];
        long sampled = 0;
        long chromatic = 0;
        double weightSum = 0;
        double saturationSum = 0;
        double lightnessSum = 0;

        for (int y = 0; y < height; y += stride) {
            int row = y * width;
            for (int x = 0; x < width; x += stride) {
                int pixel = argb[row + x];
                if (((pixel >>> 24) & 0xff) < MIN_ALPHA) continue;
                sampled++;
                double red = ((pixel >> 16) & 0xff) / 255.0;
                double green = ((pixel >> 8) & 0xff) / 255.0;
                double blue = (pixel & 0xff) / 255.0;
                double lightness = lightness(red, green, blue);
                if (lightness < MIN_LIGHTNESS || lightness > MAX_LIGHTNESS) continue;
                double saturation = saturation(red, green, blue, lightness);
                if (saturation < MIN_SATURATION) continue;
                chromatic++;

                double weight = saturation * midLightnessPreference(lightness);
                if (weight <= 0) continue;
                double hue = hue(red, green, blue);
                int bin = (int) (hue / (360.0 / HUE_BINS));
                if (bin >= HUE_BINS) bin = HUE_BINS - 1;
                double radians = Math.toRadians(hue);
                binWeight[bin] += weight;
                binSin[bin] += weight * Math.sin(radians);
                binCos[bin] += weight * Math.cos(radians);
                weightSum += weight;
                saturationSum += weight * saturation;
                lightnessSum += weight * lightness;
            }
        }

        // Greyscale, monochrome, and near-black artwork never reaches a
        // confident hue. Say so instead of inventing one.
        if (sampled == 0 || weightSum <= 0) return null;
        if (chromatic < sampled * MIN_CHROMATIC_RATIO) return null;

        int dominant = 0;
        for (int bin = 1; bin < HUE_BINS; bin++)
            if (binWeight[bin] > binWeight[dominant]) dominant = bin;

        double clusterWeight = 0;
        double clusterSin = 0;
        double clusterCos = 0;
        for (int offset = -1; offset <= 1; offset++) {
            int bin = wrapBin(dominant + offset);
            clusterWeight += binWeight[bin];
            clusterSin += binSin[bin];
            clusterCos += binCos[bin];
        }
        // An even spread across the wheel has no dominant family; a complement
        // of the average would be arbitrary.
        if (clusterWeight < weightSum * MIN_DOMINANT_SHARE) return null;
        if (clusterSin == 0 && clusterCos == 0) return null;
        double baseHue = normalizeDegrees(Math.toDegrees(Math.atan2(clusterSin, clusterCos)));

        double accentHue = chooseComplement(baseHue, binWeight, binSin, binCos,
                binWeight[dominant]);
        double meanSaturation = saturationSum / weightSum;
        double meanLightness = lightnessSum / weightSum;
        double accentSaturation = clamp(0.52 + 0.42 * meanSaturation,
                MIN_ACCENT_SATURATION, MAX_ACCENT_SATURATION);
        double accentLightness = clamp(0.46 + 0.30 * (1.0 - meanLightness),
                MIN_ACCENT_LIGHTNESS, MAX_ACCENT_LIGHTNESS);

        // Deep hues (blue above all) sit below the legibility floor at a
        // pleasant lightness. Brighten first, desaturate only if that is not
        // enough, so the accent never turns into a neon or a pastel by choice.
        while (accentLightness < CONTRAST_LIGHTNESS_CEILING &&
                contrastAgainstChrome(accentHue, accentSaturation, accentLightness) < MIN_CONTRAST)
            accentLightness = Math.min(CONTRAST_LIGHTNESS_CEILING, accentLightness + 0.01);
        while (accentSaturation > CONTRAST_SATURATION_FLOOR &&
                contrastAgainstChrome(accentHue, accentSaturation, accentLightness) < MIN_CONTRAST)
            accentSaturation = Math.max(CONTRAST_SATURATION_FLOOR, accentSaturation - 0.02);

        return hslHex(accentHue, accentSaturation, accentLightness);
    }

    /** True for the exact {@code "#rrggbb"} spelling this class emits. */
    public static boolean isAccent(String value) {
        if (value == null || value.length() != 7 || value.charAt(0) != '#') return false;
        for (int index = 1; index < 7; index++) {
            char digit = value.charAt(index);
            boolean hex = (digit >= '0' && digit <= '9') || (digit >= 'a' && digit <= 'f');
            if (!hex) return false;
        }
        return true;
    }

    /**
     * Normalizes a persisted accent for reuse. Anything this class would not
     * have written - including the uppercase and CSS-shorthand spellings a
     * hand-edited metafile might contain - is rejected rather than trusted.
     */
    public static String sanitize(String value) {
        if (value == null) return "";
        String trimmed = value.trim().toLowerCase(java.util.Locale.US);
        return isAccent(trimmed) ? trimmed : "";
    }

    /** Smallest angle, in degrees, between two hues. */
    public static double hueDistance(double left, double right) {
        double delta = Math.abs(normalizeDegrees(left) - normalizeDegrees(right)) % 360.0;
        return delta > 180.0 ? 360.0 - delta : delta;
    }

    /** Hue, in degrees, of a {@code "#rrggbb"} accent. */
    public static double hueOf(String hex) {
        int rgb = Integer.parseInt(hex.substring(1), 16);
        return hue(((rgb >> 16) & 0xff) / 255.0, ((rgb >> 8) & 0xff) / 255.0,
                (rgb & 0xff) / 255.0);
    }

    /** WCAG contrast ratio of a {@code "#rrggbb"} color against dark chrome. */
    public static double contrastAgainstChrome(String hex) {
        int rgb = Integer.parseInt(hex.substring(1), 16);
        return contrast(relativeLuminance(((rgb >> 16) & 0xff) / 255.0,
                ((rgb >> 8) & 0xff) / 255.0, (rgb & 0xff) / 255.0), chromeLuminance());
    }

    private static int stride(int width, int height) {
        int longest = Math.max(width, height);
        if (longest <= SAMPLE_EDGE) return 1;
        return (longest + SAMPLE_EDGE - 1) / SAMPLE_EDGE;
    }

    private static double chooseComplement(double baseHue, double[] binWeight,
                                           double[] binSin, double[] binCos,
                                           double dominantWeight) {
        double positive = normalizeDegrees(baseHue + SPLIT_COMPLEMENT_DEGREES);
        double negative = normalizeDegrees(baseHue - SPLIT_COMPLEMENT_DEGREES);
        double positiveScore = 180.0;
        double negativeScore = 180.0;
        for (int bin = 0; bin < HUE_BINS; bin++) {
            if (binWeight[bin] < dominantWeight * SECONDARY_SHARE) continue;
            if (binSin[bin] == 0 && binCos[bin] == 0) continue;
            double hue = normalizeDegrees(Math.toDegrees(Math.atan2(binSin[bin], binCos[bin])));
            if (hueDistance(hue, baseHue) < DOMINANT_SPAN_DEGREES) continue;
            positiveScore = Math.min(positiveScore, hueDistance(positive, hue));
            negativeScore = Math.min(negativeScore, hueDistance(negative, hue));
        }
        // Ties resolve to the clockwise variant so a rescan cannot flip the
        // accent of a wallpaper whose secondary hues are symmetric.
        return negativeScore > positiveScore ? negative : positive;
    }

    private static double midLightnessPreference(double lightness) {
        double distance = (lightness - 0.5) / 0.5;
        double preference = 1.0 - distance * distance;
        return preference < 0 ? 0 : preference;
    }

    private static double lightness(double red, double green, double blue) {
        return (Math.max(red, Math.max(green, blue)) +
                Math.min(red, Math.min(green, blue))) / 2.0;
    }

    private static double saturation(double red, double green, double blue,
                                     double lightness) {
        double max = Math.max(red, Math.max(green, blue));
        double min = Math.min(red, Math.min(green, blue));
        double delta = max - min;
        if (delta <= 0) return 0;
        return lightness > 0.5 ? delta / (2.0 - max - min) : delta / (max + min);
    }

    private static double hue(double red, double green, double blue) {
        double max = Math.max(red, Math.max(green, blue));
        double min = Math.min(red, Math.min(green, blue));
        double delta = max - min;
        if (delta <= 0) return 0;
        double hue;
        if (max == red) hue = (green - blue) / delta;
        else if (max == green) hue = (blue - red) / delta + 2.0;
        else hue = (red - green) / delta + 4.0;
        return normalizeDegrees(hue * 60.0);
    }

    private static String hslHex(double hue, double saturation, double lightness) {
        double q = lightness < 0.5 ? lightness * (1.0 + saturation) :
                lightness + saturation - lightness * saturation;
        double p = 2.0 * lightness - q;
        double normalized = normalizeDegrees(hue) / 360.0;
        int red = channelByte(hueChannel(p, q, normalized + 1.0 / 3.0));
        int green = channelByte(hueChannel(p, q, normalized));
        int blue = channelByte(hueChannel(p, q, normalized - 1.0 / 3.0));
        StringBuilder hex = new StringBuilder("#");
        appendByte(hex, red);
        appendByte(hex, green);
        appendByte(hex, blue);
        return hex.toString();
    }

    private static double hueChannel(double p, double q, double t) {
        double wrapped = t;
        if (wrapped < 0) wrapped += 1.0;
        if (wrapped > 1) wrapped -= 1.0;
        if (wrapped < 1.0 / 6.0) return p + (q - p) * 6.0 * wrapped;
        if (wrapped < 1.0 / 2.0) return q;
        if (wrapped < 2.0 / 3.0) return p + (q - p) * (2.0 / 3.0 - wrapped) * 6.0;
        return p;
    }

    private static int channelByte(double value) {
        int scaled = (int) Math.round(value * 255.0);
        return scaled < 0 ? 0 : (scaled > 255 ? 255 : scaled);
    }

    private static void appendByte(StringBuilder out, int value) {
        if (value < 16) out.append('0');
        out.append(Integer.toHexString(value));
    }

    private static double contrastAgainstChrome(double hue, double saturation,
                                                double lightness) {
        return contrastAgainstChrome(hslHex(hue, saturation, lightness));
    }

    private static double chromeLuminance() {
        int rgb = Integer.parseInt(UI_BACKGROUND_HEX.substring(1), 16);
        return relativeLuminance(((rgb >> 16) & 0xff) / 255.0,
                ((rgb >> 8) & 0xff) / 255.0, (rgb & 0xff) / 255.0);
    }

    private static double contrast(double first, double second) {
        double lighter = Math.max(first, second);
        double darker = Math.min(first, second);
        return (lighter + 0.05) / (darker + 0.05);
    }

    private static double relativeLuminance(double red, double green, double blue) {
        return 0.2126 * channelLuminance(red) + 0.7152 * channelLuminance(green) +
                0.0722 * channelLuminance(blue);
    }

    private static double channelLuminance(double value) {
        return value <= 0.03928 ? value / 12.92 :
                Math.pow((value + 0.055) / 1.055, 2.4);
    }

    private static int wrapBin(int bin) {
        return ((bin % HUE_BINS) + HUE_BINS) % HUE_BINS;
    }

    private static double normalizeDegrees(double degrees) {
        double wrapped = degrees % 360.0;
        return wrapped < 0 ? wrapped + 360.0 : wrapped;
    }

    private static double clamp(double value, double low, double high) {
        return value < low ? low : (value > high ? high : value);
    }
}
