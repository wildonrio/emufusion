"""Execute the production Java submission method with controlled clock/leaves.

This checks pre-admission ownership and controller accounting only. Transport,
GPU, Android and panel behavior are deliberately not simulated as proof.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class ExternalPresentationAdmissionTest(unittest.TestCase):
    def test_actual_submission_expiry_identity_deferral_and_commit_boundaries(self):
        source = SOURCE.read_text()
        production = "\n".join(method(source, signature) for signature in (
            "    private void presentExternalBuffered(",
            "    private boolean externalPhysicalSlotAvailable(",
            "    private void recordExternalPhysicalSlot("))
        fixture = r'''
public class ExternalAdmissionTest {
    static class System {static long now=99;static long nanoTime(){return now;}}
    static class Log {static void i(String t,String m){} static void w(String t,String m){}}
    static final String TAG="fixture";
    static class AdaptiveFrameRateController {static final int PRESENT_REAL=1,PRESENT_SYNTHETIC=2;}
    static class FrameGenerationPresentationRequest {
        static final int FORMAT_RGBA8_UNORM=1;
        boolean generated=true,adjacent=true,timeline=true;
        long session=4,epoch=5,left=10,right=11,deadline=100;
        int width=320,height=240,format=1;
        boolean hasAdjacentPair(){return adjacent;}
        boolean isGenerated(){return generated;}
        long sessionEpoch(){return session;} long presentationEpoch(){return epoch;}
        long leftSequence(){return left;} long rightSequence(){return right;}
        long leftTimestampNs(){return 1000;} long rightTimestampNs(){return 2000;}
        long desiredPhysicalPresentTimeNs(){return deadline+20;}
        long hardCompletionDeadlineNs(){return deadline;}
        int outputWidth(){return width;} int outputHeight(){return height;}
        int outputFormat(){return format;}
        boolean hasCompositorFrameTimeline(){return timeline;}
        long compositorExpectedPresentationTimeNs(){return desiredPhysicalPresentTimeNs();}
        double phase(){return generated?.5:0;}
    }
    static class ExternalFrameGenerationTransport {
        enum EnqueueResult {SUBMITTED,NOT_READY,DEFERRED}
        EnqueueResult result=EnqueueResult.SUBMITTED;
        boolean pair=true,timeline=true;
        long clockAfterCall=99;int calls,releases,pending;
        boolean hasAdjacentPair(long l,long r){return pair;}
        int endpointWidth(){return 320;} int endpointHeight(){return 240;}
        EnqueueResult enqueue(FrameGenerationPresentationRequest r){
            calls++;System.now=clockAfterCall;
            if(result==EnqueueResult.SUBMITTED)pending++;
            return result;
        }
        int pendingPhysicalPresentationCount(){return pending;}
        boolean requiresCompositorFrameTimeline(){return timeline;}
        void releaseBefore(long seq){releases++;}
    }
    static class Rate {
        int scans=2,advance=1,credits=2,drops,defers,commits;
        int panelScansPerOutput(){return scans;}
        long panelPeriodNs(){return 8333333;}
        int bufferedEndpointAdvanceAfterPresentation(){return advance;}
        int bufferedOutputCredits(){return credits;}
        void dropBufferedPresentationSlot(){drops++;}
        void deferBufferedPresentationSlot(){defers++;}
        void commitBufferedPresentation(boolean ok){assert ok;commits++;credits--;}
    }
    static class Bootstrap {boolean ready=true;boolean complete(){return ready;}}
    static class Ledger {
        boolean room=true;int submits;
        boolean canSubmit(){return room;}
        void submit(FrameGenerationPresentationRequest r,int scans){assert scans>0;submits++;}
    }
    static class Budget {int admits;boolean admit(FrameGenerationPresentationRequest r){admits++;return true;}}
    final ExternalFrameGenerationTransport externalTransport=new ExternalFrameGenerationTransport();
    final Rate frameRate=new Rate();final Bootstrap externalPhysicalClockBootstrap=new Bootstrap();
    final Ledger externalPresentationLedger=new Ledger();final Budget midpointPairBudget=new Budget();
    boolean externalRatePathActive=true,activePairSyntheticCommitted;
    long activeLeftSequence=10,activeRightSequence=11,generatorId=4,epoch=5;
    long externalPrequeueDeferredCount,bufferedSyntheticNotReadyCount;
    long compositorFrameTimelineCommitted,externalLastPlannedPhysicalNs;
    long externalLastSubmittedCompositorExpectedNs,externalPhysicalSlotRejectedCount;
    long externalDirectOutputPhaseAnchorNs,bufferedSyntheticSelectedCount;
    long bufferedLastSelectedSyntheticPair,phaseDiagSpanSumNs;
    double phaseDiagSum;float phaseDiagMin=1,phaseDiagMax;int phaseDiagCount;
    int advances,refreshes,resets,realPairPreparations;
    long schedulerPresentationEpoch(){return epoch;}
    void commitBufferedEndpointAdvance(int p,int a){advances++;activeLeftSequence+=a;activeRightSequence+=a;}
    void refreshProofEvidencePresentationEpoch(){refreshes++;}
    void resetHealthWindowAfterStreamChange(){resets++;}
    // Controlled leaf: actual preparation/leases are tested separately. This
    // fixture verifies the production caller reaches it only after ownership,
    // controller/ledger commit, endpoint advance, and retirement request.
    void prepareExternalRealPairIfPossible(){
        assert frameRate.commits==realPairPreparations+1;
        assert externalPresentationLedger.submits==frameRate.commits;
        assert advances==frameRate.commits && externalTransport.releases==advances;
        assert externalLastPlannedPhysicalNs>0;
        realPairPreparations++;
    }
''' + production + r'''
    void assertUntouched() {
        assert frameRate.commits==0;
        assert externalPresentationLedger.submits==0 && midpointPairBudget.admits==0;
        assert advances==0 && realPairPreparations==0;
        assert externalTransport.releases==0 && !activePairSyntheticCommitted;
        assert compositorFrameTimelineCommitted==0 && externalLastPlannedPhysicalNs==0;
        assert externalLastSubmittedCompositorExpectedNs==0;
        assert bufferedSyntheticSelectedCount==0 && phaseDiagCount==0 && refreshes==0;
    }
    interface Mutation {void apply(ExternalAdmissionTest f,FrameGenerationPresentationRequest r);}
    static void malformed(Mutation mutation) {
        for(long now:new long[]{99,100,101,Long.MAX_VALUE}) malformed(mutation,now);
    }
    static void malformed(Mutation mutation,long now) {
        ExternalAdmissionTest f=new ExternalAdmissionTest();
        FrameGenerationPresentationRequest r=new FrameGenerationPresentationRequest();
        mutation.apply(f,r);System.now=now;
        long left=f.activeLeftSequence,right=f.activeRightSequence;int credits=f.frameRate.credits;
        try {f.presentExternalBuffered(r,2);throw new AssertionError("invalid contract accepted");}
        catch(IllegalStateException expected){}
        f.assertUntouched();assert f.frameRate.drops==0 && f.externalTransport.calls==0;
        assert f.activeLeftSequence==left && f.activeRightSequence==right && f.frameRate.credits==credits;
    }
    public static void main(String[] args) {
        for(boolean generated:new boolean[]{false,true}) {
            for(long now:new long[]{100,101,Long.MAX_VALUE}) {
                ExternalAdmissionTest f=new ExternalAdmissionTest();
                FrameGenerationPresentationRequest r=new FrameGenerationPresentationRequest();
                r.generated=generated;System.now=now;
                f.presentExternalBuffered(r,generated?2:1);
                f.assertUntouched();assert f.externalTransport.calls==0;
                assert f.activeLeftSequence==10 && f.activeRightSequence==11 && f.frameRate.credits==2;
                assert f.frameRate.drops==1 && f.bufferedSyntheticNotReadyCount==1;
                assert r.deadline==100; // expired proposal never retimestamped
                // A NEW future proposal for the retained pair may be admitted.
                FrameGenerationPresentationRequest next=new FrameGenerationPresentationRequest();
                next.generated=generated;next.deadline=200;System.now=150;
                f.externalTransport.clockAfterCall=250; // Accepted before return can cross cutoff.
                f.presentExternalBuffered(next,generated?2:1);
                assert f.externalTransport.calls==1 && f.externalTransport.pending==1;
                assert f.externalPresentationLedger.submits==1 && f.frameRate.commits==1;
                assert f.midpointPairBudget.admits==(generated?1:0);
                assert f.activeLeftSequence==11 && f.advances==1;
                assert f.realPairPreparations==1;
                assert f.compositorFrameTimelineCommitted==1 && f.externalLastPlannedPhysicalNs==220;
                assert r.deadline==100 && next.deadline==200;
            }
        }
        for(ExternalFrameGenerationTransport.EnqueueResult result:
                ExternalFrameGenerationTransport.EnqueueResult.values()) {
            ExternalAdmissionTest f=new ExternalAdmissionTest();System.now=99;
            f.externalTransport.result=result;f.externalTransport.clockAfterCall=101;
            f.presentExternalBuffered(new FrameGenerationPresentationRequest(),2);
            assert f.externalTransport.calls==1;
            if(result==ExternalFrameGenerationTransport.EnqueueResult.SUBMITTED){
                assert f.externalPresentationLedger.submits==1 && f.midpointPairBudget.admits==1;
                assert f.realPairPreparations==1;
            } else {
                f.assertUntouched();assert f.externalTransport.pending==0;
                assert f.activeLeftSequence==10 && f.activeRightSequence==11 && f.frameRate.credits==2;
                assert f.frameRate.drops==(result==ExternalFrameGenerationTransport.EnqueueResult.NOT_READY?1:0);
                assert f.frameRate.defers==(result==ExternalFrameGenerationTransport.EnqueueResult.DEFERRED?1:0);
            }
        }
        malformed((f,r)->r.adjacent=false);
        malformed((f,r)->f.externalTransport.pair=false);
        malformed((f,r)->f.externalRatePathActive=false);
        malformed((f,r)->f.externalPhysicalClockBootstrap.ready=false);
        malformed((f,r)->r.generated=false);
        malformed((f,r)->f.frameRate.scans=0);
        malformed((f,r)->f.frameRate.credits=0);
        malformed((f,r)->f.frameRate.advance=2);
        malformed((f,r)->f.activeRightSequence=12);
        malformed((f,r)->f.externalPresentationLedger.room=false);
        malformed((f,r)->f.epoch=0);
        malformed((f,r)->r.session=6);
        malformed((f,r)->r.epoch=6);
        malformed((f,r)->r.width=640);
        malformed((f,r)->r.height=480);
        malformed((f,r)->r.format=2);
        malformed((f,r)->r.timeline=false);
        malformed((f,r)->f.externalTransport.timeline=false);
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="external-admission-") as temporary:
            output = Path(temporary)
            java = output / "ExternalAdmissionTest.java"
            java.write_text(fixture)
            result = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d",
                                     str(output), str(java)], capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(JAVA / "java"), "-ea", "-cp", str(output),
                                     "ExternalAdmissionTest"], capture_output=True,
                                    text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
