package com.thorium.lucent.video;

import com.thorium.lucent.TestSupport;

public final class DualScreenLayoutTest {
    public static void main(String[] args) {
        checkDsScreenOrder();
        checkDsPhoneLayout();
        DualScreenLayout.Region top = DualScreenLayout.top(256, 384);
        DualScreenLayout.Region bottom = DualScreenLayout.bottom(256, 384);
        TestSupport.equal(0, top.top, "top screen begins at frame top");
        TestSupport.equal(192, top.height(), "top screen height");
        TestSupport.equal(192, bottom.top, "bottom screen begins at midpoint");
        TestSupport.equal(192, bottom.height(), "bottom screen height");
        int[] pixels = {
                10, 11, 20, 21,
                30, 31, 40, 41
        };
        int[] upload = DualScreenLayout.forGeneratorUpload(pixels, 2, 4);
        int[] expected = {
                20, 21, 10, 11,
                40, 41, 30, 31
        };
        TestSupport.equal(java.util.Arrays.toString(expected),
                java.util.Arrays.toString(upload),
                "each physical screen is vertically corrected without swapping screens");
        TestSupport.equal(10, pixels[0],
                "generator correction leaves the Canvas source untouched");
        try {
            DualScreenLayout.forGeneratorUpload(new int[3], 2, 4);
            throw new AssertionError("short two-screen frame was accepted");
        } catch (IllegalArgumentException expectedFailure) {
            // Expected.
        }
        TestSupport.equal(Short.MIN_VALUE, DualScreenLayout.pointerCoordinate(0f),
                "pointer minimum");
        TestSupport.equal((short)0, DualScreenLayout.pointerCoordinate(0.5f),
                "pointer midpoint");
        TestSupport.equal(Short.MAX_VALUE, DualScreenLayout.pointerCoordinate(1f),
                "pointer maximum");
        TestSupport.equal((short)0, DualScreenLayout.lowerScreenPointerY(0f),
                "lower display top maps to composite midpoint");
        TestSupport.equal(Short.MAX_VALUE,
                DualScreenLayout.lowerScreenPointerY(1f),
                "lower display bottom maps to composite bottom");
        checkDsTouchBounds();
        TestSupport.equal((short)3641,
                DualScreenLayout.threeDsSideBySidePointerX(0f),
                "3DS touch left maps to Azahar column 400 of 720");
        TestSupport.equal((short)32766,
                DualScreenLayout.threeDsSideBySidePointerX(1f),
                "3DS touch right maps to composite right");
        TestSupport.equal((short)-32767,
                DualScreenLayout.threeDsSideBySidePointerY(0f),
                "3DS touch top uses full SideScreen height");
        TestSupport.equal((short)32766,
                DualScreenLayout.threeDsSideBySidePointerY(1f),
                "3DS touch bottom uses full SideScreen height");
        DualScreenLayout.TouchPoint upperLeft =
                DualScreenLayout.threeDsTouchPoint(0f, 75f, 1240, 1080);
        TestSupport.truth(upperLeft.inside, "contained image corner accepts touch");
        TestSupport.equal(0f, upperLeft.x, "left edge maps to touch x0");
        TestSupport.equal(0f, upperLeft.y, "letterbox offset removed from touch y");
        DualScreenLayout.TouchPoint lowerRight =
                DualScreenLayout.threeDsTouchPoint(1240f, 1005f, 1240, 1080);
        TestSupport.truth(!lowerRight.inside, "half-open right/bottom boundary releases touch");
        TestSupport.equal(1f, lowerRight.x, "right edge maps to touch x1");
        TestSupport.equal(1f, lowerRight.y, "bottom edge maps to touch y1");
        DualScreenLayout.TouchPoint center =
                DualScreenLayout.threeDsTouchPoint(620f, 540f, 1240, 1080);
        TestSupport.equal(0.5f, center.x, "center x unchanged");
        TestSupport.equal(0.5f, center.y, "center y unchanged");
        TestSupport.truth(!DualScreenLayout.threeDsTouchPoint(620f, 74f, 1240, 1080).inside,
                "upper black bar does not press the guest touch screen");
        TestSupport.truth(!DualScreenLayout.threeDsTouchPoint(620f, 1006f, 1240, 1080).inside,
                "drag outside sends release instead of a clamped press");
        TestSupport.truth(!DualScreenLayout.threeDsTouchPoint(Float.NaN, 0f, 1240, 1080).inside,
                "invalid position cannot press");
        TestSupport.truth(!DualScreenLayout.threeDsTouchPoint(0f, 0f, 0, 1080).inside,
                "unlaid-out view cannot press");
        DualScreenLayout.TouchPoint wideLeft =
                DualScreenLayout.threeDsTouchPoint(240f, 0f, 1920, 1080);
        TestSupport.equal(0f, wideLeft.x, "pillarbox offset removed on wider displays");
        TestSupport.truth(!DualScreenLayout.threeDsTouchPoint(239f, 540f, 1920, 1080).inside,
                "pillarbox does not press");
        // Reproduce the actual Azahar float conversion and half-open crop,
        // including the rounding immediately inside each image boundary.
        for (int scale = 1; scale <= 4; ++scale) {
            for (float position : new float[] {0f, Math.nextUp(0f), 0.5f,
                                                Math.nextDown(1f), 1f}) {
                short px = DualScreenLayout.threeDsSideBySidePointerX(position);
                short py = DualScreenLayout.threeDsSideBySidePointerY(position);
                int canvasX = (int)((px + 32767) / 65534f * (720 * scale));
                int canvasY = (int)((py + 32767) / 65534f * (240 * scale));
                TestSupport.truth(canvasX >= 400 * scale && canvasX < 720 * scale,
                        "quantized X remains within the core touch crop");
                TestSupport.truth(canvasY >= 0 && canvasY < 240 * scale,
                        "quantized Y remains within the core touch crop");
            }
        }
    }

    private static void checkDsPhoneLayout() {
        int[] source = {10, 11, 20, 21, 30, 31, 40, 41};
        int[] target = new int[8];
        DualScreenLayout.dsSideBySide(source, target, 2, 4);
        TestSupport.equal("[10, 11, 30, 31, 20, 21, 40, 41]",
                java.util.Arrays.toString(target), "phone retains every native pixel, top left/touch right");
        TestSupport.equal(30, source[4], "native composite remains unmodified");
        DualScreenLayout.TouchPoint center =
                DualScreenLayout.dsSideBySideTouchPoint(960f, 360f, 1280, 720);
        TestSupport.truth(center.inside, "right screen accepts stylus");
        TestSupport.equal(0.5f, center.x, "right screen center x");
        TestSupport.equal(0.5f, center.y, "right screen center y");
        TestSupport.equal((short)16383, DualScreenLayout.lowerScreenPointerY(center.y),
                "phone stylus reaches native lower half");
        TestSupport.truth(DualScreenLayout.dsSideBySideTouchPoint(640f, 120f, 1280, 720).inside,
                "right panel top-left boundary included");
        for (float[] outside : new float[][] {{639f, 360f}, {960f, 119f},
                {960f, 600f}, {1280f, 360f}, {Float.NaN, 360f}})
            TestSupport.truth(!DualScreenLayout.dsSideBySideTouchPoint(
                    outside[0], outside[1], 1280, 720).inside,
                    "non-touch screen, bars and outer boundaries release stylus");
        TestSupport.truth(!DualScreenLayout.dsSideBySideTouchPoint(0f, 0f, 0, 0).inside,
                "missing phone surface cannot press");
        try {
            DualScreenLayout.dsSideBySide(source, source, 2, 4);
            throw new AssertionError("in-place layout would overwrite pixels");
        } catch (IllegalArgumentException expected) {}
    }

    private static void checkDsScreenOrder() {
        for (int height : new int[] {384, 768, 1152}) {
            for (boolean swapped : new boolean[] {false, true}) {
                int primary = DualScreenLayout.dsScreenTop(height, true, swapped);
                int secondary = DualScreenLayout.dsScreenTop(height, false, swapped);
                TestSupport.equal(swapped ? height / 2 : 0, primary, "primary native half");
                TestSupport.equal(swapped ? 0 : height / 2, secondary, "secondary native half");
                TestSupport.equal(height / 2, Math.abs(primary - secondary), "complete distinct halves");
                TestSupport.equal(swapped, DualScreenLayout.dsPanelIsTouch(true, swapped),
                        "primary input follows native touch half");
                TestSupport.equal(!swapped, DualScreenLayout.dsPanelIsTouch(false, swapped),
                        "inactive panel cannot cancel or move the active stylus");
            }
        }
        for (int height : new int[] {0, 1, 383}) {
            try {
                DualScreenLayout.dsScreenTop(height, true, true);
                throw new AssertionError("invalid composite height accepted");
            } catch (IllegalArgumentException expected) {}
        }
        DualScreenLayout.TouchPoint center = DualScreenLayout.dsTouchPoint(960f, 540f, 1920, 1080);
        TestSupport.equal(0.5f, center.x, "top panel touch removes pillarbox offset");
        TestSupport.equal(0.5f, center.y, "top panel touch center");
        TestSupport.equal((short)16383, DualScreenLayout.lowerScreenPointerY(center.y),
                "top physical panel still targets native lower composite half");
        TestSupport.truth(!DualScreenLayout.dsTouchPoint(239f, 540f, 1920, 1080).inside,
                "primary pillarbox cannot press");
    }

    private static void checkDsTouchBounds() {
        DualScreenLayout.TouchPoint corner =
                DualScreenLayout.dsTouchPoint(0f, 75f, 1240, 1080);
        TestSupport.truth(corner.inside, "DS contained image includes top/left edges");
        TestSupport.equal(0f, corner.x, "DS left image edge maps to x0");
        TestSupport.equal(0f, corner.y, "DS top image edge removes 75px letterbox");
        TestSupport.equal((short)0, DualScreenLayout.lowerScreenPointerY(corner.y),
                "DS image top reaches bottom composite half, not letterbox offset");
        DualScreenLayout.TouchPoint center =
                DualScreenLayout.dsTouchPoint(620f, 540f, 1240, 1080);
        TestSupport.truth(center.inside, "DS image center accepts touch");
        TestSupport.equal(0.5f, center.x, "DS center x is unchanged");
        TestSupport.equal(0.5f, center.y, "DS center y is unchanged");
        DualScreenLayout.TouchPoint lastInside = DualScreenLayout.dsTouchPoint(
                Math.nextDown(1240f), Math.nextDown(1005f), 1240, 1080);
        TestSupport.truth(lastInside.inside, "DS last interior point accepts touch");
        TestSupport.truth(lastInside.x < 1f && lastInside.y < 1f,
                "DS interior remains below exclusive normalized boundaries");
        for (float[] outside : new float[][] {
                {620f, 74f}, {620f, 1005f}, {620f, 1079f},
                {-1f, 540f}, {1240f, 540f}, {Float.NaN, 540f},
                {620f, Float.NaN}, {Float.POSITIVE_INFINITY, 540f},
                {Float.NEGATIVE_INFINITY, 540f},
                {620f, Float.POSITIVE_INFINITY}, {620f, Float.NEGATIVE_INFINITY}
        }) {
            DualScreenLayout.TouchPoint point = DualScreenLayout.dsTouchPoint(
                    outside[0], outside[1], 1240, 1080);
            TestSupport.truth(!point.inside,
                    "DS bars, outside drags, and invalid positions release instead of press");
            TestSupport.truth(Float.isFinite(point.x) && Float.isFinite(point.y),
                    "DS release coordinates remain finite");
        }
        TestSupport.truth(!DualScreenLayout.dsTouchPoint(0f, 0f, 0, 1080).inside,
                "DS unavailable surface cannot activate touch");
        TestSupport.truth(!DualScreenLayout.dsTouchPoint(0f, 0f, 1240, -1).inside,
                "DS invalid height cannot activate touch");
        DualScreenLayout.TouchPoint wideLeft =
                DualScreenLayout.dsTouchPoint(240f, 0f, 1920, 1080);
        TestSupport.truth(wideLeft.inside, "DS wide-display image starts at x240");
        TestSupport.equal(0f, wideLeft.x, "DS pillarbox offset is removed");
        TestSupport.truth(!DualScreenLayout.dsTouchPoint(239f, 540f, 1920, 1080).inside,
                "DS left pillarbox releases touch");
        TestSupport.truth(!DualScreenLayout.dsTouchPoint(1680f, 540f, 1920, 1080).inside,
                "DS right pillarbox boundary releases touch");
        DualScreenLayout.TouchPoint portraitTop =
                DualScreenLayout.dsTouchPoint(0f, 215f, 1080, 1240);
        TestSupport.truth(portraitTop.inside, "DS fit follows changed surface dimensions");
        TestSupport.equal(0f, portraitTop.y, "DS portrait letterbox offset is removed");
    }
}
