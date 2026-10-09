"""The actual lower-surface binding stays Direct for every primary FG mode."""
from pathlib import Path
import re
import unittest

from tools.tests import test_runtime_direct_recovery as recovery

method = recovery.method

ROOT = Path(__file__).resolve().parents[2]
PREVIEW = ROOT / 'android-companion/src/com/thorium/preview/PreviewActivity.java'


class SecondaryDirectPolicyTest(unittest.TestCase):
    def test_actual_mode_selection_and_binding_never_start_a_lower_generator(self):
        show = method(PREVIEW, '    private void showGameplaySurface(')
        assignment = re.search(r'gameplayFrameGenerationMode\s*=.*?;', show, re.S).group()
        self.assertLess(show.index(assignment), show.index('showClockwiseGameplaySurface();'))
        bind = method(PREVIEW, '    private void ensureGameplayGenerator(Surface output, int inputWidth')
        body = r'''
    static class Surface {}
    static class Log {static void i(String a,String b){}static void e(String a,String b,Throwable c){}}
    static class FrameGenerationBackendPolicy {
        enum Backend {DIRECT,BUILT_IN,LSFG}
        static class Selection {Backend backend;Selection(Backend b){backend=b;}}
    }
    static class FrameGenerationSettings {
        enum Mode {OFF,BUILT_IN_ALPHA,LSFG}
        static Mode primary;
        static Mode mode(Object context){return primary;}
        static FrameGenerationBackendPolicy.Selection selectBackendForSession(Object context,Mode mode){
            return new FrameGenerationBackendPolicy.Selection(mode==Mode.OFF ?
                FrameGenerationBackendPolicy.Backend.DIRECT:FrameGenerationBackendPolicy.Backend.BUILT_IN);}
    }
    static class FrameGenerationRenderer {Surface inputSurface(){return new Surface();}void close(){}}
    static class FrameGenerationRendererFactory {
        static int calls;
        static FrameGenerationRenderer create(Object selection,Surface output,int a,int b,int c,int d,
            float hz,String label,int id,java.util.function.BooleanSupplier q,
            java.util.function.BooleanSupplier p,java.util.function.BooleanSupplier r,
            java.util.function.BooleanSupplier s){calls++;return new FrameGenerationRenderer();}
    }
    static class SurfaceOwnershipException extends RuntimeException {
        SurfaceOwnershipException(String message,Throwable cause){super(message,cause);}
        static boolean isUnsafe(Throwable f){return false;}
    }
    static class Preview {
        long gameplayGeneration=2,gameplayGeneratorGeneration,gameplayQuarantinedGeneration;
        Surface gameplayEngineSurface;
        FrameGenerationRenderer gameplayFrameGenerator;
        FrameGenerationSettings.Mode gameplayFrameGenerationMode;
        void selectMode(){
''' + assignment + r'''
        }
        float displayRefreshRate(){return 120;}int displayId(){return 4;}
        boolean qualificationProofEnabled(){return false;}boolean densePyramidEnabled(){return false;}
        boolean denseV27ReducedAnalysisEnabled(){return false;}boolean denseV28ReducedAnalysisEnabled(){return false;}
        void bindGameplayRuntimeErrorListener(FrameGenerationRenderer r,long g){}
        void quarantineGameplayGenerator(long g,Throwable f){throw new AssertionError(f);}
''' + bind + r'''
    }
    public static void main(String[] args) {
        for(FrameGenerationSettings.Mode primary:FrameGenerationSettings.Mode.values())
            for(int[] size:new int[][]{{1240,1080,1240,1080},{1080,1240,1240,1080}}) {
                FrameGenerationSettings.primary=primary;
                Preview p=new Preview();p.selectMode();
                Surface output=new Surface();
                p.ensureGameplayGenerator(output,size[0],size[1],size[2],size[3]);
                assert FrameGenerationSettings.primary==primary:"primary preference changed";
                assert p.gameplayFrameGenerator==null:"lower generator allocated";
                assert p.gameplayEngineSurface==output:"lower Surface identity changed";
                assert p.gameplayGeneratorGeneration==2;
                p.ensureGameplayGenerator(output,size[0],size[1],size[2],size[3]);
                assert p.gameplayEngineSurface==output;
            }
        assert FrameGenerationRendererFactory.calls==0:"lower FG pipeline started";
    }
'''
        recovery.RuntimeDirectRecoveryTest.run_java(self, body)


if __name__ == '__main__':
    unittest.main()
