# Amiga / CD32 PUAE Phase 2 host closure

PUAE is wired into EmuFusion's normal in-process Phase 2 route for `amiga` and
`amigacd32` only in the explicitly requested qualification package. This is
not a release approval: `shipped` and all device/runtime gates remain false.

## Exact build and AROS boundary

- PUAE source commit: `96ebfcfc2c66233ad37f6dc99ee991211dc719ad`
- Source archive SHA-256:
  `af671aa1b42eb5b97a05b3ac2e57b6f397f3e17bbd0be7ac204636c2321d3cf0`
- Android ARM64 proof core SHA-256:
  `29d03ec1b442431243fd6e7fbc902a811d130a693c274b673dd3a1c61d0aeadf`
- Embedded compressed AROS SHA-256:
  `5ee9dade0feeae8b0f30e3b35b0b79535b7313c89e3328dc6ad6bc43f42f620c`
- Decompressed 1 MiB AROS SHA-256:
  `1211897caea79785f2441da4b75a460255b7f85e5129e03fe0ab61a8aebfb2c1`

October 5 normal staging uses the 16 KiB-aligned candidate accepted by the
strict Android loader. Two clean builds at the same isolated path match;
path-independent reproduction and game/runtime/release qualification remain
unproven for this artifact. See the software-pages and portable-integration QA
directories dated October 4.

The build-time verifier extracts the C byte array from the exact source,
decompresses it, validates both identities, requires exactly one compressed
match in the ELF, and scans the source closure for known CD32 ROM identities.

AROS upstream declares the AROS Public License 1.1. PUAE's exact embedded ROM
is nevertheless only bound to the pinned PUAE snapshot: the mutable WinUAE
download referenced by PUAE now differs, and EmuFusion has not reproduced the ROM
from a pinned AROS source revision. That is recorded rather than papered over;
the firmware and license release gates remain false.

## CD32 fails closed

CD32 has no built-in firmware approval. Before loading the core,
`Phase2QualificationCatalog` accepts only one of the exact-size upstream
compatibility profiles in `engines/puae-firmware-policy.json`: one combined
1 MiB file, or the exact 512 KiB main and 512 KiB extended pair. The catalog
hashes the user's files, copies them into app-private system storage, and
aborts on any missing or mismatched file.

EmuFusion never bundles, downloads, or supplies Kickstart/CD32 ROMs. Compatibility
MD5 values do not establish lawful provenance.

## Dependency and content evidence

`engines/puae-dependency-audit.json` inventories all 227 objects from the
exact Android configuration and maps them to the core or a vendored component.
The source lock, SPDX SBOM, packaged notices, and APK verifier bind that
inventory. The audit deliberately remains incomplete because WHDLoad/data
rights and AROS source-to-ROM provenance are unresolved.

A CC0 deterministic 880 KiB Amiga boot-block fixture is available under
`engines/qa/fixtures/puae-minimal`. Its expected SHA-256 is
`e5692a1ef7a769936b283b465f1dd965979a2cae1e16e4f8af32e41c310724b1`.
It is not packaged in the APK, and its existence does not claim a device run.

## Remaining gates

- exact AROS source reproduction and complete dependency/data rights review;
- physical-device launch, rendering, audio, input, and lifecycle evidence;
- 100-cycle state restore and version-migration evidence;
- sustained pacing, thermals, and three-title compatibility per system;
- release signing and explicit distribution approval.
