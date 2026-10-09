"""Published FG input survives native startup until an actual owner acknowledgement."""
from pathlib import Path
import os
import unittest
from tools.tests import test_runtime_direct_recovery as harness

GAME = harness.GAME


class PublishedSurfaceRetirementTest(unittest.TestCase):
    run_java = harness.RuntimeDirectRecoveryTest.run_java

    def test_host_retires_only_after_producer_ack_and_orders_exit(self):
        path = Path(os.environ.get('EMUFUSION_STARTUP_HOST_SOURCE',
                                   str(GAME / 'InWindowGameHost.java')))
        bodies = '\n'.join(harness.method(path, signature) for signature in (
            '    @Override public void retireSurfaceRenderer(',
            '    private void runAfterPresentationRecovery('))
        self.run_java(r'''
    static class Queue {ArrayDeque<Runnable> q=new ArrayDeque<>();
        void execute(Runnable r){q.add(r);}void post(Runnable r){q.add(r);}
        void flush(){while(!q.isEmpty())q.remove().run();}}
    static class EngineSession {boolean ack=true;int barriers;
        boolean quiesceForSurfaceRetirement(){barriers++;return ack;}}
    static class FrameGenerationRenderer {EngineSession owner;int closes;boolean fail;
        void close(){assert owner.barriers==1&&owner.ack;closes++;
            if(fail)throw new IllegalStateException("close failed");}}
    static class GameSurface {interface RetirementCompletion{void complete(Throwable failure);}}
    static class Log {static void i(String tag,String message){}}
    static class Request {String engineId="native";}
    static class Host {
        String TAG="test";Request request=new Request();boolean surfaceAvailable=true,presentationRecoveryPending;
        EngineSession session=new EngineSession(),retiringSession;
        Queue RETIREMENT_RELEASES=new Queue(),mainHandler=new Queue();int updates;
        void updateGameplayScreenOn(){updates++;}
''' + bodies + r'''
    }
    public static void main(String[] args){
        for(int mode=0;mode<5;mode++){
            Host h=new Host();FrameGenerationRenderer r=new FrameGenerationRenderer();r.owner=h.session;
            if(mode==1)r.owner.ack=false;if(mode==2)r.fail=true;
            if(mode==3){h.retiringSession=h.session;h.session=null;}
            if(mode==4)h.session=null;
            int[] completions={0},stops={0};Throwable[] result={null};
            h.retireSurfaceRenderer(r,f->{completions[0]++;result[0]=f;});
            assert !h.surfaceAvailable&&h.presentationRecoveryPending&&h.updates==1;
            assert r.closes==0&&r.owner.barriers==0&&completions[0]==0;
            final int expectedCloses=(mode==1||mode==4)?0:1;
            h.runAfterPresentationRecovery(()->{assert r.closes==expectedCloses;stops[0]++;});
            assert stops[0]==0;
            h.RETIREMENT_RELEASES.flush();assert stops[0]==1&&completions[0]==0;
            assert r.closes==((mode==1||mode==4)?0:1);
            h.mainHandler.flush();assert completions[0]==1&&!h.presentationRecoveryPending;
            assert (result[0]==null)==(mode==0||mode==3);
        }
    }
''')

    def test_native_barrier_covers_startup_longer_than_ui_wait(self):
        path = Path(os.environ.get('EMUFUSION_RETIREMENT_NATIVE_SOURCE',
                                   str(GAME / 'NativeAdapterEngineSession.java')))
        task = harness.method(path, '    private static final class RenderTask')
        body = harness.method(path, '    @Override public boolean quiesceForSurfaceRetirement(')
        self.run_java(r'''
    static class Log {static void w(String a,String b,Throwable t){}}
    static final String TAG="test";
    static class AudioTrack{int pauses;void pause(){pauses++;}}
    static class NativeAdapterHost {int pauses;void pause(){pauses++;}}
''' + task + r'''
    static class Session {
        volatile boolean prepared=true,started,resumeRequested=true;
        AtomicBoolean stopping=new AtomicBoolean(),released=new AtomicBoolean();
        Object surface=new Object();AudioTrack audioTrack=new AudioTrack();
        NativeAdapterHost host=new NativeAdapterHost();Thread renderThread;
        LinkedBlockingQueue<RenderTask> renderTasks=new LinkedBlockingQueue<>();
''' + body + r'''
    }
    public static void main(String[] args)throws Exception {
        for(int mode=0;mode<3;mode++){
            Session s=new Session();CountDownLatch entered=new CountDownLatch(1),finishStart=new CountDownLatch(1);
            CountDownLatch exit=new CountDownLatch(1);int which=mode;
            s.renderThread=new Thread(()->{try{
                entered.countDown();finishStart.await();s.started=which!=1;
                RenderTask t=s.renderTasks.take();if(which==2)t.abandon();else t.run();exit.await();
            }catch(InterruptedException e){throw new AssertionError(e);}});
            s.renderThread.start();entered.await();AtomicBoolean done=new AtomicBoolean(),ack=new AtomicBoolean();
            Thread retirement=new Thread(()->{ack.set(s.quiesceForSurfaceRetirement());done.set(true);});
            retirement.start();Thread.sleep(350);
            assert !done.get():"250ms elapsed is not native startup acknowledgement";
            assert !s.resumeRequested&&s.surface==null&&s.host.pauses==0;
            finishStart.countDown();retirement.join(1000);assert done.get();
            assert ack.get()==(mode!=2);assert s.host.pauses==(mode==0?1:0);
            exit.countDown();s.renderThread.join(1000);assert !s.renderThread.isAlive();
        }
    }
''')


if __name__ == '__main__':
    unittest.main()
