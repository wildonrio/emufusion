"""Compile Cemu's actual size heuristic, not a duplicate implementation.

Checks allocation sizing only; physical rendering needs separate device evidence.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def sizing_block():
    lock = json.loads((ROOT / "engines/cemu-source-lock.json").read_text())
    source = (Path(lock["core"]["stagedTree"]) /
              "src/Cafe/HW/Latte/Core/LatteRenderTarget.cpp").read_text()
    method = source.index("LatteTextureView* LatteMRT::GetColorAttachmentTexture(")
    start = source.index("if(LatteGPUState.allowFramebufferSizeOptimization)", method)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class CemuColorAttachmentHeightTest(unittest.TestCase):
    def test_real_heuristic_preserves_partial_scissor_allocations(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        harness = r'''
#include <cstdint>
#include <cstdio>
using uint32 = uint32_t;
struct Scissor { uint32 x,y; uint32 get_BR_X(){return x;} uint32 get_BR_Y(){return y;} };
struct { bool allowFramebufferSizeOptimization;
 struct { Scissor PA_SC_GENERIC_SCISSOR_BR; } contextNew;
} LatteGPUState;
struct Size { uint32 w,h; };
Size actual(uint32 colorBufferWidth,uint32 colorBufferHeight) {
''' + sizing_block() + r'''
return {colorBufferWidth,colorBufferHeight};
}
int main() {
 struct Case { const char* name; uint32 w,h,x,y,ew,eh; bool enabled; } cases[] = {
  {"full TV",1920,1088,1920,1080,1920,1080,true},
  {"NES Remix partial TV",1920,1088,1556,1042,1920,1088,true},
  {"full Pad",864,480,854,480,864,480,true},
  {"compatible Pad padding",864,480,692,463,864,463,true},
  {"empty scissor",1920,1088,1920,0,1920,1088,true},
  {"oversized scissor",1920,1088,1920,2000,1920,1088,true},
  {"full 720p",1280,736,1280,720,1280,720,true},
  {"partial 720p",1280,736,640,360,1280,736,true},
  {"optimization disabled",1920,1088,1920,1080,1920,1088,false},
  {"unpadded buffer",1920,1080,1920,1070,1920,1080,true}
 };
 int failed=0;
 for(auto c:cases) {
  LatteGPUState={c.enabled,{{c.x,c.y}}};
  auto s=actual(c.w,c.h);
  if(s.w!=c.ew||s.h!=c.eh) {
   ++failed; printf("FAIL %s: got %ux%u, expected %ux%u\n",c.name,s.w,s.h,c.ew,c.eh);
  }
 }
 printf("10 sizing cases, %d failures\n",failed);
 return failed?1:0;
}
'''
        with tempfile.TemporaryDirectory(prefix="cemu-color-height-") as directory:
            source = Path(directory) / "test.cpp"
            binary = Path(directory) / "test"
            source.write_text(harness)
            subprocess.run([compiler, "-std=c++20", "-O1", "-g",
                            "-fsanitize=address,undefined", str(source), "-o", str(binary)],
                           check=True, capture_output=True, text=True, timeout=60)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
