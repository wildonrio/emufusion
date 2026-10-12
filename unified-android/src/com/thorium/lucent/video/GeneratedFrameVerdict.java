package com.thorium.lucent.video;

import java.nio.ByteBuffer;

/**
 * Decides from a per-cell comparison whether a generated image is a genuine
 * motion-compensated frame. Each cell holds four bytes: |G-A|, |G-B|,
 * |G-(A+B)/2| and |A-B| (luma, scaled x4), for the generated image G between
 * real images A and B, sampled at the same points.
 *
 * <p>Only cells where the scene moved (A and B differ) carry evidence. A true
 * interpolation of moving content matches A in some of them and B in others
 * (a hard edge part-way along its path) or neither (shifted texture); a
 * duplicate matches one real image almost everywhere; a cross-fade matches
 * the 50/50 blend where it matches neither. A scene with too little motion
 * gives no evidence either way and is never counted as generated.</p>
 */
public final class GeneratedFrameVerdict {
    public static final int GENERATED = 1;
    public static final int DUPLICATE = 2;
    public static final int BLEND = 3;
    public static final int STATIC = 4;

    private GeneratedFrameVerdict() {}

    public static int classify(ByteBuffer cells, int cellCount, int movingMin,
                               int equalMax, int minMovingCells) {
        int moving = 0, equalA = 0, equalB = 0, blendOnly = 0;
        for (int i = 0; i < cellCount; ++i) {
            int base = i * 4;
            int ga = cells.get(base) & 0xff;
            int gb = cells.get(base + 1) & 0xff;
            int gm = cells.get(base + 2) & 0xff;
            int ab = cells.get(base + 3) & 0xff;
            if (ab < movingMin) continue;
            ++moving;
            boolean isA = ga < equalMax;
            boolean isB = gb < equalMax;
            if (isA) ++equalA;
            if (isB) ++equalB;
            if (!isA && !isB && gm < equalMax) ++blendOnly;
        }
        if (moving < minMovingCells) return STATIC;
        if (blendOnly * 10 > moving * 6) return BLEND;
        if (equalA * 20 > moving * 17 || equalB * 20 > moving * 17) return DUPLICATE;
        return GENERATED;
    }
}
