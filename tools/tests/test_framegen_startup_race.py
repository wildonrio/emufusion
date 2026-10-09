"""Execute real SurfaceView lifecycle methods under controlled queue ordering."""
from pathlib import Path
import os
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


class StartupRaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get('EMUFUSION_STARTUP_VIEW_SOURCE',
                                   str(GAME / 'GameSurfaceView.java')))
        source = path.read_text()
        signatures = [
            '    public void setListener(', 'public void surfaceChanged(',
            '    private void startGeneratorAsync(',
            '    private void finishGeneratorStartup(',
            '    void requestOwnerDirect(',
            'public void surfaceDestroyed(', '    private void releaseGenerator(']
        if '    private void retireCancelledStartup(' in source:
            signatures.append('    private void retireCancelledStartup(')
        bodies = '\n'.join(method(source, s) for s in signatures)
        harness = r'''
package com.thorium.preview.game;
import java.util.*;
public class StartupRace {
    static boolean onWorker;
    static boolean enforceRetirementThread=true;
    static class Queue {
        final boolean worker; ArrayDeque<Runnable> tasks = new ArrayDeque<>();
        Queue(boolean worker) {this.worker=worker;}
        void execute(Runnable r) {tasks.add(r);} void post(Runnable r) {tasks.add(r);}
        void flush() {
            boolean before=onWorker;onWorker=worker;
            try {while(!tasks.isEmpty())tasks.remove().run();} finally {onWorker=before;}
        }
    }
    static class Log {
        static void i(String t,String m){} static void w(String t,String m){}
        static void e(String t,String m,Throwable e){}
    }
    static class android {static class os {static class SystemClock {
        static long elapsedRealtime(){return 0;}
    }}}
    static class FrameGenerationSettings {enum Mode {OFF, BUILT_IN_ALPHA, LSFG}}
    static class FrameGenerationBackendPolicy {enum Backend {DIRECT, BUILTIN}}
    static class Surface {boolean valid=true; Renderer owner; boolean isValid(){return valid;}}
    static class SurfaceHolder {Surface output=new Surface(); Surface getSurface(){return output;}}
    static class Renderer {
        Surface input=new Surface();int closes,resizes;boolean published,failClose;
        Renderer(){input.owner=this;}
        void close(){
            assert published || onWorker || !enforceRetirementThread : "unpublished renderer closed on UI";
            closes++;
            if(failClose)throw new IllegalStateException("retirement failed");
            input.valid=false;
        }
        Surface inputSurface(){return input;}
        void setAuthoritativeSourceHz(double v){} void setProducerTimelineHz(double v){}
        void setStatsListener(Object v){} void setFirstSubmittedFrameListener(Runnable v){}
        void setSlotLatticeProducer(boolean v){}
        void resize(int w,int h,int a,int b,float hz){resizes++;}
    }
    static class FrameGenerationRenderer extends Renderer {}
    static class GameSurface {
      interface RetirementCompletion {void complete(Throwable failure);}
      static class Listener {
        int available,resizes,destroys,errors,lastWidth,lastHeight;Surface last;
        FrameGenerationRenderer retiring;RetirementCompletion retirement;
        void retireSurfaceRenderer(FrameGenerationRenderer r,RetirementCompletion c){
            destroys++;retiring=r;retirement=c;
        }
        void acknowledgeRetirement(boolean ok){
            assert retirement!=null;
            Throwable problem=ok?null:new IllegalStateException("producer still owns input");
            if(ok){onWorker=true;try{retiring.close();}finally{onWorker=false;}}
            retirement.complete(problem);retirement=null;
        }
        void onSurfaceAvailable(Surface s,int w,int h){
            assert !onWorker : "engine publication must run on UI";
            assert s!=null && s.isValid() : "published stale/null renderer input";
            available++;last=s;lastWidth=w;lastHeight=h;
            if(s.owner!=null)s.owner.published=true;
        }
        void onSurfaceSizeChanged(int w,int h){resizes++;}
        void onSurfaceDestroyed(){destroys++;}
        void onSurfaceStartupError(String m,Throwable e){errors++;}
    }}
    static class Primary {
        static final String TAG="test";
        Queue GENERATOR_STARTUP=new Queue(true),mainHandler=new Queue(false);
        boolean surfaceLive,runtimePresentationFailed,generatorStartupPending;
        boolean startupFellBackToDirect,runtimeRecoveryPending,slotLatticeProducer,ownerRequestedDirect;
        int surfaceGeneration,quarantinedSurfaceGeneration=-1,pendingWidth,pendingHeight;
        float lastReportedPanelHz;double authoritativeSourceHz,producerTimelineHz;
        Object frameRateListener;Runnable firstSubmittedFrameListener;
        GameSurface.Listener listener=new GameSurface.Listener();
        Surface outputSurface,engineSurface;FrameGenerationRenderer frameGenerator;
        FrameGenerationBackendPolicy.Backend activeBackend=FrameGenerationBackendPolicy.Backend.DIRECT;
        FrameGenerationSettings.Mode launchMode=FrameGenerationSettings.Mode.BUILT_IN_ALPHA;
        SurfaceHolder holder=new SurfaceHolder();int width=1920,height=1080,creates;
        RuntimeException createFailure; boolean failClose;
        ArrayList<FrameGenerationRenderer> made=new ArrayList<>();
        SurfaceHolder getHolder(){return holder;}int getWidth(){return width;}int getHeight(){return height;}
        float rendererRefreshRate(){return 120;}
        String activeFrameGenerationBackend(){return activeBackend.name();}
        void propagatePanelRefresh(String s){}void bindRuntimeErrorListener(int g){}
        void requestDirectFrameRate(Surface s){}
        void createGenerator(Surface output,int w,int h){
            releaseGenerator();outputSurface=output;
            if(launchMode==FrameGenerationSettings.Mode.OFF || startupFellBackToDirect){
                activeBackend=FrameGenerationBackendPolicy.Backend.DIRECT;engineSurface=output;return;
            }
            assert onWorker : "FG construction must run on worker";
            creates++;
            if(createFailure!=null)throw createFailure;
            frameGenerator=new FrameGenerationRenderer();frameGenerator.failClose=failClose;
            made.add(frameGenerator);engineSurface=frameGenerator.inputSurface();
            activeBackend=FrameGenerationBackendPolicy.Backend.BUILTIN;
        }
        void changed(){surfaceChanged(holder,0,width,height);}
        void destroyed(){surfaceDestroyed(holder);holder.output.valid=false;}
        void recreated(){holder=new SurfaceHolder();changed();}
        void drain(){
            for(int i=0;i<10 && (!GENERATOR_STARTUP.tasks.isEmpty() || !mainHandler.tasks.isEmpty());i++){
                GENERATOR_STARTUP.flush();mainHandler.flush();
            }
            assert GENERATOR_STARTUP.tasks.isEmpty() && mainHandler.tasks.isEmpty() : "startup retry loop";
        }
''' + bodies + r'''
    }
    public static void main(String[] args){
        int scenario=Integer.parseInt(args[0]);Primary p=new Primary();
        if(scenario==0){
            enforceRetirementThread=false; // reach the wrong-generation handoff assertion
            p.changed();p.destroyed();p.recreated();
            p.drain();
            assert p.listener.available==1 && p.listener.last==p.engineSurface;
            assert p.creates==2 && p.made.get(0).closes==1 && p.made.get(1).closes==0;
        }else if(scenario==1){
            p.changed();p.GENERATOR_STARTUP.flush();p.destroyed();p.recreated();p.drain();
            assert p.listener.available==1 && p.made.get(0).closes==1 && p.made.get(1).closes==0;
        }else if(scenario==2){
            p.changed();p.GENERATOR_STARTUP.flush();
            GameSurface.Listener next=new GameSurface.Listener();p.setListener(next);
            assert next.available==0 : "listener got unpublished startup result";
            p.mainHandler.flush();assert next.available==1;
        }else if(scenario==3){
            p.changed();p.destroyed();p.drain();
            assert p.listener.available==0 && p.made.get(0).closes==1 && !p.generatorStartupPending;
        }else if(scenario==4){
            p.changed();p.destroyed();p.recreated();p.width=1240;p.height=930;p.changed();p.drain();
            assert p.listener.available==1 && p.listener.lastWidth==1240 && p.listener.lastHeight==930;
        }else if(scenario==5){
            p.launchMode=FrameGenerationSettings.Mode.OFF;p.changed();
            assert p.listener.available==1 && p.engineSurface==p.holder.output && p.creates==0;
            p.destroyed();p.recreated();
            assert p.listener.available==2 && p.engineSurface==p.holder.output && p.creates==0;
            assert p.GENERATOR_STARTUP.tasks.isEmpty() && p.mainHandler.tasks.isEmpty();
        }else if(scenario==6){
            p.failClose=true;p.changed();p.destroyed();p.recreated();p.drain();
            assert p.listener.available==0 && p.listener.errors==1 && p.creates==1;
            p.destroyed();p.recreated();p.drain();assert p.creates==1;
        }else if(scenario==7){
            p.createFailure=new SurfaceOwnershipException("startup still owns output",null);
            p.changed();p.destroyed();p.recreated();p.drain();
            assert p.listener.available==0 && p.listener.errors==1 && p.creates==1;
        }else if(scenario==8){
            p.changed();p.destroyed();p.GENERATOR_STARTUP.flush();p.mainHandler.flush();
            p.recreated();p.destroyed();p.recreated();p.drain();
            assert p.listener.available==1 && p.made.get(0).closes==1;
        }else if(scenario==9){
            p.changed();p.width=1280;p.height=720;p.changed();p.drain();
            assert p.creates==1 && p.listener.available==1 && p.listener.lastWidth==1280;
            assert p.made.get(0).resizes==1 && p.made.get(0).closes==0;
        }else if(scenario==10 || scenario==11 || scenario==12){
            p.changed();p.drain();FrameGenerationRenderer first=p.frameGenerator;
            p.destroyed();
            assert first.closes==0 && first.input.isValid() : "released input during native startup";
            p.recreated();p.setListener(p.listener);p.drain();
            assert p.creates==1 && p.listener.available==1 : "wake passed retirement gate";
            if(scenario==12)p.destroyed();
            p.listener.acknowledgeRetirement(scenario!=11);p.drain();
            if(scenario==11){
                assert first.closes==0 && p.runtimePresentationFailed && p.listener.errors==1;
                assert p.frameGenerator==first && p.creates==1;
            }else{
                assert first.closes==1;
                assert p.creates==(scenario==10?2:1);
                assert p.listener.available==(scenario==10?2:1);
            }
        }else if(scenario>=13 && scenario<=16){
            p.failClose=scenario==15;
            p.changed();
            if(scenario!=13)p.GENERATOR_STARTUP.flush();
            if(scenario==16){p.destroyed();p.recreated();}
            p.requestOwnerDirect();
            assert p.listener.available==0;
            p.drain();
            assert p.creates==(scenario==13?0:1);
            for(FrameGenerationRenderer r:p.made){
                assert !r.published && r.closes==1 : "Off published an intermediate Surface";
            }
            if(scenario==15){
                assert p.listener.available==0 && p.listener.errors==1;
                assert p.runtimePresentationFailed;
            }else{
                assert p.listener.available==1 && p.listener.last==p.holder.output;
                assert p.frameGenerator==null && p.startupFellBackToDirect;
                p.destroyed();p.recreated();p.drain();
                assert p.listener.available==2 && p.listener.last==p.holder.output;
                assert p.creates==(scenario==13?0:1) : "wake reenabled generation";
            }
        }else throw new AssertionError("unknown scenario");
    }
}
'''
        cls.temp = tempfile.TemporaryDirectory(prefix='fg-startup-race-')
        cls.addClassCleanup(cls.temp.cleanup)
        out = Path(cls.temp.name)
        fixture = out / 'StartupRace.java'
        fixture.write_text(harness)
        result = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out),
                                 str(GAME / 'SurfaceOwnershipException.java'), str(fixture)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_lifecycle_queue_interleavings(self):
        for scenario in range(17):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(JAVA / 'java'), '-ea', '-cp', self.temp.name,
                                         'com.thorium.preview.game.StartupRace', str(scenario)],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cancelled_startup_error_cannot_reopen_retired_game_ui(self):
        path = Path(os.environ.get('EMUFUSION_STARTUP_HOST_SOURCE',
                                   str(GAME / 'InWindowGameHost.java')))
        body = method(path.read_text(), 'public void onSurfaceStartupError(')
        harness = r'''
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
public class StartupError {
    static class Queue {
        ArrayDeque<Runnable> tasks=new ArrayDeque<>();int removed;boolean finishing,destroyed;
        void runOnUiThread(Runnable r){tasks.add(r);}boolean isFinishing(){return finishing;}
        boolean isDestroyed(){return destroyed;}void removeCallbacks(Runnable r){removed++;}
        void flush(){while(!tasks.isEmpty())tasks.remove().run();}
    }
    static class View {static final int GONE=8;int value;void setVisibility(int v){value=v;}}
    static class Log {static void e(String a,String b,Throwable c){}}
    static class Host {
        static final String TAG="test";Queue activity=new Queue(),mainHandler=activity;
        boolean libraryReturned,fatalErrorVisible,surfaceAvailable=true;AtomicBoolean exitStarted=new AtomicBoolean();
        Runnable revealLaunchSpinner=()->{};View launchSpinner=new View();int shown,updates;
        void updateGameplayScreenOn(){updates++;}void showFatalError(String m){shown++;fatalErrorVisible=true;}
''' + body + r'''
    }
    public static void main(String[] args){
        for(int state=0;state<6;state++){
            Host h=new Host();h.onSurfaceStartupError("cancelled",null);
            if(state==1)h.libraryReturned=true;if(state==2)h.exitStarted.set(true);
            if(state==3)h.activity.finishing=true;if(state==4)h.activity.destroyed=true;
            if(state==5)h.fatalErrorVisible=true;
            assert h.surfaceAvailable && h.updates==0 : "stale startup error changed state before UI admission";
            h.activity.flush();
            assert h.shown==(state==0?1:0) && h.updates==(state==0?1:0);
            assert h.surfaceAvailable==(state!=0);
            if(state==0){
                assert h.mainHandler.removed==1 && h.launchSpinner.value==View.GONE;
                h.onSurfaceStartupError("duplicate",null);h.activity.flush();assert h.shown==1;
            }
        }
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='fg-startup-error-') as temp:
            out = Path(temp)
            source = out / 'StartupError.java'
            source.write_text(harness)
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', str(source)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'StartupError'],
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


if __name__ == '__main__':
    unittest.main()
