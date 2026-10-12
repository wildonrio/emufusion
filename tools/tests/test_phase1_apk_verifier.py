import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "phase1_apk_verifier",
    ROOT / "unified-android" / "tools" / "verify_phase1_apk.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Phase1ApkVerifierTest(unittest.TestCase):
    def build_apk(self, path: Path, corrupt: Optional[str] = None):
        engine_id = "mesen"
        commit = "0" * 40
        archive_sha = "1" * 64
        core = b"core"
        core_sha = hashlib.sha256(core).hexdigest()
        library = "libemufusion_core_mesen.so"
        registry = {"engines": [{
            "id": engine_id, "phase": 1, "shipped": False,
            "source": {"commit": commit, "archiveSha256": archive_sha},
        }]}
        opt_in = {"qualificationOnly": True, "engines": [{
            "id": engine_id, "commit": commit, "libraryName": library,
        }]}
        artifacts = {"artifacts": [{
            "engineId": engine_id, "fileName": library, "sha256": core_sha,
            "sourceCommit": commit, "sourceArchiveSha256": archive_sha,
        }]}
        sbom = {"packages": [{
            "SPDXID": "SPDXRef-Package-mesen",
            "checksums": [{"algorithm": "SHA256", "checksumValue": archive_sha}],
        }]}
        if corrupt == "hash":
            artifacts["artifacts"][0]["sha256"] = "2" * 64
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(MODULE.REGISTRY, json.dumps(registry))
            archive.writestr(MODULE.OPT_IN, json.dumps(opt_in))
            archive.writestr(MODULE.ARTIFACTS, json.dumps(artifacts))
            archive.writestr(MODULE.SBOM, json.dumps(sbom))
            archive.writestr(MODULE.NOTICES, "Engine id: mesen\n")
            archive.writestr(f"lib/arm64-v8a/{library}", core)

    def test_accepts_complete_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / "ok.apk"
            self.build_apk(apk)
            self.assertEqual([], MODULE.verify(apk))

    def test_rejects_binary_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / "bad.apk"
            self.build_apk(apk, "hash")
            self.assertTrue(any("hash differs" in error for error in MODULE.verify(apk)))

    def test_rejects_missing_compliance_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / "missing.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr(MODULE.REGISTRY, "{}")
            errors = MODULE.verify(apk)
            self.assertTrue(any("missing Phase 1" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
