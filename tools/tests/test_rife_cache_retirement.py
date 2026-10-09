"""Run actual cache retirement methods with fake native slots and Images."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class CacheRetirementTest(unittest.TestCase):
    def test_old_outputs_retire_only_after_worker_and_future_outputs_survive(self):
        jdk=Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        if not (jdk/'javac').exists(): self.skipTest('JDK17 unavailable')
        source=(ROOT/'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        release=source.split('@Override public void releaseBefore(long minimumSequence) {',1)[1].split(
            '@Override public void resetEndpointTimeline()',1)[0]
        retire=source.split('private void retireDiscardedCachedOutputs() {',1)[1].split(
            'private AppOwnedOutput takeReadyOutput(',1)[0]
        ready=source.split('private boolean hasReadyOutput(FrameGenerationPreparationRequest request) {',1)[1].split(
            'private void cacheReadyOutput(',1)[0]
        code='''import java.util.*;
public class CacheProbe {
 static class FrameGenerationPreparationRequest {
  long left; FrameGenerationPreparationRequest(long n) {left=n;}
  long leftSequence(){return left;}
  boolean matches(FrameGenerationPreparationRequest other){return left==other.left;}
 }
 static class Bridge { int released; void releaseBoundHardwareBufferRifeOutput(long p,boolean s){released++;} }
 static class PreparedPresentation {
  long proofSequence; FrameGenerationPreparationRequest request; Bridge jobBridge=new Bridge(); boolean discardRequested;
  PreparedPresentation(long n){proofSequence=n;request=new FrameGenerationPreparationRequest(n);}
 }
 static class Image { int closes; void close(){if(++closes!=1)throw new AssertionError("double close");} }
 static class RetainedEndpoint { Image image=new Image(); boolean discardRequested; }
 enum GenerationReadiness { READY }
 boolean preparationInFlight,cachedOutputDiscardPending;
 long minimumRetainedOutputSequence;
 LinkedHashMap<Long,PreparedPresentation> readyOutputs=new LinkedHashMap<>();
 LinkedHashMap<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
 LinkedHashMap<Long,GenerationReadiness> pairReadiness=new LinkedHashMap<>();
 HashMap<Long,Integer> boundTextureIds=new HashMap<>();
 HashMap<Long,Bridge> boundOutputBridges=new HashMap<>();
 int deleted;
 void requireOwner(){} void requireOpen(){} void deleteOwnedTexture(long p){deleted++;}
 boolean nativeReferences(long sequence) {
  for(PreparedPresentation p:readyOutputs.values()) if(sequence==p.request.left||sequence==p.request.left+1)return true;
  return false;
 }
 public void releaseBefore(long minimumSequence) {
'''+release+'''private void retireDiscardedCachedOutputs() {
'''+retire+'''private boolean hasReadyOutput(FrameGenerationPreparationRequest request) {
'''+ready+'''
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  CacheProbe p=new CacheProbe(); PreparedPresentation old=new PreparedPresentation(1), future=new PreparedPresentation(7);
  p.readyOutputs.put(1L,old); p.readyOutputs.put(7L,future);
  for(long i=1;i<=9;i++)p.retained.put(i,new RetainedEndpoint());
  p.preparationInFlight=true; p.releaseBefore(5);
  check(old.discardRequested&&!future.discardRequested&&old.jobBridge.released==0);
  check(p.retained.containsKey(1L)&&p.retained.get(1L).discardRequested);
  check(!p.hasReadyOutput(old.request)&&p.hasReadyOutput(future.request));
  p.preparationInFlight=false; p.retireDiscardedCachedOutputs(); p.releaseBefore(5);
  check(old.jobBridge.released==1&&future.jobBridge.released==0&&p.deleted==1);
  check(!p.retained.containsKey(1L)&&p.retained.containsKey(7L));
  p.releaseBefore(3); p.retireDiscardedCachedOutputs();
  check(p.minimumRetainedOutputSequence==5&&p.deleted==1&&p.hasReadyOutput(future.request));
  p.releaseBefore(9);check(future.jobBridge.released==1&&p.readyOutputs.isEmpty());
 }
}'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'CacheProbe.java';path.write_text(code)
            subprocess.run([str(jdk/'javac'),str(path)],check=True,capture_output=True,text=True)
            subprocess.run([str(jdk/'java'),'-cp',directory,'CacheProbe'],check=True,capture_output=True,text=True)
