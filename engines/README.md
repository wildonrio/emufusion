# EmuFusion engine supply chain

`registry.json` is the authoritative Phase 1 candidate inventory. A pinned
commit records what will be audited; it does not approve or ship that engine.
The validator enforces that only engines with resolved licenses, reproducible
builds, and qualified state support may become `approved` or `shipped`.

No core binaries are stored in this repository or downloaded by the app.
Development builds use verified source archives:

```sh
./engines/build_core.sh mgba
./engines/build_core.sh mesen
./engines/build_core.sh mesen-s
./engines/build_core.sh sameboy
./engines/build_core.sh gearsystem
./engines/build_core.sh gearcoleco
./engines/build_core.sh freeintv
./engines/build_core.sh fuse
./engines/build_core.sh swanstation
```

Outputs go to ignored `engines/build/<abi>/`. Moving an output into an APK is a
separate release action that is prohibited until its registry gates pass.

All nine pinned recipes completed an Android ARM64 compile on 2026-08-06.
This is compile verification only, not save-state, device, performance, or
reproducibility qualification. In particular, `build.reproducible` remains
false until clean independent builds produce matching normalized artifacts.
The unified build has an explicit
`LUCENT_INCLUDE_EXPERIMENTAL_CORES=1` qualification flag; release builds leave
it unset. Qualification filenames are `liblucent_core_mesen.so` and
`liblucent_core_mgba.so`. Such builds also carry the explicit
`engine-qualification-opt-in.json` asset. Its `qualificationOnly` field keeps
the cores visibly outside the release gate, while `autoSelect` defaults to
false. A hardware-test artifact may additionally set
`LUCENT_AUTOSELECT_EXPERIMENTAL_CORES=1`; this is rejected unless experimental
cores are also explicitly included, and it never affects a default build.

The independent JNI host lives in `unified-android/native`. It implements the
MIT libretro API directly; it contains no RetroArch frontend source, assets,
settings, or configuration.

## Compile verification record

| Candidate | Android ARM64 compile | Source integrity notes |
|---|---|---|
| Mesen | Passed 2026-08-06 | Commit archive SHA-256 pinned |
| mGBA | Passed 2026-08-06 | Commit archive SHA-256 pinned |
| Mesen-S | Passed 2026-08-06 | Commit archive SHA-256 pinned |
| SameBoy | Passed 2026-08-06 | Commit archive plus official RGBDS 1.0.3 Darwin/Linux tool archives SHA-256 pinned |
| Gearsystem | Passed 2026-08-06 | Commit archive SHA-256 pinned |
| Gearcoleco | Passed 2026-08-06 | Commit archive SHA-256 pinned |
| FreeIntv | Passed 2026-08-06 | Commit archive SHA-256 pinned; firmware remains user-supplied |
| Fuse | Passed 2026-08-06 | Commit archive SHA-256 pinned |
| SwanStation | Passed 2026-08-07 | Commit archive and complete vendored dependency closure SHA-256 pinned; MIT OpenBIOS included upstream; forced ThinLTO and build/source path leakage were removed; two path-isolated clean builds were byte-identical (`ea00701e…`) |
| melonDS DS | Passed 2026-08-06 | Top-level commit plus all eleven FetchContent dependency archives SHA-256 pinned and staged offline; two consecutive clean Android ARM64 builds were bit-identical (`f0e0509f…`) |
| MAME | Passed 2026-08-06 for Arcade and Neo Geo AES | Constrained driver set; source/Makefile/NDK/recipe/output fingerprints pinned; exact qualified core SHA `8e099718…` is safely reusable; Neo Geo CD remains firmware-blocked |

The script always builds into ignored development output. It does not copy any
core into EmuFusion and does not change an engine's approval, qualification, or
shipping status.

## Phase 2 qualification payload

`phase2-registry.json` is the fail-closed authority for the larger-system
candidates. The explicit qualification APK currently stages PPSSPP, Play!,
ARMSX2, Flycast, Azahar, and Virtual Jaguar in EmuFusion's own GLES/Vulkan host.
Their exact source archives, dependencies, integration patches, official
release archives, and toolchains are locked by `*-source-lock.json` files as
applicable. Azahar now builds the same pinned 2125.1.3 source and 52 recursive
Git links with the Android error-signature patch and 16 KiB alignment. Its
SPDX artifact is `GENERATED_FROM` source, not `EXTRACTED_FROM` the older release
ZIP. Two clean builds at different paths on the current host match the tested
core; runtime audio/performance and release qualification remain open. The
previous upstream core is retained beside the staged output as a hash-named
backup. No Phase 2 engine is shipped, and
open dependency/license, legal-content, firmware, state, renderer,
performance, and device gates remain binding.

Every qualification APK generates three deterministic compliance assets from
the exact staged files: an SPDX 2.3 source SBOM, a source-to-binary artifact
manifest, and a human-readable notice. Generation fails if any opted-in core is
missing, its commit differs from the registry, or its source archive is not
SHA-256 pinned. These files improve traceability; they do not satisfy an open
dependency audit or change `shipped=false`.

Reproducible-build claims are separately bound by
`reproducibility-lock.json`. The verifier requires an exact registry set,
source commit/archive identities, two byte-identical builds, the relevant
engine recipe/preamble and patch SHA-256 values, and the exact staged artifact
SHA-256. A stale recipe or reused
binary therefore stops qualification packaging instead of silently weakening
the claim.

Android ARM64 callback, save-memory, and serialization evidence is documented
in [`qa/phase1a-matrix.md`](qa/phase1a-matrix.md). The reproducible emulator-only
harness and legal fixture provenance are in [`qa/README.md`](qa/README.md).

## Remaining Phase 1A MAME work

MAME remains experimental rather than release-approved. Driver/dependency
notices, an independent clean-build comparison, physical-device performance,
and a legal Neo Geo CD/CDZ main BIOS path are still required. The build recipe
will reuse only the exact emulator-qualified binary after matching the pinned
source archive, upstream Makefile, NDK metadata, recipe identity, and core
SHA-256; `LUCENT_FORCE_REBUILD=1` opts into the expensive clean rebuild.
