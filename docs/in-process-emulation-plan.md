# EmuFusion in-process emulation plan

Status: Phase 1 has structural and AYN Thor activity evidence for 13 runnable
paths but remains release-gated; Phase 2 has fail-closed in-process candidates
for PSP, PS2, Dreamcast/Naomi/Atomiswave, 3DS, and Jaguar, with multiple
platform, compliance, lifecycle, performance, and device gates still open  
Last reviewed: 2026-08-07

Implementation snapshot (2026-08-07): EmuFusion now hosts gameplay inside its
existing single-task `MainActivity`, with an independent libretro API host,
software video/audio path, canonical
digital and analog input, touch fallback, Quick Resume, rolling checkpoint
storage, and strict engine release gates. The Phase 1 registry covers 34
platform definitions. Fourteen license-compatible core artifacts compile for
Android ARM64 from SHA-256-pinned source inputs. The fail-closed Activity
harness covers 17 runnable system paths after adding the previously omitted
DOS path; thirteen paths have the previously recorded native callback/state
and real EmuFusion Android Activity evidence on the AYN Thor;
three firmware/provenance-dependent paths remain explicitly blocked. All remain
experimental and unshipped until the physical-device and release requirements
in this document pass. Phase 2 has begun with a fail-closed hardware-render
host and a reproducible, feature-limited PPSSPP compiler/linker proof. No
RetroArch frontend code, assets, configuration, or application dependency is
used.

This document is the durable product and engineering specification for making
games run inside EmuFusion. It is intentionally independent of conversation
history. If implementation details conflict with this document, this document
wins until it is deliberately amended.

## 1. Product contract

EmuFusion will become an emulator frontend as well as a game-library frontend.
For supported systems, selecting a game opens a Lucent-owned game surface in
the EmuFusion Android package. It must not expose another emulator's library,
window, menus, configuration screen, branding, or launcher.

EmuFusion may implement the MIT-licensed **libretro API** and load compatible
emulator cores. It must not include or reuse the RetroArch frontend, its menus,
configuration system, assets, controller UI, or terminology. Libretro is an
API; RetroArch is only one implementation of a frontend for that API.

The normal user experience has no emulator or graphics settings. The only
user-facing emulation controls are:

1. Resume.
2. Controls: inspect or remap the automatically selected controller profile.
3. Restore earlier point: open the automatic checkpoint history.
4. Exit to EmuFusion: save and return to the exact library location.

There are no on-screen controls when a built-in, USB, or Bluetooth gamepad is
available. On-screen controls appear automatically only on a phone/tablet with
no usable physical controller, or temporarily after the active controller is
disconnected.

## 2. Non-negotiable boundaries

- No RetroArch application, frontend code, menus, configuration files, assets,
  or visible behavior.
- No core-options screen. Curated settings live in tested EmuFusion profiles.
- No emulator APK is silently installed. Android does not generally permit it.
- No firmware, BIOS, encryption keys, copyrighted console OS files, or games
  are bundled. EmuFusion may detect and validate files supplied by the user.
- No game may run faster or slower because the display refresh rate differs
  from the game's native timing.
- No core is shipped until its complete dependency/license graph is approved
  for distribution with EmuFusion's GPL-3.0-only application.
- A buildbot binary proves technical availability, not redistribution approval.
- GPLv2-only and non-commercial cores are license gates, not automatic choices.
- If an engine cannot safely serialize and restore state, EmuFusion must say so
  internally and must not pretend that Quick Resume is protected.

## 3. Runtime architecture

### 3.1 One EmuFusion identity and one display-0 emulation window

The library and every emulation engine must remain in EmuFusion's existing
`MainActivity`. `InWindowGameHost` temporarily covers the library views with a
game surface and restores those same views on exit. A game launch must never
start another Activity on display 0, another Android task, another package, or
an external emulator. Legacy trampoline/game Activities and external launch
bridges may remain in source history for migration reference, but they must not
appear in the unified APK manifest or DEX payload.

The in-window host owns these subsystems:

- `EngineRegistry`: maps normalized system IDs to exactly one approved engine.
- `LibretroHost`: EmuFusion's own minimal implementation of `libretro.h`.
- `NativeEngineAdapter`: common JNI contract for engines that are not suitable
  libretro cores.
- `GameSurface`: Vulkan first, OpenGL ES fallback, software upload fallback.
- `AudioHost`: low-latency AAudio/Oboe output and resampling.
- `InputRouter`: device detection, canonical buttons, per-system mapping, and
  user overrides.
- `StateVault`: Quick Resume, rolling automatic checkpoints, screenshots,
  compression, validation, retention, and restore.
- `FirmwareVault`: hashes and validates user-provided firmware without
  downloading or bundling it.
- `FramePacer`: preserves guest timing and matches presentation to the best
  supported Android display mode.
- `SessionRouter`: returns within the same `MainActivity` to the exact EmuFusion
  system, sort, view, and game.

Release qualification must record, for every tested game, one package
(`com.thorium.preview`), one PID, one recents identity, one display-0 task ID,
one resumed display-0 Activity
(`org.pegasus_frontend.android.MainActivity`, retained only as an internal JNI
compatibility class name), and one display-0 application window from launch
through gameplay and return. Any external emulator observation is an automatic
failure, even if rendering, input, audio, and saving otherwise work.

On a Thor, EmuFusion may keep one private, non-focusable `PreviewActivity` on the
secondary display solely for preview playback or a black gameplay surface. It
must be in the same package and PID, excluded from recents, non-exported,
rejected on display 0, and must never load or host an emulation engine. This
dual-display surface is not a second app or a second emulation window.

### 3.2 Engine contract

Every libretro core or native adapter must expose the equivalent of:

```text
probe(content, firmware) -> compatibility result
load(content, firmware, profile)
start(surface, audio, input)
pause()
resume()
flushPersistentSave()
canSerialize() -> boolean
serialize() -> versioned bytes
unserialize(versioned bytes)
captureFrame() -> image
stop()
capabilities() -> screens, touch, motion, microphone, state support
```

Native adapters must behave exactly like the libretro host at the EmuFusion UI
boundary. An engine is an implementation detail and never a navigation target.

### 3.3 Core supply chain

Create a checked-in `engines/registry.json` containing, for every engine:

- EmuFusion engine ID and systems.
- Upstream repository and homepage.
- Exact source commit/tag.
- Full SPDX license expression and dependency-license report.
- Source archive SHA-256.
- Android ABIs and minimum API level.
- Build recipe and reproducibility status.
- Firmware requirements and accepted hashes.
- Save-state capability and compatibility version.
- Renderer and controller capabilities.
- Current state: `approved`, `license-blocked`, `experimental`, or `external`.

Approved engines are built from source in EmuFusion CI. EmuFusion must not download
unversioned executable cores from arbitrary mirrors at runtime. Engine updates
ship as signed EmuFusion APK updates so one tested engine/profile set stays intact.

## 4. Unified saving behavior

### 4.1 Quick Resume

Each game has exactly one user-invisible Quick Resume state:

- Save it when the user exits through EmuFusion.
- Save it when the Thor Stop button is held for one second.
- Save it before an engine is stopped, updated, or evicted for memory pressure.
- Attempt an asynchronous save when Android backgrounds the game activity.
- Flush SRAM, memory cards, and native in-game saves before serializing state.
- On next launch, restore Quick Resume automatically after validating the ROM
  hash, engine ID, engine state version, firmware fingerprint, and checksum.
- If validation fails, retain the state for recovery but boot the game normally.

### 4.2 Automatic history

- Create a checkpoint every 10 minutes of active emulated play time.
- Do not count pause time, menus, background time, or suspended time.
- Create an additional checkpoint before overwriting Quick Resume and before
  applying an engine update.
- Store a screenshot, game-time counter, wall-clock timestamp, engine version,
  ROM hash, firmware hash, and CRC with every checkpoint.
- Write to a temporary file, fsync, verify, then atomically rename.
- Compress state data in a background worker.
- Retain at least the newest 12 checkpoints per game.
- After that, thin older states to hourly anchors, with a per-game ceiling of
  72 checkpoints or 512 MiB, whichever is reached first.
- Never delete the newest valid Quick Resume state while pruning history.

`Restore earlier point` is deliberately one level inside EmuFusion's pause menu.
It shows a horizontal timeline of screenshots and timestamps. Restoring an old
checkpoint first preserves the current state as a new recovery checkpoint.

### 4.3 Required state qualification

For a libretro engine, `retro_serialize_size()` must be non-zero and a full
serialize/unserialize round trip must pass automated tests. Serialization is an
optional libretro feature, so merely being a libretro core is insufficient.

Qualification per system requires:

- 100 consecutive save/restore cycles without corruption.
- Save while audio, video, controller, and storage are active.
- Save from at least 20 legally distributable test/homebrew titles where the
  system has enough such titles.
- Restore after process death and device reboot.
- Restore on every supported Android ABI and renderer.
- Verify normal SRAM/memory-card data separately from state snapshots.
- Verify or deliberately reject states after an engine update.

## 5. Input and controller policy

### 5.1 Device detection

`InputRouter` builds a canonical controller from Android `InputDevice` sources,
key codes, axes, vendor/product IDs, descriptor, device name, and whether the
device is internal or external. It must recognize capability, not just names.

The checked-in device catalog must include profiles for:

- AYN Thor and Odin families.
- Retroid Pocket/Flip families.
- Logitech G Cloud and Razer Edge.
- AYANEO Pocket Android devices.
- Android-based Anbernic devices.
- Backbone, Razer Kishi, GameSir, and 8BitDo mobile controllers.
- Xbox One/Series, DualShock 4, DualSense, Switch Pro, and common USB HID pads.
- A generic standards-compliant Android gamepad fallback.

Unknown devices run a one-time capability probe. The resulting profile is
stored by descriptor plus vendor/product ID, never by display name alone.

### 5.2 Canonical controls

EmuFusion normalizes physical inputs to:

```text
D-pad; South/East/West/North; L1/R1; L2/R2; L3/R3;
Start; Select; Guide/Menu; left/right sticks; touch; motion
```

System profiles translate those controls to authentic console controls. Core
defaults are never trusted blindly. Examples:

- NES: B=South, A=East, Start/Select preserved.
- SNES: B=South, A=East, Y=West, X=North, shoulders preserved.
- PlayStation: Cross=South, Circle=East, Square=West, Triangle=North.
- Genesis six-button: A=West, B=South, C=East; X/Y/Z use the upper row selected
  by the tested device profile.
- N64: A/B use the two primary face positions, C buttons use the right stick
  with face-button fallbacks, Z uses L2, and L/R use L1/R1.
- GameCube: use a device-specific geometric mapping rather than assuming Xbox
  labels match the GameCube face cluster.
- DS/3DS/Wii U: map touch to the lower display when available and to a toggleable
  touch surface on single-screen phones.

The only controller setting is `Remap Controls`. It starts from the complete
working profile, allows per-system or per-game overrides, supports reset, and
never exposes core input-device terminology.

### 5.3 On-screen controls

- Hidden when any complete physical gamepad is active.
- Hidden by default on known Android gaming handhelds.
- Shown on a phone/tablet only when no complete gamepad exists.
- Shown temporarily if the active controller disconnects during play.
- Automatically removed as soon as a physical controller reconnects.

## 6. Video, speed, and display policy

- Preserve the game's original logic and audio timing.
- Do not "unlock" a 30/60 FPS game by accelerating emulation.
- For 2D systems, use the highest integer scale that fits, correct pixel aspect,
  and pillarbox/letterbox rather than stretch.
- For 3D systems, select a tested internal-resolution profile based on device
  GPU class, renderer, thermal state, and sustained benchmark—not a settings UI.
- Output the final surface at the physical display resolution.
- Request the closest compatible display refresh rate with Android's frame-rate
  API and use Swappy/presentation timestamps for stable pacing.
- High-FPS patches and frame interpolation are separate future capabilities;
  they are never silently enabled and are not prerequisites for this roadmap.
- On a Thor, DS/3DS/Wii U layouts may use both displays; single-screen systems
  render gameplay on the top display and stop the lower preview when play starts.

## 7. Phase 1 — EmuFusion libretro host and low-complexity cores

Goal: prove the internal runtime and ship the largest reliable group with one
UI, one controller system, and qualified automatic state history.

The official libretro Android ARM64 build catalog currently publishes cores for
every entry below. EmuFusion will build approved cores from upstream source rather
than importing RetroArch or copying its configuration.

### 7.1 Phase 1A: license-compatible first shipment

| Systems | Preferred core | Upstream/status | State target |
| --- | --- | --- | --- |
| NES/Famicom | Mesen | GPLv3; Android ARM64 core | Deterministic |
| SNES/Super Famicom | Mesen-S, then bsnes if qualification wins | GPLv3 candidate | Required |
| Game Boy/Color | SameBoy | MIT | Required |
| Game Boy Advance | mGBA | MPL-2.0 | Deterministic |
| SG-1000/Master System/Game Gear | Gearsystem | GPLv3 | Deterministic |
| ColecoVision | Gearcoleco | GPLv3 | Deterministic |
| Intellivision | FreeIntv | GPLv2-or-later | Required |
| PlayStation | SwanStation | GPLv3 | Basic, must qualify |
| Nintendo DS/DSi | melonDS DS | GPLv3-or-later | Serialized |
| ZX Spectrum | Fuse | GPLv3 | Must qualify |
| Arcade/Neo Geo/Neo Geo CD | current MAME | GPLv2-or-later | Per-driver qualification |

### 7.2 Phase 1B: technically easy, license-gated

These cores already exist for Android ARM64 and mostly expose serialization,
but EmuFusion must not bundle them until a GPL-3.0-only compatibility decision,
replacement, or explicit permission is documented.

| Systems | Candidate core | Gate |
| --- | --- | --- |
| Atari 2600 | Stella 2023 | Core metadata says GPLv2 |
| Atari 5200/Atari 8-bit | Atari800 | GPLv2-only review |
| Atari 7800 | ProSystem | GPLv2-only review |
| Amstrad CPC | Caprice32 | GPLv2-only review |
| Atari ST | Hatari | GPLv2-only review |
| PC Engine/CD | Beetle PCE Fast | GPLv2-only review |
| Genesis/Sega CD/32X | PicoDrive | legacy MAME-license review |
| Neo Geo Pocket/Color | Beetle NeoPop | GPLv2-only review |
| WonderSwan/Color | Beetle Cygne | GPLv2-only review |
| Virtual Boy | Beetle VB | GPLv2-only review |
| Nintendo 64 | Mupen64Plus-Next | GPLv2-only plus Vulkan/GLES qualification |
| Commodore 64 | VICE x64sc | GPLv2-only review |
| MSX | blueMSX/fMSX | choose a redistributable source build |
| Magnavox Odyssey² | O2EM | Artistic-license compatibility review |
| DOS/Windows 9x | DOSBox Pure | upstream says GPLv2-or-later; verify every dependency |

The checked-in Phase 1 registry currently maps **34 normalized systems**.
PC Engine CD and monochrome WonderSwan remain deliberately unadvertised until
their firmware/fixture contracts are enforced. Systems without an approved
in-process engine remain unavailable; there is no external fallback or
partially working swap.

### 7.3 Phase 1 completion gate

- One Lucent-owned game activity; no external emulator window.
- No RetroArch package or frontend source in the dependency graph.
- Automatic controller profiles and hidden on-screen controls on handhelds.
- Quick Resume plus 10-minute history working after process death.
- No visible core settings or core names.
- Direct launch and return preserve the exact EmuFusion navigation state.
- Cold launch, input latency, audio underrun, frame pacing, and state tests pass.

## 8. Phase 2 — heavy libretro cores and native adapters

Goal: preserve the identical EmuFusion UX while integrating systems whose cores
need hardware rendering, multi-screen behavior, computer peripherals, large
states, or deeper native adaptation.

The fail-closed Phase 2 source and qualification authority is
[`engines/phase2-registry.json`](../engines/phase2-registry.json), with the
human audit in
[`engines/qa/phase2-matrix.md`](../engines/qa/phase2-matrix.md). PPSSPP is the
first runnable **candidate**, not an approved or shipped engine; every Phase 2
runtime, renderer, state, performance, and device gate remains closed until its
recorded qualification work passes.

Play!'s official Android libretro profile and Virtual Jaguar now also have
exact-pin, byte-identical ARM64 compiler/linker proofs. These results advance
only their Android build gates; legal-content, renderer, state, performance,
and device gates remain closed. Play!'s closure and proof details are recorded
in [`docs/phase2-play.md`](phase2-play.md).

| Systems | Preferred route | Why Phase 2 |
| --- | --- | --- |
| Apple II | AppleWin core | Keyboard, disks, and GPLv2-only review |
| Amiga/Amiga CD32 | PUAE core | Keyboard/mouse/disks, firmware, GPLv2-only review |
| Sega Saturn | benchmark Ymir/YabaSanshiro/Beetle Saturn | Accuracy/performance and license selection |
| Dreamcast/Naomi/Atomiswave | Flycast core or native adapter | Vulkan, arcade peripherals, GPL version review |
| PlayStation 2 | Play! core/native adapter | ARM64 JIT, compatibility profiles, large states |
| GameCube/Wii | Dolphin core/native adapter | Vulkan, Wii input, NAND, motion, large states |
| PSP | PPSSPP core/native adapter | Vulkan, assets, large state and version migration |
| Nintendo 3DS | Azahar ARM64 core/native adapter | Dual screens, touch, firmware, shader caches |
| ScummVM | native/libretro adapter | Core reports no generic serialization; use engine saves |
| Atari Jaguar | Virtual Jaguar core or a better compatible engine | Existing core is available but compatibility must improve before it can replace standalone options |

Although Android ARM64 builds exist today for Play!, Dolphin, PPSSPP, Flycast,
and Azahar, Phase 2 does not assume their libretro ports are automatically the
best integration. Each system gets a benchmark between the libretro core and a
thin adapter around upstream's native engine. The user-facing contract remains
identical either way.

PPSSPP is the first Phase 2 heavy-engine build candidate. EmuFusion pins official
PPSSPP `v1.20.4` at peeled commit
`fa50bb1976065c4f8b1b47af227d367fe9771555` and has an off-device Android ARM64
compiler/linker proof using PPSSPP's own libretro adapter. The exact hardened
APK now passes EmuFusion's one-window Thor checkpoint in the existing
`MainActivity`: visible output, live audio, physical A input, held-Stop return,
Quick Resume commit, process death, live restore, one visible recents identity,
and a black lower display all have machine-readable evidence. This does not
close the aggregate release gate: the first proof deliberately excludes
FFmpeg, and its notice/asset audit, legal fixture/toolchain, 100-cycle matrix,
Vulkan lifecycle, sustained performance, migration, and broader-device gates
remain open. See `docs/phase2-ppsspp.md`.

Phase 2 adds **12 current platforms** when Apple II, Amiga/CD32, Saturn,
Dreamcast, PS2, GameCube, Wii, PSP, 3DS, Jaguar validation, and ScummVM are
counted. Jaguar may move forward into Phase 1 if its compatibility gate passes.

## 9. Phase 3 — experimental modern systems

Goal: link every credible upstream project and bring engines in-process only
when Android, licensing, performance, firmware, and lifecycle requirements are
genuinely satisfied. There is no external-emulator fallback in unified EmuFusion.

The machine-readable authority is
[`engines/phase3-registry.json`](../engines/phase3-registry.json). It pins the
currently observed upstream commit for every Phase 3 owner, enforces exactly
one in-Lucent route per system, and keeps every release gate false. These are
tracking identities, not approved source archives: archive hashes, dependency
closures, Android artifacts, legal fixtures, runtime adapters, and device
evidence must be added before the corresponding source/runtime gates may open.

| Systems | Project/route | Planned treatment |
| --- | --- | --- |
| 3DO | Opera or another compatible engine | Opera core is LGPL/non-commercial; do not bundle without a replacement or permission |
| PlayStation Vita | Vita3K Android | Native adapter; GPLv2 compatibility and state support are gates |
| Wii U | Cemu | Native Android port/adapter; MPL-2.0; no assumption that desktop code is production-ready on Android |
| Nintendo Switch | Eden | Native adapter; GPLv3-or-later; user supplies firmware/keys; Quick Resume only if a reliable state API exists |
| PlayStation 3 | **aPS3e** | Add official project link now; experimental Android RPCS3-derived engine; GPLv2 compatibility, firmware, performance, and state API are gates |
| Original Xbox | xemu | Track upstream; ARM64 Android/Vulkan port, BIOS/HDD setup, and license architecture required |
| Xbox 360 | Xenia | Track upstream Android work; ARM64 JIT/Vulkan and production compatibility required |
| Windows / PC | DOSBox Pure now; Wine/Box64 container adapter next | DOS and user-supplied Windows 3.x/9x disk images run in-process now. Modern Win32/Win64 remains a managed Phase 3 container engine, not a conventional ROM core. |

aPS3e is real and must be represented in the source registry:

- Repository: <https://github.com/aenu1/aps3e>
- Project page: <https://aenu.cc/aps3e/>
- Current description: experimental native Android PS3 emulator based on RPCS3.
- License claim: GPLv2, requiring architectural/legal resolution with EmuFusion's
  GPL-3.0-only combined application.
- Firmware: user-provided official PS3 firmware; never bundled by EmuFusion.

Phase 3 does not mean "impossible." It means EmuFusion will not promise transparent
in-process play, automatic history, or broad compatibility before the relevant
engine exposes and passes those capabilities. Until then, the system remains
unavailable in EmuFusion; an official project link may be shown only as provenance.

## 10. Catalog expansion beyond the current 56 systems

The engine registry and visual catalog must also add known Android ARM64 core
targets absent from `GameSystems.java`, including at minimum:

- Atari Lynx — GearLynx/Handy.
- Vectrex — VecX.
- NEC PC-FX — Beetle PC-FX.
- Sega Pico — PicoDrive.
- Pokémon Mini — PokeMini.
- Game & Watch — GW.
- Mega Duck/Cougar Boy — SameDuck.
- Philips CD-i — Same CD-i, license/firmware qualification required.
- Sharp X68000 — PX68k.
- NEC PC-98 — Neko Project II Kai.
- NEC PC-88 — QUASI88.
- Classic Macintosh — Mini vMac.
- Commodore VIC-20, Plus/4, PET, and C128 — corresponding VICE cores.
- MSX2 — blueMSX/openMSX-compatible route.
- SuperGrafx — Beetle SuperGrafx.
- Sega Naomi/Naomi 2/Atomiswave — Flycast.
- Nintendo DSi — melonDS DS when firmware and NAND are present.
- DOS/Windows 9x — DOSBox Pure; later Windows through managed Wine/Box64.

Each addition requires a system definition, extensions/identification rules,
logo and company art, controller layout, metadata namespaces, firmware rules,
engine mapping, save qualification, and test set. A core appearing on the
buildbot must not make a system visible unless all those pieces exist.

## 11. Upstream engine source registry

EmuFusion keeps official-source links for provenance, credit, license review, and
corresponding-source access. These links are not executable routes and do not
authorize EmuFusion to open or install standalone emulator applications. The
initial registry includes:

- MAME/MAME4droid: <https://github.com/mamedev/mame>,
  <https://github.com/seleuco/MAME4droid-2024>
- Robert Broglia `.emu` applications: <https://www.explusalpha.com/contents/emuex>
- Mupen64Plus/M64Plus AE: <https://github.com/mupen64plus/mupen64plus-core>,
  <https://github.com/mupen64plus-ae/mupen64plus-ae>
- DuckStation: <https://github.com/stenzek/duckstation>
- Play!: <https://github.com/jpd002/play->
- Flycast: <https://github.com/flyinghead/flycast>
- melonDS Android: <https://github.com/rafaelvcaetano/melonDS-android>
- Dolphin: <https://github.com/dolphin-emu/dolphin>
- Azahar: <https://github.com/azahar-emu/azahar>
- PPSSPP: <https://github.com/hrydgard/ppsspp>
- Vita3K: <https://github.com/Vita3K/Vita3K>
- Cemu: <https://github.com/cemu-project/Cemu>
- Eden: <https://git.eden-emu.dev/eden-emu/eden>
- aPS3e: <https://github.com/aenu1/aps3e>
- RPCS3: <https://github.com/RPCS3/rpcs3>
- xemu: <https://github.com/xemu-project/xemu>
- Xenia: <https://github.com/xenia-project/xenia>
- Winlator: <https://github.com/brunodev85/winlator>
- ScummVM: <https://github.com/scummvm/scummvm>
- DOSBox Pure: <https://github.com/schellingb/dosbox-pure>
- Official libretro API/core metadata: <https://github.com/libretro/libretro-super>
- Official Android ARM64 core builds:
  <https://buildbot.libretro.com/nightly/android/latest/arm64-v8a/>

The application shows project credit and source/license information under
About > Emulation Engines. It never shows emulator implementation names in the
normal library or gameplay flow.

### 11.1 Core source registry seeds

The first `engines/registry.json` audit starts from these source projects. This
list records candidates, not blanket approval to redistribute them:

- Mesen: <https://github.com/libretro/Mesen>
- Mesen-S: <https://github.com/libretro/Mesen-S>
- SameBoy: <https://github.com/LIJI32/SameBoy>
- mGBA: <https://github.com/mgba-emu/mgba>
- Gearsystem: <https://github.com/drhelius/Gearsystem>
- Gearcoleco: <https://github.com/drhelius/Gearcoleco>
- FreeIntv: <https://github.com/libretro/FreeIntv>
- SwanStation: <https://github.com/libretro/swanstation>
- melonDS DS core: <https://github.com/JesseTG/melonds-ds>
- Fuse core: <https://github.com/libretro/fuse-libretro>
- Virtual Jaguar core: <https://github.com/libretro/virtualjaguar-libretro>
- Stella: <https://github.com/stella-emu/stella>
- Atari800: <https://github.com/atari800/atari800>
- ProSystem core: <https://github.com/libretro/prosystem-libretro>
- Caprice32 core: <https://github.com/libretro/libretro-cap32>
- Hatari core: <https://github.com/libretro/hatari>
- Beetle PCE Fast: <https://github.com/libretro/beetle-pce-fast-libretro>
- PicoDrive: <https://github.com/libretro/picodrive>
- Beetle NeoPop: <https://github.com/libretro/beetle-ngp-libretro>
- Beetle WonderSwan: <https://github.com/libretro/beetle-wswan-libretro>
- Beetle Virtual Boy: <https://github.com/libretro/beetle-vb-libretro>
- Mupen64Plus-Next: <https://github.com/libretro/mupen64plus-libretro-nx>
- VICE cores: <https://github.com/libretro/vice-libretro>
- blueMSX core: <https://github.com/libretro/blueMSX-libretro>
- O2EM core: <https://github.com/libretro/libretro-o2em>
- DOSBox Pure: <https://github.com/schellingb/dosbox-pure>
- PUAE core: <https://github.com/libretro/libretro-uae>
- AppleWin core: <https://github.com/audetto/AppleWin>
- MAME: <https://github.com/mamedev/mame>
- Flycast: <https://github.com/flyinghead/flycast>
- Play!: <https://github.com/jpd002/play->
- Dolphin: <https://github.com/dolphin-emu/dolphin>
- PPSSPP: <https://github.com/hrydgard/ppsspp>
- Azahar: <https://github.com/azahar-emu/azahar>
- ScummVM: <https://github.com/scummvm/scummvm>

## 12. Delivery milestones

1. **Legal/source audit:** produce the registry, SBOM, license matrix, source
   pins, and replacement decisions. No core integration precedes this gate.
2. **Host proof:** Mesen plus mGBA running through `InWindowGameHost` in the
   existing `MainActivity`, with audio, controller input, return routing, Quick
   Resume, and checkpoint history.
3. **Phase 1A shipment:** all green Phase 1 cores and the complete controller
   profile system.
4. **Phase 1B resolution:** replace, obtain permission for, or legally isolate
   each yellow core; never silently waive the gate.
5. **Phase 2 adapters:** hardware-rendered and multi-screen systems, one at a
   time, with the same qualification suite.
6. **Phase 3 research:** aPS3e, Eden, Cemu, Vita3K, xemu, Xenia, and Windows
   engines remain feature-flagged until they meet production gates.
7. **Exact unified release gate:** build one signed artifact and rerun every
   qualified Phase 1 and Phase 2 system against that exact SHA, rejecting any
   second package, task, Activity, or display-0 application window.

## 13. Definition of done for one system

A system is not "integrated" until all of the following are true:

- A game launches inside EmuFusion's existing MainActivity without another
  package, task, Activity, or display-0 application window.
- Exiting returns to the same collection, filter, sort, view, and selection.
- A complete physical controller works with no on-screen controls.
- Phone-only mode supplies usable on-screen controls.
- Remapping works and survives restart.
- Quick Resume survives process death and reboot.
- Ten-minute checkpoint history passes corruption and pruning tests.
- Normal in-game saves are flushed independently of states.
- Resolution, aspect ratio, refresh request, audio, and frame pacing pass.
- Required firmware is detected with a clear, legal user-supply flow.
- No core settings, emulator window, or emulator branding appears in normal UX.
- License, source, notices, SBOM, reproducible build, and upstream credit ship.
- At least the system's high-value compatibility test set passes on the Thor
  and two representative single-screen Android device classes.

Only after this checklist passes may `EngineRegistry` expose and select the
in-process engine. A failed or unavailable engine remains fail-closed.

## 14. Authoritative technical references

- Libretro API/core relationship:
  <https://docs.libretro.com/development/cores/developing-cores/>
- Independent libretro frontends:
  <https://docs.libretro.com/development/frontends/>
- Libretro core licenses and non-commercial warnings:
  <https://docs.libretro.com/development/licenses/>
- Current Android ARM64 core inventory:
  <https://buildbot.libretro.com/nightly/android/latest/arm64-v8a/>
- Android frame pacing:
  <https://developer.android.com/games/sdk/frame-pacing>
- Android frame-rate selection:
  <https://developer.android.com/games/optimize/display-refresh-rate-change>
- Android package-install user-action boundary:
  <https://developer.android.com/reference/android/content/pm/PackageInstaller>
- GNU license compatibility and plugin guidance:
  <https://www.gnu.org/licenses/gpl-faq.html>
