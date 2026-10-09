# LSFG common backend contract checkpoint — 2026-08-24

Status: **HOST/ANDROID SOURCE PASS; LSFG GAMEPLAY AND PRODUCT ROUTING REMAIN STOP**.

The bounded Android ARM64 LSFG feasibility milestone is complete in
`LSFG-ANDROID-INPROCESS-FEASIBILITY-2026-08-24.md`. This checkpoint closes the
next product integration prerequisite: an external renderer now receives one
complete immutable request owned by EmuFusion rather than inferring missing
timing state.

## Request boundary

`FrameGenerationPresentationRequest` now carries and validates:

- immutable session and presentation epochs;
- adjacent retained endpoint IDs and source timestamps;
- the exact source-timeline output timestamp and derived phase;
- the intended physical scan timestamp;
- Thor's earlier platform/driver presentation timestamp;
- a hard GPU-completion deadline no later than that platform cutoff;
- generated-image width, height, and exact RGBA8 UNORM format.

The physical scan timestamp is no longer mislabeled as the early platform
timestamp. `DisplayFrameGenerator` constructs the request from the same
`PhysicalPresentationDeadline` used for scheduling. No extra per-frame
contract object was added: only the already-required immutable request is
allocated.

Before submission, the external path verifies the request's generator/session,
presentation epoch, endpoint-pool geometry, format, and unexpired hard
deadline. `ExternalPresentationLedger` derives the evidence epoch from the
request itself and joins native physical timing to the request's early driver
timestamp. `ExternalPresentationEvidence` independently verifies that the raw
driver timestamp plus the proven Thor lead equals the request's physical scan
target.

The quarantined RIFE transport was migrated to the same boundary. It locks the
session identity, permits presentation-epoch changes only after an explicit
timeline reset, validates its AHardwareBuffer geometry/format, and returns
`NOT_READY` rather than submitting after the hard deadline. This does not make
RIFE product-eligible.

## Safety and routing

- Product `Frame Generation: On` still resolves to Direct because LSFG and
  Built-in assessments remain unavailable/unqualified.
- No normal APK, backend selection, UI, device setting, or lower-screen path
  changed.
- No APK was built or installed for this checkpoint.
- The Thor remained asleep.

## Gates

- `unified-android/test.sh`: PASS.
- Focused systemwide + RIFE packaging tests: 66/66 PASS.
- Full Android Java source-set compilation: PASS.
- Conditional RIFE Java source-set compilation: PASS.
- Repository-wide Python discovery: 1373/1376 passed; the three failures are
  pre-existing unrelated ownership issues (theme freeze hash, Cemu patch-lock
  metadata, and external-emulator manifest queries). None touches this
  checkpoint.

## Frozen source identities

- `FrameGenerationPresentationRequest.java`:
  `7d8ea7728ca6402c7d95ff7a35383f200f175d9b134a84893268d9b248d70ad2`
- `ExternalPresentationLedger.java`:
  `61f1595ba04a5641543a22d86c8b269f58b5f16d724a6d53167da1bb6e71bd8e`
- `ExternalPresentationEvidence.java`:
  `2c2fb7ac9a044386ce6f0df3e915b5269245b5db522aae16482c401b058d74e4`
- `ExternalFrameGenerationTransport.java`:
  `088796282f5f5c673248a8ef66daa1f66a7a70ab77b707b64631e6bc8dd430f0`
- `DisplayFrameGenerator.java`:
  `6f921bc2c9b8a0a05acb6382c55f49e3b137b904ff6aa7ff286b41521b6cf3c0`
- `RifePresentationTransport.java`:
  `e35689314e39cc54d54ecbba1db61e229e42c60eee1c91e50c8684867299eb88`

## Next bounded milestone

Implement a top-display-only, shell-gated LSFG qualification transport using
the pinned MIT wrapper plus an EmuFusion-owned Vulkan/AHardwareBuffer WSI host.
It must accept only exact midpoint requests, use the request's hard deadline,
return `NOT_READY` without retry/catch-up, and keep the user-owned proprietary
shader payload outside the APK. Normal automatic routing must remain Direct
until Ocarina 20→40 moving gameplay independently passes the full physical and
visual acceptance standard.
