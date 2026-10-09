# EmuFusion direct-cadence normalization plan

Status: host implementation and fail-closed QA are complete; physical Thor
evidence is still required before calling any system judder-free.

## Product rule

Frame generation Off does not fabricate frames. EmuFusion may make only a
small clock correction (at most 0.75%) from a console's NTSC-family clock to an
exact panel divisor, and resamples PCM by the inverse ratio so audio duration
and pitch remain synchronized. A game that is actually running below its
target is a performance failure; the cadence layer must not relabel it or hide
it by dropping frames.

The Thor evidence collected by this project exposes 60.000004 and 120.00001 Hz
top-panel modes to Android. It does not expose a 100 Hz mode. Therefore:

| Corrected source clock | Panel mode | Physical hold |
|---:|---:|---:|
| 60 | 60 | 1 scan per core frame |
| 40 | 120 | 3 scans per core frame |
| 30 | 60 | 2 scans per core frame |
| 24 | 120 | 5 scans per core frame |
| 20 | 60 | 3 scans per core frame |
| 15 | 60 | 4 scans per core frame |
| 12 | 60 | 5 scans per core frame |
| 10 | 60 | 6 scans per core frame |

The panel holding one submitted buffer for two or more scans is equivalent to
submitting duplicate frames, without redundant CPU/GPU work. A 30 Hz game on a
60 Hz panel is therefore the exact two-scan schedule the user requested.

Genuine 50/25 Hz content is deliberately not accelerated to 60/30: that would
alter game speed by 20%. It needs a physically verified 100 Hz panel mode or an
explicit interpolation/resampling mode. On a panel that exposes only 60/120,
authentic speed plus strict Off plus perfectly uniform cadence cannot all be
true simultaneously. EmuFusion must report that limitation rather than claim a
smooth average.

## Exact fixed-clock corrections

The current automatic corrections include:

| Family | Declared clock | Corrected clock | Speed correction |
|---|---:|---:|---:|
| NTSC NES/SNES | 60.0988 | 60 | -0.1644% |
| GB/GBC/GBA | 59.7275 | 60 | +0.4562% |
| related handheld clock | 59.8261 | 60 | +0.2907% |
| Mega Drive family | 59.9227 | 60 | +0.1290% |
| 29.97 family | 29.97 | 30 | +0.1001% |
| 23.976 family | 23.976 | 24 | +0.1001% |
| 20.03 family | 20.03 | 20 | -0.1498% |

The policy is driven by each loaded core's `retro_system_av_info`, so it also
applies to internally hosted systems that are not in a hardcoded system list.
Both software and GLES/Vulkan libretro hosts call the same policy and native
PCM-ratio correction.

Some 20/30 Hz games run inside a 60 Hz console/core callback clock. In that
case the core already repeats unchanged console frames on its fixed 60 Hz
timeline. EmuFusion synchronizes the console clock, not pixel uniqueness; it
must not run the whole console at 20/30 Hz.

## Eliminated periodic-stall source

The old software path allocated a full Java video byte array, a native staging
allocation, a `VideoFrame`, rectangles, and paints every callback. Retained
GBA/SNES evidence contained 30–40 ms stop-the-world collection stalls.

The revised path has three reusable, explicitly leased video buffers. JNI
copies directly into the leased array with no native staging allocation.
Mailbox replacement, catch-up coalescing, rendering, and shutdown each return
ownership exactly once. Geometry changes may allocate each slot once; rolling
telemetry reports cumulative `videoBufferAllocations` and
`videoPoolExhaustions`, and physical QA requires allocations no greater than
three after warm-up and zero exhaustion.

## Off-device proof completed

- Ten-minute deterministic scan simulations cover 60.0988, 59.7275, 59.8261,
  59.9227, 40, 29.97, 24, 23.976, 20.03, 15, 12, and 10 Hz. Every accepted
  clock has one constant integer scan hold and zero accumulated drift.
- Native mock-core PCM tests execute the exact SNES 60.0988→60 and GBA
  59.7275→60 ratios. From 700 input frames the established sink receives the
  expected 701 and 696 frames respectively.
- Replacement/close concurrency tests prove pooled mailbox ownership is
  returned exactly once.
- Android production Java compilation, the JNI export/header contract, the
  complete native host suite, and ASan/UBSan pass.

## Required physical proof after the Thor is connected

For every built-in system, run at least one moving title for at least 60 seconds
after warm-up. Systems with materially different game clocks require one title
per clock class (for example N64 20/30/60). Capture the exact gameplay layer's
SurfaceFlinger latency timestamps and the same-PID EmuFusion log.

Run `unified-android/tools/verify_direct_cadence_evidence.py` for fixed-clock
libretro cases. A pass requires all of the following in the same session:

1. declared clock, corrected clock, and selected panel are an integer ratio;
2. at least twelve consecutive five-second engine windows within 0.75%;
3. direct presents match the corrected clock with no busy drop or failure;
4. audio playback head advances with zero drops, write errors, drain-bound
   hits, or post-warm-up underruns;
5. the three-buffer pool never exhausts;
6. at least 600 actual SurfaceFlinger rows have one interval length within the
   panel tolerance—one long or short hold fails even if average FPS is perfect.

Native adapters (Switch, Wii U, PS3) own their guest clocks and cannot be
safely retimed by the generic libretro host. Their physical QA must first prove
the engine's own limiter and compositor cadence. Any failing adapter needs an
engine-specific clock-control implementation; it must not inherit a fictional
generic PASS.

The physical result, not these host simulations, decides whether SNES, GBA, or
any other system is actually judder-free on the Thor.
