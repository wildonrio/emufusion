package com.thorium.preview.cheats.sources;

import com.thorium.lucent.cheats.Cheat;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** One downloaded cheat with its provenance and how the engine receives it. */
public final class DownloadedCheat {
    public static final String DELIVERY_LIVE = "live";
    public static final String DELIVERY_BOOT = "boot";
    public static final String DELIVERY_UNSUPPORTED = "unsupported";

    public final Cheat cheat;
    /** The {@link CheatSourceRegistry} id the row came from. */
    public final String source;
    /** {@code live}, {@code boot} or {@code unsupported}. */
    public final String delivery;
    /** Lower-case tags such as {@code widescreen}, {@code 60fps}, or a source group name. */
    public final List<String> tags;
    /** The upstream dialect of {@link Cheat#code} (for example {@code pnach}, {@code cwcheat}). */
    public final String engineFormat;

    public DownloadedCheat(Cheat cheat, String source, String delivery,
                           List<String> tags, String engineFormat) {
        if (cheat == null) throw new IllegalArgumentException("cheat required");
        this.cheat = cheat;
        this.source = source == null ? "" : source;
        this.delivery = normaliseDelivery(delivery);
        List<String> clean = new ArrayList<>();
        if (tags != null) {
            for (String tag : tags) {
                if (tag == null) continue;
                String value = tag.trim().toLowerCase(Locale.US);
                if (!value.isEmpty() && !clean.contains(value)) clean.add(value);
            }
        }
        this.tags = Collections.unmodifiableList(clean);
        this.engineFormat = engineFormat == null ? "" : engineFormat;
    }

    public boolean hasTag(String tag) {
        return tag != null && tags.contains(tag.trim().toLowerCase(Locale.US));
    }

    public static String normaliseDelivery(String delivery) {
        String clean = delivery == null ? "" : delivery.trim().toLowerCase(Locale.US);
        if (DELIVERY_LIVE.equals(clean) || DELIVERY_BOOT.equals(clean)) return clean;
        return DELIVERY_UNSUPPORTED;
    }

    @Override public String toString() {
        return "DownloadedCheat{" + cheat.id + " from " + source + " via " + delivery + "}";
    }
}
