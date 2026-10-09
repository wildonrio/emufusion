# EmuFusion physical-presentation timestamp recovery — 2026-08-23

## Scope

This is a narrow physical telemetry checkpoint, not a frame-generation quality
qualification. The AYN Thor top panel was exercised with the schema-58 N64
qualification build solely to verify recovery from finite
`EGL_ANDROID_get_frame_timestamps` history.

## Prior failure

Thor previously stopped exposing physical-present evidence after approximately
800 presentations. Native polling treated every failed historical timestamp
query as fatal (`nativeStatus=-3`), closed the tracker, and permanently removed
truthful `A` telemetry for the remainder of the session.

The Khronos extension permits implementations to retain only finite history.
Querying an expired frame ID reports `EGL_BAD_ACCESS`; that result means the
individual frame's scanout outcome is unknowable, not that the EGL context or
extension is permanently unusable.

## Bounded correction

- Only `EGL_BAD_ACCESS` retires the affected oldest frame as unavailable.
- An unavailable frame is counted as neither presented nor dropped.
- Rolling actual/qualification evidence is cleared and requires a fresh clean
  two-second window.
- Newer pending frame IDs remain queryable.
- All other EGL, surface, context, parameter, timestamp, ordering, and ring
  failures remain fatal/fail-closed.

## Host evidence

- Native address/undefined sanitizer suites: PASS.
- Android Java suite: PASS.
- System/runtime tests: 309 PASS.
- Frame-generation evidence tests: 56 PASS.
- Qualification APK build: PASS.

## Physical evidence

Diagnostic output directory:

`/private/tmp/fzerox-v58-physical-present-recovery-r2`

During the bounded F-Zero run the tracker reached:

- `physicalAvailable=1`
- `physicalPresented=13039`
- `physicalUnavailable=3`
- `physicalDropped=0`
- `physicalSamples=256`
- rolling physical rate approximately `60.00 Hz` in the later direct scene

The former permanent `nativeStatus=-3` shutdown did not recur. This proves
long-run availability and recovery beyond the old 800-present cutoff.

The runner was deliberately interrupted once the telemetry question was
answered because the attract scene had stopped supplying interpolation
endpoints. The run is not a cadence or image-quality pass. The known-safe APK
was then explicitly restored, proof was unset, and the app was force-stopped.

## Remaining blocker

The earlier moving F-Zero proof remains a substantive quality STOP. At 31
proof samples, only about 14% of materially changed cells had any valid moving
direction, even though aggregate cycle, photometric, texture, transport, and
GPU-budget evidence remained healthy. The next algorithm arm must improve
changed-pixel motion ownership without weakening confidence thresholds or
acceptance gates.
