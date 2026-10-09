"""Regression for failed descriptor allocations returning non-null output handles.

The real Android GPU probe reproduces this at allocation1025. This executable
recording-driver test also covers hard failures and bounded fresh-pool failure.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests import test_dolphin_descriptor_batches as batch

PATCH=batch.ROOT/'engines/patches/dolphin-libretro-descriptor-errors.patch'

class DescriptorErrorsTest(unittest.TestCase):
    def test_original_fails_and_corrected_methods_pass(self):
        with tempfile.TemporaryDirectory(prefix='dolphin-descriptor-errors-') as directory:
            directory=Path(directory)
            for name in ('CommandBufferManager.cpp','CommandBufferManager.h'):
                target=directory/batch.REL/name; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((batch.SOURCE/batch.REL/name).read_bytes())
            original=(directory/batch.REL/'CommandBufferManager.cpp').read_text()
            subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(PATCH)],
                           cwd=directory,check=True,capture_output=True)
            fixed=(directory/batch.REL/'CommandBufferManager.cpp').read_text()
            # The existing test's driver/pool reset fixture supplies shared scaffolding.
            (directory/batch.REL/'CommandBufferManager.cpp').write_text(original)
            subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(batch.PATCH)],
                           cwd=directory,check=True,capture_output=True)
            batched=(directory/batch.REL/'CommandBufferManager.cpp').read_text()
            header=(directory/batch.REL/'CommandBufferManager.h').read_text()
            fixture=batch.harness(batched,header).split('int main() {')[0]
            signature='VkDescriptorSet CommandBufferManager::AllocateDescriptorSet('
            # Shared driver deliberately poisons failed output handles, as ranchu did.
            self.assertIn('out[i]=handle<VkDescriptorSet>(999999)', fixture)
            main=r'''
static void require(bool ok) { if (!ok) std::exit(42); }
int main() {
 const auto layout=handle<VkDescriptorSetLayout>(2);
 for (auto exhausted : {VK_ERROR_FRAGMENTED_POOL, VK_ERROR_OUT_OF_POOL_MEMORY}) {
   fresh_driver(); CommandBufferManager manager;
   require(manager.AllocateDescriptorSet(layout)!=VK_NULL_HANDLE);
   injected={exhausted,VK_SUCCESS};
   auto set=manager.AllocateDescriptorSet(layout);
   require(sets.contains(set)); // A phantom failed handle must never escape.
   require(creates==2 && calls.size()==3);
 }
 for (auto hard : {VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY,VK_ERROR_DEVICE_LOST}) {
   fresh_driver(); CommandBufferManager manager;
   injected={hard};
   require(manager.AllocateDescriptorSet(layout)==VK_NULL_HANDLE);
   require(creates==1 && calls.size()==1 && errors==1);
 }
 {
   fresh_driver(); CommandBufferManager manager;
   injected={VK_ERROR_FRAGMENTED_POOL,VK_ERROR_FRAGMENTED_POOL};
   require(manager.AllocateDescriptorSet(layout)==VK_NULL_HANDLE);
   require(creates==1 && calls.size()==1);
 }
 {
   fresh_driver(); CommandBufferManager manager; fail_create=true;
   require(manager.AllocateDescriptorSet(layout)==VK_NULL_HANDLE);
   require(creates==1 && manager.m_descriptor_set_count==1024);
 }
 {
   fresh_driver(); CommandBufferManager manager;
   auto& r=manager.GetCurrentFrameResources();
   r.descriptor_pools={manager.CreateDescriptorPool(1),manager.CreateDescriptorPool(10)};
   require(manager.AllocateDescriptorSet(layout)!=VK_NULL_HANDLE);
   require(manager.AllocateDescriptorSet(layout)!=VK_NULL_HANDLE);
   require(creates==2 && r.current_descriptor_pool_index==1);
 }
}
'''
            for name,implementation,expected in [('original',original,42),('fixed',fixed,0)]:
                source=fixture.replace(batch.block(batched,signature),batch.block(implementation,signature))
                unit=directory/(name+'.cpp'); unit.write_text('#include <cstdlib>\n'+source+main)
                binary=directory/name
                subprocess.run(['clang++','-std=c++20','-fsanitize=address,undefined',
                                '-I',str(batch.HEADERS),str(unit),'-o',str(binary)],
                               check=True,capture_output=True)
                result=subprocess.run([str(binary)],capture_output=True,timeout=15)
                self.assertEqual(result.returncode,expected,result.stderr.decode())

if __name__=='__main__': unittest.main()
