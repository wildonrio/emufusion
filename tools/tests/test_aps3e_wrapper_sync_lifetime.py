"""Deterministic delayed condition-wait reacquire, using actual wrapper code."""
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT/'engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/app/src/main/cpp/aps3e_emu.cpp'
GEN = ROOT/'engines/diagnostics/prepare_wrapper_sync_lifetime.py'
spec = importlib.util.spec_from_file_location('wrapper_sync', GEN)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

PREFIX = r'''
#include <atomic>
#include <cassert>
#include <stdexcept>
struct mock_mutex_t { bool alive=false; };
struct mock_cond_t { bool alive=false; };
#undef PTHREAD_MUTEX_INITIALIZER
#undef PTHREAD_COND_INITIALIZER
#define PTHREAD_MUTEX_INITIALIZER {true}
#define PTHREAD_COND_INITIALIZER {true}
void mock_mutex_init(mock_mutex_t* p, void*) { p->alive=true; }
void mock_cond_init(mock_cond_t* p, void*) { p->alive=true; }
void mock_mutex_destroy(mock_mutex_t* p) { p->alive=false; }
void mock_cond_destroy(mock_cond_t* p) { p->alive=false; }
void mock_mutex_lock(mock_mutex_t* p) { if (!p->alive) throw std::runtime_error("destroyed mutex"); }
void mock_mutex_unlock(mock_mutex_t*) {}
void mock_cond_signal(mock_cond_t*) {}
void worker_stop();
void mock_cond_wait(mock_cond_t* c, mock_mutex_t* m) {
 assert(c->alive);
 mock_mutex_unlock(m);
 worker_stop(); // worker runs through signal and exit before waiter is scheduled
 mock_mutex_lock(m);
}
void usleep(int) {}
int kills=0;
struct { void Kill() { ++kills; } } Emu;
enum { STATUS_RUNNING=1,STATUS_STOPPED,STATUS_PAUSED,STATUS_REQUEST_PAUSE,STATUS_REQUEST_RESUME,STATUS_REQUEST_STOP };
'''


@unittest.skipUnless(SRC.is_file(), 'local wrapper source absent')
class WrapperSyncLifetimeTest(unittest.TestCase):
    def test_patch_reproduces_tested_source_without_touching_cached_tree(self):
        original = SRC.read_bytes()
        patch = ROOT/'engines/patches/aps3e-wrapper-sync-lifetime.patch'
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary)/'app/src/main/cpp/aps3e_emu.cpp'
            copy.parent.mkdir(parents=True)
            copy.write_bytes(original)
            subprocess.run(['git', 'apply', str(patch)], cwd=temporary, check=True)
            self.assertEqual(copy.read_text(), generator.prepare(original))
            subprocess.run(['git', 'apply', '--reverse', str(patch)], cwd=temporary, check=True)
            self.assertEqual(copy.read_bytes(), original)
        self.assertEqual(SRC.read_bytes(), original)

    def test_scope_and_drift(self):
        old = SRC.read_bytes()
        new = generator.prepare(old)
        self.assertNotIn('pthread_mutex_destroy(', new)
        self.assertNotIn('pthread_cond_destroy(', new)
        self.assertIn('std::atomic<int> emu_status{-1};', new)
        with self.assertRaises(ValueError):
            generator.prepare(old+b'\n')

    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_actual_stop_waiter_outlives_worker_old_fails_new_passes(self):
        old = SRC.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            for label, text, expected in [('old',old.decode(),10),('new',generator.prepare(old),0)]:
                declarations = text[text.index('    pthread_mutex_t key_event_mutex'):text.index('    void init();')]
                start=text.index('        LOGW("new thr:')
                init=text[text.index('\n',start)+1:text.index('        init();',start)]
                start=text.index('            if (emu_status == STATUS_REQUEST_STOP)')
                end=text.index('\n            usleep(10);',start)
                stop=text[start:end]
                start=text.index('\n        }',end)+len('\n        }')
                footer=text[start:text.index('\n    }',start)]
                start=text.index('    void quit(){')
                quit_method=text[start:text.index('\n    }',start)+6]
                source_code=PREFIX+declarations+'\nvoid worker_stop() { bool boot_ok=true; do {\n'+stop+'\n} while(false);\n'+footer+'}\n'+quit_method
                source_code+='\nint main() {\n'+init+r'''
 try {
  for (int i=0;i<100;i++) { emu_status=STATUS_RUNNING; quit(); assert(emu_status==STATUS_STOPPED); }
 } catch (const std::runtime_error&) { return 10; }
 assert(kills==100);
}
'''
                source_code = re.sub(r'\bpthread_', 'mock_', source_code)
                source=Path(temporary)/(label+'.cpp')
                binary=Path(temporary)/label
                source.write_text(source_code)
                subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
                self.assertEqual(subprocess.run([str(binary)]).returncode,expected)
        self.assertEqual(SRC.read_bytes(),old)


if __name__ == '__main__':
    unittest.main()
