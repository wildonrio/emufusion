"""Execute production endpoint preparation with fake imports and queued worker."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CachedEndpointLookaheadTest(unittest.TestCase):
    def test_cached_lookahead_and_cold_import_lifetimes(self):
        source = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        methods = source.split('private void scheduleEndpointPreparation()', 1)[1].split('private void finishEndpointPreparation(', 1)[0]
        java = '''import java.util.*;
class EndpointProbe {
 static class HardwareBuffer {
  boolean primary=true,secondary=true;int closes;
  boolean isClosed(){return closes!=0;}
  void close(){if(++closes!=1)throw new AssertionError("double close");}
 }
 static class Image {HardwareBuffer buffer=new HardwareBuffer();int gets;
  HardwareBuffer getHardwareBuffer(){gets++;return buffer;}}
 static class RetainedEndpoint {boolean prepared,preparing,discardRequested;long sequence;Image image=new Image();}
 class Bridge {boolean primary,fail;int imports,queries;
  Bridge(boolean p){primary=p;}
  boolean isHardwareBufferEndpointPrepared(HardwareBuffer b,int w,int h){queries++;if(fail)throw new IllegalStateException();return primary?b.primary:b.secondary;}
  void prepareHardwareBufferEndpoint(HardwareBuffer b,int w,int h){check(!b.isClosed());imports++;}
 }
 static class Worker {Runnable pending;void execute(Runnable r){check(pending==null);pending=r;}}
 static class Owner {void post(Runnable r){r.run();}}
 static class Log {static void i(String tag,String message){}}
 static final String TAG="test";static final int MAX_IMAGES=8;
 boolean closed,preparationInFlight,nativePending,endpointImportCacheWarm;
 boolean startupSurfaceProbeComplete=true,generatedRatePathActive=true;
 Throwable fatalFailure;int width=256,height=240,consecutiveCachedEndpointCount;
 Map<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
 Bridge bridge=new Bridge(true),secondaryBridge=new Bridge(false);
 Worker preparationWorker=new Worker();Owner owner=new Owner();
 void requireOwner(){}
 void finishEndpointPreparation(long s,RetainedEndpoint e,long wall,Throwable failure){
  preparationInFlight=false;e.preparing=false;e.prepared=failure==null;fatalFailure=failure;
 }
 RetainedEndpoint add(long s,boolean prepared){RetainedEndpoint e=new RetainedEndpoint();e.sequence=s;e.prepared=prepared;retained.put(s,e);return e;}
 private void scheduleEndpointPreparation()''' + methods + '''
 static void check(boolean value){if(!value)throw new AssertionError();}
 public static void main(String[] args){
  EndpointProbe p=new EndpointProbe();
  for(long s=1;s<=8;s++)p.add(s,s<=3);
  p.scheduleEndpointPreparation();
  for(RetainedEndpoint e:p.retained.values()){
   check(e.prepared);check(e.image.buffer.closes==(e.sequence<=3?0:1));
  }
  check(p.preparationWorker.pending==null&&p.bridge.imports==0);
  for(boolean secondaryMiss:new boolean[]{false,true}){
   p=new EndpointProbe();for(long s=1;s<=3;s++)p.add(s,true);
   RetainedEndpoint cold=p.add(4,false);
   if(secondaryMiss)cold.image.buffer.secondary=false;else cold.image.buffer.primary=false;
   p.scheduleEndpointPreparation();check(!cold.prepared&&!cold.preparing);
   check(cold.image.buffer.closes==1&&p.preparationWorker.pending==null);
  }
  p=new EndpointProbe();RetainedEndpoint cold=p.add(1,false);cold.image.buffer.primary=false;
  p.scheduleEndpointPreparation();check(cold.preparing&&p.preparationInFlight&&cold.image.buffer.closes==0);
  p.preparationWorker.pending.run();check(cold.prepared&&cold.image.buffer.closes==1);
  check(p.bridge.imports==1&&p.secondaryBridge.imports==1);
  p=new EndpointProbe();RetainedEndpoint bad=p.add(1,false);p.bridge.fail=true;
  p.scheduleEndpointPreparation();check(p.fatalFailure!=null&&bad.image.buffer.closes==1&&p.preparationWorker.pending==null);
  for(int gate=0;gate<5;gate++){
   p=new EndpointProbe();RetainedEndpoint e=p.add(1,false);
   if(gate==0)p.closed=true;if(gate==1)p.fatalFailure=new Exception();
   if(gate==2)p.startupSurfaceProbeComplete=false;if(gate==3)p.preparationInFlight=true;if(gate==4)p.nativePending=true;
   p.scheduleEndpointPreparation();check(e.image.gets==0&&p.preparationWorker.pending==null);
  }
 }
}'''
        jdk = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'EndpointProbe.java'
            path.write_text(java)
            subprocess.run([str(jdk / 'javac'), str(path)], check=True, capture_output=True)
            subprocess.run([str(jdk / 'java'), '-cp', directory, 'EndpointProbe'], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
