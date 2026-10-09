"""Actual Java host guards/leases plus real observer, with an instrumented JNI leaf.

This catches ABI-capacity disagreement across the Java modules. It does not load
an Android native library or qualify the real Vulkan image/timestamp join.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.tests.test_lsfg_endpoint_lifetime import method

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "unified-android/src"
VIDEO = SRC / "com/thorium/lucent/video"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


class NativeSourceImageHostBoundaryTest(unittest.TestCase):
    def test_actual_host_capacity_validation_lease_and_observer_integration(self):
        host = (SRC / "com/thorium/preview/NativeAdapterHost.java").read_text()
        constants = "\n".join(re.findall(r"    public static final int SOURCE_[^\n]+", host))
        methods = "\n".join(method(host, signature) for signature in (
            "public int sourceImageBinding(ByteBuffer output)",
            "public int querySourceImage(long sessionEpoch, long surfaceEpoch,",
        ))
        fixture = r'''
import java.nio.*;
import java.util.concurrent.*;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import com.thorium.lucent.video.*;
public class HostBoundaryTest implements NativeSourceImageProvider {
    private long handle=19;
    private final ReentrantReadWriteLock sourceQueryLease=new ReentrantReadWriteLock();
    private volatile boolean sourceQueriesEnabled=true;
    static int bindings,queries; static ByteBuffer seenBuffer;
    static long seenHandle,seenSession,seenSurface,seenPts;
    static boolean throwQuery;
    static void check(boolean value){if(!value)throw new AssertionError();}
    static int nativeSourceImageBinding(long handle,ByteBuffer out){
        ++bindings;seenBuffer=out;seenHandle=handle;
        out.order(ByteOrder.LITTLE_ENDIAN);
        out.putInt(0,1);out.putInt(4,64);out.putLong(8,11);out.putLong(16,22);out.putLong(24,33);
        return 1;
    }
    static int nativeQuerySourceImage(long handle,long session,long surface,long pts,ByteBuffer out){
        ++queries;seenBuffer=out;seenHandle=handle;seenSession=session;seenSurface=surface;seenPts=pts;
        if(throwQuery)throw new IllegalStateException("synthetic JNI failure");
        if(session<=0||surface<=0||pts<=0)return 9; // actual JNI key validation remains separate
        out.order(ByteOrder.LITTLE_ENDIAN);
        out.putInt(0,1);out.putInt(4,808);out.putInt(8,1);out.putInt(12,0);
        out.putLong(16,1);out.putLong(24,pts);out.putLong(40,session);out.putLong(48,surface);
        out.putLong(56,33);out.putLong(72,1);out.putLong(80,pts-1);
        out.putInt(88,1);out.putInt(92,1);out.putInt(96,1);
        out.putLong(104,44);out.putLong(112,1);out.putLong(120,-700);
        out.putInt(128,7);out.putInt(132,1);out.putInt(136,2);out.putInt(140,2);
        out.putInt(144,1);out.putInt(148,1280);out.putInt(152,720);out.putInt(156,1280);
        out.putInt(160,1);out.putInt(184,1280);out.putInt(188,720);
        return 1;
    }
    void rejected(ByteBuffer buffer){
        int before=queries;check(querySourceImage(11,22,1000,buffer)==9);check(queries==before);
    }
    public static void main(String[] args)throws Exception{
        HostBoundaryTest host=new HostBoundaryTest();
        check(SOURCE_IMAGE_BUFFER_BYTES==808 && SOURCE_BINDING_BUFFER_BYTES==64);
        ByteBuffer exact=ByteBuffer.allocateDirect(NativeSourceImage.IMAGE_BYTES);
        check(host.querySourceImage(11,22,1234567,exact)==1 && queries==1);
        check(seenBuffer==exact && seenHandle==19 && seenSession==11 && seenSurface==22 && seenPts==1234567);
        host.rejected(ByteBuffer.allocateDirect(807));host.rejected(ByteBuffer.allocate(808));
        host.rejected(exact.asReadOnlyBuffer());host.rejected(null);
        ByteBuffer larger=ByteBuffer.allocateDirect(4096);
        check(host.querySourceImage(11,22,1234568,larger)==1);
        ByteBuffer sliceSource=ByteBuffer.allocateDirect(816);sliceSource.position(8);
        ByteBuffer slice=sliceSource.slice();check(slice.capacity()==808);
        check(host.querySourceImage(11,22,1234569,slice)==1 && seenBuffer==slice);
        int before=bindings;
        check(host.sourceImageBinding(ByteBuffer.allocateDirect(63))==9 && bindings==before);
        check(host.sourceImageBinding(ByteBuffer.allocate(64))==9 && bindings==before);
        check(host.sourceImageBinding(ByteBuffer.allocateDirect(64).asReadOnlyBuffer())==9 && bindings==before);
        check(host.sourceImageBinding(null)==9 && bindings==before);
        check(host.sourceImageBinding(ByteBuffer.allocateDirect(64))==1 && bindings==before+1);
        // Closed/disabled hosts cannot cross JNI even with correctly sized buffers.
        before=queries;host.sourceQueriesEnabled=false;
        check(host.querySourceImage(11,22,1234570,exact)==8 && queries==before);
        host.sourceQueriesEnabled=true;host.handle=0;
        check(host.querySourceImage(11,22,1234570,exact)==8 && queries==before);host.handle=19;
        // A live writer makes the actual try-read lease return BUSY, never wait.
        CountDownLatch locked=new CountDownLatch(1),release=new CountDownLatch(1);
        Thread writer=new Thread(()->{
            host.sourceQueryLease.writeLock().lock();locked.countDown();
            try{check(release.await(5,TimeUnit.SECONDS));}catch(InterruptedException e){throw new AssertionError(e);}
            finally{host.sourceQueryLease.writeLock().unlock();}
        });
        writer.start();check(locked.await(5,TimeUnit.SECONDS));
        try{
            check(host.querySourceImage(11,22,1234570,exact)==3 && queries==before);
            check(host.sourceImageBinding(ByteBuffer.allocateDirect(64))==3);
        }finally{release.countDown();writer.join(5000);}
        check(!writer.isAlive());
        throwQuery=true;
        try{host.querySourceImage(11,22,1234570,exact);throw new AssertionError("JNI exception swallowed");}
        catch(IllegalStateException expected){}finally{throwQuery=false;}
        check(host.sourceQueryLease.writeLock().tryLock());host.sourceQueryLease.writeLock().unlock();
        // Crucial integration: the REAL observer's808-byte buffer passes the
        // ACTUAL host guard/lease before reaching this fake native payload.
        NativeSourceImageObserver observer=new NativeSourceImageObserver(1);
        observer.setProvider(host);int beforeQuery=queries,beforeBinding=bindings;
        observer.observeLatest(8000000);observer.retainCandidate(0);observer.classifyCandidate(0);
        observer.finishClassified(true,8000000,true,true);
        String diagnostic=observer.diagnostic();
        check(queries==beforeQuery+1 && bindings==beforeBinding+1);
        check(seenBuffer.capacity()==808 && diagnostic.contains("classifiedAccepted=1"));
        check(diagnostic.contains("queryACCEPTED=1") && !diagnostic.contains("queryBAD_ARGUMENT="));
        observer.releaseCandidate(0);observer.close();
        System.out.println("808-byte actual host boundary passes;807 rejected before JNI;observer accepted metadata only");
    }
''' + constants + "\n" + methods + "\n}\n"
        with tempfile.TemporaryDirectory(prefix="native-source-host-boundary-") as temporary:
            directory = Path(temporary)
            fixture_path = directory / "HostBoundaryTest.java"
            fixture_path.write_text(fixture)
            sources = [fixture_path, *(VIDEO / name for name in (
                "NativeSourceImage.java", "NativeSourceImageProvider.java",
                "NativeSourceImageLedger.java", "NativeSourceImageObserver.java"))]
            result = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", str(directory),
                                     *map(str, sources)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(JAVA / "java"), "-cp", str(directory), "HostBoundaryTest"],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("807 rejected before JNI", result.stdout)


if __name__ == "__main__":
    unittest.main()
