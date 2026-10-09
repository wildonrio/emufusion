"""Execute the real shell preflight against both actual receipt validators."""
import importlib.util
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'engines/tools/armsx2_build_identity.py'
SPEC = importlib.util.spec_from_file_location('candidate_identity', TOOL)
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)
STAGE_SPEC = importlib.util.spec_from_file_location('stage_candidate',
    ROOT / 'unified-android/tools/stage_ps2_candidate_registry.py')
staging = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(staging)


class Ps2CandidateInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='emufusion-ps2-inputs-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'engines/tools').mkdir(parents=True)
        shutil.copyfile(TOOL, self.root / 'engines/tools/armsx2_build_identity.py')
        self.patch = self.root / 'patch.cpp'
        self.patch.write_text('current PS2 source')
        (self.root / 'engines/build_core.sh').write_text('recipe')
        (self.root / 'engines/armsx2-source-lock.json').write_text(json.dumps(dict(core=dict(commit='pinned'),
            patches=[dict(path='patch.cpp', sha256=identity.sha256(self.patch))])))
        self.cores = self.root / 'candidate pair'
        self.cores.mkdir()
        for name, pages in [('armsx2_libretro.so', 4096), ('armsx2_16k_libretro.so', 16384)]:
            core = self.cores / name
            core.write_bytes(str(pages).encode())
            snapshot = dict(sourceInputs=identity.source_inputs(self.root), hostPageSize=pages,
                            recipeSha256=identity.sha256(self.root / 'engines/build_core.sh'))
            identity.receipt_path(core).write_text(json.dumps(
                identity.make_receipt(self.root, core, pages, snapshot)))
        build = (ROOT / 'unified-android/build.sh').read_text()
        self.script = build.split('# BEGIN PS2 qualification input preflight\n')[1].split(
            '# END PS2 qualification input preflight')[0]
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('LUCENT_')}
        self.env.update(ROOT_DIR=str(self.root), ARMSX2_CORE_DIR=str(self.cores),
                        LUCENT_ARMSX2_QUALIFICATION_DIR=str(self.cores),
                        INCLUDE_PHASE2_PPSSPP='1', REUSE_PHASE2_PPSSPP='1')

    def run_preflight(self, **changes):
        return subprocess.run(['/bin/sh', '-eu', '-c', self.script],
                              env=dict(self.env, **changes), capture_output=True,
                              text=True, timeout=10)

    def test_verified_pair_with_spaces_passes(self):
        self.assertEqual(self.run_preflight().returncode, 0)

    def test_rejects_release_unknown_signing_and_nonreuse(self):
        for change in [dict(LUCENT_SIGNING_PROFILE='release'),
                       dict(LUCENT_SIGNING_PROFILE='typo'),
                       dict(REUSE_PHASE2_PPSSPP='0'), dict(INCLUDE_PHASE2_PPSSPP='0')]:
            with self.subTest(change=change):
                result = self.run_preflight(**change)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('require debug signing', result.stderr)

    def test_relative_directory_rejected(self):
        self.assertIn('must be absolute', self.run_preflight(ARMSX2_CORE_DIR='relative').stderr)

    def test_missing_second_receipt_rejected(self):
        identity.receipt_path(self.cores / 'armsx2_16k_libretro.so').unlink()
        self.assertNotEqual(self.run_preflight().returncode, 0)

    def test_changed_binary_rejected(self):
        (self.cores / 'armsx2_libretro.so').write_bytes(b'wrong binary')
        self.assertNotEqual(self.run_preflight().returncode, 0)

    def test_page_variants_cannot_be_swapped(self):
        one = identity.receipt_path(self.cores / 'armsx2_libretro.so')
        two = identity.receipt_path(self.cores / 'armsx2_16k_libretro.so')
        a, b = one.read_bytes(), two.read_bytes()
        one.write_bytes(b); two.write_bytes(a)
        self.assertNotEqual(self.run_preflight().returncode, 0)

    def test_changed_source_rejected(self):
        self.patch.write_text('unbuilt source change')
        self.assertNotEqual(self.run_preflight().returncode, 0)

    def test_default_reuse_still_checks_identity(self):
        (self.cores / 'armsx2_libretro.so').write_bytes(b'stale default staging')
        self.assertNotEqual(self.run_preflight(LUCENT_ARMSX2_QUALIFICATION_DIR='').returncode, 0)

    def test_preflight_precedes_dependencies_and_packing_uses_selected_directory(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        self.assertLess(build.index('# BEGIN PS2 qualification input preflight'),
                        build.index('fetch_dependency()'))
        self.assertIn('cp "$ARMSX2_CORE_DIR/armsx2_16k_libretro.so"', build)
        packing = build.split('PHASE2_STAGED_CORE_COUNT=0')[1]
        self.assertIn('if [ "$phase2_core" = armsx2 ]; then phase2_input_dir="$ARMSX2_CORE_DIR"; fi', packing)

    def decoded_fixture(self):
        decoded = self.root / 'decoded'
        (decoded / 'assets').mkdir(parents=True)
        libs = decoded / 'lib/arm64-v8a'
        libs.mkdir(parents=True)
        for name in ('armsx2', 'armsx2_16k'):
            shutil.copyfile(self.cores / (name + '_libretro.so'), libs / ('liblucent_core_' + name + '.so'))
        registry = dict(engines=[dict(id='other', preserved='untouched'), dict(id='armsx2',
            source=dict(commit='pinned'), shipped=False, gates=dict(runtime=False, distribution=False),
            build=dict(recipe='same recipe', proofArtifactSha256='old', proofArtifactPath='old', reproducible=False))])
        target = decoded / 'assets/phase2-engine-registry.json'
        target.write_text(json.dumps(registry))
        return decoded, target, registry

    def test_candidate_registry_only_changes_build_attribution(self):
        decoded, target, original = self.decoded_fixture()
        staging.stage(self.root, self.cores, decoded)
        actual = json.loads(target.read_text())
        expected = copy.deepcopy(original)
        expected['engines'][1]['build'] = actual['engines'][1]['build']
        self.assertEqual(actual, expected)
        self.assertEqual(actual['engines'][1]['build']['proofArtifactSha256'],
                         identity.sha256(self.cores / 'armsx2_libretro.so'))
        self.assertFalse(actual['engines'][1]['build']['reproducible'])

    def test_registry_rejects_unverified_packaged_bytes_without_mutating(self):
        decoded, target, original = self.decoded_fixture()
        (decoded / 'lib/arm64-v8a/liblucent_core_armsx2_16k.so').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'packaged bytes'):
            staging.stage(self.root, self.cores, decoded)
        self.assertEqual(json.loads(target.read_text()), original)

    def test_registry_rejects_wrong_commit_or_shipped_flag(self):
        decoded, target, original = self.decoded_fixture()
        for field in ('commit', 'shipped'):
            changed = copy.deepcopy(original)
            if field == 'commit': changed['engines'][1]['source']['commit'] = 'wrong'
            else: changed['engines'][1]['shipped'] = True
            target.write_text(json.dumps(changed))
            with self.assertRaises(ValueError): staging.stage(self.root, self.cores, decoded)
            self.assertEqual(json.loads(target.read_text()), changed)


if __name__ == '__main__':
    unittest.main()
