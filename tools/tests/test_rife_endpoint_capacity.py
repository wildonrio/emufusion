"""Exercise production endpoint admission/announcement with deterministic leaves."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT=Path(__file__).resolve().parents[2]


class RifeEndpointCapacityTest(unittest.TestCase):
    def test_full_pool_rejects_before_export_and_recovers(self):
        text=(ROOT/'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        bodies='\n'.join(method(text,s) for s in (
            '    @Override public boolean canAcceptEndpoint()',
            '    @Override public void expectEndpoint(long sequence, long timestampNs)'))
        source='''
import java.util.*;
public class CapacityTest {
 static final int MAX_IMAGES=8;
 static class ExpectedEndpoint {ExpectedEndpoint(long s,long t){}}
 ArrayDeque<ExpectedEndpoint> expected=new ArrayDeque<>();
 Map<Long,Object> retained=new HashMap<>();
 long lastExpectedSequence,lastExpectedTimestampNs;boolean closed,wrongOwner;
 Object reader=new Object();int drains;boolean drainFailure;
 void onImageAvailable(Object r){drains++;if(drainFailure)closed=true;}
 void requireOwner(){if(wrongOwner)throw new IllegalStateException();}
 void requireOpen(){if(closed)throw new IllegalStateException();}
 BODIES
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] a){
   CapacityTest failed=new CapacityTest();failed.drainFailure=true;
   try{failed.canAcceptEndpoint();throw new AssertionError();}catch(IllegalStateException ok){}
   check(failed.drains==1);
   for(int retainedCount=0;retainedCount<=8;retainedCount++){
     CapacityTest t=new CapacityTest();
     for(int i=0;i<retainedCount;i++)t.retained.put((long)i,new Object());
     long seq=1;
     while(t.canAcceptEndpoint()){t.expectEndpoint(seq,seq*1000);seq++;}
     check(t.expected.size()+t.retained.size()==8&&t.drains>0);
     long before=t.lastExpectedSequence;
     try{t.expectEndpoint(seq,seq*1000);throw new AssertionError();}catch(IllegalStateException ok){}
     check(t.lastExpectedSequence==before);
     if(!t.expected.isEmpty())t.expected.removeFirst();else t.retained.remove(0L);
     check(t.canAcceptEndpoint());t.expectEndpoint(seq,seq*1000);check(!t.canAcceptEndpoint());
     t.closed=true;try{t.canAcceptEndpoint();throw new AssertionError();}catch(IllegalStateException ok){}
     t.closed=false;t.wrongOwner=true;try{t.canAcceptEndpoint();throw new AssertionError();}catch(IllegalStateException ok){}
   }
 }
}
'''.replace(' BODIES',bodies)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'CapacityTest.java';p.write_text(source)
            subprocess.run([str(JAVA/'javac'),str(p)],check=True,capture_output=True)
            subprocess.run([str(JAVA/'java'),'-cp',d,'CapacityTest'],check=True,capture_output=True)
