# EmuFusion frame generation — HANDOVER F (2026-08-20 ~10:25, top-screen cadence STOP)

Read this before changing or installing anything. It supersedes handover E for
the current frame-generation investigation, but E still contains the broader
system scoreboard and build instructions.

## User priority and goal

The top panel is the product priority. The lower DS/3DS panel is best-effort and
must not delay or gate a correct top-screen result. The user directly observed
ALBW reporting `50/<43-49>` while looking severely choppy. Never qualify or
describe this as smooth.

The intended policy remains: lock the highest sustainable **real source** tier;
never demote a proven 50/60 source merely to make panel arithmetic convenient;
never label a target as delivered output; generated output is capped at 2x.

## Device state at handoff

- Thor serial: `427c87b2`
- adb: `/Users/tyleryoung/.codex/tools/android-platform-tools/adb`
- Restored installed APK SHA-256:
  `d71792d64c470873cf39bd36ffce5cd02311994b7bfb58753f04805a972e4cac`
- Installed package hash was re-read from `/data/app/.../base.apk` and matches.
- App was relaunched to the library after restore; it is not left in a game.
- `emufusion_framegen_proof=null`
- `emufusion_framegen_dense_pyramid=1`
- `emufusion_framegen_dense_v28_160=1`
- Do not delete the two dense settings.

## Exact physical top-screen failure

The old/full installed APK was tested in live ALBW gameplay while panning:

- gameplay SurfaceFlinger layer: main `SurfaceView...(BLAST)#200`
- real latched cadence: **45.2648 Hz** over 2.7836 s
- a separate retained layer `#196` latched at 119.435 Hz but was not gameplay
- overlay/log: `Frame rate committed 50 / 43`, then 46, 44, 40, 49, etc.;
  target remained 100
- primary HEALTH showed producer samples repeatedly near 50–62 Hz while the
  locked tier stayed 50 and actual visible delivery remained ~40–49 Hz

This proves a real presentation scheduler failure, not subjective judder and
not merely a dishonest counter.

## New working-tree scheduler also physically rejected

The current working tree contains a much newer retained-endpoint FIFO scheduler.
It passes host tests but is **not safe to ship**. A Phase-2-only diagnostic APK
was built from it, installed briefly, tested in the same ALBW save, then removed.

Diagnostic artifact (keep only for forensic comparison):

`unified-android/build/lucent-3.2.16-phase2-qualification-d34bb8adc96e831ea0a43b7b5b62d376d41b333926bdaf2cc3464eae6ad3687c.apk`

Physical result during a 10 s right-stick pan:

- actual gameplay layer `SurfaceView...(BLAST)#269`: **40.4607 Hz**
- unrelated retained layer `#254`: 119.5544 Hz
- overlay initially `50/52`, then primary fell `50 -> 40 -> 30`
- primary producer evidence was approximately 58–64 Hz, yet the controller
  demoted to locked30/output60
- actual committed values remained about 31–47 Hz
- secondary generator entered an invalid state: source around 102/207,
  `presents=0`, rapidly increasing epochs/underruns, repeated `Presentation stalled`

Reject this implementation. Host tests alone did not reveal the physical fault.

Current unsafe WIP hashes:

- `AdaptiveFrameRateController.java` `ddcbbee4a3278d0aa152d30f4b23ef9537a8a16bbb79158ffa51662f66213674`
- `EndpointFrameSelector.java` `6d1d719dc0e6f73cda36dbcf4ebbdcfa8529ff26c2dda7b8f2ab055420985ea9`
- `DisplayFrameGenerator.java` `9119fcf08471450f4f76e8b5e65d53796ef66092382eb37cdd8b67f289620697`
- controller test `4fc8ca988c57a8a01220039035b454e64d7d9f67146823a04711cafb62744290`
- endpoint-selector test `edbdc36f8e3d462e7684c14dd12321f88b36a3be95903876cf5face8fcc6815d`

Do not merely adjust thresholds around this WIP. First explain and eliminate the
source-tier collapse and invalid secondary rate/epoch storm with a deterministic
production-order replay, then retest physically.

## Correct cadence constraints on this Thor

The device itself is authoritative. `dumpsys display` exposes only these top
panel modes: 60.000004 and 120.00001 Hz; active mode was 120.00001. It does not
expose 40/80/100 modes or VRR. Internet reports are contradictory: some owners
infer 80/100 from AYN's FPS gauge, while other reports say only 60/120. Do not
trust the gauge over `dumpsys` and SurfaceFlinger fences.

Consequences on fixed 120 Hz:

- 60 -> 120 is exact and ideal (one generated midpoint per real interval).
- 30 -> 60 is exact; 20 -> 40 is exact.
- 40 -> 80 uses a 2-of-3 scan cadence and is not uniformly spaced.
- 50 -> 100 uses a 5-of-6 cadence, necessarily mixing 8.33 and 16.67 ms
  intervals. No scheduler can make that uniform on fixed 120 without either an
  exact 100/VRR mode, changing game speed, or exceeding the 2x cap to resample
  all the way to 120.
- Never demote a real 50 source to 40 merely for divisibility; that throws away
  genuine frames. Keep source detection and output/panel policy separate.
- ALBW's observed producer was near 60, so the immediate target is stable
  60-real -> 120-presented, not 50/100 and certainly not 30/60.

## Lower-screen finding (deprioritized but cheap fix retained)

The earlier 3DS QA failure selected the wrong lower compositor layer. Live ALBW
proved:

- hashed PreviewActivity child: zero latency rows
- plain PreviewActivity parent: zero rows
- non-BLAST SurfaceView: zero rows
- `SurfaceView[...PreviewActivity](BLAST)`: 127 real rows

`secondary_gameplay_layers()` now always selects the strict BLAST SurfaceView,
for both DS and rotated 3DS. Added regression covers the exact four-layer list.

Hashes after this narrow harness-only fix:

- runner `c4a92847515ed1dcfb29fe44749e90fd550981bf05f07082768120efd1c1553f`
- runtime tests `1738380ba29ff6f0892abe0851248326f2f42e4b7583f3858e9c8c974dafb786`

Tests passed: 226 runtime tests; combined Android frame-generation/runtime suite
379 tests; `unified-android/test.sh` all 23 components.

## Full-build integrity blocker

A full Phase-2+Phase-3 build compiles/signs but correctly fails
`verify_phase3_apk.py`:

`Packaged cemu adapter source differs from the source lock`

Do not update the lock blindly. Current untracked adapter source SHA is
`b976b658...`, while the lock records `5e569661...`; the staged Cemu binary is
`ee431573...` and matches the artifact entry. The source changed after that
binary was built, so packaging current source beside the old binary would be a
false provenance claim. Either rebuild the Cemu adapter from the exact current
source and deliberately update/audit the lock, or keep using a Phase-2-only APK
for isolated 3DS diagnostics.

## Next bounded work

1. Freeze top-screen scope. Do not run dual-screen qualification yet.
2. Add a deterministic replay for the exact physical ALBW shape: producer
   evidence 58–64 Hz, 120-Hz callbacks, successful-swap truth. It must hold
   source60 and cannot emit source50/40/30.
3. Find why `EndpointFrameSelector`/FIFO causes physical delivery to fall near
   40 Hz and why the secondary obtains impossible 102/207-Hz source rates.
   Treat each generator independently; never let a 120-Hz presentation callback
   masquerade as unique source cadence.
4. Provide an immediate fail-safe: if generated scheduling cannot sustain at
   least the real source cadence over a short committed-window guard, disable
   generation and present real endpoints directly. Never let frame generation
   reduce 59–60 real input to 40–45 visible output.
5. Build a Phase-2 diagnostic artifact, run ALBW for >=30 s with continuous pan,
   and measure only the actual gameplay BLAST layer. Require source60/output120,
   SurfaceFlinger close to the panel cadence, stable tier, no FIFO coalesces,
   no epoch storm, and overlay equal to successful presents.
6. Only after top passes, optionally re-enable lower-screen qualification.

## Commands / layer measurement

Always quote SurfaceFlinger layer names containing parentheses:

```sh
adb -s 427c87b2 shell "dumpsys SurfaceFlinger --latency 'SurfaceView[...]'"
```

Passing the layer as an unquoted adb-shell argument produces a shell syntax
error at `(BLAST)` and can masquerade as zero evidence.

