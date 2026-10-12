"""Execute used renderer admission/FIFO/history/export with real native metadata.

Only Android/GL, rate-policy and external carrier leaves are synthetic. This is
identity/retention coverage, not physical cadence, pixels or guest-clock proof.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_native_source_image_renderer_wiring import method, JAVA

ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / "unified-android/src/com/thorium/emufusion/video"
DFG = ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"


class NativeEndpointProvenanceTest(unittest.TestCase):
    def test_actual_admission_fifo_history_rotation_export_and_zero_hot_allocations(self):
        production = DFG.read_text()
        signatures = (
            "private void finishNativeClassifiedObservation(boolean unique)",
            "private void releaseNativeEndpointProvenance(int slot)",
            "private void copyNativeEndpointProvenance(int source, int destination)",
            "private void clearNativeEndpointTimeline(boolean fifo)",
            "private String nativeEndpointProvenanceDiagnostic()",
            "private void closeNativeSourceImageObserver()",
            "private void consumeClassifiedFrame(boolean unique)",
            "private void acceptPresentationEndpoint(int sourceTexture, long timestampNs,",
            "private boolean admitExternalEndpointCandidate()",
            "private void publishExternalEndpoint(",
            "private void discardEndpointFifoHead()",
            "private void consumeEndpointIntoHistory(int historyIndex, boolean left)",
            "private void resetEndpointTimelineForSchedulerEpoch()",
            "private void invalidateBufferedPairForReprime(boolean resetController)",
            "private void commitBufferedEndpointAdvance(int presentation, int advance)",
        )
        fixture = r'''
import com.thorium.emufusion.video.*;
import java.nio.*;
import java.lang.management.ManagementFactory;
public class ProvenanceTest {
    static void check(boolean value){if(!value)throw new AssertionError();}
    static class Log {static void w(String t,String m){}}
    static class Build {static class VERSION {static int SDK_INT=33;}}
    static class EGL14 {
        static final Object EGL_NO_SURFACE=new Object();static boolean swap=true;
        static boolean eglMakeCurrent(Object a,Object b,Object c,Object d){return true;}
        static boolean eglSwapBuffers(Object a,Object b){return swap;}
    }
    static class EGLExt {static long timestamp;
        static boolean eglPresentationTimeANDROID(Object a,Object b,long t){timestamp=t;return true;}}
    static class GLES20 {
        static final int GL_FRAMEBUFFER=1,GL_COLOR_BUFFER_BIT=2;
        static void glBindFramebuffer(int a,int b){} static void glViewport(int a,int b,int c,int d){}
        static void glClearColor(float a,float b,float c,float d){} static void glClear(int a){}
    }
    static class AdaptiveFrameRateController {
        static final int PRESENT_REAL=1;
        static boolean continuous=true,duplicate=true;
        static boolean endpointSpanContinuous(long a,long b,double hz){return continuous;}
        static boolean duplicateOccupiesNextSourceSlot(long a,long b,double hz,int c,int d){return duplicate;}
    }
    static class Rate {boolean sustainable=true;int resets;
        boolean hasSustainableGenerationRate(){return sustainable;}
        double presentationSourceHz(){return 60;}
        boolean lockedTierActive(){return false;}
        boolean admitLockedTierEndpoint(long timestamp){return true;}
        double directLatticeSourceHz(){return 0;}
        void resetPresentation(){resets++;}}
    static class ExternalFrameGenerationTransport {
        boolean admit=true;int exports,cancelled,resets;long seq,pts;
        final NativeSourceImageLedger values=new NativeSourceImageLedger(1);
        boolean canAcceptEndpoint(){return admit;}
        boolean usesAppOwnedPresentation(){return false;}
        int endpointWidth(){return 1920;}int endpointHeight(){return 1080;}
        void expectEndpoint(long s,long p,NativeSourceImageLedger source,int slot,long lease){
            exports++;seq=s;pts=p;
            long old=values.lease(0);if(old!=0)values.release(0,old);
            if(source!=null && lease!=0)check(source.copyTo(slot,lease,values,0)==NativeSourceImageLedger.Result.SUCCESS);
        }
        void cancelExpectedEndpoint(long s){check(seq==s);cancelled++;long l=values.lease(0);if(l!=0)values.release(0,l);}
        void resetEndpointTimeline(){resets++;}
    }
    static class TransportFactory {boolean nativeSoftwareGeometry(){return false;}}
    static class Timeline {boolean pairSpanAllowed(long a,long b){return true;}void reset(){}}
    final Timeline timeline=new Timeline();boolean timelineMode,timelineActive;
    TransportFactory externalTransportFactory;
    Object deferredExternalPreparation,pendingAppOwnedRequest,pendingAppOwnedPreparation;
    static final int ENDPOINT_FIFO_CAPACITY=6,NATIVE_HISTORY_BASE=6,NATIVE_ADMISSION_SLOT=8;
    static final String TAG="test";long generatorId=1;
    final NativeSourceImageObserver nativeSourceImageObserverInitial=new NativeSourceImageObserver(6);
    NativeSourceImageObserver nativeSourceImageObserver=nativeSourceImageObserverInitial;
    NativeSourceImageLedger nativeEndpointProvenance=new NativeSourceImageLedger(9);
    final Rate frameRate=new Rate();ExternalFrameGenerationTransport externalTransport;
    boolean holdoutMode;boolean withholdForHoldout(int texture,long timestampNs){return false;}
    final int[] endpointFifoTextures={10,11,12,13,14,15},historyTextures={20,21};
    final long[] endpointFifoSequence=new long[6],endpointFifoTimestampNs=new long[6],
        endpointFifoUniqueSequence=new long[6],endpointFifoCandidateLoss=new long[6];
    final int[] endpointFifoSubmission=new int[6];final long[] textureContent=new long[32];
    int previousIndex,currentIndex=1,endpointFifoHead,endpointFifoCount;
    long activeLeftSequence,activeRightSequence,activeLeftTimestampNs,activeRightTimestampNs,
        activeLeftUniqueSequence,activeRightUniqueSequence,activeLeftCandidateLoss,activeRightCandidateLoss;
    int activeLeftSubmission,activeRightSubmission,lastPresentationEndpointSubmission;
    long nativeProvenanceTransfers,nativeProvenanceMissing,nativeProvenanceFailures,
        endpointCandidateUnavailable,endpointTimestampCorrections,endpointFifoCoalesced,endpointSequence,
        realFrameCount,lastPresentationEndpointTimestampNs,bufferedSyntheticQuotaSkippedCount,
        observedBufferedPresentationEpoch,externalEndpointAdmissionRejected;
    boolean classifiedFrameReady=true,classifiedPixelVerdictKnown=true,activePairReady,
        activePairSyntheticCommitted,motionEstimateReady,denseTemporalGuideReady,
        externalEndpointAdmissionBlocked,observeUnique=true,copyFailure;
    int classifiedUniqueTexture=1,classifiedUniqueSubmission=1,historyWidth=1280,historyHeight=720,
        outputWidth=1920,outputHeight=1080;
    long classifiedUniqueTimestampNs;float presentationAspect=16f/9;
    Object eglEndpointSurface=new Object(),eglDisplay=new Object(),eglContext=new Object(),eglSurface=new Object();
    long schedulerPresentationEpoch(){return 1+frameRate.resets;}
    void resetHealthWindowAfterStreamChange(){}void refreshProofEvidencePresentationEpoch(){}
    boolean observeUniqueFrame(long p,int s){return observeUnique;}
    void copyTexture(int s,int d){if(copyFailure)throw new IllegalStateException("copy failed");textureContent[d]=textureContent[s];}
    void drawTexture2d(int t){check(textureContent[t]==classifiedUniqueTimestampNs);}
    void fail(String m){throw new IllegalStateException(m);}void checkGl(String m){}
    void recordPromotedEndpoint(long s){}void prepareBufferedPairIfPossible(){}
    static class Provider implements NativeSourceImageProvider {
        long frame=900,session=11,surface=22,swap=33,composition=1;int status=1;boolean held;
        public int sourceImageBinding(ByteBuffer b){
            b.putInt(0,1);b.putInt(4,64);b.putLong(8,session);b.putLong(16,surface);b.putLong(24,swap);return 1;}
        public int querySourceImage(long s,long u,long p,ByteBuffer b){
            b.putInt(0,1);b.putInt(4,808);b.putInt(8,status);b.putLong(16,composition);b.putLong(24,p);
            b.putLong(40,session);b.putLong(48,surface);b.putLong(56,swap);b.putLong(72,composition++);
            b.putLong(80,p-1);b.putInt(88,1);b.putInt(92,1);b.putInt(96,1);
            b.putLong(104,44);b.putLong(112,frame);b.putLong(120,-789);
            b.putInt(128,7);b.putInt(132,2);b.putInt(136,2);b.putInt(140,2);b.putInt(144,held?2:1);
            b.putInt(148,1280);b.putInt(152,720);b.putInt(156,1280);b.putInt(160,1);
            b.putInt(184,1280);b.putInt(188,720);return status;}
    }
    final Provider provider=new Provider();
    ProvenanceTest(){nativeSourceImageObserver.setProvider(provider);}
    void classify(long raw,long output,boolean unique,boolean known){
        nativeSourceImageObserver.observeLatest(raw);nativeSourceImageObserver.classifyLatest();
        classifiedUniqueTimestampNs=output;textureContent[1]=output;
        classifiedPixelVerdictKnown=known;++classifiedUniqueSubmission;
        finishNativeClassifiedObservation(unique);
    }
    long lease(int slot){return nativeEndpointProvenance.lease(slot);}
    long frame(int slot){return nativeEndpointProvenance.queueFrameNumber(slot,lease(slot),0);}
    NativeSourceImage.Decode status(int slot){return nativeEndpointProvenance.observation(slot,lease(slot));}
    NativeSourceImageLedger.PixelVerdict pixels(int slot){return nativeEndpointProvenance.pixelVerdict(slot,lease(slot));}
''' + "\n".join(method(production, signature) for signature in signatures) + r'''
    void exactDelayedAndRotation(){
        externalTransport=new ExternalFrameGenerationTransport();
        nativeSourceImageObserver.observeLatest(1000);nativeSourceImageObserver.retainCandidate(2);
        provider.frame=901;nativeSourceImageObserver.observeLatest(2000);
        nativeSourceImageObserver.classifyCandidate(2);nativeSourceImageObserver.releaseCandidate(2);
        classifiedUniqueTimestampNs=1000;textureContent[1]=1000;
        finishNativeClassifiedObservation(true);consumeClassifiedFrame(true);
        check(endpointSequence==1 && lease(8)==0 && frame(0)==900 && textureContent[10]==1000);
        check(externalTransport.values.queueFrameNumber(0,externalTransport.values.lease(0),0)==900);
        check(externalTransport.pts==1000 && EGLExt.timestamp==1000);
        consumeEndpointIntoHistory(0,true);check(frame(6)==900 && lease(0)==0);
        provider.frame=902;classify(3000,3000,true,true);consumeClassifiedFrame(true);
        consumeEndpointIntoHistory(1,false);check(frame(7)==902 && activeRightSequence==2);
        check(nativeEndpointProvenance.compare(6,lease(6),7,lease(7))==NativeSourceImage.Pair.QUEUE_FRAME_GAP);
        long rightLease=lease(7);commitBufferedEndpointAdvance(1,1);
        check(previousIndex==1 && currentIndex==0 && lease(7)==rightLease && lease(6)==0 && frame(7)==902);
        provider.frame=903;classify(4000,4000,true,true);consumeClassifiedFrame(true);
        consumeEndpointIntoHistory(currentIndex,false);
        check(nativeEndpointProvenance.compare(7,lease(7),6,lease(6))==NativeSourceImage.Pair.ADJACENT_QUEUED_IMAGES);
        check(nativeEndpointProvenanceDiagnostic().contains("authority=false"));
        NativeSourceImage.Slot snapshot=new NativeSourceImage.Slot();
        check(nativeEndpointProvenance.copySnapshot(6,lease(6),snapshot)==NativeSourceImage.Transfer.COPIED);
        check(snapshot.sessionEpoch()==11 && snapshot.surfaceEpoch()==22 && snapshot.swapchainEpoch()==33);
        check(snapshot.guestRequestedTimestampNs(0)==-789 && snapshot.queueFrameNumber(0)==903);
    }
    void missingHeldAndErrors(){
        classify(1000,1000,true,false);consumeClassifiedFrame(true);check(pixels(0)==NativeSourceImageLedger.PixelVerdict.UNKNOWN);
        provider.held=true;classify(2000,2000,false,true);consumeClassifiedFrame(false);
        check(pixels(1)==NativeSourceImageLedger.PixelVerdict.HELD && frame(1)==900);
        classify(0,3000,true,true);consumeClassifiedFrame(true);
        check(status(2)==NativeSourceImage.Decode.BAD_ARGUMENT && nativeEndpointProvenance.rawTimestampNs(2,lease(2))==0);
        provider.status=2;classify(4000,4000,true,true);consumeClassifiedFrame(true);
        check(status(3)==NativeSourceImage.Decode.PENDING && frame(3)==0);
        provider.status=1;classify(5000,5001,true,true);consumeClassifiedFrame(true);
        check(status(4)==NativeSourceImage.Decode.ACCEPTED && frame(4)==900 && pixels(4)==NativeSourceImageLedger.PixelVerdict.UNIQUE);
        check(nativeEndpointProvenance.classifiedJoin(4,lease(4))==NativeSourceImageLedger.TimestampJoin.MISMATCH);
        check(nativeEndpointProvenance.classifiedTimestampNs(4,lease(4))==5001 && nativeEndpointProvenance.rawTimestampNs(4,lease(4))==5000);
        check(nativeEndpointProvenance.compare(0,lease(0),4,lease(4))==NativeSourceImage.Pair.CLASSIFIED_TIMESTAMP_MISMATCH);
        discardEndpointFifoHead();check(lease(0)==0 && frame(1)==900);
    }
    void heldReseed(){
        // With no retained presentation endpoint, an actual held image re-seeds
        // Direct presentation even without a sustainable generation rate.
        frameRate.sustainable=false;provider.held=true;classify(1000,1000,false,true);consumeClassifiedFrame(false);
        check(endpointFifoCount==1 && endpointSequence==1 && lease(8)==0);
        check(frame(endpointFifoHead)==900 && pixels(endpointFifoHead)==NativeSourceImageLedger.PixelVerdict.HELD);
        provider.frame=901;classify(2000,2000,false,true);consumeClassifiedFrame(false);
        check(endpointFifoCount==1 && endpointSequence==1 && lease(8)==0);
    }
    void rejectionAndResets(){
        lastPresentationEndpointTimestampNs=500;// a prior endpoint exists: held frames are not re-seeds
        frameRate.sustainable=false;classify(1000,1000,false,true);consumeClassifiedFrame(false);
        check(lease(8)==0 && endpointFifoCount==0);
        observeUnique=false;classify(2000,2000,true,true);consumeClassifiedFrame(true);check(lease(8)==0);
        observeUnique=true;externalTransport=new ExternalFrameGenerationTransport();externalTransport.admit=false;
        classify(3000,3000,true,true);consumeClassifiedFrame(true);
        check(lease(8)==0 && externalTransport.exports==0 && endpointSequence==0);
        externalTransport.admit=true;classify(4000,4000,true,true);consumeClassifiedFrame(true);
        AdaptiveFrameRateController.continuous=false;provider.frame=905;
        classify(5000,5000,true,true);consumeClassifiedFrame(true);AdaptiveFrameRateController.continuous=true;
        check(endpointFifoCount==1 && frame(endpointFifoHead)==905 && lease(8)==0);
        consumeEndpointIntoHistory(0,true);classify(6000,6000,true,true);
        resetEndpointTimelineForSchedulerEpoch();check(frame(8)==905 && lease(6)==0);
        consumeClassifiedFrame(true);check(frame(endpointFifoHead)==905);
        classify(7000,7000,true,true);EGL14.swap=false;
        try{consumeClassifiedFrame(true);throw new AssertionError();}catch(IllegalStateException good){}
        EGL14.swap=true;check(lease(8)==0 && externalTransport.cancelled==1);
        closeNativeSourceImageObserver();check(nativeEndpointProvenance==null && nativeSourceImageObserver==null);
    }
    void overflowAndEpochs(){
        for(int i=0;i<7;i++){provider.frame=1000+i;classify(1000+i*1000,1000+i*1000,true,true);consumeClassifiedFrame(true);}
        check(endpointFifoCount==1 && frame(0)==1006);
        for(int i=1;i<6;i++)check(lease(i)==0);
        consumeEndpointIntoHistory(0,true);provider.swap++;
        classify(9000,9000,true,true);consumeClassifiedFrame(true);consumeEndpointIntoHistory(1,false);
        check(nativeEndpointProvenance.compare(6,lease(6),7,lease(7))==NativeSourceImage.Pair.EPOCH_CHANGED);
        deferredExternalPreparation=pendingAppOwnedRequest=pendingAppOwnedPreparation=new Object();
        invalidateBufferedPairForReprime(false);check(lease(6)==0 && lease(7)==0);
        check(deferredExternalPreparation==null && pendingAppOwnedRequest==null && pendingAppOwnedPreparation==null);
    }
    void hotLoop(){
        classify(1000,1000,true,true);consumeClassifiedFrame(true);consumeEndpointIntoHistory(0,true);
        releaseNativeEndpointProvenance(6);lastPresentationEndpointTimestampNs=0;
    }
    public static void main(String[] args){
        new ProvenanceTest().exactDelayedAndRotation();new ProvenanceTest().missingHeldAndErrors();
        new ProvenanceTest().heldReseed();
        new ProvenanceTest().rejectionAndResets();new ProvenanceTest().overflowAndEpochs();
        ProvenanceTest warm=new ProvenanceTest();for(int i=0;i<50000;i++)warm.hotLoop();
        com.sun.management.ThreadMXBean bean=(com.sun.management.ThreadMXBean)ManagementFactory.getThreadMXBean();
        bean.setThreadAllocatedMemoryEnabled(true);long thread=Thread.currentThread().getId();
        long before=bean.getThreadAllocatedBytes(thread);for(int i=0;i<10000;i++)warm.hotLoop();
        long allocated=bean.getThreadAllocatedBytes(thread)-before;
        check(allocated==0);System.out.println("used admission/FIFO/history/export; zero hot allocations; no authority");
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="native-endpoint-provenance-") as temporary:
            path = Path(temporary) / "ProvenanceTest.java"
            path.write_text(fixture)
            sources = [VIDEO / f"{name}.java" for name in (
                "NativeSourceImage", "NativeSourceImageLedger", "NativeSourceImageObserver", "NativeSourceImageProvider")]
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", temporary,
                                       *map(str, sources), str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / "java"), "-cp", temporary, "ProvenanceTest"],
                                 capture_output=True, text=True, timeout=45)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn("zero hot allocations; no authority", ran.stdout)


if __name__ == "__main__":
    unittest.main()
