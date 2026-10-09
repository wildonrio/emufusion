package com.thorium.lucent.video;

/** Pure layout math for the audited stacked and 3DS side-by-side composites. */
public final class DualScreenLayout {
    public static final class TouchPoint {
        public final float x;
        public final float y;
        public final boolean inside;

        TouchPoint(float x, float y, boolean inside) {
            this.x = x;
            this.y = y;
            this.inside = inside;
        }
    }

    public static final class Region {
        public final int left;
        public final int top;
        public final int right;
        public final int bottom;

        Region(int left, int top, int right, int bottom) {
            this.left = left;
            this.top = top;
            this.right = right;
            this.bottom = bottom;
        }

        public int width() { return right - left; }
        public int height() { return bottom - top; }
    }

    private DualScreenLayout() {}

    /** Native TopBottom row order never changes; only its physical destination does. */
    public static int dsScreenTop(int height, boolean primary, boolean touchOnPrimary) {
        validate(1, height);
        return dsPanelIsTouch(primary, touchOnPrimary) ? height / 2 : 0;
    }

    public static boolean dsPanelIsTouch(boolean primary, boolean touchOnPrimary) {
        return primary == touchOnPrimary;
    }

    public static Region top(int width, int height) {
        validate(width, height);
        return new Region(0, 0, width, height / 2);
    }

    public static Region bottom(int width, int height) {
        validate(width, height);
        return new Region(0, height / 2, width, height);
    }

    /** Phone layout: retain both complete screens, top left and touch right.
     * The caller reuses the destination to avoid per-frame allocation. */
    public static void dsSideBySide(int[] stacked, int[] output, int width, int height) {
        validate(width, height);
        long count = (long) width * height;
        if (stacked == null || output == null || stacked == output ||
                count > stacked.length || count > output.length)
            throw new IllegalArgumentException("distinct complete frame buffers are required");
        int panelHeight = height / 2;
        for (int row = 0; row < panelHeight; ++row) {
            System.arraycopy(stacked, row * width, output, row * width * 2, width);
            System.arraycopy(stacked, (row + panelHeight) * width,
                    output, row * width * 2 + width, width);
        }
    }

    /** Touch on the right-hand DS screen in the contained phone composite. */
    public static TouchPoint dsSideBySideTouchPoint(float x, float y,
                                                   int viewWidth, int viewHeight) {
        if (viewWidth <= 0 || viewHeight <= 0 || !Float.isFinite(x) || !Float.isFinite(y))
            return new TouchPoint(0f, 0f, false);
        PresentationGeometry.Rectangle bounds =
                PresentationGeometry.fitInside(viewWidth, viewHeight, 8f / 3f);
        float nx = 2f * (x - bounds.left) / bounds.width() - 1f;
        float ny = (y - bounds.top) / bounds.height();
        return new TouchPoint(Math.max(0f, Math.min(1f, nx)),
                Math.max(0f, Math.min(1f, ny)),
                nx >= 0f && nx < 1f && ny >= 0f && ny < 1f);
    }

    /**
     * Returns a generator-upload copy of a vertically stacked two-screen frame.
     *
     * <p>Android's bitmap-to-GL upload and libretro's software-frame row order
     * use opposite vertical origins.  Flipping the complete stacked image
     * would also exchange the console's top and touch screens, so each physical
     * screen has to be flipped independently.  The caller retains its original
     * array for the Canvas fallback, whose origin already matches libretro.
     */
    public static int[] forGeneratorUpload(int[] pixels, int width, int height) {
        validate(width, height);
        if (pixels == null || pixels.length < (long) width * height)
            throw new IllegalArgumentException("a complete two-screen frame is required");
        int[] result = new int[width * height];
        int screenHeight = height / 2;
        for (int screen = 0; screen < 2; ++screen) {
            int screenTop = screen * screenHeight;
            for (int row = 0; row < screenHeight; ++row) {
                int sourceRow = screenTop + row;
                int targetRow = screenTop + screenHeight - 1 - row;
                System.arraycopy(pixels, sourceRow * width,
                        result, targetRow * width, width);
            }
        }
        return result;
    }

    public static short pointerCoordinate(float normalized) {
        if (Float.isNaN(normalized)) normalized = 0f;
        float clamped = Math.max(0f, Math.min(1f, normalized));
        if (clamped <= 0f) return Short.MIN_VALUE;
        if (clamped >= 1f) return Short.MAX_VALUE;
        return (short)Math.round(-32768f + clamped * 65535f);
    }

    /** Maps a physical lower-display Y coordinate into the lower half of the
     * vertically stacked libretro composite that both dual-screen cores see. */
    public static short lowerScreenPointerY(float normalized) {
        if (Float.isNaN(normalized)) normalized = 0f;
        float clamped = Math.max(0f, Math.min(1f, normalized));
        return pointerCoordinate(0.5f + clamped * 0.5f);
    }

    /** Maps a local 3DS touch-panel X into Azahar's reviewed SideScreen
     * composite: 400 top-screen columns followed by 320 touch columns. */
    public static short threeDsSideBySidePointerX(float normalized) {
        if (Float.isNaN(normalized)) normalized = 0f;
        float clamped = Math.max(0f, Math.min(1f, normalized));
        // Azahar floors ((pointer + 32767) / 65534 * canvasWidth) and
        // accepts only [400,720). Keep quantization inside that half-open crop.
        int minimum = (int)Math.ceil((5.0 / 9.0) * 65534.0 - 32767.0);
        return (short)Math.max(minimum, Math.min(32766,
                pointerCoordinate((5f + clamped * 4f) / 9f)));
    }

    /** SideScreen gives both 3DS screens the complete 240-line height. */
    public static short threeDsSideBySidePointerY(float normalized) {
        return (short)Math.max(-32767, Math.min(32766, pointerCoordinate(normalized)));
    }

    /** Convert DS lower-panel touches through the same contained 256x192
     * image used by the software Canvas crop. Black bars must release touch. */
    public static TouchPoint dsTouchPoint(float x, float y,
                                         int viewWidth, int viewHeight) {
        return fourThreeTouchPoint(x, y, viewWidth, viewHeight);
    }

    /** Convert logical display touches through the contained 320x240 image,
     * not through the portrait producer buffer or the surrounding black bars.
     * A release outside the image must still be delivered, with inside=false. */
    public static TouchPoint threeDsTouchPoint(float x, float y,
                                               int viewWidth, int viewHeight) {
        return fourThreeTouchPoint(x, y, viewWidth, viewHeight);
    }

    /** The phone displays the complete 720x240 SideScreen image: the right
     * 320 columns are touchable, after removing the composite's display bars. */
    public static TouchPoint threeDsPhoneTouchPoint(float x, float y,
                                                   int viewWidth, int viewHeight) {
        if (viewWidth <= 0 || viewHeight <= 0 || !Float.isFinite(x) || !Float.isFinite(y))
            return new TouchPoint(0f, 0f, false);
        PresentationGeometry.Rectangle bounds =
                PresentationGeometry.fitInside(viewWidth, viewHeight, 3f);
        float touchLeft = bounds.left + bounds.width() * (5f / 9f);
        float nx = (x - touchLeft) / (bounds.width() * (4f / 9f));
        float ny = (y - bounds.top) / bounds.height();
        return new TouchPoint(Math.max(0f, Math.min(1f, nx)),
                Math.max(0f, Math.min(1f, ny)),
                nx >= 0f && nx < 1f && ny >= 0f && ny < 1f);
    }

    private static TouchPoint fourThreeTouchPoint(float x, float y,
                                                 int viewWidth, int viewHeight) {
        if (viewWidth <= 0 || viewHeight <= 0 || !Float.isFinite(x) || !Float.isFinite(y))
            return new TouchPoint(0f, 0f, false);
        PresentationGeometry.Rectangle bounds =
                PresentationGeometry.fitInside(viewWidth, viewHeight, 4f / 3f);
        float nx = (x - bounds.left) / bounds.width();
        float ny = (y - bounds.top) / bounds.height();
        boolean inside = nx >= 0f && nx < 1f && ny >= 0f && ny < 1f;
        return new TouchPoint(Math.max(0f, Math.min(1f, nx)),
                Math.max(0f, Math.min(1f, ny)), inside);
    }

    private static void validate(int width, int height) {
        if (width < 1 || height < 2 || (height & 1) != 0)
            throw new IllegalArgumentException("an even two-screen frame is required");
    }
}
