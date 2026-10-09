# EmuFusion LSFG backend evaluation — 2026-08-23

> 2026-08-24 superseding technical update: the bounded in-process Android
> Vulkan feasibility milestone now passes on Thor. The exact patched wrapper
> consumed EmuFusion-owned endpoint AHBs, kept output GPU-resident, used an
> owned WSI surface and `VK_GOOGLE_display_timing`, and physically passed the
> generated subsets for fixed-midpoint 20→40, 30→60, and 60→120 with constant
> 6/4/2-scan spacing. See
> `docs/LSFG-ANDROID-INPROCESS-FEASIBILITY-2026-08-24.md` and
> `experiments/lsfg-vulkan-android-inprocess/evidence/thor-owned-surface-multirate-r6.json`.
> This supersedes the technical-interface STOP statements below, but does not
> make LSFG selectable: moving N64 gameplay, full alternating real/generated
> SurfaceFlinger evidence, complete fallback injection, automatic product
> integration, and lawful asset delivery remain unresolved.

> 2026-08-24 update: the lawful RIFE+ncnn alternative has now physically
> demonstrated a uniform synthetic 30→60 Vulkan transport on Thor, but remains
> quarantined and non-qualifying. See
> `docs/RIFE-VULKAN-DISPLAY-TIMING-CHECKPOINT-2026-08-24.md` for the exact
> cadence evidence and remaining visual/legal/product blockers.

## Decision

Lossless Scaling is **not currently a selectable or active EmuFusion backend**.
Frame Generation remains a single owner setting (`Off` / `On`), and `On`
currently resolves to EmuFusion's built-in backend.  Direct presentation remains
the fail-safe.

This is deliberate rather than a missing-file fallback.  The available LSFG
artifacts do not yet satisfy the legal-interface, synchronization, timing, and
physical-qualification requirements below.

## Publicly verifiable state

- The official Steam product describes LSFG as a proprietary model and lists
  Windows 10+ / DirectX 11 as its supported platform.  It points to `lsfg-vk`
  only as a community-driven Linux port:
  <https://store.steampowered.com/app/993090/Lossless_Scaling/>
- The unofficial Android project uses MediaProjection plus a system overlay for
  normal operation.  Its own documentation reports roughly 50–80 ms additional
  latency, per-session capture consent, a persistent system indicator, and Play
  policy restrictions.  That path cannot preserve EmuFusion's endpoint identity,
  phase, scheduler, or one-setting UX and is therefore not an acceptable backend:
  <https://github.com/FrankBarretta/LSFG-Android>
- The Android fork of `lsfg-vk` adds an in-process `AHardwareBuffer` API
  (`createContextFromAHB`) and is technically closer to the required contract:
  <https://github.com/FrankBarretta/lsfg-vk-android>
- The fork's pipeline code is MIT-licensed, but the generated result still needs
  proprietary LSFG shader assets obtained from a user-owned `Lossless.dll`.
  The current Android application is separately licensed for personal,
  non-commercial, sideload-only use and expressly does not redistribute the DLL
  or extracted shaders:
  <https://github.com/FrankBarretta/LSFG-Android-Application#license>
  Neither the application license nor the MIT wrapper license grants rights to
  THS's proprietary shader payload.

### 2026-08-24 public-source recheck

No official THS Android SDK, redistributable runtime, or documented callable
LSFG integration API was located in the official Steam product page or update
history as of this review.  This is a bounded statement about the public sources
reviewed, not a claim that a private partner API cannot exist.  The official
page still identifies LSFG as proprietary, lists Windows 10+/DirectX 11 as the
supported product environment, and describes Linux only as a community-driven
`lsfg-vk` port.  It now documents an Adaptive mode that can target a non-integer
multiple, but does not publish that capability as a developer ABI:
<https://store.steampowered.com/app/993090/Lossless_Scaling/>

The exact public Android library source reviewed was the `release` branch at
commit `3e89e5439a98f55d5acb003d20039426ab24e69c` (2026-05-01):
<https://github.com/FrankBarretta/lsfg-vk-android/tree/3e89e5439a98f55d5acb003d20039426ab24e69c>

That source establishes a real but insufficient low-level integration surface:

- `initialize(... generationCount ...)` fixes the number of outputs for the
  library lifetime; `createContextFromAHB` accepts two input AHBs and one AHB per
  generated output; `presentContext` exposes no presentation timestamp or phase:
  <https://github.com/FrankBarretta/lsfg-vk-android/blob/3e89e5439a98f55d5acb003d20039426ab24e69c/framegen/public/lsfg_3_1.hpp>
- The output shader constants are constructed as
  `(i + 1) / (generationCount + 1)`.  The published interface therefore produces
  fixed evenly spaced phases, not EmuFusion's exact phase derived from immutable
  endpoint and presentation timestamps:
  <https://github.com/FrankBarretta/lsfg-vk-android/blob/3e89e5439a98f55d5acb003d20039426ab24e69c/framegen/v3.1_src/shaders/generate.cpp>
- The context reuses eight submission slots and can wait on their fences with an
  unlimited timeout.  The Android wrapper additionally exposes `waitIdle()` as
  `vkDeviceWaitIdle` because the framegen library owns a separate Vulkan device:
  <https://github.com/FrankBarretta/lsfg-vk-android/blob/3e89e5439a98f55d5acb003d20039426ab24e69c/framegen/v3.1_src/context.cpp>
  <https://github.com/FrankBarretta/lsfg-vk-android/blob/3e89e5439a98f55d5acb003d20039426ab24e69c/framegen/v3.1_src/lsfg.cpp>

Those are engineering blockers, not a dismissal of the port.  The MIT wrapper
could in principle be adapted to accept EmuFusion-owned timestamps/phases and a
nonblocking synchronization contract.  Such adaptation still cannot be an
automatic product backend until the proprietary shader use is expressly lawful,
the exact ABI is frozen, and the modified path passes output, latency, failure,
and moving-game physical qualification.

## Local ownership artifact (metadata only)

The supplied file was **not executed** and its proprietary resources were not
extracted.

```text
path: /Users/tyleryoung/Downloads/Lossless.dll
sha256: fe0faeb147accab84539ac2bdcaa4eb3dec850752a336e710b85fc87477004e4
size: 5,435,904 bytes
format: PE32+ x86-64 Windows DLL
link timestamp: 2025-06-09 09:10:46
```

Its PE export metadata exposes Windows application-level entry points such as
`Init`, `Activate`, `ApplySettings`, and `UnInit`; it does not expose a documented
Android ABI or a documented endpoint/phase frame-generation interface.  File
presence and ownership therefore do not qualify it as an Android backend.

## Technical candidate and blockers

The Thor device reports Vulkan 1.3 on Adreno 740 and exposes both
`VK_ANDROID_external_memory_android_hardware_buffer` and `VK_EXT_robustness2`,
so an in-process Vulkan candidate is technically plausible.  The captured device
capability record is:

```text
/private/tmp/thor-vkjson-2026-08-23.json
```

The current community Android wrapper is not usable as-is:

1. It creates a separate Vulkan device around shared AHardwareBuffers and then
   calls `vkDeviceWaitIdle`.  A blocking whole-device wait is forbidden on the
   live presentation path.
2. Its public fixed-count interface does not make EmuFusion the sole owner of
   an arbitrary exact interpolation phase.  The reviewed public ABI has no
   timestamp/phase parameter and constructs only fixed evenly spaced phases.
3. Its normal Android application owns capture, pacing, queueing, overlay output,
   settings, and counters.  EmuFusion must own all of those instead.
4. No lawful redistribution or incorporation permission for the proprietary
   shader payload has been established.

Vulkan provides external semaphore/fence mechanisms that may permit asynchronous
cross-device synchronization without `vkDeviceWaitIdle`; in particular,
`VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT` represents Linux sync files or
Android fence objects.  Any candidate must query and self-test this exact path on
Thor rather than assuming support:
<https://registry.khronos.org/VulkanSC/specs/1.0-extensions/man/html/VkExternalSemaphoreHandleTypeFlagBits.html>

## Required EmuFusion backend contract

Backend selection occurs once at a safe session boundary:

```text
Frame Generation On
  -> compatible, legally usable, self-tested LSFG
  -> otherwise Built-in
  -> otherwise Direct
```

The backend receives only:

- immutable adjacent endpoint IDs, textures/buffers, and producer timestamps;
- exact requested presentation timestamp and derived phase in `[0, 1]`;
- output dimensions/format and a hard completion deadline;
- an immutable session/presentation epoch.

The backend returns a generated image plus completion/status evidence.  It does
not own capture, source-rate normalization, target selection, buffering,
presentation pacing, overlays, counters, or fallback policy.

An LSFG candidate is usable only after all of the following pass:

- explicit legal permission for the exact assets and integration form;
- arm64 Android ABI/API version and required Vulkan capabilities;
- exact-phase correctness at several non-midpoint phases;
- endpoint-order, cut/discontinuity, and stale-epoch rejection;
- nonblocking synchronization with no CPU readback or whole-device wait;
- bounded p95/max latency below the target deadline;
- output-content self-tests and physical moving-game qualification;
- atomic failure fallback that discards the failed pair and re-primes Built-in.

Until then, the honest automatic result is `Built-in`, not a file-presence-based
`LSFG` label.

## Quarantined lawful-alternative timing boundary

The independently locked RIFE v4.6 + ncnn Vulkan experiment remains a research
backend, not an LSFG implementation and not a product route.  Its model
provenance/redistribution and numerical-golden gates are still unresolved, and
the Phase-1 runner includes Vulkan upload, inference, and CPU download rather
than the required in-process presentation-surface path.

Two fresh Thor measurements on 2026-08-23 establish a useful per-rate boundary
at 128x72.  Both used 30 warm-up pairs and 120 measured pairs in the standalone
`com.emufusion.rifebenchmark` package; the installed EmuFusion APK was not
replaced.

| Path | Composite p95 | End-to-end p95 | Missed synthetic deadlines |
| --- | ---: | ---: | ---: |
| 30 -> 60 | 9.249 ms | 9.349 ms | 0 / 120 |
| 60 -> 120 | 8.967 ms | 9.066 ms | 120 / 120 |

Evidence:

```text
/private/tmp/rife-128x72-30to60-r1.4n7hTW/phase1-v4-128x72-30to60-20260823-r1/incomplete-result.json
sha256 8e115ff614bdb9859ead68e1b8934508a003e2701c37d70280897315f4acabb6

/private/tmp/rife-128x72-60to120-r1.Z2KuAW/phase1-v4-128x72-60to120-20260823-r1/incomplete-result.json
sha256 91178fffbcdb8de12639215c8df7146a15b6beaf59d0f5d9a6894ee5760fdfca
```

The content diagnostics were materially stronger than the current built-in N64
TWINE experiment (114 of 116 motion-eligible samples correlated, with 76,965
non-crossfade pixels out of 78,379 eligible pixels), but these are analytic
diagnostics rather than a physical moving-game visual pass.

Consequences:

- The present RIFE adapter is demonstrably too slow for 60 -> 120, even at
  128x72.  It must not be routed there.
- It has enough isolated timing headroom to justify a later, quarantined
  presentation-surface experiment for 30 -> 60 and 20 -> 40.
- Automatic backend selection must be qualified per source/target path; a
  backend that passes 30 -> 60 cannot inherit certification for 60 -> 120.
- No product integration is authorized until the legal/model provenance,
  exact-phase, no-readback synchronization, numerical-golden, and physical
  visual/cadence gates all pass.

After the experiment, `com.thorium.preview` remained stopped with proof unset and
the installed APK still hashed to
`6d3f874883a9fa9ad7e1fab5edbc66a34ebd6f82ac618db47b8238ccb5473a3f`.

## RIFE Android transport checkpoint

Device-safety rule for all remaining physical work: Thor's OLED must be left
`Dozing`/screen-off whenever a visual test is not actively running. Install,
pull, parse, build, and host analysis should occur with the panel off. Wake only
immediately before a Surface/visual run; afterward force-stop the benchmark and
turn the display off in the same cleanup sequence. This avoids leaving a static
launcher or benchmark overlay on the OLED for long unattended periods.

The next lawful-alternative milestone is now source-complete inside the
standalone benchmark only. It does **not** make RIFE a product backend and does
not change the timing result above.

The immutable preparation step now applies two exact, hash-pinned changes:

1. `RIFE::process_v4_vk_record` records host-input upload plus RIFE v4 inference
   into a caller-owned `ncnn::VkCompute` and returns the output as a GPU-resident
   `VkMat`. It performs no output download, submit, fence wait, allocator
   reclamation, or presentation. The caller must retain the command, inputs,
   output, and both allocators until its exact completion fence signals.
2. The benchmark-patched ncnn command object exposes a nonblocking submit path
   only when `VK_KHR_push_descriptor` makes every recorded command immediate.
   It rejects delayed records, host-download post work, a missing fence,
   inconsistent wait-semaphore state, duplicate submit, and reset while work is
   pending. Completion uses `vkGetFenceStatus`; neither `vkWaitForFences` nor
   `vkDeviceWaitIdle` appears in this steady-state contract.

Thor physically reports this narrow API as supported:

```text
gpuResidentRecordApiCompiled=true
nonBlockingSubmissionApiCompiled=true
nonBlockingSubmissionSupported=true
gpuResidentSurfaceOutputImplemented=false
```

The exact cold-load smoke passed on Adreno 740 with APK SHA-256
`1bb03c790a31b822aae0572e888bae0192549ee43878e45bad3187f22f61c98d` and
native-library SHA-256
`a62a200a6c241253e9f6528fc83149b542a3ca974972a175abd3abc43732d067`.
The earlier refactored legacy 64x64 interpolation also passed with intact
canaries and changed output. EmuFusion was neither installed nor started by
these checks.

A subsequent real Android `Surface` capability probe also passed on Thor. It
created `VkSurfaceKHR` from a 1920x1025 `ANativeWindow`, and the exact RIFE/ncnn
compute queue family (`0`) reported presentation support. The surface exposed
six formats, four present modes, FIFO and mailbox, RGBA8/BGRA8, and all three
useful output capabilities: storage image, transfer destination, and color
attachment. Every Vulkan query returned `VK_SUCCESS`; the reported usage mask
was `159`, with image-count range 3..64. The standalone probe APK was SHA-256
`72171740a44408c0afd3bfce30c2ca441fc887f98ca16b7dd0c33b7ccadc2f0b`.

The next isolated transport checkpoint also passed. The benchmark created a
four-image `VK_FORMAT_R8G8B8A8_UNORM` FIFO swapchain at 1920x1025 with
`VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_STORAGE_BIT`, acquired one
image with zero timeout, recorded and submitted a blue GPU clear through the
new nonblocking command path, called `vkQueuePresentKHR`, and observed its exact
fence complete after one zero-wait poll. The result reported one submit, one
completion, and one present call. Teardown-only queue idle remained explicitly
separate from the steady path.

The exact smoke artifacts were:

```text
run: surface-clear-present-r1
status: PASS
benchmark APK SHA-256: 356ccdc489e2667de46187308a21fb8f5802731b12fe9d6442ac420c5d17af96
instrumentation APK SHA-256: 0c46ebbfecb5ac4416895bd87afedde644c74f071f86b54f49442b7b42a1096c
swapchain format / images / present mode: 37 / 4 / 2
submitted / completed / present calls: 1 / 1 / 1
```

This proves the benchmark-owned Android Surface, swapchain, semaphore, fence,
and present plumbing on Thor. It still does **not** prove that a RIFE output was
converted into a swapchain image, that SurfaceFlinger physically displayed the
clear, or that any generated cadence meets a deadline. The next required
implementation is the GPU-only conversion from the returned `VkMat` into the
acquired swapchain image followed by timestamped 30 -> 60 testing. Until that
works and produces physical presentation evidence, `presentationSurfacePresent`
and `qualificationEligible` remain false.

That GPU-only conversion has now passed its first isolated physical smoke as
well. The locked RIFE v4 path returned its actual GPU ABI (128x72 tightly
interleaved `uint8` RGB); an 8-bit-storage compute shader bilinearly scaled and
letterboxed it directly into the acquired RGBA8 swapchain image. No output
download or CPU readback occurred before presentation. Run
`surface-rife-output-r3` reported one submit, one completion, one present call,
and completion after six zero-wait fence polls. A compositor screenshot was
captured only after the live submission completed and visibly contains the
expected nonblank deterministic moving-shape scene rather than a clear or
corrupt buffer.

```text
benchmark APK SHA-256: b4903abf4110d35c8b6ef62dca534f411ec0033f7e34349243a63174e2f3de91
instrumentation APK SHA-256: 70f62da7a43cc94ace03758153ad9a78166a73d21648f4deb62983ababfb3020
native library SHA-256: 993cd17f2bed08d29bd132ac71a7b2c73684b77c11dc6f0775fcdf9ffc4ad848
compositor screenshot SHA-256: dd72e663c7c9cb3129322a2f4e111c85d5bd93f1a383270cde7209d7a4e1517c
enqueue call wall: 45.549323 ms (cold single-shot; not a deadline result)
```

This is the first proof that a RIFE-generated image can remain GPU-resident all
the way to a real Thor swapchain presentation. It is still deliberately
nonqualifying: it supplies neither physical presentation timestamps nor a
sustained scheduled stream, and the cold one-shot enqueue wall includes setup
and recording rather than an isolated GPU interval. The next milestone is a
bounded asynchronous 30 -> 60 stream with immutable endpoint timestamps,
per-frame phase, multiple in-flight jobs, SurfaceFlinger evidence, and the
uniform panel-scan rule. EmuFusion remains untouched.

The legal characterization is similarly narrow. The exact RIFE ncnn repository
ships its v4.6 model under a repository-level MIT license, the original RIFE
repository is MIT, and ncnn is BSD-3-Clause. Those public licenses support this
private source experiment and appear to permit redistribution when notice terms
are met, but they do not supply an explicit patent grant or independently prove
training-data provenance. This remains a legal-review item rather than a claim
of legal certainty or an LSFG identity.
