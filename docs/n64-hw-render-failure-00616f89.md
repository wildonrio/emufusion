# N64 hardware-render failure — immutable 00616f89 APK

## Finding

The N64 failure is a frontend contract rejection, not a bad ROM, missing GLES
driver, missing Mupen binary, or Activity routing failure.

The real-menu run in
`unified-android/build/runtime-acceptance-00616f89-full-r5-restored`
reaches the live EmuFusion window, loads the exact Mupen64Plus-Next shared object,
and calls `retro_load_game`. Mupen then logs:

> `mupen64plus: libretro frontend doesn't have OpenGL support`

The exception that follows (`core rejected game content`) is a consequence of
that negotiation failure; it is not evidence that the `.z64` file is invalid.

## Exact cause

EmuFusion pins Mupen64Plus-Next commit
[`f275caf4b2bfa1e6d1c51636746ea793f3d80320`](https://github.com/libretro/mupen64plus-libretro-nx/tree/f275caf4b2bfa1e6d1c51636746ea793f3d80320).
In that source, GLideN64's `glsm_state_ctx_init` submits a
`retro_hw_render_callback` with these material fields:

- GLES context (`OPENGLES3` for EmuFusion's pinned build)
- `depth = true`
- `stencil = false`
- `cache_context = true`
- non-null `context_reset` and `context_destroy`

The immutable 00616f89 host's `hardware_request_supported()` rejects any callback having
`cache_context = true` unless the backend advertises
`LUCENT_RETRO_HW_CACHE_CONTEXT`. That APK's Android GLES backend advertises
only the depth/stencil features it probes; it never advertises cache-context
support.
Consequently `RETRO_ENVIRONMENT_SET_HW_RENDER` returns false. Mupen converts
that false result to the exact OpenGL-support error captured in the run.

The upstream libretro header describes `cache_context` as a request that the
frontend go “very far” to avoid resetting the context, while explicitly
allowing reset in extreme situations and recommending cores tolerate reset.
Treating the flag as an all-or-nothing capability and rejecting the hardware
contract is therefore stricter than the API semantics require. EmuFusion may
honor it by preserving EGL state where possible or accept it as advisory while
using the existing `context_destroy`/`context_reset` recovery path. It must not
silently claim preservation it does not implement.

## Fail-closed acceptance contract for the next APK

Static and host tests must prove:

1. The exact packaged Mupen SHA and source pin remain locked.
2. A GLideN64 callback with GLES3, depth, and `cache_context = true` is accepted.
3. Unsupported context APIs, impossible GLES versions, missing proc-address or
   framebuffer callbacks, and unsupported required depth/stencil still reject.
4. The accepted callback receives EmuFusion's `get_current_framebuffer` and
   `get_proc_address` functions.
5. `context_reset` runs only after the requested EGL context is current;
   `context_destroy` runs while it is still current, or context loss is
   explicitly recorded.
6. A hardware video callback using `RETRO_HW_FRAME_BUFFER_VALID` advances a
   nonzero frame sequence and reaches a successful EGL swap. It must never be
   interpreted as a software pixel pointer.

Physical real-menu QA must then pass for at least three N64 titles:

1. Launch by a physical A press from EmuFusion's real N64 list.
2. Preserve the same EmuFusion package, task, Activity, window, and PID.
3. Capture explicit ordered markers for hardware-render acceptance,
   `retro_load_game complete`, context reset, and a nonzero presented frame.
4. Capture changing, recognizably game-specific frames; a black/error/static
   surface, route marker, loaded `.so`, or host overlay is not gameplay proof.
5. Capture sustained video/audio/input health rather than only a boot frame.
6. Hold Stop and return immediately to the exact selected title with no
   preparing/saving/EmuFusion/Pegasus splash and no Activity/surface restart.
7. Confirm quick-resume/save-state persistence on relaunch.

Any occurrence of “libretro frontend doesn't have OpenGL support,” `core
rejected game content`, renderer/session error, absent acceptance/reset/swap
marker, or missing visible gameplay fails the N64 gate. The offline verifier is
`unified-android/tools/verify_n64_hw_runtime_evidence.py`; the current 00616f89
evidence is expected to fail it.
