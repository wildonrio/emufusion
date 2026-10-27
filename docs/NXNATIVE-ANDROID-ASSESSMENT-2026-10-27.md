# nxnative on Android: assessment (2026-10-27)

The owner asked whether nxnative ([github.com/seedds/nxnative](https://github.com/seedds/nxnative), MIT,
read at commit `4397e2e`) would beat Eden because it runs Switch games natively instead of emulating
them, and how to adapt it to Android.

**Method.** nxnative ships complete source and no binaries, so it was read as source; REA is for
compiled targets. The clone sits in a scratch folder and nothing from it was executed. Three
independent read-only passes covered the CPU/OS host, graphics, and the per-game pipeline with
integration. GitHub metadata came from read-only API calls. Unless marked otherwise, statements
below are what the code shows.

## What nxnative is

nxnative turns one game's NSPs plus the user's `prod.keys` into an app for one Apple device. It has
three layers:

- **NSO rewriter** (`dm/tools/patch_nso.py`, Python, offline on a Mac). It rewrites only the
  instructions Apple's kernel forbids or changes:
  - `svc`, `cntpct` and `cntvct` become a call into the host;
  - `tpidr_el0` and `tpidrro_el0` become per-thread slots;
  - x18 becomes a per-thread slot;
  - a misaligned `sub sp` is rounded to 16 bytes;
  - spin loops yield;
  - per-build cuts are applied.

  The output is linked into the signed app.
- **Horizon host** (`dm/host`, C). It replaces Horizon's SVCs and the SDK's services:
  - guest address = host address, inside one reserved region;
  - each guest thread is a pthread;
  - 771 SDK functions are replaced directly, with no TLS swap per call.
- **Graphics.** It implements the games' own APIs on Metal:
  - NVN (`hle_nvn.c` plus `nvn_mtl.m`, about 1 MB);
  - the games' Vulkan (`dm/gfx/vk`) and NVIDIA OpenGL (`dm/gfx/gl`).

  Maxwell shaders go through Ryujinx's translator to SPIR-V, then SPIRV-Cross to MSL, compiled
  per game on the Mac.

Every game needs a profile in `dm/games/<titleID>` (88 rows today), and each profile is tied to
the NSO builds it was brought up on:

- 25 profiles carry hand patches, 643 of the ~720 rows in ASTRAL CHAIN alone;
- 5 carry 60 fps frame-step stubs;
- behaviour keys are found during bring-up.

A game without a profile gets a provisional package "that may not boot". The first build takes
30-60 minutes on a Mac.

## Is it "native instead of emulation" compared with our Eden?

The CPU part of the idea is already in our build. Eden on Android executes game code natively
(`cpu_backend: Nce`, the default with `HAS_NCE`) for every game with a 39-bit address space. Our
logs show one exception: New Super Mario Bros. U Deluxe, which logs "Program does not utilize
39-bit address space, unable to natively execute code" and falls back to the Dynarmic JIT. The
cause is Eden's own layout:

- its NCE arena sits between 2^36 and 2^39 (`host_memory.cpp:405-433`);
- only the 39-bit layout is moved onto it (`k_page_table_base.cpp:240-266`);
- hence the gate in `deconstructed_rom_directory.cpp:185-189` and `settings.cpp:208-216`.

nxnative's real advantages are:

1. **GPU.** Eden emulates the Maxwell GPU: command lists, engines, GPU memory manager, texture
   cache heuristics, shader recompilation at runtime. nxnative never sees GPU commands. It
   replaces the NVN library calls, so a draw becomes a native draw. This is where most of the
   speed comes from.
2. **No OS emulation per call.** SDK functions run as host code. Eden's NCE still traps every SVC
   into an emulated kernel and swaps `TPIDR_EL0` on each transition (`arm_nce.s:17-46`).
3. **Per-game tuning.** Patches, 60 fps stubs, prewarmed shader lists.

The price is that it is per game and per version, and the graphics layer is Metal only.

## State of Android work outside this repository

- **nxnative:** `CONTRIBUTING.md` supports Apple devices only. There is one Android PR,
  [seedds/nxnative#447](https://github.com/seedds/nxnative/pull/447). It is unreviewed and was
  opened 2026-10-27:
  - +9.6k lines: a Vulkan replay of ~2.9k lines, AAudio, MediaCodec, a Java launcher, and an APK
    builder that pushes game files over adb;
  - only Super Mario Bros. Wonder was tested, at about 30 fps on a Snapdragon 695 (render scale
    0.8).
- **Upstream d2r-mobile** (MIT, the project nxnative copied its generic parts from) has
  `dm/android` and a Vulkan engine imported from a private repository. Its status page reported
  9-10 fps on an Adreno 830 on 2026-10-16.
- Nobody has an Android runtime that matches the Metal one.

## Our library

| Game | nxnative profile | Notes |
| --- | --- | --- |
| Metroid Dread | 010093801237C000, 2.1.0 | Plays on iPhone; 60 fps gameplay, 30 fps cutscenes; no hand patches |
| Super Mario Odyssey | 0100000000010000, 1.4.1 | Plays on iPhone; one SDK cut; untranslated geometry shaders; first minute silent |
| Link's Awakening | 01006BB00C6F0000, 1.1.0 | Plays on iPhone; one PhysX cut; 5 manual shader facts |
| NSMBU Deluxe, Sonic Superstars, Mega Man 11 | none | Provisional only |

Profiles match exact builds. Our dumps must be those versions, or no per-build fixes apply.

## What an Android port needs (estimates are inference)

1. **CPU/OS host as a JNI library.** About 2-4 engineer-months to reach `nnMain`.
   - **Rewriter.** Its logic carries over. The TLS anchor needs a Linux replacement: on Linux,
     `tpidrro_el0` holds 0 or kernel data. Keeping x18 removal protects Android's shadow call
     stack.
   - **Load path.** Rewritten code goes into anonymous RW→RX memory, the Mac host's path
     (`loader.c:535-564`). Our targetSdk 30 forbids executing files from the data directory, so
     the iOS embedding path does not apply.
   - **Host code.** Mostly POSIX. Mach thread ports, QoS, Darwin `ucontext`, `vm_remap` and
     `mach_absolute_time` need Linux equivalents. Signals must chain with ART.
   - **Rewrite cost.** A Mac rewrite of a large title takes 6-13 minutes, so results must be
     cached.
2. **NVN on Vulkan.** About 6-12 engineer-months to parity on a few titles.
   - **What carries over.** `hle_nvn.c` is ~95% API-neutral. About a quarter of `nvn_mtl.m`'s
     lines call Metal; the rest is replay logic to port function by function.
   - **Hardest item: guest memory shared with the GPU.** Metal's zero-copy shared buffers have no
     common Vulkan equivalent. `VK_EXT_external_memory_host` support on Adreno is unknown;
     otherwise the guest's memory pools must be allocated from Vulkan and mapped into the game.
   - **Shaders.** The Ryujinx translator already emits Vulkan SPIR-V with all resources in set 0,
     so the whole MSL stage drops out. Capability answers must change from Metal's to Adreno's, and
     the stage-interface fixes (`vs_pad`, `vs_init`, `precise`) must be redone in SPIR-V.
     Translating on the device at runtime is possible, either with Eden's C++ recompiler or by
     re-running the translator.
   - **Known Thor driver bugs** (512.676) that Eden already works around: push descriptors
     (`vulkan_device.cpp:505-513`) and custom border colours (`:517-540`).
   - **Pipeline compile stutter** is the main play-quality risk.
   - **Games that use Vulkan on the Switch** would pass through about 80-90% directly, because the
     Android calling convention matches the Switch's.
3. **Platform pieces.**
   - Audio output: AudioUnit → AAudio.
   - H.264/AAC movies: VideoToolbox → MediaCodec (Odyssey uses H.264).
   - Controllers, rumble and motion: our input layer.
   - Front-end hooks (`dm/host/front.h`).
   - The bundled Arial Unicode font is proprietary and must be replaced.
4. **Pipeline.**
   - Extraction (LibHac/.NET), rewriting (Python, capstone), shader translation (.NET) and the
     `game.tsv` profiles need a build host, or ports that run on the device.
   - Keys are used only at extraction.
   - The output holds decrypted game data, so each user must build their own from their own dumps
     and never redistribute it.

Licences allow shipping derived code: MIT (nxnative, Ryujinx shader subset), BSD-3 (libvpx,
FLIP), zlib (deko3d port), Apache-2.0/MIT (Vulkan headers, SPIRV-Cross). Host behaviour modelled on
yuzu and Atmosphère (GPL) is reimplemented, not copied, and our APK already ships GPL-3 Eden.

## Recommendation

nxnative is not a drop-in replacement for Eden. At best it is a faster path for the few games
with a profile, at their exact versions, on top of Eden, which keeps every other game. In order:

1. **Native CPU for 36-bit games inside Eden** (days, and the only change to our own Switch
   engine).
   - Load 36-bit titles with the 39-bit layout under NCE (`deconstructed_rom_directory.cpp:185-189`,
     `k_process.cpp:1215-1236`). This is what nxnative does implicitly: games ask `GetInfo` for
     their regions.
   - Gate it per title behind a QA switch, and A/B NSMBU Deluxe on the Thor.
   - Risk: a game that keeps pointers in 36 bits. Stock Eden does not do this, so it needs the
     owner's go-ahead (the standing rule is "Switch like stock Eden").
2. **Feasibility spike on the Thor** (1-2 weeks).
   - Build PR #447's Android path, as a review copy in its own folder, for Metroid Dread 2.1.0 from
     the owner's own dump and keys.
   - Measure frame time, frame pacing and stutter against Eden.
   - The spike needs the NSP and `prod.keys` on the Mac, which moves private data, and it runs a
     third party's build scripts. Both need an explicit go-ahead.
3. **Only if the spike beats Eden clearly:**
   - a native Switch engine for profiled games, sharing EmuFusion's frame generation, input and
     audio;
   - NVN on Vulkan built from nxnative's replay logic and Eden's Adreno workarounds;
   - every other game stays on Eden.
