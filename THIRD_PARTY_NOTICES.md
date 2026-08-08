# Third-party notices

## Pegasus Frontend

Lucent is a modified distribution of Pegasus Frontend and uses Pegasus as its
library and theme engine.

- Project: <https://github.com/mmatyas/pegasus-frontend>
- Exact base source: <https://github.com/mmatyas/pegasus-frontend/tree/6b322063>
- Base version: `alpha16-105-g6b322063`
- Copyright: Mátyás M. and Pegasus Frontend contributors
- License: GNU General Public License, version 3.0
- License text: included as `LICENSE` and available at
  <https://www.gnu.org/licenses/gpl-3.0.html>

Lucent changes the Android package and presentation, installs a new default
theme, and adds library discovery/import, metadata and media enrichment,
preview playback, direct emulator launching, update handling, and optional
device-specific controller and LED integration. Lucent is not an official
Pegasus release and is not endorsed by the Pegasus project.

The complete corresponding source and build scripts are available from the
same release repository. See `SOURCE_OFFER.md` and `unified-android/build.sh`.

The Lucent name, icon, Android integration, importer, updater, and default
theme are Lucent additions. Platform and emulator names and logos are used for
identification and remain the property of their respective owners; their
presence does not imply sponsorship or endorsement.

## The Qt Toolkit (Qt 5.15.10)

**This application uses the Qt toolkit, version 5.15.10, under the GNU Lesser
General Public License version 3 (LGPL-3.0).** Qt is the GUI, QML, networking,
multimedia, and database toolkit that the Pegasus frontend runtime and the
Lucent theme run on. Lucent neither compiles nor modifies Qt: the exact Qt
binaries in the APK are the ones linked into the checksum-pinned upstream
Pegasus Android build, and they are repacked unchanged.

- Project: <https://www.qt.io/>
- Source code: <https://code.qt.io/cgit/qt/qt5.git/> — the exact packaged
  version is the `v5.15.10-lts-lgpl` tag,
  <https://code.qt.io/cgit/qt/qt5.git/tag/?h=v5.15.10-lts-lgpl>
- Copyright: The Qt Company Ltd. and other Qt contributors
- Licenses: LGPL-3.0 for the modules listed below, except Qt Quick Timeline,
  which is GPL-3.0-or-later (see the separate entry). Qt is additionally
  available under commercial terms from The Qt Company; Lucent does not use and
  does not sublicense those terms.
- License text: `LICENSE-LGPL-3.0.txt` is included in the APK alongside this
  file, and the GPLv3 text it incorporates by reference is included as
  `LICENSE`. Both are also at <https://www.gnu.org/licenses/lgpl-3.0.html> and
  <https://www.gnu.org/licenses/gpl-3.0.html>.

The version determination is recorded in `docs/qt-dependency-notes.md`; it is
read from the build string embedded in the packaged
`libQt5Core_arm64-v8a.so`.

Packaged Qt modules (all `_arm64-v8a`): Qt5Core, Qt5Gui, Qt5Qml, Qt5QmlModels,
Qt5QmlWorkerScript, Qt5Quick, Qt5QuickParticles, Qt5QuickShapes, Qt5Network,
Qt5Multimedia, Qt5MultimediaQuick, Qt5Sql, Qt5Svg, Qt5Gamepad, and
Qt5AndroidExtras. The APK additionally contains the matching Qt platform,
image-format, media, audio, SQL-driver, icon-engine, gamepad-backend and QML
plugins built from the same Qt sources and covered by the same terms.

### Relinking rights (LGPL-3.0 section 4)

You may modify Qt and use your modified Qt with Lucent. Because Lucent ships Qt
as separate shared objects rather than statically linked code, a modified Qt can
be substituted without rebuilding Lucent:

1. Build the Qt 5.15.10 modules listed above for `arm64-v8a` with your changes,
   keeping the packaged `SONAME`s (for example
   `libQt5Core_arm64-v8a.so`).
2. Replace the corresponding files under `lib/arm64-v8a/` in the APK, leaving
   `res/values/arrays.xml` (`qt_libs`, `load_local_libs`, `bundled_libs`)
   unchanged so the Qt bootstrap loads your libraries by the same names.
3. Re-zipalign and re-sign the APK with your own key. `unified-android/build.sh`
   performs exactly these steps and accepts a different signing identity through
   documented environment variables.

Lucent applies no patch to any Qt library. The only binary Lucent modifies is
Pegasus's own `libpegasus-fe_arm64-v8a.so`; those patches are in
`unified-android/tools/` and are applied by `unified-android/build.sh`.

### Qt Quick Timeline (GPL-3.0-or-later)

`libqml_QtQuick_Timeline_qtquicktimelineplugin_arm64-v8a.so` comes from the
`qtquicktimeline` module, which — unlike the rest of the packaged Qt — offers no
LGPL option. It is available commercially or under the GNU General Public
License version 3 or later as approved by the KDE Free Qt Foundation, and Lucent
conveys it under GPL-3.0, the same license as the application as a whole.

- Source code: <https://code.qt.io/cgit/qt/qtquicktimeline.git/> (branch `5.15`)
- License text: included as `LICENSE`, and at
  <https://www.gnu.org/licenses/gpl-3.0.html>

## OpenSSL 1.1.1t

Lucent packages the OpenSSL 1.1.1t cryptography and TLS libraries
(`libcrypto.so`, `libssl.so`, `SONAME`s `libcrypto.so.1.1` and `libssl.so.1.1`)
as bundled by the upstream Pegasus Android build for Qt Network's HTTPS support.
They are repacked unchanged.

- Project: <https://www.openssl.org/>
- Source code: <https://github.com/openssl/openssl/tree/OpenSSL_1_1_1t>
- Copyright: The OpenSSL Project Authors, and Eric Young and Tim Hudson for the
  original SSLeay code
- License: the dual **OpenSSL License and original SSLeay License**. The
  Apache-2.0 relicensing applies only from OpenSSL 3.0 onward and does **not**
  cover this version.
- License text: <https://www.openssl.org/source/license-openssl-ssleay.txt>

Both licenses require that the above attributions be retained; this notice
serves that purpose, and it ships inside the APK. The version was read from the
`OpenSSL 1.1.1t  7 Feb 2023` string in the packaged `libcrypto.so`.

Note for maintainers: OpenSSL 1.1.1 reached end of life on 2023-09-11. Moving to
a maintained branch requires rebuilding the upstream Pegasus Android package and
is tracked with the wider Qt toolchain work, not here.

## LLVM libc++

`libc++_shared.so` is the Android NDK build of the LLVM C++ standard library,
bundled by the upstream Pegasus Android build and required by Qt and by every
Lucent native host and core.

- Project: <https://libcxx.llvm.org/>
- Copyright: the LLVM Project contributors
- License: Apache License 2.0 with the LLVM exception
- License text: <https://llvm.org/LICENSE.txt>

## Apache Commons Compress

Lucent uses Apache Commons Compress 1.21 to inspect and extract verified ROM
payloads from 7z archives.

- Project: <https://commons.apache.org/proper/commons-compress/>
- Copyright: The Apache Software Foundation
- License: Apache License, version 2.0
- License text: <https://www.apache.org/licenses/LICENSE-2.0>

## XZ for Java

Lucent uses XZ for Java 1.9 as the LZMA/LZMA2 decoder used by 7z archives.

- Project: <https://tukaani.org/xz/java.html>
- Copyright: Lasse Collin and contributors
- License: Public domain for version 1.9

## Optional qualification-only emulator cores

Lucent development builds may be produced with
`LUCENT_INCLUDE_EXPERIMENTAL_CORES=1`. Those builds include pinned, unmodified
libretro core builds solely for compatibility and save-state qualification;
release builds do not enable or auto-select them until every registry gate is
complete.

The complete current qualification set is Mesen, Mesen-S, SameBoy, mGBA,
Gearsystem, SwanStation, melonDS DS, Fuse, constrained MAME, DOSBox Pure,
ProSystem, Beetle PCE Fast, Beetle NeoPop, and Beetle Cygne. The exact
project URL, source commit, source-archive SHA-256, declared SPDX license,
binary SHA-256, build recipe, qualification status, and remaining audit note
for every binary are generated into `PHASE1-CORE-NOTICES.txt` in the APK. The
same package includes `phase1-sbom.spdx.json` and
`phase1-engine-artifacts.json`; generation fails closed if a requested library
or pinned source hash is absent. The authoritative source records remain in
`engines/registry.json` and `engines/qualification-opt-in.json`.

The three Beetle candidates added to this qualification-only set are based on
pinned Mednafen-derived libretro source and use the GPL-2.0-or-later option.
Their selected dependency closure also contains MIT libretro-common code.
Beetle PCE Fast additionally contains BSD-3-Clause libchdr, Zstandard and
Tremor code, zlib-licensed zlib code, and public-domain LZMA SDK code. Beetle
NeoPop contains GPL-2.0-or-later z80-fuse-derived code. Beetle Cygne contains
the permissively licensed V30MZ CPU core by Bryan McPhail; that author credit
is required. Configuration-specific evidence is recorded under
`engines/audits/` and is not a substitute for final legal review.

Beetle Virtual Boy is not part of the qualification payload. Its selected
source closure includes legacy SoftFloat 2b custom terms whose compatibility
with Lucent's combined GPLv3 distribution has not been established, so the
registry and build remain fail-closed.

## Optional Phase 2 multi-core qualification payload

An explicitly requested Phase 2 qualification APK may include the pinned
cores below. Normal Lucent release builds do not include or select this
payload.

| Core | Project | Exact source commit | Declared license |
| --- | --- | --- | --- |
| AppleWin | <https://github.com/audetto/AppleWin> | `2045a52d89363005476e670e45df048655edccf7` | GPL-2.0-or-later |
| PUAE | <https://github.com/libretro/libretro-uae> | `96ebfcfc2c66233ad37f6dc99ee991211dc719ad` | GPL-2.0-or-later |
| PPSSPP | <https://github.com/hrydgard/ppsspp> | `fa50bb1976065c4f8b1b47af227d367fe9771555` | GPL-2.0-or-later |
| Play! | <https://github.com/jpd002/Play-> | `50aedca2639521bc498ace0b2be1ea012801a86a` | BSD-3-Clause |
| ARMSX2 | <https://github.com/ARMSX2/ARMSX2> | `788a59d641c777cb7f70726ea573d420508e0931` | GPL-3.0-only |
| Flycast | <https://github.com/flyinghead/flycast> | `d4fc0774107c4c307346b469499b9303a6ca0ffa` | GPL-2.0-or-later |
| Azahar | <https://github.com/azahar-emu/azahar> | `b42d0916ba9799297ae0e27c07d56801da1b5de5` | GPL-2.0-or-later |
| Virtual Jaguar | <https://github.com/libretro/virtualjaguar-libretro> | `59f7f9cc594ae6c6982c2bd8fc0dbf36873f9869` | GPL-3.0-only |
| ScummVM (32-engine lite profile) | <https://github.com/scummvm/scummvm> | `6aa8fa9b6f9e5a7ae670cc355af1b727ff75c995` | GPL-3.0-or-later |

The qualification APK carries every core's upstream license file, an exact
binary manifest, the source/dependency locks, and
`assets/phase2-sbom.spdx.json`. Azahar's binary is extracted from a
checksum-pinned official release archive; no upstream signature or local
source reproduction is claimed. Dependency licenses that have not completed
file-level audit remain `NOASSERTION`; Lucent does not infer or waive those
obligations.

The AppleWin qualification build applies the checksum-locked
`engines/patches/applewin-external-firmware.patch`. It removes every upstream
ROM and firmware resource from the core and accepts only an exact user-supplied
six-file profile at runtime. Lucent distributes no Apple ROM or peripheral
firmware. The full policy and open release gates are documented in
`engines/applewin-firmware-policy.json` and `docs/phase2-applewin.md`.

The PUAE qualification build binds its exact embedded AROS snapshot by both
compressed and decompressed SHA-256, while CD32 accepts only exact-size
user-supplied compatibility identities and packages no proprietary firmware.
The configuration-specific 227-object inventory, component evidence, open
provenance gates, and notices are recorded in
`engines/puae-dependency-audit.json`, `engines/puae-firmware-policy.json`, and
`docs/phase2-puae.md`.

### ScummVM lite-profile qualification core

The ScummVM qualification core is built from commit
`6aa8fa9b6f9e5a7ae670cc355af1b727ff75c995` under GPL-3.0-or-later with a
small Lucent exit-autosave patch. It contains only the 32 engine identifiers in
the pinned upstream `lite_engines.list`; it is not a claim of universal
ScummVM compatibility. The exact binary SHA-256 is
`668aa27dd70990921372d95338dab6384610f721b7bcb4f224b67e63e44d1f4d`.

Packaging runs a binary-specific compliance gate over all 337 linked external
objects and four identified embedded subcomponents. The generated
`SCUMMVM-CORE-NOTICES.txt`, component license directory, and per-object hash
manifest must accompany the core. The authoritative component counts,
licenses, and evidence hashes are in `engines/scummvm-dependency-audit.json`;
unknown components or any artifact, object-count, or evidence drift fails the
build.

The pinned *Flight of the Amazon Queen* freeware fixture is downloaded only
from ScummVM for device qualification and is not bundled or redistributed by
Lucent.
