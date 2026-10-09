"""Execute the patched upstream allocator with controlled loader/FD outcomes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / 'engines/patches/flycast-android-shared-memory.patch'
SOURCE = ROOT / ('engines/build/sources/'
                 'flycast-d4fc0774107c4c307346b469499b9303a6ca0ffa')


class FlycastAndroidSharedMemoryTest(unittest.TestCase):
    def test_patch_identity_and_recipe(self):
        digest = hashlib.sha256(PATCH.read_bytes()).hexdigest()
        lock = json.loads((ROOT / 'engines/flycast-source-lock.json').read_text())
        entry, = [p for p in lock['patches'] if p['path'].endswith(PATCH.name)]
        self.assertEqual(entry['sha256'], digest)
        recipe = (ROOT / 'engines/build_core.sh').read_text()
        self.assertIn('engines/patches/' + PATCH.name + ' \\\n            ' + digest, recipe)

    def test_actual_allocator_modern_and_legacy_paths(self):
        if not SOURCE.is_dir():
            self.skipTest('Pinned Flycast source archive must be staged first')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'core/linux/posix_vmem.cpp'
            target.parent.mkdir(parents=True)
            shutil.copyfile(SOURCE / 'core/linux/posix_vmem.cpp', target)
            subprocess.run(['patch', '-p1', '-i', str(PATCH)], cwd=root,
                           check=True, capture_output=True)
            source = target.read_text()
            start = source.index('static int ashmem_create_region(')
            end = source.index('\n#endif', start)
            allocator = source[start:end]
            fixture = r'''
#include <cassert>
#include <cerrno>
#include <cstddef>
#include <cstring>
#define WARN_LOG(...) ((void)0)
#define ASHMEM_NAME_DEF "dev/ashmem"
#define ASHMEM_SET_SIZE 123
#define O_RDWR 2
#define RTLD_NOW 2
#define RTLD_LOCAL 0
using Create = int (*)(const char*, size_t);
static int creates, loads, symbols, unloads, opens, sizes, closes;
static int createResult=31, openResult=41, sizeResult=0;
static bool loadWorks=true, symbolWorks=true;
static int create(const char *name, size_t size) {
    assert(!strcmp(name,"RAM") && size==4096); ++creates; return createResult;
}
static Create ASharedMemory_create=nullptr;
static void *dlopen(const char *name, int flags) {
    assert(!strcmp(name,"libandroid.so") && flags==(RTLD_NOW|RTLD_LOCAL));
    ++loads; return loadWorks ? (void*)1 : nullptr;
}
static void *dlsym(void *handle, const char *name) {
    assert(handle==(void*)1 && !strcmp(name,"ASharedMemory_create"));
    ++symbols; return symbolWorks ? reinterpret_cast<void*>(&create) : nullptr;
}
static int dlclose(void *handle) { assert(handle==(void*)1); ++unloads; return 0; }
static int open(const char *name, int flags) {
    assert(!strcmp(name,"/dev/ashmem") && flags==O_RDWR); ++opens; return openResult;
}
static int ioctl(int fd, int operation, size_t size) {
    assert(fd==41 && operation==ASHMEM_SET_SIZE && size==4096); ++sizes; return sizeResult;
}
static int close(int fd) { assert(fd==41); ++closes; return 0; }
'''
            main = r'''
int main(int argc, char **argv) {
    assert(argc==2);
    int scenario=argv[1][0]-'0';
    if(scenario==0) ASharedMemory_create=&create;
    if(scenario==2) symbolWorks=false;
    if(scenario==3) loadWorks=false;
    if(scenario==4) createResult=-1;
    if(scenario==5) { createResult=-1; sizeResult=-1; }
    if(scenario==6) { loadWorks=false; openResult=-1; }
    int fd=ashmem_create_region("RAM",4096);
    assert(fd==(scenario<2 ? 31 : (scenario>=5 ? -1 : 41)));
    assert(creates==(scenario==0 || scenario==1 || scenario==4 || scenario==5));
    assert(loads==(scenario!=0));
    assert(symbols==(scenario!=0 && loadWorks));
    assert(unloads==symbols);
    assert(opens==(scenario>=2));
    assert(sizes==(scenario>=2 && scenario!=6));
    assert(closes==(scenario==5));
}
'''
            cpp = root / 'allocator.cpp'
            cpp.write_text(fixture + allocator + main)
            binary = root / 'allocator'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                            str(cpp), '-o', str(binary)], check=True)
            for scenario in range(7):
                with self.subTest(scenario=scenario):
                    subprocess.run([str(binary), str(scenario)], check=True)


if __name__ == '__main__':
    unittest.main()
