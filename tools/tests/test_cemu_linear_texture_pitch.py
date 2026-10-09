"""Exercise the actual texture-loader setup with authoritative guest row pitches.

The mocked AddrLib deliberately returns its *allocation* alignment, not the
guest descriptor's row pitch. This reproduces Barbie's 640 -> 768 chroma bug.
It is not a test of AddrLib or Vulkan themselves.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CemuLinearTexturePitchTest(unittest.TestCase):
    def test_actual_loader_honors_base_linear_pitch_and_tracking_extent(self):
        tree = Path(json.loads((ROOT / "engines/cemu-source-lock.json").read_text())
                    ["core"]["stagedTree"])
        source = Path(os.environ.get("CEMU_TEXTURE_LOADER_TEST_SOURCE", str(tree /
            "src/Cafe/HW/Latte/Core/LatteTextureLoader.cpp"))).read_text()
        begin = source.index("void LatteTextureLoader_begin(")
        end = source.index("\nuint8* LatteTextureLoader_GetInput", begin)
        harness = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <vector>
using uint8=uint8_t; using uint32=uint32_t; using uint64=uint64_t;
using sint32=int32_t; using MPTR=uint32;
#define cemu_assert_debug(x) assert(x)
namespace Latte {
enum class E_DIM {DIM_2D, DIM_3D};
enum class E_HWTILEMODE {TM_LINEAR_GENERAL=0, TM_LINEAR_ALIGNED=1, TILED=4};
enum class E_GX2SURFFMT {R8=8, RG8=16, RGBA8=32, BC1=64};
using E_GX2TILEMODE=E_HWTILEMODE;
bool IsCompressedFormat(E_GX2SURFFMT f){return f==E_GX2SURFFMT::BC1;}
uint32 GetFormatBits(E_GX2SURFFMT f){return uint32(f);}
bool TM_IsMacroTiled(E_HWTILEMODE m){return m==E_HWTILEMODE::TILED;}
E_HWTILEMODE MakeGX2TileMode(E_HWTILEMODE m){return m;}
}
namespace CafeSystem { uint64 title=0; uint64 GetForegroundTitleId(){return title;} }
namespace LatteAddrLib {
struct AddrSurfaceInfo_OUT {
 uint32 pitch=0,height=0,depth=0; uint64 surfSize=0;
 Latte::E_HWTILEMODE hwTileMode;
};
void GX2CalculateSurfaceInfo(Latte::E_GX2SURFFMT fmt,uint32 w,uint32 h,uint32 d,
 Latte::E_DIM,Latte::E_GX2TILEMODE mode,uint32,uint32 level,AddrSurfaceInfo_OUT* s){
 uint32 bpp=Latte::GetFormatBits(fmt);
 uint32 alignedPixels=std::max(64u,256*8/bpp);
 s->pitch=(std::max(1u,w>>level)+alignedPixels-1)/alignedPixels*alignedPixels;
 s->height=std::max(1u,h>>level);s->depth=d;s->hwTileMode=mode;
 s->surfSize=uint64(s->pitch)*s->height*d*bpp/8;
}
uint32 CalculateMipOffset(Latte::E_GX2SURFFMT,uint32,uint32,uint32,Latte::E_DIM,
 Latte::E_HWTILEMODE,uint32,uint32,uint32 level){return level*4096;}
}
struct LatteTextureLoaderCtx {
 uint32 physAddress,physMipAddress,sliceIndex,mipLevels,bpp,pipeSwizzle,bankSwizzle;
 Latte::E_HWTILEMODE tileMode;
 sint32 stepX,stepY,minOffsetOutdated,maxOffsetOutdated,width,height,pitch;
 uint32 surfaceInfoHeight,surfaceInfoDepth,levelOffset,computeAddrInfo;
 uint8* inputData;
};
std::vector<uint8> memory(8*1024*1024);
uint8* memory_getPointerFromPhysicalOffset(uint32 p){return memory.data()+p;}
template<typename... T> void SetupCachedSurfaceAddrInfo(T...){ }
''' + source[begin:end] + r'''
LatteTextureLoaderCtx load(uint32 width,uint32 height,uint32 pitch,
 Latte::E_GX2SURFFMT f=Latte::E_GX2SURFFMT::R8,
 Latte::E_HWTILEMODE tile=Latte::E_HWTILEMODE::TM_LINEAR_ALIGNED,
 uint32 mip=0,uint32 depth=1){
 LatteTextureLoaderCtx c{};
 LatteTextureLoader_begin(&c,0,mip,0,1024,f,Latte::E_DIM::DIM_2D,
  width,height,depth,5,pitch,tile,0);
 return c;
}
int main(){
 auto chroma=load(640,360,640);
 assert(chroma.pitch==640); // Original recalculates this as 768.
 assert(chroma.maxOffsetOutdated==640*360);
 // Row tags expose drift even when both decoder implementations share it.
 for(uint32 y=0;y<360;y++)std::fill_n(memory.data()+640*y,640,uint8(y));
 for(uint32 y=0;y<360;y++)assert(chroma.inputData[y*chroma.pitch]==uint8(y));
 auto luma=load(1280,720,1280);assert(luma.pitch==1280);
 assert(luma.maxOffsetOutdated==1280*720);
 auto padded=load(640,360,704);assert(padded.pitch==704);
 assert(padded.maxOffsetOutdated==704*360);
 for(auto f:{Latte::E_GX2SURFFMT::R8,Latte::E_GX2SURFFMT::RG8,Latte::E_GX2SURFFMT::RGBA8}){
  auto c=load(640,360,648,f);assert(c.pitch==648);
  assert(c.maxOffsetOutdated==648*360*int(f)/8);
 }
 auto general=load(640,360,640,Latte::E_GX2SURFFMT::R8,Latte::E_HWTILEMODE::TM_LINEAR_GENERAL);
 assert(general.pitch==640);
 auto layered=load(640,360,640,Latte::E_GX2SURFFMT::R8,Latte::E_HWTILEMODE::TM_LINEAR_ALIGNED,0,3);
 assert(layered.maxOffsetOutdated==640*360*3);
 // This correction must not reinterpret tiled/compressed layouts or lower mips.
 assert(load(640,360,640,Latte::E_GX2SURFFMT::R8,Latte::E_HWTILEMODE::TILED).pitch==768);
 assert(load(640,360,160,Latte::E_GX2SURFFMT::BC1).pitch==640);
 assert(load(640,360,640,Latte::E_GX2SURFFMT::R8,Latte::E_HWTILEMODE::TM_LINEAR_ALIGNED,1).pitch==512);
 assert(load(640,360,0).pitch==768); // Missing pitch retains existing calculation.
 CafeSystem::title=0x000500301001200aULL;
 assert(load(640,360,640,Latte::E_GX2SURFFMT::R8,Latte::E_HWTILEMODE::TM_LINEAR_ALIGNED,1).pitch==320);
}
'''
        with tempfile.TemporaryDirectory(prefix="cemu-linear-pitch-") as directory:
            path = Path(directory)
            (path / "test.cpp").write_text(harness)
            build = subprocess.run([shutil.which("clang++"), "-std=c++20", "-O1",
                "-fsanitize=address,undefined", str(path / "test.cpp"),
                "-o", str(path / "test")], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(path / "test")], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
