"""Compile actual provider attachment/default methods; no device or clock proof."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_lsfg_endpoint_lifetime import method

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "unified-android/src"
GAME = SRC / "com/thorium/preview/game"
VIDEO = SRC / "com/thorium/lucent/video"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


class NativeSourceImageProviderTest(unittest.TestCase):
    def test_actual_attachment_pins_host_reuses_provider_and_leaves_off_unallocated(self):
        source = (GAME / "NativeAdapterEngineSession.java").read_text()
        methods = "\n".join(method(source, signature) for signature in (
            "private static final class PinnedSourceImageProvider",
            "private void attachNativeSourceImageProvider(NativeAdapterHost active, Surface input)",
            "private void publishProducerTiming(NativeAdapterHost active)",
            "private void configureNativePresentation(NativeAdapterHost active, Surface primary)",
            "private void rebindNativeSurface(NativeAdapterHost active, Surface primary, Surface lower)",
            "@Override public void attachSurface(Surface value, int width, int height)",
        ))
        fixture = r'''
package com.thorium.preview.game;
import android.view.Surface;
import java.nio.ByteBuffer;
import java.util.IdentityHashMap;
import com.thorium.lucent.video.NativeSourceImageProvider;
public class ProviderTest {
    static final String TAG="test";
    NativeAdapterHost host; Surface surface,secondarySurface;
    PinnedSourceImageProvider nativeSourceImageProvider;
    boolean prepared=true,started=true;
    double producerTimelineHz; int reportedTimingCapabilities=-1;
    final Entry entry=new Entry();
    static class Entry {String id="eden";}
    static class Log {static void i(String tag,String message){}}
    static void check(boolean value){if(!value)throw new AssertionError();}
    void publishLowerSourceCadence(){}
    void voidDimensions(int width,int height){}
    void runOnRenderThread(Runnable work){work.run();}
    static class NativeAdapterHost {
        final int identity; int queries,bindings,rebinds,lastEpoch,lastSurface;
        long lastPts; ByteBuffer lastBuffer; boolean closed,busy;
        NativeAdapterHost(int value){identity=value;}
        boolean setFgPresentation(boolean value){return true;}
        int timingCapabilities(){return 3;}
        double producerTimelineHz(){return 0.0;}
        int sourceImageBinding(ByteBuffer output){
            ++bindings;lastBuffer=output;return closed?-1:busy?-2:identity;
        }
        int querySourceImage(long epoch,long surface,long pts,ByteBuffer output){
            ++queries;lastEpoch=(int)epoch;lastSurface=(int)surface;
            lastPts=pts;lastBuffer=output;return closed?-1:busy?-2:identity;
        }
        void surfaceRecreated(Surface primary,Surface secondary){++rebinds;}
    }
    static class Renderer implements FrameGenerationRenderer {
        final Surface input; NativeSourceImageProvider provider;int attachments;
        Renderer(Surface value){input=value;}
        public Surface inputSurface(){return input;}
        public void setNativeSourceImageProvider(NativeSourceImageProvider value){
            provider=value;++attachments;
        }
        public void setStatsListener(StatsListener value){}
        public void setAuthoritativeSourceHz(double value){throw new AssertionError("new authority");}
        public void setProducerTimelineHz(double value){check(value==0.0);}
        public void setSlotLatticeProducer(boolean value){check(!value);}
        public void setFirstSubmittedFrameListener(Runnable value){}
        public boolean submitSoftwareFrame(int[] c,int w,int h,int l,int t,int r,int b,float a){return false;}
        public void resize(int a,int b,int c,int d,float e){}
        public void close(){}
    }
    static class NoObserverRenderer implements FrameGenerationRenderer {
        public Surface inputSurface(){return null;}
        public void setStatsListener(StatsListener value){}
        public void setAuthoritativeSourceHz(double value){}
        public void setProducerTimelineHz(double value){}
        public void setFirstSubmittedFrameListener(Runnable value){}
        public boolean submitSoftwareFrame(int[] c,int w,int h,int l,int t,int r,int b,float a){return false;}
        public void resize(int a,int b,int c,int d,float e){}
        public void close(){}
    }
    public static void main(String[] args){
        ProviderTest session=new ProviderTest();
        NativeAdapterHost first=new NativeAdapterHost(11),second=new NativeAdapterHost(22);
        Surface input=new Surface(),otherInput=new Surface();
        session.host=first;session.surface=input;
        // Off has no registered renderer and performs no observer allocation/query.
        session.publishProducerTiming(first);
        check(session.nativeSourceImageProvider==null && first.queries==0 && first.bindings==0);
        Renderer unrelated=new Renderer(otherInput);FrameGenerationRendererRegistry.register(unrelated);
        session.publishProducerTiming(first);check(unrelated.attachments==0);
        Renderer renderer=new Renderer(input);FrameGenerationRendererRegistry.register(renderer);
        session.publishProducerTiming(first);
        NativeSourceImageProvider original=renderer.provider;
        check(original!=null && renderer.attachments==1 && first.bindings==0 && first.queries==0);
        session.publishProducerTiming(first);check(renderer.provider==original && renderer.attachments==2);
        ByteBuffer output=ByteBuffer.allocateDirect(808);
        check(original.sourceImageBinding(output)==11 && first.lastBuffer==output);
        check(original.querySourceImage(7,8,123456789L,output)==11);
        check(first.lastEpoch==7 && first.lastSurface==8 && first.lastPts==123456789L);
        // Detachment and mutable host replacement cannot redirect an old provider.
        session.surface=null;session.host=second;
        session.attachNativeSourceImageProvider(first,input);check(renderer.attachments==2);
        check(original.querySourceImage(7,8,123456790L,output)==11 && second.queries==0);
        first.busy=true;check(original.sourceImageBinding(output)==-2);
        first.closed=true;check(original.querySourceImage(7,8,123456791L,output)==-1);
        session.surface=input;session.publishProducerTiming(second);
        NativeSourceImageProvider replacement=renderer.provider;
        check(replacement!=original && replacement.sourceImageBinding(output)==22);
        session.publishProducerTiming(second);check(renderer.provider==replacement);
        session.attachNativeSourceImageProvider(first,input);check(renderer.provider==replacement);
        session.attachNativeSourceImageProvider(second,otherInput);check(unrelated.attachments==0);
        session.attachNativeSourceImageProvider(null,input);check(renderer.provider==replacement);
        // A new renderer Surface on the same host receives the cached exact binding.
        session.attachSurface(otherInput,1920,1080);
        check(second.rebinds==1 && unrelated.provider==replacement);
        check(original.querySourceImage(7,8,123456792L,output)==-1 && second.queries==0);
        // The default API is genuinely inert, including a null clear.
        NativeSourceImageProvider exploding=new NativeSourceImageProvider(){
            public int sourceImageBinding(ByteBuffer b){throw new AssertionError();}
            public int querySourceImage(long a,long b,long c,ByteBuffer d){throw new AssertionError();}
        };
        NoObserverRenderer noop=new NoObserverRenderer();
        noop.setNativeSourceImageProvider(exploding);noop.setNativeSourceImageProvider(null);
        System.out.println("exact-host observer attachment only; no timing authority");
    }
''' + methods + "\n}\n"
        with tempfile.TemporaryDirectory(prefix="native-source-provider-") as temporary:
            directory = Path(temporary)
            stub = directory / "android/view/Surface.java"
            stub.parent.mkdir(parents=True)
            stub.write_text("package android.view; public class Surface { public boolean isValid(){return true;} }\n")
            fixture_path = directory / "ProviderTest.java"
            fixture_path.write_text(fixture)
            sources = [stub, fixture_path, VIDEO / "NativeSourceImageProvider.java",
                       VIDEO / "RuntimePresentationFailure.java", GAME / "FrameGenerationRenderer.java",
                       GAME / "FrameGenerationRendererRegistry.java"]
            result = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", str(directory),
                                     *map(str, sources)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(JAVA / "java"), "-cp", str(directory),
                                     "com.thorium.preview.game.ProviderTest"],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("no timing authority", result.stdout)

    def test_pinned_methods_never_read_mutable_session_host_or_query_on_attachment(self):
        source = (GAME / "NativeAdapterEngineSession.java").read_text()
        pinned = method(source, "private static final class PinnedSourceImageProvider")
        self.assertIn("final NativeAdapterHost boundHost", pinned)
        self.assertNotIn("active = host", pinned)
        attach = method(source, "private void attachNativeSourceImageProvider(NativeAdapterHost active, Surface input)")
        self.assertLess(attach.index("if (generator == null) return;"),
                        attach.index("new PinnedSourceImageProvider(active)"))
        self.assertNotIn(".querySourceImage(", attach)
        self.assertNotIn(".sourceImageBinding(", attach)
        self.assertNotIn("setProducerTimelineHz", attach)
        self.assertNotIn("setAuthoritativeSourceHz", attach)
        off = method((GAME / "GameSurfaceView.java").read_text(),
                     "private void createGenerator(Surface output, int width, int height)")
        off_branch = off[off.index("if (launchMode == FrameGenerationSettings.Mode.OFF)"):
                         off.index("FrameGenerationSettings.QualificationTransport")]
        self.assertIn("engineSurface = output;", off_branch)
        self.assertNotIn("NativeSourceImageProvider", off_branch)
        self.assertNotIn("FrameGenerationRendererFactory.create(", off_branch)


if __name__ == "__main__":
    unittest.main()
