"""Exercise actual LSFG cache-import scheduling, with controlled worker/owner queues.

No device throughput, GPU completion or interpolation quality is simulated here.
"""
import unittest

from tools.tests import test_lsfg_endpoint_lifetime as lifetime_support
from tools.tests.test_lsfg_endpoint_lifetime import TRANSPORT, method


def fixture():
    source = TRANSPORT.read_text()
    methods = "\n".join(method(source, signature) for signature in (
        "private void scheduleEndpointPreparation()",
        "private boolean hasPreparedPresentationWindow()",
        "private void finishEndpointPreparation(",
        "@Override public boolean visibleSubmissionReady()",
        "@Override public boolean hasAdjacentPair(",
        "@Override public boolean hasPreparedLookahead(",
        "private static final class AdmissionDiagnostics",
    ))
    return r'''
import java.util.*;
public class EndpointTest {
    long nativeHandle=7;
    boolean generatedRatePathActive,closed,preparationInFlight,wrongOwner;
    RuntimeException fatalFailure;
    int retireCalls,retryCalls;
    enum EnqueueResult {NOT_READY}
    final AdmissionDiagnostics admission=new AdmissionDiagnostics();
    final LinkedHashMap<Long,RetainedEndpoint> retained=new LinkedHashMap<>();
    final WorkQueue preparationWorker=new WorkQueue(),owner=new WorkQueue();
    static class WorkQueue {
        final ArrayDeque<Runnable> work=new ArrayDeque<>();
        void execute(Runnable r){work.add(r);}
        void post(Runnable r){work.add(r);}
        void one(){check(!work.isEmpty(),"expected queued work");work.remove().run();}
    }
    static class RetainedEndpoint {
        final long sequence,buffer;
        boolean prepared,preparing,discardRequested;
        RetainedEndpoint(long s,boolean ready){sequence=s;buffer=s;prepared=ready;}
    }
    static class NativeLsfgBridge {
        static final List<Long> imports=new ArrayList<>();
        static boolean fail;
        static void prepareEndpoint(long handle,long buffer){
            check(handle==7,"wrong native handle");imports.add(buffer);
            if(fail)throw new IllegalStateException("injected import failure");
        }
    }
    static class android {static class util {static class Log {
        static void i(String tag,String value){}
    }}}
    void requireOwner(){if(wrongOwner)throw new IllegalStateException("foreign owner");}
    void requireOpen(){if(closed||fatalFailure!=null)throw new IllegalStateException("unavailable");}
    void retireDiscardedEndpoints(){++retireCalls;}
    void retryAnnouncedRealPair(){++retryCalls;}
    static void check(boolean b,String why){if(!b)throw new AssertionError(why);}
    RetainedEndpoint add(long s,boolean ready){
        RetainedEndpoint e=new RetainedEndpoint(s,ready);retained.put(s,e);return e;
    }
    void finishOne(){preparationWorker.one();owner.one();}
''' + methods + r'''
    public static void main(String[] args){
        EndpointTest t=new EndpointTest();String mode=args[0];
        if(mode.equals("window_gaps")){
            t.add(1,true);t.add(3,true);t.add(4,true);
            check(!t.hasPreparedPresentationWindow(),"gap must not fill lookahead");
            RetainedEndpoint e=t.add(5,true);
            check(t.hasPreparedPresentationWindow(),"three adjacent imports ready");
            e.discardRequested=true;
            check(!t.hasPreparedPresentationWindow(),"discarded image is not lookahead");
            return;
        }
        RetainedEndpoint a=t.add(1,true),b=t.add(2,true),c=t.add(3,false),d=t.add(4,false);
        t.generatedRatePathActive=mode.equals("generated");
        if(mode.equals("closed"))t.closed=true;
        if(mode.equals("fatal"))t.fatalFailure=new IllegalStateException("existing failure");
        if(mode.equals("inflight"))t.preparationInFlight=true;
        if(mode.equals("closed")||mode.equals("fatal")||mode.equals("inflight")){
            t.scheduleEndpointPreparation();
            check(t.preparationWorker.work.isEmpty(),"guard must prevent new import");return;
        }
        if(mode.equals("discard"))c.discardRequested=true;
        if(mode.equals("foreign")){
            t.wrongOwner=true;
            try{t.scheduleEndpointPreparation();throw new AssertionError("foreign owner accepted");}
            catch(IllegalStateException expected){}
            check(t.preparationWorker.work.isEmpty(),"foreign owner queued work");return;
        }
        t.scheduleEndpointPreparation();
        check(t.preparationWorker.work.size()==1,"prepared A/B must not block importing successor C");
        check(t.preparationInFlight,"one import must own worker lease");
        check(!t.visibleSubmissionReady(),"native mutex exclusion must remain");
        check(t.hasAdjacentPair(1,2),"lookahead import cannot erase prepared A/B");
        check(!t.hasPreparedLookahead(2),"uncompleted C is not ready");
        t.scheduleEndpointPreparation();
        check(t.preparationWorker.work.size()==1,"one in-flight import maximum");
        if(mode.equals("failure"))NativeLsfgBridge.fail=true;
        if(mode.equals("identity"))t.retained.put(3L,new RetainedEndpoint(3,false));
        if(mode.equals("closing"))t.closed=true;
        t.finishOne();
        if(mode.equals("failure")||mode.equals("identity")){
            check(t.fatalFailure!=null,"failed/changed import must latch failure");
            check(!c.prepared,"failed image cannot become prepared");
            check(t.retryCalls==0&&t.preparationWorker.work.isEmpty(),"failure must not publish or continue");
            return;
        }
        if(mode.equals("closing")){
            check(!c.prepared&&t.retryCalls==0,"close must not publish import");return;
        }
        if(mode.equals("discard")){
            check(NativeLsfgBridge.imports.equals(Arrays.asList(4L)),"discarded C must not import");return;
        }
        check(NativeLsfgBridge.imports.equals(Arrays.asList(3L)),"exact successor imported");
        check(c.prepared&&t.hasPreparedLookahead(2),"C must be ready before A retires");
        check(t.retained.get(1L)==a&&a.prepared&&b.prepared,"active pair must survive");
        check(t.visibleSubmissionReady(),"owner completion releases mutex exclusion");
        check(t.preparationWorker.work.isEmpty()&&!d.preparing,"stop at three, not whole FIFO");
        check(t.retireCalls==1&&t.retryCalls==1,"normal completion hooks preserved");
        t.retained.remove(1L);t.scheduleEndpointPreparation();t.finishOne();
        check(NativeLsfgBridge.imports.equals(Arrays.asList(3L,4L)),"advance replenishes one successor");
        check(t.preparationWorker.work.isEmpty(),"bounded replenishment");
    }
}
'''


class ImportLookaheadTest(unittest.TestCase):
    compile_run = lifetime_support.LsfgEndpointLifetimeTest.compile_run

    def test_actual_import_and_completion_boundaries(self):
        self.compile_run(fixture(), [(name,) for name in (
            "direct", "generated", "window_gaps", "closed", "fatal", "inflight",
            "discard", "foreign", "failure", "identity", "closing",
        )])


if __name__ == "__main__":
    unittest.main()
