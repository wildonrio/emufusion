# LSFG top-display qualification selector checkpoint — 2026-08-24

Status: **OWNED VULKAN/AHB/FIFO LIVE SOURCE PASS; THOR SELF-TEST AND GAMEPLAY ROUTING REMAIN STOP**.

The adjusted authoritative goal remains LSFG-first and top-screen-first. This
checkpoint adds only the session-boundary selector needed to attach a future
conditional LSFG transport to the already-frozen common timing contract.

## Behavior

- `emufusion_framegen_lsfg_qualification=1` is a shell-only request, never a
  user preference or product qualification signal.
- Qualification transports are accepted only on Android's default/top display
  and only while the owner's single `Frame Generation: On` preference is on.
- LSFG and RIFE qualification globals are mutually exclusive. Both on, both
  off, a missing reflected factory, or any settings error resolves to the
  normal product selection, which is still Direct at this checkpoint.
- The renderer factory now has one generic external-qualification boundary;
  backend identity remains `LSFG` or `Built-in` for honest overlay reporting.
- No LSFG factory, native library, shader, DLL, or private derived payload is
  packaged by the normal build. The user-owned `Lossless.dll` remains outside
  the repository and APK and was not executed.
- RIFE's existing qualification factory remains compatible through the same
  boundary.

## Gates

- `unified-android/test.sh`: PASS.
- Focused LSFG/RIFE/systemwide Python suite: 70/70 PASS.
- Complete conditional Android Java source-set compilation: PASS.
- Android ARM64 native build against the exact patched MIT wrapper: PASS.
- The EmuFusion-owned host now creates a separate Vulkan device on the exact
  selected GPU, requires one graphics/transfer/present queue, creates a FIFO
  swapchain, requires `VK_GOOGLE_display_timing`, and records the measured
  refresh duration. It uses a per-device function table that cannot be
  clobbered by LSFG's separate internal Volk device.
- All nine fixed RGBA8 AHardwareBuffers are imported using queried Android
  hardware-buffer allocation size, format, and memory-type bits. A bounded
  setup-only command establishes `GENERAL` layout and releases ownership to
  `VK_QUEUE_FAMILY_EXTERNAL` before CPU setup pixels and LSFG prewarm.
- Owned-WSI live source contract: PASS. No CPU window fallback or synchronous
  GPU readback exists. The only Vulkan fence wait is the bounded setup
  transition; live copy/generate/present uses zero-timeout status/sync-FD
  polling and never calls device-idle.
- The native checkpoint allocates nine fixed AHardwareBuffers, creates three
  LSFG contexts, and setup-prewarms them through the nonblocking sync-FD API.
  The live host now imports the exact retained Java endpoint AHBs, GPU-copies
  them into a retired fixed slot, exports the LSFG input fence, retains and
  zero-polls the output fence, and submits no presentation unless completion
  is proven before the immutable cutoff. It then blits through the owned FIFO
  swapchain with a unique `VK_GOOGLE_display_timing` ID.
- Each slot retains a persistently mapped 48x81 RGBA8 proof staging allocation.
  A GPU-only three-tile downsample/copy is read only after that slot's fence is
  signaled; the CPU analysis produces the common 48x27 endpoint/output content
  record without synchronously stalling presentation.
- A bounded session-opening self-test is source-complete. It requires exact
  endpoint passthrough, a distinct LSFG midpoint, pre-deadline completion,
  conservative pair safety, and two matching physical-latch timestamps before
  `selfTestPassed` may be true. It has not yet run on the Thor.
- A debug-signed conditional qualification APK rebuilt successfully with the
  LSFG-specific notice gate active:
  `lucent-3.2.16-lsfg-framegen-qualification-5c9ec0aa01fa0f246d017f2e7755083a2508df83d4c6a0c33834beb14b73e4ee.apk`.
  Its SHA-256 is
  `5c9ec0aa01fa0f246d017f2e7755083a2508df83d4c6a0c33834beb14b73e4ee`.
- The Java endpoint handoff now retains each exact `HardwareBuffer` and, on
  Android 13 or newer, zero-polls the source `SyncFence` before native
  submission. An unsignaled acquire fence returns `NOT_READY`; it is never
  converted into a blocking wait.
- APK inspection found exactly one
  `lib/arm64-v8a/liblucent_lsfg_qualification.so`, both DEX files, and all four
  conditional LSFG classes. It found zero `Lossless.dll`, `.spv`, private
  LSFG-manifest, or other user-owned payload entries.
- The APK was not installed and the Thor was not woken.

## Frozen identities

- `ExternalFrameGenerationTransportLoader.java`:
  `7ce08f7e275a23de1f241f8ebb368e258a9432b0360fa969b8bb96ac8d61d38d`
- `FrameGenerationSettings.java`:
  `1392428d5c56b59498d45854c7ca46eb6e69b1326b0ed68cae197ea43eac54d2`
- `FrameGenerationRendererFactory.java`:
  `5d0c076730f6a80fed8a2627af4ddc1116e69cf7035e0cbc89669725fd9c6e06`
- `GameSurfaceView.java`:
  `d8bc8492f64b79e78aa5a0b988ba79465f47ebcb414ae16670d5bc20fac33c4e`
- LSFG structural test:
  `987fdd2ccd68b409af8053b76cafd19684f21bc9f26c5b33217a02fa2b0032d0`
- `NativeLsfgBridge.java`:
  `d753bfadb3eb99dc0306aa70277970ec122ddb924da351c1582193cda62879bf`
- `LsfgQualificationRuntime.java`:
  `1b21918a1e2edf09cc3c4dd0913a462f5d8e48aa696cd7456a21a957da2d2d13`
- `LsfgQualificationTransportFactory.java`:
  `9ef90da274935b073b75946c1222dd0df7bb1fcc3563fdfc662cee2faceb983f`
- `LsfgPresentationTransport.java`:
  `ee3322a2fa2396b38275a5bb36c5c7f497590454c639c36aaae98c9c3ff804e4`
- Native CMake:
  `a47395ee95d83f1bd0b109f5bfbf385c8b6a97e153b73c6994902edc81e95cff`
- Native prewarm/JNI source:
  `fd83d00e2850bd9843d456ef27dbe3e41fb2be44648843b932318624d085b851`
- Owned Vulkan host header/source:
  `f4892d9e9b93eb8c93c5329b5749c6432a58c47cab1605811191a34578fd151d` /
  `e8c63f0c177b3d4a20a2ac9a3a2eb0d3261ff8e2a16bb5a4276b0cbac723fcdb`.
- Owned WSI setup source verifier:
  `b34e9f42042683097759c0561edd10d7f628a77904fd879822bb848982b97380`.
- Conditional Android build script:
  `a4c170aacf42c18c333940c7382f456c23373f0e9234a3972f6fde2fee1473cc`
- Patched-wrapper checkout verifier:
  `a57258528d80b8b535affdb2a017f70b0d249a762463f353ecd6979bd6009454`

## Next bounded checkpoint

Run exactly one bounded qualification session on the Thor and preserve its
native capability/self-test record, Vulkan timing rows, physical display
timings, and logcat failure if any. Do not enter gameplay unless the complete
session-opening self-test passes. Return the OLED to black immediately after
the bounded run. A self-test pass proves only the fundamental Android LSFG
transport; product routing remains Direct until moving Ocarina 20→40 passes
the complete physical and visual standard.
