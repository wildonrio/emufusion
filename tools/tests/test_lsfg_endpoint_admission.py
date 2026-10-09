"""Execute production admission/retirement methods with controlled platform leaves.

Capacity pressure is not a timing PASS. This verifies no new ownership/export and
no midpoint continuity across a skipped candidate, without changing pool size.
"""
import unittest

from tools.tests import test_lsfg_endpoint_lifetime as lifetime

ROOT, TRANSPORT, method = lifetime.ROOT, lifetime.TRANSPORT, lifetime.method


class LsfgEndpointAdmissionTest(unittest.TestCase):
    compile_run = lifetime.LsfgEndpointLifetimeTest.compile_run

    def test_actual_renderer_and_transport_admission(self):
        transport = TRANSPORT.read_text()
        renderer = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
        transport_methods = "\n".join(method(transport, signature) for signature in (
            "@Override public boolean canAcceptEndpoint()",
            "@Override public void expectEndpoint(long sequence, long timestampNs)",
            "@Override public void resetEndpointTimeline()",
            "private boolean nativeReferences(long sequence)",
            "private void retireDiscardedEndpoints()",
            "private void requireOpen()",
            "private static final class ExpectedEndpoint",
            "private static final class RetainedEndpoint",
        ))
        renderer_methods = "\n".join(method(renderer, signature) for signature in (
            "private boolean admitExternalEndpointCandidate()",
            "private void acceptPresentationEndpoint(int sourceTexture, long timestampNs,",
            "private boolean synchronizeBufferedPresentationEpoch()",
        ))
        source = r'''
import java.util.*;
public class EndpointTest {
 static void check(boolean condition){if(!condition)throw new AssertionError();}
 interface ExternalFrameGenerationTransport {boolean canAcceptEndpoint();void expectEndpoint(long s,long t);void resetEndpointTimeline();}
 static class HardwareBuffer {boolean closed,copyPending;void close(){check(!closed);closed=true;}}
 static class Image {boolean closed;void close(){check(!closed);closed=true;}}
 static class Request {long left,right;Request(long a,long b){left=a;right=b;}long leftSequence(){return left;}long rightSequence(){return right;}}
 static class Private {Request request;Private(long a,long b){request=new Request(a,b);}}
 static class NativeLsfgBridge {
  static int queries;static boolean error;
  static boolean referencesSourceImage(long handle,HardwareBuffer b){check(!b.closed);++queries;if(error)throw new IllegalStateException("unknown copy");return b.copyPending;}
  static void discardPreparedRealPair(long handle){} static void discardPreparedGenerated(long handle){}
 }
 static class Transport implements ExternalFrameGenerationTransport {
  static final int MAX_IMAGES=8;long nativeHandle=1,lastExpectedSequence,lastExpectedTimestampNs,requestPresentationEpoch=5;
  boolean closed,preparationInFlight;RuntimeException fatalFailure;Private preparedRealPair,preparedGenerated;Request announcedRealPair;
  final ArrayDeque<ExpectedEndpoint> expected=new ArrayDeque<>();
  final LinkedHashMap<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
  final Map<Long,Object> pairReadiness=new HashMap<>();
  final Map<Long,Request> submitted=new HashMap<>();
  void requireOwner(){}
  RetainedEndpoint add(long s){RetainedEndpoint e=new RetainedEndpoint(s,100*s,new Image(),new HardwareBuffer());e.prepared=true;retained.put(s,e);return e;}
''' + transport_methods + r'''
 }
 static class AdaptiveFrameRateController {static boolean endpointSpanContinuous(long a,long b,double h){return true;}}
 static class Clock {long epoch=5;int resets;void resetPresentation(){++resets;++epoch;}double presentationSourceHz(){return 60;}}
 static class Log {static int warnings;static void w(String t,String m){++warnings;}}
 static class Renderer {
  static final int ENDPOINT_FIFO_CAPACITY=6;static final String TAG="test";
  final Clock frameRate=new Clock();ExternalFrameGenerationTransport externalTransport;
  long generatorId=1,endpointCandidateUnavailable,externalEndpointAdmissionRejected,endpointTimestampCorrections;
  long endpointFifoCoalesced,lastPresentationEndpointTimestampNs=800,endpointSequence=8,realFrameCount,observedBufferedPresentationEpoch;
  int lastPresentationEndpointSubmission,endpointFifoCount=2,endpointFifoHead,resetCalls,proofRefreshes,healthResets,exports,copies;
  boolean externalEndpointAdmissionBlocked;
  final int[] endpointFifoTextures=new int[6],endpointFifoSubmission=new int[6];
  final long[] endpointFifoSequence=new long[6],endpointFifoTimestampNs=new long[6],endpointFifoUniqueSequence=new long[6],endpointFifoCandidateLoss=new long[6];
  long schedulerPresentationEpoch(){return frameRate.epoch;}
  void resetEndpointTimelineForSchedulerEpoch(){++resetCalls;externalTransport.resetEndpointTimeline();endpointFifoCount=0;endpointFifoHead=0;lastPresentationEndpointTimestampNs=0;Arrays.fill(endpointFifoSequence,0);}
  void refreshProofEvidencePresentationEpoch(){++proofRefreshes;}
  void resetHealthWindowAfterStreamChange(){++healthResets;}
  void publishExternalEndpoint(int texture,long s,long t){++exports;externalTransport.expectEndpoint(s,t);}
  void copyTexture(int a,int b){++copies;}
  static final int NATIVE_ADMISSION_SLOT=8;
  void releaseNativeEndpointProvenance(int slot){}
  void copyNativeEndpointProvenance(int source,int destination){}
''' + renderer_methods + r'''
 }
 public static void main(String[] args){
  String scenario=args[0];Transport t=new Transport();Renderer r=new Renderer();r.externalTransport=t;
  if(scenario.equals("pressure_recovery")){
   for(long i=1;i<=8;i++){Transport.RetainedEndpoint e=t.add(i);e.buffer.copyPending=true;}
   t.lastExpectedSequence=8;t.lastExpectedTimestampNs=800;
   t.submitted.put(42L,new Request(1,2));
   // Four retiring originals plus active/queued images fill eight below FIFO6.
   for(long i=1;i<=4;i++)t.retained.get(i).discardRequested=true;
   r.acceptPresentationEndpoint(1,900,9);
   check(r.exports==0&&r.copies==0&&r.endpointSequence==8&&r.realFrameCount==0);
   check(r.endpointCandidateUnavailable==1&&r.externalEndpointAdmissionRejected==1&&r.externalEndpointAdmissionBlocked);
   check(r.resetCalls==1&&r.frameRate.resets==1&&r.proofRefreshes==1&&r.healthResets==1);
   check(t.retained.size()==8&&t.submitted.size()==1&&t.expected.isEmpty()&&t.lastExpectedSequence==8);
   r.acceptPresentationEndpoint(1,1000,10);
   check(r.resetCalls==1&&r.endpointCandidateUnavailable==2&&r.externalEndpointAdmissionRejected==2&&r.exports==0);
   HardwareBuffer released=t.retained.get(1L).buffer;released.copyPending=false;
   // Physical metadata survives carrier retirement; admission consumes no identity.
   check(t.canAcceptEndpoint()&&released.closed&&t.submitted.size()==1&&t.lastExpectedSequence==8);
   r.acceptPresentationEndpoint(1,1100,11);
   check(r.exports==1&&r.copies==1&&r.endpointSequence==9&&r.realFrameCount==1&&!r.externalEndpointAdmissionBlocked);
   check(r.endpointFifoCount==1&&r.endpointFifoTimestampNs[0]==1100&&r.endpointFifoCandidateLoss[0]==2);
   check(t.expected.peekFirst().sequence==9&&t.expected.peekFirst().timestampNs==1100&&!t.retained.containsKey(9L));
   check(r.endpointCandidateUnavailable==2&&r.externalEndpointAdmissionRejected==2);
   // A producer callback can recover before the next render/vsync. The actual
   // epoch synchronizer must not discard that just-exported new candidate.
   check(!r.synchronizeBufferedPresentationEpoch()&&r.resetCalls==1&&r.endpointFifoCount==1);
   check(t.expected.peekFirst().sequence==9&&!t.expected.peekFirst().discard);
  }else if(scenario.equals("expected_capacity")){
   for(long i=1;i<=8;i++)t.expectEndpoint(i,100*i);
   check(!t.canAcceptEndpoint()&&t.expected.size()==8&&t.lastExpectedSequence==8);
   try{t.expectEndpoint(9,900);throw new AssertionError();}catch(IllegalStateException expected){}
   check(t.expected.size()==8&&t.lastExpectedSequence==8);
  }else if(scenario.equals("private_import_lease")){
   Transport.RetainedEndpoint a=t.add(1),b=t.add(2);a.discardRequested=b.discardRequested=true;
   t.preparedRealPair=new Private(1,2);t.retireDiscardedEndpoints();check(!a.image.closed&&!b.image.closed&&NativeLsfgBridge.queries==0);
   t.preparedRealPair=null;t.preparationInFlight=true;t.retireDiscardedEndpoints();check(!a.image.closed&&!b.image.closed&&NativeLsfgBridge.queries==0);
   t.preparationInFlight=false;t.retireDiscardedEndpoints();check(a.image.closed&&b.image.closed);
  }else if(scenario.equals("unknown_copy")){
   Transport.RetainedEndpoint a=t.add(1);a.discardRequested=true;NativeLsfgBridge.error=true;
   try{t.canAcceptEndpoint();throw new AssertionError();}catch(IllegalStateException expected){}
   check(!a.image.closed&&!a.buffer.closed&&t.retained.size()==1);
  }else if(scenario.equals("direct")){
   r.externalTransport=null;r.acceptPresentationEndpoint(1,900,9);
   check(r.exports==0&&r.copies==1&&r.endpointSequence==9&&r.resetCalls==0&&r.externalEndpointAdmissionRejected==0);
  }else throw new AssertionError(scenario);
 }
}
'''
        self.compile_run(source, tuple((case,) for case in (
            "pressure_recovery", "expected_capacity", "private_import_lease", "unknown_copy", "direct")))


if __name__ == "__main__":
    unittest.main()
