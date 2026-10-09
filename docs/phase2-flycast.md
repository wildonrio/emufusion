# Phase 2 Flycast integration checkpoint

Date: 2026-08-07

October 4 normal integration: staged core is now
`5a25b2987d95711a7e2462438babf6b2b494917be2988a1a18fd55eab7090464`.
The ordinary source recipe's 16 KiB shared/module link flags and path maps
reproduce the exact runtime-tested artifact in a fresh separate build root.
The registry proof was updated and the previous `938709bb` artifact backed up.
The complete normal APK `9672d342...c974` contains this core. This is build
integration, not additional Dreamcast gameplay/audio acceptance. Historical
runtime evidence and its limitations remain in the portability matrix.

October 2 portability candidate: `938709bb4f39c788a3938d4906806ff0358b98b0abd4eafbdb9f766f36f7c5f2`
adds `engines/patches/flycast-android-shared-memory.patch`. The API-24 libretro
binary has no libandroid dependency, leaving its weak ASharedMemory_create
reference null on the Android 16 simulator. Explicit public-API lookup succeeds
in a native probe, including coherent shared mappings. Seven allocator scenarios
pass executable ASan/UBSan checks. One isolated clean core build completed.
Simulator APK `cadc70d6b2acebe9816a2e97a0bc0f69d5ce84a8dddc47856fb127cfa503899d`
renders the owned Sonic Adventure Limited Edition GDI in two separate processes
without the prior VMEM/recompiler crash; normal Exit/checkpoint completes.
Gameplay acceptance still fails: multiple scenes produce ~88,200 PCM frames/sec
into a 44,100 Hz sink and drop roughly half. The threaded core's render-driven
retro_run does not guarantee one 60 Hz guest step per call, unlike the host's
current assumption. Source-time pacing is next, not a larger audio FIFO or a
global 30 FPS clamp. See `qa/android-portability-2026-10-02/matrix.json`.
This does not change release gates or generalize the older Thor checkpoint.

Status: **Dreamcast one-window checkpoint passed; Naomi and Atomiswave content
blocked; not release-qualified or shipped**.

EmuFusion packages the pinned Flycast Android ARM64 core only in the explicit
Phase 2 qualification payload. The artifact SHA-256 is
`a1734df1ec9ca36b9d9a4c3d51074f4c1c18349a59f19bee1790cb1a7660b30c` (2026-09-06:
rebuilt with `engines/patches/flycast-libretro-cheat-support.patch`, which
wires `retro_cheat_set`/`retro_cheat_reset` to the core's own
`CheatManager::addGameSharkCheat`/`enableCheat`; the prior unpatched artifact
hashed to `9f463fd96331dcaf507a853de5c501b06fa2abd5084ebdff5a869f6cce2ad0d5`).
Normal release routing remains fail-closed and no RetroArch frontend is used.

## Hardened AYN Thor checkpoint

Exact APK SHA-256
`12e0e83494a75b0f709b93b2a0c4efed9810f7c1632dc5272f2e9278ead37006`
ran the user's 240pSuite Dreamcast image inside the existing
`org.pegasus_frontend.android.MainActivity` on display 0. There was one EmuFusion
process, one visible EmuFusion recents identity, no external emulator activity,
and the private display-4 preview surface was completely black.

The gate measured 60.64 FPS, 44.1 kHz stereo, 225,639 received/written audio
frames, and zero underruns. Physical A input produced a visible response.
Holding the Thor Stop/Select button committed Quick Resume and returned to the
same activity. After forced process death, Flycast restored live video and
audio at 60.59 FPS. Evidence is in
`unified-android/build/one-window-phase2-hardened-available-matrix/results.json`.

## Remaining gates

- The dependency and file-level license audit is incomplete.
- Naomi and Atomiswave have no authorized fixture on the connected Thor and
  their firmware identities remain blocked; Dreamcast evidence must not be
  generalized to those systems.
- Vulkan, repeated context loss, 100 state cycles, migration, broad title
  compatibility, sustained thermal behavior, and additional devices remain
  open.
- The KallistiOS fixture/toolchain must be pinned and its built artifact rights
  recorded before it can become a distributed release fixture.

The registry therefore remains `shipped=false` and does not auto-select the
qualification core in production.
