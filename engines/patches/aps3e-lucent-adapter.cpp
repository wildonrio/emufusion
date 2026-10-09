// SPDX-License-Identifier: GPL-2.0-only
//
// Lucent's in-process adapter for the pinned aPS3e/RPCS3 Android engine.
// This translation unit is compiled into aPS3e's native library.  It does not
// load aPS3e's Activity or JNI frontend: Lucent owns the window, controller,
// lifecycle, firmware gate and Quick Resume artifact.

#include "lucent_native_adapter.h"

#include "emulator.h"
#include "emulator_aps3e.h"
#include "Emu/savestate_utils.hpp"
#include "Utilities/File.h"

#include <android/native_window.h>
#include <android/log.h>
#include <android/api-level.h>
#include <jni.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <dlfcn.h>
#include <unistd.h>

namespace {

constexpr const char* kTag = "LucentAps3e";
constexpr auto kBootTimeout = std::chrono::seconds(120);
constexpr auto kStopTimeout = std::chrono::seconds(45);
constexpr std::size_t kMaxStateBytes = 2ull * 1024ull * 1024ull * 1024ull;

void log_error(const char* message) {
    __android_log_print(ANDROID_LOG_ERROR, kTag, "%s", message ? message : "unknown");
}

void write_error(char* error, std::size_t size, const char* message) {
    if (!error || size == 0) return;
    std::snprintf(error, size, "%s", message ? message : "unknown error");
}

std::string current_library_directory() {
    Dl_info info{};
    if (!dladdr(reinterpret_cast<const void*>(&current_library_directory), &info) ||
        !info.dli_fname || !*info.dli_fname) return {};
    return std::filesystem::path(info.dli_fname).parent_path().string();
}

bool readable_file(const std::filesystem::path& path) {
    std::error_code ec;
    return std::filesystem::is_regular_file(path, ec) &&
           std::filesystem::file_size(path, ec) > 0;
}

std::filesystem::path newest_state(const std::filesystem::path& root) {
    std::filesystem::path newest;
    std::filesystem::file_time_type newest_time{};
    std::error_code ec;
    if (!std::filesystem::is_directory(root, ec)) return {};
    for (std::filesystem::recursive_directory_iterator it(
                 root, std::filesystem::directory_options::skip_permission_denied, ec), end;
         it != end && !ec; it.increment(ec)) {
        if (!it->is_regular_file(ec)) continue;
        const std::string name = it->path().filename().string();
        if (!name.ends_with(".SAVESTAT") && !name.ends_with(".SAVESTAT.zst") &&
            !name.ends_with(".SAVESTAT.gz")) continue;
        const auto time = it->last_write_time(ec);
        if (ec) { ec.clear(); continue; }
        if (newest.empty() || time > newest_time) {
            newest = it->path();
            newest_time = time;
        }
    }
    return newest;
}

bool read_file(const std::filesystem::path& path, std::vector<std::uint8_t>& out) {
    std::error_code ec;
    const auto size = std::filesystem::file_size(path, ec);
    if (ec || size == 0 || size > kMaxStateBytes) return false;
    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    out.resize(static_cast<std::size_t>(size));
    input.read(reinterpret_cast<char*>(out.data()), static_cast<std::streamsize>(out.size()));
    return input.good() || input.eof();
}

bool write_file_atomic(const std::filesystem::path& destination,
                       const void* data, std::size_t size) {
    if (!data || size == 0 || size > kMaxStateBytes) return false;
    std::error_code ec;
    std::filesystem::create_directories(destination.parent_path(), ec);
    if (ec) return false;
    const auto pending = destination.string() + ".pending";
    {
        std::ofstream output(pending, std::ios::binary | std::ios::trunc);
        if (!output) return false;
        output.write(static_cast<const char*>(data), static_cast<std::streamsize>(size));
        output.flush();
        if (!output) { std::filesystem::remove(pending, ec); return false; }
    }
    std::filesystem::remove(destination, ec);
    ec.clear();
    std::filesystem::rename(pending, destination, ec);
    if (ec) std::filesystem::remove(pending, ec);
    return !ec;
}

int virtual_key(lucent_native_control control, float value, bool& pressed,
                std::uint16_t& magnitude) {
    // APS3E_VKC is intentionally mirrored from aps3e_rp3_impl.cpp.  Keeping
    // this mapping explicit makes the physical-slot -> DS3 contract auditable.
    enum : int {
        kNone = 0, kLeft, kUp, kRight, kDown,
        kSquare, kCross, kCircle, kTriangle,
        kLsLeft, kLsUp, kLsRight, kLsDown,
        kRsLeft, kRsUp, kRsRight, kRsDown,
        kL1, kL2, kL3, kR1, kR2, kR3, kStart, kSelect, kPs
    };
    magnitude = static_cast<std::uint16_t>(std::clamp(std::abs(value), 0.0f, 1.0f) * 255.0f);
    pressed = magnitude > 0;
    switch (control) {
        // Lucent's canonical A/B/X/Y are physical south/east/west/north.
        // A PS3's corresponding printed controls are Cross/Circle/Square/Triangle.
        case LUCENT_PAD_A: return kCross;
        case LUCENT_PAD_B: return kCircle;
        case LUCENT_PAD_X: return kSquare;
        case LUCENT_PAD_Y: return kTriangle;
        case LUCENT_PAD_L: return kL1;
        case LUCENT_PAD_R: return kR1;
        case LUCENT_PAD_ZL: return kL2;
        case LUCENT_PAD_ZR: return kR2;
        case LUCENT_PAD_L3: return kL3;
        case LUCENT_PAD_R3: return kR3;
        case LUCENT_PAD_DPAD_UP: return kUp;
        case LUCENT_PAD_DPAD_DOWN: return kDown;
        case LUCENT_PAD_DPAD_LEFT: return kLeft;
        case LUCENT_PAD_DPAD_RIGHT: return kRight;
        case LUCENT_PAD_START: return kStart;
        case LUCENT_PAD_SELECT: return kSelect;
        case LUCENT_PAD_HOME: return kPs;
        case LUCENT_PAD_LSTICK_X: return value < 0 ? kLsLeft : kLsRight;
        case LUCENT_PAD_LSTICK_Y: return value < 0 ? kLsUp : kLsDown;
        case LUCENT_PAD_RSTICK_X: return value < 0 ? kRsLeft : kRsRight;
        case LUCENT_PAD_RSTICK_Y: return value < 0 ? kRsUp : kRsDown;
        default: return kNone;
    }
}

} // namespace

// The unified Lucent APK does not package aPS3e's Activity frontend classes.
// Its upstream JNI_OnLoad unconditionally RegisterNatives against those
// classes, which makes ART abort when the adapter is opened in-process. The
// native engine only needs the VM identity cached by that hook; accept it over
// the host's versioned adapter ABI without registering any Java frontend.
extern JavaVM* g_jvm;
extern "C" __attribute__((visibility("default")))
int lucent_native_adapter_set_java_vm(std::uint32_t version, void* java_vm) {
    if (version != 1u || !java_vm) return 0;
    g_jvm = static_cast<JavaVM*>(java_vm);
    return 1;
}

struct lucent_native_engine {
    std::mutex mutex;
    std::string system_directory;
    std::string save_directory;
    std::string content_path;
    std::filesystem::path restore_path;
    std::vector<std::uint8_t> serialized_state;
    ANativeWindow* primary = nullptr;
    bool loaded = false;
    bool started = false;
    bool stopped = false;
    bool save_requested = false;
};

static void release_boot_io(lucent_native_engine* engine) {
    if (!engine) return;
    if (engine->primary) {
        if (ae::window == engine->primary) ae::window = nullptr;
        ANativeWindow_release(engine->primary);
        engine->primary = nullptr;
    }
    if (ae::boot_type == ae::BOOT_TYPE_WITH_FD && ae::boot_game_fd >= 0) {
        close(ae::boot_game_fd);
        ae::boot_game_fd = -1;
    }
}

static void adapter_describe(lucent_native_capabilities* out) {
    if (!out) return;
    *out = {};
    out->abi_version = LUCENT_NATIVE_ADAPTER_ABI_VERSION;
    out->engine_id = "aps3e";
    out->engine_version = "2.40-b5ae1af";
    out->has_quick_resume = true;
    out->has_persistent_save = true;
    out->dual_screen = false;
    out->required_firmware = 1;
    // RPCS3 itself supports up to CELL_PAD_MAX_PORT_NUM (7) pad ports, but
    // every one of them that uses the "Keyboard" device shares a SINGLE
    // AndroidVirtualPadHandler instance (aps3e_rp3_impl.cpp's pad_thread::
    // Init() caches it per handler TYPE, not per player) whose entire virtual
    // key space is the fixed 26-entry APS3E_VKC/mouse_list enum. Player 0's
    // own default cfg_pad binds all 25 non-"none" codes one-to-one (verified
    // by reading init_config()/bindPadToDevice()), so there is no disjoint
    // code range left for a second player without either widening that
    // vendored enum or reaching into the handler's private per-pad button
    // list -- both out of scope for this adapter translation unit. Report
    // capability honestly: exactly one real, routable controller.
    out->max_controllers = 1;
}

static lucent_native_engine* adapter_create() {
    try { return new lucent_native_engine(); }
    catch (...) { return nullptr; }
}

static bool adapter_load(lucent_native_engine* engine,
                         const lucent_native_load_request* request,
                         char* error, std::size_t error_size) {
    if (!engine || !request || !request->system_directory || !request->save_directory ||
        !request->content_path || !*request->content_path) {
        write_error(error, error_size, "PS3 load request is incomplete");
        return false;
    }
    std::lock_guard lock(engine->mutex);
    if (engine->started) {
        write_error(error, error_size, "PS3 session is already running");
        return false;
    }
    engine->system_directory = request->system_directory;
    engine->save_directory = request->save_directory;
    engine->content_path = request->content_path;
    std::error_code ec;
    std::filesystem::create_directories(engine->system_directory + "/logs", ec);
    std::filesystem::create_directories(engine->system_directory + "/config", ec);
    std::filesystem::create_directories(engine->system_directory + "/cache", ec);
    std::filesystem::create_directories(engine->save_directory, ec);
    if (ec) {
        write_error(error, error_size, "PS3 private data directory could not be created");
        return false;
    }
    setenv("APS3E_DATA_DIR", engine->system_directory.c_str(), 1);
    const std::string logs = engine->system_directory + "/logs";
    const std::string config = engine->system_directory + "/config/config.yml";
    setenv("APS3E_LOG_DIR", logs.c_str(), 1);
    setenv("APS3E_GLOBAL_CONFIG_YAML_PATH", config.c_str(), 1);
    setenv("APS3E_ENABLE_LOG", "true", 1);
    const std::string api_level = std::to_string(android_get_device_api_level());
    setenv("APS3E_ANDROID_API_VERSION", api_level.c_str(), 1);
    const std::string native_libraries = current_library_directory();
    if (!native_libraries.empty())
        setenv("APS3E_NATIVE_LIB_DIR", native_libraries.c_str(), 1);

    const std::filesystem::path flash =
            std::filesystem::path(engine->system_directory) / "config/dev_flash";
    const std::filesystem::path firmware_version = flash / "vsh/etc/version.txt";
    if (!readable_file(firmware_version)) {
        // aPS3e's installer calls statfs(dev_flash) after validating the PUP
        // and before extracting it.  The Activity frontend normally creates
        // this target during initialization, but Lucent installs firmware
        // before starting the emulation thread, so create this exact private
        // target here.  A pre-existing directory without the concrete version
        // sentinel may be a partial prior install: never overwrite or delete
        // it because this launch did not create it.
        ec.clear();
        const bool created_flash = std::filesystem::create_directories(flash, ec);
        if (ec) {
            write_error(error, error_size, "PS3 firmware target could not be created");
            return false;
        }
        if (!created_flash) {
            write_error(error, error_size, "PS3 firmware installation is incomplete");
            return false;
        }
        const auto pup = std::filesystem::path(engine->system_directory) / "PS3UPDAT.PUP";
        if (!readable_file(pup)) {
            std::error_code cleanup_error;
            std::filesystem::remove_all(flash, cleanup_error);
            write_error(error, error_size, "A user-supplied PS3 system update is required");
            return false;
        }
        const int fd = open(pup.c_str(), O_RDONLY | O_CLOEXEC);
        if (fd < 0) {
            std::error_code cleanup_error;
            std::filesystem::remove_all(flash, cleanup_error);
            write_error(error, error_size, "PS3 system update could not be opened");
            return false;
        }
        // ae::install_firmware transfers fd into fs::file::from_fd, whose
        // unix_file owns and closes it.  Closing it again here can invalidate
        // an unrelated descriptor if another thread reuses the number.
        if (!ae::install_firmware(fd)) {
            std::error_code cleanup_error;
            std::filesystem::remove_all(flash, cleanup_error);
            write_error(error, error_size, "PS3 firmware validation or installation failed");
            return false;
        }
        if (!readable_file(firmware_version)) {
            std::error_code cleanup_error;
            std::filesystem::remove_all(flash, cleanup_error);
            write_error(error, error_size, "PS3 firmware installation did not complete");
            return false;
        }
    }
    if (!std::filesystem::exists(engine->content_path, ec)) {
        write_error(error, error_size, "PS3 game content is unavailable");
        return false;
    }
    engine->loaded = true;
    engine->stopped = false;
    return true;
}

static bool adapter_start(lucent_native_engine* engine, const lucent_native_io* io,
                          char* error, std::size_t error_size) {
    if (!engine || !io || io->kind != LUCENT_NATIVE_RENDER_VULKAN_WINDOW ||
        !io->primary_window || !engine->loaded) {
        write_error(error, error_size, "PS3 Vulkan window is unavailable");
        return false;
    }
    std::lock_guard lock(engine->mutex);
    engine->primary = static_cast<ANativeWindow*>(io->primary_window);
    ANativeWindow_acquire(engine->primary);
    ae::window = engine->primary;
    ae::window_width = ANativeWindow_getWidth(engine->primary);
    ae::window_height = ANativeWindow_getHeight(engine->primary);

    const std::filesystem::path content(engine->content_path);
    const std::string extension = content.extension().string();
    if (extension == ".iso" || extension == ".ISO") {
        ae::boot_game_fd = open(content.c_str(), O_RDONLY | O_CLOEXEC);
        if (ae::boot_game_fd < 0) {
            release_boot_io(engine);
            write_error(error, error_size, "PS3 disc image could not be opened");
            return false;
        }
        ae::boot_type = ae::BOOT_TYPE_WITH_FD;
    } else {
        ae::boot_game_path = engine->content_path;
        ae::boot_type = ae::BOOT_TYPE_WITH_PATH;
    }
    std::thread(ae::main_thr).detach();
    const auto deadline = std::chrono::steady_clock::now() + kBootTimeout;
    while (std::chrono::steady_clock::now() < deadline &&
           !ae::is_running() && !engine->stopped) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (!ae::is_running()) {
        // A synchronous boot rejection reaches STATUS_STOPPED through the
        // pinned wrapper patch. Do not call ae::quit() here: while boot_game()
        // itself is still blocked there is no wrapper loop to acknowledge its
        // condition variable, so a timeout cleanup must stay non-blocking.
        release_boot_io(engine);
        write_error(error, error_size, "PS3 engine did not reach running state");
        return false;
    }
    engine->started = true;
    return true;
}

static bool adapter_run_frame(lucent_native_engine* engine) {
    if (!engine || !engine->started || engine->stopped) return false;
    // RPCS3 owns its emulation/render threads.  The host tick is a health poll,
    // deliberately paced so Lucent's render owner does not busy-spin.
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    return ae::is_running() || ae::is_paused();
}

static void adapter_set_control(lucent_native_engine* engine,
                                std::uint32_t controller_index,
                                lucent_native_control control, float value) {
    // describe() reports max_controllers == 1: the shared virtual-pad key
    // space has no room for a second independently-routable player (see the
    // comment in adapter_describe()). Per the ABI contract for such an
    // adapter, any index other than the primary/local player is a fail-closed
    // no-op -- it must never alias onto player 0's state.
    if (controller_index != 0) return;
    if (!engine || !engine->started || engine->stopped) return;
    bool pressed = false;
    std::uint16_t magnitude = 0;
    const int code = virtual_key(control, value, pressed, magnitude);
    switch (control) {
        case LUCENT_PAD_LSTICK_X:
        case LUCENT_PAD_LSTICK_Y:
        case LUCENT_PAD_RSTICK_X:
        case LUCENT_PAD_RSTICK_Y: {
            // aPS3e retains the negative and positive virtual keys separately.
            // Release the opposite direction first, including on neutral (which
            // maps to the positive key), or a previous left/up remains held.
            bool opposite_pressed = false;
            std::uint16_t opposite_magnitude = 0;
            const int opposite = virtual_key(control, value < 0 ? 1.f : -1.f,
                                             opposite_pressed, opposite_magnitude);
            ae::key_event(static_cast<std::uint32_t>(opposite), false, 0);
            break;
        }
        default: break;
    }
    if (code != 0) ae::key_event(static_cast<std::uint32_t>(code), pressed, magnitude);
}

static void adapter_pause(lucent_native_engine* engine) {
    if (engine && engine->started && !engine->stopped && ae::is_running()) ae::pause();
}

static void adapter_resume(lucent_native_engine* engine) {
    if (engine && engine->started && !engine->stopped && ae::is_paused()) ae::resume();
}

static bool adapter_flush_save(lucent_native_engine* engine) {
    // RPCS3's guest save-data manager performs durable file writes itself.  A
    // successful call means the engine is alive and its config root exists;
    // Quick Resume below is the separate exact-position artifact.
    return engine && engine->loaded &&
           std::filesystem::is_directory(engine->system_directory + "/config");
}

static std::size_t adapter_serialize_size(lucent_native_engine* engine) {
    if (!engine || !engine->started) return 0;
    std::lock_guard lock(engine->mutex);
    if (!engine->save_requested) {
        engine->save_requested = true;
        // Use RPCS3's own savestate-and-exit path.  Kill is asynchronous: the
        // fully-stopped predicate below is the commit boundary, not the return
        // from this call.
        Emu.Kill(false, true);
        const auto deadline = std::chrono::steady_clock::now() + kStopTimeout;
        while (std::chrono::steady_clock::now() < deadline && !Emu.IsStopped(true))
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        engine->restore_path = newest_state(
                std::filesystem::path(engine->system_directory) / "config/savestates");
        if (!engine->restore_path.empty())
            read_file(engine->restore_path, engine->serialized_state);
        // Emu.Kill(save_state=true) stops RPCS3 but aPS3e's wrapper thread
        // otherwise remains in STATUS_RUNNING forever. Retire that wrapper as
        // part of the same commit so a second in-process title cannot inherit
        // a live stale main thread.
        if (ae::is_running() || ae::is_paused()) ae::quit();
        engine->stopped = true;
    }
    return engine->serialized_state.size();
}

static std::size_t adapter_serialize(lucent_native_engine* engine,
                                     void* out, std::size_t capacity) {
    if (!engine) return 0;
    const std::size_t required = adapter_serialize_size(engine);
    if (!out && capacity == 0) return required;
    if (!out || required == 0 || capacity < required) return 0;
    std::memcpy(out, engine->serialized_state.data(), required);
    return required;
}

static bool adapter_unserialize(lucent_native_engine* engine,
                                const void* data, std::size_t size) {
    if (!engine || !engine->started || !data || size == 0 || size > kMaxStateBytes)
        return false;
    const std::filesystem::path incoming =
            std::filesystem::path(engine->save_directory) / "lucent-restore.SAVESTAT.zst";
    if (!write_file_atomic(incoming, data, size)) return false;
    // RPCS3 validates the state header/version before replacing the running
    // guest.  A rejected or incompatible state therefore fails closed.
    Emu.GracefulShutdown(false, false, false);
    const auto deadline = std::chrono::steady_clock::now() + kStopTimeout;
    while (std::chrono::steady_clock::now() < deadline && !Emu.IsStopped(true))
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    if (!Emu.IsStopped(true)) return false;
    return Emu.BootGame(incoming.string(), "", true) == game_boot_result::no_errors;
}

static bool adapter_surface_recreated(lucent_native_engine* engine,
                                      const lucent_native_io* io) {
    if (!engine || !io || !io->primary_window || !engine->started || engine->stopped)
        return false;
    std::lock_guard lock(engine->mutex);
    ANativeWindow* replacement = static_cast<ANativeWindow*>(io->primary_window);
    ANativeWindow_acquire(replacement);
    ANativeWindow* old = engine->primary;
    engine->primary = replacement;
    ae::window = replacement;
    ae::window_width = ANativeWindow_getWidth(replacement);
    ae::window_height = ANativeWindow_getHeight(replacement);
    if (old) ANativeWindow_release(old);
    // The Android GS frame reads ae::window when RPCS3 recreates its frame.
    // Explicit resize keeps the current surface dimensions coherent.
    return true;
}

static void adapter_stop(lucent_native_engine* engine) {
    if (!engine) return;
    std::lock_guard lock(engine->mutex);
    if (engine->started && !engine->stopped) {
        ae::quit();
        engine->stopped = true;
    }
    engine->started = false;
    release_boot_io(engine);
}

static void adapter_destroy(lucent_native_engine* engine) {
    if (!engine) return;
    adapter_stop(engine);
    delete engine;
}

static const lucent_native_adapter kAdapter = {
    LUCENT_NATIVE_ADAPTER_ABI_VERSION,
    adapter_describe,
    adapter_create,
    adapter_load,
    adapter_start,
    adapter_run_frame,
    adapter_set_control,
    adapter_pause,
    adapter_resume,
    adapter_flush_save,
    adapter_serialize_size,
    adapter_serialize,
    adapter_unserialize,
    adapter_surface_recreated,
    adapter_stop,
    adapter_destroy,
};

extern "C" __attribute__((visibility("default")))
const lucent_native_adapter* lucent_native_adapter_entry() {
    return &kAdapter;
}
