# RIFE pre-present pair-safety checkpoint — 2026-08-24

Status: **HOST BUILD / PHYSICAL UNQUALIFIED**.

This checkpoint closes the architectural defect where scene-cut evidence was
available only after a generated image had already been presented. It does not
certify RIFE gameplay quality, any N64 rate path, or automatic product routing.

## Implemented contract

- Endpoint retention and interpolation permission are separate. The common
  external-backend default is fail-closed `PENDING`; a backend must explicitly
  complete an exact-pair classifier before returning `READY`.
- Each already-required RIFE presentation command writes a five-tile,
  48x27 RGB proof atlas: current left, current right, current output, the same
  current right, and an optional retained look-ahead endpoint.
- The current-right checksum must match in both atlas positions. The look-ahead
  pair is accepted only with exact adjacent sequence/timestamp/Image ownership.
- The classifier result is immutable and keyed by the right endpoint sequence.
  `PENDING` or `UNSAFE` disables fractional output while preserving exact
  endpoint presentation. A reset changes the transport epoch so stale native
  completion cannot authorize a new endpoint timeline.
- The GPU proof copy shares the presentation command and fence. Polling is
  zero-wait; there is no synchronous readback or blocking fence wait.
- The timing verifier requires `externalContentSceneCutRisk=0` for every
  generated proof and preserves the lifetime, monotonic
  `externalUnsafePairs` count as handled rejection evidence.

## Correctness defect caught during audit

The new two look-ahead checksum accumulators were initially omitted from the
explicit FNV-offset initializer. C++ zero-initialized them, which made the
required current-right checksum equality fail deterministically. All five
accumulators now start at the same FNV offset and a source regression pins that
exact contract.

## Frozen source identities

- `DisplayFrameGenerator.java`: `ed9b7d1364a15774914f0d1bec6ebd5ddc09f221b6ef7485c1597dc65eca3e26`
- `ExternalFrameGenerationTransport.java`: `f9173741fa3bff7cd8a4ffc7de76a9d0aa7b1fa9575f0bbcee288a55ab66cbd4`
- `RifePresentationTransport.java`: `2fe6986b723003ccd42ec36f5dc866a8f86e7cb3ddf34cae8e3cc78a7aa08354`
- `NativeRifeBridge.java`: `029e55b0efcda656ec6f7f91fa35109aeca4bcbebcb9b27e646e5d31e7aea80c`
- `rife_benchmark_jni.cpp`: `885694f82dc95ef6e60be7024314c26d3ef334fb68f333a918e43a1e865df473`
- `NativeRifeBridgeContentProofTest.java`: `bb691c0c066c9e9bc1e12a6b3df1dbe7f834040327f38df1346b0849658b0e92`
- `verify_rife_frame_generation_timing.py`: `a6299c34c41e25df5c80dda84b12cf200cc91260ae6861ae6e71b311243031bd`
- verifier test: `9494279f01a17580767ad4f8d89f7aaa9ee3f16232393aef2a5194f537ba6d74`

## Immutable APKs

- Qualification APK:
  `unified-android/build/lucent-3.2.16-rife-framegen-qualification-e344cf3aaea51f1321a308bde94c14e042a4cdaf0ba3723dfcd9b3c28153396f.apk`
- Default APK:
  `unified-android/build/lucent-3.2.16-08b6faeedaccdfdddd610c562dcb1dd762e7f0a0dcba81bb4eb760efaeda5d69.apk`

The default APK contains no RIFE model, native library, or RIFE class
definition. The qualification APK contains the locked v4.6 model, exact
arm64 native library, notices, manifest, bridge, and qualification transport.

## Host gates

- 73 focused product/packaging/timing/system-wide tests: PASS.
- RIFE Gradle unit tests, including 22-field content-proof mapping: PASS.
- RIFE native Android build: PASS.
- 30 RIFE upstream/transport source gates: PASS.
- Extracted Vulkan proof compute shader: PASS with `glslangValidator -V`.
- `unified-android/test.sh`: PASS.
- Qualification and default APK assembly/signature/payload gates: PASS.

The repository-wide 1,375-test run exposed three unrelated dirty-worktree
failures after the in-scope stale RIFE build-flag expectation was corrected:
theme pin drift, Cemu adapter lock drift, and external-emulator query-manifest
drift. These do not prove or disprove this frame-generation checkpoint and
must not be represented as green.

## Required next evidence

Do not call this path qualified until an attended, moving N64 top-screen run
proves all of the following on Thor:

1. Exact endpoint presentation primes pair classification before any fractional
   output; a deliberate scene transition increments `externalUnsafePairs` and
   produces no generated scene-cut-risk row.
2. RIFE record plus GPU work completes before the selected physical slot under
   moving content, with no queue growth, unavailable rows, or missed slots.
3. SurfaceFlinger timestamps have only the selected integer scan multiple after
   warm-up and agree with successful physical-presentation counters.
4. Moving-video inspection shows no ghosting, doubled geometry, HUD warping,
   disocclusion trails, or destructive blending.
5. The default/built-in path remains separately usable and independently
   qualified; this qualification-only RIFE payload must not be treated as
   automatic product selection.

The Thor OLED must remain asleep during host work. Wake it only for a short,
attended physical run and sleep it immediately afterward.
