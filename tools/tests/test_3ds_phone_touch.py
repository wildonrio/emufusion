"""Run the real 3DS phone stylus against Android event doubles and audit wiring."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_phone_analog_controls import JAVA, ROOT, STUBS


HARNESS = r"""package com.thorium.preview.game;
import android.view.MotionEvent;
import com.thorium.lucent.video.DualScreenLayout;
public class ThreeDsPhoneStylusTest {
  static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
  static MotionEvent event(int a,int index,int[] ids,float... xy){return new MotionEvent(a,index,ids,xy);}
  static void center(ThreeDsPhoneStylus.State s){
    check(s.pressed,"center must press");
    check(Math.abs(s.x-DualScreenLayout.threeDsSideBySidePointerX(.5f))<=1,"native X");
    check(Math.abs(s.y-DualScreenLayout.threeDsSideBySidePointerY(.5f))<=1,"native Y");
  }
  public static void main(String[] args){
    for(int[] size:new int[][]{{1152,720,0,168,1152,384},{1280,720,0,146,1280,427},
      {1920,1080,0,220,1920,640},{720,1280,0,520,720,240},{2600,720,220,0,2160,720}}){
      int w=size[0],h=size[1]; float scale=size[4]/720f;
      float left=size[2],top=size[3];
      float x=left+560*scale,y=top+size[5]/2f;
      ThreeDsPhoneStylus p=new ThreeDsPhoneStylus();
      center(p.update(event(0,0,new int[]{7},x,y),w,h));
      center(p.update(event(5,1,new int[]{7,8},x,y,0,0),w,h));
      center(p.update(event(6,1,new int[]{7,8},x,y,0,0),w,h));
      center(p.update(event(2,0,new int[]{8,7},0,0,x,y),w,h));
      check(!p.update(event(6,1,new int[]{8,7},0,0,x,y),w,h).pressed,"owner lift");
      check(!p.update(event(2,0,new int[]{8},x,y),w,h).pressed,"no stolen owner");
      p.update(event(0,0,new int[]{3},x,y),w,h);
      check(!p.update(event(2,0,new int[]{3},left+200*scale,y),w,h).pressed,"left screen releases");
      center(p.update(event(2,0,new int[]{3},x,y),w,h));
      check(!p.update(event(2,0,new int[]{3},x,top-1),w,h).pressed,"letterbox releases");
      center(p.update(event(2,0,new int[]{3},x,y),w,h));
      check(!p.update(event(3,0,new int[]{3},x,y),w,h).pressed,"cancel releases");
      p.update(event(0,0,new int[]{3},left+200*scale,y),w,h);
      check(!p.update(event(2,0,new int[]{3},x,y),w,h).pressed,"left-screen gesture cannot become stylus");
      p.update(event(0,0,new int[]{3},x,y),w,h);
      check(!p.release().pressed,"pause/stop releases");
      check(!p.update(event(2,0,new int[]{3},x,y),w,h).pressed,"resume needs fresh down");
      p.update(event(0,0,new int[]{3},x,y),w,h);
      check(!p.update(event(1,0,new int[]{3},x,y),w,h).pressed,"up releases");
      p.update(event(0,0,new int[]{3},x,y),w,h);
      check(!p.update(event(2,0,new int[]{4},x,y),w,h).pressed,"missing pointer releases");
      check(!p.update(event(0,0,new int[]{3},Float.NaN,y),w,h).pressed,"nonfinite");
      check(!p.update(event(0,0,new int[]{3},x,y),0,0).pressed,"empty view");
    }
    System.out.println("3DS phone geometry, ownership, release and cancellation passed at five sizes");
  }
}
"""


class ThreeDsPhoneTouchTest(unittest.TestCase):
    def test_real_stylus(self):
        src = ROOT / "unified-android/src/com/thorium"
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            event = temp / "android/view/MotionEvent.java"
            event.parent.mkdir(parents=True)
            event.write_text(STUBS["android/view/MotionEvent.java"])
            harness = temp / "ThreeDsPhoneStylusTest.java"
            harness.write_text(HARNESS)
            subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", str(temp),
                            str(event), str(harness),
                            str(src / "lucent/metadata/EngineSystemIdResolver.java"),
                            str(src / "lucent/video/PresentationGeometry.java"),
                            str(src / "lucent/video/DualScreenLayout.java"),
                            str(src / "preview/game/ThreeDsPhoneStylus.java")], check=True)
            subprocess.run([str(JAVA / "java"), "-cp", str(temp),
                            "com.thorium.preview.game.ThreeDsPhoneStylusTest"], check=True)

    def test_session_and_host_wiring(self):
        src = ROOT / "unified-android/src/com/thorium/preview/game"
        host = (src / "InWindowGameHost.java").read_text()
        self.assertIn("session.onPrimaryTouch(event, view.getWidth(), view.getHeight())", host)
        self.assertNotIn("((LibretroEngineSession) session).onPrimaryTouch", host)
        session = (src / "PpssppGlesEngineSession.java").read_text()
        touch = session.split("@Override public void onPrimaryTouch(", 1)[1].split(
            "private void releasePhoneStylus", 1)[0]
        self.assertIn("!isThreeDsSystem(request.systemId)", touch)
        self.assertIn("if (lower != null && lower.isValid()) return", touch)
        self.assertIn("prepared && resumeRequested", touch)
        self.assertIn("!stopping.get() && !released.get()", touch)
        self.assertIn("active.setPointer(0, point.x, point.y, point.pressed)", touch)
        for start in ("void pause(", "void stop(", "void releaseWhenComplete(",
                      "void onSecondarySurfaceAvailable("):
            self.assertIn("releasePhoneStylus();", session.split(start, 1)[1][:250])


if __name__ == "__main__":
    unittest.main()
