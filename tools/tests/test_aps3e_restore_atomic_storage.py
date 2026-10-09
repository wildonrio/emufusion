"""Reproduce the restored-ID-map type mismatch with real RPCS3 pointer classes."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT/'engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/app/src/main/cpp/rpcs3/rpcs3'
FILES = {
    'sys_sync.h': 'Storage',
    'sys_memory.cpp': 'lv2_memory_container',
    'sys_event.cpp': 'lv2_obj',
    'sys_net.cpp': 'lv2_socket',
}


class RestoreAtomicStorageTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_actual_four_callback_assignments_and_reference_lifetime(self):
        fixture = (ROOT/'engines/diagnostics/lucent_restore_atomic_storage_test.cpp').read_text()
        patch = (ROOT/'engines/patches/aps3e-savestate-atomic-storage.patch').read_text()
        self.assertIn('std::array<stx::atomic_ptr<T>, T::id_count> vec_data',
                      (CORE/'Emu/IdManager.h').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            for filename, kind in FILES.items():
                original = (CORE/'Emu/Cell/lv2'/filename).read_text()
                old = '*static_cast<shared_ptr<'+kind+'>*>(storage) = ptr;'
                new = '*static_cast<atomic_ptr<'+kind+'>*>(storage) = ptr;'
                self.assertEqual(original.count(old), 1)
                self.assertIn(new, patch)
                for label, assignment in [('old',old),('fixed',new)]:
                    with self.subTest(file=filename, variant=label):
                        text = fixture.replace('using stx::atomic_ptr;',
                            'using stx::atomic_ptr; using '+kind+' = object;')
                        text = re.sub(r'#ifdef TEST_BROKEN.*?#endif', assignment, text, flags=re.S)
                        source=target/(filename+'.'+label+'.cpp')
                        binary=target/(filename+'.'+label)
                        source.write_text(text)
                        subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined',
                            '-I',str(CORE),str(source),'-o',str(binary)],check=True,
                            capture_output=True,text=True)
                        result=subprocess.run([str(binary)],capture_output=True,text=True)
                        if label=='old':
                            self.assertNotEqual(result.returncode,0)
                            self.assertIn('AddressSanitizer',result.stderr)
                            self.assertIn('atomic_ptr<object>::load()',result.stderr)
                        else:
                            self.assertEqual(result.returncode,0,result.stderr)

    def test_reported_tagged_pointer_decodes_to_exact_fault(self):
        # The observed raw pointer, decoded as though already packed, produces
        # the exact reference-counter address in the matching device tombstone.
        raw=0xb4000074b7b49920
        decoded=(raw & 0xff00000000000000) | ((raw >> 16) & 0x000000ffffffffff)
        self.assertEqual(decoded-8,0xb40000000074b7ac)
        packed=(raw & 0xff00000000000000) | ((raw & 0x000000ffffffffff) << 16)
        self.assertEqual((packed & 0xff00000000000000) | ((packed >> 16) & 0x000000ffffffffff),raw)


if __name__ == '__main__':
    unittest.main()
