# LSFG live demonstration attempt — 2026-09-03

Status: **LIVE LSFG GENERATION DEMONSTRATED ON THE THOR (build 101, Ocarina of Time 20→40, badge LSFG, actual 40.0 fps, midpoint advance 0.49-0.51 on 22 motion triples); owner holds preliminary (verbal) THS permission and
needs a functioning demonstration for formal written approval. Product
routing and redistribution remain STOP until that approval exists.**

## What was found on the Thor (build 100, private cache intact)

- `FrameGenerationSettings.Mode.LSFG` only attaches the transport when the
  shell global `emufusion_framegen_proof` is `1`; otherwise
  `GameSurfaceView` logs "LSFG private beta requested without proof mode;
  falling over to the built-in generator". The harness deletes that global
  at every launch and arms it later, so a harness launch can never start an
  LSFG session; arm proof, then relaunch the title from the library.
- With proof armed the native open failed twice and fell to Built-in:
  `EmuFusion-LSFG open failed: SurfaceControl timed-apply worker scheduling
  failed` — the worker's `setpriority(-10)` / `sched_setaffinity(cpu 6)`
  strict check, even though all eight CPUs were online and the app was in
  `top-app`.
- `LsfgPresentationTransport.supportsRatePath` accepted only 20→40, while
  the 2026-09-01 protocol plans 20→60 (×3) for a 20-Hz source, so the
  rate path could never activate; the transport is fixed-midpoint (one
  generated frame per pair).
- `LsfgQualificationTransportFactory` fixed the endpoint geometry at
  320×180 regardless of the game surface.

## Build 101 changes

- `owned_surface_control_presenter.cpp`: priority/affinity failures are
  logged as degraded timing, not a failed open.
- `ExternalFrameGenerationTransport.maxGenerationFactor()` (default 3.0),
  LSFG returns 2.0; `AdaptiveFrameRateController.setMaxGenerationFactor`
  and `UniformFrameRatePlan.select(source, panel, factor)` plan ×2 targets
  for such a backend (20→40, 30→60, 60→120); `DisplayFrameGenerator`
  applies the ceiling when the transport attaches.
- `supportsRatePath` admits 20→40, 30→60, 60→120.
- Endpoint geometry = game surface × shell global
  `emufusion_lsfg_endpoint_scale` (default 0.5), floor 320×180.

## Demonstration procedure

`scratchpad/lsfg_demo.sh <apkNN.path> n64 <label>` (harness launch of
Ocarina of Time, detach, `set_framegen_mode.sh lsfg`, arm proof, Select-hold
to the library, A to relaunch, then logs, badge screenshot, 5-s recording
and the intermediate-frame statistic). Watch for: `LSFG endpoint geometry`,
`External transport generation ceiling`, `External rate-path transition`,
`poll failed` / `cutoff`, and the badge backend `LSFG`.

## Result (build 101, 2026-09-03 08:58)

Ocarina of Time (mupen64plus-next), proof armed, mode LSFG:

- `LSFG endpoint geometry 960x540 (suggested 1920x1080 scale=0.5)`
- `External transport generation ceiling generator=2 backend=LSFG maxGenerationFactor=2.0`
- `External rate-path transition ... candidateSource=20 candidateOutput=40 candidateScans=3 supported=1`
- `Frame rate committed source=19.9 target=40.000 actual=40.006 cadenceQualified=0 backend=LSFG`
- 5-s panel recording: 22 motion triples, middle-frame advance p25/50/75 =
  0.49 / 0.50 / 0.51 (ideal 0.50), 4.5 % on an endpoint, no duplicate steps.

`cadenceQualified` stays 0 because the external path's qualification proof
is the harness's job; the badge reports the backend that actually ran.

Build 102 removes the proof-mode precondition for an explicit LSFG
selection so the demonstration works from the handheld's own settings
without adb.

## Wii U (Cemu) with LSFG: crash (2026-09-03 09:05)

Attaching the LSFG transport to a Cemu session (the engine's output Surface
becomes the 960x540 endpoint ImageReader) crashed the process in
`liblucent_native_adapter_cemu.so` (`VulkanRenderer::~VulkanRenderer` /
`Submit` on `lucent-phase3-r`, SIGSEGV at 0x0) while Cemu recreated its own
Vulkan swapchain for the new surface. Cemu is itself a Vulkan renderer;
LSFG owns a second Vulkan device in the same process. Not needed for the
N64 demonstration; parked. Build 102 was installed afterwards with mode
`lsfg` selected and the proof global cleared.

## Demonstrating from the handheld (build 102 and later)

1. Frame Generation setting (three-way): choose **LSFG** ("private beta").
2. Launch The Legend of Zelda: Ocarina of Time (N64, in-process
   mupen64plus-next). The badge reads `20 fps · direct · LSFG` during the
   60-Hz menus and `20 → 40 · 40.0 fps · LSFG` in gameplay once the
   fixed-midpoint path has primed (about ten seconds after gameplay starts).
3. No adb switch is needed. The transport attaches on the explicit selection;
   capability, deadline and physical-present failures still fall closed to
   Direct per slot, so a badge that stays `direct` is honest.

Known limits: endpoints are 960x540 (shell global
`emufusion_lsfg_endpoint_scale`, 1.0 = full 1080p, untested for deadline
fit); only 20→40, 30→60 and 60→120 are admitted and only 20→40 has been
seen active; Cemu (Wii U) crashes in its own Vulkan swapchain recreate when
LSFG owns the output; GameCube/Dolphin 60→120 is untested.

## Build 103: bounded re-arm after a late slot

`maybeRearmExternalTimingAfterCooldown` (DisplayFrameGenerator): for
compositor-timeline transports (LSFG) a physical-slot miss quarantines
generation for 2 s; with the rate path idle a fresh scheduler epoch then
re-primes exactly as at start-up (no stale endpoint or phase crosses the
boundary). Bounded to 20 re-arms per session, after which the session stays
Direct with a log line. The app-owned (RIFE) recovery path is unchanged.
