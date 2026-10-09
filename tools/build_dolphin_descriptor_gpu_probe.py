#!/usr/bin/env python3
"""Build an Android correctness probe from original and patched Dolphin methods."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NDK = Path('/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/ndk/27.0.12077973')
HOST = NDK / 'toolchains/llvm/prebuilt/darwin-x86_64/bin'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('batch_test',ROOT/'tools/tests/test_dolphin_descriptor_batches.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    sources=ROOT/'unified-android/native/tests'
    (out/'descriptor_constants.h').write_text(module.pool_constants())
    with tempfile.TemporaryDirectory(prefix='dolphin-gpu-methods-') as work:
        work=Path(work)
        original=(module.SOURCE/module.REL/'CommandBufferManager.cpp').read_text()
        for name in ('CommandBufferManager.cpp','CommandBufferManager.h'):
            dest=work/module.REL/name; dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes((module.SOURCE/module.REL/name).read_bytes())
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(module.PATCH)],cwd=work,check=True)
        cpp=(work/module.REL/'CommandBufferManager.cpp').read_text()
        header=(work/module.REL/'CommandBufferManager.h').read_text()
        (work/module.REL/'CommandBufferManager.cpp').write_text(original)
        error_patch=ROOT/'engines/patches/dolphin-libretro-descriptor-errors.patch'
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(error_patch)],cwd=work,check=True)
        fixed=(work/module.REL/'CommandBufferManager.cpp').read_text()
        structures='\n'.join(module.block(header,'struct '+n)+';' for n in ('DescriptorSetBatch','FrameResources'))
        pieces=[]
        for namespace,allocation in [('baseline',original),('candidate',cpp),('fixed',fixed)]:
            pieces.append('namespace '+namespace+' {\nclass CommandBufferManager { public:\n'+structures+'''
const u32 DESCRIPTOR_SETS_PER_POOL=1024;
std::array<FrameResources,3> m_frame_resources;
u32 m_current_frame=0, m_descriptor_set_count=1024;
FrameResources& GetCurrentFrameResources() { return m_frame_resources[m_current_frame]; }
VkDescriptorPool CreateDescriptorPool(u32);
VkDescriptorSet AllocateDescriptorSet(VkDescriptorSetLayout);
void ResetDescriptorPools();
};
'''+module.block(cpp,'VkDescriptorPool CommandBufferManager::CreateDescriptorPool(')+'\n'+
                module.block(allocation,'VkDescriptorSet CommandBufferManager::AllocateDescriptorSet(')+'\n'+
                module.block(cpp,'void CommandBufferManager::ResetDescriptorPools(')+'\n}\n')
        (out/'descriptor_methods.h').write_text('\n'.join(pieces))
    for binding in (0,1):
        spirv=out/('shader%d.spv'%binding)
        subprocess.run([str(NDK/'shader-tools/darwin-x86_64/glslc'),'-DBINDING_ID='+str(binding),
            str(sources/'descriptor_probe.comp'),'-o',str(spirv)],check=True)
        data=spirv.read_bytes(); words=struct.unpack('<%dI'%(len(data)//4),data)
        (out/('descriptor_shader%d.h'%binding)).write_text('static const uint32_t shader%d[]={%s};\n'%(
            binding,','.join(hex(word) for word in words)))
    binary=out/'descriptor-gpu-probe'
    subprocess.run([str(HOST/'aarch64-linux-android26-clang++'),'-std=c++20','-O2','-static-libstdc++',
        '-Wl,-z,max-page-size=16384','-I',str(out),str(sources/'dolphin_descriptor_gpu_probe.cpp'),
        '-lvulkan','-o',str(binary)],check=True)
    record={'binary':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'patchSha256':hashlib.sha256(module.PATCH.read_bytes()).hexdigest(),
            'errorPatchSha256':hashlib.sha256(error_patch.read_bytes()).hexdigest(),
            'poolConstants':module.pool_constants(),
            'defaultValuesPerVariant':1057*6,'frameSlots':3,'layoutsWithDifferentBindings':2,
            'gameplayTest':False,'noDeviceIdentifiersCollected':True}
    (out/'build-result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__': main()
