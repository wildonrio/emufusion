"""Run production Surface startup bodies against deterministic Android leaves."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end].replace('@Override ', '')


class FramegenStartupFallbackTest(unittest.TestCase):
    def test_failed_startup_stays_direct_until_new_game_view(self):
        view = (GAME / 'GameSurfaceView.java').read_text()
        legacy = (GAME / 'GameSurface.java').read_text()
        primary_methods = '\n'.join(method(view, signature) for signature in [
            '    private void createGenerator(',
            '    private void retireFailedGenerator(',
            '    private void useDirectAfterUnavailableLsfg(',
            '    private void releaseGenerator(',
            'public void surfaceChanged('])
        legacy_methods = '\n'.join(method(legacy, signature) for signature in [
            '    private void ensureSurface(', '    private void releaseSurfaces('])
        source = r'''
package com.thorium.preview.game;
public class StartupFallbackTest {
    static class SurfaceTexture {}
    static class Surface {
        boolean valid=true;
        Surface(){} Surface(SurfaceTexture t){}
        boolean isValid(){return valid;} void release(){valid=false;}
    }
    static class SurfaceHolder {Surface s=new Surface(); Surface getSurface(){return s;}}
    static class Log {
        static void i(String a,String b){} static void e(String a,String b){}
        static void e(String a,String b,Throwable t){} static void w(String a,String b,Throwable t){}
        static void w(String a,String b){}
    }
    static class Handler {boolean post(Runnable r){r.run();return true;}}
    static class android {static class widget {static class Toast {
        static final int LENGTH_LONG=1;
        static Toast makeText(Object c,String m,int d){return new Toast();} void show(){}
    }}}
    static class FrameGenerationBackendPolicy {
        enum Backend {DIRECT, BUILTIN, LSFG}
        static class Selection {Backend backend=Backend.BUILTIN;}
    }
    static class FrameGenerationSettings {
        enum Mode {OFF, BUILT_IN_ALPHA, LSFG}
        static int selections,probes; static boolean available=true,directSelection;
        static class QualificationTransport {
            Object factory=new Object(); String label="LSFG";
            FrameGenerationBackendPolicy.Backend backend=FrameGenerationBackendPolicy.Backend.LSFG;
        }
        static QualificationTransport qualificationTransport(Object c,int d,Mode m){
            probes++;return m==Mode.LSFG && available ? new QualificationTransport():null;
        }
        static FrameGenerationBackendPolicy.Selection selectBackendForSession(Object c,Mode m){
            selections++; FrameGenerationBackendPolicy.Selection s=new FrameGenerationBackendPolicy.Selection();
            if(directSelection)s.backend=FrameGenerationBackendPolicy.Backend.DIRECT; return s;
        }
    }
    static class FrameGenerationRenderer {
        int closes; boolean failClose; Surface input=new Surface();
        void close(){closes++;if(failClose)throw new IllegalStateException("close unresolved");if(input!=null)input.release();}
        void setAuthoritativeSourceHz(double h){} void setProducerTimelineHz(double h){}
        void setSlotLatticeProducer(boolean enabled){}
        void setStatsListener(Object o){} void setFirstSubmittedFrameListener(Runnable r){}
        Surface inputSurface(){return input;}
        void resize(int a,int b,int c,int d,float h){}
    }
    static class FrameGenerationRendererRegistry {static int liveCount(){return 0;}}
    static class FrameGenerationRendererFactory {
        static int creates; static boolean fail=true,unsafe,invalidInput,nullInput;
        static FrameGenerationRenderer last;
        static int createdCount(){return creates;}
        static FrameGenerationRenderer make(){
            creates++;
            if(unsafe)throw new SurfaceOwnershipException("unreleased output",null);
            if(fail)throw new IllegalStateException("backend unavailable");
            last=new FrameGenerationRenderer();
            if(invalidInput)last.input.valid=false;
            if(nullInput)last.input=null;
            return last;
        }
        static FrameGenerationRenderer create(Object s,Surface o,int w,int h,int a,int b,float r,
                String label,int d,java.util.function.BooleanSupplier... flags){return make();}
        static FrameGenerationRenderer createExternalQualification(Object s,Surface o,int w,int h,int a,int b,
                float r,String label,int d,java.util.function.BooleanSupplier flag){return make();}
    }
    static class Listener {
        int available,resizes,errors;
        void onSurfaceAvailable(Surface s,int w,int h){available++;}
        void onSurfaceSizeChanged(int w,int h){resizes++;}
        void onSurfaceStartupError(String m,Throwable t){errors++;}
    }
    static class Primary {
        static final String TAG="fixture";
        boolean startupFellBackToDirect,runtimePresentationFailed,surfaceLive,generatorStartupPending,runtimeRecoveryPending;
        int quarantinedSurfaceGeneration=-1,surfaceGeneration,pendingWidth,pendingHeight,asyncStarts;
        boolean lsfgUnavailableNotified,slotLatticeProducer; float lastReportedPanelHz;
        Surface outputSurface,engineSurface; FrameGenerationRenderer frameGenerator;
        FrameGenerationBackendPolicy.Backend activeBackend=FrameGenerationBackendPolicy.Backend.DIRECT;
        FrameGenerationSettings.Mode launchMode;
        Handler mainHandler=new Handler(); Listener listener=new Listener();
        Object frameRateListener; Runnable firstSubmittedFrameListener; double authoritativeSourceHz,producerTimelineHz;
        Primary(FrameGenerationSettings.Mode mode){launchMode=mode;}
        Object getContext(){return this;} int displayId(){return 0;}
        float refreshRate(){return 120f;} float rendererRefreshRate(){return 120f;}
        boolean qualificationProofEnabled(){return false;} boolean densePyramidEnabled(){return true;}
        boolean denseV27ReducedAnalysisEnabled(){return false;} boolean denseV28ReducedAnalysisEnabled(){return true;}
        void requestDirectFrameRate(Surface s){} void propagatePanelRefresh(String r){}
        void startGeneratorAsync(Surface s,int w,int h){asyncStarts++;createGenerator(s,w,h);}
''' + primary_methods + r'''
    }
    static class Legacy {
        static final String TAG="fixture";
        boolean startupFellBackToDirect,runtimePresentationFailed,firstFrameSubmitted;
        Surface outputSurface,renderSurface; SurfaceTexture quarantinedTexture;
        FrameGenerationRenderer frameGenerator; int surfaceGeneration;
        FrameGenerationSettings.Mode launchMode;
        FrameGenerationBackendPolicy.Backend activeBackend=FrameGenerationBackendPolicy.Backend.DIRECT;
        Object frameRateListener; Listener listener=new Listener();
        Legacy(FrameGenerationSettings.Mode mode){launchMode=mode;}
        Object getContext(){return this;} int displayId(){return 0;} float refreshRate(){return 120f;}
        void requestDirectFrameRate(Surface s){} void bindRuntimeErrorListener(){}
''' + legacy_methods + r'''
    }
    static void reset(){
        FrameGenerationRendererFactory.creates=0;FrameGenerationRendererFactory.fail=true;
        FrameGenerationRendererFactory.unsafe=false;FrameGenerationSettings.available=true;
        FrameGenerationRendererFactory.invalidInput=false;
        FrameGenerationRendererFactory.nullInput=false;
        FrameGenerationSettings.directSelection=false;FrameGenerationSettings.selections=0;
        FrameGenerationSettings.probes=0;
    }
    public static void main(String[] args){
        for(FrameGenerationSettings.Mode mode:FrameGenerationSettings.Mode.values()){
            reset(); Primary p=new Primary(mode); SurfaceHolder holder=new SurfaceHolder();
            p.surfaceChanged(holder,0,1920,1080);
            assert p.engineSurface==holder.s && p.frameGenerator==null;
            int attempts=FrameGenerationRendererFactory.creates, async=p.asyncStarts;
            assert attempts==(mode==FrameGenerationSettings.Mode.OFF?0:mode==FrameGenerationSettings.Mode.LSFG?2:1);
            for(int wake=0;wake<3;wake++){
                p.releaseGenerator();p.surfaceGeneration++;holder=new SurfaceHolder();
                p.surfaceChanged(holder,0,1920,1080);
                assert FrameGenerationRendererFactory.creates==attempts : "wake retried failed generator";
                assert p.asyncStarts==async : "Direct wake waited for generator worker";
                assert p.engineSurface==holder.s && p.frameGenerator==null;
            }
            assert p.launchMode==mode : "fallback changed owner preference";
            Primary next=new Primary(mode);next.surfaceChanged(new SurfaceHolder(),0,1920,1080);
            assert FrameGenerationRendererFactory.creates==attempts*2 : "new game cannot retry owner selection";
            if(mode==FrameGenerationSettings.Mode.OFF)
                assert FrameGenerationSettings.probes==0 && FrameGenerationSettings.selections==0;
        }
        reset();FrameGenerationSettings.available=false;
        Primary missing=new Primary(FrameGenerationSettings.Mode.LSFG);
        missing.createGenerator(new Surface(),1920,1080);
        int probes=FrameGenerationSettings.probes;missing.releaseGenerator();
        FrameGenerationSettings.available=true;missing.createGenerator(new Surface(),1920,1080);
        assert FrameGenerationSettings.probes==probes && FrameGenerationRendererFactory.creates==0;
        for(boolean selection:new boolean[]{false,true}){
            reset();FrameGenerationSettings.directSelection=selection;
            Legacy l=new Legacy(FrameGenerationSettings.Mode.BUILT_IN_ALPHA);
            l.ensureSurface(new SurfaceTexture(),1920,1080);
            assert l.renderSurface==l.outputSurface && l.frameGenerator==null;
            int attempts=FrameGenerationRendererFactory.creates,selections=FrameGenerationSettings.selections;
            l.releaseSurfaces();l.ensureSurface(new SurfaceTexture(),1920,1080);
            assert FrameGenerationRendererFactory.creates==attempts : "TextureView retried unavailable generator";
            assert FrameGenerationSettings.selections==selections;
            assert l.renderSurface==l.outputSurface;
        }
        for(FrameGenerationSettings.Mode mode:new FrameGenerationSettings.Mode[]{
                FrameGenerationSettings.Mode.BUILT_IN_ALPHA,FrameGenerationSettings.Mode.LSFG}){
          for(boolean absent:new boolean[]{false,true}){
            reset();FrameGenerationRendererFactory.fail=false;
            FrameGenerationRendererFactory.invalidInput=true;
            FrameGenerationRendererFactory.nullInput=absent;
            Primary invalid=new Primary(mode);Surface output=new Surface();
            invalid.createGenerator(output,1920,1080);
            assert invalid.engineSurface==output : "invalid generator input reached engine";
            assert invalid.frameGenerator==null && invalid.startupFellBackToDirect;
            assert FrameGenerationRendererFactory.last.closes==1 : "invalid input renderer leaked";
          }
        }
        reset();FrameGenerationRendererFactory.fail=false;
        Primary success=new Primary(FrameGenerationSettings.Mode.BUILT_IN_ALPHA);
        success.createGenerator(new Surface(),1920,1080);FrameGenerationRenderer renderer=success.frameGenerator;
        assert renderer!=null && !success.startupFellBackToDirect;
        success.releaseGenerator();assert renderer.closes==1;
        success.createGenerator(new Surface(),1920,1080);assert success.frameGenerator!=null;
        reset();FrameGenerationRendererFactory.unsafe=true;
        Primary unsafe=new Primary(FrameGenerationSettings.Mode.LSFG);
        try{unsafe.createGenerator(new Surface(),1920,1080);throw new AssertionError("unsafe reuse");}
        catch(SurfaceOwnershipException expected){}
        assert !unsafe.startupFellBackToDirect && unsafe.engineSurface==null;
        Legacy quarantined=new Legacy(FrameGenerationSettings.Mode.BUILT_IN_ALPHA);
        SurfaceTexture texture=new SurfaceTexture();quarantined.ensureSurface(texture,1920,1080);
        assert quarantined.renderSurface==null && quarantined.quarantinedTexture==texture;
        assert !quarantined.startupFellBackToDirect && quarantined.listener.errors==1;
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='fg-startup-fallback-') as temporary:
            out = Path(temporary)
            fixture = out / 'StartupFallbackTest.java'
            fixture.write_text(source)
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out),
                                       str(GAME / 'SurfaceOwnershipException.java'), str(fixture)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out),
                                  'com.thorium.preview.game.StartupFallbackTest'],
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


if __name__ == '__main__':
    unittest.main()
