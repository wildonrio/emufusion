# EmuFusion strict-Off physical QA — 2026-08-30

Device: Thor dual-OLED handheld, serial `427c87b2`.

Qualification APK (debug-signed, not releasable):

`unified-android/build/lucent-3.2.16-emufusion-plus-lsfg-internal-c81060e513305909355914852629a2d4aca0128b0733df9721d57e71a7a70b83.apk`

SHA-256:
`c81060e513305909355914852629a2d4aca0128b0733df9721d57e71a7a70b83`.
This latest package includes the PS2/PPSSPP AudioTrack corrections and Cemu's
engine-owned FPS telemetry hook. Earlier table rows were captured on exact
predecessor qualification APKs from the same source campaign; corrected rows
below explicitly name the replacement evidence.

The device preference was checked after installation and was exactly
`mode-version=3`, `mode=off`, `enabled=false`. Every strict-Off launch logged
`surfaceIdentity=true rendererCreated=0 liveRenderers=0`. Device tests were run
with the lid closed; after every case EmuFusion was force-stopped, Android was
put to sleep, and both `/sys/class/backlight/*/actual_brightness` values were
verified as zero.

## Sustained direct-presentation evidence

The fail-closed verifier joins the synchronized core clock, twelve consecutive
five-second runtime windows, and 600 monotonically increasing actual-present
timestamps from the exact visible top-panel SurfaceFlinger layer. It rejects a
single long/short hold, mailbox replacement, failed post, pool exhaustion,
audio discontinuity, or non-uniform panel ratio.

| System / title | Core clock | SF mean | 600-present interval range | Result |
|---|---:|---:|---:|---|
| NES / Super Mario Bros. 3 | 60.000 Hz (from 60.099827) | 60.0427 Hz | 16.6483–16.6618 ms | PASS |
| SNES / Super Mario World | 60.000 Hz (from 60.098812) | 60.0209 Hz | 16.6547–16.6673 ms | PASS |
| GB / Link's Awakening | 60.000 Hz (from 59.727501) | 60.0330 Hz | 16.6504–16.6671 ms | PASS |
| GBC / Link's Awakening DX | 60.000 Hz (from 59.727501) | 60.0196 Hz | 16.6540–16.6683 ms | PASS |
| GBA / Metroid Fusion | 60.000 Hz (from 59.727501) | 60.0308 Hz | 16.6515–16.6665 ms | PASS |
| Genesis / Sonic the Hedgehog | 60.000 Hz (from 59.922743) | 60.0251 Hz | 16.6526–16.6697 ms | PASS |
| Game Gear / Sonic the Hedgehog 2 | 60.000 Hz | 60.0361 Hz | 16.6485–16.6624 ms | PASS |

All seven rows had 12/12 clean application windows, zero direct mailbox drops,
zero failed presents, zero audio drops/focus drops/write errors/native-drain
bound hits/underruns, and zero frame-pool exhaustion.

## Direct-path fix proved during this run

BlastEm had been returning a random overscan choice because its core queried
`RETRO_ENVIRONMENT_GET_OVERSCAN` and the host did not initialize the result.
The host now explicitly returns `false` (crop TV-safe overscan). Physical proof:
Genesis changed from a 347x243 inactive-border frame to the active 320x224
picture and a full-height 1440x1080 destination while retaining the sustained
cadence PASS above.

The Java software-frame pool also used exact-size arrays. A PS1 core changing
video mode reallocated all three arrays repeatedly. Buffers now grow to a
bounded reusable power-of-two capacity, retain the exact active byte count,
and native copy accepts a larger destination while copying only active bytes.
Native lifecycle, ASan/UBSan, and the complete Java host suite passed. On the
physical PS1 rerun allocations stayed at three instead of climbing to 17.

## Dual-screen routing

Nintendo DS / Metroid Prime Hunters demo was recaptured from the two physical
display IDs. The top gameplay crop was upright on display 0 and the distinct
bottom crop was upright on display 4. Two five-second windows were 300/300 at
60 Hz with no drop/audio fault. 3DS / A Link Between Worlds likewise produced
distinct upright top and lower images, with the 3D scene on the top display.

These are routing regressions, not sustained 60-second cadence certification
for both surfaces.

## Representative startup/geometry results from the same source line

The following representative physical launches reached visible internal
rendering with strict Off. These are not equivalent to the sustained verifier
above unless explicitly stated:

- N64: F-Zero X, Ocarina of Time, and TWINE launched internally; the visible
  destination was full-height 1440x1080. Runtime callbacks/presents held about
  60 Hz. This does **not** independently prove their 60/20/30 unique-content
  rates.
- GameCube: Mario Kart: Double Dash launched through internal Dolphin.
- Wii: New Super Mario Bros. Wii launched through internal Dolphin after the
  Wii-only Vulkan/identity-transform correction; image was visible and upright.
- Dreamcast: Crazy Taxi launched through internal Flycast, full-height.
- PSP: God of War: Ghost of Sparta launched internally and held about 60 Hz
  without logged drop/underrun.
- PS2: Shadow of the Colossus launched internally, but accumulated seven audio
  underruns during cold cinematic loading. This remains a real caveat.
- Wii U: Super Mario 3D World launched through internal Cemu to a visible
  full-screen image. No sustained native cadence attestation was available.
- Switch: Metroid Dread launched through internal Eden to a visible 1080p
  splash, but emitted Vulkan unsupported-format warnings. This proves startup,
  not full-game compatibility.
- PS3: built-in aPS3e reached the Ico/Shadow selector after the PixelCopy
  first-frame correction. Full gameplay and repeated-title lifecycle remain
  unqualified.

## Honest failures / remaining work

- PS1 / Castlevania: Symphony of the Night deliberately emits repeated/null
  video callbacks during FMV/video-mode transitions. Two windows contained
  only 291 and 277 unique images while the core/audio clock stayed exactly
  60 Hz. Fifteen subsequent gameplay windows were 300/300. Reposting identical
  frames would not add motion; therefore the generic 60-unique-present verifier
  correctly cannot certify the whole boot sequence.
- PS2 cold-load audio underruns remain unresolved.
- Switch sustained gameplay compatibility remains unresolved.
- PS3 full gameplay and same-process repeated launch remain unresolved.
- GameCube F-Zero GX and Mega Man X Collection images are truncated. The SD
  archive checked so far contains no complete recoverable copy. Preflight must
  continue rejecting them rather than trying to boot corrupted data.
- “No judder ever” is not yet proved for every title. The sustained PASS table
  is the empirical scope currently established; lower-rate N64 unique-content
  cadence and native-adapter systems need title-specific content evidence, not
  only callback or SurfaceFlinger averages.

## Bounded remaining-system cadence campaign

The later campaign uses `run_strict_off_cadence_probe.py`. It captures four
untouched SurfaceFlinger latency windows from the exact BLAST gameplay layer.
The physical test is an integer scan-lattice test: a new image may legitimately
remain for two, three, or more panel scans, but every replacement must still
land on an integer 60/120 Hz scan slot. This is the correct test for 30/20/24
fps content and does not pretend that a repeated scan is a newly rendered
game frame.

The engine-side gate uses rolling retired-frame windows. Phase 2's logger is
cumulative from launch, so the probe derives bounded rates from consecutive
`frames / cumulative-average-fps` timestamps; one-time cold-start work no
longer contaminates later gameplay windows. Cumulative audio counters likewise
fail only when they increase during the bounded sample.

| System / title | Declared → synchronized | Rolling engine FPS | Physical result |
|---|---:|---:|---|
| N64 / Ocarina of Time | 60.000 → 60.000 | sustained 60.01–60.39 in the long route run | PASS; 505 one-scan updates |
| Nintendo DS / Portrait of Ruin | 59.826098 → 60.000 | direct hardware clock | PASS; 504 one-scan updates |
| Nintendo 3DS / A Link Between Worlds | 60.000 → 60.000 | 60.02, 60.04, 59.94 | PASS; 505 one-scan updates on the replacement APK |
| PlayStation / Symphony of the Night | 59.817333 → 60.000 | 59.985–60.005 core callback rate | PASS; deliberate duplicate/null callbacks correctly reuse the last scan |
| Dreamcast / Crazy Taxi | 59.945300 → 60.000 | 59.99, 59.99, 59.99 | PASS; 505 one-scan updates |
| GameCube / Metroid Prime | 59.940060 → 60.000 | 59.95, 60.01, 60.03 | PASS using the complete 1,344,307,776-byte CISO |
| Wii / Super Mario Galaxy 2 | 59.940060 → 60.000 | 60.01, 59.96, 60.03 after load | PASS; earlier cold-load sample was not steady gameplay |
| PSP / Ghost of Sparta | 59.940060 → 60.000 | 59.99, 60.01, 60.03 | Late-window visual PASS; six earlier load-transition audio underruns remain |
| PS2 / God of War | 59.940000 → 60.000 | 60.03, 59.92, 60.02 | PASS; zero underruns through 3,600 frames on the corrected APK |
| Switch / Metroid Dread | measured 60.0 on 120 panel | 60.2, 59.9, 60.0, 60.0 | PASS; every replacement on one/two exact 120 Hz slots |
| Wii U / Super Mario 3D World | measured target 60 on 120 panel | 54.3, 59.1, 55.2, 56.1 | FAIL; real guest slowdown and holds up to five scan slots |
| PS3 / Ico & Shadow collection | no guest hook; 120 panel | unavailable | FAIL CLOSED; Surface itself is regular 60→120 but guest speed is unmeasured |

The PS2 audio failure exposed a real source bug: the JIT-stall cushion was
keyed only to the retired `play` id, so current `armsx2` was reduced to the
generic 50 ms steady queue. The source now includes both PS2 ids. PPSSPP's
repeatable approximately-55-second underrun is addressed separately by raising
only its steady queue from 50 to 100 ms. The replacement APK physically proves
the PS2 fix. PPSSPP is clean in the late window, but a six-underrun burst during
an earlier load transition means the entire launch is not an audio PASS.

The corrupt Metroid Prime RVZ is 5,602,836 bytes and correctly fails preflight.
The SD-card archive RVZ is truncated to the same scale. The complete internal
CISO is 1,344,307,776 bytes and passed, establishing that the old GameCube
failure was damaged content rather than Dolphin cadence.

Cemu's existing two-second LattePerformanceMonitor FPS is now preserved by its
Android WindowSystem and exported through the standardized native-adapter hook.
The rebuilt, lock-updated, 16 KiB-aligned Cemu artifact proves that Super Mario
3D World is genuinely retiring only 50.8–59.6 guest frames/sec in this scene;
the final four certification windows are recorded above. The 120 Hz panel is
not the cause and cannot repair uneven source delivery. aPS3e still has no
equivalent engine-owned hook and remains fail-closed. Eden's pre-existing hook
now participates in the same certification rule and passes Metroid Dread.
