# LSFG Android in-process feasibility — 2026-08-24

Status: **BOUNDED TECHNICAL FEASIBILITY PASS; N64 GAMEPLAY AND PRODUCT QUALIFICATION STILL STOP**.

This checkpoint is intentionally narrower than product qualification. It
records what the Thor physically proved, what remains unproven, and the legal
boundary around the user's proprietary Lossless Scaling asset.

## Decision summary

The public Android Vulkan wrapper is technically plausible enough to justify
one bounded midpoint-only integration experiment. It is not acceptable
unchanged and it is not currently an EmuFusion backend.

Evidence supports these statements:

- Android ARM64 can load the public native wrapper on the Thor.
- A privately supplied, hash-identified Windows DLL can be inspected without
  executing it, and the public extractor can translate its shader payload.
- Thor's Adreno 740 Vulkan driver accepted all 48 translated shader modules.
- The public wrapper can import RGBA AHardwareBuffers for both endpoints and
  output.
- Thor exposes Android external AHardwareBuffer memory and external sync-FD
  semaphore features required for a GPU-only cross-device handoff.
- Two exact deterministic endpoint AHardwareBuffers were submitted directly
  to fixed-2× LSFG without MediaProjection or a companion capture path.
- The generated AHardwareBuffer stayed GPU-resident in the live path and was
  presented through a disposable EmuFusion-owned FIFO Vulkan surface.
- A matching `VK_GOOGLE_display_timing` record proved physical latch, and the
  zero-wait host fence observation occurred before the requested deadline.
- Evidence-only post-completion hashing proved the generated image differed
  from both endpoints and placed the moving object at the requested midpoint.

Evidence does **not** yet prove:

- all required product failure injections, especially delayed/invalid sync FDs,
  export failure, swapchain-not-ready, and endpoint/session epoch changes;
- SurfaceFlinger-layer agreement for the full alternating real/generated stream;
- 20→40, 30→60, or 60→120 moving-game deadlines and visual quality;
- representative moving-game visual quality or product legality.

## Exact public and private identities

| Item | Identity |
| --- | --- |
| Public wrapper | `FrankBarretta/lsfg-vk-android` commit `3e89e5439a98f55d5acb003d20039426ab24e69c` |
| `dxbc` submodule | `78ab59a8aaeb43cd1b0a5e91ba86722433a10b78` |
| `pe-parse` submodule | `31ac5966503689d5693cd9fb520bd525a8710e17` |
| `toml11` submodule | `be08ba2be2a964edcdb3d3e3ea8d100abc26f286` |
| `volk` submodule | `be3dbd49bf77052665e96b6c7484af855e7e5f67` |
| Disposable probe scaffold | `FrankBarretta/LSFG-Android-Application` commit `b84754199823615d32d65fe33ea59481dca88dcf` |
| User-owned input | `Lossless.dll`, 5,435,904 bytes, SHA-256 `fe0faeb147accab84539ac2bdcaa4eb3dec850752a336e710b85fc87477004e4` |

The DLL is PE32+ x86-64 Windows code and was not executed. Its imports include
Windows/D3D11/DXGI/DWM APIs; its exported surface is application-oriented
(`Init`, `Activate`, `ApplySettings`, `UnInit`), not an Android SDK ABI.

The public wrapper and its framegen source declare MIT. The separate Android
application is excluded from product code because its repository has
conflicting GPL/custom-license signals and its MediaProjection/overlay model is
explicitly disallowed by the EmuFusion goal.

## Thor foundation probe

The probe used a disposable application ID, `com.emufusion.lsfgfeasibility`,
so it did not replace EmuFusion or the user's existing LSFG application. The
test privately staged the owner-supplied DLL into app-private storage, invoked
the public extractor, asked the actual driver to create every resulting Vulkan
shader module, and removed the private input afterward.

Final device result:

```text
instrumentation: OK (1 test), 1.494 s
lsfg-extract: Translated 48 DXBC shaders
Using GPU: Adreno (TM) 740 (API 1.3.128)
Probe complete: 48 accepted, 0 rejected
```

Exact disposable APKs:

- ARM64 target: SHA-256
  `8ce36297cf52bdf22ef8e07bf398d35fbdaaa3732800e5c9e541fcee590492bc`
  (64,889,262 bytes).
- Instrumentation: SHA-256
  `a65fd357f99c3b52b663d855593bf6f36a60cc9d682a14ec3bc19e8f036fa7f1`
  (814,108 bytes).

The Thor OLED remained asleep before and after the probe. The disposable
package and staged DLL were removed.

This is `FOUNDATION_PASS`, not `LIVE_PATH_PASS`.

## Owned-surface midpoint probe r1

After the foundation probe, the exact public wrapper was patched with a new
Android-only try API. The patch imports an input `SYNC_FD` temporarily, signals
an LSFG-owned exportable `SYNC_FD`, checks ring reuse with
`vkGetFenceStatus`, and returns `BUSY` rather than waiting. The disposable
target supplied two deterministic 320×180 RGBA endpoint AHardwareBuffers
directly; no capture service was started.

The host imported LSFG's output-ready FD into its separate Vulkan device,
submitted a GPU blit into a dedicated 1920×1025 FIFO swapchain owned by the
probe Activity, and `vkQueuePresentKHR` returned success. Instrumentation
passed 1/1 in 5.184 seconds. The measured request record was:

```text
left/right endpoint: 100/101
left/right source time: 1000000000 / 1033333334 ns
requested source time: 1016666667 ns (exact 1/2 phase)
generation CPU submit: 0.640000 ms
owned WSI present CPU submit: 3.142344 ms
request-to-present-submit: 5.328594 ms
provisional 50 ms deadline margin at submit: 44.650781 ms
```

Exact r1 APKs:

- ARM64 target SHA-256
  `4cd8ab0e09327781756eda8b10f02328c487bcfda3ef08517a7dee07ab08ce3d`.
- Instrumentation SHA-256
  `1d5974132dea0b5cd7af2a1ea6e7ed5103a9145b634131a7b43172b9e391d9cb`.

Machine-readable evidence is in
`experiments/lsfg-vulkan-android-inprocess/evidence/thor-owned-surface-midpoint-r1.json`.

This establishes `TRANSPORT_SUBMISSION_PASS`: real Android execution,
AHardwareBuffer endpoints, cross-device sync-FD handoff, GPU-resident output,
owned WSI submission, and safe one-shot cleanup all worked. It does **not**
establish GPU completion, physical latch time, correct generated pixels, or
the 8.3/16.7 ms product deadlines. CPU return from `vkQueuePresentKHR` is not a
physical frame.

## Owned-surface deadline/latch/content probe r2

The r2 incremental patch enabled Thor-supported
`VK_GOOGLE_display_timing`, attached a unique present ID and exact desired
physical timestamp, and polled both the command-ring fence and past-present
records without a Vulkan wait. The host submission waits on LSFG's exported
sync FD entirely on-GPU; therefore the first successful host-fence observation
is a conservative CPU-observed upper bound for completion of LSFG plus the
presentation blit.

The final attended Thor run passed 1/1 in 3.750 seconds:

```text
requested physical present: 127692181341288 ns
completion deadline:        127692179341288 ns
GPU completion observed:    127692155629777 ns
completion margin:          23.711511 ms
actual physical present:    127692188491495 ns
target error:               +7.150207 ms
reported refresh duration:  8.337742 ms
```

The matching present ID was `1`. Qualcomm returned its timing record after
four bounded evidence-only successor presents retired the FIFO. That flush is
part of the disposable test harness, not a product scheduling mechanism.

After the fence completed, an explicitly evidence-only CPU readback hashed the
two input AHBs and generated output:

```text
left endpoint hash:   14290466770950409080
right endpoint hash:   4013645300055462474
generated hash:       10527994926776730623
moving-object centroid X: 0.48616173
```

The live generation/presentation path performed no CPU readback, blocking
fence wait, queue/device idle, MediaProjection capture, overlay service, or
separate LSFG application. The test also rejected an invalid phase, expired
deadline, second request while the evidence slot was pending, and detached
surface. A deadline miss after LSFG submission additionally quarantined the
entire context until teardown. This is necessary because closing an exported
sync FD does not cancel the GPU write and this context pins one shared output
AHB; immediate reuse would race stale work.

Exact r2 APKs:

- ARM64 target SHA-256
  `d0aa637d15f4bf3abfdaedc6cfa79b0e171ee8b41e6489497885ab4c86e85c53`.
- Instrumentation SHA-256
  `95846138262665b5682bbafbd63c7bc3baf1fd6d0fdcd92afdc59bbefd08f022`.

Machine-readable evidence is in
`experiments/lsfg-vulkan-android-inprocess/evidence/thor-owned-surface-midpoint-r2.json`.
The incremental patch is
`experiments/lsfg-vulkan-android-inprocess/patches/0003-display-timing-content-evidence.patch`
(SHA-256 `30b08a0fecae7cd6e98920d7d97b1a1c6cb29da42794004c593a54470b58d93a`).

This is a bounded feasibility-core pass. It is still **not** a gameplay or
product-routing pass: steady-state backpressure, the full failure matrix,
SurfaceFlinger layer joining, and per-rate visual/cadence qualification remain.

## Three-slot multirate feasibility probe r6

The next bounded arm replaced unsafe reuse of one pinned output AHB with three
fully independent endpoint/output/context slots. Each context is prewarmed
during setup and then reused only after the host submission fence reports
success through `vkGetFenceStatus`. The live sequence uses no blocking fence
wait or queue/device idle. Setup-only sync-FD waits and teardown-only queue
drains are explicitly separated from the live path.

An initial r3 run correctly stopped: the timing collector paused while five
successor presents retired Qualcomm's limited result history, and an
un-prewarmed first context could miss one scan. That evidence remains in
`thor-owned-surface-midpoint-stress-r3-stop.json`. The final collector drains
new timing records throughout retirement, uses a two-millisecond completion
cutoff, prewarms all three contexts, and checks consecutive physical latch
intervals rather than average FPS.

The attended r6 Thor run passed 1/1 in 7.113 seconds:

| Fixed 2× path | Generated requests | GPU deadline misses | Physical records | Required scan gap | Observed gap | Spacing violations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20→40 | 20 | 0 | 20 | 6 scans | 6–6 | 0 |
| 30→60 | 30 | 0 | 30 | 4 scans | 4–4 | 0 |
| 60→120 | 60 | 0 | 60 | 2 scans | 2–2 | 0 |

Across 110 generated requests there were zero busy slots, submit errors,
present errors, missing timing records, target misses, retirement-fence
timeouts, or catch-up/spacing violations. The smallest observed live
completion margin was 1.522817 ms before the already conservative
two-millisecond pre-scan cutoff. The one-shot deterministic output hashes and
midpoint centroid also passed again, followed by the surface-loss and
post-submit quarantine checks.

Exact r6 APKs:

- ARM64 target SHA-256
  `00e1fadc385d685dcbd45ff2c395c58ffc0b29e0394e3a7ab573c1ebd5434c07`.
- Instrumentation SHA-256
  `75735eb3647c4a390e1a5a15fbb43d4cf4628f1afdb58dbe53baef029f5dec9d`.

The incremental source patch is
`experiments/lsfg-vulkan-android-inprocess/patches/0004-three-slot-multirate-stress.patch`
(SHA-256 `06aa2786ea6f9e835ff75f05da13e51e4a702cc8df7b5e4ca55eaf946466f2f2`).
Machine-readable evidence is
`experiments/lsfg-vulkan-android-inprocess/evidence/thor-owned-surface-multirate-r6.json`.

This completes the updated goal's bounded **technical feasibility** milestone:
Android ARM64 execution, exact owned endpoints, GPU-resident generated output,
owned WSI presentation, exact fixed midpoint requests, live nonblocking
synchronization, hard deadlines, constant physical generated-subset spacing,
and safe basic fallback are proven. It does not authorize gameplay. The next
phase is common-timing-authority integration and N64 top-screen certification,
starting with Ocarina of Time 20→40.

## Why the public live path is currently a STOP

The pinned Android API exposes `createContextFromAHB`, `presentContext`, and
`waitIdle`. With `generationCount = 1`, its internal phase is exactly 0.5.
Arbitrary requested phases are not exposed.

The current implementation has three disqualifying steady-state behaviors:

1. Context slot reuse calls an infinite fence wait.
2. The Android wrapper uses `vkDeviceWaitIdle` to bridge its producer device
   and LSFG's separate device.
3. Imported/exported semaphores use opaque-FD assumptions instead of Android
   one-shot sync FDs with explicit ownership.

The reference application's WSI path is also not sufficient: it uses a 500 ms
swapchain-acquire timeout and a command-ring helper that may wait. Its CPU
capture/overlay fallback is outside scope.

## Nonblocking proof architecture

The bounded experiment uses three Vulkan ownership domains on the same physical
Adreno device:

```text
EmuFusion producer queue
  writes endpoint AHBs
  signals and exports input-ready SYNC_FD
        ↓
LSFG-owned Vulkan queue
  imports input-ready SYNC_FD as temporary semaphore
  reads two endpoint AHBs, writes midpoint output AHB
  signals exportable output-ready semaphore
  exports output-ready SYNC_FD
        ↓
EmuFusion presentation queue
  imports output-ready SYNC_FD as temporary semaphore
  acquires output AHB, GPU-blits into owned swapchain image
  presents at the exact requested physical midpoint deadline
```

All CPU-side resource acquisition is try/nonblocking. A busy fence slot,
unavailable swapchain image, invalid FD, missed deadline, endpoint mismatch, or
driver error rejects that generated frame. The real endpoint remains the only
authorized fallback; no stale midpoint is presented.

`vkDeviceWaitIdle` is allowed only after requests are stopped during teardown.

## Acceptance ledger for the next run

The next physical experiment cannot pass without one record per request that
binds:

- session and presentation epoch;
- adjacent endpoint IDs and immutable endpoint timestamps;
- endpoint AHardwareBuffer identities;
- desired presentation timestamp;
- exact phase 0.5;
- input sync-FD import success;
- LSFG submission and nonblocking slot index;
- output sync-FD export/import success;
- GPU begin/end timestamps;
- swapchain image and successful present ID;
- requested deadline and completion margin;
- content signature proving the output belongs to that exact endpoint pair;
- explicit rejection reason for every non-presented request.

At least these failure injections must return direct safely: occupied LSFG
slot, delayed input fence, invalid input FD, output export failure, swapchain
not ready, missed deadline, surface loss, and endpoint-epoch change.

Only after that ledger and attended physical output pass may the work advance
to N64 gameplay certification for the exact fixed-2× paths 20→40, 30→60, and
60→120.

## Public sources

- [Official Lossless Scaling Steam page](https://store.steampowered.com/app/993090/Lossless_Scaling/)
- [`lsfg-vk-android` exact public commit](https://github.com/FrankBarretta/lsfg-vk-android/tree/3e89e5439a98f55d5acb003d20039426ab24e69c)
- [`lsfg-vk-android` public API](https://github.com/FrankBarretta/lsfg-vk-android/blob/3e89e5439a98f55d5acb003d20039426ab24e69c/framegen/public/lsfg_3_1.hpp)
- [Reference Android application](https://github.com/FrankBarretta/LSFG-Android-Application)
- [Original `lsfg-vk` project](https://github.com/PancakeTAS/lsfg-vk)

The official product page describes Lossless Scaling as a Windows/DX11
product and Linux support as community-driven. No official Android developer
SDK or redistribution permission was found. Therefore the personal
owner-supplied asset path and any publicly redistributable EmuFusion backend
remain separate decisions.
