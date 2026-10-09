"""Guard the launch wiring around the executing directory-selection tests."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"


class NativeQaStorageWiringTest(unittest.TestCase):
    def test_audited_native_requires_explicit_namespace_and_approved_route(self):
        host = (GAME / "InWindowGameHost.java").read_text()
        section = host[host.index('String qualificationSession = "";'):]
        self.assertLess(section.index("if (qualificationOnly)"), section.index("boolean nativeNamespace"))
        self.assertIn('boolean nativeNamespace = approvedPhaseThree &&', section)
        self.assertIn('NativeQualificationStorage.supports(engine, system)', section)
        self.assertIn("!phaseOneNamespace && !nativeNamespace", section)
        self.assertIn("!QUALIFICATION_SESSION.matcher(candidate).matches()", section)

    def test_software_save_isolation_does_not_require_frame_generation(self):
        host = (GAME / "InWindowGameHost.java").read_text()
        section = host[host.index('String qualificationSession = "";'):]
        section = section[:section.index('FrameGenerationSettings.Mode launchMode')]
        self.assertIn('boolean phaseOneNamespace = approvedPhaseOne;', section)
        self.assertNotIn('FrameGenerationSettings', section)
        self.assertIn('if (qualificationOnly)', section)
        self.assertIn('qualification_session")).isEmpty()', section)
        # The chosen backend still comes from the user's mode, not the QA flag.
        self.assertIn('FrameGenerationSettings.mode(activity);', host)

    def test_same_namespace_reaches_preopen_guest_root_and_snapshot_root(self):
        session = (GAME / "NativeAdapterEngineSession.java").read_text()
        self.assertIn("NativeAdapterSystemDirectory.saveDirectoryName(request.qualificationSession)", session)
        self.assertIn("entry.id, request.systemId, request.qualificationSession);", session)
        # resolve() also receives the opened content so decrypted Wii U
        # images can skip disc-key gating; the namespace is unchanged.
        self.assertIn("entry.id, request.systemId, capabilities.requiredFirmware,\n"
                      "                        request.qualificationSession, game);", session)
        self.assertLess(session.index("NativeAdapterSystemDirectory.prepareForOpen"),
                        session.index("new NativeAdapterHost(entry.coreFile, trusted)"))
        self.assertIn('NativeQualificationStorage.supports(', session)
        self.assertIn('NativeQualificationStorage.claimProcessRoot(', session)
        self.assertLess(session.index('NativeQualificationStorage.claimProcessRoot('),
                        session.index('saveDirectory = new File('))

    def test_production_overloads_preserved_and_qa_does_not_mark_normal_prerequisites(self):
        source = (GAME / "NativeAdapterSystemDirectory.java").read_text()
        self.assertIn('return prepareForOpen(context, engineId, systemId, "");', source)
        self.assertIn('return resolve(context, engineId, systemId, requiredFirmware, "");', source)
        resolve = source[source.index("int requiredFirmware, String qualificationSession)"):]
        resolve = resolve[:resolve.index("private static IllegalStateException unavailable")]
        # Three successful outcomes record readiness: an existing install, the
        # decrypted Wii U content path, and a fresh install. Each record must
        # be guarded so a QA namespace never marks normal prerequisites.
        guard = "if (qualificationSession == null || qualificationSession.isEmpty())"
        self.assertEqual(resolve.count("NativeAdapterPrerequisites.record("), 3)
        self.assertEqual(resolve.count(guard), 3)
        for before in resolve.split("NativeAdapterPrerequisites.record(")[:-1]:
            self.assertTrue(before.rstrip().endswith(guard),
                            "prerequisite record is not guarded by the QA namespace check")
        self.assertEqual(resolve.count("throw unavailable(context, systemId, qualificationSession);"), 2)


if __name__ == "__main__":
    unittest.main()
