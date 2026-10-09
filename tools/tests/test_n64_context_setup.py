"""Exercise the pinned N64 core's real context callbacks with a GLSM model."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_in_window_activity_recreation import java_block

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'engines/build/work/mupen64plus-next-arm64-v8a/libretro/libretro.c'


class N64ContextSetupTest(unittest.TestCase):
    def test_setup_is_repeated_after_each_destroy(self):
        source = SOURCE.read_text()
        callbacks = java_block(source, 'void context_reset(void)')
        callbacks += '\n' + java_block(source, 'static void context_destroy(void)')
        fixture = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#define CORE_NAME "test"
#define RETRO_LOG_DEBUG 0
enum { RDP_PLUGIN_GLIDEN64=1, GLSM_CTL_STATE_CONTEXT_RESET,
       GLSM_CTL_STATE_SETUP, GLSM_CTL_STATE_CONTEXT_DESTROY };
static int current_rdp_type=RDP_PLUGIN_GLIDEN64, setups, window_first;
static bool context_setup_first_init, emu_initialized, stale_bindings;
static void log_cb(int level, const char *message) {}
static void glsm_ctl(int op, void *data) {
    if(op==GLSM_CTL_STATE_CONTEXT_DESTROY) window_first=0;
    if(op==GLSM_CTL_STATE_SETUP) { setups++; stale_bindings=false; }
    // The real GLSM reset only performs setup itself when window_first>0.
    if(op==GLSM_CTL_STATE_CONTEXT_RESET) {
        if(window_first) { setups++; stale_bindings=false; }
        window_first=1;
    }
}
static void gln64DestroyGfxContext(void) { assert(!stale_bindings); }
static void gln64ReinitGfxContext(void) { assert(!stale_bindings); }
static void reinit_gfx_plugin(void) {}
'''
        checks = r'''
int main(void) {
    context_reset(); assert(setups==1 && context_setup_first_init);
    emu_initialized=true;
    for(int i=0; i<3; ++i) {
        context_destroy(); stale_bindings=true;
        assert(!context_setup_first_init);
        context_reset(); assert(setups==i+2 && !stale_bindings);
    }
    current_rdp_type=99;
    context_destroy(); context_reset();
    assert(setups==4 && context_setup_first_init);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            test = path / 'context.c'
            test.write_text(fixture + callbacks + checks)
            subprocess.run(['cc', '-std=c11', str(test), '-o', str(path/'test')], check=True)
            subprocess.run([str(path/'test')], check=True)


if __name__ == '__main__':
    unittest.main()
