# N64 built-in frame-generation r27 quality STOP — 2026-08-24

## Verdict

The built-in dense optical-flow backend is **not qualified** for the N64
20→40 path. The physical AYN Thor run proved stable top-panel cadence and met
the GPU deadline, but representative moving output was visibly destructive and
the motion-ownership evidence failed by a wide margin.

This is a content-quality STOP, not a pacing failure. Do not lower confidence,
occlusion, motion, or substantive-output thresholds to turn it into a pass.

## Physical evidence

Authoritative directory:

```text
.evidence-n64-proof-r27/
```

At the final 31-sample schema-61 proof snapshot:

| Signal | Result |
|---|---:|
| Source / target / actual overlay | `S20.0 T40 A40.0` |
| App output window | 120 presents / 3.000 s |
| Panel callbacks | 360 |
| Pair-max + warp-p95 | 6,766 us (< 7,333 us gate) |
| Backward dense valid | 25,478 / 40,176 = 63.416% |
| Forward dense valid | 25,810 / 40,176 = 64.242% |
| Motion-eligible proof samples | 1 / 31 = 3.226% |
| Motion-correlated proof samples | 1 / 31 |
| Substantive pixels | 204 / 1,433 = 14.236% |
| Non-crossfade pixels | 1,326 / 1,433 = 92.533% |
| Atlas/tag errors | 0 / 0 |

The transport and coarse dense-validity counts therefore worked, but they did
not establish trustworthy ownership of moving content. The 18-second capture
shows a large translucent blue smear that bears no valid resemblance to the
intended moving geometry. This is forbidden by the goal's ghosting, doubled
geometry, disocclusion, and destructive-blending acceptance rules.

## Frozen hashes

```text
after-18s.png     3b1f2d5701a7465266d32f167a7531780537f55572966e0ca9d79d8b9a7dbcd4
after-42s.png     fadd9cff039dece432750b202f179cd37b3844bea1582a48ed949cf67b1b403f
logcat-final.txt  481137529b45b95cce7b514364f7a8bcbc2d08a9143b99642b5cebc8fcb23cec
sf-layers.txt     25586ac16496fc55e17eb7e683622ea81e1f1892f100fc912b27b992fab63362
```

## Consequence

- Keep the built-in backend complete and safely fail-closed.
- Do not advertise this path as qualified or buttery smooth.
- Preserve the proven uniform scheduler and endpoint/timestamp contract.
- Move low-rate quality work to the quarantined RIFE/Vulkan path, which has
  materially stronger prior motion-correlation evidence, while retaining all
  legal, deadline, scene-cut, and physical-gameplay gates.

