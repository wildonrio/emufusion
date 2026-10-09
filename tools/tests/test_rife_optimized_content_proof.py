"""Compare production proof decoding with and without compiler optimization."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class OptimizedContentProofTest(unittest.TestCase):
    def test_o2_preserves_every_proof_field(self):
        source=(ROOT/'experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/cpp/rife_benchmark_jni.cpp').read_text()
        declarations=source[source.index('constexpr int kContentProofWidth'):source.index('struct AcquiredHardwareBuffer')]
        function=source[source.index('bool decode_content_proof('):source.index('bool collect_pending_content_proof(')]
        fields=re.findall(r'std::uint64_t (\w+) =',declarations)
        harness=r'''
#include <array>
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <vector>
DECLARATIONS
std::int64_t now_ns(){return 1;}
std::int64_t content_analysis_thread_cpu_ns(){return 1;}
void report_content_analysis_delay(std::uint64_t,std::uint64_t,std::int64_t){}
namespace ncnn {
struct Allocator {void invalidate(void*){}};
struct VkMat {
 Allocator owned;Allocator* allocator=&owned;void* data=nullptr;
 int dims=2,w=kContentProofAtlasWidth,h=kContentProofHeight,elempack=1;
 std::size_t elemsize=3;std::vector<std::uint8_t> bytes=std::vector<std::uint8_t>(kContentProofBytes);
 bool empty(){return bytes.empty();}std::size_t total(){return w*h;}
 void* mapped_ptr(){return bytes.data();}
};
}
FUNCTION
int main(){
 for(unsigned seed=0;seed<64;++seed){
  ncnn::VkMat input;unsigned state=seed+1;
  for(auto& byte:input.bytes){state=state*1664525u+1013904223u;byte=state>>24;}
  if(seed%3==0)std::fill(input.bytes.begin(),input.bytes.end(),seed);
  if(seed%2==0)for(int y=0;y<kContentProofHeight;++y)
   for(int x=0;x<kContentProofWidth*3;++x)
    input.bytes[y*kContentProofAtlasWidth*3+3*kContentProofWidth*3+x]=
      input.bytes[y*kContentProofAtlasWidth*3+kContentProofWidth*3+x];
  SurfaceContentProof proof;
  bool ok=decode_content_proof(input,seed+1,true,&proof);
  if(seed%2==0&&!ok)return 2;
  std::cout<<ok;
  FIELDS
  std::cout<<'\n';
 }
}
'''.replace('DECLARATIONS',declarations).replace('FUNCTION',function).replace('FIELDS','\n'.join("std::cout<<' '<<proof."+f+';' for f in fields))
        outputs=[]
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'proof.cpp';path.write_text(harness)
            for optimization in ('-O0','-O2'):
                binary=Path(temporary)/optimization[1:]
                subprocess.run(['clang++','-std=c++17',optimization,str(path),'-o',str(binary)],check=True,capture_output=True)
                result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
                outputs.append(result.stdout)
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(len(outputs[0].splitlines()),64)
