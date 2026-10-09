"""The QA chord queues capture; only the render owner may execute it."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RenderCaptureProbeTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'),'compiler absent')
    def test_actual_queue_scope_once_and_existing_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'adapter.cpp'
            subprocess.run(['python3',str(ROOT/'engines/diagnostics/prepare_render_capture_probe.py'),
                '--source',str(ROOT/'engines/patches/aps3e-lucent-adapter.cpp'),
                '--output',str(output)],check=True,capture_output=True)
            text=output.read_text()
            start=text.index('static void qa_capture_input(')
            body=text[start:text.index('static bool adapter_run_frame(',start)]
            self.assertIn('qa_capture_on_render_owner(engine);',text)
            self.assertIn('qa_capture_input(engine, control, value);',text)
            flush=text[text.index('static bool adapter_flush_save('):text.index('static std::size_t adapter_serialize_size(lucent_native_engine* engine) {')]
            self.assertNotIn('probe',flush)
            fields=text[text.index('    std::atomic<bool> qa_capture_left'):text.index('\n};',text.index('    std::atomic<bool> qa_capture_left'))]
            prefix=r'''
#include <atomic>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <string>
enum lucent_native_control { LUCENT_PAD_L,LUCENT_PAD_R,LUCENT_PAD_A };
constexpr int ANDROID_LOG_WARN=1; constexpr const char* kTag="test";
void __android_log_print(int,const char*,const char*,...) {}
void log_error(const char*) {}
std::filesystem::path slot; int captures=0;
std::filesystem::path capture_state_path() { return slot; }
struct lucent_native_engine {
 bool loaded=true,started=true,stopped=false;
 std::string system_directory; std::filesystem::path restore_path;
'''+fields+r'''
};
std::size_t adapter_serialize_size(lucent_native_engine*) { ++captures; return 4; }
'''
            suffix=r'''
int main(int argc,char** argv) {
 assert(argc==2); slot=std::string(argv[1])+"/state";
 const std::string qa="/data/app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee/aps3e";
 for (const auto& path : {qa,std::string("/data/app_engine-system/aps3e"),qa+"-other"}) {
  lucent_native_engine e; e.system_directory=path; captures=0;
  qa_capture_input(&e,LUCENT_PAD_L,1); qa_capture_on_render_owner(&e); assert(captures==0);
  qa_capture_input(&e,LUCENT_PAD_R,1); assert(captures==0);
  qa_capture_on_render_owner(&e); assert(captures==(path==qa));
  qa_capture_input(&e,LUCENT_PAD_R,1); qa_capture_on_render_owner(&e); assert(captures==(path==qa));
 }
 lucent_native_engine e; e.system_directory=qa; captures=0;
 std::ofstream(slot)<<"preserve";
 qa_capture_input(&e,LUCENT_PAD_L,1); qa_capture_input(&e,LUCENT_PAD_R,1);
 qa_capture_on_render_owner(&e); assert(captures==0);
 std::string saved; std::ifstream(slot)>>saved; assert(saved=="preserve");
 for(int flag=0;flag<3;++flag) {
  lucent_native_engine invalid; invalid.system_directory=qa;
  invalid.loaded=flag!=0; invalid.started=flag!=1; invalid.stopped=flag==2;
  qa_capture_input(&invalid,LUCENT_PAD_L,1); qa_capture_input(&invalid,LUCENT_PAD_R,1);
  assert(!invalid.qa_capture_requested);
 }
 qa_capture_input(nullptr,LUCENT_PAD_L,1);
}
'''
            source=root/'test.cpp'; binary=root/'test'
            source.write_text(prefix+body+suffix)
            subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary),str(root)],check=True)

    def test_emergency_cleanup_releases_both_chord_buttons(self):
        for name in ('qa_oled_timeout.sh','qa_oled_device_timeout.sh'):
            text=(ROOT/'tools'/name).read_text()
            for button in (310,311):
                self.assertIn('sendevent /dev/input/event9 1 '+str(button)+' 0',text)


if __name__ == '__main__':
    unittest.main()
