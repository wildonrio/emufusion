"""Secondary startup ownership contracts, not a physical-device qualification."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SecondaryRendererRetirementTest(unittest.TestCase):
    def test_same_generation_quarantine_precedes_direct_policy_and_factory(self):
        source = (ROOT / "android-companion/src/com/thorium/preview/PreviewActivity.java").read_text()
        ensure = source.split(
            "private void ensureGameplayGenerator(Surface output, int inputWidth, int inputHeight,", 1
        )[1].split("private void quarantineGameplayGenerator", 1)[0]
        guard = ensure.index("gameplayQuarantinedGeneration == gameplayGeneration")
        self.assertLess(guard, ensure.index("selectBackendForSession"))
        self.assertLess(guard, ensure.index("FrameGenerationRendererFactory.create"))
        catch = ensure.split("catch (RuntimeException failure)", 1)[1]
        self.assertLess(catch.index("partial.close()"), catch.index("SurfaceOwnershipException.isUnsafe"))
        self.assertIn("failure.addSuppressed(new SurfaceOwnershipException", catch)
        unsafe = catch.split("if (SurfaceOwnershipException.isUnsafe(failure))", 1)[1].split(
            "Log.e(", 1)[0]
        self.assertIn("quarantineGameplayGenerator(gameplayGeneration, failure);", unsafe)
        self.assertIn("return;", unsafe)
        self.assertNotIn("gameplayEngineSurface = output", unsafe)

    def test_quarantine_clears_handoff_and_notifies_only_its_own_generation(self):
        source = (ROOT / "android-companion/src/com/thorium/preview/PreviewActivity.java").read_text()
        quarantine = source.split("private void quarantineGameplayGenerator(", 1)[1].split(
            "private void releaseGameplayGenerator(", 1)[0]
        self.assertIn("gameplayEngineSurface = null;", quarantine)
        self.assertIn("gameplayQuarantinedGeneration = failedGeneration;", quarantine)
        self.assertIn("if (firstFailure)", quarantine)
        self.assertIn("surfaceFailed(failedGeneration, failure)", quarantine)
        release = source.split("private void releaseGameplayGenerator()", 1)[1].split(
            "private float displayRefreshRate()", 1)[0]
        self.assertIn("long retiringGeneration = gameplayGeneratorGeneration;", release)
        self.assertIn("quarantineGameplayGenerator(retiringGeneration,", release)
        self.assertLess(release.index("gameplayEngineSurface = null"), release.index("generator.close()"))

    def test_router_cannot_deliver_null_or_invalid_surface_after_rejection(self):
        source = (ROOT / "android-companion/src/com/thorium/preview/SecondaryGameplaySurfaceRouter.java").read_text()
        available = source.split("static synchronized void surfaceAvailable(", 1)[1].split(
            "static void surfaceFailed(", 1)[0]
        self.assertIn("matched && surface != null && surface.isValid()", available)
        failed = source.split("static void surfaceFailed(", 1)[1].split(
            "static synchronized void surfaceDestroyed(", 1)[0]
        self.assertIn("target = generation == candidate ? listener : null;", failed)
        self.assertIn("}\n        if (target != null) target.onSecondarySurfaceError(failure);", failed)

    def test_every_secondary_engine_reports_error_to_existing_fatal_ui(self):
        for name in ("NativeAdapterEngineSession", "LibretroEngineSession", "PpssppGlesEngineSession"):
            source = (ROOT / "unified-android/src/com/thorium/preview/game" / (name + ".java")).read_text()
            error = source.split("public void onSecondarySurfaceError(Throwable failure)", 1)[1].split(
                "@Override public void onSecondaryTouch", 1)[0]
            self.assertIn("secondarySurface = null;", error, name)
            self.assertIn("callback.onSessionError(", error, name)
            self.assertIn("failure);", error, name)


if __name__ == "__main__":
    unittest.main()
