"""Exercise the generated QA restore gates and callback using real file reads."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class StateRestoreProbeTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_actual_release_chord_scope_read_and_preservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / 'adapter.cpp'
            subprocess.run(['python3', str(ROOT/'engines/diagnostics/prepare_state_restore_probe.py'),
                            '--source', str(ROOT/'engines/patches/aps3e-lucent-adapter.cpp'),
                            '--output', str(generated)], check=True, capture_output=True)
            text = generated.read_text()
            fields_start = text.index('    std::atomic<bool> qa_capture_left')
            fields = text[fields_start:text.index('\n};', fields_start)]
            start = text.index('struct capture_file {')
            capture_file = text[start:text.index('std::filesystem::path capture_state_path()', start)]
            start = text.index('static void qa_capture_input(')
            helpers = text[start:text.index('static bool adapter_run_frame(', start)]
            control = text[text.index('static void adapter_set_control('):text.index('static void adapter_pause(')]
            self.assertLess(control.index('if (code != 0) ae::key_event'),
                            control.index('qa_capture_input(engine, control, value)'))
            self.assertNotIn('render-capture-probe begin', text)
            prefix = r'''
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
enum lucent_native_control { LUCENT_PAD_L, LUCENT_PAD_R, LUCENT_PAD_A };
constexpr int ANDROID_LOG_WARN=1; constexpr const char* kTag="test";
void __android_log_print(int,const char*,const char*,...) {}
void log_error(const char*) {}
struct { bool IsRunning() {return true;} } Emu;
namespace ae { bool is_running() {return true;} }
std::filesystem::path slot;
std::filesystem::path capture_state_path() {return slot;}
struct lucent_native_engine {
 bool loaded=true, started=true, stopped=false;
 std::string system_directory, save_directory;
'''+fields+r'''
};
int restores=0; bool accept=true;
static bool adapter_unserialize(lucent_native_engine*,const void* data,std::size_t size) {
 assert(size==318191507); assert(data); ++restores; return accept;
}
'''
            suffix = r'''
void chord(lucent_native_engine& e) {
 qa_capture_input(&e,LUCENT_PAD_L,1); qa_capture_input(&e,LUCENT_PAD_R,1);
 assert(!e.qa_capture_requested);
 qa_capture_input(&e,LUCENT_PAD_L,0); assert(!e.qa_capture_requested);
 qa_capture_input(&e,LUCENT_PAD_R,0);
}
int main(int argc,char** argv) {
 assert(argc==2); const std::filesystem::path root=argv[1];
 const auto system=root/"app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee/aps3e";
 const auto save=root/"engine-saves-qa/qa-6ad510e4afd607fcabffb75570be37ee/aps3e/a2680fcb94d97bbe550e4a694bf99769";
 std::filesystem::create_directories(save);
 slot=system/"config/savestates/BCUS98259/BCUS98259_1_0.SAVESTAT.zst";
 std::filesystem::create_directories(slot.parent_path());
 lucent_native_engine base; base.system_directory=system; base.save_directory=save;
 auto init=[&](lucent_native_engine& e) {e.system_directory=system; e.save_directory=save;};
 // Missing source and wrong captured byte count cannot reach actual restore.
 {lucent_native_engine e; init(e); chord(e); qa_restore_on_render_owner(&e); assert(restores==0);}
 {std::ofstream out(slot); out<<"preserve";}
 {lucent_native_engine e; init(e); chord(e); qa_restore_on_render_owner(&e); assert(restores==0);}
 // Sparse fixture has the exact observed size without allocating disk space.
 int fd=::open(slot.c_str(),O_RDWR); assert(fd>=0); assert(::ftruncate(fd,318191507)==0); ::close(fd);
 struct stat before{}; assert(::stat(slot.c_str(),&before)==0);
 // Wrong engine namespace, content identity and restore namespace are all rejected.
 for(int kind=0;kind<4;++kind) {
  lucent_native_engine e; init(e);
  if(kind==0)e.system_directory=(root/"app_engine-system/aps3e").string();
  if(kind==1)e.save_directory=(save.parent_path()/"other-game").string();
  if(kind==2)e.save_directory=(root/"normal/qa-6ad510e4afd607fcabffb75570be37ee/aps3e/a2680fcb94d97bbe550e4a694bf99769").string();
  if(kind==3)slot=system/"config/savestates/OTHER/OTHER_1_0.SAVESTAT.zst";
  chord(e); qa_restore_on_render_owner(&e); assert(restores==0);
  slot=system/"config/savestates/BCUS98259/BCUS98259_1_0.SAVESTAT.zst";
 }
 const auto destination=save/"lucent-restore.SAVESTAT.zst";
 {std::ofstream out(destination); out<<"old-restore";}
 {lucent_native_engine e; init(e); chord(e); qa_restore_on_render_owner(&e); assert(restores==0);}
 {std::string value; std::ifstream(destination)>>value; assert(value=="old-restore");}
 std::filesystem::remove(destination); // Test-owned temporary fixture only.
 for(bool result:{true,false}) {
  lucent_native_engine e; init(e); accept=result; const int prior=restores;
  chord(e); assert(restores==prior); qa_restore_on_render_owner(&e); assert(restores==prior+1);
  chord(e); qa_restore_on_render_owner(&e); assert(restores==prior+1);
 }
 struct stat after{}; assert(::stat(slot.c_str(),&after)==0);
 assert(before.st_ino==after.st_ino && before.st_size==after.st_size);
 std::string value; std::ifstream(slot)>>value; assert(value.substr(0,8)=="preserve");
}
'''
            source = root/'test.cpp'
            source.write_text(prefix+capture_file+helpers+suffix)
            binary = root/'test'
            subprocess.run(['c++', '-std=c++20', '-fsanitize=address,undefined', str(source),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary), str(root)], check=True)

    def test_packager_rejects_unscoped_restore(self):
        result = subprocess.run(['python3', str(ROOT/'engines/diagnostics/package_spurs_trace.py'),
                                 '--state-restore-probe', '/not-read', '--trace-library', '/not-read',
                                 '--trace-sha256', '0'*64, '--output-dir', '/not-created'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('state restore requires wrapper/retained composition', result.stderr)


if __name__ == '__main__':
    unittest.main()
