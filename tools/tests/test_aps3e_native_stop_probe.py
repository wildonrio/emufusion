"""The diagnostic must not stop ordinary gameplay or accept incomplete shutdown."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'engines/patches/aps3e-lucent-adapter.cpp'
GEN = ROOT / 'engines/diagnostics/prepare_native_stop_probe.py'
spec = importlib.util.spec_from_file_location('stop_probe', GEN)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class StopProbeTest(unittest.TestCase):
    def test_narrow_change_and_drift_rejected(self):
        old = SRC.read_bytes()
        self.assertEqual(generator.prepare(old).replace(generator.NEW, generator.OLD, 1), old.decode())
        with self.assertRaises(ValueError):
            generator.prepare(old + b'\n')

    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_scope_and_stopped_boundary(self):
        text = generator.prepare(SRC.read_bytes())
        body = text[text.index(generator.OLD):text.index('static std::size_t adapter_serialize_size')]
        prefix = r'''
#include <cassert>
#include <chrono>
#include <filesystem>
#include <string>
#include <thread>
constexpr int ANDROID_LOG_WARN=1;
constexpr const char* kTag="test";
constexpr auto kStopTimeout=std::chrono::milliseconds(0);
void __android_log_print(int, const char*, const char*, ...) {}
int quit_calls=0;
namespace ae { void quit() { ++quit_calls; } }
struct { bool stopped=true; bool IsStopped(bool fully) { assert(fully); return stopped; } } Emu;
struct lucent_native_engine {
 bool loaded=true, started=true, stopped=false;
 std::string system_directory;
};
'''
        suffix = r'''
int main(int argc, char** argv) {
 assert(argc==2);
 const std::string root=argv[1];
 const std::string scope="app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee";
 const auto check=[&](const std::string& parent, const std::string& engine_name,
                     bool loaded, bool started, bool already_stopped,
                     bool completes, int expected_calls, bool expected_result) {
  lucent_native_engine e{loaded, started, already_stopped, root+"/"+parent+"/"+engine_name};
  std::filesystem::create_directories(e.system_directory+"/config");
  quit_calls=0; Emu.stopped=completes;
  assert(adapter_flush_save(&e)==expected_result);
  assert(quit_calls==expected_calls);
  assert(e.stopped==(already_stopped || (expected_calls && completes)));
 };
 check(scope,"aps3e",true,true,false,true,1,true);
 check(scope,"aps3e",true,true,false,false,1,false);
 check("app_engine-system","aps3e",true,true,false,true,0,true);
 check(scope+"-other","aps3e",true,true,false,true,0,true);
 check(scope,"eden",true,true,false,true,0,true);
 check(scope,"aps3e",false,true,false,true,0,false);
 check(scope,"aps3e",true,false,false,true,0,true);
 check(scope,"aps3e",true,true,true,true,0,true);
 assert(!adapter_flush_save(nullptr));
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'probe.cpp'
            binary=Path(temporary)/'probe'
            source.write_text(prefix+body+suffix)
            subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror',
                            '-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary),str(Path(temporary)/'data')],check=True)


if __name__ == '__main__':
    unittest.main()
