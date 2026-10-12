package com.thorium.preview.cheats.delivery;

import com.thorium.emufusion.cheats.Cheat;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * One catalogue row together with how it reaches the engine.
 *
 * <p>{@link Cheat} deliberately knows nothing about engines. The delivery
 * layer needs three more facts per row -- where it came from, whether the
 * packaged engine takes it live or only at boot, and the tags the downloader
 * attached (the "widescreen" tag drives the hack policy) -- and those live
 * here rather than on the model so the in-game panel and the persisted
 * selection keep working on plain cheats.
 *
 * <p>Pure Java: the boot writers and the session registry are proven on the
 * host, so nothing in this package may import Android or org.json.
 */
public final class DeliveryCheat {
    /** Applied to the running core through retro_cheat_set. */
    public static final String LIVE = "live";
    /** Written into the engine's own files before load; applies on the next launch. */
    public static final String BOOT = "boot";
    /** Listed, but the packaged engine has no path that consumes it yet. */
    public static final String UNSUPPORTED = "unsupported";

    private static final Pattern WIDESCREEN_NAME =
            Pattern.compile("(?i)(16:9|widescreen|wide screen|aspect)");
    /**
     * Community frame-rate unlocks: "60 FPS", "60fps", Cemu's "FPS++",
     * "Unlock framerate", "FPS unlock". A "30 FPS" lock never matches.
     */
    private static final Pattern FRAME_RATE_UNLOCK_NAME = Pattern.compile(
            "(?i)(\\b60\\s*-?\\s*fps\\b|\\b60\\s*frames|fps\\s*\\+\\+|" +
            "\\bunlock(ed)?\\s*(the\\s*)?(frame\\s*-?\\s*rate|fps)|" +
            "(frame\\s*-?\\s*rate|fps)\\s*unlock)");
    /** "60 FPS" said outright: preferred over a generic "unlock". */
    private static final Pattern SIXTY_FPS_NAME = Pattern.compile("(?i)(\\b60\\s*-?\\s*fps\\b|\\b60\\s*frames)");
    /**
     * Never an unlock, whatever a source tagged it: a code that puts the game
     * back ("Unlimited FPS [Default]", "Restore", "Normal") or, below, a lower
     * rate ("30 FPS [Fixed]", "20fps lock"). Sources tag every frame-rate
     * code "60fps", so the tag alone is not enough.
     */
    private static final Pattern REVERT_NAME = Pattern.compile(
            "(?i)(\\bdefault\\b|\\brestore|\\bnormal\\b|\\boriginal\\b)");
    private static final Pattern LOWER_RATE_NAME = Pattern.compile("(?i)\\b[1-5]?[0-9]\\s*-?\\s*(fps|frames)\\b");

    public final Cheat cheat;
    public final String source;
    public final String delivery;
    public final List<String> tags;
    public final String engineFormat;

    public DeliveryCheat(Cheat cheat, String source, String delivery,
                         List<String> tags, String engineFormat) {
        if (cheat == null) throw new IllegalArgumentException("cheat required");
        this.cheat = cheat;
        this.source = source == null ? "" : source.trim();
        this.delivery = normaliseDelivery(delivery);
        List<String> cleaned = new ArrayList<>();
        if (tags != null) {
            for (String tag : tags) {
                if (tag == null) continue;
                String value = tag.trim().toLowerCase(Locale.US);
                if (!value.isEmpty() && !cleaned.contains(value)) cleaned.add(value);
            }
        }
        this.tags = Collections.unmodifiableList(cleaned);
        this.engineFormat = engineFormat == null ? "" : engineFormat.trim().toLowerCase(Locale.US);
    }

    /** A row with no provenance beyond the catalogue it came from. */
    public static DeliveryCheat plain(Cheat cheat, String source, String delivery) {
        return new DeliveryCheat(cheat, source, delivery, null, "");
    }

    public DeliveryCheat withDelivery(String newDelivery) {
        return new DeliveryCheat(cheat, source, newDelivery, tags, engineFormat);
    }

    public String id() { return cheat.id; }

    public boolean isLive() { return LIVE.equals(delivery); }

    public boolean isBoot() { return BOOT.equals(delivery); }

    public boolean isUnsupported() { return UNSUPPORTED.equals(delivery); }

    public boolean hasTag(String tag) {
        return tag != null && tags.contains(tag.trim().toLowerCase(Locale.US));
    }

    /**
     * The widescreen policy's own test: a "widescreen" tag from the
     * downloader, or a name that says so in the ways cheat authors do.
     */
    public boolean isWidescreen() {
        return hasTag("widescreen") || WIDESCREEN_NAME.matcher(cheat.name).find();
    }

    /** A patch that lets the game run at 60 fps (or uncapped) instead of 30/20. */
    public boolean isFrameRateUnlock() {
        return frameRateUnlockRank() < Integer.MAX_VALUE;
    }

    /**
     * 0 for an explicit "60 FPS" code, 1 for another unlock by name, 2 for a
     * code only a source tagged; {@code Integer.MAX_VALUE} when it is not an
     * unlock at all.
     */
    public int frameRateUnlockRank() {
        String name = cheat.name == null ? "" : cheat.name;
        if (REVERT_NAME.matcher(name).find()) return Integer.MAX_VALUE;
        // "60 FPS (30 FPS cutscenes)" is still a 60 FPS code; a lower rate
        // with no 60 beside it is a lock.
        if (SIXTY_FPS_NAME.matcher(name).find()) return 0;
        if (LOWER_RATE_NAME.matcher(name).find()) return Integer.MAX_VALUE;
        if (FRAME_RATE_UNLOCK_NAME.matcher(name).find()) return 1;
        return hasTag("60fps") ? 2 : Integer.MAX_VALUE;
    }

    /**
     * What the panel shows. Boot rows say when they take effect, because a
     * switch that moves without a visible change otherwise reads as broken;
     * unsupported rows say why they cannot move.
     */
    public String displayDescription() {
        String base = cheat.description == null ? "" : cheat.description;
        if (isBoot()) return append(base, BOOT_NOTE);
        if (isUnsupported()) return append(base, UNSUPPORTED_NOTE);
        return base;
    }

    /** Same words as DownloadedCheatCodec, so a downloaded row is never annotated twice. */
    public static final String BOOT_NOTE = "applies on next launch";
    public static final String UNSUPPORTED_NOTE = "not applied by the packaged engine yet";

    /** The cheat as the panel should list it: same id and code, decorated text. */
    public Cheat displayCheat() {
        String description = displayDescription();
        if (description.equals(cheat.description)) return cheat;
        return new Cheat(cheat.id, cheat.name, description, cheat.code);
    }

    private static String append(String base, String note) {
        if (base.contains(note)) return base;
        return base.isEmpty() ? note : base + " • " + note;
    }

    static String normaliseDelivery(String delivery) {
        if (delivery == null) return "";
        String value = delivery.trim().toLowerCase(Locale.US);
        if (LIVE.equals(value) || BOOT.equals(value) || UNSUPPORTED.equals(value)) return value;
        return "";
    }

    @Override public String toString() {
        return "DeliveryCheat{" + cheat.id + " " + delivery + "}";
    }
}
