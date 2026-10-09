# GETLLAR read-barrier candidate: preparation and limits

September 8, 2026. This is a candidate, not a promoted normal build or a claim
that PS3 crashes, pacing or frame generation are fixed.

The trace-disabled candidate reached brief controlled ICO gameplay in an
18:41 launch-to-Exit test. See
[device evidence](../../docs/qa/ps3-read-barrier-no-trace-2026-09-08/README.md).
Repeat launch, sustained gameplay, visible library return and sleep/resume
remain required. Normal APK `02d71f09` was restored after that test.

## Patch preparation

Use `engines/patches/aps3e-getllar-read-barrier-build.patch` for a future build
from the pinned aPS3e source with the existing source-lock patches applied.
It adds exactly the same four lines as the historical
`aps3e-getllar-read-barrier.patch`, but includes surrounding context. The
historical minimal patch can be applied twice and duplicate the barrier; the
build version rejects a second application. Do not apply both versions.

Build patch SHA-256:
`79fc0d709a7090e402d9838c65b722c462de42e8b98afd160b6c7363c40f9bee`.
The historical patch and existing APK provenance have not been rewritten.

The local source currently ALREADY contains the barrier and seven conditional
trace blocks. From the repository root, this read-only check confirms that
the build patch is already present:

```sh
git apply --reverse --check --directory=engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b engines/patches/aps3e-getllar-read-barrier-build.patch
```

The source lock and normal staged library are intentionally unchanged. Do not
add the patch to the lock's active patch list until the corresponding artifact
is actually staged and its identity updated. There is no newly completed clean
build here. The existing pinned Ninja state is invalid: a full target invocation
would rebuild approximately 4,533 actions. Isolated compile/link/package helpers
remain available in this directory; they require explicit new output paths and
must not replace the other agent's current build. For a trace-disabled compile,
use `compile_spurs_trace.py --without-trace`; package with `--without-trace` too,
and record the actual patch used via `--extra-source-patch`.

## Host regression

```sh
python3 -B -m unittest tools.tests.test_aps3e_getllar_read_barrier tools.tests.test_aps3e_putllc_unchanged_race tools.tests.test_aps3e_rejected_dma_profile tools.tests.test_phase3_aps3e_packaging -v
```

All 26 tests passed on this host, with no skips. The new test applies/reverses
patches only in temporary copies, reconstructs the hash-pinned pre-trace source,
checks application with and without diagnostic blocks, and verifies exact
round trips. It also disassembles the tested ARM object: `dmb ishld` at `0x105c`
precedes the reservation `ldar` at `0x1078`, with no `lucent_spurs` symbols.
Heavyweight source/object tests explicitly skip when those local inputs are
absent. This is source/binary evidence, not an exhaustive concurrency proof or
runtime qualification. No panels were activated for these host checks.
