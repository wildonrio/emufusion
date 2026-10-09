# RIFE Vulkan zero-copy cached checkpoint — 2026-08-24

## Verdict

The quarantined Android RIFE+ncnn experiment now proves the complete offscreen
input transport on the physical AYN Thor:

```text
EGL render
  -> ImageReader RGBA8888 image
  -> immutable timestamp + producer fence
  -> retained AHardwareBuffer
  -> Vulkan external-memory import
  -> GPU planar-float to packed-RGB conversion
  -> GPU-resident RIFE inference
```

No CPU endpoint copy is present. A blocking output readback is used only by the
separate validation probe and is explicitly forbidden in a live path.

This is not product integration or qualification. The current v4.6 asset
remains quarantined by the provenance gate, the timed probe uses
`submit_and_wait`, cache eviction still needs live fence ownership, and the
output has not yet been connected to EmuFusion's timestamp authority or a
physical moving-game presentation.

## Exact endpoint identity

The two imported endpoints were rendered into distinct `ImageReader` buffers
and retained with exact monotonic timestamps:

```text
previous = 106394481149048 ns
current  = 106394498912068 ns
```

The native cache owns an acquired `AHardwareBuffer` reference for each entry.
Vulkan pipeline/image objects are destroyed before that reference is released.
The cache is bounded to eight entries and fails closed rather than evicting an
object without a completion fence.

## Sustained cached result

The final run uses one cache-prime call followed by three unmeasured warmups and
120 measured inferences at 128×72, phase 0.5:

| Metric | Result |
|---|---:|
| Cache entries | 2 |
| Final-call cache hits / misses | 2 / 0 |
| Reused setup time | 2,813 ns |
| Record p50 / p95 | 2.424 / 2.488 ms |
| Submit-and-wait p50 / p95 | 5.647 / 5.663 ms |
| Total p50 / p95 | 8.073 / 8.142 ms |
| Total max | 8.175 ms |
| 30→60 deadline (16.667 ms) | PASS |
| 60→120 deadline (8.333 ms) | Numerical PASS, insufficient margin |
| Output validation | PASS, byte range 0–255 |

The low-rate N64 paths have meaningful compute headroom. The 60→120 result has
only about 0.19 ms p95 margin before surface conversion, queueing, compositor
cutoff, emulator contention, and safety overhead; it is therefore not a
defensible live qualification.

## Evidence and hashes

```text
experiments/rife-ncnn-vulkan-android/android-benchmark/evidence/
  thor-ahardwarebuffer-import-2026-08-24/cached-r2/

result JSON  3dfb4854eba05224d48056464859171a057dd3e8e5de6dfc5397eeb6bc7fb879
app APK      a9ca2c53cfad7c6ff94738386bfc12c8b08b866790e9c49c6356d9d0260f3569
test APK     dda8489ef3f35849c298ae40399973e21df3361abe5b2cc4262fec3b0f483f31
```

The instrumentation launched no Activity, required no screen wake, and the
Thor remained asleep before and after both physical runs.

## Required next work

1. Replace probe-only fence waits and `submit_and_wait` with an explicit,
   nonblocking acquire/compute/present fence chain.
2. Add fence-owned bounded cache reuse/eviction and a GPU surface-output timing
   campaign under concurrent emulator load.
3. Use only an expressly licensed and provenance-locked model; do not promote
   the current v4.6 benchmark asset by inference.
4. Integrate behind EmuFusion's immutable endpoint/timestamp/phase contract,
   never behind an independent capture or scheduling loop.
5. Physically inspect representative N64 20→40 and 30→60 moving gameplay and
   verify SurfaceFlinger scan histograms before any qualification.

