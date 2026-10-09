"""Execute the loading-video fit math and guard all asynchronous size callbacks."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT, method

BOOT = ROOT / 'unified-android/src/com/thorium/preview/BootVideoOverlay.java'


class BootVideoAspectTest(unittest.TestCase):
    def test_actual_transform_preserves_aspect_fits_and_centers(self):
        fit = method(BOOT.read_text(), 'private static void fitVideo(')
        harness = r'''
public final class BootAspectProbe {
  static class Matrix {
    float sx, sy, px, py;
    void setScale(float x, float y, float cx, float cy) {
      sx=x; sy=y; px=cx; py=cy;
    }
  }
  static class TextureView {
    int width, height; Matrix matrix;
    TextureView(int w, int h) { width=w; height=h; }
    int getWidth() { return width; }
    int getHeight() { return height; }
    void setTransform(Matrix m) { matrix=m; }
  }
  static void check(boolean ok, String why) {
    if (!ok) throw new AssertionError(why);
  }
  static void close(double actual, double expected, String why) {
    check(Math.abs(actual-expected) < 0.002, why+": "+actual+" != "+expected);
  }
  static void verify(TextureView view, int vw, int vh) {
    fitVideo(view, vw, vh);
    Matrix m=view.matrix;
    double w=view.width*m.sx, h=view.height*m.sy;
    close(w/h, (double)vw/vh, "aspect ratio distorted");
    check(w<=view.width+0.002 && h<=view.height+0.002, "video cropped");
    check(Math.abs(w-view.width)<0.002 || Math.abs(h-view.height)<0.002,
          "video not largest possible fit");
    close((1-m.sx)*m.px, (view.width-w)/2, "not centered horizontally");
    close((1-m.sy)*m.py, (view.height-h)/2, "not centered vertically");
  }
  public static void main(String[] args) {
    TextureView phone=new TextureView(2400,1080);
    verify(phone,1920,1080);
    close(phone.matrix.sx,0.8,"wide phone must pillarbox, not stretch");
    close(phone.matrix.sy,1,"wide phone uses full height");
    TextureView thor=new TextureView(1920,1080);
    verify(thor,1920,1080);
    close(thor.matrix.sx,1,"16:9 remains full screen");
    close(thor.matrix.sy,1,"16:9 remains full screen");
    TextureView tablet=new TextureView(1920,1200);
    verify(tablet,1920,1080);
    close(tablet.matrix.sx,1,"16:10 uses full width");
    close(tablet.matrix.sy,0.9,"16:10 must letterbox, not stretch");
    // Insets/window resizing and a later decoder size report must replace
    // the old transform instead of accumulating scales.
    phone.width=2200; phone.height=1000; verify(phone,1920,1080);
    verify(phone,1440,1080);
    phone.width=1920; phone.height=1080; verify(phone,1920,1080);
    close(phone.matrix.sx,1,"stale transform after resize");
    Matrix before=phone.matrix;
    fitVideo(phone,0,1080); check(phone.matrix==before,"unknown source size");
    phone.width=0;
    fitVideo(phone,1920,1080); check(phone.matrix==before,"unmeasured view");
    for(int w : new int[]{1280,1920,2160,2400,2560,3840})
      for(int h : new int[]{720,1080,1200})
        for(int vw : new int[]{640,1280,1440,1920,2560})
          for(int vh : new int[]{360,480,720,1080})
            verify(new TextureView(w,h),vw,vh);
    System.out.println("boot aspect PASS");
  }
''' + fit + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-boot-aspect-test-') as temp:
            unit = Path(temp) / 'BootAspectProbe.java'
            unit.write_text(harness)
            subprocess.run([str(JAVA/'javac'), str(unit)], check=True,
                           capture_output=True, text=True)
            run = subprocess.run([str(JAVA/'java'), '-cp', temp, 'BootAspectProbe'],
                                 check=True, capture_output=True, text=True)
            self.assertIn('boot aspect PASS', run.stdout)

    def test_fit_applies_before_playback_and_after_each_size_change(self):
        source = BOOT.read_text()
        mount = method(source, 'private static synchronized void mount(')
        self.assertIn('surface.setOpaque(false)', mount)
        self.assertIn('container.setBackgroundColor(Color.BLACK)', mount)
        self.assertIn('start(surface, new Surface(texture), video)', mount)
        resize = method(source, 'public void onSurfaceTextureSizeChanged(')
        self.assertIn('fitVideo(surface, playing.getVideoWidth(), playing.getVideoHeight())', resize)
        video = method(source, 'public void onVideoSizeChanged(')
        self.assertIn('fitVideo(view, width, height)', video)
        prepared = method(source, 'public void onPrepared(')
        self.assertLess(prepared.index('fitVideo('), prepared.index('ready.start()'))


if __name__ == '__main__':
    unittest.main()
