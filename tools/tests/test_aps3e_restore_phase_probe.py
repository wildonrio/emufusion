"""Verify diagnostic phase ordering and retained-wrapper composition."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'engines/diagnostics'))
from prepare_restore_phase_probe import prepare, prepare_wrapper
from prepare_core_error_trace import LISTENER


class RestorePhaseProbeTest(unittest.TestCase):
    def test_new_attempt_preserves_previous_qa_destinations(self):
        original = (ROOT/'engines/patches/aps3e-lucent-adapter.cpp').read_bytes()
        baseline = prepare(original)
        candidate = prepare(original, attempt='atomic1')
        self.assertEqual(candidate, baseline.replace(
            'lucent-restore-phase2.SAVESTAT.zst',
            'lucent-restore-atomic1.SAVESTAT.zst'))
        self.assertIn('lucent-restore.SAVESTAT.zst', candidate)
        for invalid in ('', '../old', 'a/b', 'A', 'a'*50):
            with self.assertRaises(ValueError):
                prepare(original, attempt=invalid)

    def test_wrapper_only_adds_existing_error_mirror(self):
        original = (ROOT/'engines/build/candidates/aps3e-wrapper-sync-source-2026-09-09/aps3e_emu.cpp').read_bytes()
        result = prepare_wrapper(original)
        recovered = result.replace(LISTENER+'\nnamespace ae{', 'namespace ae{', 1)
        recovered = recovered.replace('        install_lucent_core_error_listener();\n', '', 1)
        self.assertEqual(recovered.encode(), original)
        with self.assertRaises(ValueError):
            prepare_wrapper(original+b' ')

    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_actual_callback_phase_order_and_normal_destination(self):
        text = prepare((ROOT/'engines/patches/aps3e-lucent-adapter.cpp').read_bytes())
        self.assertIn('std::filesystem::exists(save / "lucent-restore-phase2.SAVESTAT.zst", ec)', text)
        start = text.index('static bool adapter_unserialize(lucent_native_engine* engine,')
        body = text[start:text.index('static bool adapter_surface_recreated(', start)]
        prefix = r'''
#include <cassert>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <dlfcn.h>
#include <filesystem>
#include <string>
#include <thread>
#include <vector>
constexpr auto kStopTimeout=std::chrono::milliseconds(2);
constexpr std::size_t kMaxStateBytes=1000;
constexpr int ANDROID_LOG_WARN=1; constexpr const char* kTag="test";
std::vector<std::string> phases, operations;
void __android_log_print(int,const char*,const char* format,...) {
 char output[256]; va_list args; va_start(args,format); vsnprintf(output,sizeof(output),format,args); va_end(args);
 if(std::string(output).find("state-restore-phase ")==0) phases.push_back(output);
}
struct lucent_native_engine {bool started=true; std::string system_directory,save_directory;};
struct {struct {bool suspend_emu=false;} savestate;} g_cfg;
bool commit_ok=true,stop_ok=true,boot_ok=true; std::filesystem::path destination;
bool write_file_atomic(const std::filesystem::path& path,const void*,std::size_t) {
 destination=path; operations.push_back("commit"); return commit_ok;
}
enum class game_boot_result {no_errors,error};
struct {
 void GracefulShutdown(bool,bool,bool) {operations.push_back("shutdown");}
 bool IsStopped(bool) {return stop_ok;}
 game_boot_result BootGame(const std::string&,const char*,bool) {operations.push_back("boot"); return boot_ok?game_boot_result::no_errors:game_boot_result::error;}
} Emu;
'''
        suffix = r'''
int main() {
 const std::string qa="/data/app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee/aps3e";
 lucent_native_engine e; e.system_directory=qa; e.save_directory="/save";
 auto reset=[] {phases.clear(); operations.clear(); commit_ok=stop_ok=boot_ok=true;};
 assert(adapter_unserialize(&e,"data",4));
 assert(destination.filename()=="lucent-restore-phase2.SAVESTAT.zst");
 assert((operations==std::vector<std::string>{"commit","shutdown","boot"}));
 assert(phases.size()==7 && phases[0]=="state-restore-phase commit begin" && phases[6]=="state-restore-phase boot returned result=0");
 reset(); commit_ok=false; assert(!adapter_unserialize(&e,"data",4)); assert(operations.size()==1 && phases.back()=="state-restore-phase commit failed");
 reset(); stop_ok=false; assert(!adapter_unserialize(&e,"data",4)); assert(operations.size()==2 && phases.back()=="state-restore-phase shutdown timeout");
 reset(); boot_ok=false; assert(!adapter_unserialize(&e,"data",4)); assert(operations.size()==3 && phases.back()=="state-restore-phase boot returned result=1");
 reset(); g_cfg.savestate.suspend_emu=true;
 assert(!adapter_unserialize(&e,"data",4)); assert(operations.empty());
 assert(phases.back()=="state-restore-phase skipped: suspend mode would consume preserved state");
 g_cfg.savestate.suspend_emu=false;
 reset(); e.system_directory="/data/app_engine-system/aps3e";
 assert(adapter_unserialize(&e,"data",4)); assert(phases.empty());
 assert(destination.filename()=="lucent-restore.SAVESTAT.zst");
 reset(); e.started=false; assert(!adapter_unserialize(&e,"data",4)); assert(operations.empty());
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'test.cpp'; binary = root/'test'
            source.write_text(prefix+body+suffix)
            subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

    def test_packager_requires_core_mirror_and_composition(self):
        result = subprocess.run(['python3',str(ROOT/'engines/diagnostics/package_spurs_trace.py'),
            '--restore-phase-probe','/not-read','--trace-library','/not-read',
            '--trace-sha256','0'*64,'--output-dir','/not-created'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('restore phase requires retained wrapper/composition',result.stderr)


if __name__ == '__main__':
    unittest.main()
