# Phase 2 hardware-render host foundation

EmuFusion's independent libretro host now understands the hardware-render
negotiation boundary without enabling hardware cores in the Android product.
This code uses only the MIT-licensed libretro ABI declarations; it does not
embed RetroArch frontend code.

## Implemented native boundary

- `lucent_retro_create()` remains software-only. The existing JNI and every
  Phase 1 core therefore behave exactly as before.
- `lucent_retro_create_with_options()` accepts a versioned, copied capability
  description. Missing, malformed, or partially implemented backends are
  rejected before a core is initialized.
- The host handles `RETRO_ENVIRONMENT_SET_HW_RENDER`,
  `GET_PREFERRED_HW_RENDER`, experimental `GET_HW_RENDER_INTERFACE`, and the
  no-payload `SET_HW_SHARED_CONTEXT` command.
- GLES 2, GLES 3, versioned GLES 3.1+, and Vulkan are the only accepted context
  families. Desktop GL and Direct3D requests fail closed on Android.
- Depth, stencil, cached-context, debug-context, and shared-context requests
  succeed only when the frontend advertises the exact capability. Stencil
  without depth is rejected.
- GLES requires explicit current-framebuffer and procedure-address callbacks.
  Vulkan requires a non-null, versioned Vulkan render-interface base. The
  frontend-owned interface is never modified or freed by the core host.
- A successful negotiation does not imply a live context. Frames cannot run
  until `lucent_retro_hw_context_reset()` is called. After
  `lucent_retro_hw_context_destroy()`, frames fail again until another reset.
- Hardware framebuffer sentinels are counted separately from software video;
  they cannot masquerade as copied RGB frames.

The normal and ASan/UBSan mock suites exercise software preservation, missing
backend rejection, capability mismatches, GLES and Vulkan negotiation,
framebuffer/procedure hooks, Vulkan interface identity, reset/destroy ordering,
unexpected context loss/recovery, duplicate-reset rejection, and hardware-frame
sentinels.

The same production Android backend source is also compiled off-device against
a deterministic fake EGL/ANativeWindow driver. Both the normal and ASan/UBSan
runs prove exact-version probing, capability gating, attach/reset ordering,
wrong-thread rejection, one swap per new frame, no duplicate stale swap,
context-loss recovery, orderly destroy, and balanced native-window ownership.

## Android EGL/GLES foundation

`lucent_android_gles_backend.c` is now an Android-only EGL owner behind a small
native API. It is compiled into the ARM64 host library but is not yet selected
by the production JNI/session path.

- Creation initializes EGL, binds GLES, and proves a usable context on a
  one-pixel pbuffer before advertising any capability. GLES 3.1/3.2 is
  advertised only when exact versioned KHR context creation succeeds.
- Depth and stencil are advertised only after suitable EGL configs are found.
  Cached, debug, and shared contexts remain disabled.
- After a core negotiates GLES, attach selects a matching window config,
  configures and retains the `ANativeWindow`, creates the requested context,
  makes it current, and only then calls the core's `context_reset`.
- The backend presents only when the host records a new
  `RETRO_HW_FRAME_BUFFER_VALID` sequence. A core frame that did not submit a
  hardware framebuffer cannot trigger an old-buffer swap.
- Orderly detach calls `context_destroy` while the context is current, then
  destroys the EGL surface/context and releases the window. Every lifecycle
  operation is render-thread-affine.
- `EGL_CONTEXT_LOST` uses the distinct
  `lucent_retro_hw_context_lost()` transition. It never calls core cleanup
  against dead GL objects; a replacement context must invoke `context_reset`
  before another frame can run.
- The Android NDK build links only platform EGL/GLES/ANativeWindow APIs. Vulkan
  is deliberately not advertised by this backend because EmuFusion still lacks a
  complete Vulkan render interface and swapchain owner.

An opt-in `ExperimentalGlesLibretroHost` JNI wrapper now converts an Android
`Surface` with `ANativeWindow_fromSurface`, exposes attach, run-and-present,
detach, and explicit surface/context recreation, and keeps close fail-closed
when called from the wrong render thread. It is deliberately absent from the
engine catalog and `LibretroEngineSession`; the production `LibretroHost`
constructor still calls the software-only native creation path. Run
`native/verify_android_gles_jni.sh` to compile its Java signatures, rebuild the
Android ARM library, and prove all generated JNI entry points are exported.

The verification gate also runs a qualification-only host-JVM lifecycle probe
through the exact `ExperimentalGlesLibretroHost` public methods with injected
deterministic bindings. It proves create/load, invalid-surface rejection,
attach, resume, run-and-present, hardware-info mapping, pause, surfaced context
loss, explicit recreate, second present, detach, idempotent close, and rejection
after close. The fake `android.view.Surface` used by this test lives only under
`native/tests/java`; it is never included in the Android source or APK. Native
EGL semantics remain covered independently by the normal and sanitizer fake-EGL
suite described above.

`ExperimentalGlesRenderLoop` is the qualification-only integration layer.
It constructs and loads the experimental host on a dedicated daemon render
thread, serializes Android surface attach/recreate/detach with pause/resume,
paces run-and-present at 60 Hz, stops frame submission after context loss, and
resumes only after an explicit surface recreation. Close is synchronously
drained on the render thread, so EGL and core teardown cannot accidentally run
on an Activity/UI thread. It remains unreferenced by the production engine
catalog and `LibretroEngineSession`.

The host-JVM gate drives this loop with a deterministic fake host and proves
that every GLES operation stays on one non-caller thread across create/load,
attach, resume, presentation, context loss, pause, recreate, second
presentation, controller forwarding, AV discovery, PCM draining,
serialize/unserialize, save-RAM transfer, detach, and idempotent close.
Unexpected failures are surfaced
through its qualification listener rather than silently restarting a core.

The isolated PPSSPP qualification package now connects this render loop to the
Lucent-owned `GameSurface` through `PpssppGlesEngineSession`. A separate
`Phase2QualificationCatalog` exposes the factory only when the APK contains the
exact experimental/unshipped registry row, an explicit `autoSelect=false`
opt-in, a matching core artifact hash, and the pinned PPSSPP runtime assets.
The normal build contains none of those qualification assets, and ordinary PSP
metadata retains its external route.

## Android work deliberately still missing

No current production path passes hardware options to the host. The isolated
PPSSPP package covers the GLES surface and input proof, but before any hardware
core can be qualified or selected Android still needs all of the following:

1. Implement the complete libretro Vulkan render interface—not merely its base
   type/version. It must own Android instance/device/queue selection,
   `ANativeWindow` swapchain creation, image acquisition, synchronization,
   layout transitions, presentation, and swapchain recreation.
2. Complete physical-device context lifecycle qualification. The implementation
   and deterministic loss/recovery tests are present, but Android evidence for
   pause, detach, recreation, and activity/process transitions is not.
3. Qualify the implemented PPSSPP PCM, save-RAM, and Quick Resume transports
   with legal content, 100-cycle state tests, process death, and version
   migration; add automatic checkpoint history. Core calls already remain on
   the render thread, and incompatible identity/state failures boot normally
   without replacing the last verified snapshot.
4. Define hardware scaling, rotation, dual-screen routing, frame pacing, and
   color-space behavior. The software `byte[]`/Canvas upload loop must be
   bypassed for GPU frames while audio, input, save RAM, and state handling stay
   shared.
5. Add emulator instrumentation for device GLES context loss/recreation and Vulkan
   swapchain recreation. Physical-device qualification comes later and is not
   part of this foundation.
6. Keep every hardware-rendered registry entry unapproved and unshipped until
   the relevant Android backend, lifecycle tests, licensing review, sustained
   state tests, and visible-output tests all pass.

Until those steps are complete, the qualification route must remain explicit,
unshipped, and unavailable to normal metadata auto-selection.
