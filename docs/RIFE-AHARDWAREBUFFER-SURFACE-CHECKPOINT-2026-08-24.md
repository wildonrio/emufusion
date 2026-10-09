# RIFE timestamped AHardwareBuffer → Surface checkpoint (2026-08-24)

## Outcome

The quarantined Android RIFE v4.6 arm now has one physically executed path that combines:

- exact retained `Image` endpoint identity and timestamps;
- producer-fence checks with `SyncFence.await(Duration.ZERO)` only;
- cached `AHardwareBuffer` import into Vulkan (no CPU pixel readback);
- GPU-resident RIFE inference and RGBA8 swapchain conversion;
- zero-timeout swapchain acquisition;
- fence-owned asynchronous Vulkan submission and zero-timeout completion polling;
- direct `vkQueuePresentKHR` presentation to the benchmark `Surface`.

This is a benchmark checkpoint, not product integration or qualification.

## Physical evidence

Single presentation:

- evidence: `experiments/rife-ncnn-vulkan-android/evidence/ahardwarebuffer-surface-2026-08-24/r2/`
- result SHA-256: `0dd071ebc0801b2f446506e77b55c6ec7a82743c0fa5d6b0889a232a3e050cf7`
- status: `PASS`
- one enqueue, one GPU completion, one present;
- two exact AHardwareBuffer cache misses;
- producer readiness succeeded on the first zero-timeout check;
- no CPU readback and no blocking fence wait;
- cold enqueue wall time: `89,648,125 ns` (one-time import/pipeline setup, forbidden in the live presentation interval).

Initial cached sustained run (five warmups plus 120 measured submissions):

- evidence: `experiments/rife-ncnn-vulkan-android/evidence/ahardwarebuffer-surface-2026-08-24/r3-sustained/`
- result SHA-256: `6d3e479cf685edf6230486d9e7f3a74e39b3da8bbd4b2ba873fcc3665614c73e`
- status: `PASS`
- submitted/completed/presented: `125/125/125`;
- cache misses/hits: `2/248` exactly;
- measured enqueue p50/p95/max: `2.760 / 2.933 / 3.479 ms`;
- measured enqueue-through-fence-completion p50/p95/max: `9.470 / 9.680 / 10.196 ms`;
- Vulkan-reported panel period: `8,337,771 ns`;
- all completion checks were zero-timeout polls; the instrumentation driver slept 1 ms between unsuccessful polls, so completion-wall measurements include up to that polling quantization.

The 1 ms polling sleep was then made configurable in the test driver. A
zero-sleep/`Thread.yield()` arm proved that enqueue-through-fence wall time is
still dominated by the FIFO swapchain/panel boundary, not just polling
quantization. The native path therefore gained two Vulkan timestamp queries per
submission. They begin after successful zero-timeout swapchain acquisition and
end after AHardwareBuffer import, RIFE, and swapchain conversion, excluding
acquire/presentation wait. Query results are read only after the existing fence
has signaled; no blocking wait was added.

Exact sustained timestamp results (five warmups plus 120 measured submissions):

| Evidence | Analysis size | GPU work p50 / p95 / max | P95 GPU margin to 8.333 ms | All GPU jobs under one scan |
| --- | ---: | ---: | ---: | ---: |
| `r6-96x54-gpu-timestamps` | 96×54 | 4.714 / 4.728 / 4.774 ms | 3.606 ms | 120/120 |
| `r7-128x72-gpu-timestamps` | 128×72 | 5.573 / 5.596 / 5.610 ms | 2.737 ms | 120/120 |
| `r8-160x90-gpu-timestamps` | 160×90 | 6.028 / 6.056 / 6.108 ms | 2.277 ms | 120/120 |

Because CPU command recording precedes GPU execution, the final gate also
pairs each measured enqueue wall interval with its own GPU timestamp interval:

| Evidence | Analysis size | Paired enqueue+GPU p50 / p95 / max | P95 / max margin to 8.333 ms |
| --- | ---: | ---: | ---: |
| `r9-160x90-combined-deadline` | 160×90 | 8.010 / 8.114 / 8.280 ms | 0.219 / 0.053 ms |
| `r10-128x72-combined-deadline` | 128×72 | 7.465 / 7.554 / 7.752 ms | 0.779 / 0.581 ms |

The 160×90 arm technically fits the isolated benchmark but has no defensible
live-path margin for endpoint export, handler jitter, or compositor handoff. It
is rejected for an initial 60→120 product arm. The unpaired 96×54 measurements
imply substantially more margin, but must still be repeated in the integrated
path; no benchmark result substitutes for moving-game physical evidence.

The OLED was awake only for each short, actively monitored run and was returned to `mWakefulness=Asleep` immediately afterward.

## Honest rate decision

- `20→40`: isolated performance headroom supports a 160×90 analysis arm for the 25 ms output period, subject to integrated real-game quality/cadence proof.
- `30→60`, `40→60`, and `50→60`: isolated performance headroom supports a 160×90 analysis arm for the roughly 16.7 ms output period, subject to integrated proof.
- `60→120`: isolated GPU performance is now provisionally viable. Use a conservative 96×54 first product arm (or 128×72 only if integrated timing proves its remaining overhead fits). The 160×90 arm is not deadline-safe enough for this path.

This is an isolated performance result, **not a qualified rate path**. The
benchmark uses a deterministic static endpoint fixture, not representative
moving N64 gameplay; it does not prove scene-cut handling, visual quality,
SurfaceFlinger cadence, thermal stability, or fallback behavior.

No result here relaxes the uniform-divisor rule, maximum-2× rule, timestamp phase contract, scene-cut/discontinuity rejection, or physical moving-game acceptance standard.

## Source and artifact identity

Source hashes:

- `rife_benchmark_jni.cpp`: `33a3904149b50f20e6e5bac754a44a388ac7b69813f50f9960e73c8fc1b62d1c`
- `NativeRifeBridge.java`: `c995ec0ccf1d5c0cb83d04ef3a58d90be409808176903cbf394f9b76281091d6`
- `RifeBenchmarkInstrumentedTest.java`: `7b88627b3f35c818a6cb6484fa46a925cdcbe0f70a0e87bb2c0f90b7ae501cce`
- `test_surface_transport_gate.py`: `8142e6f454076707c787713cd3b054099b33328ac167ae4261e209ae409ab4a6`
- `CMakeLists.txt`: `10569b3a0100ffb8b0253f8bdd233b1dde145503e0009109a50819a0a26e8ff5`
- `verify_host_artifacts.py` (16 KiB ELF gate): `0bf35431388b00682fa020388a6c5a353881c9d86cb9b96bb0b3a3f0e9a24664`
- `stage_rife_framegen_qualification.py`: `5dbdb91b13bce4b2d814e2883313e3a7e222434c6c5a72477c2a513209ad4706`

Artifacts:

- app APK: `28023bba582782c2eafeb78ffcc5e0bb35dd92b7e7c648ed4cd0dc20a94126df`
- instrumentation APK: `c5d53ce3f7cf37db91f052556a41c2469b276d2e563e504f8d3ee73bf52be8b3`
- host artifact verification record: `d2a3067e159da35e0a3eef27e072b8e2928c3783f4cf62df8afb265bc85774c3`
- qualification APK: `3be85d90c71bc873aa5fd285c8007d79af83144d7cfed13a8391c839103f8070`
- native library: `3b20ca136ac1de0bd58343d00648fd39e09e4695954b74ff7ebd419f785bad94`, GNU Build ID `2bb6c37c7abfb6e68718bd47458b6cf6527a2cae`, minimum `PT_LOAD` alignment 16,384 bytes

Host gates:

- 29 Python source/contract tests: PASS;
- C++ buffer validation test: PASS;
- Java, Android instrumentation, and arm64 native builds: PASS;
- fail-closed APK/upstream artifact verifier: `HOST_STATIC_PASS_DEVICE_UNTESTED` before the physical run, with no model packaged and exact arm64 native/notice/upstream identities.
- full default-off product build after the qualification build: PASS and contains no RIFE library, model, manifest, or Java bridge;
- full `LUCENT_INCLUDE_RIFE_FRAMEGEN=1` product packaging build: PASS, debug-signed and named `rife-framegen-qualification`, with exact models/notices/native manifest and product routing still false.

## Remaining work

1. Move all cold import/pipeline setup to a session-boundary self-test; never perform it in a live presentation callback.
2. Integrate the endpoint-owning contract with EmuFusion's immutable timestamped endpoint queue, not a separate RIFE capture/rate scheduler.
3. First expose defensible N64 top-screen paths behind automatic backend selection and safe direct fallback: 160×90 for lower-rate targets and a conservative 96×54 initial arm for `60→120`.
4. Physically test representative moving N64 gameplay for cadence, SurfaceFlinger agreement, artifacts, scene cuts, underruns, and fallback.
5. Separately prove `60→120` in the integrated path; do not inherit qualification from lower-rate paths or from this static benchmark.
6. Keep `productIntegrationAllowed:false` until product initialization/self-test, failure routing, performance, and physical acceptance are all closed. The exact model may travel only in the separately named notice-complete qualification APK; that is not routing approval.
