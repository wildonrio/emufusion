# RIFE N64 TWINE r231 timing checkpoint — 2026-08-27

## Scope and verdict

This checkpoint covers only the N64 top-screen TWINE 30→60 RIFE candidate on
the AYN Thor. It is a **physical timing and numeric-content pass**, not final
visual certification and not a product-routing approval.

- Timing verifier: PASS.
- SurfaceFlinger physical cadence: PASS.
- Numeric generated-content evidence: PASS.
- Manual moving-game inspection for ghosting/warping/stalls: still required.
- Ocarina 20→40 and F-Zero X nominal 60→120: still pending certification.
- THS/LSFG written permission: still absent; LSFG remains out of scope for
  product integration until permission is obtained.

The Thor was lit only for the bounded qualification run. Cleanup stopped the
apps and verified both OLED backlights at zero.

## Exact artifacts

- Evidence: `.evidence-rife-twine-r231-structural-phase-retention`
- Qualification APK:
  `unified-android/build/lucent-3.2.16-rife-framegen-qualification-916bab3aec896189fb476b82ec8c1cf05148d9bb081e153443e7c6c058ebd78c.apk`
- APK SHA-256:
  `916bab3aec896189fb476b82ec8c1cf05148d9bb081e153443e7c6c058ebd78c`
- Qualification session: `qa-48ed8f1671d04fa9aeb0c9121f0dddc6`
- Active window: 62.497483 seconds, activation line 2598.

Frozen relevant source hashes at this checkpoint:

- `AdaptiveFrameRateController.java`:
  `4792acaaacdebacfc432df784907730fe8be6060db063814986d2a126244c830`
- `AdaptiveFrameRateControllerTest.java`:
  `b7433781a844b6872ae55242f21e436d7420354358ee2d7ace680eeed11206eb`
- `verify_rife_frame_generation_timing.py`:
  `35bfcd97c574441a7cd06163e42f24d3628f13650b72c4b2cc238a4715962bcd`
- `test_rife_frame_generation_timing.py`:
  `b21abfdc72f5818d54a837087ff5d6a22b6bdb3b7a12371e51d7ba8c66666791`
- `test_systemwide_frame_generation.py`:
  `b8c7ec58942755119ac5bef4d97d44aeb6925ab9dd0334e0ffa6bea19c6ed9f3`
- TWINE harness:
  `12795fbf25165a64ab4680bf1d11f71cd4624b2ce780c512b8a262b603d0c3a2`

## Source-clock correction

r229 and r230 showed the same N64 timing authority being torn down by an
arbitrary anomaly-density boundary: four, then seven exact core-ordinal phase
edges in a 300-period window. The native GLES transport timestamps the core's
60 Hz frame ordinal. The observed TWINE image stream is overwhelmingly 30 Hz,
with exact 16.67/50 ms edges that occur as balanced -½/+½-period phase
corrections.

The retained-clock predicate is now structural:

- acquisition remains strict and unchanged;
- the canonical 30 Hz period must remain the strict mode;
- every correction must be an exact 0.5× or 1.5× edge within a narrow numeric
  tolerance;
- all corrections retain the modal submission ordinal;
- short/long counts may differ by at most one rolling-window boundary edge;
- cumulative phase excursion may never exceed half a source period;
- one-sided stalls, 2× gaps, accumulated full-period displacement, unstable
  clocks, and genuine 29.90 Hz still revoke authority.

This avoids chasing a 1%, 2%, or later percentage threshold while preserving
fail-closed source identity.

## r231 physical evidence

The generated path remained active for the complete 60-second moving-game
window. No `supported=0` transition occurred after activation.

Final timing verifier result:

- source: 30.000 Hz
- target: 59.978 Hz (two measured panel scans)
- actual app-owned physical cadence: 60.005 Hz
- timing samples: 3,828
- physically presented endpoints: 1,921
- physically presented generated frames: 1,907
- generated moving/distinct proofs: 1,907 / 1,907
- generated timestamp phase: exactly 0.5 throughout
- deadline, desired-slot, early, late, and GPU-budget misses: zero
- unsafe pairs, scene-cut risks, endpoint failures, endpoint-equality failures:
  zero
- combined bind/swap p95: 577,135 ns
- combined maximum: 1,388,749 ns
- available deadline budget: 16,672,906 ns

SurfaceFlinger active game layer (`#539`), 127 rows:

- actual cadence: 60.007747 Hz
- actual interval minimum: 16.657188 ms
- actual interval median: 16.664322 ms
- actual interval maximum: 16.670416 ms
- desired cadence: 60.007421 Hz

This is constant two-scan spacing; there are no 8.33/25 ms cadence alternations
in the captured generated layer.

## Verifier closure

The original timing verifier incorrectly required lifetime dropped/unavailable
counters to be zero. Six Direct-mode timestamp-history expirations occurred
before the clean generated epoch and were correctly failed closed/recovered;
their lifetime counters intentionally remain monotonic. The corrected verifier:

- conserves every lifetime submission as presented + pending + dropped +
  unavailable;
- rejects counter regression;
- binds dropped/unavailable baselines to the record before the selected epoch;
- requires zero new failed outcomes in the selected generated epoch;
- treats Choreographer callback count as transport-independent while still
  requiring every SurfaceControl/frame-timeline selection/token/probe/commit
  field to remain zero for app-owned EGL.

The immutable r231 log passes the corrected verifier and remains explicitly
`qualified=false`, blocked by manual moving-video visual inspection.

## Next actions

1. Run a separate bounded human-observed TWINE pan/combat session and record an
   explicit manual pass/fail for ghosting, warping, periodic stalls, and visible
   frame fabrication. Keep OLED exposure bounded and black both panels after.
2. If and only if manual TWINE quality passes, freeze the 30→60 N64 candidate.
3. Certify Ocarina 20→40 with the same physical/manual bar.
4. Certify F-Zero X nominal 60→120.
5. Do not move to later systems or claim the overall goal complete until the
   complete certification order and legal requirements are satisfied.
