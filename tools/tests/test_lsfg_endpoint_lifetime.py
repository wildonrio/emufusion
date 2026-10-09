"""Compile production LSFG Java method bodies against instrumented Android leaves.

These are bounded ownership/math regressions, not device cadence evidence.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = ROOT / "unified-android/qualification-src/com/thorium/preview/game/LsfgPresentationTransport.java"
JAVA_HOME = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")
GAME = ROOT / "unified-android/src/com/thorium/preview/game"


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end].replace("@Override ", "")


class LsfgEndpointLifetimeTest(unittest.TestCase):
    def compile_run(self, body, scenarios=((),)):
        javac = str(JAVA_HOME / "javac") if (JAVA_HOME / "javac").exists() else shutil.which("javac")
        java = str(JAVA_HOME / "java") if (JAVA_HOME / "java").exists() else shutil.which("java")
        self.assertIsNotNone(javac)
        self.assertIsNotNone(java)
        with tempfile.TemporaryDirectory(prefix="lsfg-endpoint-regression-") as temporary:
            directory = Path(temporary)
            source = directory / "EndpointTest.java"
            source.write_text(body)
            result = subprocess.run([javac, "--release", "8", "-d", str(directory),
                                     str(GAME / "SurfaceOwnershipException.java"),
                                     str(ROOT / "unified-android/src/com/thorium/lucent/video/NativeSourceImage.java"),
                                     str(ROOT / "unified-android/src/com/thorium/lucent/video/NativeSourceImageLedger.java"),
                                     str(source)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for scenario in scenarios:
                with self.subTest(scenario=scenario):
                    result = subprocess.run([java, "-cp", str(directory), "EndpointTest", *scenario],
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_acquire_boundary_retirement_discard_identity_and_fatal_latch(self):
        production = TRANSPORT.read_text()
        acquisition = method(production, "@Override public void onImageAvailable(ImageReader source)")
        source = r'''
import java.util.*;
public class EndpointTest {
    static final int MAX_IMAGES=8; final int width=2,height=2;
    boolean closed; RuntimeException fatalFailure; int prepared;
    long lastExpectedSequence,lastExpectedTimestampNs,endpointDiscontinuities,endpointDiscontinuitiesTotal;
    final ArrayDeque<ExpectedEndpoint> expected=new ArrayDeque<>();
    final LinkedHashMap<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
    void requireOwner() {}
    static class android { static class util { static class Log {
        static void w(String tag,String message) {}
    } } }
    void scheduleEndpointPreparation() { ++prepared; }
    static void check(boolean b) { if(!b) throw new AssertionError(); }
    static class HardwareBuffer {
        static final int RGBA_8888=1; static final long USAGE_GPU_SAMPLED_IMAGE=1L;
        boolean closed; int closes;
        boolean isClosed(){return closed;} int getWidth(){return 2;}
        int getHeight(){return 2;} int getLayers(){return 1;}
        int getFormat(){return 1;} long getUsage(){return 1;}
        void close(){closed=true; ++closes;}
    }
    static class Image {
        long timestamp; final ImageReader reader;
        final HardwareBuffer buffer=new HardwareBuffer(); boolean closed;
        Image(long t,ImageReader r){timestamp=t;reader=r;}
        long getTimestamp(){return timestamp;} HardwareBuffer getHardwareBuffer(){return buffer;}
        void close(){check(!closed);closed=true;--reader.acquired;}
    }
    static class ImageReader {
        final ArrayDeque<Image> pending=new ArrayDeque<>(); int acquired,calls;
        Image acquireNextImage(){
            ++calls;
            if(acquired>=8) throw new IllegalStateException("maxImages (8)");
            Image image=pending.pollFirst();if(image!=null) ++acquired;return image;
        }
    }
    Image queue(ImageReader reader,long sequence,long timestamp,boolean discard){
        Image image=new Image(timestamp,reader);reader.pending.add(image);
        ExpectedEndpoint identity=new ExpectedEndpoint(sequence,timestamp);identity.discard=discard;
        expected.add(identity);return image;
    }
    public static void main(String[] args){
        EndpointTest test=new EndpointTest(); ImageReader reader=new ImageReader();
        for(long i=1;i<=8;++i)test.queue(reader,i,100+i,false);
        test.onImageAvailable(reader);
        check(test.fatalFailure==null && test.retained.size()==8 && reader.acquired==8);
        check(reader.calls==8 && test.expected.isEmpty());
        // Spurious callback at capacity must not even call Android's acquire.
        test.onImageAvailable(reader);check(reader.calls==8);
        // Returning exactly one retired image permits exactly one new acquire.
        test.retained.remove(1L).close();test.queue(reader,9,109,false);
        test.onImageAvailable(reader);
        check(test.fatalFailure==null && reader.calls==9 && reader.acquired==8);
        check(test.retained.get(9L).timestampNs==109 && test.prepared==9);
        // Discarded and malformed images release both wrappers and the Image.
        EndpointTest discard=new EndpointTest();ImageReader other=new ImageReader();
        Image discarded=discard.queue(other,1,101,true);discard.onImageAvailable(other);
        check(discarded.closed && discarded.buffer.closes==1 && other.acquired==0);
        Image malformed=discard.queue(other,2,102,false);
        malformed.timestamp=999;discard.onImageAvailable(other);
        check(discard.fatalFailure!=null && malformed.closed && malformed.buffer.closes==1);
        int calls=other.calls;discard.queue(other,3,103,false);discard.onImageAvailable(other);
        check(other.calls==calls && other.pending.size()==1);
    }
''' + acquisition + method(production, "private static final class ExpectedEndpoint") + \
            method(production, "private static final class RetainedEndpoint") + "\n}\n"
        self.compile_run(source)

    def test_odd_nanosecond_midpoint_and_extreme_timestamps(self):
        production = TRANSPORT.read_text()
        helper = method(production, "private static boolean isExactMidpoint(long left, long right, long middle)")
        self.compile_run("public class EndpointTest {\n" + helper + r'''
    static void check(boolean b){if(!b)throw new AssertionError();}
    public static void main(String[] args){
        check(isExactMidpoint(100,105,102));check(!isExactMidpoint(100,105,103));
        check(isExactMidpoint(100,106,103));check(!isExactMidpoint(100,101,100));
        check(!isExactMidpoint(0,4,2));check(!isExactMidpoint(4,2,3));
        check(isExactMidpoint(Long.MAX_VALUE-5,Long.MAX_VALUE,Long.MAX_VALUE-3));
        check(isExactMidpoint(1,Long.MAX_VALUE,1+(Long.MAX_VALUE-1)/2));
        for(long span=2;span<100000;span++){
            check(isExactMidpoint(100,100+span,100+span/2));
            if((span&1)==1)check(!isExactMidpoint(100,100+span,101+span/2));
        }
    }
}
''')
        for signature in ("private static boolean isExactMidpoint(FrameGenerationPresentationRequest request)",
                          "private static boolean isExactMidpoint(FrameGenerationPreparationRequest request)"):
            wrapper = method(production, signature)
            self.assertIn("request.rightTimestampNs(), request.presentationTimestampNs()", wrapper)
            self.assertNotIn("leftDelta == rightDelta", wrapper)

    def test_native_retirement_precedes_returning_image_buffers(self):
        close = method(TRANSPORT.read_text(), "@Override public void close()")
        self.assertLess(close.index("awaitTermination"), close.index("NativeLsfgBridge.close"))
        self.assertLess(close.index("NativeLsfgBridge.close"), close.index("endpoint.close()"))
        self.assertLess(close.index("NativeLsfgBridge.close"), close.index("reader.close()"))

    def test_actual_close_success_timeout_interrupt_and_native_failure(self):
        production = TRANSPORT.read_text()
        helpers = "\n".join(method(production, signature) for signature in (
            "private static void requireLifecycleAdmissionAvailable()",
            "private void reserveLifecycleOwner()", "private void releaseLifecycleOwner()",
            "private SurfaceOwnershipException quarantineCloseFailure(Throwable failure)",
            "@Override public void close()"))
        # Only platform leaves and the outer class name are substituted. Each
        # failure scenario runs in a fresh JVM: a quarantined process cannot be
        # reset or reused by this fixture, just as production cannot reset it.
        fixture = r'''
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import com.thorium.preview.game.SurfaceOwnershipException;
public class EndpointTest {
    private static final Object LIFECYCLE_LOCK = new Object();
    private static EndpointTest lifecycleOwner;
    private static SurfaceOwnershipException processCloseFailure;
    static final List<String> events = new ArrayList<>();
    static String mode;
    final long nativeHandle=14;
    final Reader reader=new Reader(); final Worker preparationWorker=new Worker();
    final LinkedHashMap<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
    final ArrayDeque<ExpectedEndpoint> expected=new ArrayDeque<>();
    final Map<Long,Object> pairReadiness=new HashMap<>(),submitted=new HashMap<>();
    Object preparedGenerated=new Object(),preparedRealPair=new Object(),announcedRealPair=new Object();
    boolean closed,retirementComplete; SurfaceOwnershipException closeFailure;
    void requireOwner() {}
    static void check(boolean condition) { if(!condition)throw new AssertionError(events.toString()); }
    static void event(String value) { check(!Thread.holdsLock(LIFECYCLE_LOCK));events.add(value); }
    static class Reader {
        void setOnImageAvailableListener(Object listener,Object owner) { event("detach"); }
        void close() { event("reader");if(mode.equals("reader"))throw new IllegalStateException("reader"); }
    }
    static class Worker {
        void shutdown() { event("shutdown"); }
        boolean awaitTermination(long timeout,TimeUnit unit)throws InterruptedException {
            event("wait");check(timeout==5L && unit==TimeUnit.SECONDS);
            if(mode.equals("interrupt"))throw new InterruptedException("worker");
            return !mode.equals("timeout");
        }
    }
    static class RetainedEndpoint {
        final String name;RetainedEndpoint(String n){name=n;}
        void close(){event(name);if(mode.equals("endpoint"))throw new IllegalStateException("endpoint");}
    }
    static class ExpectedEndpoint {void releaseProvenance(){}}
    static class NativeLsfgBridge {
        static void close(long handle) { check(handle==14);event("native");
            if(mode.equals("native"))throw new IllegalStateException("native"); }
    }
    EndpointTest() {
        reserveLifecycleOwner();event("native-open");
        retained.put(1L,new RetainedEndpoint("image1"));retained.put(2L,new RetainedEndpoint("image2"));
        expected.add(new ExpectedEndpoint());pairReadiness.put(1L,new Object());submitted.put(1L,new Object());
    }
    static void concurrentAdmission()throws Exception {
        // Hold a starting owner behind a fake native-open boundary while
        // another thread attempts admission. The lifecycle monitor must not
        // be held over that boundary, nor may a second open be reached.
        CountDownLatch reserved=new CountDownLatch(1), release=new CountDownLatch(1);
        AtomicReference<EndpointTest> admitted=new AtomicReference<>();
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread first=new Thread(()->{
            try { EndpointTest one=new EndpointTest();admitted.set(one);reserved.countDown();release.await(); }
            catch(Throwable error){failure.set(error);}
        });first.start();check(reserved.await(1,TimeUnit.SECONDS));
        Thread second=new Thread(()->{
            try { new EndpointTest();failure.set(new AssertionError("second native open")); }
            catch(UnsupportedOperationException expected) {}
            catch(Throwable error){failure.set(error);}
        });second.start();second.join(1000);check(!second.isAlive() && failure.get()==null);
        check(Collections.frequency(events,"native-open")==1 && lifecycleOwner==admitted.get());
        release.countDown();first.join(1000);check(!first.isAlive());
        mode="success";admitted.get().close();check(lifecycleOwner==null);
    }
    public static void main(String[] args)throws Exception {
        mode=args[0];if(mode.equals("concurrent")){concurrentAdmission();return;}
        EndpointTest test=new EndpointTest();events.clear();
        if(mode.equals("success")) {
            test.close();
            check(events.equals(Arrays.asList("detach","shutdown","wait","native","image1","image2","reader")));
            check(test.closed && test.retirementComplete && lifecycleOwner==null && processCloseFailure==null);
            check(test.retained.isEmpty() && test.expected.isEmpty() && test.pairReadiness.isEmpty() &&
                    test.submitted.isEmpty() && test.preparedGenerated==null &&
                    test.preparedRealPair==null && test.announcedRealPair==null);
            test.close();check(events.size()==7); // No retry of native/image retirement.
            EndpointTest replacement=new EndpointTest();check(lifecycleOwner==replacement);replacement.close();
            return;
        }
        SurfaceOwnershipException first;
        try{test.close();throw new AssertionError("unsafe success");}
        catch(SurfaceOwnershipException unsafe){first=unsafe;}
        check(test.closed && !test.retirementComplete && test.closeFailure==first && processCloseFailure==first);
        check(lifecycleOwner==test); // Strong reference to exactly ONE failed host and its resources.
        if(mode.equals("timeout") || mode.equals("interrupt")) {
            check(events.equals(Arrays.asList("detach","shutdown","wait")));
            check(test.retained.size()==2 && test.expected.size()==1 && test.preparedGenerated!=null);
            check(test.preparedRealPair!=null && test.announcedRealPair!=null);
            if(mode.equals("interrupt"))check(Thread.interrupted());
        }else if(mode.equals("native")) {
            check(events.equals(Arrays.asList("detach","shutdown","wait","native")));
            check(test.retained.size()==2 && test.expected.size()==1 && test.preparedGenerated!=null);
            check(test.preparedRealPair!=null && test.announcedRealPair!=null);
        }else if(mode.equals("endpoint")) {
            check(events.equals(Arrays.asList("detach","shutdown","wait","native","image1")));
            check(test.retained.size()==2 && test.expected.size()==1 && test.preparedGenerated!=null);
            check(test.preparedRealPair!=null && test.announcedRealPair!=null);
        }else check(mode.equals("reader") && events.get(events.size()-1).equals("reader"));
        int before=events.size();
        try{test.close();throw new AssertionError("repeat close hid failure");}
        catch(SurfaceOwnershipException repeated){check(repeated==first);}
        try{requireLifecycleAdmissionAvailable();throw new AssertionError("unsafe process readmitted");}
        catch(SurfaceOwnershipException rejected){check(rejected==first);}
        try{new EndpointTest();throw new AssertionError("second native open after poison");}
        catch(SurfaceOwnershipException rejected){check(rejected==first);}
        check(events.size()==before && lifecycleOwner==test);
    }
''' + helpers + "\n}\n"
        self.compile_run(fixture, tuple((mode,) for mode in
                         ("success", "timeout", "interrupt", "native", "endpoint", "reader", "concurrent")))


if __name__ == "__main__":
    unittest.main()
