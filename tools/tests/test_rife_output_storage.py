"""Compile the actual native output-storage predicate against minimal value types."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/cpp/rife_benchmark_jni.cpp'


class OutputStorageTest(unittest.TestCase):
    def test_actual_storage_predicate(self):
        text = SOURCE.read_text()
        body = text.split('bool prepared_output_storage_valid(', 1)[1].split(
            '\nbool finish_prepared_surface_output(', 1)[0]
        cpp = r'''
#include <cassert>
#include <vector>
#include <cstddef>
constexpr int VK_NULL_HANDLE=0;
struct Mat { bool missing=true; bool empty() const { return missing; } };
struct SurfaceControlOutputSlot {
    enum State {IDLE,PREPARING,READY};
    State state=PREPARING; void* buffer=nullptr; int image=0; Mat image_mat;
};
struct PreparedSurfaceOutput { Mat output; int surface_control_slot=-1; };
struct SurfaceTransport {
    bool surface_control_mode=false,app_owned_output_mode=false;
    std::vector<SurfaceControlOutputSlot> surface_control_outputs;
};
''' + 'bool prepared_output_storage_valid(' + body + r'''
int main() {
    SurfaceTransport t; PreparedSurfaceOutput p;
    assert(!prepared_output_storage_valid(nullptr,p));
    assert(!prepared_output_storage_valid(&t,p));
    p.output.missing=false;
    assert(prepared_output_storage_valid(&t,p));
    for (int mode=0;mode<2;++mode) {
        t.surface_control_mode=mode==0; t.app_owned_output_mode=mode==1;
        t.surface_control_outputs.clear(); p.surface_control_slot=0;
        assert(!prepared_output_storage_valid(&t,p));
        t.surface_control_outputs.emplace_back();
        auto& s=t.surface_control_outputs[0];
        s.buffer=&t; s.image=1; s.image_mat.missing=false;
        p.output.missing=true;
        assert(prepared_output_storage_valid(&t,p));
        s.state=SurfaceControlOutputSlot::READY;
        assert(!prepared_output_storage_valid(&t,p));
        s.state=SurfaceControlOutputSlot::PREPARING;
        s.image=0; assert(!prepared_output_storage_valid(&t,p)); s.image=1;
        s.buffer=nullptr; assert(!prepared_output_storage_valid(&t,p)); s.buffer=&t;
        s.image_mat.missing=true; assert(!prepared_output_storage_valid(&t,p));
        s.image_mat.missing=false;
        p.surface_control_slot=-1; assert(!prepared_output_storage_valid(&t,p));
        p.surface_control_slot=1; assert(!prepared_output_storage_valid(&t,p));
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'test.cpp'
            source.write_text(cpp)
            binary = Path(directory)/'test'
            subprocess.run(['c++','-std=c++17',str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
        completion = text.split('bool finish_prepared_surface_output(',1)[1]
        self.assertIn('!timing_ok || !proof_ok || !prepared_output_storage_valid(transport, prepared)',completion)


if __name__ == '__main__':
    unittest.main()
