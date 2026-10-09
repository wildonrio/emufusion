"""Run the shutdown unblocking policy with Eden's actual queue wait/pause bodies."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / 'engines/patches/eden-lucent-adapter.cpp'


class AudioShutdownTest(unittest.TestCase):
    def test_shutdown_releases_full_queue_without_draining_or_host_delivery(self):
        adapter = ADAPTER.read_text()
        helper = re.search(r'    void QuiesceShutdownStreams\(\) \{.*?\n    \}', adapter, re.S)
        self.assertIsNotNone(helper, 'shutdown must release DSP queue waiters before idling')
        stream = (ROOT / 'engines/build/switch-src/eden/src/audio_core/sink/sink_stream.cpp').read_text()
        methods = []
        for name in ('WaitFreeSpace', 'SignalPause'):
            method = re.search(r'void SinkStream::' + name + r'\(.*?\n\}', stream, re.S)
            self.assertIsNotNone(method)
            methods.append(method[0].replace('SinkStream::', ''))
        program = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <future>
#include <memory>
#include <mutex>
#include <stop_token>
#include <vector>
namespace Core { struct System { bool shutting=false; bool IsShuttingDown() const {return shutting;} }; }
struct Stream {
    std::mutex release_mutex;
    std::condition_variable_any release_cv;
    bool paused=false;
    int queued_buffers=99, max_queue_size=4;
''' + '\n'.join(methods) + r'''
    void Stop() { SignalPause(); }
};
struct Sink {
    std::atomic<Core::System*> system{nullptr};
    std::mutex streams_mutex;
    std::vector<std::unique_ptr<Stream>> streams;
''' + helper[0] + r'''
};
int main() {
    Sink sink; Core::System core;
    sink.streams.emplace_back(std::make_unique<Stream>());
    sink.QuiesceShutdownStreams(); assert(!sink.streams[0]->paused);
    sink.system=&core;
    sink.QuiesceShutdownStreams(); assert(!sink.streams[0]->paused);
    std::promise<void> entered;
    auto waiter=std::async(std::launch::async,[&]{ entered.set_value(); sink.streams[0]->WaitFreeSpace({}); });
    entered.get_future().wait();
    assert(waiter.wait_for(std::chrono::milliseconds(25))==std::future_status::timeout);
    core.shutting=true; sink.QuiesceShutdownStreams();
    assert(waiter.wait_for(std::chrono::seconds(1))==std::future_status::ready);
    waiter.get();
    assert(sink.streams[0]->queued_buffers==99);
    sink.QuiesceShutdownStreams(); assert(sink.streams[0]->paused);
}
'''
        compiler = shutil.which('clang++') or shutil.which('c++')
        with tempfile.TemporaryDirectory(prefix='eden-audio-shutdown-') as directory:
            path = Path(directory)
            (path / 'test.cpp').write_text(program)
            subprocess.run([compiler, '-std=c++20', '-pthread', str(path / 'test.cpp'),
                            '-o', str(path / 'test')], check=True)
            subprocess.run([str(path / 'test')], check=True, timeout=5)

    def test_pump_unblocks_before_idle_guard(self):
        source = ADAPTER.read_text().split('void Pump() {', 1)[1]
        self.assertLess(source.index('QuiesceShutdownStreams();'),
                        source.index('if (sink == nullptr || !IsConsuming())'))


if __name__ == '__main__':
    unittest.main()
