"""Source-order regression; not a substitute for device in-flight teardown QA."""
from pathlib import Path
import unittest


class TeardownOrderTest(unittest.TestCase):
    def test_bound_outputs_are_identity_scoped(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        self.assertIn('boundAppOwnedOutputs.size() >= 6',source)
        self.assertIn('boundAppOwnedOutputs.get(output.proofSequence) != output',source)
        self.assertIn('for (AppOwnedOutput appOutput : boundAppOwnedOutputs.values())',source)
        bind=source.split('@Override public AppOwnedOutput bindAppOwnedOutput(',1)[1].split('@Override public void releaseAppOwnedOutput',1)[0]
        self.assertLess(bind.index('boundTextureIds.containsValue(textureId)'),bind.index('current.jobBridge.bindPreparedHardwareBufferRifeOutput'))
        close=source.split('@Override public void close() {',1)[1]
        self.assertIn('while (bound.hasNext())',close)
        self.assertLess(close.index('boundOutputBridges.get(output.proofSequence).releaseBoundHardwareBufferRifeOutput'),close.index('bound.remove()'))
        self.assertIn('secondaryBridge.closePresentationSurface()',close)
        self.assertLess(close.index('secondaryBridge.close()'),close.index('endpoint.image.close()'))

    def test_gpu_drain_precedes_image_recycling(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        close=source.split('@Override public void close() {',1)[1].split('private static final class ExpectedEndpoint',1)[0]
        timeout=close.index('if (!preparationStopped) {')
        drain=close.index('bridge.closePresentationSurface()')
        confirmed=close.index('teardown.getBoolean("closed")')
        native_close=close.index('prepared.close()')
        recycle=close.index('endpoint.image.close()')
        self.assertLess(timeout,drain)
        self.assertIn('throw new IllegalStateException',close[timeout:drain])
        self.assertLess(drain,confirmed)
        self.assertLess(confirmed,native_close)
        self.assertLess(native_close,recycle)
        self.assertLess(recycle,close.index('reader.close()'))
        self.assertIn('if (teardownComplete) return;',close)
        self.assertNotIn('if (closed) return;',close)
        self.assertLess(close.index('reader.close()'),close.index('teardownComplete = true'))


if __name__=='__main__': unittest.main()
