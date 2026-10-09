// SPDX-License-Identifier: GPL-3.0-or-later
//
// Lucent Phase 3 native adapter for the Eden Switch engine.
//
// This translation unit is compiled INTO Eden's own libyuzu-android.so and is
// the only symbol Lucent calls: lucent_native_adapter_entry(). It drives
// EmulationSession directly, so the engine runs inside Lucent's process, in
// Lucent's window, with no Eden Activity, no second task, and no emulator UI.
//
// Eden owns its emulation loop (RunEmulation blocks until halted), so the
// adapter runs it on one engine thread and reports liveness from run_frame().
// That satisfies the ABI contract -- Lucent still owns the surface, audio sink
// ownership, pause/resume, save flushing, and teardown ordering.
//
// THE WHOLE SESSION LIVES ON THAT ONE ENGINE THREAD. Eden's own Android
// frontend runs bring-up, the loop and teardown as a single function body on a
// single thread (jni/native.cpp's static RunEmulation(): a SCOPE_EXIT calling
// ShutdownEmulation, then InitializeEmulation, then RunEmulation), and
// NativeLibrary.stopEmulation() from its UI only sets the halt flag. The
// adapter used to spread that across three different host threads -- Lucent's
// render owner called InitializeEmulation, a private thread called
// RunEmulation, and Lucent's lifecycle executor called ShutdownEmulation after
// joining that thread. Eden's kernel is not thread-agnostic here: every host
// thread that reaches into it gets a lazily created dummy KThread held in
// KernelCore's thread_local storage, and that KThread is registered with the
// kernel by its constructor but is only unregistered by a refcount drop -- so
// when a host thread exits, the KThread backing its kernel identity is
// destroyed while the kernel still holds the pointer. Joining the emulation
// thread and only THEN calling ShutdownEmulation destroyed the identity that
// had brought the guest kernel up, and then asked a different thread to tear
// that kernel down. That teardown either hung with the guest half terminated
// or faulted inside KThread::Finalize -> KProcess::DeleteThreadLocalRegion ->
// KLightLock::UnlockSlowPath -> KThread::EndWait, which is the same shape:
// kernel bookkeeping pointing at a thread object that is no longer there.
//
// So: start() hands the boot to the engine thread and waits for its result,
// and stop() only signals and joins. Teardown now runs on the same thread that
// ran the guest, before that thread's kernel identity is destroyed, exactly as
// upstream does it.
//
// Firmware and keys are never bundled: load() fails closed unless Lucent hands
// over a validated system directory that Eden can read them from.

#include <cmath>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <limits>
#include <list>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include <android/native_window.h>
#include <dlfcn.h>

#include "lucent_native_adapter.h"

extern "C" const lucent_native_adapter* lucent_native_adapter_entry(void);

#include "audio_core/common/common.h"
#include "audio_core/sink/sink.h"
#include "audio_core/sink/sink_stream.h"
#include "common/fs/path_util.h"
#include "common/logging.h"
#include "common/settings.h"
#include "common/settings_enums.h"
#include "common/thread.h"
#include "common/lucent_pacing.h"
#include "common/lucent_audio_observation.h"
#include "common/lucent_source_image.h"
#include "core/core.h"
#include "core/core_timing.h"
#include "core/perf_stats.h"
#include "input_common/drivers/virtual_gamepad.h"
#include "input_common/main.h"
#include "jni/native.h"
#include "video_core/renderer_base.h"

// Installed by the local patch to src/audio_core/sink/sink_details.cpp, which is
// recorded in engines/eden-source-lock.json. It is declared here rather than in
// Eden's own header so the patch stays confined to a single vendored file; the
// parameter type is part of a function's mangled name, so if the two ever drift
// apart this fails to link instead of silently mismatching.
namespace AudioCore::Sink {
void SetLucentSinkFactory(SinkPtr (*factory)());
} // namespace AudioCore::Sink

namespace {

constexpr const char* kEngineId = "eden";
constexpr const char* kEngineVersion = "eden-v0.2.0";

// Settings::values.players (Settings::values.players.GetValue()) is a
// std::array<PlayerInput, 10> mirroring HID's NPad slots, but the guest-visible
// NPad handheld/standard styles only ever address Player1..Player8 -- indices
// 8 and 9 back Handheld and Debug pads Lucent never routes local input to.
// This is also the controller_index ceiling adapter_describe() advertises via
// lucent_native_capabilities::max_controllers, so the two must stay in sync.
constexpr std::size_t kMaxLocalControllers = 8;

} // namespace

struct lucent_native_engine {
    std::thread emulation_thread;
    std::atomic<bool> started{false};
    std::atomic<bool> loaded{false};
    ANativeWindow* window{nullptr};
    // Pins GPU/renderer lifetime across lifecycle requests. The session thread
    // acquires this before ShutdownEmulation, but stop releases it before join.
    // GPU callbacks never acquire it, avoiding a wait-back cycle.
    std::mutex presentation_api_mutex;
    // InitializeEmulation builds the render window, so it cannot run until
    // Lucent has handed us a surface. load() therefore only prepares the
    // system and keeps the content path for start().
    std::string content_path;

    // Boot handshake. start() has to report a real load failure to Lucent, but
    // the load itself now happens on the engine thread, so start() blocks here
    // until that thread has published a status. It blocks for exactly as long
    // as it used to spend inside InitializeEmulation on the calling thread.
    std::mutex boot_mutex;
    std::condition_variable boot_cv;
    bool boot_published{false};
    Core::SystemResultStatus boot_status{Core::SystemResultStatus::ErrorNotInitialized};
};

/**
 * Directory the adapter itself was loaded from, which is also where the
 * Vulkan driver hook libraries sit. Derived from our own symbol rather than
 * passed in, so the ABI does not need to carry an Android-specific path.
 */
static std::string adapter_library_directory() {
    Dl_info info{};
    if (dladdr(reinterpret_cast<const void*>(&lucent_native_adapter_entry), &info) == 0 ||
        info.dli_fname == nullptr) {
        return std::string();
    }
    const std::string path(info.dli_fname);
    const auto separator = path.find_last_of('/');
    return separator == std::string::npos ? std::string() : path.substr(0, separator);
}

// ---------------------------------------------------------------------------
// Audio.
//
// Lucent owns the output device. The ABI hands us `audio_sink`, which is backed
// by an AudioTrack that Lucent creates, plays and pauses with the session, and
// drains on its own render thread. So the engine must not open a device of its
// own: Eden's Oboe backend talks straight to OpenSL ES, which both leaves
// Lucent's track starved (the "disabled due to previous underrun" spam) and is
// unsafe here, because OboeSinkStream is destroyed through Sink::CloseStream
// without anything ever calling oboe::AudioStream::close() -- Oboe's own
// destructors are no-ops, so a guest that ends an audio session leaves an
// OpenSL ES buffer-queue callback firing into freed memory.
//
// The adapter therefore supplies Eden with a real AudioCore sink rather than
// tapping one. Eden's SinkStream base class already does the channel down-mix,
// the volume, the buffer-release accounting and the played-sample clock the
// guest reads back; its pull model (ProcessAudioOutAndRender) is what paces
// audio. We do what OboeSinkStream does, with Lucent's AudioTrack as the device.
//
// One difference matters. Oboe gives every stream its own OpenSL stream and lets
// AudioFlinger mix them; Lucent's ABI is a single PCM sink, and the guest really
// can have several output streams open at once (the renderer plus any number of
// audout sessions). So the CLOCK LIVES IN THE SINK, not the stream: one pump
// thread pulls a block from every playing stream, sums them, and pushes one
// block. A pump per stream would push a multiple of real time into one ring and
// interleave two streams instead of mixing them.
// ---------------------------------------------------------------------------

namespace {

// Lucent's sink, published by start() and cleared by stop(). The pump reads it
// on every block so a session that ends mid-block simply stops pushing, rather
// than writing into a context Lucent has already released.
std::atomic<lucent_native_audio_sink> g_audio_sink{nullptr};
std::atomic<void*> g_audio_sink_ctx{nullptr};

// Lucent's track is 48 kHz interleaved stereo s16, which is also Eden's own
// TargetSampleRate, so nothing here resamples.
constexpr u32 kLucentChannels = 2;
// One block is Eden's own 5 ms audio quantum, so we consume at the rate the
// renderer produces and never have to guess at a buffer size.
constexpr u32 kBlockFrames = AudioCore::TargetSampleCount;
constexpr u32 kBlockSamples = kBlockFrames * kLucentChannels;
constexpr std::chrono::nanoseconds kBlockPeriod{1'000'000'000LL * kBlockFrames /
                                                AudioCore::TargetSampleRate};
// Past this much lateness the scheduler starved us for longer than Lucent's
// track can absorb, so the backlog is dropped rather than pushed as a burst.
constexpr std::chrono::milliseconds kResyncAfter{100};

class LucentSinkStream final : public AudioCore::Sink::SinkStream {
public:
    LucentSinkStream(Core::System& system_, AudioCore::Sink::StreamType type_,
                     const std::string& name_, u32 system_channels_)
        : SinkStream(system_, type_) {
        name = name_;
        system_channels = system_channels_;
        device_channels = kLucentChannels;
    }
    ~LucentSinkStream() override = default;

    /// Whether the sink should pull a block from this stream. Capture streams
    /// have no device behind them -- Lucent's ABI carries no microphone, so the
    /// base class hands the guest silence instead.
    bool IsPlayingOutput() const {
        return type != AudioCore::Sink::StreamType::In && !IsPaused();
    }

    void Start(bool resume = false) override {
        (void)resume;
        if (!paused) {
            return;
        }
        paused = false;
    }

    void Stop() override {
        if (paused) {
            return;
        }
        // Unblocks the ADSP, which may be waiting on us for queue space.
        SignalPause();
    }
};

class LucentSink final : public AudioCore::Sink::Sink {
public:
    LucentSink() {
        device_channels = kLucentChannels;
    }

    // The pump dereferences both the streams and the Core::System behind them,
    // and Eden tears sinks down while the guest is still running, so it is
    // joined before anything it touches is released. This is exactly what
    // OboeSinkStream fails to do with its OpenSL ES callback.
    ~LucentSink() override {
        stopping.store(true, std::memory_order_release);
        if (pump.joinable()) {
            pump.join();
        }
        std::scoped_lock lock{streams_mutex};
        streams.clear();
    }

    AudioCore::Sink::SinkStream* AcquireSinkStream(Core::System& system_, u32 system_channels_,
                                                   const std::string& name,
                                                   AudioCore::Sink::StreamType type) override {
        std::scoped_lock lock{streams_mutex};
        system.store(&system_, std::memory_order_release);
        auto& stream = streams.emplace_back(
            std::make_unique<LucentSinkStream>(system_, type, name, system_channels_));
        // Eden builds two sinks and DeviceSession routes capture to the input
        // one, so only the sink that is handed a playable stream starts a clock.
        // The input sink must never push into Lucent's single output ring, or
        // the device would be fed at twice real time.
        if (type != AudioCore::Sink::StreamType::In && !pump.joinable()) {
            pump = std::thread(&LucentSink::Pump, this);
        }
        return stream.get();
    }

    void CloseStream(AudioCore::Sink::SinkStream* to_remove) override {
        std::scoped_lock lock{streams_mutex};
        streams.remove_if([&](auto& stream) { return stream.get() == to_remove; });
    }

    void CloseStreams() override {
        std::scoped_lock lock{streams_mutex};
        streams.clear();
    }

    f32 GetDeviceVolume() const override {
        std::scoped_lock lock{streams_mutex};
        return streams.empty() ? 1.0f : streams.front()->GetDeviceVolume();
    }

    void SetDeviceVolume(f32 volume) override {
        std::scoped_lock lock{streams_mutex};
        for (auto& stream : streams) {
            stream->SetDeviceVolume(volume);
        }
    }

    void SetSystemVolume(f32 volume) override {
        std::scoped_lock lock{streams_mutex};
        for (auto& stream : streams) {
            stream->SetSystemVolume(volume);
        }
    }

private:
    void QuiesceShutdownStreams() {
        Core::System* const current = system.load(std::memory_order_acquire);
        if (current == nullptr || !current->IsShuttingDown()) {
            return;
        }
        // Shutdown waits for audio service finalization, which waits for the
        // DSP. The DSP may already be blocked in WaitFreeSpace when shutdown
        // disables this pump. SignalPause releases that wait without consuming
        // queued audio or delivering it to a retiring host AudioTrack.
        std::scoped_lock lock{streams_mutex};
        for (auto& stream : streams) {
            stream->Stop();
        }
    }

    /// True while Lucent is actually consuming. Lucent stops draining the ring
    /// when it pauses the session, so pushing during a pause would queue a
    /// backlog that plays back as a delay on resume rather than as silence.
    bool IsConsuming() const {
        Core::System* const current = system.load(std::memory_order_acquire);
        return current != nullptr && !current->IsPaused() && !current->IsShuttingDown();
    }

    void Pump() {
        Common::SetCurrentThreadName("LucentAudioOut");
        constexpr s32 kMin = std::numeric_limits<s16>::min();
        constexpr s32 kMax = std::numeric_limits<s16>::max();
        std::array<s32, kBlockSamples> mix{};
        std::array<s16, kBlockSamples> pulled{};
        std::array<s16, kBlockSamples> block{};
        auto deadline = std::chrono::steady_clock::now();
        Lucent::AudioObservation observation{};

        while (!stopping.load(std::memory_order_acquire)) {
            QuiesceShutdownStreams();
            const auto sink = g_audio_sink.load(std::memory_order_acquire);
            void* const sink_ctx = g_audio_sink_ctx.load(std::memory_order_acquire);
            if (sink == nullptr || !IsConsuming()) {
                // Idle without draining the guest's queued buffers, and restart
                // the clock so resuming does not emit a catch-up burst.
                std::this_thread::sleep_for(std::chrono::milliseconds{5});
                deadline = std::chrono::steady_clock::now();
                continue;
            }

            mix.fill(0);
            bool any_stream = false;
            {
                std::scoped_lock lock{streams_mutex};
                for (auto& stream : streams) {
                    auto* const output = static_cast<LucentSinkStream*>(stream.get());
                    if (!output->IsPlayingOutput()) {
                        continue;
                    }
                    any_stream = true;
                    AudioCore::Sink::OutputConsumption pull{};
                    output->ProcessAudioOutAndRender(pulled, kBlockFrames, &pull);
                    observation.Pull(kBlockFrames, pull.queued_frames, pull.copied_samples,
                                     pull.held_frames, pull.paused_frames);
                    for (u32 index = 0; index < kBlockSamples; ++index) {
                        mix[index] += pulled[index];
                    }
                }
            }
            for (u32 index = 0; index < kBlockSamples; ++index) {
                block[index] = static_cast<s16>(std::clamp(mix[index], kMin, kMax));
            }
            // With nothing playing this is a block of silence, which is the
            // right thing to send: it keeps Lucent's track fed at real time
            // instead of letting it underrun between audio sessions.
            const auto accepted = sink(sink_ctx, block.data(), kBlockFrames);
            observation.Delivery(kBlockFrames, accepted, any_stream);

            deadline += kBlockPeriod;
            const auto now = std::chrono::steady_clock::now();
            const auto late_ns = now > deadline
                ? std::chrono::duration_cast<std::chrono::nanoseconds>(now - deadline).count() : 0;
            observation.Late(static_cast<uint64_t>(late_ns), now - deadline > kResyncAfter);
            if (observation.blocks % 200 == 0) {
                // Bracket the clock read. Multicore CoreTiming is wall-derived,
                // not proof of guest work or an image's logical retirement time.
                const auto host_before = Lucent::SourceMonotonicNs();
                const auto core_ns = system.load(std::memory_order_acquire)
                    ->CoreTiming().GetGlobalTimeNs().count();
                const auto host_after = Lucent::SourceMonotonicNs();
                LOG_INFO(Audio_Sink,
                    "EmuFusion audio observation blocks={} streamFrames={} queuedFrames={} "
                    "copiedSamples={} heldFrames={} pausedFrames={} noStreamBlocks={} "
                    "mixedFrames={} acceptedFrames={} rejectedFrames={} invalidReturns={} "
                    "lateBlocks={} resyncs={} maxLateNs={} hostBeforeNs={} coreNs={} "
                    "hostAfterNs={} multicore={} viBaseHz={:.9f} physicalPlayback=unverified",
                    observation.blocks, observation.stream_frames, observation.queued_frames,
                    observation.copied_samples, observation.held_frames, observation.paused_frames,
                    observation.no_stream_blocks, observation.mixed_frames, observation.accepted_frames,
                    observation.rejected_frames, observation.invalid_returns, observation.late_blocks,
                    observation.resyncs, observation.max_lateness_ns, host_before, core_ns, host_after,
                    Settings::values.use_multi_core.GetValue(), Lucent::BaseVsyncHz());
            }
            if (deadline > now) {
                std::this_thread::sleep_until(deadline);
            } else if (now - deadline > kResyncAfter) {
                deadline = now;
            }
        }
    }

    mutable std::mutex streams_mutex;
    std::list<AudioCore::Sink::SinkStreamPtr> streams;
    std::atomic<Core::System*> system{nullptr};
    std::thread pump;
    std::atomic<bool> stopping{false};
};

AudioCore::Sink::SinkPtr make_lucent_sink() {
    return std::make_unique<LucentSink>();
}

} // namespace

static void adapter_describe(lucent_native_capabilities* out) {
    if (out == nullptr) {
        return;
    }
    std::memset(out, 0, sizeof(*out));
    out->abi_version = LUCENT_NATIVE_ADAPTER_ABI_VERSION;
    out->engine_id = kEngineId;
    out->engine_version = kEngineVersion;
    // Eden exposes no deterministic, migration-safe full-state API, so Lucent
    // must not advertise Quick Resume for Switch. Held-Stop flushes the game's
    // own saves and exits instead of promising a snapshot it cannot restore.
    out->has_quick_resume = false;
    out->has_persistent_save = true;
    // The Switch is a single-screen target on the Thor; the GamePad/lower
    // display is not used by this engine.
    out->dual_screen = false;
    // Console keys plus a system firmware archive, both user-supplied.
    out->required_firmware = 2;
    // adapter_load() connects and adapter_set_control() routes exactly
    // Player1..Player8 (players[0..kMaxLocalControllers-1]); see the
    // kMaxLocalControllers comment for why the underlying 10-slot array stops
    // short of that.
    out->max_controllers = kMaxLocalControllers;
}

static lucent_native_engine* adapter_create(void) {
    return new (std::nothrow) lucent_native_engine();
}

static bool adapter_load(lucent_native_engine* engine,
                         const lucent_native_load_request* request,
                         char* error, size_t error_size) {
    const auto fail = [&](const char* message) {
        if (error != nullptr && error_size > 0) {
            std::snprintf(error, error_size, "%s", message);
        }
        return false;
    };
    if (engine == nullptr || request == nullptr) {
        return fail("adapter load received no engine or request");
    }
    if (request->content_path == nullptr || request->content_path[0] == '\0') {
        return fail("no Switch content path was supplied");
    }
    if (request->system_directory == nullptr || request->system_directory[0] == '\0') {
        // Keys/firmware live under this root. Refuse rather than booting into
        // an undecryptable state that would look like a hang.
        return fail("no validated key/firmware directory was supplied");
    }

    // Keep the embedded runtime on translated guest execution with address
    // checks. Selecting Dynarmic alone is insufficient: Eden's default Auto
    // accuracy sets fastmem_address_space_bits=64, bypassing the ARM64 emitter's
    // guest-range branch. Accurate preserves the actual process address width,
    // disables unsafe FP optimizations, and retains in-range fastmem access.
    // EmulationSession does not read the standalone frontend's config, so set
    // both values explicitly before it initializes the guest.
    //
    // This is an address-boundary correctness policy, NOT attribution of the
    // observed heap corruption. The prior SurfaceControl and malloc-debug
    // failures already ran with Dynarmic; their original writer is unknown.
    Settings::values.cpu_backend.SetValue(Settings::CpuBackend::Dynarmic);
    Settings::values.cpu_accuracy.SetValue(Settings::CpuAccuracy::Accurate);

    // EmuFusion's internal Switch runtime intentionally exposes no Nintendo
    // account, LAN room, or multiplayer UI. Advertising a live network anyway
    // lets titles enter partially implemented NIFM/socket paths in the
    // embedded process. Super Mario Odyssey reproduced this deterministically:
    // shortly after Resume it issued SetTerminateResult(2010-0212), performed
    // a guest userspace panic, and stopped producing frames while the Android
    // process remained alive. Eden's own troubleshooting contract recommends
    // airplane mode for exactly this class of network-service failure. Keep
    // the zero-configuration internal runtime honestly offline; a future
    // explicit multiplayer feature can own and validate the opposite policy.
    Settings::values.airplane_mode.SetValue(true);

    // Match the portable Android default. Panel resolution does not describe
    // GPU capacity: forcing docked mode for the Thor's panel also made every
    // phone run the game's TV profile. Games choose their own rendering workload
    // from this mode; presentation still preserves their original aspect ratio.
    // The embedded adapter has no standalone Eden configuration UI, so apply the
    // default explicitly for each load, before the guest reads its operation mode.
    Settings::values.use_docked_mode.SetValue(Settings::ConsoleMode::Handheld);

    // Each session starts at the upstream VI base clock. Only a bounded
    // near-native fractional correction may be requested, never a load tier.
    Lucent::SetPacedVsyncHz(0.0);
    Lucent::SetFgPresentation(false);
    Lucent::ResetTimingDiagnostics();
    Lucent::g_source_images.BeginSession();

    // The embedded adapter has no Eden controller-settings Activity. Eden's
    // compiled Android defaults leave every player disconnected, so HIDCore's
    // ReloadInputDevices() builds the virtual-gamepad devices but immediately
    // disconnects the emulated NPads. Overlay writes then reach the input engine
    // (and look successful to Lucent) while the guest sees no controller at
    // all. The stock Eden Activity normally performs this connection through
    // NativeInput.connectController(); establish the same Pro Controller
    // contract for every locally routable player -- Player1..Player8,
    // players[0..kMaxLocalControllers-1] -- before InitializeEmulation reloads
    // HID devices, so multiplayer sessions find every controller_index
    // adapter_set_control() will honor already connected.
    auto& players = Settings::values.players.GetValue();
    for (std::size_t i = 0; i < kMaxLocalControllers; ++i) {
        players[i].connected = true;
        players[i].controller_type = Settings::ControllerType::ProController;
    }

    // Point Eden at Lucent's validated per-engine root before anything reads
    // keys, NAND, or save data.
    Common::FS::SetAppDirectory(std::string(request->system_directory));

    auto& session = EmulationSession::GetInstance();
    // Two of Eden's initializers are once-per-PROCESS, not once-per-title, and
    // running them again for a second title is what made the SECOND Switch
    // session in a process hang in teardown while the first tore down cleanly.
    //
    // Upstream does both exactly once, from YuzuApplication.onCreate():
    // GpuDriverHelper.initializeDriverParameters() -> initializeGpuDriver, and
    // DirectoryInitialization.start() -> initializeSystem(false), the latter
    // guarded by an areDirectoriesReady flag. Every later call in Eden's own
    // code passes reload = true.
    //
    // Re-running them is not merely wasteful. InitializeSystem(false) calls
    // InputSubsystem::Initialize(), whose RegisterEngine() REPLACES every input
    // engine shared_ptr -- keyboard, touch, android, virtual_gamepad and the
    // rest -- and re-registers their factories, while HIDCore's emulated
    // controllers are still holding devices built by the engines being dropped.
    // The adapter also caches the virtual gamepad pointer from that subsystem.
    // InitializeGpuDriver re-opens the Vulkan driver and replaces the shared
    // library handle the previous render window was built against.
    //
    // So: resolve the driver once, and hand InitializeSystem the reload flag
    // that says the process-wide half is already standing.
    static std::atomic<bool> process_initialized{false};
    const bool first_session = !process_initialized.exchange(true);
    if (first_session) {
        // The Vulkan driver has to be resolved before InitializeEmulation,
        // which hands the loaded library to its render window. An empty
        // custom-driver triple asks for the system driver.
        session.InitializeGpuDriver(adapter_library_directory(), std::string(),
                                    std::string(), std::string());
    }
    // InitializeSystem creates the filesystem and the manual content provider.
    // Nothing that touches content may run before it: ConfigureFilesystemProvider
    // dereferences that provider, and calling it first is a null dereference.
    // That half runs for every title; only the process-wide half is skipped.
    session.InitializeSystem(!first_session);
    LOG_INFO(Frontend, "EmuFusion Switch console mode={} source=portable-default",
             Settings::values.use_docked_mode.GetValue() == Settings::ConsoleMode::Handheld
                 ? "handheld" : "docked");
    // InitializeEmulation itself calls ConfigureFilesystemProvider, so the
    // adapter must not call it separately -- and it builds EmuWindow_Android
    // from the native window, so it has to wait for start().
    engine->content_path.assign(request->content_path);
    engine->loaded.store(true);
    return true;
}

static bool adapter_start(lucent_native_engine* engine, const lucent_native_io* io,
                          char* error, size_t error_size) {
    const auto fail = [&](const char* message) {
        if (error != nullptr && error_size > 0) {
            std::snprintf(error, error_size, "%s", message);
        }
        return false;
    };
    if (engine == nullptr || io == nullptr) {
        return fail("adapter start received no engine or io");
    }
    if (!engine->loaded.load()) {
        return fail("adapter start called before a title was loaded");
    }
    if (io->primary_window == nullptr) {
        return fail("Lucent supplied no render window");
    }
    if (engine->started.load()) {
        return true;
    }

    engine->window = static_cast<ANativeWindow*>(io->primary_window);
    Lucent::g_source_images.BindSurface();
    auto& session = EmulationSession::GetInstance();
    session.SetNativeWindow(engine->window);

    // Publish Lucent's sink and claim Eden's audio backend BEFORE the system is
    // created: AudioCore builds both of its sinks inside InitializeEmulation
    // below, and after that the choice is fixed for the session. A caller that
    // supplies no sink keeps Eden's own backend rather than losing audio
    // outright -- that is a caller with nowhere to send PCM, not an error here.
    g_audio_sink_ctx.store(io->audio_sink_ctx, std::memory_order_release);
    g_audio_sink.store(io->audio_sink, std::memory_order_release);
    AudioCore::Sink::SetLucentSinkFactory(io->audio_sink != nullptr ? &make_lucent_sink : nullptr);

    // Now that a surface exists, bring the title up on the engine thread. This
    // mirrors jni/native.cpp's static RunEmulation() exactly: initialize, run,
    // and unwind through ShutdownEmulation, all in one function body on one
    // thread. Eden's teardown finalizes the very kernel objects that identify
    // the host thread which brought the guest up, so bring-up and teardown have
    // to be the same thread or the kernel is left holding a pointer to a
    // KThread whose thread_local storage has already gone away.
    engine->emulation_thread = std::thread([engine]() {
        Common::SetCurrentThreadName("LucentEdenSession");
        auto& engine_session = EmulationSession::GetInstance();
        const auto boot = engine_session.InitializeEmulation(engine->content_path, 0, true);
        {
            std::scoped_lock publish{engine->boot_mutex};
            engine->boot_status = boot;
            engine->boot_published = true;
        }
        engine->boot_cv.notify_all();
        if (boot == Core::SystemResultStatus::Success) {
            LOG_INFO(Frontend, "Lucent session running");
            engine_session.RunEmulation();
        }
        // Reached on every path, halted or failed, like upstream's SCOPE_EXIT.
        // A failed InitializeEmulation still built a render window that has to
        // be released here.
        LOG_INFO(Frontend, "Lucent session tearing down on the engine thread");
        {
            std::scoped_lock lifecycle{engine->presentation_api_mutex};
            engine_session.ShutdownEmulation();
        }
        LOG_INFO(Frontend, "Lucent session teardown complete");
    });

    Core::SystemResultStatus boot_status{};
    {
        std::unique_lock wait{engine->boot_mutex};
        engine->boot_cv.wait(wait, [engine]() { return engine->boot_published; });
        boot_status = engine->boot_status;
    }
    if (boot_status != Core::SystemResultStatus::Success) {
        // The engine thread has already unwound through ShutdownEmulation, so
        // this join returns promptly and leaves nothing of the session behind.
        if (engine->emulation_thread.joinable()) {
            engine->emulation_thread.join();
        }
        engine->loaded.store(false);
        if (error != nullptr && error_size > 0) {
            if (boot_status == Core::SystemResultStatus::ErrorVideoCore) {
                std::snprintf(error, error_size,
                              "Switch graphics could not start. This device's Vulkan driver "
                              "could not initialize the built-in renderer (status %d).",
                              static_cast<int>(boot_status));
            } else {
                std::snprintf(error, error_size,
                              "Eden could not initialize this Switch title (status %d)",
                              static_cast<int>(boot_status));
            }
        }
        return false;
    }

    engine->started.store(true);
    return true;
}

static bool adapter_run_frame(lucent_native_engine* engine) {
    if (engine == nullptr || !engine->started.load()) {
        return false;
    }
    // Eden presents from its own loop. Report liveness so Lucent can fail the
    // session instead of leaving a frozen picture on screen.
    std::scoped_lock lifecycle{engine->presentation_api_mutex};
    auto& session = EmulationSession::GetInstance();
    return session.IsRunning() && !session.System().Renderer().HasPresentationFailure();
}

// Lucent's canonical controls are already console-semantic -- SystemControlLayouts
// has resolved the Thor's physical geometry into the console's own buttons -- so
// LUCENT_PAD_A means the Switch's A, not whichever key sits bottom-right.
//
// These go to Eden's VirtualGamepad rather than its Android driver. The Android
// driver wants a GUID, a port, raw Android keycodes and a controller registered
// from a YuzuInputDevice Java object, and it then resolves those through a user
// input profile that Lucent never writes. VirtualGamepad is the path Eden's own
// on-screen overlay uses: player-indexed, already bound to the guest pad, and
// needing no profile, no registration and no keycodes.
static bool virtual_button_for(lucent_native_control control,
                               InputCommon::VirtualGamepad::VirtualButton& out) {
    using VB = InputCommon::VirtualGamepad::VirtualButton;
    switch (control) {
    case LUCENT_PAD_A:          out = VB::ButtonA;      return true;
    case LUCENT_PAD_B:          out = VB::ButtonB;      return true;
    case LUCENT_PAD_X:          out = VB::ButtonX;      return true;
    case LUCENT_PAD_Y:          out = VB::ButtonY;      return true;
    case LUCENT_PAD_L:          out = VB::TriggerL;     return true;
    case LUCENT_PAD_R:          out = VB::TriggerR;     return true;
    case LUCENT_PAD_ZL:         out = VB::TriggerZL;    return true;
    case LUCENT_PAD_ZR:         out = VB::TriggerZR;    return true;
    case LUCENT_PAD_L3:         out = VB::StickL;       return true;
    case LUCENT_PAD_R3:         out = VB::StickR;       return true;
    case LUCENT_PAD_DPAD_UP:    out = VB::ButtonUp;     return true;
    case LUCENT_PAD_DPAD_DOWN:  out = VB::ButtonDown;   return true;
    case LUCENT_PAD_DPAD_LEFT:  out = VB::ButtonLeft;   return true;
    case LUCENT_PAD_DPAD_RIGHT: out = VB::ButtonRight;  return true;
    // Switch labels these Plus and Minus; Lucent's canonical names are the
    // generic Start/Select the rest of the library uses.
    case LUCENT_PAD_START:      out = VB::ButtonPlus;   return true;
    case LUCENT_PAD_SELECT:     out = VB::ButtonMinus;  return true;
    case LUCENT_PAD_HOME:       out = VB::ButtonHome;   return true;
    default:                                            return false;
    }
}

// SetStickPosition takes both axes at once, but Lucent delivers one axis per
// call, so the last value of the partner axis is retained and resent. Without
// this a horizontal push would zero the vertical axis on the very next event.
// This state is now per controller_index (previously two file-scope globals
// shared by every player): with real multi-controller routing, a second
// player's stick input must not corrupt the first player's.
struct stick_state {
    float x = 0.0f;
    float y = 0.0f;
};
static stick_state g_left_stick[kMaxLocalControllers];
static stick_state g_right_stick[kMaxLocalControllers];

static void adapter_set_control(lucent_native_engine* engine,
                                uint32_t controller_index,
                                lucent_native_control control, float value) {
    if (engine == nullptr || !engine->started.load()) {
        return;
    }
    // describe() advertises max_controllers == kMaxLocalControllers; anything
    // at or beyond that is not a player this adapter armed in adapter_load(),
    // so fail closed (drop it) rather than alias it onto player 0's state.
    if (controller_index >= kMaxLocalControllers) {
        return;
    }
    auto& session = EmulationSession::GetInstance();
    if (!session.IsRunning()) {
        return;
    }
    auto* pad = session.GetInputSubsystem().GetVirtualGamepad();
    if (pad == nullptr) {
        return;
    }
    const std::size_t player_index = controller_index;

    InputCommon::VirtualGamepad::VirtualButton button{};
    if (virtual_button_for(control, button)) {
        // Lucent sends 1.0/0.0 for digital controls and an analog ramp for
        // triggers on pads that have them; anything past halfway counts as a
        // press so an analog ZL/ZR still actuates.
        pad->SetButtonState(player_index, button, value >= 0.5f);
        return;
    }

    using VS = InputCommon::VirtualGamepad::VirtualStick;
    stick_state& left_stick = g_left_stick[player_index];
    stick_state& right_stick = g_right_stick[player_index];
    switch (control) {
    // Android reports its Y axis positive-down while the Switch stick is
    // positive-up, so the vertical axes are negated here rather than in the
    // Java layer, which must stay console-neutral for every other system.
    case LUCENT_PAD_LSTICK_X:
        left_stick.x = value;
        pad->SetStickPosition(player_index, VS::Left, left_stick.x, -left_stick.y);
        break;
    case LUCENT_PAD_LSTICK_Y:
        left_stick.y = value;
        pad->SetStickPosition(player_index, VS::Left, left_stick.x, -left_stick.y);
        break;
    case LUCENT_PAD_RSTICK_X:
        right_stick.x = value;
        pad->SetStickPosition(player_index, VS::Right, right_stick.x, -right_stick.y);
        break;
    case LUCENT_PAD_RSTICK_Y:
        right_stick.y = value;
        pad->SetStickPosition(player_index, VS::Right, right_stick.x, -right_stick.y);
        break;
    default:
        // Touch is delivered through Eden's own touch path, not the gamepad.
        break;
    }
}

static void adapter_pause(lucent_native_engine* engine) {
    if (engine == nullptr || !engine->started.load()) {
        return;
    }
    std::scoped_lock lifecycle{engine->presentation_api_mutex};
    auto& session = EmulationSession::GetInstance();
    if (session.IsRunning() && !session.IsPaused()) {
        session.PauseEmulation();
    }
    if (session.IsRunning()) {
        // Guest pause alone does not drain queued GPU composites. Complete the
        // GPU-owner barrier while the host still owns a valid Android Surface.
        session.System().GPU().SetPresentationSuspended(true);
    }
}

static void adapter_resume(lucent_native_engine* engine) {
    if (engine == nullptr || !engine->started.load()) {
        return;
    }
    std::scoped_lock lifecycle{engine->presentation_api_mutex};
    auto& session = EmulationSession::GetInstance();
    if (session.IsPaused()) {
        if (!session.System().GPU().SetPresentationSuspended(false)) {
            LOG_ERROR(Frontend, "Lucent refusing to resume failed Vulkan presentation");
            return;
        }
        session.UnPauseEmulation();
    }
}

static bool adapter_flush_save(lucent_native_engine* engine) {
    if (engine == nullptr || !engine->loaded.load()) {
        return false;
    }
    std::scoped_lock lifecycle{engine->presentation_api_mutex};
    // Pausing quiesces the guest and lets Eden's filesystem layer settle its
    // pending save writes before Lucent reports a clean exit.
    auto& session = EmulationSession::GetInstance();
    if (session.IsRunning() && !session.IsPaused()) {
        session.PauseEmulation();
    }
    return true;
}

static size_t adapter_serialize_size(lucent_native_engine* engine) {
    (void)engine;
    return 0;
}

static size_t adapter_serialize(lucent_native_engine* engine, void* out, size_t capacity) {
    (void)engine;
    (void)out;
    (void)capacity;
    return 0;
}

static bool adapter_unserialize(lucent_native_engine* engine, const void* data, size_t size) {
    (void)engine;
    (void)data;
    (void)size;
    return false;
}

static bool adapter_surface_recreated(lucent_native_engine* engine,
                                      const lucent_native_io* io) {
    if (engine == nullptr || io == nullptr || io->primary_window == nullptr) {
        return false;
    }
    std::scoped_lock lifecycle{engine->presentation_api_mutex};
    auto& session = EmulationSession::GetInstance();
    const bool running = session.IsRunning();
    if (running && !session.System().GPU().SetPresentationSuspended(true)) {
        return false;
    }
    Lucent::g_source_images.BindSurface();
    engine->window = static_cast<ANativeWindow*>(io->primary_window);
    session.SetNativeWindow(engine->window);
    session.SurfaceChanged();
    if (running && !session.IsPaused()) {
        return session.System().GPU().SetPresentationSuspended(false);
    }
    return true;
}

static void adapter_stop(lucent_native_engine* engine) {
    if (engine == nullptr) {
        return;
    }
    Lucent::g_source_images.Close();
    auto& session = EmulationSession::GetInstance();
    if (engine->started.load()) {
        {
            std::scoped_lock lifecycle{engine->presentation_api_mutex};
            if (session.IsRunning()) {
                session.System().GPU().SetPresentationSuspended(true);
            }
            // Leave the paused state first. Lucent pauses the engine twice on
            // exit; System::Pause suspends guest threads and parks CoreTiming.
            // ShutdownMainProcess must terminate those same threads, so match
            // Eden's frontend by halting a running guest. Only guest progress
            // resumes here: presentation remains suspended through destruction.
            if (session.IsPaused()) {
                session.UnPauseEmulation();
            }
            LOG_INFO(Frontend, "Lucent halting the Switch session");
            session.HaltEmulation();
        } // Never hold presentation_api_mutex across the session-thread join.
        if (engine->emulation_thread.joinable()) {
            // ShutdownEmulation runs on that thread, so this join is the point
            // at which the guest kernel is provably gone -- not merely the
            // point at which its run loop returned.
            engine->emulation_thread.join();
        }
        LOG_INFO(Frontend, "Lucent joined the Switch session thread");
        engine->started.store(false);
        engine->loaded.store(false);
    } else if (engine->loaded.load()) {
        // Loaded but never started: no render window and no guest were ever
        // built, so there is no session thread to unwind. Release what load()
        // did put in place.
        session.ShutdownEmulation();
        engine->loaded.store(false);
    }
    // ShutdownEmulation destroys AudioCore, which destroys the sink, which joins
    // the pump thread. Only once that has returned is it safe to drop Lucent's
    // callback: after this point nothing can push into a context Lucent is
    // about to free, and a later session installs its own.
    AudioCore::Sink::SetLucentSinkFactory(nullptr);
    g_audio_sink.store(nullptr, std::memory_order_release);
    g_audio_sink_ctx.store(nullptr, std::memory_order_release);
    engine->window = nullptr;
}

static void adapter_destroy(lucent_native_engine* engine) {
    if (engine == nullptr) {
        return;
    }
    adapter_stop(engine);
    delete engine;
}

static const lucent_native_adapter kLucentEdenAdapter = {
    /* abi_version      */ LUCENT_NATIVE_ADAPTER_ABI_VERSION,
    /* describe         */ adapter_describe,
    /* create           */ adapter_create,
    /* load             */ adapter_load,
    /* start            */ adapter_start,
    /* run_frame        */ adapter_run_frame,
    /* set_control      */ adapter_set_control,
    /* pause            */ adapter_pause,
    /* resume           */ adapter_resume,
    /* flush_save       */ adapter_flush_save,
    /* serialize_size   */ adapter_serialize_size,
    /* serialize        */ adapter_serialize,
    /* unserialize      */ adapter_unserialize,
    /* surface_recreated*/ adapter_surface_recreated,
    /* stop             */ adapter_stop,
    /* destroy          */ adapter_destroy,
};

extern "C" __attribute__((visibility("default")))
const lucent_native_adapter* lucent_native_adapter_entry(void) {
    return &kLucentEdenAdapter;
}

// Lucent reads live speed through this symbol during qualification so a
// "runs at 60fps" claim is measured from the engine, not inferred.
extern "C" __attribute__((visibility("default")))
double lucent_eden_average_game_fps(void) {
    return EmulationSession::GetInstance().PerfStats().average_game_fps;
}

// Optional near-native VI base-clock hooks. This is not the number of changing
// images: guest BufferItems retain their own swap intervals. Neither averaged
// FPS, VI callbacks nor monotonic submission timestamps establish image-linked
// guest timing, so this adapter intentionally does NOT advertise that authority.
extern "C" __attribute__((visibility("default")))
double lucent_native_adapter_declared_video_hz(void) {
    return 60.0;
}

extern "C" __attribute__((visibility("default")))
void lucent_native_adapter_set_fg_presentation_v1(bool enabled) {
    Lucent::SetFgPresentation(enabled);
}

extern "C" __attribute__((visibility("default")))
bool lucent_native_adapter_set_paced_video_hz(double hz) {
    return Lucent::SetPacedVsyncHz(hz);
}

extern "C" __attribute__((visibility("default")))
uint32_t lucent_native_adapter_timing_capabilities_v1(void) {
    return LUCENT_NATIVE_TIMING_BASE_CLOCK_CORRECTION |
           LUCENT_NATIVE_TIMING_SUBMISSION_TIMESTAMPS;
}

// Diagnostic exact-image lookup, not a stable guest-content clock. These
// optional exports do not enable AUTHORITATIVE_SOURCE_TIMELINE. Callers must
// own the native host lifetime while copying into their fixed-size output.
extern "C" __attribute__((visibility("default")))
uint32_t lucent_native_adapter_source_image_binding_v1(lucent_source_binding_v1* out,
                                                     uint32_t out_size) {
    return Lucent::g_source_images.Binding(out, out_size);
}

extern "C" __attribute__((visibility("default")))
uint32_t lucent_native_adapter_query_source_image_v1(uint64_t session_epoch,
                                                   uint64_t surface_epoch,
                                                   uint64_t buffer_timestamp_ns,
                                                   lucent_source_image_v1* out,
                                                   uint32_t out_size) {
    return Lucent::g_source_images.Query(session_epoch, surface_epoch, buffer_timestamp_ns,
                                       out, out_size);
}
