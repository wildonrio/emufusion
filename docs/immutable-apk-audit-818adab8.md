# Immutable APK audit: 818adab8 N64 candidate

Candidate:

`unified-android/build/lucent-3.2.15-phase2-qualification-818adab89aae3de36be46e334c33a63f8257c872cc5791cf1d1176883939bcae.apk`

Exact SHA-256:

`818adab89aae3de36be46e334c33a63f8257c872cc5791cf1d1176883939bcae`

## Static delta from 00616f89

Ignoring JAR-v1 signature files, only these APK members differ:

- `lib/arm64-v8a/liblucent_libretro_host.so`
- `lib/arm64-v8a/liblucent_vulkan_host.so`
- `assets/emufusion-theme.zip`

Every decompressed file inside the theme archive is byte-identical. Its outer
ZIP bytes changed only because the APK rebuild regenerated archive metadata.

The ARM64 symbol tables narrow the native host delta to the intended functions:

- GLES host: `set_hardware_render`, `lucent_android_gles_create`, and
  `lucent_android_gles_attach`
- Vulkan host: shared `set_hardware_render` diagnostics only

No exported symbol set or unrelated function size changed. The GLES changes
advertise `LUCENT_RETRO_HW_CACHE_CONTEXT`, preserve all existing capability
checks, report the exact reason for rejection, report accepted context and
request fields, and report context reset only after EGL attach/current-context
setup succeeds. The native host test covers both rejection without the
required capabilities and acceptance with GLES3/depth/cache-context.

The complete native host suite and its ASan/UBSan repetition pass, including:

- requested depth/stencil/cache/debug rejection when unavailable
- GLES3 cache-context acceptance
- framebuffer/proc-address callback replacement
- context reset, frame, context loss, recovery, and destroy ordering
- Android EGL attach, present, loss, recovery, and detach

## Frozen payloads retained

- `classes.dex` is byte-identical to 00616f89:
  `c5088cf40b6d438fb1a813b28d76ddf5e62d68cf8d279fdb55921c5acdf39e2a`
- ARM64 frontend is byte-identical:
  `ba6033bb262eb7687a3b6ba44cb9e37e238e57c42b992245e5e20a5d3b652d7a`
- The frontend's locked no-teardown replacement remains exact at `0x75fd8`:
  `600640f93b3f0094601240f979170094fd7b41a9f30742f8c0035fd6`
- `theme.qml` remains
  `8578d2c16f750913c2af0edc7bc81f9bd7885a6a9222b178821a2ca8a365538a`
- `theme.cfg` remains
  `555b32df5f07153d34e0e40addd3d70068768cb684aaccf1793e5f7a75f4350b`
- Mupen64Plus-Next remains
  `fa0a07bb3d07cf61ae140099b6a90e6610a647e44d8e15d8d930ab18aa8c36a2`
- BlastEm remains
  `1f2d4bc8878536d0f3a3783a61d7d73afca2c5797d85cc18f2f85b02ab351422`

Mupen retains four 16 KiB-aligned load segments and has no unresolved
`std::__ndk1`/`basic_stringstream` imports. One-app, Phase 1 payload, Phase 2
payload, and N64 ABI static verifiers pass.

## Runtime gate

Runtime evidence must pass
`unified-android/tools/verify_n64_hw_runtime_evidence.py` and the complete
visible/gameplay/return contract in `docs/n64-hw-render-failure-00616f89.md`.
Static acceptance does not qualify N64 by itself.

### r1 and r2 findings

The r1 run proved the N64 hardware fix: GLES3/cache-context negotiation,
context reset, visible moving N64 output, physical input, approximately 60 fps,
and sustained audio all worked. Its reported telemetry failure was a QA-parser
false negative because the real-menu route emits `Health`, not the older
qualification-only `Runtime telemetry` marker.

The corrected r2 harness then exposed a separate held-Stop race. EmuFusion restored
the library in 2 ms, but `detachViews()` abandoned the TextureView Surface while
a scheduled render-thread frame was still inside EGL swap. The swap returned
`EGL_BAD_SURFACE` (`0x300d`), the renderer error callback cleared `prepared`, and
the background save then failed `engine state vault is not ready`. The visible
return is fast and exact, but r2 is correctly a product failure because the
session was not protected.

The lifecycle ordering responsible is:

1. `InWindowGameHost.exitToLibrary()` clears `session` and removes the game view.
2. Surface destruction can no longer call `session.detachSurface()` because the
   field is already null.
3. Only after the UI return does `PpssppGlesEngineSession.stop()` asynchronously
   post `renderLoop.pause()`.
4. A previously scheduled frame can therefore swap against the abandoned
   BufferQueue before the pause reaches the render executor.
5. The renderer error callback clears `prepared` before `saveQuickResume(true)`.

A conforming fix must quiesce GPU scheduling before the game Surface can be
abandoned while still returning the existing library immediately. One viable
design is to keep the gameplay Surface attached but visually behind/transparent
and non-interactive during background serialization, then detach it on the
render executor and remove the view only after the atomic checkpoint commits.
Another is a bounded render-thread pause barrier before the UI detach, provided
the measured visible return remains under the latency gate. Merely ignoring
`EGL_BAD_SURFACE`, suppressing the renderer error, or allowing Stop without a
new verified snapshot does not pass.

The next APK must pass
`unified-android/tools/verify_n64_stop_race_evidence.py`: exactly one held-Stop,
one same-window return at no more than 50 ms, a post-return Quick Resume commit,
successful retirement, and zero abandoned-BufferQueue, `0x300d`, no-current-GL,
renderer/session-error, or save-failure markers. Runtime QA must additionally
relaunch the title and prove that the new snapshot restores.
