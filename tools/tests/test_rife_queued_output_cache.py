"""Exercise the production pre-worker queued-output check; no GPU acceptance."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java'


class QueuedOutputCacheTest(unittest.TestCase):
    def test_completed_earlier_pair_is_cached_before_future_worker(self):
        source = SOURCE.read_text()
        body = method(source, 'private void cacheQueuedOutputBeforePreparation()')
        swap = method(source, 'private void swapPreparations()')
        start = method(source, 'private PreparationResult startPreparation(')
        self.assertLess(start.index('cacheQueuedOutputBeforePreparation();'),
                        start.index('availablePreparationBridge()'))
        self.assertLess(start.index('cacheQueuedOutputBeforePreparation();'),
                        start.index('preparationInFlight = true;'))
        harness = '''
public class QueuedProbe {
    static class PreparedPresentation {
        boolean ready;
        PreparedPresentation(boolean value) { ready=value; }
    }
    boolean appOwnedPresentation=true, preparationInFlight, failPoll;
    PreparedPresentation preparedPresentation, queuedPreparation, cached;
    int polls;
    void pollPreparedPresentation() {
        check(!preparationInFlight, "native access while worker busy");
        polls++;
        if(failPoll) throw new IllegalStateException("completion failure");
        if(preparedPresentation.ready) {
            cached=preparedPresentation;
            preparedPresentation=null;
        }
    }
    BODY
    SWAP
    static void check(boolean ok,String why) { if(!ok)throw new AssertionError(why); }
    public static void main(String[] args) {
        QueuedProbe p=new QueuedProbe();
        PreparedPresentation due=new PreparedPresentation(true);
        p.queuedPreparation=due;
        p.cacheQueuedOutputBeforePreparation();
        check(p.cached==due && p.queuedPreparation==null && p.preparedPresentation==null,
              "finished earlier pair must remain bindable from cache");
        PreparedPresentation pending=new PreparedPresentation(false);
        p.queuedPreparation=pending; p.cached=null;
        p.cacheQueuedOutputBeforePreparation();
        check(p.queuedPreparation==pending && p.preparedPresentation==null && p.cached==null,
              "pending earlier pair retains native ownership");
        int count=p.polls;
        p.preparationInFlight=true; p.cacheQueuedOutputBeforePreparation();
        check(p.polls==count && p.queuedPreparation==pending,"busy worker not touched");
        p.preparationInFlight=false; p.appOwnedPresentation=false;
        p.cacheQueuedOutputBeforePreparation(); check(p.polls==count,"non-EGL path unchanged");
        p.appOwnedPresentation=true; p.preparedPresentation=due;
        p.cacheQueuedOutputBeforePreparation();
        check(p.polls==count && p.preparedPresentation==due,"current slot never displaced");
        p.preparedPresentation=null; p.failPoll=true;
        try { p.cacheQueuedOutputBeforePreparation(); throw new AssertionError("failure swallowed"); }
        catch(IllegalStateException expected) {}
        check(p.queuedPreparation==pending && p.preparedPresentation==null,
              "failure restores orientation without losing work");
        p.queuedPreparation=null; p.failPoll=false; count=p.polls;
        p.cacheQueuedOutputBeforePreparation(); check(p.polls==count,"empty queue no-op");
    }
}
'''.replace('    BODY', body).replace('    SWAP', swap)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'QueuedProbe.java'
            unit.write_text(harness)
            for command in ([str(JAVA / 'javac'), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'QueuedProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
