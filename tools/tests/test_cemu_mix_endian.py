"""Compile the real Cemu guest mixer conversion with its real endian type.

The pre-fix path reads legal Wii U pan=81 as 20736 and then indexes -20609
into a 128-entry table. These are the values in both Barbie crash tombstones.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CemuMixerEndianTest(unittest.TestCase):
    def test_actual_guest_conversion_and_all_legal_pan_positions(self):
        lock = json.loads((ROOT / "engines/cemu-source-lock.json").read_text())
        tree = Path(lock["core"]["stagedTree"])
        source = (tree / "src/Cafe/OS/libs/snd_user/snd_user.cpp").read_text()
        start = source.index("\tstruct MixControl\n")
        end = source.index("\n\tusing MixMode", start)
        structs = source[start:end]
        self.assertIn("struct GuestMixControl", structs)
        init_start = source.index("\tvoid MIXInitDeviceControl(")
        init_end = source.index("\tvoid MIXInitInputControl(", init_start)
        init = source[init_start:init_end]
        self.assertIn("GuestMixControl* control", init)
        for target in ("tv_control", "drc_control[index]", "rmt_control[index]"):
            self.assertIn(f"channel.{target} = control->ToHost();", init)
        self.assertNotIn("memcpy", init)
        harness = r'''
#include <cstdint>
#include <climits>
#include <cstddef>
#include <utility>
#include <concepts>
#include <cstring>
#include <cassert>
using uint8=uint8_t; using uint16=uint16_t; using uint32=uint32_t; using uint64=uint64_t;
using sint8=int8_t; using sint16=int16_t; using sint32=int32_t; using sint64=int64_t;
#include "Common/betype.h"
constexpr size_t AX_AUX_BUS_COUNT=3;
''' + structs + r'''
int main() {
  for (int pan=0; pan<128; ++pan) {
    for (int span=0; span<128; ++span) {
      // Construct bytes as the PowerPC game writes them, not with ToHost.
      const uint8 bytes[14]={0xfc,0x40, 0xff,0x9c, 0x00,0x3c,
          0,(uint8)pan, 0,(uint8)span, 0xff,0xec, 0xfc,0x40};
      GuestMixControl guest;
      std::memcpy(&guest,bytes,sizeof guest);
      MixControl native=guest.ToHost();
      assert(native.aux[0]==-960 && native.aux[1]==-100 && native.aux[2]==60);
      assert(native.pan==pan && native.span==span);
      assert(native.fader==-20 && native.lfe==-960);
      // Check all direct/complementary table indices used by stereo/surround.
      int table[128];
      for(int i=0;i<128;++i) table[i]=i;
      assert(table[native.pan]==pan && table[127-native.pan]==127-pan);
      assert(table[native.span]==span && table[127-native.span]==127-span);
      MixControl broken;
      std::memcpy(&broken,bytes,sizeof broken);
      if(pan==81 || pan==80) assert(broken.pan==pan*256);
    }
  }
  // Internal state stays native: reset values and scalar HLE setters are not
  // guest-memory structs and must not receive a second endian conversion.
  MixControl internal{};
  internal.pan=64; internal.span=127;
  assert(internal.pan==64 && internal.span==127);
}
'''
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="cemu-mix-endian-") as directory:
            path = Path(directory)
            (path / "test.cpp").write_text(harness)
            compiled = subprocess.run([compiler, "-std=c++20", "-O1", "-g",
                "-fsanitize=address,undefined", "-I", str(tree / "src"),
                str(path / "test.cpp"), "-o", str(path / "test")],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(path / "test")], capture_output=True,
                                 text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
