"""The corner frame-rate counter is drawn into the generator's frames while a
generator presents the game, never as a view over it (3.2.145)."""
from pathlib import Path
import unittest
from tools.tests.test_framegen_startup_fallback import method

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'


class FrameRateOverlayTest(unittest.TestCase):
    def test_generator_draws_it_last_before_the_swap(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('beginFullImageCapture(renderedSynthetic, densePhysicalFrameId, proofPhase);\n'
                      '        if (!realPredrawn && !generatedInBackBuffer) drawFrameRateOverlay();\n'
                      '        if (!finishedForNextLatch(renderedSynthetic)) {', generator)
        draw = method(generator, '    private void drawFrameRateOverlay(')
        # Uploaded once per new image (premultiplied RGBA, rows in GL order).
        self.assertIn('if (image != uploadedOverlayImage) {', draw)
        self.assertIn('image.rgba.duplicate().position(0)', draw)
        # Top-left placement in GL's bottom-left viewport, premultiplied blend,
        # and the caller's framebuffer, viewport and blend state restored.
        self.assertIn('GLES20.glViewport(overlay.leftPx, outputHeight - overlay.topPx - image.height,', draw)
        self.assertIn('GLES20.glBlendFunc(GLES20.GL_ONE, GLES20.GL_ONE_MINUS_SRC_ALPHA);', draw)
        self.assertIn('if (!blend) GLES20.glDisable(GLES20.GL_BLEND);', draw)
        self.assertIn('GLES20.glViewport(overlayState[1], overlayState[2], overlayState[3], overlayState[4]);', draw)

    def test_view_keeps_it_for_a_later_generator(self):
        view = (GAME / 'GameSurfaceView.java').read_text()
        setter = method(view, '    public boolean setFrameRateOverlay(')
        self.assertIn('if (generator == null) return false;', setter)
        self.assertIn('generator.setFrameRateOverlay(frameRateOverlay);', view)
        renderer = (GAME / 'FrameGenerationRenderer.java').read_text()
        self.assertIn('default void setFrameRateOverlay(FrameRateOverlay overlay) {}', renderer)

    def test_host_uses_the_view_only_without_a_presenting_generator(self):
        host = (GAME / 'InWindowGameHost.java').read_text(encoding='utf-8')
        show = method(host, '    private void showBadge(')
        self.assertLess(show.index('setFrameRateOverlay(overlay)'), show.index('badge.setText(text);'))
        self.assertIn('badge.setVisibility(View.GONE);\n                return;', show)
        self.assertIn('if (!text.equals(overlayText)) {', show)
        render = method(host, '    private FrameRateOverlay.Image renderBadge(')
        # Unpremultiplied ARGB from getPixels, bottom row first for GL.
        self.assertIn('for (int y = height - 1; y >= 0; --y) {', render)
        self.assertIn('rgba.put((byte) (((color >> 16) & 0xFF) * alpha / 255));', render)
        hide = method(host, '    private void hideBadge(')
        self.assertIn('setFrameRateOverlay(null);', hide)
        self.assertEqual(host.count('hideBadge();'), 3)


if __name__ == '__main__':
    unittest.main()
