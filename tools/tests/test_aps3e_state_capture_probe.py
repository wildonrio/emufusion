"""QA trigger must never serialize a normal user's save namespace."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools.tests.test_aps3e_fresh_savestate import reviewed_adapter

ROOT = Path(__file__).resolve().parents[2]


class StateCaptureProbeTest(unittest.TestCase):
    def test_package_rejects_missing_composition(self):
        result = subprocess.run(['python3',str(ROOT/'engines/diagnostics/package_spurs_trace.py'),
            '--state-capture-probe','/nonexistent/source','--output-dir','/nonexistent/output',
            '--trace-library','/nonexistent/library','--trace-sha256','0'*64],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('state capture requires wrapper/retained composition',result.stderr)

    @unittest.skipUnless(shutil.which('c++'),'compiler absent')
    def test_scoped_actual_flush(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output=root/'adapter.cpp'
            reviewed=root/'reviewed-adapter.cpp'; reviewed.write_bytes(reviewed_adapter())
            subprocess.run(['python3',str(ROOT/'engines/diagnostics/prepare_state_capture_probe.py'),
                '--source',str(reviewed),
                '--output',str(output)],check=True,capture_output=True)
            text=output.read_text()
            start=text.index('static bool adapter_flush_save(')
            body=text[start:text.index('static std::size_t adapter_serialize_size(',start)]
            prefix=r'''
#include <cassert>
#include <filesystem>
#include <fstream>
#include <string>
constexpr int ANDROID_LOG_WARN=1;
constexpr const char* kTag="test";
void __android_log_print(int,const char*,const char*,...) {}
void log_error(const char*) {}
std::filesystem::path slot;
std::filesystem::path capture_state_path() { return slot; }
struct lucent_native_engine {
 bool loaded=true,started=true,stopped=false;
 std::string system_directory;
 std::filesystem::path restore_path;
};
int calls=0; std::size_t captured=4;
std::size_t adapter_serialize_size(lucent_native_engine*) {++calls; return captured;}
'''
            suffix=r'''
int main(int argc,char** argv) {
 assert(argc==2); const std::string root=argv[1];
 slot=root+"/first.SAVESTAT.zst";
 const std::string qa="app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee";
 for (const auto& parent : {qa,std::string("app_engine-system"),qa+"-different"}) {
  for (const auto& id : {"aps3e","eden"}) {
   lucent_native_engine e; e.system_directory=root+"/"+parent+"/"+id;
   std::filesystem::create_directories(e.system_directory+"/config");
   calls=0; captured=4; assert(adapter_flush_save(&e));
   assert(calls==(parent==qa && std::string(id)=="aps3e"));
  }
 }
 lucent_native_engine e; e.system_directory=root+"/"+qa+"/aps3e";
 calls=0; captured=0; assert(!adapter_flush_save(&e)); assert(calls==1);
 std::ofstream(slot)<<"preserve";
 calls=0; captured=4; assert(!adapter_flush_save(&e)); assert(calls==0);
 for (int flag=0;flag<3;++flag) {
  e.loaded=flag!=0; e.started=flag!=1; e.stopped=flag==2; calls=0;
  adapter_flush_save(&e); assert(calls==0);
 }
 assert(!adapter_flush_save(nullptr));
}
'''
            source=root/'probe.cpp'; binary=root/'probe'
            source.write_text(prefix+body+suffix)
            subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary),str(root/'data')],check=True)


if __name__ == '__main__':
    unittest.main()
