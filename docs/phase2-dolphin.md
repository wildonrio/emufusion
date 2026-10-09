# Dolphin Phase 2 in-process candidate

Status: **qualification-packaged; release gates remain fail-closed**.

## October 5 external validation and evidence correction

Exact normal6d7bf279 is unchanged. Official Khronos Android validation layer
1.4.363.0, downloaded with release-digest verification, was attached externally to
only the owned offline Android16/4KiB landscape simulator. Actual layer startup
confirms core and synchronization validation on both GameCube and Wii. Two GC
race restorations, acceleration/boost jump, Wii World1-1 entry/visible jump and
all three normal checkpoint/retirement/library returns complete with no reported
VUID, synchronization hazard, validation error or fatal app crash in scoped logs.
Validator-only /tmp shader-cache read/write information is recorded. This is
bounded API validation, not all-frame rendering or performance acceptance.

**Correction to older rendering claims below:** the magenta/cyan rectangular
strip just after Luigi Circuit's starting line is not sufficient evidence of an
emulator artifact. The course has a rainbow Dash Panel there, and the inspected
kart accelerates and jumps after crossing it. Treat the old rendering-failure
classification as unsupported/likely normal course content, not as a bug proven
fixed. No authoritative pixel/video comparison was made. Historical screenshots
and logs remain unchanged. This correction does not apply to the separately
reproduced N64 allocation-padding bug or remove measured Dolphin audio/slowdown
failures. References: [Dash Panel](https://www.mariowiki.com/Dash_Panel),
[course walkthrough](https://www.gamespot.com/articles/mario-kart-double-dash-walkthrough/1100-6085215/).

External checker copies removed, original settings/properties restored, unchanged
APK and both identities verified, saves unchanged during cleanup; owned simulator
shut down normally. No source fix, speed improvement, physical-device test,
private report or release this run. Evidence:
`qa/android-portability-2026-10-05-dolphin-validation/outcome.json`.

## October 5 batch allocator overflow and current-code trial

The actual GPU probe now extracts the pinned core's pool constants16/8/8;
the previous8/8/8 fixture was simplified. Explicit compare mode runs corrected
single allocation versus the isolated batch method without first stopping at
the known-broken original.6342 values pass with6345/210 driver calls, followed
by120000 values with120012/3816 calls; both include pool exhaustion and
fence-delayed frame reuse. Three host tests pass with ASan/UBSan and poisoned
failed output handles. Compute storage-buffer coverage is not graphics/texture
sampling or physical-GPU acceptance.

Isolated0822302d retests existingc8a0cb1e on current e66 managed/theme code;
all other native libraries unchanged. GC race restore/reverse11mph/forward14mph
and exit/checkpoint pass, but99.644s/5700callbacks/812underruns still fails
smoothness/audio. Wii restore/map/World1-1 entry and exit/checkpoint pass; game
deaths during screenshot inspection prevent a new movement/jump claim. Map
49.131s/2700callbacks/787underruns. No matched comparison, listening, displayed
FPS or all-frame correctness claim. The batch patch remains isolated.

Normal e66 restored, both identities/PS2 cards preserved, own AVD shut down.
Insufficient-space rollback retry required removing one hash-verified disposable
Dreamcast Track3 copy, retaining its host original; restore before DC retest.
Other simulator and physical devices untouched; no release. Do not repeat this
trial as untried. Evidence and recomputation:
`qa/android-portability-2026-10-05-dolphin-batch-overflow/{outcome.json,record.py}`.

## October 5 descriptor-allocation error correction

The Android16 simulator driver returns VK_ERROR_FRAGMENTED_POOL at allocation
1025 while still writing a non-null output handle. The former allocator checked
the handle instead of requiring VK_SUCCESS and returned it to the renderer.
A negative-control GPU probe now stops at that exact failed-output acceptance,
before submitting invalid descriptors. Earlier unguarded overflow probes stalled
and were terminated; they are not performance or correctness passes.

The normal source recipe now includes `dolphin-libretro-descriptor-errors.patch`:
only successful allocations escape; exhausted pools advance, hard errors return
failure, and an unusable fresh pool cannot trigger unbounded recursion. Allocation
batching remains an isolated experiment and is NOT part of this correction.
The corrected extracted method verifies6342 actual GPU compute output values
across two incompatible layouts, three frame slots and fence-delayed pool reuse.
The original fails the corresponding allocation check.33 focused host tests pass,
including original-fails/fixed-passes allocation methods under ASan/UBSan.

The cached original native build first reproduced3d45f067 byte-for-byte, then the
single-method correction built12fecae4b12872ff80d6c677cbb2c65504cae439d86e0cad204cd1166642c6a6.
The source lock, normal recipe/registry and staged native now identify this build.
This is a controlled incremental build, not a second independent fresh build.
Actual GC/Wii gameplay with the corrected core still needs acceptance; this
probe does not prove that every prior stripe, crash or slowdown shares this cause.
Evidence: `qa/android-portability-2026-10-05-dolphin-gpu-probe/`.

The subsequent exact e66 full-APK runtime test FAILS performance/rendering
acceptance. Normal internal GC cold menus reach Luigi Circuit, but severe stalls
and magenta/cyan track patches persist. Independent driving remains unverified.
A stack samples the CPU-GPU thread waiting in ranchu descriptor allocation;
the bounded title/player window is300callbacks/51.885s with215new underruns.
Wii sequentially launches from the library to its prior durable save and map;
D-pad movement and both normal checkpoint/exit/retirement paths are verified.
Wii's map window is600callbacks/25.158s with600new underruns; an uncaptured
level attempt is not gameplay proof. No matched before/after performance,
physical GPU, listening or all-frame correctness claim. Own4KiB fixture retains
e66, verified after runtime with both original identities and PS2 cards; shut
down cleanly. Evidence: `qa/android-portability-2026-10-05-dolphin-error-runtime/`.

EmuFusion pins the maintained Dolphin libretro fork at commit
`0ff12a5a2835762e0665afe6a161a648b433f996` and the exact 30-input source
closure in
[`engines/dolphin-source-lock.json`](../engines/dolphin-source-lock.json).
The lock fixes Android API 26, NDK 27.0.12077973, CMake 3.22.1, Ninja 1.10.2,
and the Android ARM64 libretro profile. Build it with:

```sh
engines/build_core.sh dolphin
```

Two fresh October 2 builds with the alternate-signal-stack ownership fix
produced the same stripped AArch64 core after removing the non-runtime
`.note.gnu.build-id` section:

- artifact: `engines/build/arm64-v8a/dolphin_libretro.so`
- normalized SHA-256: `3d45f067691e48dcc8b8a337dd11d2310072ef48089c7f5f8c4e3508fde82296` (confirmed by two clean staged builds)

The qualification profile currently selects EmuFusion's in-process Vulkan
libretro host for GameCube and Wii; the GLES host remains available. Neither
launches Dolphin's Android Activity or Java/JNI frontend. GameCube and
Wii are qualification routes only. EmuFusion installs the pinned `Data/Sys` tree
into app-private storage and selects native EFB resolution, synchronous shader
compilation, and wait-for-shaders. r24 removes the old mandatory Thor-specific
2x EFB profile (1280x1056). Explicit supported core-option overrides still allow
upscaling; native aspect and display fit are independent of internal resolution.

The October 2 landscape Android 16 comparison runs Mario Kart Double Dash at
2x in r23 and restores that race at 1x in r24. Sampled active-step medians improve
from 31.21 to 44.33 Hz, but audio underruns continue and neither is a full-speed
acceptance pass. These are core-step intervals, not physical frame-presentation
measurements, and the scenes are not a deterministic benchmark replay. Both
normal exits/checkpoints complete; phone simultaneous steering/acceleration and
the r24 restore are visually verified. Neither fresh r23 nor restored r24
inspection shows the earlier r16 magenta stripe, without establishing all-frame
rendering correctness. Evidence: `gc-resolution-comparison-r24.json`,
`gc-2x-r23-runtime.log`, `gc-1x-r24-runtime.log`, and the `gc-*-r23/r24` screenshots
under `docs/qa/android-portability-2026-10-02/`.

## Aborted startup and Vulkan initialization (October 2)

The Vulkan host now forwards live cheat reset/set calls like GLES, including
an empty enabled selection. The former unsupported-operation exception aborted
Mario Kart startup before attaching a Surface. Its cleanup then called Dolphin's
POSIX exception-handler uninstaller without having installed a handler, freeing
Android ART's existing alternate signal stack. The pinned ownership patch makes
uninitialized/repeated cleanup a no-op, frees only Dolphin's own allocation, and
restores the previous stack after normal use. The host regression executes the
original and patched functions with ASan/UBSan; the Android early-close probe
reproduces the original abort on r16. On the exact installed r17 APK, the same
Android probe passes two load/close cycles with no Surface/frame and repeated
close calls. Evidence: `docs/qa/android-portability-2026-10-02/` files
`dolphin-early-close-r16-readable.log` and `dolphin-early-close-r17.log`.
This focused lifecycle pass is not full gameplay or hardware qualification.

The r16 landscape Android 16 simulator run resumes a GameCube race and exits
normally through Vulkan; severe GLES dark-blue shading is absent. A magenta track
stripe, inadequate speed and audio underruns remain. Do not infer hardware or
smooth-gameplay acceptance from this renderer comparison. See the October 2
portability evidence matrix for the current candidate and exact results.

## October 4 simulator pacing attribution

Clean7090 still restores Mario Kart at native1x/Off internally but runs41.28
callbacks/sec over58.135s with2221 new audio underruns. An isolated observer
places87.87% of measured native time inside the core call (20.33ms/call), versus
10.26% acquiring images/fences and1.06% final presentation. Separate CPU sampling
finds40.16% of sampled work under gfxstream descriptor allocation. Most callchains
are incomplete, so this locates a simulator-driver hotspot, not complete CPU/GPU
attribution or physical-device performance. No behavior change promoted; clean
APK and normal staging retained. Evidence and recomputation:
`docs/qa/android-portability-2026-10-04-dolphin-pacing/`.

The descriptor allocation batching trial was completed October4 and remains
isolated: callback rate improved in a bounded comparison, but audio still
failed and shared Wii/physical-GPU/rendering acceptance is incomplete. See
`qa/android-portability-2026-10-04-dolphin-descriptors/outcome.json`; do not repeat
it as an untried experiment. The current single-core policy avoids a documented
dual-core frame-pump deadlock and is not a safe performance toggle.

## October 5 Vulkan reset and normal 16 KiB control evidence

The render-owner Vulkan wrapper now forwards reset through Java/JNI to the
existing `lucent_retro_reset`, instead of unconditionally throwing unsupported.
The full portable306d candidate changes no emulator core. Android16/16KiB
GameCube runtime verifies restore, Start+Select reset, opening/title, post-reset
Start/A menus, normal checkpoint and retirement/library return. No post-reset
race or Wii reset acceptance is claimed.32 focused regressions, Java lifecycle
and render-loop probes, native tests and sanitizers pass.

Normal35d on the same16KiB fixture separately verifies new-race menus,
0-to44mph acceleration, two exits and race restoration. Its19.173s driving
window has600callbacks/599new audio underruns/0PCM drops; no full-speed/audio
pass. Both results and14 inspected captures are recorded in
`qa/android-portability-2026-10-05-vulkan-reset/outcome.json`.

The subsequent normal306d4KiB Wii run verifies the same reset bridge, title to
file/player menus, existing save selection, World1-1 and visible left-stick
movement. Two normal exits commit and retire; same-process relaunch restores the
saved transition/stage. No input mapping change was necessary. The15.402s stage
interval has600callbacks/564new underruns/0PCM drops, so performance still fails.
Fourteen inspected captures and exact runtime markers are recorded separately
in `qa/android-portability-2026-10-05-vulkan-reset/wii-outcome.json`.

## Wii IR input

The hardware GLES session supplies a real `RETRO_DEVICE_POINTER` path. Wii
right-stick X/Y is mirrored to an absolute IR cursor, and mapped A supplies both
the ordinary Wiimote A button and pointer contact. The original right-stick
analog index remains live for tilt, while the left stick remains the Nunchuk
stick. The host deterministically selects Dolphin's pointer-backed
`dolphin_ir_mode=2`; this is an internal compatibility profile, not a user
option. Runtime QA holds the IR aim while pressing A+B so a title prompt cannot
receive a click only after the cursor has sprung back to centre.

This closes the source, Android compiler/linker, packaging, and in-process host
integration work. The complete dependency-license audit, legal distributable
test content, save-state compatibility, repeated process-death recovery,
surface lifecycle, sustained performance, and three-title-per-system physical
device matrices remain independent release gates and must fail closed until
their recorded QA passes on the exact release APK.
