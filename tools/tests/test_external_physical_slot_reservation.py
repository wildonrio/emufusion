"""Execute renderer slot admission/epoch-anchor code against the real planner.

The captured aa09 values are request identities, not simulated proof of physical
display. Android/GPU work remains outside this bounded host regression.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_native_source_image_renderer_wiring import method

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
VIDEO = ROOT / "unified-android/src/com/thorium/lucent/video"
FIXTURE = Path(__file__).with_name("fixtures") / "external_physical_slot_reservation.java.in"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


class ExternalPhysicalSlotReservationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        submission = method(source, "private void presentExternalBuffered(")
        poll = method(source, "private void pollPhysicalPresentations()")
        anchor = method(poll, "if (physicalEpochChanged)")
        stale = method(poll, "if (!externalPhysicalClock.record(")
        bootstrap = method(poll, "if (externalPhysicalClockBootstrap.ready(")
        helpers = "\n".join(method(source, signature) for signature in (
            "private boolean externalPhysicalSlotAvailable(",
            "private void recordExternalPhysicalSlot(",
            "private void consumeExternalPresentationDiscontinuities()"))
        fixture = FIXTURE.read_text().replace("@SUBMISSION@", submission)
        fixture = fixture.replace("@ANCHOR@", anchor)
        fixture = fixture.replace("@STALE@", stale).replace("@BOOTSTRAP@", bootstrap)
        fixture = fixture.replace("@HELPERS@", helpers)
        cls.temporary = tempfile.TemporaryDirectory(prefix="external-slot-reservation-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        unit = cls.directory / "SlotReservationFixture.java"
        unit.write_text(fixture)
        sources = [unit] + [VIDEO / (name + ".java") for name in (
            "PhysicalPresentationDeadline", "CompositorFrameTimeline",
            "FrameGenerationPresentationRequest", "ExternalPresentationLedger")]
        result = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d",
                                 str(cls.directory), *map(str, sources)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def case(self, name):
        result = subprocess.run([str(JAVA / "java"), "-ea", "-cp", str(self.directory),
                                 "SlotReservationFixture", name],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + name, result.stdout)

    def test_pending_tail_survives_actual_epoch_anchor_and_phase_retunes(self):
        self.case("anchor")

    def test_different_tokens_cannot_reserve_the_same_physical_scan(self):
        self.case("duplicate")

    def test_expiry_failure_and_deferral_do_not_advance_reservations(self):
        self.case("failure")

    def test_discontinuity_stale_clock_and_bootstrap_keep_owned_reservations(self):
        self.case("resets")

    def test_expected_scan_has_its_own_separation_guard_and_no_timeline_is_supported(self):
        self.case("domains")


if __name__ == "__main__":
    unittest.main(verbosity=2)
