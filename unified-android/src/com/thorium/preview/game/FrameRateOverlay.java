package com.thorium.preview.game;

/**
 * The corner frame-rate counter as an image the frame generator draws into
 * each frame it presents, at a pixel position from the game view's top-left
 * corner. Immutable: a new text or burn-in position is a new instance; the
 * image is shared while the text is unchanged and never modified.
 */
final class FrameRateOverlay {
    /** Premultiplied RGBA, bottom row first (GL's texture order). */
    static final class Image {
        final int width, height;
        final java.nio.ByteBuffer rgba;

        Image(int width, int height, java.nio.ByteBuffer rgba) {
            this.width = width;
            this.height = height;
            this.rgba = rgba;
        }
    }

    final Image image;
    final int leftPx, topPx;

    FrameRateOverlay(Image image, int leftPx, int topPx) {
        this.image = image;
        this.leftPx = leftPx;
        this.topPx = topPx;
    }
}
