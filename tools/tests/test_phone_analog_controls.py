"""Execute the real phone View against small Android event/drawing test doubles."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "unified-android/src/com/thorium"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")) / "bin"

STUBS = {
    "android/content/Context.java": "package android.content; public class Context {}",
    "android/graphics/Color.java": "package android.graphics; public class Color { public static int argb(int a,int r,int g,int b){return (a<<24)|(r<<16)|(g<<8)|b;} }",
    "android/graphics/Typeface.java": "package android.graphics; public class Typeface { public static final Typeface DEFAULT_BOLD=new Typeface(); }",
    "android/graphics/Paint.java": """package android.graphics; public class Paint {
      public static final int ANTI_ALIAS_FLAG=1; public enum Align {CENTER}
      public enum Style {FILL,STROKE} public Style style=Style.FILL; public int color;
      public Paint(int flags){} public void setColor(int c){color=c;} public void setTextAlign(Align a){}
      public void setStyle(Style s){style=s;} public void setStrokeWidth(float w){}
      public void setTypeface(Typeface t){} public void setTextSize(float s){}
      public float ascent(){return -1;} public float descent(){return 1;}
    }""",
    "android/graphics/Canvas.java": """package android.graphics; public class Canvas {
      public final java.util.List<int[]> labels=new java.util.ArrayList<>(); private int fill;
      public final java.util.Map<String,String> at=new java.util.HashMap<>();
      public void drawCircle(float x,float y,float r,Paint p){if(p.style==Paint.Style.FILL)fill=p.color;}
      public void drawText(String s,float x,float y,Paint p){labels.add(new int[]{fill,p.color});
        at.put(Math.round(x)+","+Math.round(y),s);}
    }""",
    "android/view/View.java": """package android.view; import android.content.Context;
      import android.graphics.Canvas; public class View {
      public static final int VISIBLE=0,GONE=8;
      public View(Context c){onVisibilityChanged(this,GONE);}
      public void setFocusable(boolean b){} public int getWidth(){return 1212;}
      public int getHeight(){return 720;} public void invalidate(){}
      protected void onDraw(Canvas c){} public boolean onTouchEvent(MotionEvent e){return false;}
      protected void onDetachedFromWindow(){} protected void onVisibilityChanged(View v,int i){}
      public void onWindowFocusChanged(boolean f){}
    }""",
    "android/view/MotionEvent.java": """package android.view; public class MotionEvent {
      public static final int ACTION_DOWN=0,ACTION_UP=1,ACTION_MOVE=2,ACTION_CANCEL=3,
        ACTION_POINTER_DOWN=5,ACTION_POINTER_UP=6;
      private final int action,index; private final int[] ids; private final float[] xy;
      public MotionEvent(int a,int i,int[] p,float... q){action=a;index=i;ids=p;xy=q;}
      public int getActionMasked(){return action;} public int getActionIndex(){return index;}
      public int getPointerCount(){return ids.length;} public int getPointerId(int i){return ids[i];}
      public int findPointerIndex(int id){for(int i=0;i<ids.length;i++)if(ids[i]==id)return i;return -1;}
      public float getX(int i){return xy[2*i];} public float getY(int i){return xy[2*i+1];}
    }""",
}

HARNESS = r"""package com.thorium.preview.game;
import android.content.Context;
import android.view.MotionEvent;
import com.thorium.lucent.input.*;
import java.util.EnumSet;

public class PhoneAnalogTest {
  static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
  static void near(float expected,float actual){check(Math.abs(expected-actual)<0.0001f,expected+" != "+actual);}
  static double composite(int color,double background){
    double alpha=(color>>>24)/255.0; return (color&255)*alpha+background*(1-alpha);
  }
  static double luminance(double gray){
    double s=gray/255; return s<=.04045?s/12.92:Math.pow((s+.055)/1.055,2.4);
  }
  static void checkDrawingContrast(TouchControlsView view){
    android.graphics.Canvas canvas=new android.graphics.Canvas(); view.onDraw(canvas);
    check(canvas.labels.size()>=12,"phone labels were not drawn");
    for(int[] pair:canvas.labels)for(int background:new int[]{0,255}){
      double plate=composite(pair[0],background),label=composite(pair[1],plate);
      double contrast=(luminance(label)+.05)/(luminance(plate)+.05);
      check(contrast>=4.5,"phone label vanishes over background "+background+": "+contrast);
    }
  }
  static void checkFaceLabels(TouchControlsView view,String system,String north,
      String south,String west,String east){
    view.setSystem(system);
    android.graphics.Canvas canvas=new android.graphics.Canvas(); view.onDraw(canvas);
    float x=1212*.82f,y=720*.73f,d=720*.052f*1.65f;
    float[] xs={x,x,x-d,x+d},ys={y-d,y+d,y,y};
    String[] wanted={north,south,west,east};
    for(int i=0;i<4;i++) {
      String actual=canvas.at.get(Math.round(xs[i])+","+Math.round(ys[i]));
      check(java.util.Objects.equals(wanted[i],actual),system+" face "+i+
        " expected "+wanted[i]+" got "+actual);
    }
  }
  static class Sink implements TouchControlsView.Listener {
    float[] x=new float[2], y=new float[2]; int changes;
    EnumSet<CanonicalControl> buttons=EnumSet.noneOf(CanonicalControl.class);
    public void onControl(CanonicalControl c,boolean p){if(p)buttons.add(c);else buttons.remove(c);}
    public void onAnalog(int i,float a,float b){x[i]=a;y[i]=b;changes++;}
  }
  static MotionEvent event(int a,int index,int[] ids,float... xy){return new MotionEvent(a,index,ids,xy);}
  static void holdRight(TouchControlsView view,int id,float x,float y,float r){
    view.onTouchEvent(event(0,0,new int[]{id},x,y));
    view.onTouchEvent(event(2,0,new int[]{id},x+r*2,y));
  }
  public static void main(String[] args){
    check(SystemControlLayouts.analogStickCount("dreamcast")==1,"Dreamcast stick");
    check(SystemControlLayouts.analogStickCount("psp")==1,"PSP nub");
    for(String system:new String[]{"n64","ps2","gc","wii","3ds","n3ds"})
      check(SystemControlLayouts.analogStickCount(system)==2,"two axes: "+system);
    for(String system:new String[]{"nes","snes","nds","gba","gb","megadrive","unknown"})
      check(SystemControlLayouts.analogStickCount(system)==0,"no unnecessary sticks: "+system);
    TouchAnalogStick pure=new TouchAnalogStick();
    check(!pure.begin(1,0,0,0),"empty geometry");
    check(!pure.begin(1,Float.NaN,0,10),"invalid input");
    check(pure.begin(9,0,0,100),"capture");
    check(!pure.begin(10,0,0,100),"ownership");
    pure.move(10,100,0,100); near(0,pure.x());
    pure.move(9,5,0,100); near(0,pure.x());
    pure.move(9,56,0,100); near(.5f,pure.x());
    pure.move(9,100,100,100); near((float)Math.sqrt(.5),pure.x());
    near((float)Math.sqrt(.5),pure.y());
    pure.release(10); check(pure.owns(9),"other finger released owner");
    pure.release(9); near(0,pure.x()); check(pure.pointerId()==-1,"release owner");

    TouchControlsView view=new TouchControlsView(new Context()); Sink sink=new Sink();
    view.setListener(sink); view.setAnalogStickCount(2);
    checkDrawingContrast(view);
    float lx=1212*.18f,rx=1212*.82f,cy=720*.39f,r=720*.095f;
    check(!view.onTouchEvent(event(0,0,new int[]{2},600,150)),"stylus pass-through");
    check(view.onTouchEvent(event(0,0,new int[]{7},lx,cy)),"stick captured");
    view.onTouchEvent(event(2,0,new int[]{7},lx+r*2,cy)); near(1,sink.x[0]);
    // A second finger presses South while the first remains held off the stick.
    view.onTouchEvent(event(5,1,new int[]{7,19},lx+r*2,cy,rx,720*.816f));
    check(sink.buttons.contains(CanonicalControl.SOUTH),"simultaneous face button"); near(1,sink.x[0]);
    view.onTouchEvent(event(6,1,new int[]{7,19},lx+r*2,cy,rx,720*.816f));
    check(sink.buttons.isEmpty(),"face button release"); near(1,sink.x[0]);
    // Pointer index changes must not transfer stick ownership.
    view.onTouchEvent(event(5,0,new int[]{24,7},rx,cy,lx+r*2,cy));
    view.onTouchEvent(event(2,0,new int[]{24,7},rx,cy-r*2,lx+r*2,cy));
    near(-1,sink.y[1]); near(1,sink.x[0]);
    view.onTouchEvent(event(6,1,new int[]{24,7},rx,cy-r,lx+r*2,cy));
    near(0,sink.x[0]); near(-1,sink.y[1]);
    view.onTouchEvent(event(1,0,new int[]{24},rx,cy-r)); near(0,sink.y[1]);
    // Stick finger dragged over D-pad remains analog, never also digital.
    view.onTouchEvent(event(0,0,new int[]{3},lx,cy));
    view.onTouchEvent(event(2,0,new int[]{3},lx,720*.644f));
    near(1,sink.y[0]); check(sink.buttons.isEmpty(),"stick leaked to dpad");
    view.onTouchEvent(event(3,0,new int[]{3},lx,720*.644f)); near(0,sink.y[0]);
    holdRight(view,5,lx,cy,r); near(1,sink.x[0]);
    view.onWindowFocusChanged(false); near(0,sink.x[0]);
    holdRight(view,5,lx,cy,r); view.releaseTouches(); near(0,sink.x[0]);
    holdRight(view,5,lx,cy,r); view.onVisibilityChanged(view,8); near(0,sink.x[0]);
    holdRight(view,5,lx,cy,r); view.onDetachedFromWindow(); near(0,sink.x[0]);
    holdRight(view,5,lx,cy,r); view.setAnalogStickCount(0); near(0,sink.x[0]);
    check(!view.onTouchEvent(event(0,0,new int[]{2},lx,cy)),"hidden stick captures stylus");
    view.onTouchEvent(event(0,0,new int[]{6},lx,720*.644f));
    check(sink.buttons.contains(CanonicalControl.DPAD_UP),"original dpad still works");
    view.releaseTouches(); check(sink.buttons.isEmpty(),"pause releases buttons");
    // Every declared trigger/click is reachable, including digital-only PSX
    // and DS layouts; simple systems must not acquire phantom controls.
    CanonicalControl[] extras={CanonicalControl.L2,CanonicalControl.L3,
      CanonicalControl.R3,CanonicalControl.R2};
    float[] extraX={.18f,.28f,.72f,.82f};
    for(String system:new String[]{"ps2","psx","gc","wii","n64","n3ds",
      "nds","gba","nes","snes","psp","switch","wiiu","ps3"}) {
      view.setSystem(system);
      String table=system.equals("n3ds")?"3ds":system;
      boolean nativePad=system.equals("switch")||system.equals("wiiu")||system.equals("ps3");
      for(int i=0;i<extras.length;i++) {
        boolean expected=nativePad||SystemControlLayouts.bindings(table).containsKey(extras[i]);
        boolean captured=view.onTouchEvent(event(0,0,new int[]{12},1212*extraX[i],720*.12f));
        check(captured==expected,"extra hit "+system+" "+extras[i]);
        check(expected?sink.buttons.equals(EnumSet.of(extras[i])):sink.buttons.isEmpty(),
          "exact extra button "+system+" "+extras[i]);
        if(captured)view.onTouchEvent(event(1,0,new int[]{12},1212*extraX[i],720*.12f));
        check(sink.buttons.isEmpty(),"extra release "+extras[i]);
      }
    }
    view.setSystem("ps2"); view.setAnalogStickCount(2);
    holdRight(view,7,lx,cy,r);
    view.onTouchEvent(event(5,1,new int[]{7,22},lx+r,cy,1212*.28f,720*.12f));
    near(1,sink.x[0]); check(sink.buttons.contains(CanonicalControl.L3),"stick plus click");
    view.onTouchEvent(event(5,2,new int[]{7,22,31},lx+r,cy,1212*.28f,720*.12f,1212*.82f,720*.12f));
    check(sink.buttons.equals(EnumSet.of(CanonicalControl.L3,CanonicalControl.R2)),"click plus trigger");
    // Reordered pointer indices and a lifted trigger must not release the stick/click.
    view.onTouchEvent(event(6,0,new int[]{31,7,22},1212*.82f,720*.12f,lx+r,cy,1212*.28f,720*.12f));
    near(1,sink.x[0]); check(sink.buttons.equals(EnumSet.of(CanonicalControl.L3)),"independent release");
    view.onWindowFocusChanged(false); near(0,sink.x[0]);
    check(sink.buttons.isEmpty(),"focus loss releases click");
    view.onTouchEvent(event(0,0,new int[]{1},1212*.18f,720*.12f));
    check(sink.buttons.contains(CanonicalControl.L2),"trigger held");
    view.setSystem("nes"); check(sink.buttons.isEmpty(),"system change releases trigger");
    // Labels must describe the guest controls, not fixed Thor face printing.
    for(String system:new String[]{"wii","Nintendo Wii","gc","psx","unknown"}) {
      view.setSystem(system);
      android.graphics.Canvas menu=new android.graphics.Canvas(); view.onDraw(menu);
      boolean wii=system.equals("wii")||system.equals("Nintendo Wii");
      String[] names=wii?new String[]{"−","+","2","1"}:
        new String[]{"L","R","−","+"};
      float[] mx={.08f,.92f,.46f,.54f},my={.12f,.12f,.88f,.88f};
      CanonicalControl[] controls={CanonicalControl.L1,CanonicalControl.R1,
        CanonicalControl.SELECT,CanonicalControl.START};
      for(int i=0;i<4;i++) {
        float xx=1212*mx[i],yy=720*my[i];
        check(names[i].equals(menu.at.get(Math.round(xx)+","+Math.round(yy))),
          system+" menu label "+controls[i]);
        view.onTouchEvent(event(0,0,new int[]{14},xx,yy));
        check(sink.buttons.equals(EnumSet.of(controls[i])),"unchanged menu dispatch");
        view.onTouchEvent(event(1,0,new int[]{14},xx,yy));
        check(sink.buttons.isEmpty(),"menu release");
      }
    }
    checkFaceLabels(view,"gba",null,"A",null,"B");
    checkFaceLabels(view,"gameboyadvance",null,"A",null,"B");
    checkFaceLabels(view,"gb",null,null,"B","A");
    check(!view.onTouchEvent(event(0,0,new int[]{6},rx,720*.816f)),
      "unmapped hidden face button captures touch");
    checkFaceLabels(view,"snes","X","B","Y","A");
    checkFaceLabels(view,"nds","X","B","Y","A");
    checkFaceLabels(view,"n3ds","X","B","Y","A");
    checkFaceLabels(view,"psp","△","×","□","○");
    checkFaceLabels(view,"psx","△","×","□","○");
    checkFaceLabels(view,"ps2","△","×","□","○");
    checkFaceLabels(view,"gc","Y","A","B","X");
    checkFaceLabels(view,"dreamcast","Y","A","X","B");
    checkFaceLabels(view,"n64","C↑","A","C↓","B");
    // N64 game prompts say Z, not the host controller's L2. Verify the
    // actual drawn label AND the unchanged canonical press/release route.
    android.graphics.Canvas n64=new android.graphics.Canvas(); view.onDraw(n64);
    check("Z".equals(n64.at.get(Math.round(1212*.18f)+","+Math.round(720*.12f))),
      "N64 Z trigger must be labelled Z rather than L2");
    check("C".equals(n64.at.get(Math.round(1212*.82f)+","+Math.round(720*.12f))),
      "N64 C-button modifier must describe C buttons rather than R2");
    view.onTouchEvent(event(0,0,new int[]{6},1212*.18f,720*.12f));
    check(sink.buttons.equals(EnumSet.of(CanonicalControl.L2)),"Z canonical dispatch");
    check(SystemControlLayouts.bindings("n64").get(CanonicalControl.L2).retroId==12,
      "Z must still reach the core's RetroPad L2 input");
    view.onTouchEvent(event(1,0,new int[]{6},1212*.18f,720*.12f));
    check(sink.buttons.isEmpty(),"Z release");
    // The shipped mupen default map ignores X/A unless R2's C mode is held.
    // The phone's explicitly labelled C arrows must instead reach the right
    // stick's C axis directly, without turning simultaneous A/B into C keys.
    for(String system:new String[]{"n64","Nintendo 64"}) {
      view.setSystem(system); view.setAnalogStickCount(2);
      float upY=720*.644f,downX=rx-720*.086f,faceY=720*.73f;
      view.onTouchEvent(event(0,0,new int[]{6},rx,upY));
      near(-1,sink.y[1]); check(sink.buttons.isEmpty(),"C up leaked a face/modifier key");
      view.onTouchEvent(event(5,1,new int[]{6,7},rx,upY,rx,720*.816f));
      near(-1,sink.y[1]); check(sink.buttons.equals(EnumSet.of(CanonicalControl.SOUTH)),
        "C up plus A must retain actual A, not C mode");
      view.onTouchEvent(event(6,0,new int[]{6,7},rx,upY,rx,720*.816f));
      near(0,sink.y[1]); check(sink.buttons.contains(CanonicalControl.SOUTH),"C release released A");
      view.releaseTouches(); check(sink.buttons.isEmpty(),"A release after C chord");
      view.onTouchEvent(event(0,0,new int[]{6},downX,faceY));
      near(1,sink.y[1]); check(sink.buttons.isEmpty(),"C down leaked a face/modifier key");
      view.onTouchEvent(event(5,1,new int[]{6,7},downX,faceY,rx,upY));
      near(0,sink.y[1]);
      view.onTouchEvent(event(6,1,new int[]{6,7},downX,faceY,rx,upY));
      near(1,sink.y[1]);
      view.onTouchEvent(event(3,0,new int[]{6},downX,faceY)); near(0,sink.y[1]);
      holdRight(view,9,rx,cy,r); near(1,sink.x[1]);
      view.onTouchEvent(event(5,1,new int[]{9,6},rx+r*2,cy,rx,upY));
      near(1,sink.x[1]); near(-1,sink.y[1]);
      view.onTouchEvent(event(6,1,new int[]{9,6},rx+r*2,cy,rx,upY));
      near(1,sink.x[1]); near(0,sink.y[1]);
      view.onWindowFocusChanged(false); near(0,sink.x[1]); near(0,sink.y[1]);
      view.onTouchEvent(event(0,0,new int[]{6},rx,upY)); near(-1,sink.y[1]);
      view.setSystem("snes"); near(0,sink.y[1]);
      view.onTouchEvent(event(0,0,new int[]{6},rx,upY));
      check(sink.buttons.equals(EnumSet.of(CanonicalControl.NORTH)),"SNES North changed");
      near(0,sink.y[1]); view.releaseTouches();
    }
    for(String system:new String[]{"n3ds","gc","dreamcast","ps2","switch"}) {
      view.setSystem(system);
      android.graphics.Canvas triggers=new android.graphics.Canvas(); view.onDraw(triggers);
      String left=system.equals("n3ds")?"ZL":
        (system.equals("gc")||system.equals("dreamcast"))?"L":"L2";
      String right=system.equals("n3ds")?"ZR":
        (system.equals("gc")||system.equals("dreamcast"))?"R":"R2";
      check(left.equals(triggers.at.get(Math.round(1212*.18f)+","+Math.round(720*.12f))),
        system+" left guest trigger label");
      check(right.equals(triggers.at.get(Math.round(1212*.82f)+","+Math.round(720*.12f))),
        system+" right guest trigger label");
    }
    for(String system:new String[]{"pcengine","pcenginecd","PC Engine CD"}) {
      checkFaceLabels(view,system,"IV","I","III","II");
      android.graphics.Canvas pce=new android.graphics.Canvas(); view.onDraw(pce);
      String[] labels={"V","VI","Mode","RUN"};
      float[] x={.08f,.92f,.18f,.54f},y={.12f,.12f,.12f,.88f};
      CanonicalControl[] controls={CanonicalControl.L1,CanonicalControl.R1,
        CanonicalControl.L2,CanonicalControl.START};
      for(int i=0;i<labels.length;i++) {
        check(labels[i].equals(pce.at.get(Math.round(1212*x[i])+","+Math.round(720*y[i]))),
          system+" phone control label "+labels[i]);
        view.onTouchEvent(event(0,0,new int[]{6},1212*x[i],720*y[i]));
        check(sink.buttons.equals(EnumSet.of(controls[i])),system+" canonical press "+labels[i]);
        view.onTouchEvent(event(1,0,new int[]{6},1212*x[i],720*y[i]));
        check(sink.buttons.isEmpty(),system+" release "+labels[i]);
      }
    }
    checkFaceLabels(view,"megadrive","Y","B","A","C");
    checkFaceLabels(view,"gamegear",null,"1",null,"2");
    checkFaceLabels(view,"nes","B","A","B","A");
    checkFaceLabels(view,"unknown","X","B","Y","A");
    checkFaceLabels(view,"switch","X","B","Y","A");
    // aPS3e receives Sony positions through the native adapter, not RetroPad.
    // Labels must describe those positions without changing canonical events.
    for(String system:new String[]{"ps3","PS3","PS 3"}) {
      checkFaceLabels(view,system,"△","×","□","○");
      float faceX=1212*.82f, faceY=720*.73f, delta=720*.086f;
      float[] xs={faceX,faceX,faceX-delta,faceX+delta};
      float[] ys={faceY-delta,faceY+delta,faceY,faceY};
      CanonicalControl[] expected={CanonicalControl.NORTH,CanonicalControl.SOUTH,
        CanonicalControl.WEST,CanonicalControl.EAST};
      for(int i=0;i<expected.length;i++) {
        view.onTouchEvent(event(0,0,new int[]{6},xs[i],ys[i]));
        check(sink.buttons.equals(EnumSet.of(expected[i])),system+" face dispatch "+i);
        view.onTouchEvent(event(1,0,new int[]{6},xs[i],ys[i]));
        check(sink.buttons.isEmpty(),system+" face release "+i);
      }
    }
    // Same extra-button sets must still update labels (e.g. NES -> SNES).
    checkFaceLabels(view,"snes","X","B","Y","A");
    view.onTouchEvent(event(0,0,new int[]{6},rx,720*.816f));
    check(sink.buttons.contains(CanonicalControl.SOUTH),"south dispatch changed");
    view.setSystem("nes"); check(sink.buttons.isEmpty(),"layout change keeps held face");
    System.out.println("Phone analog View multi-touch, geometry, release and mappings passed");
  }
}
"""


class PhoneAnalogControlsTest(unittest.TestCase):
    def test_real_view_events(self):
        for width, height in ((1212, 720), (960, 720), (1920, 1080)):
            with self.subTest(landscape=(width, height)):
                self.run_view_events(width, height)

    def run_view_events(self, width, height):
        with tempfile.TemporaryDirectory(prefix="emufusion-phone-input-") as name:
            root = Path(name)
            sources = []
            for path, text in STUBS.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text.replace("1212", str(width)).replace("720", str(height)))
                sources.append(str(target))
            harness = root / "PhoneAnalogTest.java"
            harness.write_text(HARNESS.replace("1212", str(width)).replace("720", str(height)))
            sources.append(str(harness))
            sources.extend(str(SRC / path) for path in (
                "preview/game/TouchControlsView.java", "lucent/input/TouchAnalogStick.java",
                "lucent/input/CanonicalControl.java", "lucent/input/SystemControlLayouts.java"))
            subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", str(root), *sources], check=True)
            subprocess.run([str(JAVA / "java"), "-cp", str(root),
                            "com.thorium.preview.game.PhoneAnalogTest"], check=True)

    def test_session_wiring_and_pause_release(self):
        game = SRC / "preview/game"
        source = (game / "InWindowGameHost.java").read_text()
        self.assertIn("session.dispatchVirtualAnalog(stick, x, y)", source)
        self.assertIn("touchControls.setAnalogStickCount(session.virtualAnalogStickCount())", source)
        self.assertIn("touchControls.setSystem(request.systemId)", source)
        pause = source[source.index("private void showPauseMenu()"):]
        self.assertLess(pause.index("touchControls.releaseTouches()"), pause.index("session.pause("))
        background = source[source.index("public static synchronized void onPause(Activity activity)"):]
        self.assertLess(background.index("touchControls.releaseTouches()"), background.index("current.pause("))
        gles = (game / "PpssppGlesEngineSession.java").read_text()
        self.assertIn("active.setAnalogAxis(0, stick, 0,", gles)
        self.assertIn("active.setAnalogAxis(0, stick, 1,", gles)
        native = (game / "NativeAdapterEngineSession.java").read_text()
        self.assertIn("stick == 0 ? PAD_LSTICK_X : PAD_RSTICK_X", native)
        self.assertIn("stick == 0 ? PAD_LSTICK_Y : PAD_RSTICK_Y", native)


if __name__ == "__main__":
    unittest.main()
