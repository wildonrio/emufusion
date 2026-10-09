"""Execute production poll/bind lock prefixes under real cross-thread contention."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/cpp/rife_benchmark_jni.cpp'


class NativeOutputContentionTest(unittest.TestCase):
    def test_poll_and_bind_return_pending_without_accessing_busy_context(self):
        source = SOURCE.read_text()
        destroy = source.index('Java_com_emufusion_rifebenchmark_NativeRifeBridge_nativeDestroy(')
        destroy_body = source.index('{', destroy) + 1
        destroy_prefix = source[destroy_body:source.index('    stop_timed_release_worker(context);', destroy_body)]
        for operation in ('Poll', 'Bind'):
            start = source.index('Java_com_emufusion_rifebenchmark_NativeRifeBridge_native' + operation + 'PreparedHardwareBufferRifeOutput(')
            body = source.index('{', start) + 1
            end = source.index('    SurfaceTransport* transport', body)
            prefix = source[body:end]
            harness = r'''
#include <mutex>
#include <thread>
#include <future>
#include <chrono>
#include <string>
#include <cassert>
std::mutex g_context_mutex;
std::mutex g_output_lifetime_mutex;
thread_local std::string g_last_error;
struct BenchmarkContext { std::mutex mutex; } instance;
int lookups = 0;
BenchmarkContext* checked_context(long handle) { ++lookups; return handle ? &instance : nullptr; }
struct Env { int GetArrayLength(void*) { return 23; } } environment;
int probe(long handle=1) {
    Env* env=&environment; void* values=&environment;
    long expected_proof_sequence=1; int texture_id=1;
    PREFIX
    return 1;
}
int retired = 0;
void retire() {
    long handle=1;
    DESTROY_PREFIX
    ++retired;
}
void contended(std::mutex& mutex, bool global) {
    std::promise<void> locked, release;
    auto released=release.get_future();
    std::thread worker([&] {
        std::lock_guard<std::mutex> guard(mutex);
        locked.set_value(); released.wait();
    });
    locked.get_future().wait();
    auto result=std::async(std::launch::async, [] { return probe(); });
    bool returned=result.wait_for(std::chrono::seconds(1))==std::future_status::ready;
    // Release even on failure so a blocking regression cannot hang the suite.
    release.set_value(); worker.join();
    assert(returned); assert(result.get()==(global ? 2 : 3));
    if(global) assert(lookups==0);
    assert(probe()==1);
}
int main() {
    contended(g_output_lifetime_mutex, true);
    contended(instance.mutex, false);
    // A different context may record under the shared model mutex while an
    // earlier output is polled/bound. It must not hide that completed output.
    std::promise<void> locked, release;
    auto released=release.get_future();
    std::thread recorder([&] {
        std::lock_guard<std::mutex> guard(g_context_mutex);
        locked.set_value(); released.wait();
    });
    locked.get_future().wait();
    auto access=std::async(std::launch::async, [] { return probe(); });
    bool ready=access.wait_for(std::chrono::seconds(1))==std::future_status::ready;
    release.set_value(); recorder.join();
    assert(ready); assert(access.get()==1);
    // Destruction cannot progress past its production ownership prefix while
    // an output access pins the context registry/lifetime.
    std::unique_lock<std::mutex> lifetime(g_output_lifetime_mutex);
    auto destroy=std::async(std::launch::async, [] { retire(); });
    assert(destroy.wait_for(std::chrono::milliseconds(50))==std::future_status::timeout);
    lifetime.unlock(); destroy.get(); assert(retired==1);
    assert(probe(0)==-1);
    assert(probe()==1);
}
'''.replace('    PREFIX', prefix).replace('    DESTROY_PREFIX', destroy_prefix)
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                unit = Path(directory) / 'probe.cpp'
                unit.write_text(harness)
                binary = Path(directory) / 'probe'
                for command in (['clang++', '-std=c++17', '-pthread', str(unit), '-o', str(binary)], [str(binary)]):
                    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
