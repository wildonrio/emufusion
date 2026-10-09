"""Execute Eden's actual output-pull body; this is not device/audio qualification."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EDEN = ROOT / "engines/build/switch-src/eden"


def function(source, name):
    start = source.index(name)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


HARNESS = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <mutex>
#include <span>
#include <string>
#include "common/ring_buffer.h"
#include "eden-lucent-audio-observation.h"
using s16 = int16_t;
using u64 = uint64_t;
__STRUCT__
struct SinkBuffer { u64 frames{}, frames_played{}, tag{}; bool consumed{}; };
struct Queue {
    std::deque<SinkBuffer> items;
    bool TryPop(SinkBuffer& out) {
        if (items.empty()) return false;
        out = items.front(); items.pop_front(); return true;
    }
};
struct Clock {
    std::chrono::nanoseconds GetGlobalTimeNs() { return std::chrono::nanoseconds(123); }
};
struct System {
    bool paused{}, shutting{};
    Clock clock;
    bool IsPaused() { return paused; }
    bool IsShuttingDown() { return shutting; }
    Clock& CoreTiming() { return clock; }
};
struct SinkStream {
    System system;
    Queue queue;
    Common::RingBuffer<s16, 64> samples_buffer;
    SinkBuffer playing_buffer;
    std::array<s16, 2> last_frame{7, 9};
    std::atomic<unsigned> queued_buffers{};
    std::mutex release_mutex, sample_count_lock;
    std::condition_variable release_cv;
    std::chrono::nanoseconds last_sample_count_update_time{};
    u64 min_played_sample_count{}, max_played_sample_count{};
    unsigned GetDeviceChannels() { return 2; }
    void ProcessAudioOutAndRender(std::span<s16>, std::size_t, OutputConsumption* = nullptr);
    void Add(unsigned frames, unsigned samples) {
        queue.items.push_back({frames, 0, 0, false}); ++queued_buffers;
        std::array<s16, 8> pcm{1, 2, 3, 4, 5, 6, 7, 8};
        samples_buffer.Push(pcm.data(), samples);
    }
};
__FUNCTION__
int main(int argc, char** argv) {
    assert(argc == 2);
    std::string scenario = argv[1];
    SinkStream stream;
    OutputConsumption pull{99, 99, 99, 99};
    std::array<s16, 8> output; output.fill(-99);
    if (scenario == "zero") {
        stream.ProcessAudioOutAndRender({}, 0, &pull);
        assert(pull.queued_frames == 0 && pull.copied_samples == 0);
        assert(pull.held_frames == 0 && pull.paused_frames == 0);
        assert(stream.last_frame[0] == 7);
        return 0;
    }
    if (scenario == "paused" || scenario == "shutdown") {
        stream.Add(4, 8);
        stream.system.paused = scenario == "paused";
        stream.system.shutting = scenario == "shutdown";
        stream.ProcessAudioOutAndRender(output, 4, &pull);
        assert(pull.paused_frames == 4 && pull.held_frames == 0);
        assert(pull.copied_samples == 0 && pull.queued_frames == 0);
        assert(stream.samples_buffer.Size() == 8);
        for (auto sample : output) assert(sample == 0);
        return 0;
    }
    if (scenario == "full" || scenario == "no-observer") stream.Add(4, 8);
    if (scenario == "partial") stream.Add(2, 4);
    if (scenario == "short-ring") stream.Add(4, 2);
    stream.ProcessAudioOutAndRender(output, 4, scenario == "no-observer" ? nullptr : &pull);
    if (scenario == "held") {
        assert(pull.held_frames == 4 && pull.queued_frames == 0 && pull.copied_samples == 0);
        assert(output[0] == 7 && output[7] == 9);
        assert(stream.max_played_sample_count == 0);
    } else if (scenario == "partial") {
        assert(pull.held_frames == 2 && pull.queued_frames == 2 && pull.copied_samples == 4);
        assert(output[0] == 1 && output[3] == 4 && output[4] == 7 && output[7] == 9);
        assert(stream.max_played_sample_count == 2);
    } else if (scenario == "short-ring") {
        assert(pull.queued_frames == 4 && pull.copied_samples == 2 && pull.held_frames == 0);
        // Expose the pre-existing discrepancy without calling these played frames.
        assert(stream.max_played_sample_count == 4);
        assert(output[0] == 1 && output[1] == 2 && output[2] == -99);
    } else {
        assert(scenario == "full" || scenario == "no-observer");
        if (scenario == "full") {
            assert(pull.queued_frames == 4 && pull.copied_samples == 8 && pull.held_frames == 0);
        }
        for (unsigned i = 0; i < 8; ++i) assert(output[i] == int(i + 1));
    }
    Lucent::AudioObservation window;
    window.Pull(4, 4, 8, 0, 0);
    window.Pull(4, 2, 4, 2, 0);
    window.Delivery(4, 3, true);
    assert(window.stream_frames == 8 && window.mixed_frames == 4);
    assert(window.queued_frames == 6 && window.copied_samples == 12 && window.held_frames == 2);
    assert(window.accepted_frames == 3 && window.rejected_frames == 1);
    window.Delivery(4, 0, false);
    window.Delivery(4, 5, true);
    assert(window.blocks == 3 && window.no_stream_blocks == 1 && window.invalid_returns == 1);
    assert(window.accepted_frames == 3 && window.rejected_frames == 9);
    window.Late(0, false); window.Late(10, false); window.Late(110, true);
    assert(window.late_blocks == 2 && window.resyncs == 1 && window.max_lateness_ns == 110);
}
'''


class EdenAudioObservationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++")
        if not cls.compiler:
            raise AssertionError("C++ compiler required")
        cls.temp = tempfile.TemporaryDirectory(prefix="eden-audio-observation-")
        cls.directory = Path(cls.temp.name)
        header = (EDEN / "src/audio_core/sink/sink_stream.h").read_text()
        struct = re.search(r"struct OutputConsumption \{.*?\n\};", header, re.S).group()
        body = function((EDEN / "src/audio_core/sink/sink_stream.cpp").read_text(),
                        "void SinkStream::ProcessAudioOutAndRender")
        cls.source = HARNESS.replace("__STRUCT__", struct).replace("__FUNCTION__", body)
        cls.executable = cls.compile(cls.source, "actual")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def compile(cls, source, name):
        path = cls.directory / (name + ".cpp")
        path.write_text(source)
        executable = cls.directory / name
        result = subprocess.run([cls.compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                 "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                 "-I", str(EDEN / "src"), "-I", str(ROOT / "engines/patches"),
                                 str(path), "-o", str(executable)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return executable

    def test_actual_pull_and_accounting(self):
        for scenario in ("zero", "paused", "shutdown", "held", "full", "partial",
                         "short-ring", "no-observer"):
            with self.subTest(scenario=scenario):
                result = subprocess.run([self.executable, scenario], capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_rejects_replacing_actual_sample_count_with_requested_count(self):
        old = "observation->copied_samples += copied_samples;"
        self.assertIn(old, self.source)
        mutation = self.source.replace(old,
            "(void)copied_samples; observation->copied_samples += frames_available * frame_size;")
        executable = self.compile(mutation, "false-accounting")
        result = subprocess.run([executable, "short-ring"], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Assertion", result.stderr)

    def test_adapter_records_actual_callback_return_without_claiming_playback(self):
        adapter = (ROOT / "engines/patches/eden-lucent-adapter.cpp").read_text()
        self.assertIn("ProcessAudioOutAndRender(pulled, kBlockFrames, &pull)", adapter)
        self.assertIn("const auto accepted = sink(sink_ctx, block.data(), kBlockFrames);", adapter)
        self.assertIn("observation.Delivery(kBlockFrames, accepted, any_stream);", adapter)
        self.assertIn("physicalPlayback=unverified", adapter)

    def test_observation_source_checkpoint_matches_and_does_not_claim_device_pass(self):
        lock = json.loads((ROOT / "engines/eden-source-lock.json").read_text())
        checkpoint = lock["audioObservationCheckpoint"]
        self.assertEqual("UNVERIFIED", checkpoint["deviceEvidenceStatus"])
        for row in checkpoint["sourceInputs"]:
            with self.subTest(path=row["path"]):
                data = (ROOT / row["path"]).read_bytes()
                self.assertEqual(row["sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(row["sizeBytes"], len(data))

    def test_repeat_apply_preserves_canonical_header_mtimes(self):
        targets = [EDEN / "src/common" / name for name in (
            "lucent_pacing.h", "lucent_source_image.h", "lucent_source_image_types.h",
            "lucent_audio_observation.h")]
        before = [path.stat().st_mtime_ns for path in targets]
        result = subprocess.run(["python3", str(ROOT / "engines/tools/apply_eden_timing_patch.py"),
                                 "--apply"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(before, [path.stat().st_mtime_ns for path in targets])


if __name__ == "__main__":
    unittest.main()
