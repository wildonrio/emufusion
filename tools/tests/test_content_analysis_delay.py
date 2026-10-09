from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class ContentAnalysisDelayTest(unittest.TestCase):
    def test_threshold_cpu_failure_and_log_bound(self):
        source=(ROOT/'experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/cpp/rife_benchmark_jni.cpp').read_text()
        function=source[source.index('void report_content_analysis_delay('):source.index('bool decode_content_proof(')]
        code=r'''
#include <cstdint>
#include <atomic>
#include <cassert>
int calls=0,reads=0;long long lastCpu=0;std::int64_t cpu=400;
constexpr int ANDROID_LOG_WARN=1;
std::int64_t content_analysis_thread_cpu_ns(){++reads;return cpu;}
void __android_log_print(int,const char*,const char*,unsigned long long,unsigned long long,long long value){++calls;lastCpu=value;}
FUNCTION
int main(){
 report_content_analysis_delay(1,1000000,100);assert(calls==0&&reads==0);
 report_content_analysis_delay(2,1000001,100);assert(calls==1&&lastCpu==300);
 cpu=-1;report_content_analysis_delay(3,2000000,100);assert(calls==2&&lastCpu==-1);
 for(int i=0;i<20;++i)report_content_analysis_delay(4+i,2000000,100);
 assert(calls==8);
}
'''.replace('FUNCTION',function)
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/'test.cpp';src.write_text(code);binary=Path(temp)/'test'
            subprocess.run(['clang++','-std=c++17',str(src),'-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary)],check=True,capture_output=True)
