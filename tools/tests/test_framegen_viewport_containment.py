"""Execute the production viewport method against the shared geometry implementation."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class ViewportContainmentTest(unittest.TestCase):
    def test_actual_viewport_preserves_complete_image(self):
        src = ROOT / 'unified-android/src'
        body = method((src / 'com/thorium/preview/game/DisplayFrameGenerator.java').read_text(),
                      '    private void setPresentationViewport(')
        fixture = '''
public class ViewportTest {
    int outputWidth, outputHeight;
    float presentationAspect;
    static class GLES20 {
        static int x,y,w,h;
        static void glViewport(int a,int b,int c,int d){x=a;y=b;w=c;h=d;}
    }
''' + body + '''
    public static void main(String[] args) {
        ViewportTest t=new ViewportTest();
        for(int[] panel:new int[][]{{1920,1080},{1240,1080},{1080,1920},{1919,1079}}){
            t.outputWidth=panel[0];t.outputHeight=panel[1];
            for(float aspect:new float[]{4f/3f,16f/9f,2.4f,10f/9f,0f}){
                t.presentationAspect=aspect;t.setPresentationViewport();
                assert GLES20.x>=0 && GLES20.y>=0;
                assert GLES20.x+GLES20.w<=panel[0] && GLES20.y+GLES20.h<=panel[1];
                assert GLES20.w==panel[0] || GLES20.h==panel[1];
                float expected=aspect>0?aspect:(float)panel[0]/panel[1];
                assert Math.abs(GLES20.w-GLES20.h*expected)<=Math.max(1f,expected);
            }
        }
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='viewport-containment-') as directory:
            out = Path(directory)
            java = out / 'ViewportTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out),
                            '-sourcepath', str(src), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'ViewportTest'], check=True)
