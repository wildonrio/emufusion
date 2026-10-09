"""Exercise the patched Mesen-S firmware-failure branch, not a rewritten model."""
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'engines/build/sources/mesen-s-1d475abd174d16ecb1fb030961ff26076ab51ee6.tar.gz'
PATCH = ROOT / 'engines/patches/mesen-s-dsp1-fallback.patch'


class MesenDspFallbackTest(unittest.TestCase):
    def test_actual_branch_preserves_firmware_and_limits_hle_types(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-mesen-dsp-') as tmp:
            directory = Path(tmp)
            source = directory / 'Core/BaseCartridge.cpp'
            source.parent.mkdir()
            with tarfile.open(ARCHIVE) as archive:
                entry = next(n for n in archive.getmembers()
                             if n.name.endswith('/Core/BaseCartridge.cpp'))
                original = archive.extractfile(entry).read().decode()
            source.write_text(original)
            subprocess.run(['patch', '-s', '-d', tmp, '-p1', '-i', str(PATCH)], check=True)
            patched = source.read_text()
            start = patched.index('bool hle =', patched.index('void BaseCartridge::InitCoprocessor()'))
            end = patched.index('if(_coprocessorType == CoprocessorType::SA1)', start)
            branch = patched[start:end]
            template = r'''
                #include <memory>
                #include <vector>
                #include <cassert>
                enum class CoprocessorType {DSP1, DSP1B, DSP2, DSP3, DSP4, ST010};
                struct Base {virtual ~Base()=default;};
                struct Settings {bool EnableHleCoprocessor=false;
                    Settings& GetEmulationConfig(){return *this;}};
                struct Console {Settings settings; Settings* GetSettings(){return &settings;}};
                static bool firmwareAvailable; static int hleCalls;
                struct NecDsp:Base {
                    static Base* InitCoprocessor(CoprocessorType,Console*,std::vector<int>&){
                        return firmwareAvailable ? new NecDsp : nullptr;
                    }
                };
                struct NecDspHle:Base {
                    static Base* InitCoprocessor(CoprocessorType,Console*) {
                        ++hleCalls; return new NecDspHle;
                    }
                };
                struct Cartridge {
                    Console c; Console* _console=&c; CoprocessorType _coprocessorType;
                    std::unique_ptr<Base> _coprocessor; NecDsp* _necDsp=nullptr;
                    std::vector<int> _embeddedFirmware;
                    void init(){BRANCH}
                };
                int main(){
                    for(auto type:{CoprocessorType::DSP1,CoprocessorType::DSP1B}){
                        firmwareAvailable=false; hleCalls=0;
                        Cartridge c; c._coprocessorType=type; c.init();
                        assert(dynamic_cast<NecDspHle*>(c._coprocessor.get()));
                        assert(!c._necDsp && hleCalls==1);
                        firmwareAvailable=true; hleCalls=0;
                        Cartridge low; low._coprocessorType=type; low.init();
                        assert(low._necDsp && hleCalls==0);
                    }
                    for(auto type:{CoprocessorType::DSP2,CoprocessorType::DSP3,
                                   CoprocessorType::DSP4,CoprocessorType::ST010}){
                        firmwareAvailable=false; hleCalls=0;
                        Cartridge c; c._coprocessorType=type; c.init();
                        assert(!c._coprocessor && hleCalls==0);
                    }
                }
            '''
            harness = directory / 'test.cpp'
            harness.write_text(template.replace('BRANCH', branch))
            executable = directory / 'test'
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            str(harness), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)
            # The same assertions must reject the exact upstream branch.
            old_start = original.index('bool hle =', original.index('void BaseCartridge::InitCoprocessor()'))
            old_end = original.index('if(_coprocessorType == CoprocessorType::SA1)', old_start)
            harness.write_text(template.replace('BRANCH', original[old_start:old_end]))
            subprocess.run(['c++', '-std=c++17', str(harness), '-o', str(executable)], check=True)
            self.assertNotEqual(subprocess.run([str(executable)], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
