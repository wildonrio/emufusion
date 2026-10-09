"""Execute the real direct-canvas owner against small Android lifecycle fakes.

These check ownership/timestamp forwarding, not GPU cadence; that needs a device.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/bin')


class DirectHardwareCanvasTest(unittest.TestCase):
    def test_timestamp_and_surface_lifecycle(self):
        sources = {
            'android/util/Log.java': '''package android.util;
                public class Log {public static int calls;
                    public static int i(String tag,String message){calls++;return 0;} }''',
            'android/graphics/Canvas.java': 'package android.graphics; public class Canvas {}',
            'android/view/Surface.java': '''package android.view;
                public class Surface { public boolean valid=true;
                    public boolean isValid() {return valid;} }''',
            'android/graphics/RenderNode.java': '''package android.graphics;
                public class RenderNode {
                    public static int starts, ends, discards; public boolean recording;
                    public RenderNode(String n) {} public void setClipToBounds(boolean b) {}
                    public void setForceDarkAllowed(boolean b) {}
                    public void setPosition(int a,int b,int c,int d) {}
                    public Canvas beginRecording(int w,int h) {
                        if(recording) throw new AssertionError("nested recording");
                        recording=true; starts++; return new Canvas(); }
                    public void endRecording() {
                        if(!recording) throw new AssertionError("unbalanced recording");
                        recording=false; ends++; }
                    public void discardDisplayList() {discards++;}
                }''',
            'android/graphics/HardwareRenderer.java': '''package android.graphics;
                import android.view.Surface;
                public class HardwareRenderer {
                    public static final int SYNC_CONTEXT_IS_STOPPED=4, SYNC_FRAME_DROPPED=8,
                        SYNC_LOST_SURFACE_REWARD_IF_FOUND=2;
                    public static int creates,destroys, result; public static long stamp;
                    public static Surface target; public static boolean waitForPresent;
                    public HardwareRenderer(){creates++;}
                    public void destroy(){destroys++;}
                    public void setName(String n){} public void setContentRoot(RenderNode n){}
                    public void setLightSourceAlpha(float a,float b){}
                    public void setSurface(Surface s){target=s;}
                    public FrameRenderRequest createRenderRequest(){return new FrameRenderRequest();}
                    public static class FrameRenderRequest {
                        public FrameRenderRequest setVsyncTime(long t){stamp=t; return this;}
                        public FrameRenderRequest setWaitForPresent(boolean wait){
                            waitForPresent=wait; return this;}
                        public int syncAndDraw(){return result;}
                    }
                }''',
            'com/thorium/preview/game/DirectHardwareCanvasOwnerTest.java': '''
                package com.thorium.preview.game;
                import android.graphics.*; import android.view.Surface;
                public class DirectHardwareCanvasOwnerTest {
                    static void check(boolean b){if(!b)throw new AssertionError();}
                    public static void main(String[] args) {
                        DirectHardwareCanvas c=new DirectHardwareCanvas("test");
                        Surface s=new Surface(); c.begin(s,1440,1080,1);
                        check(c.post(123456789L)); check(HardwareRenderer.stamp==123456789L);
                        check(!HardwareRenderer.waitForPresent);
                        c.begin(s,800,600,1); c.post(234567891L);
                        check(HardwareRenderer.creates==1); // resize reuses owner
                        c.begin(s,1440,1080,2); c.post(345678912L);
                        check(!HardwareRenderer.waitForPresent); // normal rendering remains pipelined
                        check(HardwareRenderer.creates==2 && HardwareRenderer.destroys==1);
                        Surface replacement=new Surface(); c.begin(replacement,1440,1080,2);
                        check(HardwareRenderer.target==replacement); c.post(1);
                        check(HardwareRenderer.creates==3 && HardwareRenderer.destroys==2);
                        check(android.util.Log.calls==1); // no per-frame success spam
                        for(int n=0;n<1000;n++) {
                            c.begin(replacement,1440,1080,2); c.post(1);
                        }
                        check(android.util.Log.calls==1);
                        for(int result:new int[]{4,8,12}) {
                            HardwareRenderer.result=result; c.begin(replacement,1440,1080,2);
                            check(!c.post(1));
                        }
                        HardwareRenderer.result=2; c.begin(replacement,1440,1080,2);
                        check(!c.post(1)); check(HardwareRenderer.destroys==3);
                        HardwareRenderer.result=0; c.begin(replacement,1440,1080,3);
                        c.close(); c.close(); // ends recording, destroys once, not view Surface
                        check(HardwareRenderer.destroys==4);
                        check(RenderNode.starts==RenderNode.ends);
                        check(s.valid && replacement.valid);
                        replacement.valid=false;
                        try {c.begin(replacement,1440,1080,4); throw new AssertionError();}
                        catch(IllegalArgumentException expected){}
                        check(HardwareRenderer.creates==4);
                        System.out.println("DirectHardwareCanvasOwnerTest passed");
                    }
                }''',
        }
        with tempfile.TemporaryDirectory(prefix='emufusion-direct-canvas-') as tmp:
            base = Path(tmp)
            paths = []
            for name, text in sources.items():
                path = base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                paths.append(str(path))
            source = ROOT / 'unified-android/src/com/thorium/preview/game/DirectHardwareCanvas.java'
            subprocess.run([str(JAVA / 'javac'), '-d', tmp, *paths, str(source)], check=True)
            subprocess.run([str(JAVA / 'java'), '-cp', tmp,
                            'com.thorium.preview.game.DirectHardwareCanvasOwnerTest'], check=True)


if __name__ == '__main__':
    unittest.main()
