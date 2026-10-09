"""Compile the actual fixed-cache permission call for 4/16/64 KiB hosts.

No guest CPU code, structures or assembly offsets are reinterpreted. The test
uses the pinned source plus the checked-in patch and intercepts only sysconf
and mprotect. N64_HOST_PAGE_TEST_SOURCE can select the unpatched source to
demonstrate the pre-fix failure.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
REL = Path('mupen64plus-core/src/device/r4300/new_dynarec')
COMMIT = 'f275caf4b2bfa1e6d1c51636746ea793f3d80320'


class N64HostPageProtectionTest(unittest.TestCase):
    def test_recipe_pins_patch_and_both_linker_page_sizes(self):
        patch = ROOT / 'engines/patches/mupen64plus-next-host-page-protection.patch'
        recipe = (ROOT / 'engines/build_core.sh').read_text().split(
            '    mupen64plus-next)\n', 1)[1].split('    armsx2)', 1)[0]
        self.assertIn(str(patch.relative_to(ROOT)), recipe)
        self.assertIn(hashlib.sha256(patch.read_bytes()).hexdigest(), recipe)
        self.assertIn('-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384', recipe)

    def test_actual_permission_call_and_cleanup_cover_host_pages(self):
        with tempfile.TemporaryDirectory(prefix='n64-host-pages-') as temporary:
            work = Path(temporary)
            selected = os.environ.get('N64_HOST_PAGE_TEST_SOURCE')
            if selected:
                source = Path(selected)
            else:
                archive = ROOT / ('engines/build/sources/mupen64plus-next-' + COMMIT + '.tar.gz')
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                    '1810b7bbdc4abfdeee8a9f7f99c4a91dab601a228935802317c25a43d7cf9dbb')
                source = work / REL / 'new_dynarec.c'
                source.parent.mkdir(parents=True)
                with tarfile.open(archive) as tar:
                    names = [n for n in tar.getnames() if n.endswith('/' + str(REL / source.name))]
                    self.assertEqual(len(names), 1)
                    source.write_bytes(tar.extractfile(names[0]).read())
                patch = ROOT / 'engines/patches/mupen64plus-next-host-page-protection.patch'
                result = subprocess.run(['patch', '-p1', '-d', str(work), '-i', str(patch)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = source.read_text()
            # Test the actual selected ARM64 fixed-cache branch, not a copy of
            # its expected arithmetic or a grep for a new helper name.
            branch = text.split('#elif CACHE_ADDR==FIXED_CACHE_ADDR\n', 1)[1].split(
                '#else /*DYNAMIC_CACHE_ADDR*/', 1)[0]
            cleanup = text.split('void new_dynarec_cleanup(void)', 1)[1].split(
                'PROT_READ | PROT_WRITE);', 1)[0].rsplit('\n', 1)[1] + 'PROT_READ | PROT_WRITE);'
            header = source.with_name('host_memory.h')
            include = '#include "' + str(header) + '"\n' if header.exists() else ''
            harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <sys/mman.h>
#include <unistd.h>
typedef unsigned char u_char;
static long page_size;
static uintptr_t protected_start;
static size_t protected_size;
static int calls, syscall_result, protected_flags;
static long fake_sysconf(int key) { assert(key == _SC_PAGESIZE); return page_size; }
static int fake_mprotect(void *p, size_t n, int flags) {
    calls++; protected_start=(uintptr_t)p; protected_size=n; protected_flags=flags;
    assert(protected_start % page_size == 0);
    assert(protected_size % page_size == 0);
    return syscall_result;
}
#define __ANDROID__ 1
#define sysconf fake_sysconf
#define mprotect fake_mprotect
''' + include + r'''
#define TARGET_SIZE_2 25
static struct { struct { void *extra_memory; } r4300; } g_dev;
static void *base_addr, *base_addr_rx;
static void start(void) {
''' + branch + r'''
}
static void stop(void) {
''' + cleanup + r'''
}
int main(void) {
    const long sizes[] = {4096, 16384, 65536};
    for (unsigned i=0; i<3; i++) {
        page_size=sizes[i];
        for (uintptr_t offset=0; offset<(uintptr_t)page_size; offset+=4096) {
            uintptr_t address=0x10000000+offset;
            g_dev.r4300.extra_memory=(void*)address;
            calls=0; start();
            assert(calls==1 && base_addr==(void*)address && base_addr_rx==base_addr);
            assert(protected_start<=address);
            assert(protected_start+protected_size>=address+(1u<<TARGET_SIZE_2));
            assert(address-protected_start<(uintptr_t)page_size);
            assert(protected_start+protected_size-address-(1u<<TARGET_SIZE_2)<(uintptr_t)page_size);
            assert(protected_flags==(PROT_READ|PROT_WRITE|PROT_EXEC));
            uintptr_t prior_start=protected_start; size_t prior_size=protected_size;
            stop(); assert(calls==2 && protected_start==prior_start && protected_size==prior_size);
            assert(protected_flags==(PROT_READ|PROT_WRITE));
        }
    }
    return 0;
}
'''
            (work / 'test.c').write_text(harness)
            result = subprocess.run([shutil.which('clang'), '-std=c11', '-O1',
                '-fsanitize=address,undefined', str(work / 'test.c'), '-o', str(work / 'test')],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(work / 'test')], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
