"""Execute the renderer's reference-copy loop; GPU readback is not emulated."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, SOURCE, method


class ReferenceCaptureTest(unittest.TestCase):
    def test_capture_arm_is_separate_from_rendering_proof_mode(self):
        body=method(SOURCE.read_text(),'private void beginFullImageCapture(')
        gate=body.split('fullImageAttempted = true;',1)[0]
        self.assertNotIn('qualificationProofEnabled',gate)
        for requirement in ['fullImageCapture != null','fullImageAttempted','!synthetic',
                            'frameId <= 0','/data/local/tmp/emufusion-full-frame-capture']:
            self.assertIn(requirement,gate)
        self.assertIn('backendForContext(actualEglContextMajor)',body)
        self.assertIn('FullResolutionFrameReadback.readbackName(actualEglContextMajor)',body)

    def test_references_are_retained_endpoints_not_shader_reconstructions(self):
        body=method(SOURCE.read_text(),'private void finishFullImageCapture(')
        loop=method(body,'for (int endpoint = 0; endpoint < 2; ++endpoint)')
        fixture='''
import java.util.*;
public class References {
    static class GLES20 {
        static final int GL_COLOR_BUFFER_BIT=1;
        static void glViewport(int a,int b,int c,int d){}
        static void glClearColor(float a,float b,float c,float d){}
        static void glClear(int mask){}
    }
    static class Capture {int count;void enqueue(long ordinal){assert ordinal==11;count++;}}
    Capture fullImageCapture=new Capture();
    int outputWidth=1920,outputHeight=1080,presents=10;
    int[] historyTextures={7,9};int previousIndex=1,currentIndex=0;
    List<Integer> copies=new ArrayList<Integer>();int viewports;
    void setPresentationViewport(){viewports++;}
    void drawTexture2d(int texture){copies.add(texture);}
    void drawMotionFrame(float phase){throw new AssertionError("Reference was synthesized");}
    void run(){
''' + loop + '''
    }
    public static void main(String[] args){
        References r=new References();r.run();
        assert r.copies.equals(Arrays.asList(9,7));
        assert r.viewports==2 && r.fullImageCapture.count==2;
    }
}'''
        with tempfile.TemporaryDirectory(prefix='reference-capture-') as d:
            out=Path(d);unit=out/'References.java';unit.write_text(fixture)
            subprocess.run([str(JAVA/'javac'),'-d',str(out),str(unit)],check=True)
            subprocess.run([str(JAVA/'java'),'-ea','-cp',str(out),'References'],check=True)


if __name__=='__main__':unittest.main()
