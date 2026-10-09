"""Renderer metadata/image association, executing actual ingestion/classifier methods.

GL, timers and the diagnostic observer are recording leaves. Provider decode,
ledger validity and allocation checks belong to the real observer's own tests.
Nothing here establishes source-clock or generated-frame authority.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r"""//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])'""",
                    lambda match: " " * len(match.group()), source, flags=re.S)
    depth = 0
    for index in range(opening, len(source)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1].replace("@Override ", "")
    raise AssertionError("unclosed production method: " + signature)


class RendererSourceImageWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        observer_match = re.search(r"(?:final\s+)?NativeSourceImageObserver\s+(\w+)\s*[=;]", source)
        if observer_match is None:
            raise AssertionError("renderer observer wiring has not landed")
        observer_name = observer_match.group(1)
        methods = "\n".join(method(source, signature) for signature in (
            "public void onFrameAvailable(SurfaceTexture ignored)",
            "private void consumeAvailableFrame(SurfaceTexture ignored)",
            "private boolean latestImageIsUnique(long currentTimestampNs)",
            "private int findSignatureCandidate(long sequence)",
            "private void retainSignatureCandidate(long sequence, long timestampNs,",
            "private void clearSignatureCandidates()",
            "private boolean sourceSignatureIsUnique()",
            "private boolean softwareImageIsUnique(int[] colors, int width, int height)",
            "private void uploadSoftwareFrame(int[] colors, int width, int height, float aspect,",
            "public void setNativeSourceImageProvider(",
            "private void clearNativeClassifiedObservation()",
            "private void classifyLatestNativeObservation()",
            "private void finishNativeClassifiedObservation(boolean unique)",
            "private void releaseNativeEndpointProvenance(int slot)",
            "private void clearNativeEndpointTimeline(boolean fifo)",
            "private void closeNativeSourceImageObserver()",
            "private void allocateHistoryTextures(int width, int height)",
            "public void resize(int newInputWidth, int newInputHeight,"))
        cls.source = source
        # Only annotation removal and this field-name binding affect extraction;
        # every production decision and observer call remains unchanged.
        fixture = r'''
import java.nio.ByteBuffer;
import com.thorium.lucent.video.NativeSourceImageLedger;
import com.thorium.lucent.video.NativeSourceImage;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
public class WiringFixture {
    static class TransportFactory {boolean nativeSoftwareGeometry(){return false;}}
    static class Transport {int endpointWidth(){return 0;} int endpointHeight(){return 0;}}
    TransportFactory externalTransportFactory;
    Transport externalTransport;
    void reopenUnusedSoftwareTransport(int width,int height){throw new AssertionError("unexpected transport reopen");}
    static final List<String> trace=new ArrayList<>();
    static class Log {static void i(String t,String m){}static void w(String t,String m){}static void e(String t,String m){}}
    static class System {
        static long now=999999;
        static long nanoTime(){return now;}
        static void arraycopy(Object a,int ai,Object b,int bi,int n){java.lang.System.arraycopy(a,ai,b,bi,n);}
    }
    static class GLES20 {
        static final int GL_FRAMEBUFFER=1,GL_COLOR_ATTACHMENT0=2,GL_TEXTURE_2D=3,
            GL_FRAMEBUFFER_COMPLETE=4,GL_NO_ERROR=0,GL_RGBA=5,GL_UNSIGNED_BYTE=6;
        static final ArrayDeque<Integer> errors=new ArrayDeque<>();
        static int signatureByte=17;
        static void glBindFramebuffer(int a,int b){}
        static void glFramebufferTexture2D(int a,int b,int c,int d,int e){}
        static int glCheckFramebufferStatus(int a){return GL_FRAMEBUFFER_COMPLETE;}
        static void glViewport(int a,int b,int c,int d){}
        static void glBindTexture(int target,int texture){}
        static void glTexImage2D(int a,int b,int c,int d,int e,int f,int g,int h,Object i){}
        static int glGetError(){return errors.isEmpty()?0:errors.removeFirst();}
        static void glFinish(){}
        static void glReadPixels(int a,int b,int c,int d,int e,int f,ByteBuffer out){
            for(int i=0;i<out.capacity();i++)out.put(i,(byte)signatureByte);
        }
    }
    static class SurfaceTexture {
        long timestamp;int updates;
        void updateTexImage(){updates++;trace.add("update");}
        long getTimestamp(){trace.add("timestamp");return timestamp;}
        void getTransformMatrix(float[] matrix){trace.add("transform");}
        void setDefaultBufferSize(int w,int h){}
    }
    static class Handler {
        ArrayDeque<Runnable> queue=new ArrayDeque<>();
        boolean post(Runnable r){queue.addLast(r);return true;}
        void drain(){while(!queue.isEmpty())queue.removeFirst().run();}
    }
    static class NativeSourceImageProvider {boolean valid=true;}
    static class NativeSourceImageObserver {
        static int allocations;
        long latest,classified;final long[] candidates=new long[6];
        NativeSourceImageProvider provider;boolean closed;
        int finishCalls,clearCalls,closeCalls,providerCalls;
        long lastObserved=-1,finishedMetadata,finishedPts;
        boolean finishedReady,finishedUnique,finishedKnown;
        NativeSourceImageObserver(int count){assert count==6;allocations++;}
        void setProvider(NativeSourceImageProvider p){if(provider==p)return;providerCalls++;provider=p;reset();}
        void observeLatest(long raw){
            trace.add("observe:"+raw);lastObserved=raw;
            latest=!closed && provider!=null && provider.valid && raw>0?raw:0;
        }
        void classifyLatest(){trace.add("classifyLatest");classified=latest;}
        void retainCandidate(int slot){trace.add("retain:"+slot);candidates[slot]=latest;}
        void classifyCandidate(int slot){trace.add("classifyCandidate:"+slot);classified=candidates[slot];}
        void releaseCandidate(int slot){trace.add("release:"+slot);candidates[slot]=0;}
        void clearCandidates(){clearCalls++;Arrays.fill(candidates,0);}
        void clearClassified(){classified=0;}
        void reset(){latest=0;classified=0;clearCandidates();}
        void resetImages(){reset();}
        void close(){closeCalls++;closed=true;reset();provider=null;}
        String diagnostic(){return "fixture-only";}
        NativeSourceImageLedger.Result copyClassifiedTo(NativeSourceImageLedger destination,
                int slot,long pts,boolean unique,boolean known){
            return destination.observeMissing(slot,1,classified,0,0,0,NativeSourceImage.Decode.NOT_FOUND);
        }
        void finishClassified(boolean ready,long pts,boolean unique,boolean known){
            trace.add("finish");finishCalls++;finishedReady=ready;finishedPts=pts;
            finishedMetadata=classified;finishedUnique=unique;finishedKnown=known;
        }
    }
    static class DenseGpuTimer {
        static final int SIGNATURE_RESULT_FIELDS=8,STATUS_OK=1;
        long[] row=new long[0];boolean supported=true;int discardCalls;
        int capability=DENSE_SIGNATURE_CAP_READY;
        boolean signatureSupported(){return supported;}
        long[] pollSignature(long sequence){long[] result=row;row=new long[0];return result;}
        void discardPending(){discardCalls++;}
        void close(){}
    }
    static class Rate {
        boolean authoritative;int resets;float refresh;
        boolean usesAuthoritativeSourceRate(){return authoritative;}
        void setDisplayRefreshHz(float f){refresh=f;}
        void resetPresentation(){resets++;}
    }
    static final int SIGNATURE_CANDIDATE_SLOTS=6,SIGNATURE_WIDTH=2,SIGNATURE_HEIGHT=1;
    static final int DENSE_SIGNATURE_CAP_READY=1,DENSE_WALL_SIGNATURE=1;
    static final int HIGH_RES_FLOW_THRESHOLD=720,HIGH_RES_COARSE_FLOW_DIVISOR=16,
        LOW_RES_COARSE_FLOW_DIVISOR=8,HIGH_RES_FINE_FLOW_DIVISOR=8,LOW_RES_FINE_FLOW_DIVISOR=4;
    static final int REGIONAL_CANDIDATE_WIDTH=2,REGIONAL_CANDIDATE_HEIGHT=2,
        REGIONAL_FLOW_WIDTH=2,REGIONAL_FLOW_HEIGHT=2,PROOF_WIDTH=2,PROOF_HEIGHT=2,REGIONAL_FLOW_CELLS=4;
    static final String TAG="fixture";
    final AtomicBoolean closed=new AtomicBoolean();
    final Handler handler=new Handler();
    final Rate frameRate=new Rate();
    double qualifiedPhysicalPanelHz;
    long qualifiedPhysicalPanelObservedNs;
    static class PhysicalClock {void reset(){}}
    final PhysicalClock builtInPhysicalClock=new PhysicalClock();
    NativeSourceImageObserver OBSERVER;
    static final int NATIVE_HISTORY_BASE=6,NATIVE_ADMISSION_SLOT=8;
    NativeSourceImageLedger nativeEndpointProvenance;
    long nativeProvenanceFailures;
    SurfaceTexture inputTexture=new SurfaceTexture();
    android.graphics.Bitmap softwareUploadBitmap;
    boolean externalPresentationFailed,classifiedFrameReady,classifiedPixelVerdictKnown;
    boolean signatureReadbackSafe=true,densePyramidEnabled,denseV28ReducedAnalysisRequested;
    boolean denseSignatureBaselineReady,sourceSignatureReady,outputFrameRateReassertedAfterSwap;
    boolean denseResourcesReady;
    DenseGpuTimer externalSignatureTimer,denseGpuTimer;
    float[] textureTransform=new float[16];
    int latestTexture=11,frameBuffer=12,signatureTexture=13,signatureQueryTexture=14;
    int signaturePreviousTexture=15,proofTexture=16;
    int historyWidth,historyHeight,coarseFlowWidth,coarseFlowHeight,fineFlowWidth,fineFlowHeight;
    final int[] historyTextures={30,31},endpointFifoTextures={32,33},flowTextures={34,35,36},
        reverseFlowTextures={37,38,39},globalCandidateTextures={40,41},
        globalCandidateWinnerTextures={42,43},globalFlowTextures={44,45};
    int inputWidth=320,inputHeight=240,outputWidth=1920,outputHeight=1080,displayId=0;
    float refreshHz=120,presentationAspect;
    String displayRole="primary";
    long generatorId=1,endpointTimestampCorrections,diagHardwareSubmits,denseSignatureUnavailable;
    long diagSoftwareSubmits;
    long denseSignatureSequence,denseSignatureMaxQueueAge,denseSignatureReady,endpointCandidateUnavailable;
    long diagUniqueVerdicts,diagDuplicateVerdicts;
    int diagLastSignatureByteSum,diagLastChangedPixels;
    int submittedFrameCount,classifiedUniqueTexture,classifiedUniqueSubmission;
    long classifiedUniqueTimestampNs;
    final int[] signatureCandidateTextures={20,21,22,23,24,25};
    final long[] signatureCandidateSequence=new long[6],signatureCandidateTimestampNs=new long[6];
    final int[] signatureCandidateSubmission=new int[6];
    ByteBuffer signaturePixels=ByteBuffer.allocate(8),proofPixels,regionalFlowPixels;
    final byte[] currentSourceSignature=new byte[8],lastSourceSignature=new byte[8];
    final Map<Integer,Long> textureImage=new HashMap<>();
    boolean failQuery;int failures,consumes,notifications;
    long consumedPts,consumedImage,consumedMetadata;boolean consumedUnique,consumedKnown;
    void copyExternalTo(int texture){trace.add("copyExternal");textureImage.put(texture,inputTexture.timestamp);}
    void uploadBitmap(int texture){trace.add("uploadBitmap");textureImage.put(texture,(long)softwareUploadBitmap.firstPixel);}
    void copyTexture(int from,int to){trace.add("copyCandidate:"+to);textureImage.put(to,textureImage.get(from));}
    void notifyFirstSubmittedFrame(){notifications++;}
    void consumeClassifiedFrame(boolean unique){
        if(OBSERVER!=null)assert trace.get(trace.size()-1).equals("finish");consumes++;
        if(classifiedFrameReady){consumedPts=classifiedUniqueTimestampNs;
            consumedImage=textureImage.get(classifiedUniqueTexture);consumedUnique=unique;
            consumedMetadata=OBSERVER==null?0:OBSERVER.finishedMetadata;
            consumedKnown=OBSERVER!=null && OBSERVER.finishedKnown;}
    }
    void failRuntimePresentation(String reason,RuntimeException failure){failures++;externalPresentationFailed=true;}
    static void fail(String m){throw new IllegalStateException(m);}
    void drawTexture2d(int texture){}
    int signatureCapability(DenseGpuTimer timer){return timer==null?0:timer.capability;}
    void copyCurrentSignatureToPrevious(){}
    void drawSignatureDifferenceQuery(DenseGpuTimer timer,long sequence){if(failQuery)throw new IllegalStateException("fixture query error");}
    void checkGl(String text){}
    void recordDenseWall(int kind,long duration){}
    void rejectDense(String reason,RuntimeException failure){densePyramidEnabled=false;denseGpuTimer=null;}
    void teardownDenseEpoch(String reason){clearSignatureCandidates();}
    static int positive(int n){return Math.max(1,n);}
    static float sanitizeRefresh(float hz){return hz;}
    void requestOutputFrameRate(String reason){}
    float flowLimitPixels(int w,int h){return 1;}
    void textureParameters(int target){}
    void allocateEndpointTexture(int texture,int w,int h){}
    void allocateTexture(int texture,int w,int h){}
    void resetEndpointFifo(){clearSignatureCandidates();}
    void setSignatureTextureSampling(int texture){}
    void clearMotionField(int texture,int w,int h){}
    void allocateDenseResources(){}
    void resetHealthWindowAfterStreamChange(){}
''' .replace("OBSERVER", observer_name) + methods + r'''
    void frame(long pts){trace.clear();inputTexture.timestamp=pts;onFrameAvailable(inputTexture);}
    void provider(){setNativeSourceImageProvider(new NativeSourceImageProvider());handler.drain();}
    static long[] result(long sequence,int bit){return new long[]{1,sequence,bit,0,10,0,1,1};}
    static WiringFixture asynchronous(boolean external){
        return asynchronous(external,false);
    }
    static WiringFixture asynchronous(boolean external,boolean synchronousBaseline){
        WiringFixture f=new WiringFixture();f.provider();
        if(synchronousBaseline){f.frame(50);assert !f.consumedKnown;f.frame(75);assert f.consumedKnown;}
        if(external)f.externalSignatureTimer=new DenseGpuTimer();
        else {f.denseGpuTimer=new DenseGpuTimer();f.densePyramidEnabled=true;f.denseV28ReducedAnalysisRequested=true;}
        f.frame(100);assert f.consumedMetadata==100 && !f.consumedKnown;
        f.frame(200);assert !f.classifiedFrameReady;
        return f;
    }
    static void delayed(){
        WiringFixture unsupported=new WiringFixture();unsupported.provider();
        unsupported.densePyramidEnabled=true;unsupported.denseGpuTimer=new DenseGpuTimer();
        unsupported.denseGpuTimer.capability=0;
        unsupported.frame(100);unsupported.frame(200);
        assert unsupported.consumedPts==200 && unsupported.consumedKnown;
        assert unsupported.denseSignatureSequence==0;
        // Thor ca177416 filled the asynchronous ring after a long callback
        // stall. Capability alone must not enable the unqualified path.
        WiringFixture capable=new WiringFixture();capable.provider();
        capable.densePyramidEnabled=true;capable.denseGpuTimer=new DenseGpuTimer();
        capable.frame(100);capable.frame(200);
        assert capable.consumedPts==200 && capable.consumedKnown;
        assert capable.denseSignatureSequence==0;
        for(int bit:new int[]{0,1}){
            WiringFixture f=asynchronous(true);
            f.externalSignatureTimer.row=result(1,bit);f.frame(300);
            assert f.consumedPts==200 && f.consumedImage==200;
            assert f.consumedMetadata==200 && f.OBSERVER.latest==300;
            assert f.consumedKnown && f.consumedUnique==(bit==1);
            assert f.OBSERVER.candidates[0]==0;
            assert f.OBSERVER.candidates[1]==300;
            assert trace.indexOf("classifyCandidate:0")<trace.indexOf("retain:1");
            assert trace.indexOf("retain:1")<trace.indexOf("release:0");
            assert f.failures==0;
        }
    }
    static void missingAndBlind(){
        for(long pts:new long[]{0,-1,Long.MIN_VALUE}){
            WiringFixture f=new WiringFixture();f.provider();f.frameRate.authoritative=true;f.frame(pts);
            assert f.OBSERVER.lastObserved==pts && f.consumedMetadata==0;
            assert f.consumedPts==System.now && f.endpointTimestampCorrections==1;
            assert !f.consumedKnown && f.consumedUnique;
            assert trace.indexOf("copyExternal")<trace.indexOf("observe:"+pts);
        }
        WiringFixture authoritative=new WiringFixture();authoritative.provider();
        authoritative.frameRate.authoritative=true;authoritative.frame(100);
        assert authoritative.consumedMetadata==100 && !authoritative.consumedKnown;
        WiringFixture unsafe=new WiringFixture();unsafe.provider();unsafe.signatureReadbackSafe=false;unsafe.frame(100);
        assert unsafe.consumedMetadata==100 && !unsafe.consumedKnown;
        for(boolean before:new boolean[]{true,false}){
            WiringFixture gl=new WiringFixture();gl.provider();
            if(!before)GLES20.errors.add(0);GLES20.errors.add(99);gl.frame(100);
            assert gl.consumedMetadata==100 && !gl.consumedKnown;
        }
        // A prior verified classification must not lend its known bit to any
        // subsequent branch that returns a blind unique result.
        for(int branch=0;branch<5;branch++){
            WiringFixture f=new WiringFixture();f.provider();f.frame(100);
            assert !f.consumedKnown;f.frame(101);assert f.consumedKnown;
            if(branch==0)f.frameRate.authoritative=true;
            if(branch==1)f.signatureReadbackSafe=false;
            if(branch==2)GLES20.errors.add(99);
            if(branch==3){GLES20.errors.add(0);GLES20.errors.add(99);}
            if(branch==4)f.externalSignatureTimer=new DenseGpuTimer();
            f.frame(200);assert f.consumedMetadata==200 && !f.consumedKnown;
        }
    }
    static void fallback(){
        for(boolean glError:new boolean[]{false,true})for(boolean baseline:new boolean[]{false,true}){
            WiringFixture f=asynchronous(false,baseline);f.denseGpuTimer.row=result(1,1);f.failQuery=true;
            if(glError)GLES20.errors.add(99);f.frame(300);
            assert f.failures==0 && f.classifiedFrameReady;
            assert f.consumedPts==300 && f.consumedImage==300 && f.consumedMetadata==300;
            assert f.consumedKnown==(!glError && baseline);
            for(long value:f.OBSERVER.candidates)assert value==0;
        }
    }
    static void malformed(){
        for(int kind=0;kind<5;kind++){
            WiringFixture f=asynchronous(true);long[] row=result(1,1);
            if(kind==0)row[0]=-1;if(kind==1)row[6]=5;if(kind==2)row[1]=9;
            if(kind==3)row[7]=0;if(kind==4){f.clearSignatureCandidates();}
            int consumes=f.consumes;f.externalSignatureTimer.row=row;f.frame(300);
            assert f.failures==1 && f.consumes==consumes;
        }
        WiringFixture badBit=asynchronous(true);badBit.externalSignatureTimer.row=result(1,2);badBit.frame(300);
        assert badBit.failures==1;
    }
    static void providerAndReset(){
        WiringFixture f=asynchronous(true);f.clearSignatureCandidates();
        for(long value:f.OBSERVER.candidates)assert value==0;
        f.signatureCandidateSequence[0]=7;f.OBSERVER.candidates[0]=200;
        f.setNativeSourceImageProvider(new NativeSourceImageProvider());f.handler.drain();
        assert f.OBSERVER.latest==0 && f.OBSERVER.classified==0;
        for(long value:f.OBSERVER.candidates)assert value==0;
        f.OBSERVER.candidates[0]=400;f.OBSERVER.latest=400;f.OBSERVER.classified=400;
        f.resize(640,480,1920,1080,120);f.handler.drain();
        for(long value:f.OBSERVER.candidates)assert value==0;
        assert f.OBSERVER.latest==0 && f.OBSERVER.classified==0;
        assert f.frameRate.refresh==120 && f.frameRate.resets==1;
        NativeSourceImageProvider missing=new NativeSourceImageProvider();missing.valid=false;
        f.setNativeSourceImageProvider(missing);f.handler.drain();f.frameRate.authoritative=true;f.frame(500);
        assert f.consumedMetadata==0 && f.consumedPts==500 && f.consumedUnique;
    }
    static void replacementDelayed(){
        for(boolean remove:new boolean[]{false,true}){
            WiringFixture f=asynchronous(true);NativeSourceImageObserver observer=f.OBSERVER;
            NativeSourceImageProvider previous=observer.provider;
            f.setNativeSourceImageProvider(previous);f.handler.drain();
            assert observer.candidates[0]==200; // Same provider is not replacement.
            f.setNativeSourceImageProvider(remove?null:new NativeSourceImageProvider());f.handler.drain();
            assert f.signatureCandidateSequence[0]==1; // Real old GPU image still retained.
            f.externalSignatureTimer.row=result(1,1);f.frame(300);
            assert f.consumedImage==200 && f.consumedPts==200 && f.consumedKnown;
            assert f.consumedMetadata==0; // Never attach new provider's current300 to old200.
            assert observer.latest==(remove?0:300);
            assert f.failures==0 && f.OBSERVER==observer;
        }
        WiringFixture failed=asynchronous(true);failed.externalSignatureTimer.row=result(1,2);
        failed.frame(300);int finishes=failed.OBSERVER.finishCalls,consumes=failed.consumes;
        int updates=failed.inputTexture.updates;
        long observed=failed.OBSERVER.lastObserved;
        failed.frame(400);
        assert failed.inputTexture.updates==updates+1; // Existing queue drain remains.
        assert failed.OBSERVER.lastObserved==observed && failed.OBSERVER.finishCalls==finishes;
        assert failed.consumes==consumes && failed.failures==1;
    }
    static void closeAndAbsent(){
        WiringFixture absent=new WiringFixture();
        int allocated=NativeSourceImageObserver.allocations;
        absent.setNativeSourceImageProvider(null);absent.handler.drain();
        absent.frameRate.authoritative=true;absent.frame(100);
        assert absent.OBSERVER==null && NativeSourceImageObserver.allocations==allocated;
        assert absent.consumes==1 && absent.consumedPts==100 && absent.consumedUnique;
        WiringFixture beforeClosed=new WiringFixture();beforeClosed.closed.set(true);
        beforeClosed.provider();assert beforeClosed.OBSERVER==null;
        WiringFixture queued=new WiringFixture();
        queued.setNativeSourceImageProvider(new NativeSourceImageProvider());queued.closed.set(true);
        queued.handler.drain();assert queued.OBSERVER==null;
        WiringFixture f=asynchronous(true);NativeSourceImageObserver observer=f.OBSERVER;
        f.closed.set(true);f.closeNativeSourceImageObserver();
        assert f.OBSERVER==null && observer.closed && observer.closeCalls==1;
        assert observer.latest==0 && observer.classified==0;
        for(long value:observer.candidates)assert value==0;
        f.closeNativeSourceImageObserver();f.provider();f.frame(300);
        assert observer.closeCalls==1 && f.OBSERVER==null && f.consumes==2;
    }
    static void software(){
        for(int path=0;path<4;path++){
            WiringFixture f=new WiringFixture();f.provider();f.frameRate.authoritative=true;f.frame(500);
            assert f.consumedMetadata==500;
            f.frameRate.authoritative=path==0;
            f.densePyramidEnabled=path>=2;f.denseGpuTimer=path>=2?new DenseGpuTimer():null;
            f.denseV28ReducedAnalysisRequested=path!=3;
            // Avoid an unrelated geometry reset; the software observation itself
            // must invalidate the latest hardware key, not rely on resize.
            f.historyWidth=2;f.historyHeight=1;
            trace.clear();f.uploadSoftwareFrame(new int[]{777,777},2,1,2f,900);
            assert f.OBSERVER.lastObserved==0 && f.consumedMetadata==0;
            assert f.consumedPts==900 && f.consumedImage==777 && f.consumedUnique;
            assert !f.consumedKnown; // Authoritative/GPU/CPU first baselines are all blind.
            assert trace.indexOf("uploadBitmap")<trace.indexOf("observe:0");
            assert f.diagSoftwareSubmits==1 && f.diagHardwareSubmits==1;
            assert f.presentationAspect==2f && f.notifications==2;
            if(path==1 || path==3){
                trace.clear();f.uploadSoftwareFrame(new int[]{778,778},2,1,2f,901);
                assert f.consumedKnown && f.consumedMetadata==0 && f.consumedPts==901;
                assert f.denseSignatureSequence==0;
                assert !f.denseSignatureBaselineReady;
            }
        }
    }
    public static void main(String[] args){
        if(args[0].equals("delayed"))delayed();
        else if(args[0].equals("blind"))missingAndBlind();
        else if(args[0].equals("fallback"))fallback();
        else if(args[0].equals("malformed"))malformed();
        else if(args[0].equals("reset"))providerAndReset();
        else if(args[0].equals("close"))closeAndAbsent();
        else if(args[0].equals("software"))software();
        else if(args[0].equals("replacement"))replacementDelayed();
        else throw new AssertionError("unknown case");
        java.lang.System.out.println("PASS "+args[0]);
    }
}
'''.replace("OBSERVER", observer_name)
        cls.temporary = tempfile.TemporaryDirectory(prefix="source-image-renderer-")
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        unit = output / "WiringFixture.java"
        unit.write_text(fixture)
        bitmap = output / "android/graphics/Bitmap.java"
        bitmap.parent.mkdir(parents=True)
        bitmap.write_text("""package android.graphics;
public class Bitmap {
    public static class Config {public static final Config ARGB_8888=new Config();}
    int width,height;public int firstPixel;
    public static Bitmap createBitmap(int w,int h,Config c){Bitmap b=new Bitmap();b.width=w;b.height=h;return b;}
    public int getWidth(){return width;}public int getHeight(){return height;}
    public void recycle(){}
    public void setPixels(int[] p,int a,int b,int c,int d,int e,int f){firstPixel=p[0];}
}
""")
        cls.output = output
        trace_stub = output / "android/os/Trace.java"
        trace_stub.parent.mkdir(parents=True)
        trace_stub.write_text("package android.os; public class Trace {public static void beginSection(String s){} public static void endSection(){}}")
        video = ROOT / "unified-android/src/com/thorium/lucent/video"
        result = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", str(output), str(unit), str(bitmap),
                                 str(trace_stub), str(video / "NativeSourceImage.java"), str(video / "NativeSourceImageLedger.java")],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, case):
        result = subprocess.run([str(JAVA / "java"), "-ea", "-cp", str(self.output),
                                 "WiringFixture", case], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + case, result.stdout)

    def test_delayed_classification_keeps_the_old_candidate_metadata(self):
        self.run_case("delayed")

    def test_missing_pts_and_blind_unique_branches_do_not_claim_pixel_proof(self):
        self.run_case("blind")

    def test_sync_fallback_cannot_keep_prior_async_classification(self):
        self.run_case("fallback")

    def test_invalid_async_rows_never_gain_known_pixel_proof(self):
        self.run_case("malformed")

    def test_provider_replacement_resize_and_candidate_clear_invalidate_metadata(self):
        self.run_case("reset")

    def test_null_provider_and_closed_renderer_never_allocate_or_retain_observer(self):
        self.run_case("close")

    def test_software_upload_never_reuses_the_previous_hardware_key(self):
        self.run_case("software")

    def test_provider_change_does_not_relabel_old_gpu_images_and_failure_only_drains(self):
        self.run_case("replacement")

    def test_release_gl_retires_observer_before_other_resources(self):
        # The actual helper is executed above. This assertion binds it to the
        # real large GL teardown without pretending the GL/device work was run.
        cleanup = method(self.source, "private void releaseGl()")
        self.assertRegex(cleanup, r"\{\s*discardFullImageCapture\(\);\s*closeNativeSourceImageObserver\(\);")


if __name__ == "__main__":
    unittest.main(verbosity=2)
