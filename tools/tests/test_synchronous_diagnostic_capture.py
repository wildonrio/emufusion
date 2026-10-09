"""Exercise real bounded GLES2 capture with a recording GL leaf."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA,ROOT


class SynchronousCaptureTest(unittest.TestCase):
    def test_three_images_identity_error_and_closed_state(self):
        gl='''package android.opengl;
import java.nio.*;
public class GLES20 {
 public static final int GL_NO_ERROR=0,GL_RGBA=1,GL_UNSIGNED_BYTE=2,GL_PACK_ALIGNMENT=3;
 public static int calls,error,alignment=8;
 public static void glGetIntegerv(int key,int[] a,int i){a[i]=alignment;}
 public static void glPixelStorei(int key,int value){alignment=value;}
 public static int glGetError(){int e=error;error=0;return e;}
 public static void glReadPixels(int x,int y,int w,int h,int f,int t,Buffer b){
  assert alignment==1;calls++;ByteBuffer out=(ByteBuffer)b;for(int i=0;i<w*h*4;i++)out.put(i,(byte)calls);
 }
}'''
        fixture='''package com.thorium.preview.game;
import android.opengl.GLES20;
public class SyncCaptureTest {
 public static void main(String[] args){
  assert FullResolutionFrameReadback.readbackName(2).equals("synchronous-diagnostic");
  assert FullResolutionFrameReadback.readbackName(3).equals("async-pbo");
  FullResolutionFrameReadback c=new FullResolutionFrameReadback(
    FullResolutionFrameReadback.backendForContext(2),2,2,4,42);
  c.enqueue(10);c.enqueue(10);c.enqueue(10);
  assert GLES20.calls==3 && GLES20.alignment==8;
  byte[][] images=c.poll(10,4,42);
  assert images.length==3 && c.isClosed();
  for(int i=0;i<3;i++){assert images[i].length==16;for(byte b:images[i])assert b==i+1;}
  assert c.poll(12,4,42)==null;c.close();
  c=new FullResolutionFrameReadback(FullResolutionFrameReadback.backendForContext(2),2,2,4,43);
  GLES20.error=1282;
  try{c.enqueue(10);throw new AssertionError();}catch(IllegalStateException expected){}
  assert c.isClosed() && GLES20.calls==3;
  try{FullResolutionFrameReadback.backendForContext(1);throw new AssertionError();}
  catch(IllegalArgumentException expected){}
 }
}'''
        with tempfile.TemporaryDirectory(prefix='sync-capture-') as d:
            out=Path(d);stub=out/'GLES20.java';test=out/'SyncCaptureTest.java'
            stub.write_text(gl);test.write_text(fixture)
            src=ROOT/'unified-android/src/com/thorium/preview/game'
            old=ROOT/'unified-android/test/com/thorium/preview/game/FullResolutionFrameReadbackTest.java'
            subprocess.run([str(JAVA/'javac'),'-d',str(out),str(stub),str(test),
                str(src/'FullResolutionFrameReadback.java'),str(src/'DenseGpuTimer.java'),str(old)],check=True)
            for name in ['SyncCaptureTest','FullResolutionFrameReadbackTest']:
                subprocess.run([str(JAVA/'java'),'-ea','-cp',str(out),'com.thorium.preview.game.'+name],check=True)


if __name__=='__main__':unittest.main()
