# LSFG internal evaluation build — 2026-08-26

Status: **INTERNAL BUILD PASS; PRODUCT AND REDISTRIBUTION REMAIN STOP**.

This checkpoint exists only to demonstrate the in-process Android LSFG path
while written redistribution authorization is pending. The owner reports
verbal confirmation that a correct implementation may be authorized. That is
enough for this private evaluation at the owner's direction, but it is not a
substitute for written release terms.

## EmuFusion+ artifact

```text
unified-android/build/lucent-3.2.16-emufusion-plus-lsfg-internal-3902c62c25bf887e1cdf690281ece7db80cfb923e60b20e3c1b8a7b82403ecd0.apk
SHA-256 3902c62c25bf887e1cdf690281ece7db80cfb923e60b20e3c1b8a7b82403ecd0
```

The APK is debug-signed and qualification-only. It must not be uploaded,
published, shared, or installed as a public release.

This internal variant is visibly distinguished from ordinary EmuFusion:

- application label: `EmuFusion+`;
- icon: the existing rainbow vortex/controller mark with a black/charcoal
  controller shell and white buttons;
- package: still `com.thorium.preview`, intentionally replacing the same-signed
  internal EmuFusion installation in place while preserving its app data.

The exact icon source is
`unified-android/res/drawable/lucent_plus_icon.png` (SHA-256
`aa6625f564255fb5c5f781acfb6249e52a73fa158ad676dc1ea7e1c73234ac9f`).

## Internal routing

- The user-facing control remains only `Frame Generation: On/Off`.
- When this special APK contains the LSFG qualification factory and frame
  generation is On, the top display automatically attempts LSFG.
- No shell setting or backend picker is required for the internal build.
- A normal APK does not contain the factory, so the same code falls through to
  the ordinary automatic backend policy and Direct fallback.
- Initialization, capability, shader-integrity, self-test, timing, or runtime
  failure still fails closed to Direct presentation.
- Secondary-display LSFG remains out of scope; top-display correctness is the
  priority.

## Private assets

Package verification found the conditional native host
`lib/arm64-v8a/liblucent_lsfg_qualification.so` and no `Lossless.dll`, SPIR-V
payload, or private LSFG manifest in the APK. The owner-supplied DLL identity
was verified locally as:

```text
fe0faeb147accab84539ac2bdcaa4eb3dec850752a336e710b85fc87477004e4  Lossless.dll
```

Runtime shaders remain app-private and owner-controlled. They are not source
assets and are not redistribution-ready.

## Thor installation

Installed successfully on the authorized AYN Thor at serial `427c87b2` using
an in-place, same-certificate package replacement. No uninstall, app-data
clear, or configuration reset was performed. The installed package reports
version `3.2.16` / code `90` and launches into the existing EmuFusion library.

The private qualification cache contains exactly 48 SPIR-V shaders and the
manifest SHA-256
`7dbcf082bc4a0c6448161ef7c24ee7c31a12de8e4496a808f5a3b74da865b2d2`.
The cache contains zero copies of `Lossless.dll`. These assets remain in the
app-private sandbox and are not embedded in the APK.

## Gates run

- pinned public wrapper plus the authorized nonblocking Android patch: PASS;
- LSFG packaging tests: 8/8 PASS;
- systemwide frame-generation tests: 77/77 PASS;
- unified Android Java suite: PASS;
- one-app APK boundary verifier: PASS;
- explicit EmuFusion+ label/icon/internal-payload verifier: PASS;
- DEX inspection contains `LSFG internal evaluation`: PASS;
- APK inspection contains no DLL, private manifest, or `.spv`: PASS.

## Remaining qualification blockers

This build does not claim gameplay qualification. The current LSFG transport
is restricted to the demonstrated 20-to-40 path, and the last physical Ocarina
run still failed closed after missing an immutable SurfaceControl cutoff. A
private demonstration must report that fallback honestly. The backend cannot
be enabled in a distributable release until written authorization and physical
moving-game cadence/content acceptance both pass.
