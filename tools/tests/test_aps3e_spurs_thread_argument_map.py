"""Compile the actual SPU startup block, not a replacement lookup algorithm.

Tests cover all valid guest numbers and storage slots, permuted initialization,
and the no-group/non-SPURS/invalid-address paths under ASan/UBSan. This is a
localized host regression, not an Android game or ICO acceptance test.
"""
import os
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ('docs/qa/android-portability-2026-10-06-ps3-wide-pointer/'
                 'native-source/app/src/main/cpp/rpcs3/rpcs3/Emu/Cell')
PATCH = ROOT / 'engines/patches/aps3e-spurs-thread-argument-map.patch'
RELATIVE = Path('app/src/main/cpp/rpcs3/rpcs3/Emu/Cell/SPUThread.cpp')


def startup(source):
    start = source.index('\tconstexpr u32 invalid_spurs = 0u - 0x80;')
    return source[start:source.index('\n\tif (jit)', start)]


def harness(source):
    # Use the real declarations to make bounds/signed slot behavior meaningful.
    header = (SOURCE / 'lv2/sys_spu.h').read_text()
    declarations = [re.search(r'\bstd::array<[^;]+\b' + name + r';', header)[0]
                    for name in ('threads_map', 'args')]
    return '''#include <array>
#include <cstdint>
#include <cstdio>
#include <string>
using u32 = uint32_t; using u64 = uint64_t; using s8 = int8_t;
using namespace std::string_view_literals;
namespace vm { bool check_addr(u32 a) { return a >= 0x30000000 && a < 0x30010000; } }
struct Group {
''' + '\n'.join(declarations) + '''
  std::string name = "testCellSpursKernelGroup";
  unsigned spurs_running = 0;
};
u32 evaluate(Group* group, u32 index, u32 previous = 0) {
  u32 spurs_addr = previous;
''' + startup(source) + '''
  return spurs_addr;
}
int main(int argc, char**) {
  constexpr u32 invalid = 0u - 0x80;
  Group group;
  group.threads_map.fill(-1);
  for (unsigned n = 0; n < group.args.size(); ++n)
    group.args[n] = {11, 0x30000000 + n * 0x100, 33, 44};
  if (argc > 1) { // Original expression must fail bounds instrumentation here.
    group.threads_map[255] = 0;
    return evaluate(&group, 255) == 0x30000000 ? 0 : 9;
  }
  unsigned cases = 0;
  for (unsigned slot = 0; slot < group.args.size(); ++slot) {
    for (unsigned guest = 0; guest < group.threads_map.size(); ++guest) {
      group.threads_map.fill(-1);
      group.threads_map[guest] = static_cast<s8>(slot);
      const unsigned prior = group.spurs_running;
      if (evaluate(&group, guest) != group.args[slot][1]) return 2;
      if (group.spurs_running != prior + 1) return 3;
      ++cases;
    }
  }
  if (evaluate(nullptr, 255) != invalid) return 4;
  if (evaluate(nullptr, 255, 0x30000008) != 0x30000008) return 5;
  group.threads_map[255] = 0;
  group.name = "ordinary-group";
  const auto prior = group.spurs_running;
  if (evaluate(&group, 255) != invalid || group.spurs_running != prior) return 6;
  group.name = "testCellSpursKernelGroup";
  group.args[0][1] = 0;
  if (evaluate(&group, 255) != invalid || group.spurs_running != prior) return 7;
  std::printf("%u mapped startup cases and four branch controls passed\\n", cases);
}
'''


class SpursArgumentMapTest(unittest.TestCase):
    def test_normal_recipe_records_the_exact_patch_once(self):
        lock = json.loads((ROOT / 'engines/aps3e-source-lock.json').read_text())
        matches = [p for p in lock['patches'] if p['path'] == str(PATCH.relative_to(ROOT))]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['sha256'], hashlib.sha256(PATCH.read_bytes()).hexdigest())
        self.assertEqual(matches[0]['bytes'], PATCH.stat().st_size)
        self.assertEqual(matches[0]['upstreamCommit'], '9d020a3e5956134bd55d610082d82228bdfa0a96')

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='emufusion-spu-map-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.old = (SOURCE / 'SPUThread.cpp').read_text()
        target = cls.directory / RELATIVE
        target.parent.mkdir(parents=True)
        target.write_text(cls.old)
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)],
                       cwd=cls.directory, check=True, capture_output=True)
        cls.fixed = target.read_text()
        cls.programs = {}
        cls.env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:abort_on_error=0',
                       UBSAN_OPTIONS='halt_on_error=1')
        for label, source in (('old', cls.old), ('fixed', cls.fixed)):
            unit = cls.directory / (label + '.cpp')
            binary = cls.directory / label
            unit.write_text(harness(source))
            subprocess.run(['clang++', '-std=c++20', '-O1', '-g',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                str(unit), '-o', str(binary)], check=True, capture_output=True)
            cls.programs[label] = binary

    def run_case(self, label, *args):
        return subprocess.run([str(self.programs[label]), *args], env=self.env,
                              text=True, capture_output=True, timeout=15)

    def test_original_rejects_valid_non_identity_mapping(self):
        result = self.run_case('old')
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_original_out_of_bounds_is_reproduced(self):
        result = self.run_case('old', 'sparse')
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stderr, r'(out of bounds|AddressSanitizer|insufficient space for an object)')

    def test_fixed_all_256_numbers_in_each_of_eight_slots(self):
        result = self.run_case('fixed')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('2048 mapped startup cases and four branch controls passed', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_fixed_sparse_guest_number_has_no_sanitizer_error(self):
        result = self.run_case('fixed', 'sparse')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_only_the_upstream_lookup_changes(self):
        before = 'group->args[index][1]'
        after = 'group->args[group->threads_map[index]][1]'
        self.assertEqual(self.old.count(before), 1)
        self.assertEqual(self.old.replace(before, after), self.fixed)
        self.assertIn('9d020a3e5956134bd55d610082d82228bdfa0a96', PATCH.read_text())
        # This revision predates the other upstream hunk, so don't invent it.
        self.assertNotIn('notify_spus[', self.old)

    def test_real_initializer_defines_the_same_slot_mapping(self):
        source = (SOURCE / 'lv2/sys_spu.cpp').read_text()
        self.assertIn('group->threads_map[spu_num] = static_cast<s8>(inited);', source)
        self.assertIn('group->args[inited] = {args.arg1, args.arg2, args.arg3, args.arg4};', source)
        self.assertIn('group.get(), spu_num, thread_name, tid', source)
        self.assertIn('spu_num >= std::size(decltype(lv2_spu_group::threads_map){})', source)


if __name__ == '__main__':
    unittest.main()
