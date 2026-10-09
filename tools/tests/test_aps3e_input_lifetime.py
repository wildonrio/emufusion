"""Compile the actual Android pad lifecycle/methods, not a replacement algorithm.

The environment is minimal; this proves the specified native input boundaries,
not PS3 gameplay or attribution of ICO's separate SPURS freeze.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / 'docs/qa/android-portability-2026-10-06-ps3-wide-pointer/native-source'
RELATIVE = Path('app/src/main/cpp')
PATCH = ROOT / 'engines/patches/aps3e-input-lifetime.patch'
NAMES = ('aps3e_emu.cpp', 'aps3e_rp3_impl.cpp')


def method(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def sources(patched):
    original = {name: (SNAPSHOT / RELATIVE / name).read_bytes() for name in NAMES}
    if not patched:
        return {name: payload.decode() for name, payload in original.items()}
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary) / RELATIVE
        folder.mkdir(parents=True)
        for name, payload in original.items():
            (folder / name).write_bytes(payload)
        subprocess.run(['git', 'apply', str(PATCH)], cwd=temporary, check=True)
        result = {name: (folder / name).read_text() for name in NAMES}
        subprocess.run(['git', 'apply', '--reverse', str(PATCH)], cwd=temporary, check=True)
        assert all((folder / name).read_bytes() == payload for name, payload in original.items())
    assert all((SNAPSHOT / RELATIVE / name).read_bytes() == payload for name, payload in original.items())
    return result


PREFIX = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <pthread.h>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
using u32 = unsigned;
thread_local int pad_lock_depth = 0;
struct shared_mutex {
    std::mutex mutex;
    std::atomic<int> attempts{0}, acquired{0};
    void lock() { ++attempts; mutex.lock(); assert(pad_lock_depth++ == 0); ++acquired; }
    void unlock() { assert(--pad_lock_depth == 0); mutex.unlock(); }
};
template<class T> struct atomic_t {
    std::atomic<T> value;
    atomic_t(T initial): value(initial) {}
    T observe() { return value.load(); }
    T operator=(T next) { value.store(next); return next; }
};
enum class pad_handler { keyboard, other };
bool expect_protected = false;
std::atomic<int> total_key_calls{0};
struct PadHandlerBase { virtual ~PadHandlerBase() = default; };
struct AndroidVirtualPadHandler: PadHandlerBase {
    int calls = 0;
    u32 last_code = 0;
    bool last_pressed = false, throw_key = false;
    int last_value = 0;
    std::function<void()> during_key;
    void Key(u32 code, bool pressed, int value) {
        if (expect_protected) assert(pad_lock_depth == 1);
        ++calls; last_code = code; last_pressed = pressed; last_value = value;
        ++total_key_calls;
        if (during_key) during_key();
        if (throw_key) throw std::runtime_error("injected Key failure");
    }
};
struct pad_thread {
    void* m_curthread;
    void* m_curwindow;
    std::map<pad_handler, std::shared_ptr<PadHandlerBase>> handlers;
    pad_thread(void*, void*, std::string_view);
    ~pad_thread();
    auto& get_handlers() {
        if (expect_protected) assert(pad_lock_depth == 1);
        return handlers;
    }
};
namespace pad {
    atomic_t<pad_thread*> g_current{nullptr};
    shared_mutex g_pad_mutex;
    std::string g_title_id;
    atomic_t<bool> g_started{false};
    pad_thread* get_current_handler(bool) { return g_current.observe(); }
}
template<class T> using named_thread = T;
struct registry {
    template<class T> T* try_get() { return pad::g_current.observe(); }
} registry_instance;
registry* g_fxo = &registry_instance;
namespace ae { pthread_mutex_t key_event_mutex = PTHREAD_MUTEX_INITIALIZER; }
'''

SUFFIX = r'''
bool unlocked() {
    const int status = pthread_mutex_trylock(&ae::key_event_mutex);
    // The old failing method left a mutex owned by this thread locked.
    // Release it for process cleanup; never intentionally crash/hang the Mac.
    pthread_mutex_unlock(&ae::key_event_mutex);
    return status == 0;
}
int main(int argc, char** argv) {
    assert(argc == 3);
    const int scenario = std::atoi(argv[1]);
    expect_protected = std::atoi(argv[2]);
    bool threw = false;
    if (scenario == 0) {
        for (int i = 0; i < 100; ++i) ae::key_event(i, false, 0);
        assert(unlocked());
    } else if (scenario == 1) {
        pad_thread thread(nullptr, nullptr, "startup");
        try { ae::key_event(1, true, 255); }
        catch (const std::out_of_range&) { threw = true; }
        const bool released = unlocked();
        std::printf("{\"missingHandlerThrew\":%s,\"inputMutexReleased\":%s}\n",
                    threw ? "true" : "false", released ? "true" : "false");
        return threw || !released ? 10 : 0;
    } else if (scenario == 2) {
        pad_thread thread(nullptr, nullptr, "wrong-handler");
        thread.handlers[pad_handler::keyboard] = std::make_shared<PadHandlerBase>();
        ae::key_event(1, true, 255);
        thread.handlers[pad_handler::keyboard] = nullptr;
        ae::key_event(1, false, 0);
        assert(unlocked());
    } else if (scenario == 3 || scenario == 4) {
        pad_thread thread(nullptr, nullptr, "running");
        auto handler = std::make_shared<AndroidVirtualPadHandler>();
        thread.handlers[pad_handler::keyboard] = handler;
        if (scenario == 4) {
            handler->throw_key = true;
            try { ae::key_event(1, true, 255); }
            catch (const std::runtime_error&) { threw = true; }
            assert(threw);
            const bool released = unlocked();
            std::printf("{\"inputMutexReleasedAfterException\":%s}\n", released ? "true" : "false");
            return released ? 0 : 10;
        }
        for (u32 code = 1; code <= 26; ++code) {
            ae::key_event(code, true, 129);
            assert(handler->last_code == code && handler->last_pressed && handler->last_value == 129);
            ae::key_event(code, false, 0);
            assert(handler->last_code == code && !handler->last_pressed && handler->last_value == 0);
        }
        assert(handler->calls == 52 && unlocked());
    } else if (scenario == 5) {
        auto previous = std::make_unique<pad_thread>(nullptr, nullptr, "old");
        auto next = std::make_unique<pad_thread>(nullptr, nullptr, "next");
        previous.reset();
        if (pad::g_current.observe() != next.get()) return 10;
        next.reset();
        assert(pad::g_current.observe() == nullptr);
        assert(pad::g_pad_mutex.acquired == 4);
    } else if (scenario == 6) {
        auto thread = std::make_unique<pad_thread>(nullptr, nullptr, "teardown");
        auto handler = std::make_shared<AndroidVirtualPadHandler>();
        thread->handlers[pad_handler::keyboard] = handler;
        std::atomic<bool> entered{false}, release{false}, destroyed{false};
        handler->during_key = [&] {
            entered = true;
            while (!release) std::this_thread::yield();
        };
        std::thread input([&] { ae::key_event(1, true, 255); });
        while (!entered) std::this_thread::yield();
        const int attempts = pad::g_pad_mutex.attempts;
        std::thread teardown([&] { thread.reset(); destroyed = true; });
        while (pad::g_pad_mutex.attempts == attempts) std::this_thread::yield();
        assert(!destroyed); // destructor reached the same lock; Key still owns it
        release = true;
        input.join(); teardown.join();
        assert(destroyed && pad::g_current.observe() == nullptr);
        ae::key_event(1, false, 0);
        assert(unlocked());
    } else if (scenario == 7) {
        std::atomic<bool> stop{false};
        std::thread input([&] {
            while (!stop) { ae::key_event(3, true, 64); ae::key_event(3, false, 0); }
        });
        for (int i = 0; i < 1000; ++i) {
            auto thread = std::make_unique<pad_thread>(nullptr, nullptr, "restart");
            const int before = total_key_calls;
            { // mirrors Init's existing lifetime mutex and handler-map rebuild
                std::lock_guard lock(pad::g_pad_mutex);
                thread->handlers.clear();
                thread->handlers[pad_handler::keyboard] = std::make_shared<AndroidVirtualPadHandler>();
            }
            // Every lifecycle must receive real Key traffic; scheduling the
            // worker only after all resets would be an empty stress test.
            while (total_key_calls == before) std::this_thread::yield();
            thread.reset();
        }
        stop = true; input.join();
        assert(unlocked() && pad::g_current.observe() == nullptr && total_key_calls >= 1000);
    } else return 99;
    assert(pad_lock_depth == 0);
    std::puts("{\"passed\":true}");
}
'''


@unittest.skipUnless(SNAPSHOT.is_dir() and shutil.which('c++'), 'source/compiler absent')
class InputLifetimeTest(unittest.TestCase):
    def run_cases(self, patched, scenarios):
        text = sources(patched)
        code = PREFIX
        code += method(text[NAMES[1]], 'pad_thread::pad_thread(') + '\n'
        code += method(text[NAMES[1]], 'pad_thread::~pad_thread()') + '\n'
        code += 'namespace ae {\n' + method(text[NAMES[0]], '    void key_event(') + '\n}\n'
        code += SUFFIX
        observations = []
        with tempfile.TemporaryDirectory() as temporary:
            source, binary = Path(temporary) / 'probe.cpp', Path(temporary) / 'probe'
            source.write_text(code)
            subprocess.run(['c++', '-std=c++20', '-pthread', '-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all', str(source), '-o', str(binary)], check=True)
            for scenario, expected in scenarios:
                result = subprocess.run([str(binary), str(scenario), str(int(patched))],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
                self.assertEqual(result.stderr, '')
                observations.append(json.loads(result.stdout) if result.stdout else {})
        return observations

    def test_current_missing_handler_throws_and_leaves_input_locked(self):
        rows = self.run_cases(False, [(1, 10)])
        self.assertEqual(rows, [dict(missingHandlerThrew=True, inputMutexReleased=False)])

    def test_current_handler_exception_leaves_input_locked(self):
        self.assertEqual(self.run_cases(False, [(4, 10)]), [dict(inputMutexReleasedAfterException=False)])

    def test_corrected_startup_missing_and_wrong_handlers_and_normal_controls(self):
        self.run_cases(True, [(i, 0) for i in range(5)])

    def test_corrected_constructor_teardown_and_concurrent_reinitialization(self):
        self.run_cases(True, [(i, 0) for i in range(5, 8)])


if __name__ == '__main__':
    unittest.main()
