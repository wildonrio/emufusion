# EmuFusion N64 schema59 edge-aware neighbor proposal — physical STOP

Date: 2026-08-23  
Device: AYN Thor (`427c87b2`)  
Candidate APK SHA-256: `d575548325bd51d6929a76d393ab205b41928b613d69adb7105c48415f6fba2e`  
Known-safe APK restored after the run: `6d3f874883a9fa9ad7e1fab5edbc66a34ebd6f82ac618db47b8238ccb5473a3f`

## Verdict

**STOP.** The schema59 edge-aware neighbor proposal is fast and its asynchronous evidence transport is healthy, but it does not provide acceptable moving-pixel ownership and it produces conspicuous warped/duplicated image bands in 30→60 N64 gameplay. It must not ship or be described as qualified.

## What schema59 changed

- Contract: `dense-v59-edge-aware-neighbor-rational-max2x-presented`
- Variant: `fragment-v59-edge-aware-neighbor`
- Analysis: 128×72, 40 passes, 47-pixel component reach
- No additional draw pass
- In the two existing reciprocal refinement passes only, a robust four-neighbor median proposal may replace the current vector when:
  - at least three neighbors support it,
  - local target appearance energy is at least 0.55, and
  - the existing joint image/cycle objective improves by the strict configured margin.
- All existing cycle, photometric, texture, spatial, scene-cut, cadence and maximum-2× gates remain unchanged.

## Physical evidence

### F-Zero X was not a valid midpoint test

The measured F-Zero source clock stayed just below half the measured ~120.033 Hz panel clock. Under the goal's strict `D ≤ 2S` and uniform-divisor rules, the controller correctly selected the two-scan ~60 Hz target rather than 120 Hz. The run therefore produced no materially intermediate proof samples and cannot judge schema59 image quality.

Preserved log:

- `/private/tmp/fzerox-v59-edge-neighbor-r1/device-logcat-final.txt`

### 007: The World Is Not Enough, 30→60

The formal runner reached real gameplay and showed `S30.0 T60 A60.0`, but its manifest failed because the one-time proof-enable marker was absent. The same live process was then placed into proof mode directly and driven through bounded physical stick motion. This is diagnostic evidence, not a formal qualification pass.

Final schema59 diagnostic snapshot:

- proof samples / completed atlases: **228 / 228**
- proof cells: **295,488**
- changed cells: **7,770**
- backward valid coverage: **149,608 / 295,488 = 50.631%**
- forward valid coverage: **156,040 / 295,488 = 52.808%**
- changed cells owned by at least one moving-valid direction: **1,718 / 7,770 = 22.111%**
- changed cells owned by both moving-valid directions: **572 / 7,770 = 7.362%**
- motion-eligible proof samples: **9 / 228 = 3.947%**
- substantive synthetic pixels: **782 / 7,770 = 10.064%**
- non-crossfade pixels: **7,315 / 7,770 = 94.144%**
- combined pair max + warp p95: **6,378 µs**, under the unchanged **7,333 µs** gate
- timer unavailable / proof errors / tag errors / pending: **0 / 0 / 0 / 0**

The proposal therefore improved neither the central ownership problem nor visual acceptance. Aggregate flow validity around 50% is misleading: most accepted vectors belong to unchanged image regions, while genuinely changing pixels remain largely unowned.

Preserved artifacts:

- direct diagnostic log: `/private/tmp/twine-v59-edge-neighbor-r1/device-logcat-manual-proof-final.txt`
  - SHA-256 `b64de8aa6885ff4367846578d55a3f28b1b8fc142bf3e83068004e57804a1fc4`
- runner-captured generated frame: `/private/tmp/twine-v59-edge-neighbor-r1/n64-title-01-framegen-visible-primary.png`
  - SHA-256 `c677b6593028ec0620168e52c404565e94e534e0dae8cac0621d06cb42bb330f`
- physical proof screenshots:
  - `/private/tmp/twine-v59-proof56.png`
  - `/private/tmp/twine-v59-orbit.png`

The screenshots visibly contain broad translucent/duplicated vertical bands and warped geometry. Numeric telemetry cannot override that manual visual failure.

## Harness findings kept separate from product quality

- The Ocarina of Time automated bootstrap repeatedly entered the save-name keyboard and never reached its controllable HUD.
- The TWINE formal run produced schema59 health records but lacked the required exactly-once proof-enable marker, so the runner correctly failed before qualification.
- Neither harness defect explains or excuses the manually observed generated-image corruption.

## Safe next step

Do not relax confidence, cycle, content, cadence or visual gates. Do not ship schema59. The next bounded built-in experiment must attack data association itself (for example a stronger chroma/gradient/census-like matching cost or a robust global-camera initializer) while preserving:

- exact timestamp-derived phase,
- adjacent classified endpoint ownership,
- uniform panel-divisor output,
- maximum 2× output,
- unchanged scene-cut/occlusion rejection,
- no blocking readback,
- the 7,333 µs combined deadline,
- and full physical moving-video inspection.

Any next arm must beat this snapshot on **changed-pixel moving ownership**, not merely aggregate valid coverage, and must eliminate the visible banding before formal certification proceeds.
