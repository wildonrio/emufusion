"""Run production delayed readiness scheduling with a deterministic owner queue."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class GpuReadyNotificationTest(unittest.TestCase):
    def test_delayed_ready_bound_and_retirement(self):
        source = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        body = method(source, 'private void schedulePreparationReadyCheck(')
        code = '''
import java.util.ArrayDeque;
class ReadyProbe {
 static class PreparedPresentation {long timelineEpoch=1,proofSequence=1;boolean discardRequested,ready;}
 static class Owner {
  ArrayDeque<Runnable> queue=new ArrayDeque<>();boolean accept=true;
  boolean postDelayed(Runnable r,long delay){if(!accept)return false;queue.add(r);return true;}
  void run(){queue.remove().run();}
 }
 Owner owner=new Owner();boolean closed,ready,throwPoll;Throwable fatalFailure;
 long timelineEpoch=1;int notifications,polls;
 PreparedPresentation preparedPresentation=new PreparedPresentation(),queuedPreparation;
 java.util.Map<Long,PreparedPresentation> readyOutputs=new java.util.HashMap<>();
 Runnable preparationCapacityListener=()->notifications++;
 boolean completedPreparationGpuReady(PreparedPresentation p){polls++;if(throwPoll)throw new IllegalStateException();return ready;}
 BODY
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  ReadyProbe p=new ReadyProbe();p.schedulePreparationReadyCheck(p.preparedPresentation,3);
  p.owner.run();check(p.notifications==0&&p.owner.queue.size()==1);
  p.ready=true;p.owner.run();check(p.notifications==1&&p.owner.queue.isEmpty());
  // Display polling caches completion between worker callback and delayed check.
  p=new ReadyProbe();PreparedPresentation cached=p.preparedPresentation;
  p.schedulePreparationReadyCheck(cached,3);
  cached.ready=true;p.readyOutputs.put(cached.proofSequence,cached);p.preparedPresentation=null;
  p.owner.run();check(p.notifications==1&&p.polls==0&&p.owner.queue.isEmpty());
  // A stale/retired cached output must not wake the pipeline.
  for(int gate=0;gate<3;gate++){
   p=new ReadyProbe();cached=p.preparedPresentation;p.schedulePreparationReadyCheck(cached,3);
   cached.ready=true;p.readyOutputs.put(cached.proofSequence,cached);p.preparedPresentation=null;
   if(gate==0)cached.discardRequested=true;
   if(gate==1)p.timelineEpoch++;
   if(gate==2)p.readyOutputs.put(cached.proofSequence,new PreparedPresentation());
   p.owner.run();check(p.notifications==0&&p.polls==0&&p.owner.queue.isEmpty());
  }
  p=new ReadyProbe();p.schedulePreparationReadyCheck(p.preparedPresentation,3);
  while(!p.owner.queue.isEmpty())p.owner.run();check(p.polls==3&&p.notifications==0);
  for(int gate=0;gate<5;gate++){
   p=new ReadyProbe();p.schedulePreparationReadyCheck(p.preparedPresentation,3);
   if(gate==0)p.closed=true;
   if(gate==1)p.timelineEpoch++;
   if(gate==2)p.preparedPresentation.discardRequested=true;
   if(gate==3)p.preparedPresentation=null;
   if(gate==4)p.preparationCapacityListener=null;
   p.owner.run();check(p.polls==0&&p.owner.queue.isEmpty());
  }
  p=new ReadyProbe();p.throwPoll=true;p.schedulePreparationReadyCheck(p.preparedPresentation,3);
  p.owner.run();check(p.fatalFailure!=null&&p.owner.queue.isEmpty());
  p=new ReadyProbe();p.owner.accept=false;p.schedulePreparationReadyCheck(p.preparedPresentation,3);
  check(p.fatalFailure!=null);
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'ReadyProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'ReadyProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
