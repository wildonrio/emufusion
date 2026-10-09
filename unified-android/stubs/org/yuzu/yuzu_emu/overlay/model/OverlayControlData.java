package org.yuzu.yuzu_emu.overlay.model;

import kotlin.Pair;

/**
 * One touch-overlay control in Eden's own on-screen layout. Lucent draws no
 * overlay -- the Thor has physical controls and the second screen is Lucent's
 * -- but Eden's JNI cache resolves the constructor and all six fields at load
 * time, including three {@code kotlin/Pair} positions. See {@link kotlin.Pair}
 * for why that type is declared locally.
 */
public final class OverlayControlData {
    public String id;
    public boolean enabled;
    public Pair portraitPosition;
    public Pair landscapePosition;
    public Pair foldablePosition;
    public float individualScale;

    public OverlayControlData(String id, boolean enabled, Pair portraitPosition,
                              Pair landscapePosition, Pair foldablePosition,
                              float individualScale) {
        this.id = id;
        this.enabled = enabled;
        this.portraitPosition = portraitPosition;
        this.landscapePosition = landscapePosition;
        this.foldablePosition = foldablePosition;
        this.individualScale = individualScale;
    }
}
