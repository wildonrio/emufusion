"""Synthetic Java-leaf fault tests of actual LSFG/DFG production method bodies.

No device, renderer substitution or empirical quality/cadence claim. The fake
ImageReader can omit an unacquired carrier, as an asynchronous queue can do.
"""
import unittest

from tools.tests import test_lsfg_endpoint_lifetime as lifetime

ROOT, TRANSPORT, method = lifetime.ROOT, lifetime.TRANSPORT, lifetime.method


class LsfgEndpointDiscontinuityTest(unittest.TestCase):
    compile_run = lifetime.LsfgEndpointLifetimeTest.compile_run

    def fixture(self):
        production = TRANSPORT.read_text()
        methods = "\n".join(method(production, signature) for signature in (
            "@Override public void expectEndpoint(long sequence, long timestampNs)",
            "@Override public void cancelExpectedEndpoint(long sequence)",
            "@Override public void onImageAvailable(ImageReader source)",
            "@Override public long consumeEndpointDiscontinuities()",
            "@Override public void resetEndpointTimeline()",
            "@Override public boolean hasAdjacentPair(long left, long right)",
            "private boolean nativeReferences(long sequence)",
            "private void retireDiscardedEndpoints()",
            "private void requireOpen()",
            "private static final class ExpectedEndpoint",
            "private static final class RetainedEndpoint",
        ))
        renderer = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
        consumer = method(renderer, "private void consumeExternalEndpointDiscontinuities()")
        return r'''
import java.util.*;
interface ExternalFrameGenerationTransport {
    long consumeEndpointDiscontinuities(); void resetEndpointTimeline();
}
public class EndpointTest implements ExternalFrameGenerationTransport {
    static final int MAX_IMAGES=8; final int width=2,height=2; final long nativeHandle=9;
    long lastExpectedSequence,lastExpectedTimestampNs,endpointDiscontinuities,endpointDiscontinuitiesTotal;
    long requestPresentationEpoch=37; boolean closed,preparationInFlight;
    RuntimeException fatalFailure; int preparationSchedules;
    final ArrayDeque<ExpectedEndpoint> expected=new ArrayDeque<>();
    final LinkedHashMap<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
    final Map<Long,Object> pairReadiness=new HashMap<>();
    final Map<Long,SubmittedPresentation> submitted=new HashMap<>();
    PreparedGenerated preparedGenerated,preparedRealPair;
    Request announcedRealPair;
    static final List<String> logs=new ArrayList<>();
    static void check(boolean condition){if(!condition)throw new AssertionError(logs.toString());}
    void requireOwner(){}
    void scheduleEndpointPreparation(){++preparationSchedules;}
    static class Log { static void w(String tag,String message){logs.add(message);} }
    static class android { static class util { static class Log {
        static void w(String tag,String message){EndpointTest.logs.add(message);}
    } } }
    static class NativeLsfgBridge {
        static int discarded,discardedReal,referenceQueries;
        static boolean referenceFailure;
        // Instrumented native leaf, not a mock of Java's ownership decision:
        // abandoned copy/proof/output dependencies remain carrier references.
        static final IdentityHashMap<HardwareBuffer,NativeWork> work=new IdentityHashMap<>();
        static void discardPreparedGenerated(long handle){check(handle==9);++discarded;}
        static void discardPreparedRealPair(long handle){check(handle==9);++discardedReal;}
        static boolean referencesSourceImage(long handle,HardwareBuffer buffer){
            check(handle==9 && buffer!=null && !buffer.closed);++referenceQueries;
            if(referenceFailure)throw new IllegalStateException("synthetic unknown native fence state");
            NativeWork pending=work.get(buffer);
            if(pending==null)return false;
        if(!pending.copyReady)
                return true;
            work.remove(buffer);return false;
        }
    }
    static class NativeWork {boolean copyReady,proofRequired=true,proofReady,outputReady;}
    static class Request {
        final long left,right; Request(long l,long r){left=l;right=r;}
        long leftSequence(){return left;}long rightSequence(){return right;}
    }
    static class PreparedGenerated {Request request; PreparedGenerated(long l,long r){request=new Request(l,r);} }
    static class SubmittedPresentation {Request request; SubmittedPresentation(long l,long r){request=new Request(l,r);} }
    static class HardwareBuffer {
        static final int RGBA_8888=1;static final long USAGE_GPU_SAMPLED_IMAGE=1L;
        int width=2,height=2,layers=1,format=1,closes;long usage=1;boolean closed;
        boolean isClosed(){return closed;}int getWidth(){check(!closed);return width;}
        int getHeight(){check(!closed);return height;}int getLayers(){check(!closed);return layers;}
        int getFormat(){check(!closed);return format;}long getUsage(){check(!closed);return usage;}
        void close(){++closes;closed=true;}
    }
    static class Image {
        long timestamp; HardwareBuffer buffer=new HardwareBuffer();final ImageReader reader;boolean closed;
        Image(long t,ImageReader r){timestamp=t;reader=r;}
        long getTimestamp(){return timestamp;}HardwareBuffer getHardwareBuffer(){return buffer;}
        void close(){check(!closed);closed=true;--reader.acquired;}
    }
    static class ImageReader {
        final ArrayDeque<Image> pending=new ArrayDeque<>();int acquired,calls;
        Image acquireNextImage(){++calls;if(acquired>=8)throw new IllegalStateException("ninth acquire");
            Image image=pending.pollFirst();if(image!=null)++acquired;return image;}
        Image deliver(long timestamp){Image image=new Image(timestamp,this);pending.add(image);return image;}
    }
    Image announce(ImageReader reader,long sequence,long timestamp){
        expectEndpoint(sequence,timestamp);return reader.deliver(timestamp);
    }
    static class Dfg {
        static final String TAG="DFG";
        final ExternalFrameGenerationTransport externalTransport;
        long endpointCandidateUnavailable,epoch=37;int resetCalls,proofRefreshes,healthResets;
        final long generatorId=1;final FrameRate frameRate=new FrameRate();
        class FrameRate {void resetPresentation(){++epoch;}}
        Dfg(EndpointTest transport){externalTransport=transport;}
        long schedulerPresentationEpoch(){return epoch;}
        void resetEndpointTimelineForSchedulerEpoch(){++resetCalls;externalTransport.resetEndpointTimeline();}
        void refreshProofEvidencePresentationEpoch(){++proofRefreshes;}
        void resetHealthWindowAfterStreamChange(){++healthResets;}
''' + consumer + r'''
    }
    void verifyFatal(Image image,String expectedReason,int expectedDepth){
        check(fatalFailure!=null && fatalFailure.getMessage().contains(expectedReason));
        check(image.closed && (image.buffer==null || image.buffer.closes==1));
        check(expected.size()==expectedDepth && retained.isEmpty());
        check(endpointDiscontinuities==0 && endpointDiscontinuitiesTotal==0);
        int before=image.reader.calls;image.reader.deliver(999);onImageAvailable(image.reader);
        check(image.reader.calls==before); // terminal failure never retries/relabels
        try{consumeEndpointDiscontinuities();throw new AssertionError("fatal hidden");}
        catch(IllegalStateException expected){}
    }
    static void normal(){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        for(int i=1;i<=8;i++)t.announce(r,i,100+i);
        t.onImageAvailable(r);check(t.fatalFailure==null && t.retained.size()==8 && r.calls==8);
        t.onImageAvailable(r);check(r.calls==8 && t.consumeEndpointDiscontinuities()==0);
        try{t.expectEndpoint(9,109);throw new AssertionError("capacity exceeded");}
        catch(IllegalStateException expected){}
    }
    static void lossAndOwnerBoundary(){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();Dfg d=new Dfg(t);
        Image first=t.announce(r,1,101);t.onImageAvailable(r);t.retained.get(1L).prepared=true;
        t.submitted.put(44L,new SubmittedPresentation(1,1));
        NativeWork copy=new NativeWork();NativeLsfgBridge.work.put(first.buffer,copy);
        t.expectEndpoint(2,102); // announced, but never acquired: async carrier replaced
        Image resumed=t.announce(r,3,103);t.onImageAvailable(r);t.retained.get(3L).prepared=true;
        check(t.fatalFailure==null && t.retained.get(3L).timestampNs==103 && !t.retained.containsKey(2L));
        check(!t.hasAdjacentPair(1,3) && !t.hasAdjacentPair(2,3));
        check(!first.closed && t.submitted.size()==1 && t.endpointDiscontinuitiesTotal==1);
        check(logs.get(0).contains("firstSkippedSequence=2") && logs.get(0).contains("resumedSequence=3"));
        d.consumeExternalEndpointDiscontinuities();
        check(d.epoch==38 && d.endpointCandidateUnavailable==1 && d.resetCalls==1);
        check(d.proofRefreshes==1 && d.healthResets==1 && t.requestPresentationEpoch==0);
        check(!first.closed && t.submitted.size()==1 && t.retained.get(1L).discardRequested);
        check(resumed.closed && !t.retained.containsKey(3L)); // old visible chain re-primes
        d.consumeExternalEndpointDiscontinuities();check(d.epoch==38 && d.endpointCandidateUnavailable==1);
        check(t.endpointDiscontinuitiesTotal==1); // health/epoch resets cannot erase lifetime loss
        Image four=t.announce(r,4,104),five=t.announce(r,5,105);t.onImageAvailable(r);
        t.retained.get(4L).prepared=true;t.retained.get(5L).prepared=true;
        check(t.hasAdjacentPair(4,5) && !t.hasAdjacentPair(1,4));
        check(!four.closed && !five.closed && !first.closed);
        copy.copyReady=true;t.retireDiscardedEndpoints();
        check(first.closed && first.buffer.closes==1 && t.submitted.size()==1);
        t.submitted.clear(); // immutable physical metadata retires independently
    }
    static void discardedExpectation(String mode){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        t.expectEndpoint(1,101);t.expectEndpoint(2,102);t.resetEndpointTimeline();
        check(t.expected.size()==2 && t.expected.peekFirst().discard);
        Image stale=r.deliver(102);t.onImageAvailable(r);
        check(t.fatalFailure==null && stale.closed && stale.buffer.closes==1 && t.retained.isEmpty());
        check(t.endpointDiscontinuitiesTotal==1 && t.preparationSchedules==0);
        if(mode.equals("discard_then_new")){
            Image current=t.announce(r,3,103);t.onImageAvailable(r);
            check(t.retained.get(3L).image==current && !current.closed);
        }
        t.resetEndpointTimeline();check(t.consumeEndpointDiscontinuities()==1);
        check(t.consumeEndpointDiscontinuities()==0 && t.endpointDiscontinuitiesTotal==1);
    }
    static void boundedAndRepeated(){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        for(int i=1;i<=8;i++)t.expectEndpoint(i,100+i);
        try{t.expectEndpoint(9,109);throw new AssertionError("capacity exceeded");}
        catch(IllegalStateException expected){}
        Image image=r.deliver(108);t.onImageAvailable(r);
        check(t.retained.get(8L).image==image && t.endpointDiscontinuitiesTotal==7);
        check(t.expected.isEmpty() && r.acquired==1 && t.consumeEndpointDiscontinuities()==7);
        t.resetEndpointTimeline();check(image.closed);
        t.expectEndpoint(9,109);t.announce(r,10,110);t.onImageAvailable(r);
        check(t.endpointDiscontinuitiesTotal==8 && t.consumeEndpointDiscontinuities()==1);
    }
    static void preparingOwner(){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        Image image=t.announce(r,1,101);t.onImageAvailable(r);t.retained.get(1L).preparing=true;
        t.expectEndpoint(2,102);t.announce(r,3,103);t.onImageAvailable(r);
        t.resetEndpointTimeline();check(!image.closed && t.retained.get(1L).discardRequested);
        t.retained.get(1L).preparing=false;t.retireDiscardedEndpoints();check(image.closed);
    }
    static void privateOwnerAndMultipleLosses(){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        Image one=t.announce(r,1,101),two=t.announce(r,2,102);t.onImageAvailable(r);
        PreparedGenerated privateWork=new PreparedGenerated(1,2);t.preparedGenerated=privateWork;
        t.expectEndpoint(3,103);t.announce(r,4,104);t.onImageAvailable(r);
        t.expectEndpoint(5,105);t.expectEndpoint(6,106);t.announce(r,7,107);t.onImageAvailable(r);
        check(t.fatalFailure==null && t.endpointDiscontinuitiesTotal==3);
        check(t.consumeEndpointDiscontinuities()==3 && t.consumeEndpointDiscontinuities()==0);
        check(t.preparedGenerated==privateWork && NativeLsfgBridge.discarded==0);
        check(!one.closed && !two.closed && t.nativeReferences(1) && t.nativeReferences(2));
        check(!t.hasAdjacentPair(2,4) && !t.hasAdjacentPair(4,7));
    }
    static void nativeAbandonedOwner(boolean real){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        Image one=t.announce(r,1,101),two=t.announce(r,2,102);t.onImageAvailable(r);
        PreparedGenerated identity=new PreparedGenerated(1,2);
        if(real){t.preparedRealPair=identity;t.announcedRealPair=identity.request;}
        else t.preparedGenerated=identity;
        check(t.nativeReferences(1) && t.nativeReferences(2) && NativeLsfgBridge.referenceQueries==0);
        NativeWork work=new NativeWork();
        NativeLsfgBridge.work.put(one.buffer,work);NativeLsfgBridge.work.put(two.buffer,work);
        t.resetEndpointTimeline();
        check(t.preparedRealPair==null && t.announcedRealPair==null && t.preparedGenerated==null);
        check(NativeLsfgBridge.discardedReal==(real?1:0) && NativeLsfgBridge.discarded==(real?0:1));
        check(!one.closed && !two.closed && t.retained.size()==2 && r.acquired==2);
        // Only the exact source-copy fence releases the original carrier.
        // Later proof/output work reads the fixed private copies, not this Image.
        work.proofReady=true;work.outputReady=true;t.retireDiscardedEndpoints();
        check(!one.closed && !two.closed); // Even signaled output/proof does not waive copy.
        work.proofReady=false;work.outputReady=false;
        work.copyReady=true;t.retireDiscardedEndpoints();
        check(one.closed && two.closed && one.buffer.closes==1 && two.buffer.closes==1);
        check(t.retained.isEmpty() && r.acquired==0 && NativeLsfgBridge.work.isEmpty());
        t.retireDiscardedEndpoints();check(one.buffer.closes==1 && two.buffer.closes==1);
    }
    static void preparationInFlightOwner(){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        Image one=t.announce(r,1,101),two=t.announce(r,2,102);t.onImageAvailable(r);
        t.preparationInFlight=true;t.resetEndpointTimeline();
        check(!one.closed && !two.closed && NativeLsfgBridge.referenceQueries==0);
        check(t.nativeReferences(1) && t.nativeReferences(2));
        t.preparationInFlight=false;t.retireDiscardedEndpoints();
        check(one.closed && two.closed && NativeLsfgBridge.referenceQueries==2);
    }
    static void failedNativeReferenceQuery(){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        Image one=t.announce(r,1,101),two=t.announce(r,2,102);t.onImageAvailable(r);
        NativeLsfgBridge.referenceFailure=true;
        try{t.resetEndpointTimeline();throw new AssertionError("unknown native ownership released");}
        catch(IllegalStateException expected){check(expected.getMessage().contains("unknown native fence"));}
        check(!one.closed && !two.closed && t.retained.size()==2 && r.acquired==2);
        check(NativeLsfgBridge.referenceQueries==1 && one.buffer.closes==0 && two.buffer.closes==0);
    }
    static void discardedPrefixAndLateLostArrival(String mode){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        t.expectEndpoint(1,101);t.expectEndpoint(2,102);
        if(mode.equals("discard_prefix"))t.resetEndpointTimeline();
        Image resumed=t.announce(r,3,103);t.onImageAvailable(r);
        check(t.fatalFailure==null && t.retained.get(3L).image==resumed);
        check(t.endpointDiscontinuitiesTotal==2 && !resumed.closed);
        if(mode.equals("late_lost_arrival")){
            Image late=r.deliver(102);t.onImageAvailable(r);
            check(t.fatalFailure!=null && late.closed && !resumed.closed);
            check(t.retained.get(3L).image==resumed && t.endpointDiscontinuitiesTotal==2);
        }
    }
    static void invalid(String mode){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        t.expectEndpoint(1,101);t.expectEndpoint(2,102);
        Image image=r.deliver(102);String reason="timestamp identity mismatch";
        if(mode.equals("unknown"))image.timestamp=103;
        else if(mode.equals("near"))image.timestamp=100;
        else if(mode.equals("zero"))image.timestamp=0;
        else if(mode.equals("negative"))image.timestamp=-1;
        else if(mode.equals("ambiguous"))t.expected.add(new ExpectedEndpoint(3,102));
        else if(mode.equals("null")){image.buffer=null;reason="HardwareBuffer identity";}
        else if(mode.equals("closed")){image.buffer.closed=true;reason="closed=true";}
        else if(mode.equals("width")){image.buffer.width=3;reason="actualSize=3x2";}
        else if(mode.equals("height")){image.buffer.height=3;reason="actualSize=2x3";}
        else if(mode.equals("layers")){image.buffer.layers=2;reason="layers=2";}
        else if(mode.equals("format")){image.buffer.format=4;reason="format=4";}
        else if(mode.equals("usage")){image.buffer.usage=0;reason="usage=0";}
        else throw new AssertionError(mode);
        t.onImageAvailable(r);t.verifyFatal(image,reason,mode.equals("ambiguous")?3:2);
    }
    static void cancellationAndDuplicates(String mode){
        EndpointTest t=new EndpointTest();ImageReader r=new ImageReader();
        if(mode.equals("cancel")){
            t.expectEndpoint(1,101);t.cancelExpectedEndpoint(1);t.announce(r,2,102);t.onImageAvailable(r);
            check(t.fatalFailure==null && t.retained.containsKey(2L) && t.endpointDiscontinuitiesTotal==0);
            try{t.expectEndpoint(3,102);throw new AssertionError("duplicate timestamp");}
            catch(IllegalArgumentException expected){}return;
        }
        if(mode.equals("cancelled_arrival")){
            t.expectEndpoint(1,101);t.cancelExpectedEndpoint(1);Image image=r.deliver(101);
            t.onImageAvailable(r);t.verifyFatal(image,"expectedSequence=0",0);return;
        }
        Image prior=t.announce(r,1,101);t.onImageAvailable(r);
        t.expectEndpoint(2,102);Image duplicate=r.deliver(101);t.onImageAvailable(r);
        check(t.fatalFailure!=null && duplicate.closed && duplicate.buffer.closes==1);
        check(!prior.closed && t.retained.get(1L).image==prior && t.expected.size()==1);
        check(t.endpointDiscontinuitiesTotal==0);
    }
    public static void main(String[] args){
        String mode=args[0];
        if(mode.equals("normal"))normal();
        else if(mode.equals("loss_boundary"))lossAndOwnerBoundary();
        else if(mode.equals("discard_prefix") || mode.equals("late_lost_arrival"))
            discardedPrefixAndLateLostArrival(mode);
        else if(mode.startsWith("discard"))discardedExpectation(mode);
        else if(mode.equals("bounded"))boundedAndRepeated();
        else if(mode.equals("preparing"))preparingOwner();
        else if(mode.equals("private_and_multiple"))privateOwnerAndMultipleLosses();
        else if(mode.equals("native_abandoned_real"))nativeAbandonedOwner(true);
        else if(mode.equals("native_abandoned_generated"))nativeAbandonedOwner(false);
        else if(mode.equals("preparation_inflight"))preparationInFlightOwner();
        else if(mode.equals("native_reference_failure"))failedNativeReferenceQuery();
        else if(mode.equals("cancel")||mode.equals("cancelled_arrival")||mode.equals("duplicate_arrival"))
            cancellationAndDuplicates(mode);
        else invalid(mode);
    }
''' + methods + "\n}\n"

    def test_actual_methods_exact_skip_buffer_faults_discard_ownership_and_epoch_boundary(self):
        scenarios = (
            "normal", "loss_boundary", "discard", "discard_then_new", "bounded", "preparing",
            "discard_prefix", "late_lost_arrival", "private_and_multiple",
            "native_abandoned_real", "native_abandoned_generated", "preparation_inflight", "native_reference_failure",
            "unknown", "near", "zero", "negative", "ambiguous", "null", "closed", "width",
            "height", "layers", "format", "usage", "cancel", "cancelled_arrival", "duplicate_arrival",
        )
        self.compile_run(self.fixture(), tuple((scenario,) for scenario in scenarios))

    def test_existing_renderer_consumes_loss_before_any_new_pair_or_presentation(self):
        renderer = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
        render = method(renderer, "private void renderFrame(long frameTimeNanos)")
        consume = render.index("consumeExternalEndpointDiscontinuities();")
        self.assertLess(consume, render.index("pollPhysicalPresentations();"))
        self.assertLess(consume, render.index("prepareBufferedPairIfPossible();"))
        reset = method(TRANSPORT.read_text(), "@Override public void resetEndpointTimeline()")
        self.assertNotIn("submitted.clear", reset)
        self.assertNotIn("expected.clear", reset)
        self.assertNotIn("endpointDiscontinuities =", reset)
        self.assertNotIn("endpointDiscontinuitiesTotal =", reset)


if __name__ == "__main__":
    unittest.main()
