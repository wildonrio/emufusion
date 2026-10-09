# Corresponding source for EmuFusion

This repository is the corresponding source for the EmuFusion Android application.
It is provided at no charge alongside every downloadable APK.

## Source map

- Pegasus Frontend base: version `alpha16-105-g6b322063`, exact source commit
  [`6b322063`](https://github.com/mmatyas/pegasus-frontend/tree/6b322063)
- Qt toolkit: version `5.15.10`, source tag
  [`v5.15.10-lts-lgpl`](https://code.qt.io/cgit/qt/qt5.git/tag/?h=v5.15.10-lts-lgpl)
- OpenSSL: version `1.1.1t`, source tag
  [`OpenSSL_1_1_1t`](https://github.com/openssl/openssl/tree/OpenSSL_1_1_1t)
- Expected upstream Android APK: `pegasus-fe_alpha16-105-g6b322063_android64.apk`
- Expected upstream APK SHA-256:
  `e595be198bfd21c1855eaf563d5af0deae9c9601e6efb195ed299f2065287c67`
- EmuFusion Android services: `android-companion/`
- EmuFusion launch and controller integration: `android-launch-bridge/`
- EmuFusion theme: `theme/`
- Complete transformation and build instructions: `unified-android/build.sh`
- In-process engine inventory and pinned upstream identities:
  `engines/registry.json`
- Qualification-only core build recipes: `engines/build_core.sh`
- Signed packaged-core provenance generator:
  `unified-android/tools/generate_engine_artifact_manifest.py`
- Deterministic Phase 2 SPDX 2.3 SBOM generator:
  `unified-android/tools/generate_phase2_sbom.py`
- Optional RIFE frame-generation qualification source/provenance lock:
  `experiments/rife-ncnn-vulkan-android/upstream-lock.json`
- Deterministic RIFE upstream preparation and packaging gates:
  `experiments/rife-ncnn-vulkan-android/android-benchmark/tools/prepare_upstreams.py`
  and `unified-android/tools/stage_rife_framegen_qualification.py`

`unified-android/build.sh` downloads and verifies the exact upstream binary,
applies the package, manifest, and bytecode transformations recorded in the
script, compiles the EmuFusion sources, embeds the theme and license notices, and
produces the signed APK. A distributor may provide a different signing key via
the documented environment variables without altering the program source.

The upstream source and this repository are both hosted on GitHub and can be
downloaded without registration. Together they contain the source and scripts
needed to build, install, run, and modify the version of EmuFusion distributed in
the matching release.

## Qt and OpenSSL

The APK bundles Qt 5.15.10 (LGPL-3.0, except the Qt Quick Timeline QML plugin,
which is GPL-3.0-or-later), OpenSSL 1.1.1t (dual OpenSSL/SSLeay license), and
LLVM libc++ (Apache-2.0 with LLVM exception). EmuFusion modifies none of them: the
exact binaries are the ones linked into the checksum-pinned upstream Pegasus
Android APK named above, and `unified-android/build.sh` repacks them unchanged.
The only binary EmuFusion patches is Pegasus's own `libpegasus-fe_arm64-v8a.so`,
by the scripts in `unified-android/tools/`.

Their complete corresponding source is published by their upstream projects at
the exact versions listed in the source map above, and is available to any
recipient of this APK without charge and without registration. Per-module
copyright, license, and license-text locations are in
`THIRD_PARTY_NOTICES.md`, which ships inside the APK together with the LGPLv3
text (`LICENSE-LGPL-3.0.txt`) and the GPLv3 text (`LICENSE`).

### Replacing the bundled Qt (LGPL-3.0 section 4)

Qt is packaged as separate shared objects, so a recipient may run EmuFusion against
their own modified Qt without rebuilding EmuFusion. Build the Qt 5.15.10 modules
for `arm64-v8a` keeping the packaged `SONAME`s (`libQt5Core_arm64-v8a.so` and
so on), replace the matching files under `lib/arm64-v8a/` in the APK, leave
`res/values/arrays.xml` (`qt_libs`, `load_local_libs`, `bundled_libs`) untouched
so the Qt bootstrap loads them by the same names, then re-zipalign and re-sign
with your own key. `unified-android/build.sh` performs those same steps and
accepts a different signing identity through documented environment variables.
The same procedure applies to `libcrypto.so` and `libssl.so`.

`docs/qt-dependency-notes.md` records how the packaged Qt and OpenSSL versions
were determined and which Qt libraries the frontend hard-links.

Qualification builds may additionally contain any core named by
`engines/qualification-opt-in.json`. Every such APK carries
`phase1-engine-artifacts.json`, `phase1-sbom.spdx.json`, and
`PHASE1-CORE-NOTICES.txt`, generated from the exact staged libraries. Those
files bind each binary SHA-256 to its pinned source commit, source-archive
SHA-256, declared license, and checked-in build recipe. The complete source
identities and build commands are in `engines/registry.json` and
`engines/build_core.sh`; the current qualification set is Mesen, Mesen-S,
SameBoy, mGBA, Gearsystem, SwanStation, melonDS DS, Fuse, and constrained MAME.
No ROM, proprietary firmware, key, or copyrighted game-system material is
included.

An APK explicitly built with `LUCENT_INCLUDE_RIFE_FRAMEGEN=1` additionally
contains the exact qualification-only RIFE/ncnn native payload and the
hash-bound RIFE v4.6 model. The complete source commits, source/archive hashes,
model hashes, patch identities, and licenses are recorded in
`experiments/rife-ncnn-vulkan-android/upstream-lock.json`; complete notice texts
ship under `assets/framegen/rife-v4.6/licenses/`. The build flag is default-off,
the resulting filename says `rife-framegen-qualification`, and the embedded
manifest explicitly forbids product routing.

An APK explicitly built with `LUCENT_INCLUDE_LSFG_FRAMEGEN=1` compiles the
EmuFusion-owned host in `unified-android/lsfg-qualification-native/` against an
external checkout of the exact public MIT wrapper and authorized Android patch
identified by `experiments/lsfg-vulkan-android-inprocess/upstream-lock.json`.
The build verifies the complete patched checkout before compilation. Neither
`Lossless.dll` nor derived shaders are corresponding-source inputs for the APK:
they are not packaged or redistributed and may only be staged privately by the
owner for a local qualification run.

The separate, explicitly requested Phase 2 qualification APK contains
qualification-only in-process candidates including AppleWin, PUAE, Beetle
Saturn, Dolphin, PPSSPP, Play!, ARMSX2, Flycast, Azahar, Virtual Jaguar, and
ScummVM. Their exact source commits and archive hashes are in
`engines/phase2-registry.json`; staged dependency, patch, toolchain, and/or
official-release-artifact identities are in the corresponding
`engines/*-source-lock.json` files. Each core's complete upstream license text,
`phase2-sbom.spdx.json`, the registry, and the signed artifact manifest are in
the APK. Azahar is extracted from its checksum-pinned official 2125.1.3 Android
ARM64 release ZIP; EmuFusion does not claim an upstream signature or a locally
reproduced source-to-binary build for it. The source lock records the exact
corresponding source snapshot separately. All dependency/license audits that
remain open are represented as `NOASSERTION`; this payload is fail-closed,
qualification-only, and never the production engine selection.

AppleWin's corresponding-source materials additionally include
`engines/applewin-source-lock.json`,
`engines/patches/applewin-external-firmware.patch`, and
`engines/applewin-firmware-policy.json`. The patch removes the upstream ROM
resource inputs from the compiled core. No Apple firmware is part of the
corresponding-source bundle or APK.

PUAE's corresponding-source materials additionally include
`engines/puae-source-lock.json`, `engines/puae-dependency-audit.json`,
`engines/puae-firmware-policy.json`, and `engines/PUAE-CORE-NOTICES.txt`.
They bind the selected 227-object build closure and exact built-in AROS bytes.
No Commodore Kickstart or CD32 firmware is included; those files remain
user-supplied and are accepted only by the fail-closed runtime profile.

The optional Phase 3 PlayStation 3 qualification adapter is built from aPS3e
commit `b5ae1af50d5e2f3b705506e7380a4504e086840b`. Its downloaded source archive
SHA-256 is
`37fb172d3cd115aa13b29571710f8223c19783ead44cd174f64d686911533ee1`.
`engines/aps3e-source-lock.json` records the exact tree, build toolchain,
patches, adapter binary and open dependency/license gates; the checked-in
patches and adapter translation unit are under `engines/patches/`. The vendored
RPCS3-derived engine is GPL-2.0-only and its license text is included at
`engines/compliance/aps3e/GPL-2.0-only.txt`. The complete static-dependency
notice audit remains unfinished, so this adapter is qualification-only and
not release-qualified. No Sony firmware or PS3 game content is included.
