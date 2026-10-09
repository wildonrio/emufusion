"""Actual Java real-pair methods with instrumented JNI leaves, not GPU evidence."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_lsfg_endpoint_lifetime import ROOT, TRANSPORT, JAVA_HOME, method

VIDEO = ROOT / "unified-android/src/com/thorium/lucent/video"
RENDERER = ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
JNI = ROOT / "unified-android/lsfg-qualification-native/lsfg_qualification_jni.cpp"


def fixture():
    source = TRANSPORT.read_text()
    methods = "\n".join(method(source, signature) for signature in (
        "@Override public PreparationResult prepareRealPair(",
        "@Override public PreparationReadiness realPairPreparationReadiness(",
        "private void validateRealPairIdentity(",
        "private void validatePreparationIdentity(",
        "private void retryAnnouncedRealPair()",
        "@Override public EnqueueResult enqueue(",
        "@Override public void resetEndpointTimeline()",
        "private boolean nativeReferences(long sequence)",
        "private void retireDiscardedEndpoints()",
        "private void finishEndpointPreparation(",
        "private void requireOpen()",
        "private static final class PreparedRealPair",
        "private static final class RetainedEndpoint",
        "private static final class ExpectedEndpoint",
        "private static final class SubmittedPresentation",
        "private static final class AdmissionDiagnostics",
    ))
    hook = method(RENDERER.read_text(), "private void prepareExternalRealPairIfPossible()")
    return r'''
import java.util.*;
import com.thorium.lucent.video.*;
public class RealPairTest {
 enum PreparationResult {SUBMITTED,ALREADY_READY,NOT_READY}
 enum PreparationReadiness {ABSENT,PENDING,READY,UNSAFE}
 enum EnqueueResult {SUBMITTED,NOT_READY,DEFERRED}
 enum GenerationReadiness {PENDING,READY,UNSAFE}
 static final int MAX_PENDING_PRESENTATIONS=16;
 final int width=2,height=2;final long nativeHandle=9;
 long requestSessionEpoch,requestPresentationEpoch,nextPresentId=1;
 boolean closed,preparationInFlight; RuntimeException fatalFailure;
 PreparedRealPair preparedRealPair;PreparedGenerated preparedGenerated;
 FrameGenerationPreparationRequest announcedRealPair;
 final AdmissionDiagnostics admission=new AdmissionDiagnostics();
 final LinkedHashMap<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
 final LinkedHashMap<Long,SubmittedPresentation> submitted=new LinkedHashMap<>();
 final Map<Long,Object> pairReadiness=new HashMap<>();
 final List<ExpectedEndpoint> expected=new ArrayList<>();
 void requireOwner(){} void scheduleEndpointPreparation(){}
 PreparationReadiness preparationReadiness(FrameGenerationPreparationRequest r){return PreparationReadiness.READY;}
 GenerationReadiness generationReadiness(long a,long b){return GenerationReadiness.UNSAFE;}
 static boolean isExactMidpoint(FrameGenerationPresentationRequest r){return r.presentationTimestampNs()==r.leftTimestampNs()+(r.rightTimestampNs()-r.leftTimestampNs())/2;}
 static boolean endpointAcquireFenceReady(RetainedEndpoint endpoint){return endpoint.image.ready;}
 static void check(boolean value){if(!value)throw new AssertionError();}
 static void expectFailure(Runnable body){try{body.run();throw new AssertionError("accepted malformed identity");}catch(IllegalArgumentException|IllegalStateException expected){}}
 static class PreparedGenerated {FrameGenerationPreparationRequest request;PreparedGenerated(FrameGenerationPreparationRequest r){request=r;}}
 static class HardwareBuffer {boolean closed;void close(){check(!closed);closed=true;}}
 static class Image {boolean closed,ready=true;void close(){check(!closed);closed=true;}}
 static class android {static class util {static class Log {static void i(String tag,String message){}}}}
 static class NativeLsfgBridge {
  static final int PREPARE_NOT_READY=0,PREPARE_SUBMITTED=1,PREPARE_READY=2,PREPARE_UNSAFE=3;
  static final int SUBMIT_NOT_READY=0,SUBMIT_ACCEPTED=1;
  static int prepared,polled,discarded,queried,enqueued,reset,prepareResult=1,readiness=1,enqueueResult=1;
  static final Set<HardwareBuffer> owned=new HashSet<>();
  static long selected;static boolean referenceError;
  static int prepareRealPair(long h,HardwareBuffer a,HardwareBuffer b,long se,long pe,long ls,long lt,long rs,long rt,int w,int ht,int f){
   check(h==9&&a!=b&&!a.closed&&!b.closed&&rs==ls+1&&rt>lt);++prepared;
   if(prepareResult!=0){owned.add(a);owned.add(b);}return prepareResult;
  }
  static int preparedRealPairReadiness(long h,HardwareBuffer a,HardwareBuffer b,long se,long pe,long ls,long lt,long rs,long rt){++polled;check(owned.contains(a)&&owned.contains(b));return readiness;}
  static void discardPreparedRealPair(long h){++discarded;}
  static void discardPreparedGenerated(long h){}
  static void resetTimeline(long h,long epoch){check(epoch>0);++reset;}
  static boolean referencesSourceImage(long h,HardwareBuffer b){++queried;if(referenceError)throw new IllegalStateException("unknown native lease");return owned.contains(b);}
  static int enqueue(long h,HardwareBuffer a,HardwareBuffer b,long se,long pe,long ls,long lt,long rs,long rt,long timestamp,long physical,long driver,long deadline,long vsync,long expected,long tokenDeadline,int w,int ht,int f,long id){
   ++enqueued;selected=timestamp;check(owned.contains(a)&&owned.contains(b));return enqueueResult;
  }
 }
 RetainedEndpoint add(long sequence,long timestamp){RetainedEndpoint e=new RetainedEndpoint(sequence,timestamp,new Image(),new HardwareBuffer());e.prepared=true;retained.put(sequence,e);return e;}
 FrameGenerationPreparationRequest pair(long left){return FrameGenerationPreparationRequest.between(7,11,left,100*left,left+1,100*(left+1),100*left,2,2,1);}
 FrameGenerationPresentationRequest visible(FrameGenerationPreparationRequest pair,long timestamp){long now=System.nanoTime();return FrameGenerationPresentationRequest.between(pair.sessionEpoch(),pair.presentationEpoch(),pair.leftSequence(),pair.leftTimestampNs(),pair.rightSequence(),pair.rightTimestampNs(),timestamp,now+2_000_000_000L,now+1_500_000_000L,now+1_500_000_000L,0,2,2,1);}
 void readyPair(FrameGenerationPreparationRequest p){check(prepareRealPair(p)==PreparationResult.SUBMITTED);NativeLsfgBridge.readiness=2;check(realPairPreparationReadiness(p)==PreparationReadiness.READY);}
 interface ExternalFrameGenerationTransport {
  boolean supportsPrivateRealPairPreparation();int endpointWidth();int endpointHeight();
  PreparationResult prepareRealPair(FrameGenerationPreparationRequest p);
 }
 static class Renderer {
  ExternalFrameGenerationTransport externalTransport;FrameGenerationPreparationRequest externalRealPairPreparation;
  boolean externalPresentationFailed;long generatorId=7,activeLeftSequence=1,activeRightSequence=2,activeLeftTimestampNs=100,activeRightTimestampNs=200,epoch=11;
  long schedulerPresentationEpoch(){return epoch;}
''' + hook + r'''
 }
 static class TransportStub implements ExternalFrameGenerationTransport {
  boolean supported=true;int calls;FrameGenerationPreparationRequest request;
  public boolean supportsPrivateRealPairPreparation(){return supported;}
  public int endpointWidth(){return 2;}public int endpointHeight(){return 2;}
  public PreparationResult prepareRealPair(FrameGenerationPreparationRequest r){++calls;request=r;return PreparationResult.NOT_READY;}
 }
''' + methods + r'''
 public static void main(String[] args){
  String test=args[0]; RealPairTest t=new RealPairTest();
  RetainedEndpoint a=t.add(1,100),b=t.add(2,200);FrameGenerationPreparationRequest p=t.pair(1);
  if(test.equals("real_left")||test.equals("real_right")){
   t.readyPair(p);long target=test.equals("real_left")?100:200;
   check(t.enqueue(t.visible(p,target))==EnqueueResult.SUBMITTED);
   check(NativeLsfgBridge.selected==target&&NativeLsfgBridge.enqueued==1);
   check(t.preparedRealPair==null&&t.announcedRealPair==null&&t.submitted.size()==1);
   check(t.nativeReferences(1)&&t.nativeReferences(2));
  }else if(test.equals("not_ready")){
   check(t.enqueue(t.visible(p,100))==EnqueueResult.NOT_READY);check(NativeLsfgBridge.enqueued==0);
   t.prepareRealPair(p);check(t.enqueue(t.visible(p,200))==EnqueueResult.NOT_READY);check(t.nextPresentId==1);
   check(t.admission.counts[AdmissionDiagnostics.REAL_ABSENT]==1);
   check(t.admission.counts[AdmissionDiagnostics.REAL_GPU_PENDING]==1);
   check(t.admission.describe().contains(" admissionRealAbsent=1"));
  }else if(test.equals("canonical_identity")){
   expectFailure(()->t.prepareRealPair(FrameGenerationPreparationRequest.between(7,11,1,100,2,200,150,2,2,1)));
   expectFailure(()->t.prepareRealPair(FrameGenerationPreparationRequest.between(7,11,1,100,2,200,200,2,2,1)));
   expectFailure(()->t.prepareRealPair(FrameGenerationPreparationRequest.between(7,11,1,100,2,200,100,3,2,1)));
   check(NativeLsfgBridge.prepared==0);t.readyPair(p);
   check(!t.preparedRealPair.matches(t.visible(p,150)));
   check(!t.preparedRealPair.matches(t.visible(FrameGenerationPreparationRequest.between(8,11,1,100,2,200,100,2,2,1),100)));
   check(!t.preparedRealPair.matches(t.visible(FrameGenerationPreparationRequest.between(7,12,1,100,2,200,100,2,2,1),100)));
   check(!t.preparedRealPair.matches(t.visible(FrameGenerationPreparationRequest.between(7,11,2,200,3,300,200,2,2,1),200)));
  }else if(test.equals("import_retry")){
   b.prepared=false;b.preparing=true;t.preparationInFlight=true;
   check(t.prepareRealPair(p)==PreparationResult.NOT_READY);
   check(NativeLsfgBridge.prepared==0&&NativeLsfgBridge.reset==0&&t.announcedRealPair==p);
   t.finishEndpointPreparation(b,20,null);check(NativeLsfgBridge.prepared==1&&NativeLsfgBridge.reset==1);
   check(t.preparedRealPair!=null&&!t.preparedRealPair.ready);
  }else if(test.equals("producer_fence")){
   b.image.ready=false;check(t.prepareRealPair(p)==PreparationResult.NOT_READY);
   check(NativeLsfgBridge.prepared==0);b.image.ready=true;t.retryAnnouncedRealPair();check(NativeLsfgBridge.prepared==1);
  }else if(test.equals("capacity")){
   NativeLsfgBridge.prepareResult=0;check(t.prepareRealPair(p)==PreparationResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.PREPARE_NATIVE_BUSY]==1);
   check(t.preparedRealPair==null&&t.announcedRealPair==p&&t.nextPresentId==1);
   NativeLsfgBridge.prepareResult=1;t.retryAnnouncedRealPair();check(t.preparedRealPair!=null);
   check(t.admission.counts[AdmissionDiagnostics.PREPARE_SUBMITTED]==1);
   check(t.admission.counts[AdmissionDiagnostics.PREPARE_READY]==0);
   NativeLsfgBridge.readiness=2;
   check(t.realPairPreparationReadiness(p)==PreparationReadiness.READY);
   check(t.realPairPreparationReadiness(p)==PreparationReadiness.READY);
   check(t.admission.counts[AdmissionDiagnostics.PREPARE_READY]==1);
  }else if(test.equals("retirement")){
   t.readyPair(p);t.resetEndpointTimeline();
   check(NativeLsfgBridge.discarded==1&&t.preparedRealPair==null&&t.announcedRealPair==null);
   check(!a.image.closed&&!b.image.closed&&t.retained.size()==2);
   NativeLsfgBridge.owned.clear();t.retireDiscardedEndpoints();check(a.image.closed&&b.image.closed&&t.retained.isEmpty());
  }else if(test.equals("import_lease")){
   t.preparationInFlight=true;check(t.nativeReferences(1));check(NativeLsfgBridge.queried==0);
  }else if(test.equals("lease_unknown")){
   NativeLsfgBridge.referenceError=true;a.discardRequested=true;
   expectFailure(()->t.retireDiscardedEndpoints());check(!a.image.closed&&t.retained.containsKey(1L));
  }else if(test.equals("replace")){
   t.readyPair(p);t.add(3,300);FrameGenerationPreparationRequest next=t.pair(2);
   check(t.prepareRealPair(next)==PreparationResult.SUBMITTED);check(NativeLsfgBridge.discarded==1&&NativeLsfgBridge.prepared==2);
   check(t.admission.counts[AdmissionDiagnostics.REPLACE_READY]==1);
   t.add(4,400);check(t.prepareRealPair(t.pair(3))==PreparationResult.SUBMITTED);
   check(t.admission.counts[AdmissionDiagnostics.REPLACE_PENDING]==1);
   a.discardRequested=true;t.retireDiscardedEndpoints();check(!a.image.closed);
  }else if(test.equals("native_reject")){
   t.readyPair(p);NativeLsfgBridge.enqueueResult=0;
   check(t.enqueue(t.visible(p,200))==EnqueueResult.NOT_READY);
   check(t.preparedRealPair!=null&&t.announcedRealPair==p&&t.submitted.isEmpty()&&t.nextPresentId==1);
   check(t.admission.counts[AdmissionDiagnostics.NATIVE]==1);
  }else if(test.equals("admission_reasons")){
   t.readyPair(p); b.image.ready=false;
   check(t.enqueue(t.visible(p,100))==EnqueueResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.FENCE]==1);b.image.ready=true;
   t.preparationInFlight=true;
   check(t.enqueue(t.visible(p,100))==EnqueueResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.REAL_IMPORT_BUSY]==1);t.preparationInFlight=false;
   t.retained.remove(2L);
   check(t.enqueue(t.visible(p,100))==EnqueueResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.ENDPOINT]==1);t.retained.put(2L,b);
   for(long i=1;i<=16;i++)t.submitted.put(i,null);
   check(t.enqueue(t.visible(p,100))==EnqueueResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.CAPACITY]==1);t.submitted.clear();
   FrameGenerationPresentationRequest expired=FrameGenerationPresentationRequest.between(7,11,1,100,2,200,100,10000,9000,9000,0,2,2,1);
   check(t.enqueue(expired)==EnqueueResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.DEADLINE]==1);
   t.add(3,300);FrameGenerationPreparationRequest next=t.pair(2);
   check(t.enqueue(t.visible(next,200))==EnqueueResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.REAL_MISMATCH]==1);
   check(NativeLsfgBridge.enqueued==0 && t.nextPresentId==1 && t.preparedRealPair!=null);
   t.admission.counts[AdmissionDiagnostics.NATIVE]=Long.MAX_VALUE;
   check(t.admission.blocked(AdmissionDiagnostics.NATIVE)==EnqueueResult.NOT_READY);
   check(t.admission.counts[AdmissionDiagnostics.NATIVE]==Long.MAX_VALUE);
  }else if(test.equals("fatal_closed_retry")){
   t.announcedRealPair=p;t.closed=true;t.retryAnnouncedRealPair();check(NativeLsfgBridge.prepared==0);
   t.closed=false;NativeLsfgBridge.prepareResult=-1;t.retryAnnouncedRealPair();check(t.fatalFailure!=null);
  }else if(test.equals("renderer_hook")){
   Renderer r=new Renderer();r.prepareExternalRealPairIfPossible();check(r.externalRealPairPreparation==null);
   TransportStub stub=new TransportStub();stub.supported=false;r.externalTransport=stub;
   r.prepareExternalRealPairIfPossible();check(stub.calls==0&&r.externalRealPairPreparation==null);
   stub.supported=true;r.prepareExternalRealPairIfPossible();check(stub.calls==1&&stub.request.phase()==0);
   FrameGenerationPreparationRequest first=stub.request;r.prepareExternalRealPairIfPossible();check(stub.request==first);
   r.activeLeftSequence=2;r.activeRightSequence=3;r.activeLeftTimestampNs=200;r.activeRightTimestampNs=300;
   r.prepareExternalRealPairIfPossible();check(stub.request!=first&&stub.request.leftSequence()==2);
   int before=stub.calls;r.externalPresentationFailed=true;r.prepareExternalRealPairIfPossible();check(stub.calls==before);
  }else throw new AssertionError(test);
 }
}
'''


class RealPairPreparationTest(unittest.TestCase):
    def test_actual_java_preparation_activation_and_lease_boundaries(self):
        javac = str(JAVA_HOME / "javac") if (JAVA_HOME / "javac").exists() else shutil.which("javac")
        java = str(JAVA_HOME / "java") if (JAVA_HOME / "java").exists() else shutil.which("java")
        with tempfile.TemporaryDirectory(prefix="lsfg-real-pair-java-") as temporary:
            directory = Path(temporary)
            source = directory / "RealPairTest.java"
            source.write_text(fixture())
            dependencies = [VIDEO / (name + ".java") for name in (
                "FrameGenerationPreparationRequest", "FrameGenerationPresentationRequest",
                "PhysicalPresentationDeadline", "CompositorFrameTimeline",
                "NativeSourceImage", "NativeSourceImageLedger")]
            result = subprocess.run([javac, "--release", "8", "-d", str(directory),
                                     *map(str, dependencies), str(source)], capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for case in ("real_left", "real_right", "not_ready", "canonical_identity",
                         "import_retry", "producer_fence", "capacity", "retirement",
                         "import_lease", "lease_unknown", "replace", "native_reject",
                         "fatal_closed_retry", "renderer_hook", "admission_reasons"):
                with self.subTest(case=case):
                    result = subprocess.run([java, "-cp", str(directory), "RealPairTest", case],
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_jni_real_activation_has_no_deadline_critical_copy_fallback(self):
        source = JNI.read_text()
        enqueue = method(source, "Java_com_thorium_preview_game_NativeLsfgBridge_enqueue(")
        self.assertNotIn("tryPrepare(request)", enqueue)
        self.assertIn("preparedRealPair->matches(left, right", enqueue)
        self.assertIn("presentationTimestampNs != leftTimestampNs", enqueue)
        self.assertIn("presentationTimestampNs != rightTimestampNs", enqueue)
        self.assertIn("activatePrivatePrepared", enqueue)
        prepare = method(source, "Java_com_thorium_preview_game_NativeLsfgBridge_prepareRealPair(")
        self.assertIn("tryPreparePrivateEndpointPair(left, right)", prepare)
        self.assertNotIn("tryPresentContextSyncFd", prepare)
        self.assertNotIn("physicalPresent", prepare)
        self.assertIn("left == right", prepare)
        query = method(source, "Java_com_thorium_preview_game_NativeLsfgBridge_referencesSourceImage(")
        self.assertIn("return JNI_TRUE;", query)

    def test_renderer_hooks_precede_selection_and_follow_pair_construction(self):
        source = RENDERER.read_text()
        wrapper = method(source, "private void renderFrame(")
        self.assertIn("renderTracedFrame(frameTimeNanos);", wrapper)
        render = method(source, "private void renderTracedFrame(")
        self.assertLess(render.index("prepareExternalRealPairIfPossible();"),
                        render.index("frameRate.selectBufferedPresentation("))
        copy = method(source, "private void copyBufferedEndpoints(boolean initialPair)")
        self.assertIn("prepareExternalRealPairIfPossible();", copy)
        present = method(source, "private void presentExternalBuffered(")
        self.assertLess(present.index("commitBufferedEndpointAdvance("),
                        present.index("prepareExternalRealPairIfPossible();"))


if __name__ == "__main__":
    unittest.main()
