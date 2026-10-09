package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.Cheat;

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
