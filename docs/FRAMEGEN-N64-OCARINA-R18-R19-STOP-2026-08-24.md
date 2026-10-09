# EmuFusion N64 Ocarina motion qualification — r18/r19 STOP

Date: 2026-08-24  
Device: AYN Thor (`427c87b2`)  
Installed APK SHA-256: `37f55d96de26acde62efe6452896c5f19f04d55e8facb18453621de7c1d9258d`

## Verdict

**STOP.** The dense schema-61 path was genuinely active, but neither controlled
Ocarina motion fixture produced a current, latency-overlapping steady segment.
No output qualified and no threshold was weakened.

The OLED was force-stopped and put to sleep after every attempt. At this
checkpoint `mWakefulness=Asleep`, Thor is not running, proof is absent, and the
two persistent dense switches remain enabled.

## Run accounting

- `r16`: startup-only failure because the device was deliberately asleep and
  the runner had not woken it. No game or product evidence.
- `r17`: invalid setup, aborted. An inherited cleanup deleted the persistent
  dense switches, so telemetry exposed legacy schema22 / `denseEnabled=0`.
  This is not a product result.
- `r18`: valid schema61 run with the dense switches restored. The proposed
  Z-held left/right strafe was not actually bound to a nearby target, reached
  static geometry, and timed out without a steady segment.
- `r19`: valid schema61 run using the exact C-Up plus octagonal left-stick
  pattern that had previously sustained 20→40 on a dialogue-static scene. The
  dialogue was cleared before proof and no proof-time A press was sent. In
  actual scene motion, the timestamp/image grid still became discontinuous and
  timed out without a steady segment.

Preserved evidence:

- `.evidence-product-deadline-r18/`
- `.evidence-product-deadline-r19/`

Both `results.json` files end with:

`timed out capturing latency for a current steady frame-generation segment: no latency-overlapping steady segment`

## Exact r19 diagnosis

The current producer admitted exact 20-Hz stretches, then observed real lower
unique-image intervals. Durable proof summaries repeatedly contained 2× and
noncanonical spans instead of the required all-ordinary grid, for example:

- `count=604 one=595 two=2 other=7 ordinalBad=11`
- `count=600 one=596 two=2 other=2 ordinalBad=4`

The controller therefore behaved fail-closed:

- health 29: epoch395, target40, presents112, promoted57, generated111
- health 30: epoch397, target40, presents98, promoted50, generated97
- health 31 onward: new epochs, direct20, no generated output

The motion proof never became representative (`motionEligibleSamples` reached
only 2), and the proof-evidence epoch kept changing. The old r13 20→40 run was
not counterevidence: its last ten source proofs were perfect only while the
visible scene was effectively dialogue-static, and it failed the content gate.

## Harness change retained

`run_runtime_acceptance_qa.py` now:

1. reaches Ocarina's owned gameplay HUD;
2. traverses out of the house and clears the Saria greeting before proof;
3. rechecks a dialogue-free gameplay HUD;
4. during proof, holds analog C-Up and cycles the exact r13 octagonal left-stick
   path without A/START/menu input;
5. releases both sticks in `finally`.

Host gates after that change:

- runtime runner tests: 258/258 PASS
- unified Android host suite: PASS
- `py_compile`: PASS
- `git diff --check`: PASS

Frozen host hashes at this checkpoint:

- runner: `b2ad686683e54f5972bbb7f61a1422a4ca28f28c47a754cf04441a0bb8807333`
- runtime tests: `6f159b9fcfef2570709c164365c92c82c3409da4471fca5109703338427735f3`

## Device/OLED safety — mandatory

Never leave the OLED on between commands or after a run. Wake it only
immediately before an actively monitored physical test. Every run must use an
EXIT/INT/TERM trap that:

1. deletes only `emufusion_framegen_proof`;
2. force-stops `com.thorium.preview`;
3. sends Android sleep keyevent `223` twice.

Afterward verify `mWakefulness=Asleep`, no Thor PID, and displays OFF.

Do **not** delete these persistent settings:

```text
emufusion_framegen_dense_pyramid=1
emufusion_framegen_dense_v28_160=1
```

Deleting them silently selects legacy v22. This happened once in r17 and was
immediately corrected.

## Next safe work

Do not rerun the same Ocarina fixture and do not loosen clock, motion, cadence,
or content gates. First perform a read-only producer/clock audit to decide how
authentic repeated game ticks are represented by the immutable hardware PTS and
submission ordinal.

The architecture question is whether an ordinal-proven repeated 20-Hz game tick
can be retained as an explicit same-image endpoint on the canonical timeline,
instead of collapsing two source periods into one long adjacent-unique pair.
Any implementation must still satisfy the goal's no-fabricated-callback,
no-extrapolation, adjacent-source-timestamp, successful-physical-presentation,
and maximum-2× contracts. If that identity cannot be proven from the producer,
remain direct rather than inventing it.

Separately, schema61 is already a hard dense-quality STOP in
`docs/FRAMEGEN-N64-V61-STOP-2026-08-23.md`; fixing source scheduling alone does
not make its estimator shippable.
