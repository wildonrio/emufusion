# Phase 2 ARMSX2 integration checkpoint

Date: 2026-08-07

Status: **experimental, reproducibly buildable, qualification-packaged, not
release-qualified, not shipped**.

EmuFusion uses ARMSX2 as the current Vulkan-first in-process PlayStation 2
candidate. It runs inside EmuFusion's existing
`org.pegasus_frontend.android.MainActivity`; no ARMSX2 or external emulator
activity is launched.

## October 5 descriptor batching: built, runtime acceptance pending

Same-process Training A/B/A isolates driver descriptor allocation:51.492Hz with
519 new audio underruns at one set/call,59.485Hz/0 with batch32, then48.791Hz/415
after returning to one set/call. Measured unpaused intervals are40.783/40.346/36.892s.
Batching supplies a distinct set per draw, caches only within a fenced pool
generation, caps allocation at8192, clears only after successful pool reset, and
preserves caller-driven exhaustion recovery. Normal image-quality settings remain.
This is a bounded throughput improvement, not physical cadence/listening acceptance.

External core/synchronization validation shows an independent existing mismatch:
the subpassInput shader sees SAMPLED_IMAGE layout descriptors on non-Mali drivers.
Both private batched APK and unchangedf394 emit07990; no clean-validation claim.
New normal input-attachment patch matches layout/writes through one predicate for
non-Qualcomm drivers, preserving the existing Qualcomm workaround pending hardware
qualification. Batching and this correction are in the locked recipe. Fresh normal
4KiB `a763df4d` and16KiB `0a75e425` builds completed; isolated candidate `745980f3`
passes packaging/strict16KiB/signing gates. Original staged binaries remain
unchanged.30focused and39metadata/packaging checks pass.

Candidate runtime acceptance did NOT pass: complete intervals57.650s/46.834Hz with
715newunderruns and50.686s/53.269Hz with251newunderruns. Immediately afterward,
host inspection found432running processes on10cores and load869. Repeated Android
Gesture Monitor input timeouts prevented normal-exit qualification. This is a
material uncontrolled host-load confound, not a proven source regression or an
app-main-thread deadlock. Corrective external Vulkan validation remains unrun.
No new movement/landed-attack pass. Do not promote the candidate.

Exactf394 restored; both identities/all302checked saves unchanged. Owned simulator
and log reader stopped, ADB empty; no unrelated workload stopped or Thor used.
Retest the retained APK on a quiet host, without rebuilding completed cores.
The four-patch source lock deliberately rejects the old staged two-patch receipts;
normal packaging needs accepted matching cores before proceeding. Evidence:
`qa/android-portability-2026-10-05-ps2-descriptor-integration/outcome.json`.

Trial52f902c5 restored exactf394; both identities and302checked saves unchanged.
Checker copies removed, settings restored, simulator/readers stopped. Evidence:
`qa/android-portability-2026-10-05-ps2-descriptor-batch/outcome.json`.

## October 5 pipeline observer: rendering-publication bottleneck lead

Isolated2f564f5b retains Full blending and normal synchronization; only the Vulkan
host adds monotonic stage timing. Four analysis regressions and eleven PS2 checks
pass. Confirmed Training idle animation,45s without screenshots: complete measured
37.357s/1800callbacks=48.184Hz,858new audio underruns,0PCMdrop. Core-call wall time
69.69%,slot-fence12.25%,acquisition7.84%,presentation3.57%. Largest acquisition
15.483ms; the prior multi-second acquisition/tail gap is not reproduced. First
45s window starts in loading/transition and is not a whole-window gameplay claim.

Three app-only stack samples outside those windows find the frontend timed waiting
inside retro_run; two find the GS thread in the simulator Vulkan driver's
vkAllocateDescriptorSets/qemu_pipe_read. This is a lead to measure allocator cost
and a bounded per-layout frame-pool batching control, not proof that all core-call
time is CPU work, not a deadlock, and not grounds for dropping fences. Historical
unstripped-core file is now absent; local-symbol resolution was not possible.

Normal exit/library return verified; exactf394 restored, original identities and
all302checked saves preserved; simulator/log reader shut down. No production code
or setting changed and no performance fix promoted. No current16KiB, hardware,
fresh-data, listening, all-game or release pass. Evidence:
`qa/android-portability-2026-10-05-ps2-pipeline/outcome.json`.

## October 5 blending control: not a performance fix

Complete normal `f39419d9...f1e07` still forces Full blending. An isolated control
changes only this option to Basic in the Vulkan host; the unchanged source first
reproduces the baseline host byte-for-byte. All other APK code is unchanged.
On the existing headless landscape Android16/4KiB fixture, both runs reach the
same Capcom vs. SNK2 Training grid with Ryu/Kyo, C groove and ratio2, then exit
normally. Basic measures51.327callbacks/s and676newunderruns over40.914s: failed.
Full's25.251s measured portion gives59.404callbacks/s/0underruns, but a24.519s tail
without health messages prevents a whole-run pass or precise relative comparison.
No image-quality or gameplay-speed improvement is established; Basic is not adopted.

A live resumed-menu stack samples Android `BufferQueueProducer::dequeueBuffer`
through `vkAcquireNextImageKHR`, not ongoing guest computation. One sample also
fits a normal FIFO wait; it does not prove a deadlock or explain the long gap.
Next measure acquisition/presentation and compositor consumption during a repeated
gap rather than guessing another quality setting. Normal f394 restored with both
original profile identities and all302checked saves unchanged; library verified,
simulator stopped, no Thor or publication. Source/settings unchanged. Evidence:
`qa/android-portability-2026-10-05-ps2-blend-control/outcome.json`.

## October 5 frame-clock correction (current source/build)

The normal recipe now includes `armsx2-libretro-frame-clock.patch`: frontend
pacing owns the guest-vblank handoff instead of racing a second nominal-rate
limiter, and an early consumer waits for publication rather than completing an
empty step. Duplicate game images still represent guest vblanks. Abort and
startup/failure waits remain bounded. This is not an unlimited-speed setting.

Fresh builds are staged for both page geometries, with receipts binding the
core bytes to the locked source/patches and page size. APK reuse rejects old
binaries without these receipts. Current hashes:

- 4 KiB: `c331a8e24c4c3e6b18ad409a4229950bc9f092a1a857ab8a2cdad48855d58b90`
- 16 KiB: `cd9107dde7663bb1a7cf38efc6fbeea30a7045cff90c7965be2056c89c69d6ad`

The 16 KiB result reproduces the earlier diagnostic clock core. It was not
retested on 16 KiB this turn. Exact delta APK `db39b330...92bb4055` changes only
both PS2 cores and their build metadata relative to normal `5f004e71...46db14`.
On the existing 4 KiB Android 16 landscape fixture, normal library launch,
Training movement, a landed attack and normal exit are visually verified.
The 95.185-second fight window gives 798.809 PCM samples/callback, 403 new output
underruns and zero frontend PCM drops. Callback throughput is only 56.732/s.
**Audio/performance remains failed; this is a partial timing correction.**
No controlled before/after replay, audio listening, fresh-data installation or
Quick Resume pass is claimed. Memory-card bytes and both profile identities
were preserved, normal `5f004` restored, and the simulator stopped. No Thor
installation or public release. See
`qa/android-portability-2026-10-05-ps2-clock-integration/runtime-result.json`.

The hashes and two-clean-build statement below describe the historical August
baseline, not the current clock-corrected engine.

## Exact build identity

- Upstream: <https://github.com/ARMSX2/ARMSX2>
- Commit: `788a59d641c777cb7f70726ea573d420508e0931`
- Source archive SHA-256:
  `bc2bb2f106ca499252e3bfe0a40366de5e9749fd84bebbbe80ed52c4b07abf63`
- Compile closure: `engines/armsx2-source-lock.json`
- Integration patch: `engines/patches/armsx2-libretro-android-build.patch`
- Recipe: `engines/build_core.sh armsx2`
- Final AArch64 ELF SHA-256:
  `14baf81c3df6be7e34b7461ee9557616c4996ed49f137a948efb13303af35a13`

The recipe pins NDK `27.0.12077973`, CMake `3.31.6-g38307f9`, Ninja `1.12.1`,
API 26, all seven shaderc dependencies, the EmuFusion integration patch, locale,
timezone, source epoch, path maps, and `--build-id=none`. Two isolated clean
source/build roots produced byte-identical stripped files (24,637,656 bytes)
with no GNU Build ID. Their 114-file runtime-asset trees also matched,
including `GameIndex.yaml` and `patches.zip`.

## AYN Thor checkpoint

The qualification APK launched the user's God of War image on the Thor's top
display with ARMSX2 in EmuFusion's Vulkan host. The exact APK run demonstrated:

- a visible game frame and live 48 kHz stereo audio;
- a physical A-button down/up delivered from the Odin Controller input node;
- current interval performance near 60 FPS after warm-up;
- Quick Resume commit before exit; and
- a forced process death followed by successful state restore and continued
  video/audio.

The runtime-asset revision fix also removed the previous `patches.zip` warning.
This is a one-title, one-device qualification checkpoint, not a compatibility
or release claim.

The current product-contract run used exact hardened APK SHA-256
`12e0e83494a75b0f709b93b2a0c4efed9810f7c1632dc5272f2e9278ead37006`.
God of War remained in the same `MainActivity`, task, window, and process;
display 4 was black with a measured visible fraction of `0.0`; physical A and
held Stop were delivered through the Odin Controller node; Quick Resume was
committed; and a forced process death restored live video and audio. Health was
59.52 FPS at 48 kHz before exit and 59.65 FPS after restore, with zero audio
underruns. Evidence is in
`unified-android/build/one-window-phase2-hardened-available-matrix/results.json`.

## Gates still closed

October 3 portability checkpoint: a normal library launch on an Android 16
16 KiB-page simulator reproduced the upstream page-size mismatch rejection.
The build now bundles the original 4 KiB core and an additional 16 KiB core in
one APK, selected from the actual kernel page size. The exact-page guard is
preserved. The new variant SHA-256 is
`0fc8c092a58ee005614691cbbce7ce25a030fe473952084781cc856de03f8965`;
it has one successful clean build, not a two-build reproducibility proof.
Both runtime-asset trees match, and the existing 4 KiB core is unchanged.

The same candidate APK `b6839c52...1505d7d` was installed with exact-byte and
stable-identity verification on headless, landscape 4 KiB and 16 KiB Android 16
simulators, each with only EmuFusion installed. Capcom vs. SNK 2 training,
analog movement, an R2 attack and normal exit were visually verified on both;
16 KiB same-process repeat boot/exit also passed. Audio underruns remain on both,
Quick Resume remains quarantined, and whole-APK native 16 KiB compatibility
is not qualified. No public release or physical-device installation occurred.
Full evidence: `qa/android-portability-2026-10-03-ps2-16k/outcome.json`.

- Complete file-level dependency/license and notice audit.
- Legally redistributable PS2 fixture with a reproducible toolchain.
- User-BIOS identity/policy and a multi-region firmware matrix.
- 100 state cycles, ten-minute history, reboot, corruption, and migration QA.
- Broad title compatibility, normal memory-card saves, surface-loss recovery,
  sustained thermal/frame-pacing/audio testing, and single-screen devices.
- Thor dual-display behavior and 16 KiB-page Android compatibility.

The registry therefore keeps `reproducible=false` for the overall release
candidate and all distribution/runtime/device gates closed despite the exact
recipe's byte reproducibility and successful Thor checkpoint.
