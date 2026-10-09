"""Execute extracted adapter capture functions against real temporary files."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT/'engines/patches/aps3e-lucent-adapter.cpp'
GEN = ROOT/'engines/diagnostics/prepare_fresh_savestate.py'
spec = importlib.util.spec_from_file_location('fresh_capture', GEN)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

PREFIX = r'''
#include <cassert>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
constexpr std::size_t kMaxStateBytes=64;
constexpr auto kStopTimeout=std::chrono::milliseconds(0);
int mode=0, kills=0, quits=0, reads=0;
std::string slot;
void log_error(const char*) {}
std::string get_savestate_file(const std::string&, const std::string&, int a, int b) {
 assert(a==0 && b==0); return mode==10 ? "unexpected" : slot;
}
struct MockEmu {
 bool stopped=false;
 std::function<void()> kill;
 bool IsStopped(bool = false) { return stopped; }
 void Kill(bool autoexit, bool save) { assert(!autoexit && save); ++kills; kill(); }
 std::string GetTitleID() { return "GAME"; }
 std::string GetBoot() { return "GAME.self"; }
} Emu;
namespace ae {
 bool is_running() { return quits==0; }
 bool is_paused() { return false; }
 void quit() { ++quits; }
}
struct lucent_native_engine {
 bool started=true, stopped=false, save_requested=false;
 std::mutex mutex;
 std::string system_directory;
 std::filesystem::path restore_path;
 std::vector<std::uint8_t> serialized_state;
};
ssize_t checked_read(int fd, void* data, size_t size) {
 ++reads;
 if (mode==8 && reads==1) { errno=EINTR; return -1; }
 if (mode==7) {
  if (reads==1) return ::read(fd,data,2);
  return 0; // deterministic short read/EOF: must discard the partial buffer
 }
 return ::read(fd,data,size);
}
#define read checked_read
'''

SUFFIX = r'''
#undef read
void put(const std::string& path, const std::string& bytes) {
 std::ofstream out(path,std::ios::binary); out<<bytes; assert(out.good());
}
int main(int argc, char** argv) {
 assert(argc==3);
 mode=std::stoi(argv[2]);
 lucent_native_engine e;
 e.system_directory=argv[1];
 const auto root=e.system_directory+"/config/savestates";
 std::filesystem::create_directories(root);
 slot=root+"/GAME_1_0.SAVESTAT.zst";
 if (mode==11) std::filesystem::create_directory(slot);
 else if (mode!=4) put(slot,"old!");
 const bool success=mode==2 || mode==4 || mode==8;
 const auto old_time=std::filesystem::file_time_type::clock::now()-std::chrono::hours(1);
 if (mode!=4 && mode!=11) std::filesystem::last_write_time(slot,old_time);
 if (mode==9) { e.stopped=true; Emu.stopped=true; }
 Emu.kill=[&] {
  Emu.stopped=mode!=1;
  if (mode==0 || mode==9 || mode==10 || mode==11) return;
  if (mode==3) {
   put(root+"/OTHER.SAVESTAT.zst","wrong-game"); return;
  }
  put(slot+".pending",mode==5 ? "" : mode==6 ? std::string(65,'x') : "new!");
  // Equal size and timestamp, but a newly committed inode: should be accepted.
  std::filesystem::last_write_time(slot+".pending",old_time);
  std::filesystem::rename(slot+".pending",slot);
 };
 auto result=adapter_serialize_size(&e);
 if ((result>0)!=success || (!success && !e.serialized_state.empty())) return 10;
 if (success && std::string(e.serialized_state.begin(),e.serialized_state.end())!="new!") return 11;
 if (mode==1 && e.stopped) return 12;
 if ((mode==9 || mode==10 || mode==11) && kills!=0) return 13;
 if ((mode==0 || mode==3 || mode==5 || mode==6 || mode==7 || success) && quits!=1) return 14;
 const int calls=kills;
 if (adapter_serialize_size(&e)!=result || kills!=calls) return 15;
 if (!success && !e.restore_path.empty()) return 16;
 return 0;
}
'''


class FreshSavestateTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_restore_write_preserves_destination_and_reports_failed_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, text in [('old',SRC.read_text()),('new',generator.prepare(SRC.read_bytes()))]:
                start = text.index('bool write_file_atomic(')
                body = text[start:text.index('int virtual_key(',start)]
                suffix = r'''
#undef read
int main(int argc, char** argv) {
 assert(argc==2);
 const auto root=std::filesystem::path(argv[1]);
 std::filesystem::create_directories(root/"destination");
 std::ofstream(root/"destination"/"keep")<<"preserve";
 // Renaming a file over a nonempty directory fails. Cleanup must not return true.
 if (write_file_atomic(root/"destination","new",3)) return 10;
 assert(std::filesystem::exists(root/"destination"/"keep"));
 assert(!std::filesystem::exists(root/"destination.pending"));
 assert(write_file_atomic(root/"normal","old",3));
 assert(write_file_atomic(root/"normal","new",3));
 std::string value; std::ifstream(root/"normal")>>value; assert(value=="new");
 assert(!write_file_atomic(root/"normal",nullptr,3));
 assert(!write_file_atomic(root/"normal","new",0));
 assert(std::filesystem::exists(root/"normal"));
}
'''
                source=root/(label+'.cpp'); binary=root/label
                source.write_text(PREFIX+'\n#undef read\n'+body+suffix)
                subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
                result=subprocess.run([str(binary),str(root/(label+'-data'))])
                self.assertEqual(result.returncode,10 if label=='old' else 0)

    def test_preserves_unrelated_code_and_rejects_drift(self):
        old = SRC.read_bytes()
        new = generator.prepare(old)
        for marker in ('static void adapter_set_control(', 'static bool adapter_unserialize('):
            end = '\n}\n'
            before = old.decode()[old.decode().index(marker):].split(end, 1)[0]
            after = new[new.index(marker):].split(end, 1)[0]
            self.assertEqual(before, after)
        self.assertNotIn('newest_state(', new)
        with self.assertRaises(ValueError):
            generator.prepare(old+b'\n')

    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_actual_capture_stale_timeout_wrong_game_and_fresh_commit(self):
        old = SRC.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, text in [('old', old.decode()), ('new', generator.prepare(old))]:
                start = text.index('std::filesystem::path newest_state(') if label=='old' else text.index('struct capture_file {')
                helpers = text[start:text.index('bool write_file_atomic(', start)]
                start = text.index('static std::size_t adapter_serialize_size(')
                capture = text[start:text.index('static std::size_t adapter_serialize(', start)]
                source = root/(label+'.cpp')
                binary = root/label
                # The test read shim applies only to the new POSIX read helper.
                prefix = PREFIX if label=='new' else PREFIX+'\n#undef read\n'
                source.write_text(prefix+helpers+capture+SUFFIX)
                subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined',
                                str(source),'-o',str(binary)],check=True)
                cases = range(12) if label=='new' else (0,1,3)
                for case in cases:
                    with self.subTest(version=label, case=case):
                        result = subprocess.run([str(binary),str(root/(label+str(case))),str(case)])
                        self.assertEqual(result.returncode,0 if label=='new' else 10)
        self.assertEqual(SRC.read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
