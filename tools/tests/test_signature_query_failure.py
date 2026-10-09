"""Execute the real signature draw boundary against controlled query failures."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from tools.tests.test_native_source_image_renderer_wiring import JAVA, SOURCE, method


class SignatureQueryFailureTest(unittest.TestCase):
    def test_failure_evidence_and_gl_state_restoration(self):
        body = method(SOURCE.read_text(), 'private void drawSignatureDifferenceQuery(')
        fixture = '''
import java.util.*;
public class QueryTest {
    static class GLES20 {
        static final int GL_SCISSOR_TEST=1,GL_DEPTH_TEST=2,GL_STENCIL_TEST=3,
            GL_CULL_FACE=4,GL_TRIANGLE_STRIP=5;
        static final Set<Integer> enabled=new HashSet<Integer>();
        static int draws;
        static boolean glIsEnabled(int x){return enabled.contains(x);}
        static void glDisable(int x){enabled.remove(x);}
        static void glEnable(int x){enabled.add(x);}
        static void glUseProgram(int x){}
        static void glDrawArrays(int a,int b,int c){draws++;}
    }
    static class DenseGpuTimer {
        boolean accepts;int pending,ended;
        boolean beginSignature(long sequence){return accepts;}
        int pendingSignatures(){return pending;}
        void endSignature(){ended++;}
    }
    int signatureCompareProgram=1,signatureTexture=2,signaturePreviousTexture=3;
    int signatureCapability(DenseGpuTimer timer){return timer==null?0:63;}
    void bindQuad(int program){}
    void bindTexture(int a,String b,int c,int d){}
''' + body + '''
    public static void main(String[] args){
        QueryTest q=new QueryTest();
        for(int pending:new int[]{0,4}){
            DenseGpuTimer timer=new DenseGpuTimer();timer.pending=pending;
            GLES20.enabled.clear();GLES20.enabled.add(1);GLES20.enabled.add(3);
            try {q.drawSignatureDifferenceQuery(timer,5);throw new AssertionError();}
            catch(IllegalStateException e){
                assert e.getMessage().contains("begin failed sequence=5 pending="+pending+" capability=63");
                assert !e.getMessage().contains("ring full");
            }
            assert timer.ended==0 && GLES20.draws==0;
            assert GLES20.enabled.equals(new HashSet<Integer>(Arrays.asList(1,3)));
        }
        try {q.drawSignatureDifferenceQuery(null,6);throw new AssertionError();}
        catch(IllegalStateException e){assert e.getMessage().contains("pending=-1 capability=0");}
        DenseGpuTimer timer=new DenseGpuTimer();timer.accepts=true;
        q.drawSignatureDifferenceQuery(timer,7);
        assert timer.ended==1 && GLES20.draws==1;
        assert GLES20.enabled.equals(new HashSet<Integer>(Arrays.asList(1,3)));
    }
}'''
        with tempfile.TemporaryDirectory(prefix='signature-failure-') as directory:
            out = Path(directory)
            unit = out / 'QueryTest.java'
            unit.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), str(unit)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'QueryTest'], check=True)


if __name__ == '__main__':
    unittest.main()
