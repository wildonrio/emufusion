package com.thorium.preview;

/**
 * Scale for a preview video on a panel of another shape, applied to a
 * TextureView (which first stretches the buffer over the whole view).
 *
 * <p>The lower panel showed previews cropped to fill it: the Thor's bottom
 * screen is 1240x1080, so a 16:9 video was scaled 1.55x and lost a third of
 * its width (owner, 2026-10-13: "cutting off half the preview videos"). The
 * whole frame is shown now, at full width or height, centred on the panel's
 * background.</p>
 */
public final class PreviewVideoFit {
    private PreviewVideoFit() {}

    /** {scaleX, scaleY} about the view centre that contains the whole video. */
    public static float[] contain(int viewWidth, int viewHeight, int videoWidth, int videoHeight) {
        if (viewWidth <= 0 || viewHeight <= 0 || videoWidth <= 0 || videoHeight <= 0)
            return new float[] {1f, 1f};
        float viewAspect = viewWidth / (float) viewHeight;
        float videoAspect = videoWidth / (float) videoHeight;
        if (videoAspect > viewAspect) return new float[] {1f, viewAspect / videoAspect};
        return new float[] {videoAspect / viewAspect, 1f};
    }
}
