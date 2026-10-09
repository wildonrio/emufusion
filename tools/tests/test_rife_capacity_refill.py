"""Exercise renderer refill lifecycle gates without authorizing presentation."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class CapacityRefillTest(unittest.TestCase):
    def test_owner_callback_stale_pending_and_failure_gates(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, 'private void registerExternalPreparationCapacityListener()')
        java = '''
import java.util.concurrent.atomic.AtomicBoolean;
class CapacityProbe {
 static class ExternalFrameGenerationTransport {
  Runnable listener;boolean appOwned=true;
  boolean usesAppOwnedPresentation(){return appOwned;}
  void setPreparationCapacityListener(Runnable r){listener=r;}
 }
 ExternalFrameGenerationTransport externalTransport=new ExternalFrameGenerationTransport();
 AtomicBoolean closed=new AtomicBoolean();
 boolean externalPresentationFailed,externalRatePathActive=true,fail,resolvePending,changeEpoch;
 Object pendingAppOwnedRequest;long externalLastPlannedPhysicalNs=1;
 long observedBufferedPresentationEpoch=1,epoch=1;int refills,failures,retries;
 long schedulerPresentationEpoch(){return epoch;}
 boolean retryDeferredExternalPreparation(){return false;}
 boolean retryPendingAppOwnedPresentation(){retries++;if(fail)throw new IllegalStateException();
  if(resolvePending)pendingAppOwnedRequest=null;if(changeEpoch)epoch++;return true;}
 void prepareExternalLookahead(){refills++;if(fail)throw new IllegalStateException();}
 void failRuntimePresentation(String s,RuntimeException e){failures++;}
 BODY
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  for(int gate=0;gate<8;gate++){
   CapacityProbe p=new CapacityProbe();p.registerExternalPreparationCapacityListener();
   Runnable callback=p.externalTransport.listener;
   if(gate==0)p.closed.set(true);
   if(gate==1)p.externalPresentationFailed=true;
   if(gate==2)p.externalTransport=new ExternalFrameGenerationTransport();
   if(gate==3)p.externalRatePathActive=false;
   if(gate==4)p.pendingAppOwnedRequest=new Object();
   if(gate==5)p.externalLastPlannedPhysicalNs=0;
   if(gate==6)p.epoch++;
   callback.run();check(p.refills==(gate==7?1:0));
   check(p.retries==(gate==4?1:0));
  }
  CapacityProbe p=new CapacityProbe();p.registerExternalPreparationCapacityListener();
  p.fail=true;p.externalTransport.listener.run();check(p.failures==1);
  for(boolean changed : new boolean[]{false,true}){
   p=new CapacityProbe();p.registerExternalPreparationCapacityListener();
   p.pendingAppOwnedRequest=new Object();p.resolvePending=true;p.changeEpoch=changed;
   p.externalTransport.listener.run();
   check(p.retries==1&&p.pendingAppOwnedRequest==null);
   check(p.refills==(changed?0:1));
  }
  p=new CapacityProbe();p.registerExternalPreparationCapacityListener();
  Object exactRequest=new Object();p.pendingAppOwnedRequest=exactRequest;
  p.externalTransport.listener.run();check(p.retries==1&&p.refills==0);
  check(p.pendingAppOwnedRequest==exactRequest);
  p.fail=true;p.externalTransport.listener.run();check(p.failures==1);
  p=new CapacityProbe();p.externalTransport.appOwned=false;
  p.registerExternalPreparationCapacityListener();check(p.externalTransport.listener==null);
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'CapacityProbe.java'
            unit.write_text(java)
            for command in ([str(JAVA / 'javac'), '-d', directory, str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'CapacityProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
