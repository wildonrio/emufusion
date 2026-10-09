// SPDX-License-Identifier: GPL-3.0-or-later
//
// Lucent Phase 3 native adapter for the Cemu Wii U engine.
//
// This translation unit is compiled INTO Cemu's own libCemuAndroid.so and is
// the only symbol Lucent calls: lucent_native_adapter_entry(). It drives
// CafeSystem/VulkanRenderer directly, so the engine runs inside Lucent's
// process, in Lucent's windows, with no Cemu Activity and no emulator UI.
//
// LICENCE NOTE: Cemu is Mozilla Public License 2.0 and carries no Exhibit B
// "Incompatible With Secondary Licenses" notice, so MPL-2.0 section 3.3 permits
// the combined Larger Work to be distributed under a Secondary License. Lucent
// distributes under GPL-3.0-only, which is a Secondary License in MPL 2.0's own
// terms (1.12 names the GPL v2.0 "or any later versions"). Cemu's own files stay
// MPL-2.0 file-by-file; only this Lucent-authored file is GPL-3.0-or-later.
//
// Cemu owns its emulation loop: LaunchForegroundTitle() detaches its own title
// thread and returns immediately, so unlike Eden this adapter does not need to
// spawn one. run_frame() reports liveness so Lucent can fail a dead session
// rather than leaving a frozen picture on screen.
//
// Keys are never bundled. The user's own keys.txt is copied into the validated
// system directory by Lucent before load() runs, and load() hands it to Cemu's
// own KeyCache. When it holds no key that fits the disc, load() still fails
// closed and reports Cemu's missing-disc-key / missing-ticket status.

#include <array>
#include <atomic>
#include <cmath>
#include <chrono>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

#include <android/log.h>
#include <android/native_window.h>
#include <dlfcn.h>
#include <signal.h>

#include "lucent_native_adapter.h"

extern "C" const lucent_native_adapter* lucent_native_adapter_entry(void);

#include "Cafe/CafeSystem.h"
#include "Cafe/Filesystem/FST/KeyCache.h"
#include "Cafe/HW/Latte/Core/LatteOverlay.h"
#include "Cafe/HW/Latte/Core/LatteTiming.h"
#include "Cafe/HW/Latte/Renderer/Renderer.h"
#include "Cafe/HW/Latte/Renderer/Vulkan/VulkanAPI.h"
#include "Cafe/HW/Latte/Renderer/Vulkan/VulkanRenderer.h"
#include "Cafe/OS/libs/snd_core/ax.h"
#include "Cafe/OS/libs/coreinit/coreinit_MEM.h"
#include "Cafe/OS/libs/swkbd/swkbd.h"
#include "Cafe/TitleList/TitleId.h"
#include "Cafe/TitleList/TitleList.h"
#include "audio/IAudioAPI.h"
#include "config/ActiveSettings.h"
#include "config/CemuConfig.h"
#include "config/NetworkSettings.h"
#include "input/InputManager.h"
#include "input/emulated/VPADController.h"
#include "input/emulated/ProController.h"
#include "WindowSystem.h"

// forward declaration from src/main.cpp, exactly as NativeEmulation.cpp does
void CemuCommonInit();

// Defined in src/android/app/src/main/cpp/NativeEmulation.cpp. It lays out the
// emulated NAND (mlc01/sys, mlc01/usr/title/*, the Mii Maker save folders) and
// writes the language/country tables Cafe titles read at boot. Declared rather
// than duplicated so the adapter and Cemu's own frontend cannot drift apart.
namespace NativeEmulation
{
	void CreateCemuDirectories();
}

namespace
{
	constexpr const char* kEngineId = "cemu";
	constexpr const char* kEngineVersion = "cemu-android-0.5";

	// Cemu's AX mixer hands the audio device one group of 4 AX frames at a
	// time; this is the same block geometry NativeEmulation::CreateAudioDevice
	// uses, and it is what Lucent's sink will see per FeedBlock call.
	constexpr int kAxFramesPerGroup = 4;
	constexpr uint32 kSampleRate = 48000;
	// Wii U TV output clock as the host sees it: the exact 60.000 Hz lattice
	// the VulkanRenderer stamps claim (see lucent_native_adapter_set_paced_video_hz).
	constexpr sint32 kLucentDeclaredVideoHz = 60;
	std::atomic<double> g_lucent_paced_video_hz{0.0};
	constexpr uint32 kBitsPerSample = 16;

	// Lucent's audio sink takes interleaved stereo s16. The Wii U can mix 5.1
	// for the TV, but Lucent owns a stereo AudioTrack, so the device is created
	// as stereo rather than downmixing after the fact.
	constexpr uint32 kChannels = 2;

	/**
	 * Bridges Cemu's audio device interface onto Lucent's audio sink.
	 *
	 * Cemu would normally open its own cubeb stream, which would give Lucent no
	 * ownership of the AudioTrack and no way to follow system volume. Lucent
	 * hands the adapter a sink in lucent_native_io instead, so this subclass
	 * forwards each mixed block straight to it and never touches cubeb.
	 */
	class LucentAudioAPI final : public IAudioAPI
	{
	  public:
		LucentAudioAPI(lucent_native_audio_sink sink, void* sinkCtx, uint32 samplesPerBlock)
			: IAudioAPI(kSampleRate, kChannels, samplesPerBlock, kBitsPerSample),
			  m_sink(sink), m_sinkCtx(sinkCtx)
		{
		}

		// Cemu's AudioAPI enum has no Lucent member and is only consulted by the
		// desktop settings UI, which Lucent never opens. Reporting Cubeb keeps
		// the enum valid without claiming a device Lucent did not create.
		AudioAPI GetType() const override { return Cubeb; }

		/**
		 * Whether AX should run its update early to catch a starving sink up.
		 *
		 * This is NOT "may I have another block". AXOut_update polls it purely to
		 * choose between its nominal 3 ms tick and a 2.9 ms catch-up tick, and
		 * 3 ms is the Wii U's real AX frame period. Cubeb answers it by asking
		 * whether its own queue has fallen below the configured audio delay.
		 *
		 * Returning m_playing said "always starving" for the entire session, so
		 * AX never used the nominal tick and the whole audio clock ran
		 * 3.0/2.9 = 3.45% fast, permanently, for as long as a title played.
		 *
		 * Lucent's sink has no queue to be behind on: FeedBlock hands the block
		 * straight to Lucent, which owns the AudioTrack and does its own
		 * buffering, and the adapter holds nothing. With no backlog to report,
		 * the honest answer is false -- keep AX on the cadence the hardware
		 * actually had, and let the AudioTrack absorb jitter as it is designed
		 * to.
		 */
		bool NeedAdditionalBlocks() const override { return false; }

		bool FeedBlock(sint16* data) override
		{
			if (!m_playing || m_sink == nullptr || data == nullptr)
				return false;
			// m_samplesPerBlock is a frame count; the sink takes frames, not
			// samples, and pulls both channels itself.
			m_sink(m_sinkCtx, data, static_cast<size_t>(m_samplesPerBlock));
			return true;
		}

		bool Play() override
		{
			m_playing = true;
			return true;
		}

		bool Stop() override
		{
			m_playing = false;
			return true;
		}

		// Lucent owns the AudioTrack and already follows system volume, so the
		// engine-side attenuation stays at unity instead of applying a second one.
		void SetVolume(sint32 volume) override { (void)volume; m_volume = 100; }

	  private:
		lucent_native_audio_sink m_sink;
		void* m_sinkCtx;
	};

	/**
	 * How many local/remote players adapter_set_control() can address.
	 * InputManager's own player-index ceiling: kMaxVPADControllers (2) GamePad
	 * slots plus kMaxWPADControllers (7) Wiimote-family slots, of which this
	 * adapter uses index 0 (VPAD, the real Wii U GamePad) plus indices 1..7
	 * (Pro Controller, InputManager's m_wpad array) -- 8 total.
	 */
	constexpr size_t kLucentMaxControllers = InputManager::kMaxController;

	/**
	 * Cached per controller_index so set_control can reach a guest pad without
	 * re-resolving it through InputManager on every call. Index 0 (VPAD) is
	 * created eagerly in start(); indices 1..kLucentMaxControllers-1 (Pro
	 * Controller) are created lazily the first time that index is actually
	 * driven, since most sessions never use a second player.
	 */
	std::array<EmulatedControllerPtr, kLucentMaxControllers> g_controllers{};

	/**
	 * Resolves controller_index to its EmulatedController, creating a Pro
	 * Controller the first time a non-primary index is driven. Returns null
	 * for an out-of-range index or if index 0 has not been created yet by
	 * start() -- callers must fail closed on null rather than aliasing onto
	 * another slot's state.
	 */
	EmulatedControllerPtr controller_for_index(uint32_t controllerIndex)
	{
		if (controllerIndex >= kLucentMaxControllers)
			return {};
		if (g_controllers[controllerIndex])
			return g_controllers[controllerIndex];
		if (controllerIndex == 0)
			return {};
		EmulatedControllerPtr controller = InputManager::instance().get_controller(controllerIndex);
		if (!controller)
			controller = InputManager::instance().set_controller(controllerIndex, EmulatedController::Type::Pro);
		g_controllers[controllerIndex] = controller;
		return controller;
	}

	// --- PROCESS-WIDE STATE -------------------------------------------------
	//
	// Cemu is a one-title-per-process emulator upstream. Its Android frontend
	// calls initializeEmulation() once from CemuApplication and then
	// exitProcess(0) when the user quits a game (EmulationActivity.kt::onQuit),
	// so nothing upstream ever re-enters that path. Lucent keeps the library
	// mapped and launches again in the same process, which means every
	// process-wide step has to run EXACTLY ONCE. These are file-scope on
	// purpose: they describe the process, not a session, and they must survive
	// the lucent_native_engine being destroyed and re-created between titles.
	std::atomic<bool> g_process_initialised{false};
	std::atomic<bool> g_title_prepared{false};
	// Content path of the still-prepared title, so a same-title relaunch
	// can adopt an abandoned prepare instead of refusing (see load()).
	std::string g_prepared_content_path;
	std::string g_process_system_root;

	/**
	 * Every signal CemuCommonInit() takes over, via ExceptionHandler_Init().
	 *
	 * SIGIOT is deliberately absent: Linux defines it as an alias of SIGABRT, so
	 * listing it would snapshot and restore the same disposition twice.
	 */
	constexpr int kCemuHijackedSignals[] = {
		SIGABRT, SIGBUS, SIGFPE, SIGILL, SIGINT,
		SIGQUIT, SIGSEGV, SIGSYS, SIGTERM, SIGTRAP,
	};
	constexpr size_t kCemuHijackedSignalCount =
		sizeof(kCemuHijackedSignals) / sizeof(kCemuHijackedSignals[0]);

	/**
	 * Keeps Cemu's desktop crash handler from taking over Lucent's process.
	 *
	 * CemuCommonInit() calls ExceptionHandler_Init(), which sigaction()s the ten
	 * signals above to handlers that end in _Exit(1) (fatal signals) or _Exit(0)
	 * (SIGINT/SIGTERM). On the desktop that is a courtesy. Inside Lucent it is a
	 * PROCESS-WIDE takeover, installed the first time a Wii U title loads and
	 * never removed, with three consequences:
	 *
	 *   * It replaces Android's debuggerd disposition, so from that moment on NO
	 *     native crash anywhere in the app -- Cemu, Eden, Qt, ART -- produces a
	 *     tombstone. Worse, _Exit(1) is a NORMAL exit, so ActivityManager logs
	 *     "Process ... exited cleanly (1)", the Java uncaught-exception path
	 *     never runs, and nothing is written to the crash log buffer. A real
	 *     abort in this process was reaching logcat as one bare line,
	 *     "libc++abi: terminating", with no stack of any kind behind it.
	 *   * ART uses SIGSEGV for implicit null checks, GC read barriers and the
	 *     stack-overflow guard page. The handler is installed with a null
	 *     oldact and never chains, so faults the runtime is supposed to handle
	 *     and resume from become a hard exit instead.
	 *   * The handler is not async-signal-safe. It allocates, formats through
	 *     fmt, opens and writes log.txt, and walks the stack with
	 *     boost::stacktrace -- all from a signal context, in a process whose
	 *     other threads are still running.
	 *
	 * Nothing in Cemu RECOVERS from these signals; the handler is reporting
	 * only, and its report lands in a log.txt inside Lucent's private engine
	 * directory that neither the user nor Android's crash pipeline ever sees. So
	 * the dispositions in force before CemuCommonInit() are snapshotted and put
	 * back immediately afterwards. Cemu keeps everything that actually runs a
	 * title; Android keeps its own crash reporting for the whole process.
	 */
	class HostSignalDispositions
	{
	  public:
		/** Snapshots the current disposition of every signal Cemu will claim. */
		HostSignalDispositions()
		{
			for (size_t index = 0; index < kCemuHijackedSignalCount; index++)
				m_captured[index] =
					sigaction(kCemuHijackedSignals[index], nullptr, &m_saved[index]) == 0;
		}

		/** Puts each snapshotted disposition back, skipping any that failed. */
		void restore() const
		{
			for (size_t index = 0; index < kCemuHijackedSignalCount; index++)
			{
				if (m_captured[index])
					sigaction(kCemuHijackedSignals[index], &m_saved[index], nullptr);
			}
		}

	  private:
		struct sigaction m_saved[kCemuHijackedSignalCount] {};
		bool m_captured[kCemuHijackedSignalCount] {};
	};

	/**
	 * Directory the adapter itself was loaded from. Derived from our own symbol
	 * rather than passed in, so the ABI does not need to carry an
	 * Android-specific path. Cemu's custom-driver loader reads it.
	 */
	std::string adapter_library_directory()
	{
		Dl_info info{};
		if (dladdr(reinterpret_cast<const void*>(&lucent_native_adapter_entry), &info) == 0 ||
			info.dli_fname == nullptr)
			return std::string();
		const std::string path(info.dli_fname);
		const auto separator = path.find_last_of('/');
		return separator == std::string::npos ? std::string() : path.substr(0, separator);
	}

	/**
	 * Lucent's canonical controls are already console-semantic, so LUCENT_PAD_A
	 * means the Wii U GamePad's A. These go to EmulatedController's override
	 * maps (setButtonValue/setAxisValue), which are Cemu's equivalent of Eden's
	 * VirtualGamepad: get_axis_value() and is_mapping_down() consult the
	 * override before any physical controller, so no GUID, no InputAPI::Device
	 * registration and no user input profile is needed. The alternative path,
	 * CreateDefaultDeviceController() plus set_mapping(), needs a written
	 * profile that Lucent never produces.
	 */
	bool vpad_button_for(lucent_native_control control, uint64& out)
	{
		switch (control)
		{
		case LUCENT_PAD_A:          out = VPADController::kButtonId_A;     return true;
		case LUCENT_PAD_B:          out = VPADController::kButtonId_B;     return true;
		case LUCENT_PAD_X:          out = VPADController::kButtonId_X;     return true;
		case LUCENT_PAD_Y:          out = VPADController::kButtonId_Y;     return true;
		case LUCENT_PAD_L:          out = VPADController::kButtonId_L;     return true;
		case LUCENT_PAD_R:          out = VPADController::kButtonId_R;     return true;
		case LUCENT_PAD_ZL:         out = VPADController::kButtonId_ZL;    return true;
		case LUCENT_PAD_ZR:         out = VPADController::kButtonId_ZR;    return true;
		case LUCENT_PAD_L3:         out = VPADController::kButtonId_StickL; return true;
		case LUCENT_PAD_R3:         out = VPADController::kButtonId_StickR; return true;
		case LUCENT_PAD_DPAD_UP:    out = VPADController::kButtonId_Up;    return true;
		case LUCENT_PAD_DPAD_DOWN:  out = VPADController::kButtonId_Down;  return true;
		case LUCENT_PAD_DPAD_LEFT:  out = VPADController::kButtonId_Left;  return true;
		case LUCENT_PAD_DPAD_RIGHT: out = VPADController::kButtonId_Right; return true;
		// The Wii U labels these Plus and Minus; Lucent's canonical names are
		// the generic Start/Select the rest of the library uses.
		case LUCENT_PAD_START:      out = VPADController::kButtonId_Plus;  return true;
		case LUCENT_PAD_SELECT:     out = VPADController::kButtonId_Minus; return true;
		case LUCENT_PAD_HOME:       out = VPADController::kButtonId_Home;  return true;
		default:                                                           return false;
		}
	}

	/**
	 * Same idea as vpad_button_for, for a second/third/... player's Wii U Pro
	 * Controller. ProController's button shape is structurally close to
	 * VPADController's (A/B/X/Y/L/R/ZL/ZR/Plus/Minus/d-pad/two sticks), so this
	 * mirrors that table onto ProController::ButtonId.
	 *
	 * LUCENT_PAD_HOME is deliberately absent: the Home button is a GamePad-only
	 * gesture on real Wii U hardware, and adapter_set_control() always routes
	 * it to controller_index 0's VPAD before this table would ever be
	 * consulted (see the touch/Home redirect there).
	 */
	bool pro_button_for(lucent_native_control control, uint64& out)
	{
		switch (control)
		{
		case LUCENT_PAD_A:          out = ProController::kButtonId_A;     return true;
		case LUCENT_PAD_B:          out = ProController::kButtonId_B;     return true;
		case LUCENT_PAD_X:          out = ProController::kButtonId_X;     return true;
		case LUCENT_PAD_Y:          out = ProController::kButtonId_Y;     return true;
		case LUCENT_PAD_L:          out = ProController::kButtonId_L;     return true;
		case LUCENT_PAD_R:          out = ProController::kButtonId_R;     return true;
		case LUCENT_PAD_ZL:         out = ProController::kButtonId_ZL;    return true;
		case LUCENT_PAD_ZR:         out = ProController::kButtonId_ZR;    return true;
		case LUCENT_PAD_L3:         out = ProController::kButtonId_StickL; return true;
		case LUCENT_PAD_R3:         out = ProController::kButtonId_StickR; return true;
		case LUCENT_PAD_DPAD_UP:    out = ProController::kButtonId_Up;    return true;
		case LUCENT_PAD_DPAD_DOWN:  out = ProController::kButtonId_Down;  return true;
		case LUCENT_PAD_DPAD_LEFT:  out = ProController::kButtonId_Left;  return true;
		case LUCENT_PAD_DPAD_RIGHT: out = ProController::kButtonId_Right; return true;
		case LUCENT_PAD_START:      out = ProController::kButtonId_Plus;  return true;
		case LUCENT_PAD_SELECT:     out = ProController::kButtonId_Minus; return true;
		default:                                                          return false;
		}
	}

	/**
	 * VPAD/Pro both store each stick as four unsigned magnitudes and resolve
	 * them with `x = (left > right) ? -left : right`, so a single signed axis
	 * has to be split across the opposing pair and the unused side explicitly
	 * zeroed -- otherwise a push left would leave the previous right magnitude
	 * latched. Takes the target controller explicitly so it works for any
	 * controller_index, not just the primary VPAD.
	 */
	void apply_stick_axis(const EmulatedControllerPtr& controller,
	                      uint64 negativeId, uint64 positiveId, float value)
	{
		if (!controller)
			return;
		const float magnitude = value < 0.0f ? -value : value;
		const float clamped = magnitude > 1.0f ? 1.0f : magnitude;
		if (value < 0.0f)
		{
			controller->setAxisValue(negativeId, clamped);
			controller->setAxisValue(positiveId, 0.0f);
		}
		else
		{
			controller->setAxisValue(positiveId, clamped);
			controller->setAxisValue(negativeId, 0.0f);
		}
	}

	/**
	 * Clears every control override before the pads are handed back.
	 *
	 * EmulatedController lives in InputManager and outlives a title, so a
	 * button Lucent never sent an up event for would still read as held when
	 * the next title boots. VPAD/Pro resolve a stick from four unsigned
	 * magnitudes, so all four have to be zeroed, not just the two last written.
	 *
	 * Index 0's VPAD is treated as a permanent, process-lifetime controller
	 * (matching how it was already created once and reused before this
	 * change) and is only reset to neutral, never deleted. Every
	 * controller_index above it was created lazily for this title alone, so
	 * each allocated slot is also removed from InputManager via
	 * delete_controller() -- otherwise a second-player Pro Controller would
	 * leak into the next in-process title relaunch exactly like the
	 * documented g_title_prepared leak this file was already fixed for once.
	 */
	void release_all_controls()
	{
		static constexpr lucent_native_control kVpadOnlyDigital[] = {
			LUCENT_PAD_HOME,
		};
		static constexpr lucent_native_control kSharedDigital[] = {
			LUCENT_PAD_A, LUCENT_PAD_B, LUCENT_PAD_X, LUCENT_PAD_Y,
			LUCENT_PAD_L, LUCENT_PAD_R, LUCENT_PAD_ZL, LUCENT_PAD_ZR,
			LUCENT_PAD_DPAD_UP, LUCENT_PAD_DPAD_DOWN,
			LUCENT_PAD_DPAD_LEFT, LUCENT_PAD_DPAD_RIGHT,
			LUCENT_PAD_START, LUCENT_PAD_SELECT,
			LUCENT_PAD_L3, LUCENT_PAD_R3,
		};

		if (g_controllers[0])
		{
			for (lucent_native_control control : kSharedDigital)
			{
				uint64 button = 0;
				if (vpad_button_for(control, button))
					g_controllers[0]->setButtonValue(button, false);
			}
			for (lucent_native_control control : kVpadOnlyDigital)
			{
				uint64 button = 0;
				if (vpad_button_for(control, button))
					g_controllers[0]->setButtonValue(button, false);
			}
			static constexpr uint64 kVpadAxes[] = {
				VPADController::kButtonId_StickL_Left, VPADController::kButtonId_StickL_Right,
				VPADController::kButtonId_StickL_Up, VPADController::kButtonId_StickL_Down,
				VPADController::kButtonId_StickR_Left, VPADController::kButtonId_StickR_Right,
				VPADController::kButtonId_StickR_Up, VPADController::kButtonId_StickR_Down,
			};
			for (uint64 axis : kVpadAxes)
				g_controllers[0]->setAxisValue(axis, 0.0f);
			auto& touchInfo = InputManager::instance().m_pad_mouse;
			std::scoped_lock touchLock(touchInfo.m_mutex);
			touchInfo.left_down = touchInfo.left_down_toggle = false;
		}

		for (uint32_t index = 1; index < kLucentMaxControllers; index++)
		{
			if (!g_controllers[index])
				continue;
			for (lucent_native_control control : kSharedDigital)
			{
				uint64 button = 0;
				if (pro_button_for(control, button))
					g_controllers[index]->setButtonValue(button, false);
			}
			static constexpr uint64 kProAxes[] = {
				ProController::kButtonId_StickL_Left, ProController::kButtonId_StickL_Right,
				ProController::kButtonId_StickL_Up, ProController::kButtonId_StickL_Down,
				ProController::kButtonId_StickR_Left, ProController::kButtonId_StickR_Right,
				ProController::kButtonId_StickR_Up, ProController::kButtonId_StickR_Down,
			};
			for (uint64 axis : kProAxes)
				g_controllers[index]->setAxisValue(axis, 0.0f);
			InputManager::instance().delete_controller(index);
			g_controllers[index].reset();
		}
	}

	/**
	 * Re-syncs Cemu's window geometry to the extent its swapchain actually got.
	 *
	 * On Android VkSurfaceCapabilitiesKHR::currentExtent is always a concrete
	 * value, so SwapchainInfoVk::ChooseSwapExtent DISCARDS the size Cemu was
	 * asked for and uses the surface's own extent. Everything downstream,
	 * however, keeps trusting WindowSystem's phys_width/phys_height:
	 * LatteRenderTarget_getScreenImageArea centres the 16:9 letterbox inside
	 * phys_*, while DrawBackbufferQuad's scissor and render area are the
	 * swapchain extent anchored at origin 0,0. When ANativeWindow reports a
	 * window taller than the surface the compositor actually hands Vulkan --
	 * which is exactly what a late gesture/navigation inset does -- the picture
	 * is centred against the taller number, pushed down by half the difference,
	 * and then hard-clipped by the scissor. The result is a correctly scaled
	 * image with the bottom edge cut off, which is the reported symptom.
	 *
	 * The same mismatch also makes VulkanRenderer::UpdateSwapchainProperties
	 * compare phys_* against getExtent() on every AcquireNextSwapchainImage,
	 * always see a difference, and rebuild the swapchain forever without
	 * converging.
	 *
	 * Writing the real extent back fixes both: it is the size of the surface
	 * Cemu presents into, so the letterbox, the scissor and the recreation
	 * check finally agree. Cemu's own frontend never needs this because its
	 * SurfaceHolder callback reports the post-inset size; Lucent reads
	 * ANativeWindow directly, which can still be the pre-layout size.
	 */
	void sync_window_size_to_swapchain(bool mainCanvas)
	{
		auto* renderer = VulkanRenderer::GetInstance();
		if (renderer == nullptr)
			return;
		const auto& chain = renderer->GetChainInfoPtr(mainCanvas);
		if (!chain)
			return;
		const VkExtent2D extent = chain->getExtent();
		if (extent.width == 0 || extent.height == 0)
			return;
		auto& windowInfo = WindowSystem::GetWindowInfo();
		const sint32 width = static_cast<sint32>(extent.width);
		const sint32 height = static_cast<sint32>(extent.height);
		if (mainCanvas)
		{
			windowInfo.width = windowInfo.phys_width = width;
			windowInfo.height = windowInfo.phys_height = height;
		}
		else
		{
			windowInfo.pad_width = windowInfo.phys_pad_width = width;
			windowInfo.pad_height = windowInfo.phys_pad_height = height;
		}
	}

	constexpr const char* kLogTag = "LucentCemuAdapter";

	/** Reports an escaping exception once, with the entry point that raised it. */
	void report_escaping_exception(const char* entryPoint, const char* detail)
	{
		__android_log_print(ANDROID_LOG_ERROR, kLogTag,
		                    "Cemu raised an exception across adapter %s: %s",
		                    entryPoint, detail);
	}

	/**
	 * Stops any C++ exception from crossing the adapter ABI.
	 *
	 * lucent_native_adapter is a table of C function pointers, and Lucent calls
	 * them from C (unified-android/native/lucent_native_adapter_host.c) and from
	 * JNI. There is no C++ frame between the engine and the JVM that could catch
	 * anything, so an exception leaving one of these entry points does not
	 * surface as an error -- it unwinds into frames that cannot handle it and
	 * ends in std::terminate, taking the whole Lucent process with it.
	 *
	 * Cemu throws for real, not hypothetically: SwapchainInfoVk's constructor
	 * throws std::runtime_error when vkCreateAndroidSurfaceKHR fails, and the
	 * filesystem and title-parsing paths reachable from load() throw too. The
	 * ABI already has a failure value for every one of these calls, so the
	 * correct behaviour is to report the failure through it and let Lucent
	 * decide, which for a lost surface means the session ends with a message
	 * instead of the app disappearing.
	 */
	template <typename Result, typename Body>
	Result guard_abi(const char* entryPoint, Result failure, Body&& body) noexcept
	{
		try
		{
			return body();
		}
		catch (const std::exception& error)
		{
			report_escaping_exception(entryPoint, error.what());
		}
		catch (...)
		{
			report_escaping_exception(entryPoint, "unknown exception");
		}
		return failure;
	}

	/** guard_abi for the entry points the ABI declares void. */
	template <typename Body>
	void guard_abi_void(const char* entryPoint, Body&& body) noexcept
	{
		try
		{
			body();
		}
		catch (const std::exception& error)
		{
			report_escaping_exception(entryPoint, error.what());
		}
		catch (...)
		{
			report_escaping_exception(entryPoint, "unknown exception");
		}
	}
} // namespace

struct lucent_native_engine
{
	std::atomic<bool> loaded{false};
	std::atomic<bool> started{false};
	ANativeWindow* tv_window{nullptr};
	ANativeWindow* pad_window{nullptr};
	lucent_native_audio_sink audio_sink{nullptr};
	void* audio_sink_ctx{nullptr};
	std::string content_path;
	// Lucent delivers touch as normalised 0..1 within the GamePad view; the
	// last position is retained because press and move arrive as separate axes.
	float touch_x{0.0f};
	float touch_y{0.0f};
	bool gamepad_on_primary{false};
};

static void set_primary_screen(lucent_native_engine* engine, bool gamepad)
{
	// Use Cemu Android's existing held-TAB view selection. Account for a
	// game's startWithPadView preference without changing that saved profile.
	engine->gamepad_on_primary = engine->pad_window == nullptr && gamepad;
	const bool swapped = engine->pad_window == nullptr &&
		(engine->gamepad_on_primary != ActiveSettings::DisplayDRCEnabled());
	WindowSystem::GetWindowInfo().set_keystate(
		static_cast<uint32>(WindowSystem::PlatformKeyCodes::TAB), swapped);
	// Neither a screen switch nor a display rebind may leave a stylus held
	// on the canvas that just stopped owning it.
	auto& input = InputManager::instance();
	std::scoped_lock touchLock(input.m_main_mouse.m_mutex, input.m_pad_mouse.m_mutex);
	input.m_main_mouse.left_down = input.m_main_mouse.left_down_toggle = false;
	input.m_pad_mouse.left_down = input.m_pad_mouse.left_down_toggle = false;
}

static void adapter_describe(lucent_native_capabilities* out)
{
	if (out == nullptr)
		return;
	std::memset(out, 0, sizeof(*out));
	out->abi_version = LUCENT_NATIVE_ADAPTER_ABI_VERSION;
	out->engine_id = kEngineId;
	out->engine_version = kEngineVersion;
	// Cemu has no savestate or full-machine snapshot API at all, so Lucent must
	// not advertise Quick Resume for Wii U. Held-Stop flushes the game's own
	// saves and exits instead of promising a snapshot that cannot be restored.
	out->has_quick_resume = false;
	out->has_persistent_save = true;
	// The Wii U is genuinely two-screen and the Thor has a second display, so
	// the GamePad view is rendered to Lucent's lower window rather than being
	// composited into the TV view or dropped.
	out->dual_screen = true;
	// ONE user-supplied blob: keys.txt, the disc-key list Cemu's KeyCache reads
	// from ActiveSettings::GetUserDataPath("keys.txt").
	//
	// Cemu genuinely needs NO console firmware dump, and a title that is already
	// decrypted (RPX/ELF, extracted content, WUA) needs no key either. But real
	// Wii U libraries are overwhelmingly encrypted .wud/.wux disc images, and
	// those cannot be opened at all without a matching key. Reporting 0 here was
	// what stopped Lucent installing the key directory: the resolver treats the
	// count as its gate and installed nothing, so Cemu was handed an empty root
	// and failed with "no disc key was supplied" even though the user had one.
	// Declaring 1 asks EmuFusion to install disc keys. The Java resolver uses
	// the actual content type: missing keys do not block decrypted WUA/RPX/ELF.
	out->required_firmware = 1;
	// InputManager's own player-index ceiling (kMaxController = 2 VPAD slots +
	// 7 WPAD slots = 8), which this adapter honors exactly: index 0 is the
	// real VPAD GamePad, indices 1..7 are lazily created Pro Controllers. This
	// is the engine's true multi-controller capacity, not an alpha-imposed
	// cap -- a lower player limit for the current multiplayer alpha belongs in
	// the Java/UI layer, not in this honest capability report.
	out->max_controllers = static_cast<uint32_t>(kLucentMaxControllers);
}

static lucent_native_engine* adapter_create(void)
{
	return new (std::nothrow) lucent_native_engine();
}

static bool adapter_load(lucent_native_engine* engine,
                         const lucent_native_load_request* request,
                         char* error, size_t error_size)
{
	const auto fail = [&](const char* message) {
		if (error != nullptr && error_size > 0)
			std::snprintf(error, error_size, "%s", message);
		return false;
	};
	if (engine == nullptr || request == nullptr)
		return fail("adapter load received no engine or request");
	if (request->content_path == nullptr || request->content_path[0] == '\0')
		return fail("no Wii U content path was supplied");
	if (request->system_directory == nullptr || request->system_directory[0] == '\0')
		// The emulated NAND (mlc01), keys and per-title caches all live under
		// this root. Refuse rather than silently writing into the wrong place.
		return fail("no validated Wii U system directory was supplied");

	const fs::path systemRoot{request->system_directory};

	// True for every load after the first one in this process, whether or not
	// Lucent re-used the same lucent_native_engine. Used only to give Lucent a
	// distinguishable, honest message: a title that booted once and then
	// refuses is a session problem, not a bad dump.
	const bool relaunch = g_process_initialised.load();

	// A title that was prepared but never launched cannot be un-prepared: Cemu
	// only releases the mounts and the memory space from ShutdownTitle(), and
	// ShutdownTitle() returns immediately unless a title is actually running.
	// Preparing a second title over the top of that would double-mount
	// /vol/content and corrupt the FSC tree. But when the SAME content is
	// being loaded again, the still-prepared state is exactly what this
	// launch needs: adopt it instead of refusing. Abandoned prepares happen
	// in the field — a session that loads and is torn down before start()
	// (surface never delivered, launch cancelled) — and the old
	// refuse-everything behaviour meant one such launch poisoned every later
	// Wii U launch until the app restarted (user-reported 2026-08-17:
	// "after I quit a game, the emulator won't even open anymore").
	// A DIFFERENT title still refuses honestly.
	if (g_title_prepared.load())
	{
		const std::string requested =
		        fs::path(request->content_path).generic_string();
		if (requested == g_prepared_content_path && !requested.empty())
		{
			engine->content_path.assign(request->content_path);
			engine->loaded.store(true);
			__android_log_print(ANDROID_LOG_INFO, kLogTag,
			        "adopting still-prepared Wii U title for relaunch");
			return true;
		}
		return fail("a previous Wii U title is still resident; close and reopen Lucent to play again");
	}

	// ---- ONE-SHOT, PROCESS-WIDE INITIALISATION -----------------------------
	//
	// Everything below runs EXACTLY ONCE per process. Cemu's own Android
	// frontend calls this sequence once from CemuApplication and then
	// exitProcess(0) on quit, so upstream has no re-entry path and several of
	// these steps are actively harmful the second time:
	//
	//   CafeSystem::Initialize()  is already latched behind its own
	//                             s_initialized, so re-running it is a no-op --
	//                             but everything AROUND it is not.
	//   CafeTitleList::Initialize() re-reads title_list_cache.xml into an
	//                             already populated list (upstream asserts
	//                             sTLList.empty() in debug builds).
	//   CafeTitleList::Refresh()  starts a scan worker that DELETES every
	//                             TitleInfo it cannot rediscover. Lucent
	//                             configures no Cemu game paths -- the library
	//                             lives in Lucent's own index and the title
	//                             sits outside the emulated MLC -- so the
	//                             worker frees the exact entry the prepare step
	//                             below is about to look up, and races
	//                             unlocked against AddTitleFromPath.
	//   AddScanPath()             appends to sTLScanPaths without clearing.
	//   PPCTimer_init()           detaches another three-second measuring
	//                             thread that rewrites _rdtscFrequency under a
	//                             title that is already running.
	//   InputManager::load()      rebuilds the controllers Lucent is driving.
	//   GraphicPack2::LoadAll()   re-reads every pack from disk.
	//
	// Cemu's own in-process relaunch path, coreinit::OSLauncherThread, does
	// ShutdownTitle -> PrepareForegroundTitle -> LaunchForegroundTitle and
	// re-runs NONE of this. The adapter now matches that shape.
	if (!g_process_initialised.load())
	{
		// Point Cemu at Lucent's validated per-engine roots before anything
		// reads config, keys, NAND or save data. Cemu is normally told these by
		// its own Application object; there is no Activity here to do it. The
		// argument order matches NativeActiveSettings::initializeActiveSettings,
		// which also passes an empty executable path on Android.
		//
		// Every root is the Lucent system directory on purpose. Cemu keeps Wii U
		// game saves INSIDE its emulated NAND (mlc01/usr/save), not in a flat
		// per-title folder, so the ABI's separate save_directory has no place to
		// map onto without breaking the NAND layout. Lucent's save handling must
		// treat the mlc tree under the system directory as the save location.
		std::set<fs::path> failedWriteAccess;
		ActiveSettings::SetPaths(false, {}, systemRoot, systemRoot,
		                         systemRoot / "cache", systemRoot, failedWriteAccess);
		if (!failedWriteAccess.empty())
			return fail("Cemu could not write to the supplied Wii U system directory");
		// The custom-driver path reads both of these before falling back to the
		// system Vulkan loader; leaving them empty would have it probe "/".
		ActiveSettings::SetNativeLibPath(adapter_library_directory());
		ActiveSettings::SetInternalDir(systemRoot);

		// FilesystemAndroid callbacks are deliberately NOT installed. Cemu's
		// AndroidFilesystemCallbacks constructor FindClass-es
		// info/cemu/cemu/nativeinterface/NativeFiles, which does not exist in
		// Lucent's dex and would abort ART. The callbacks are only consulted for
		// content:// URIs (FilesystemAndroid::IsContentUri) and every accessor is
		// null-safe, so leaving them unset is correct as long as Lucent passes
		// real filesystem paths -- which it does.

		// This is initializeEmulation()'s body, in Cemu's own order. Only the
		// AndroidFilesystemCallbacks line is omitted, for the reason above.
		GetConfigHandle().SetFilename(ActiveSettings::GetConfigPath("settings.xml").generic_wstring());
		// Without this the emulated NAND has no sys/usr tree and no language or
		// country table, and titles fault while probing /vol/storage_mlc01.
		NativeEmulation::CreateCemuDirectories();
		NetworkConfig::LoadOnce();
		ActiveSettings::Init();
		LatteOverlay_init();
		// CemuCommonInit brings up the config, crypto, PPC timer, input manager,
		// CafeSystem, the title list and the save list. Nothing that touches a
		// title may run before it.
		//
		// It also calls ExceptionHandler_Init(), which is the ONLY thing in the
		// whole engine that installs signal handlers. Bracketing just this call
		// is therefore exact: nothing else inside it claims a signal, so putting
		// the snapshot back cannot undo a disposition some other Cemu subsystem
		// wanted. See HostSignalDispositions for why it must not stand.
		const HostSignalDispositions hostSignals;
		CemuCommonInit();
		hostSignals.restore();

		// Cemu's default vsync=0 selects VK_PRESENT_MODE_IMMEDIATE_KHR. On a
		// desktop monitor that only tears; on Lucent's SurfaceTexture-backed
		// window the consumer is EmuFusion's frame generator, and Android's
		// BufferQueue DROPS the queued image whenever a new present arrives
		// before the consumer latched the previous one. Emulation stalls make
		// presents bursty, so unique frames are physically lost and the
		// measured source rate at the generator swings tens of hertz around
		// the guest's real cadence (observed 21-59 Hz on NES Remix,
		// 2026-08-16). FIFO queues every image and blocks the producer when
		// the queue is full, pacing Cemu to the consumer without losing a
		// frame; the generator drains at panel rate, so a 60 fps guest is
		// never throttled by it.
		GetConfig().vsync = static_cast<int>(SwapchainInfoVk::VSync::FIFO);

		// Load the user's disc keys out of the system directory Lucent
		// validated. This is Cemu's own key path, not a reimplementation:
		// KeyCache_Prepare() reads ActiveSettings::GetUserDataPath("keys.txt"),
		// which the SetPaths call above resolved to <system_directory>/keys.txt,
		// and parses it exactly as the desktop build does -- one
		// 32-hex-character AES-128 key per line, '#' and ';' comments,
		// whitespace and '-'/'_' separators stripped. Lucent's
		// NativeAdapterSystemDirectory has already copied the user's keys.txt
		// there, which is why describe() reports required_firmware = 1.
		//
		// FSTVolume::OpenFromDiscImage calls this itself, so the explicit call
		// is about ORDER and INTENT rather than reachability: it guarantees the
		// cache is populated from Lucent's root before any title parse can latch
		// KeyCache's one-shot sKeyCachePrepared flag, and it keeps the key
		// dependency visible at the point Lucent's system directory is consumed.
		// It must run after CemuCommonInit() because AES128_init() lives there
		// and the keys are useless until the cipher is up.
		KeyCache_Prepare();

		g_process_system_root = systemRoot.generic_string();
		g_process_initialised.store(true);

		// CemuCommonInit() left a title-list scan running. Its removal phase
		// runs WITHOUT holding sTLMutex and frees every TitleInfo it did not
		// rediscover, so letting it overlap AddTitleFromPath below is a
		// use-after-free on the entry the prepare step needs. There is nothing
		// for it to find -- Lucent registers no Cemu game paths -- so this
		// costs milliseconds once per process.
		while (CafeTitleList::IsScanning())
			std::this_thread::sleep_for(std::chrono::milliseconds(5));

		// Cemu's 32 MiB CEMU_AREA is a process-lifetime bump allocator.  Its
		// prefix now contains every process-owned SysAllocator, while allocations
		// made by coreinit_start (including the 8 MiB system heap) belong to one
		// title.  The stock Android frontend exits its process after that title,
		// so upstream never has to distinguish the two.  Lucent does: capture the
		// permanent boundary before the first PrepareForegroundTitle, then stop()
		// can reclaim the title suffix for every same-process launch.
		coreinit_markProcessSysAreaEnd();
	}
	else if (g_process_system_root != systemRoot.generic_string())
	{
		// ActiveSettings' roots are latched into the emulated NAND layout, the
		// key cache and the shader cache paths; moving them under a live
		// process is not something Cemu supports.
		return fail("Cemu's Wii U system directory cannot change without restarting Lucent");
	}

	// A fresh device can first run decrypted content with no disc keys, then
	// import keys and launch a disc without restarting EmuFusion. The original
	// one-shot cache would retain the empty list from that first launch. All
	// previous title workers have stopped and the initial title scan has joined;
	// refresh only here, never while a reader can hold a cached key pointer.
	if (relaunch) KeyCache_Reload();

	// prepareTitle equivalent. Cemu's own frontend runs this BEFORE the audio
	// devices and BEFORE the renderer, because PrepareForegroundTitle is what
	// loads the game profile that the Vulkan driver selection then reads.
	// Reordering it produces a renderer configured against a default profile.
	const fs::path launchPath{engine->content_path.assign(request->content_path)};
	TitleInfo launchTitle{launchPath};
	if (launchTitle.IsValid())
	{
		CafeTitleList::AddTitleFromPath(launchPath);
		TitleId baseTitleId;
		if (!CafeTitleList::FindBaseTitleId(launchTitle.GetAppTitleId(), baseTitleId))
			return fail("the base game files for this Wii U title were not found");
		if (CafeSystem::PrepareForegroundTitle(baseTitleId) != CafeSystem::PREPARE_STATUS_CODE::SUCCESS)
			return fail(relaunch
			                ? "Cemu could not prepare this Wii U title a second time; close and reopen Lucent"
			                : "Cemu could not prepare this Wii U title");
	}
	else
	{
		const CafeTitleFileType fileType = DetermineCafeSystemFileType(launchPath);
		if (fileType == CafeTitleFileType::RPX || fileType == CafeTitleFileType::ELF)
		{
			if (CafeSystem::PrepareForegroundTitleFromStandaloneRPX(launchPath) != CafeSystem::PREPARE_STATUS_CODE::SUCCESS)
				return fail(relaunch
				                ? "Cemu could not prepare this standalone RPX/ELF a second time; close and reopen Lucent"
				                : "Cemu could not prepare this standalone RPX/ELF");
		}
		else if (launchTitle.GetInvalidReason() == TitleInfo::InvalidReason::NO_DISC_KEY)
			return fail("this disc image is encrypted and no disc key was supplied");
		else if (launchTitle.GetInvalidReason() == TitleInfo::InvalidReason::NO_TITLE_TIK)
			return fail("this title is encrypted and no ticket was supplied");
		else
			return fail("this file is not a Wii U title Cemu can launch");
	}

	g_title_prepared.store(true);
	g_prepared_content_path = launchPath.generic_string();
	engine->loaded.store(true);
	return true;
}

static bool adapter_start(lucent_native_engine* engine, const lucent_native_io* io,
                          char* error, size_t error_size)
{
	const auto fail = [&](const char* message) {
		if (error != nullptr && error_size > 0)
			std::snprintf(error, error_size, "%s", message);
		return false;
	};
	if (engine == nullptr || io == nullptr)
		return fail("adapter start received no engine or io");
	if (!engine->loaded.load())
		return fail("adapter start called before a title was loaded");
	if (io->primary_window == nullptr)
		return fail("Lucent supplied no render window");
	if (engine->started.load())
		return true;

	engine->tv_window = static_cast<ANativeWindow*>(io->primary_window);
	engine->pad_window = static_cast<ANativeWindow*>(io->lower_window);
	engine->audio_sink = io->audio_sink;
	engine->audio_sink_ctx = io->audio_sink_ctx;

	// setSurface/setSurfaceSize equivalent. window_main is what the renderer
	// probes to pick a physical device; canvas_main and canvas_pad are the
	// surfaces the two swapchains actually present to.
	auto& windowInfo = WindowSystem::GetWindowInfo();
	using Backend = WindowSystem::WindowHandleInfo::Backend;
	windowInfo.window_main.backend = Backend::Android;
	windowInfo.canvas_main.backend = Backend::Android;
	windowInfo.canvas_pad.backend = Backend::Android;
	windowInfo.app_active = true;
	// dpi_scale defaults to zero and is used as a divisor by the overlay.
	windowInfo.dpi_scale = windowInfo.pad_dpi_scale = 1.0;

	const int tvWidth = ANativeWindow_getWidth(engine->tv_window);
	const int tvHeight = ANativeWindow_getHeight(engine->tv_window);
	windowInfo.width = windowInfo.phys_width = tvWidth;
	windowInfo.height = windowInfo.phys_height = tvHeight;
	windowInfo.window_main.surface = engine->tv_window;
	windowInfo.canvas_main.surface = engine->tv_window;

	int padWidth = 0;
	int padHeight = 0;
	if (engine->pad_window != nullptr)
	{
		padWidth = ANativeWindow_getWidth(engine->pad_window);
		padHeight = ANativeWindow_getHeight(engine->pad_window);
		windowInfo.pad_width = windowInfo.phys_pad_width = padWidth;
		windowInfo.pad_height = windowInfo.phys_pad_height = padHeight;
		windowInfo.canvas_pad.surface = engine->pad_window;
		windowInfo.pad_open = true;
	}
	else
	{
		// Single-screen host: the menu selects TV or GamePad on the primary
		// swapchain; there is no automatic two-picture composition in Cemu.
		windowInfo.pad_open = false;
	}

	// initializeSystems equivalent. Lucent injects input through the emulated
	// controller's override maps, so no InputAPI::Device controller is created
	// and no profile is required; the pad only has to exist.
	windowInfo.set_keystatesup();
	set_primary_screen(engine, false);
	g_controllers[0] = InputManager::instance().get_controller(0);
	if (!g_controllers[0])
		g_controllers[0] = InputManager::instance().set_controller(0, EmulatedController::Type::VPAD);
	if (!g_controllers[0])
		return fail("Cemu could not create the emulated Wii U GamePad");

	if (engine->audio_sink != nullptr)
	{
		std::unique_lock audioLock(g_audioMutex);
		// TV audio carries the full mix. A second device for the GamePad would
		// push a duplicate of the same programme into Lucent's single sink, so
		// g_padAudio is deliberately left unset.
		g_tvAudio = std::make_unique<LucentAudioAPI>(
			engine->audio_sink, engine->audio_sink_ctx,
			snd_core::AX_SAMPLES_PER_3MS_48KHZ * kAxFramesPerGroup);
		g_tvAudio->Play();
	}

	// initializeRenderer equivalent. Cemu's own frontend builds a throwaway
	// SurfaceTexture here purely so VulkanRenderer has something to probe;
	// Lucent already owns a real surface, so window_main is pointed at it and
	// the JNI-constructed TestSurface is skipped entirely. That keeps the whole
	// boot path free of FindClass and therefore free of any dex dependency.
	if (!InitializeGlobalVulkan())
		return fail("Vulkan is not available on this device");
	g_renderer = std::make_unique<VulkanRenderer>();
	auto* renderer = VulkanRenderer::GetInstance();
	if (renderer == nullptr)
		return fail("Cemu could not create its Vulkan renderer");
	renderer->PublishAndroidWindows(engine->tv_window, engine->pad_window);
	renderer->InitializeSurface({tvWidth, tvHeight}, true);
	// The size above is only a hint on Android; adopt the extent the swapchain
	// really got, or the picture is letterboxed against the wrong height and
	// clipped at the bottom. See sync_window_size_to_swapchain.
	sync_window_size_to_swapchain(true);
	if (engine->pad_window != nullptr)
	{
		renderer->InitializeSurface({padWidth, padHeight}, false);
		sync_window_size_to_swapchain(false);
	}

	// LaunchForegroundTitle detaches Cemu's own title thread and returns, so
	// unlike Eden this adapter owns no emulation thread of its own.
	// Lucent tier pacing (2026-09-02): the emulated vsync is the guest's
	// frame clock, and the present stamps in VulkanRenderer claim an exact
	// 60.000 Hz lattice.  Cemu's default period deliberately overshoots to
	// 59.88 Hz (60 * 1000/1002), which skipped one stamp slot every ~8 s
	// and read as a held frame at the host.  Every start therefore begins
	// on the exact clock the stamps describe, unpaced.
	g_lucent_paced_video_hz.store(0.0);
	LatteTiming_setCustomVsyncFrequency(kLucentDeclaredVideoHz);
	CafeSystem::LaunchForegroundTitle();
	engine->started.store(true);
	return true;
}

static bool adapter_run_frame(lucent_native_engine* engine)
{
	if (engine == nullptr || !engine->started.load())
		return false;
	// Cemu presents from its own title thread. Report liveness so Lucent can
	// fail the session instead of leaving a frozen picture on screen.
	return CafeSystem::IsTitleRunning();
}

static void adapter_set_control(lucent_native_engine* engine, uint32_t controller_index,
                                lucent_native_control control, float value)
{
	if (engine == nullptr || !engine->started.load())
		return;

	if (control == LUCENT_PAD_SCREEN_VIEW)
	{
		// A remote player must never change this device's local display.
		if (controller_index == 0 && std::isfinite(value))
			set_primary_screen(engine, value >= 0.5f);
		return;
	}

	// The Wii U GamePad is the only touchscreen/Home device on real hardware,
	// so these always target the primary controller (index 0's VPAD)
	// regardless of what controller_index they arrive tagged with.
	switch (control)
	{
	case LUCENT_PAD_TOUCH_X:
	case LUCENT_PAD_TOUCH_Y:
	case LUCENT_PAD_TOUCH_PRESSED:
	case LUCENT_PAD_HOME:
		controller_index = 0;
		break;
	default:
		break;
	}

	// describe() advertises exactly kLucentMaxControllers slots; an index at
	// or beyond that is a no-op rather than aliasing onto another slot's
	// state, per the ABI's fail-closed contract for set_control().
	if (controller_index >= kLucentMaxControllers)
		return;
	EmulatedControllerPtr controller = controller_for_index(controller_index);
	if (!controller)
		return;

	uint64 button = 0;
	const bool isPrimary = controller_index == 0;
	const bool isButton = isPrimary ? vpad_button_for(control, button)
	                                : pro_button_for(control, button);
	if (isButton)
	{
		// Lucent sends 1.0/0.0 for digital controls and an analog ramp for
		// triggers on pads that have them; anything past halfway counts as a
		// press so an analog ZL/ZR still actuates.
		controller->setButtonValue(button, value >= 0.5f);
		return;
	}

	// Android reports its Y axis positive-down while the Wii U stick is
	// positive-up, so a positive Lucent value drives the Down magnitude. The
	// negation lives here rather than in the Java layer, which must stay
	// console-neutral for every other system. VPAD and Pro share the same
	// four-magnitude stick shape, so apply_stick_axis only needs the right
	// button-ID table for whichever controller this index resolved to.
	if (isPrimary)
	{
		switch (control)
		{
		case LUCENT_PAD_LSTICK_X:
			apply_stick_axis(controller, VPADController::kButtonId_StickL_Left,
			                 VPADController::kButtonId_StickL_Right, value);
			return;
		case LUCENT_PAD_LSTICK_Y:
			apply_stick_axis(controller, VPADController::kButtonId_StickL_Up,
			                 VPADController::kButtonId_StickL_Down, value);
			return;
		case LUCENT_PAD_RSTICK_X:
			apply_stick_axis(controller, VPADController::kButtonId_StickR_Left,
			                 VPADController::kButtonId_StickR_Right, value);
			return;
		case LUCENT_PAD_RSTICK_Y:
			apply_stick_axis(controller, VPADController::kButtonId_StickR_Up,
			                 VPADController::kButtonId_StickR_Down, value);
			return;

		// The GamePad touchscreen is a real Wii U input that many titles
		// require. Cemu reads it from InputManager's pad mouse state in
		// physical pad-window pixels, so Lucent's normalised 0..1
		// coordinates are scaled here.
		case LUCENT_PAD_TOUCH_X:
			engine->touch_x = value;
			return;
		case LUCENT_PAD_TOUCH_Y:
			engine->touch_y = value;
			return;
		case LUCENT_PAD_TOUCH_PRESSED:
		{
			auto& windowInfo = WindowSystem::GetWindowInfo();
			const bool separatePad = engine->pad_window != nullptr;
			const int padWidth = separatePad ? windowInfo.phys_pad_width.load() : windowInfo.phys_width.load();
			const int padHeight = separatePad ? windowInfo.phys_pad_height.load() : windowInfo.phys_height.load();
			auto& input = InputManager::instance();
			auto& touchInfo = separatePad ? input.m_pad_mouse : input.m_main_mouse;
			std::scoped_lock touchLock(touchInfo.m_mutex);
			touchInfo.position = {static_cast<sint32>(engine->touch_x * static_cast<float>(padWidth)),
			                      static_cast<sint32>(engine->touch_y * static_cast<float>(padHeight))};
			touchInfo.left_down = touchInfo.left_down_toggle = value >= 0.5f;
			return;
		}
		default:
			return;
		}
	}

	switch (control)
	{
	case LUCENT_PAD_LSTICK_X:
		apply_stick_axis(controller, ProController::kButtonId_StickL_Left,
		                 ProController::kButtonId_StickL_Right, value);
		break;
	case LUCENT_PAD_LSTICK_Y:
		apply_stick_axis(controller, ProController::kButtonId_StickL_Up,
		                 ProController::kButtonId_StickL_Down, value);
		break;
	case LUCENT_PAD_RSTICK_X:
		apply_stick_axis(controller, ProController::kButtonId_StickR_Left,
		                 ProController::kButtonId_StickR_Right, value);
		break;
	case LUCENT_PAD_RSTICK_Y:
		apply_stick_axis(controller, ProController::kButtonId_StickR_Up,
		                 ProController::kButtonId_StickR_Down, value);
		break;
	// A Pro Controller has no touchscreen or Home button on real hardware;
	// those controls were already redirected to controller_index 0 above.
	default:
		break;
	}
}

static void adapter_pause(lucent_native_engine* engine)
{
	if (engine == nullptr || !engine->started.load())
		return;
	CafeSystem::PauseTitle();
}

static void adapter_resume(lucent_native_engine* engine)
{
	if (engine == nullptr || !engine->started.load())
		return;
	CafeSystem::ResumeTitle();
}

static bool adapter_flush_save(lucent_native_engine* engine)
{
	if (engine == nullptr || !engine->loaded.load())
		return false;
	// Suspending the guest threads quiesces the emulated filesystem and lets
	// Cemu's pending save writes settle before Lucent reports a clean exit.
	// Cemu exposes no explicit "commit saves now" call; ShutdownTitle in stop()
	// is what finally closes the save handles.
	if (CafeSystem::IsTitleRunning())
		CafeSystem::PauseTitle();
	return true;
}

static size_t adapter_serialize_size(lucent_native_engine* engine)
{
	(void)engine;
	return 0;
}

static size_t adapter_serialize(lucent_native_engine* engine, void* out, size_t capacity)
{
	(void)engine;
	(void)out;
	(void)capacity;
	return 0;
}

static bool adapter_unserialize(lucent_native_engine* engine, const void* data, size_t size)
{
	(void)engine;
	(void)data;
	(void)size;
	return false;
}

static bool adapter_surface_recreated(lucent_native_engine* engine,
                                      const lucent_native_io* io)
{
	if (engine == nullptr || io == nullptr || io->primary_window == nullptr)
		return false;
	auto* renderer = VulkanRenderer::GetInstance();
	if (renderer == nullptr)
		return false;

	// Do not destroy/rebuild live chains on this adapter thread. Latte may be
	// acquiring/presenting on them, and a paused guest cannot acknowledge a
	// StopUsingPadAndWait request. Publish both windows for Latte to reconcile.
	engine->tv_window = static_cast<ANativeWindow*>(io->primary_window);
	engine->pad_window = static_cast<ANativeWindow*>(io->lower_window);
	renderer->PublishAndroidWindows(engine->tv_window, engine->pad_window);
	set_primary_screen(engine, engine->gamepad_on_primary);
	return true;
}

static void adapter_stop(lucent_native_engine* engine)
{
	if (engine == nullptr)
		return;
	if (engine->started.load())
	{
		// Clear Cemu's pause latch BEFORE tearing the title down. ShutdownTitle
		// does NOT reset CafeSystem's sTitlePaused, and flush_save() pauses to
		// quiesce the emulated filesystem, so a session that exits through the
		// normal save-and-quit path leaves the flag set. The next title would
		// then boot with PauseTitle() already latched -- Lucent's pause would
		// silently do nothing and its resume would call ResumeActiveThreads on
		// threads that were never suspended. Resuming here also gives
		// OSSchedulerEnd runnable cores to join instead of suspended ones.
		CafeSystem::ResumeTitle();
		// Drop any control Lucent still has held; the EmulatedController
		// outlives the title inside InputManager.
		release_all_controls();

		// ShutdownTitle joins Latte before g_renderer.reset() below releases
		// either swapchain. Do not wait for a future pad acquire during teardown.
		// The software keyboard state is allocated from the title's guest
		// system area, while Cemu's static pointer survives an in-process title
		// switch. Retire it before ShutdownTitle invalidates that memory; this
		// also prevents an open keyboard from drawing over the next Wii U game.
		swkbd::resetForTitleShutdown();
		// ShutdownTitle stops the guest cores and closes the emulated
		// filesystem, which is what actually commits outstanding saves. It is
		// also the ONLY thing that releases /vol/content, the virtual MLC
		// mounts and the Wii U memory space, so the process cannot prepare
		// another title until it has run.
		CafeSystem::ShutdownTitle();
		// DestroyMemorySpace deliberately leaves the early-mapped CEMU_AREA
		// alive.  Without rewinding its title-owned suffix, each launch leaks an
		// 8 MiB coreinit system heap plus smaller guest structures.  A later
		// launch reaches the 32 MiB ceiling in coreinit::InitSysHeap and raises
		// SIGTRAP from coreinit_allocFromSysArea.  Every guest thread is joined
		// by ShutdownTitle above, so this is the first safe point to reuse it.
		coreinit_resetTitleSysArea();
		engine->started.store(false);
		// A title that was launched has now definitely been through
		// ShutdownTitle -- either this call or, if the guest relaunched itself
		// through OSLauncherThread, its own -- so the mounts are released and
		// load() may prepare again.
		g_title_prepared.store(false);
		g_prepared_content_path.clear();
	}
	{
		std::unique_lock audioLock(g_audioMutex);
		if (g_tvAudio)
			g_tvAudio->Stop();
		g_tvAudio.reset();
	}
	// Release the Vulkan device and both swapchains before returning, as the
	// ABI requires: Lucent detaches the surfaces immediately afterwards.
	g_renderer.reset();

	auto& windowInfo = WindowSystem::GetWindowInfo();
	windowInfo.pad_open = false;
	windowInfo.canvas_main.surface = nullptr;
	windowInfo.canvas_pad.surface = nullptr;
	windowInfo.window_main.surface = nullptr;
	// Index 0's VPAD is process-lifetime (never delete_controller()'d, only
	// reset to neutral above in release_all_controls()); every Pro Controller
	// slot above it was already torn down and delete_controller()'d there.
	g_controllers[0].reset();
	engine->tv_window = nullptr;
	engine->pad_window = nullptr;
	engine->loaded.store(false);
}

static void adapter_destroy(lucent_native_engine* engine)
{
	if (engine == nullptr)
		return;
	adapter_stop(engine);
	delete engine;
}

// --- ABI BOUNDARY -----------------------------------------------------------
//
// Every entry point Lucent can call is registered through one of these, so no
// exception raised anywhere inside Cemu can reach a C frame. See guard_abi.
// The bodies above stay exception-free in intent; these make it structural.

/**
 * Fills the ABI's error buffer when a throw left it empty.
 *
 * adapter_load and adapter_start write their own reason on every failure they
 * return normally, so a buffer that is still empty here means guard_abi caught
 * something instead. Lucent shows this string to the user, and an empty one
 * would surface as a failure with no explanation.
 */
static void describe_caught_failure(char* error, size_t error_size,
                                    const char* message)
{
	if (error != nullptr && error_size > 0 && error[0] == '\0')
		std::snprintf(error, error_size, "%s", message);
}

static bool guarded_load(lucent_native_engine* engine,
                         const lucent_native_load_request* request,
                         char* error, size_t error_size)
{
	const bool loaded = guard_abi("load", false, [&] {
		return adapter_load(engine, request, error, error_size);
	});
	if (!loaded)
		describe_caught_failure(error, error_size,
		                        "Cemu failed while loading this Wii U title");
	return loaded;
}

static bool guarded_start(lucent_native_engine* engine, const lucent_native_io* io,
                          char* error, size_t error_size)
{
	const bool started = guard_abi("start", false, [&] {
		return adapter_start(engine, io, error, error_size);
	});
	if (!started)
		describe_caught_failure(error, error_size,
		                        "Cemu failed while starting this Wii U title");
	return started;
}

static bool guarded_run_frame(lucent_native_engine* engine)
{
	return guard_abi("run_frame", false, [&] { return adapter_run_frame(engine); });
}

static void guarded_set_control(lucent_native_engine* engine, uint32_t controller_index,
                                lucent_native_control control, float value)
{
	guard_abi_void("set_control", [&] { adapter_set_control(engine, controller_index, control, value); });
}

static void guarded_pause(lucent_native_engine* engine)
{
	guard_abi_void("pause", [&] { adapter_pause(engine); });
}

static void guarded_resume(lucent_native_engine* engine)
{
	guard_abi_void("resume", [&] { adapter_resume(engine); });
}

static bool guarded_flush_save(lucent_native_engine* engine)
{
	return guard_abi("flush_save", false, [&] { return adapter_flush_save(engine); });
}

static bool guarded_surface_recreated(lucent_native_engine* engine,
                                      const lucent_native_io* io)
{
	return guard_abi("surface_recreated", false, [&] {
		return adapter_surface_recreated(engine, io);
	});
}

static void guarded_stop(lucent_native_engine* engine)
{
	guard_abi_void("stop", [&] { adapter_stop(engine); });
}

static void guarded_destroy(lucent_native_engine* engine)
{
	guard_abi_void("destroy", [&] { adapter_destroy(engine); });
}

static const lucent_native_adapter kLucentCemuAdapter = {
	/* abi_version      */ LUCENT_NATIVE_ADAPTER_ABI_VERSION,
	/* describe         */ adapter_describe,
	/* create           */ adapter_create,
	/* load             */ guarded_load,
	/* start            */ guarded_start,
	/* run_frame        */ guarded_run_frame,
	/* set_control      */ guarded_set_control,
	/* pause            */ guarded_pause,
	/* resume           */ guarded_resume,
	/* flush_save       */ guarded_flush_save,
	/* serialize_size   */ adapter_serialize_size,
	/* serialize        */ adapter_serialize,
	/* unserialize      */ adapter_unserialize,
	/* surface_recreated*/ guarded_surface_recreated,
	/* stop             */ guarded_stop,
	/* destroy          */ guarded_destroy,
};

extern "C" __attribute__((visibility("default")))
const lucent_native_adapter* lucent_native_adapter_entry(void)
{
	return &kLucentCemuAdapter;
}

// Lucent tier pacing hooks (2026-09-02).  Optional symbols the host resolves
// with dlsym: an adapter without them simply cannot be paced.
//
// The guest's frame clock is the emulated vsync, which LatteTiming derives
// from s_customVsyncFrequency when one is set.  Pacing a tier therefore means
// asking Cemu for that integer vsync frequency; the game then runs at that
// clock exactly as it would on a slower display, and the present stamps in
// VulkanRenderer follow the same period so the host's timing authority reads
// one exact lattice.  Audio is unaffected: AX mixes on its own real-time
// alarm, not on vsync.
extern "C" __attribute__((visibility("default")))
double lucent_native_adapter_declared_video_hz(void)
{
	return static_cast<double>(kLucentDeclaredVideoHz);
}

extern "C" __attribute__((visibility("default")))
bool lucent_native_adapter_set_paced_video_hz(double hz)
{
	if (!(hz > 0.0))
	{
		g_lucent_paced_video_hz.store(0.0);
		LatteTiming_setCustomVsyncFrequency(kLucentDeclaredVideoHz);
		return true;
	}
	// Tiers are exact integers (20, 30, 40, 60); the vsync setter is integral.
	const double rounded = std::round(hz);
	if (std::fabs(hz - rounded) > 1.0e-6 || rounded < 20.0 ||
	    rounded > static_cast<double>(kLucentDeclaredVideoHz))
		return false;
	g_lucent_paced_video_hz.store(rounded);
	LatteTiming_setCustomVsyncFrequency(static_cast<sint32>(rounded));
	return true;
}

// NOTE: no lucent_cemu_average_game_fps counterpart to Eden's measurement hook
// is exported. Cemu computes its frame rate inside LattePerformanceMonitor and
// pushes it to LatteOverlay_updateStats/UpdateWindowTitles without exposing a
// public accessor, and LatteOverlay only records it when the on-screen overlay
// is enabled. Rather than export a number that would silently read zero,
// qualification must time run_frame() from Lucent's side until a small upstream
// patch adds a real accessor.
