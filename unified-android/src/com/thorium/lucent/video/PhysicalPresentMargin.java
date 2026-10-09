package com.thorium.lucent.video;

/** Conservative conversion for VK_GOOGLE_display_timing present margins. */
public final class PhysicalPresentMargin {
    private PhysicalPresentMargin() {}

    /**
     * Converts the raw uint64_t value transported through a Java long.
     *
     * <p>Some Thor/Adreno timing rows wrap a small late margin through the
     * extension's unsigned field.  A wrapped magnitude of at most one refresh
     * is conservatively reported as zero headroom.  Larger unsigned values
     * remain invalid instead of being truncated or credited as margin.</p>
     */
    public static long normalize(long rawSignedNs, long refreshDurationNs) {
        if (refreshDurationNs <= 0L)
            throw new IllegalArgumentException(
                    "physical refresh duration is invalid");
        if (rawSignedNs >= 0L) return rawSignedNs;
        if (rawSignedNs >= -refreshDurationNs) return 0L;
        throw new IllegalArgumentException(
                "physical present margin exceeds bounded unsigned-wrap range" +
                " marginRawUnsigned=" + Long.toUnsignedString(rawSignedNs) +
                " refreshNs=" + refreshDurationNs);
    }
}
