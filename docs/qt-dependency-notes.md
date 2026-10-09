# Qt dependency notes

## October 5: preserve the no-action-bar theme through the Qt loader

The October 3 resource-only correction was insufficient. The unchanged baseline
`6d7bf279...08d62` reproduces the Android16 `WindowDecorActionBar.doHide` null
`ActionBarContainer` crash at15:35:58. The packaged Qt5 `QtActivityLoader.onCreate`
recognizes only framework style IDs, replaces the app's custom `PegasusMain` with
its fallback, and then requests `FEATURE_ACTION_BAR`. Its actual window hierarchy
therefore contains a framework action bar despite the corrected manifest/style.

`patch_frontend_window_theme.py` now also omits those two pinned loader calls.
It validates loader shape before any resource writes, rejects drift, supports
idempotent checks, and preserves delegate startup and style extraction. The normal
packager checks it again before APK assembly. Signed-DEX inspection independently
confirms the calls are absent in complete `f39419d9...f1e07`; all88native libraries
and application `classes2.dex` remain byte-identical to baseline.

Three new tests fail against the old implementation;54focused checks pass after
the fix and two stale recreation-harness corrections. Headless landscape Android16
4KiB verifies three fresh-process library starts, internal PS2 boot/menu input and
normal exit. An8s cold screenshot is only black startup decor, not a successful
library observation; a separate cold boot shows the library by45s. Both original
profile identities and all302checked saves survive the preserving nonincremental
update, smoke test and cold boots. Simulator sessions stopped; Thor untouched.

This is bounded startup verification, not a measured startup-speed improvement,
all-crash guarantee, new gameplay/performance pass, 16KiB runtime pass or release.
Evidence: `qa/android-portability-2026-10-05-qt-runtime-theme/outcome.json`.

## October 5: first-run storage permission no longer terminates the frontend

`pegasus-android-storage-startup.patch` fixes the native frontend's early return
while Android's all-files Settings screen is pending. The frontend stays alive;
the existing Java lifecycle refreshes discovery after the real permission grant.
Android 11+ now uses the actual all-files result without also requesting obsolete
WRITE_EXTERNAL_STORAGE. Permission denial is not bypassed. Older Android retains
its existing legacy-permission path.

The normal source recipe, artifact lock and generated source kit include the
repair. Old kit is backed up. Complete normal qualification APK `6ede42ba...60225`
differs from `9672d342...c974` in only the frontend native library (the other 48
cohort libraries and all emulator binaries are unchanged). In an empty secondary
Android user on the headless landscape 16 KiB AVD, Settings grant/Back triggers
automatic setup and library return; the discovered owned GBA ROM launches
internally. This is not a second newly created AVD or universal acceptance.
First-install failure was reproduced in the original fresh AVD/user before repair.
Executable C++ permission regressions fail before and pass after. Release remains
unqualified; black library icons and six extra-core alignment errors in this APK
are still recorded. Five extra aligned cores have since entered normal staging,
but that change requires a new APK build. MAME is still unresolved.

## October 4: complete build uses the reviewed source kit

`build-portable.sh` now selects `build/source-frontend` and the checked-in
`source-frontend-artifact-lock.json` unless explicit paired inputs are supplied.
Install the already-built, reviewed flattened kit with
`python3 unified-android/tools/install_source_frontend.py --source <kit>`.
It verifies all 49 hashes and alignments, preserves unknown existing kits, and
is idempotent for identical inputs. This is staging, not a new source build.
The upstream build helpers/source lock described below remain the source recipe.

Complete normal build `9672d342...c974` passes package/one-app checks with all
19 required systems and LSFG retained. Its frontend is byte-identical to the
previous source-kit runtime candidate. Release signing remains blocked. Six
extra core libraries remain unaligned in this normal build (including five
repairs still isolated in QA); a new 16 KiB simulator visibly warns about page
compatibility on first launch. Do not describe this as whole-APK qualification.
See `docs/qa/android-portability-2026-10-04-portable-integration/`.

## October 4: normal packager accepts an explicit source-built kit

`unified-android/build.sh` now accepts the paired qualification inputs
`LUCENT_SOURCE_FRONTEND_DIR` and `LUCENT_SOURCE_FRONTEND_LOCK`. The first is a
flattened directory containing the complete 49-library source-built cohort; the
second is its reviewed hash/alignment lock. Both are required together. Release
signing rejects this opt-in until release qualification is complete.

`stage_source_frontend.py` validates every input and the complete decoded cohort
before copying, preserves emulator libraries, then verifies all copied bytes.
The final one-app verifier receives the same explicit lock; manifest, DEX,
all-system packaging and other existing checks remain enabled. Without this
opt-in, the legacy native patch path remains unchanged.

Actual 49-library staging and 12 staging/preflight regression tests pass in
`docs/qa/android-portability-2026-10-04-software-pages/`. This establishes staging
and preflight behavior, not a completed full normal-build or fresh-install test.
The earlier source-kit APK runtime results below remain separate evidence.

## October 4, 2026: isolated source migration now builds

The historical "does not compile Qt" and toolchain-blocked statements below
describe the normal pinned-APK packaging path, not the new isolated candidate.
`unified-android/qt-source-lock.json` and the `build_qt_*`, `build_apng_android.sh`
and `build_pegasus_source_android.sh` helpers now build matching Qt 5.15.10,
OpenSSL 1.1.1t and Pegasus `6b322063` from pinned archives with NDK 27/API 23.
They do not replace production staging. All 45 required Qt libraries/plugins,
the frontend, OpenSSL pair and libc++ are 16 KiB aligned. A standalone strict
Android 16/16 KiB loader accepts the full cohort; the old QtCore is rejected.
The source patches preserve the late-gamepad null guard and in-window launch
bookkeeping. APNG remains enabled; its pinned libpng decoder is linked explicitly.

Isolated signed candidate `227e34f2...5263b` replaces only those 49 libraries in
the complete `a1949290...deb586` APK. Retained Java/DEX, manifest, QML resource
bundle, product theme and emulator payloads are byte-identical. Old JNI exports
remain present. All-19 packaging and explicit source-cohort one-app checks pass;
57 focused host tests pass. The regular verifier's legacy native checks remain
the default; `--source-frontend-lock` requires an explicit host-side identity
lock for all 49 libraries and does not waive the other one-app checks.

Bounded runtime checks now cover the same APK on both offline headless landscape
Android16 page-size configurations. 16KiB PSX restores into a fight and exits;
PS2 reaches an actual match and exits but still has audio underruns. 4KiB DS
restores gameplay and exits twice; second restore logs success but then shows a
boot logo after a low-health session, so that restoration remains inconclusive.
Both AVDs are shut down; Thor was untouched. These are preserving updates of
existing QA fixtures, not fresh empty-data installations. Normal build staging
is unchanged and source-kit integration is still pending.

This is not a release. Whole-APK strict 16 KiB still fails for 19 other core
libraries. No new Qt version, emulator removal, audio or universal compatibility
acceptance is implied. See
`docs/qa/android-portability-2026-10-04-qt-source/` for exact hashes and evidence.

## Historical shipped dependency audit

Evidence-backed record of which Qt libraries the EmuFusion APK actually ships,
which of them can be dropped, and what the shipped versions are. Written while
auditing whether `libQt5Gamepad_arm64-v8a.so` could be removed from the package.

Every measurement below was taken from the decoded upstream base under
`unified-android/build/work/apk/`, which is produced by `unified-android/build.sh`
from the checksum-pinned upstream Pegasus APK
(`pegasus-fe_alpha16-105-g6b322063_android64.apk`,
SHA-256 `e595be198bfd21c1855eaf563d5af0deae9c9601e6efb195ed299f2065287c67`).
EmuFusion does not compile Qt; it repacks the Qt that upstream Pegasus's CI linked.

## Conclusion: libQt5Gamepad cannot be removed

**It was not removed. Removing it would produce an APK that cannot start.**

`libpegasus-fe_arm64-v8a.so` has a hard `DT_NEEDED` entry on it:

```
$ llvm-readelf -d unified-android/build/work/apk/lib/arm64-v8a/libpegasus-fe_arm64-v8a.so
  0x0000000000000001 (NEEDED)  Shared library: [libQt5Gamepad_arm64-v8a.so]
```

That is a link-time dependency of the frontend binary itself, not an optional
plugin. `dlopen()` of `libpegasus-fe` resolves `DT_NEEDED` eagerly, so deleting
the `.so` makes the very first `System.loadLibrary()` in the Qt bootstrap fail
with `dlopen failed: library "libQt5Gamepad_arm64-v8a.so" not found`, before any
EmuFusion code runs.

The dependency is real, not a stale `--no-as-needed` artifact. The frontend
binary carries 186 gamepad-related dynamic symbols, of which the `QGamepad*`
entries are undefined imports satisfied only by that library, for example:

```
UND _ZN15QGamepadManager8instanceEv
UND _ZNK15QGamepadManager17connectedGamepadsEv
UND _ZN15QGamepadManager23gamepadButtonPressEventEiNS_13GamepadButtonEd
UND _ZN21QGamepadKeyNavigationC1EP7QObject
```

Three further packaging facts make removal worse, not better:

1. `res/values/arrays.xml` lists `<item>arm64-v8a;Qt5Gamepad_arm64-v8a</item>`
   in `qt_libs`. The Qt bootstrap `dlopen`s exactly what that array names, so the
   array entry would have to be deleted too — and doing so only moves the failure
   from the bootstrap to the frontend's own `DT_NEEDED` resolution.
2. `libplugins_gamepads_androidgamepad_arm64-v8a.so` is named in `load_local_libs`
   and is itself `NEEDED`-linked against `libQt5Gamepad_arm64-v8a.so`. It is
   loaded unconditionally at startup.
3. Patching `DT_NEEDED` out of the prebuilt frontend would leave Pegasus's
   gamepad-configuration UI calling into symbols that no longer resolve, which
   is a latent crash rather than a fix.

The only sound way to drop Qt Gamepad is to rebuild Pegasus from source with
`QT -= gamepad` and the gamepad-configuration UI removed. That needs the Qt
Android toolchain that is currently blocked, so it belongs to the Qt migration
work, not to packaging.

## Late Android gamepad event null guard

The independent main-thread crash recorded on 2026-08-09 at 15:38:31 is now
root-caused. The tombstone reported a null `x0` in `QObject::thread()` and a
return address at relative offset `0x852c`. Mapping the loaded-library ranges,
dynamic relocation for `QObject::thread()`, and that return address identifies
`QAndroidGamepadBackend::handleKeyEvent()` in
`libplugins_gamepads_androidgamepad_arm64-v8a.so`, specifically its second
`FunctionEvent::runOnQtThread()` branch.

Qt Gamepad 5.15 implements that helper as:

```cpp
if (qApp->thread() == QThread::currentThread())
    func();
else
    qApp->postEvent(receiver, new FunctionEvent(func));
```

Android can deliver a final controller key event after Qt has cleared `qApp`.
The helper then calls `QObject::thread()` with a null receiver. The correct
behavior at that point is to discard the late event because there is no Qt
application or event queue to receive it.

`unified-android/tools/patch_qt_android_gamepad_null_guard.py` applies the
equivalent `if (!qApp) return` guard to both key-event branches in the exact
checksum-pinned ARM64 plugin. Each branch uses `cbz x0` to the function's
existing successful cleanup path; the original `adrp`+`add` vtable address is
folded into an equivalent `adr` so the guard fits without a trampoline. The
patcher locks the complete input SHA-256, both offsets, and all input/output
bytes, and rejects drift or repeat application. `verify_one_app_apk.py` rejects
an APK missing either guard. This is source- and disassembly-verified but still
requires a serialized physical-controller regression after the next immutable
APK is built.

## The licensing premise behind the removal request was wrong

The removal was proposed on the belief that Qt Gamepad is GPL-3.0/commercial
only in Qt 5.15, and would therefore impose GPL independently of Pegasus. That
is not the case.

`qt/qtgamepad` branch `5.15` ships both `LICENSE.GPL` and `LICENSE.LGPLv3`, and
its sources carry the `$QT_BEGIN_LICENSE:LGPL3$` header — commercial, **LGPLv3**,
or GPLv2-or-later at the recipient's option. Qt Gamepad is therefore on exactly
the same LGPL-3.0 footing as the other Qt modules in the package, and removing it
would not have changed EmuFusion's licensing position at all.

### The GPL-only Qt module in the package is Qt Quick Timeline

Found while checking the above. `libqml_QtQuick_Timeline_qtquicktimelineplugin_arm64-v8a.so`
comes from `qt/qtquicktimeline`, whose `5.15` branch ships **only** `LICENSE.GPL2`
and `LICENSE.GPL3` — there is no LGPL option. Its sources carry
`$QT_BEGIN_LICENSE:GPL$` and grant "version 3 or (at your option) any later
version approved by the KDE Free Qt Foundation".

This has no practical consequence today: EmuFusion is already a modified Pegasus
distribution conveyed under GPLv3, and GPL-3.0-or-later material may be conveyed
under GPL-3.0. It is recorded in `THIRD_PARTY_NOTICES.md` rather than removed,
because:

- the EmuFusion theme never imports `QtQuick.Timeline` (`theme/theme.qml` imports
  only `QtQuick`, `QtMultimedia`, `QtGraphicalEffects` and `SortFilterProxyModel`),
  so it is a genuine removal candidate on size grounds; but
- QML plugin resolution goes through the compiled `assets/android_rcc_bundle.rcc`
  qmldir set, so deleting the `.so` alone leaves a dangling qmldir entry; and
- it buys no licensing relief, since the GPL obligation already exists via Pegasus.

Revisit it only if a Qt rebuild happens anyway, or if APK size is the goal.

## Shipped versions

### Qt 5.15.10

`docs/HANDOVER-2026-08-07.md:587` says 5.15.10 and `aqtinstall.log` mentions the
`qt5_5152` (5.15.2) repository path. The binaries settle it — the shipped build
is **5.15.10**, and the `aqtinstall.log` line records a later, separate attempt
to obtain a local Qt toolchain, not the Qt that is packaged:

```
$ strings -a unified-android/build/work/apk/lib/arm64-v8a/libQt5Core_arm64-v8a.so
Qt 5.15.10 (arm64-little_endian-lp64 shared (dynamic) release build; by Clang 9.0.9 ...)
```

Only `libQt5Core` carries the build string; the other Qt libraries in the package
are stripped of version strings, but they are the matching module set from the
same upstream link and are treated as 5.15.10.

### OpenSSL 1.1.1t (7 Feb 2023)

```
$ strings -a unified-android/build/work/apk/lib/arm64-v8a/libcrypto.so | grep '^OpenSSL '
OpenSSL 1.1.1t  7 Feb 2023
```

`libssl.so` reports the same version. Their `SONAME`s are `libcrypto.so.1.1` and
`libssl.so.1.1`; they are packaged under the flattened names `libcrypto.so` /
`libssl.so` and resolved through the `bundled_libs` array
(`arm64-v8a;crypto`, `arm64-v8a;ssl`).

**1.1.1 is pre-3.0, so the licence is the dual OpenSSL/SSLeay licence, not
Apache-2.0.** Apache-2.0 applies only from OpenSSL 3.0 onwards. OpenSSL 1.1.1
also reached end of life on 2023-09-11, so this is an unmaintained TLS stack.

## Complete non-Lucent native payload

15 Qt modules, 16 Qt plugins, 14 QML plugins, plus:

| Library | Origin | Licence |
| --- | --- | --- |
| `libpegasus-fe_arm64-v8a.so` | Pegasus Frontend `6b322063` | GPL-3.0 |
| `libcrypto.so`, `libssl.so` | OpenSSL 1.1.1t | OpenSSL/SSLeay dual |
| `libc++_shared.so` | LLVM libc++ (Android NDK) | Apache-2.0 WITH LLVM-exception |

All three, plus the Qt set, are now described in `THIRD_PARTY_NOTICES.md`.
`tools/tests/test_licence_notice_gate.py` fails the test suite if a Qt or
OpenSSL library is packaged without a matching notice entry, and
`unified-android/build.sh` runs the same gate at package time.

## Open compliance decisions for the owner

These were found during the same audit. They are recorded rather than changed,
because each needs an owner decision or touches a file owned elsewhere.

### 1. GPL-3.0-only vs GPL-3.0-or-later — needs a one-line edit to `LICENSE`

`LICENSING.md` states GPL-3.0-**only**. The notice paragraph at the top of
`LICENSE` still carries the FSF boilerplate "either version 3 of the License, or
(at your option) any later version", which is the GPL-3.0-**or-later** grant.
They contradict each other, and the notice — not the prose — is what a recipient
relies on.

`LICENSING.md` now states the intent explicitly (GPL-3.0-only) and flags the
conflict. To finish the fix, the second sentence of `LICENSE` should read:

> under the terms of the GNU General Public License as published by
> the Free Software Foundation, version 3 of the License.

GPL-3.0-only is also the licence that the combined work actually has to be: the
qualification payload already includes GPL-3.0-only cores (ARMSX2, Virtual
Jaguar). Upstream Pegasus is GPL-3.0-or-later, which may be conveyed under
GPL-3.0, so narrowing is permitted.

### 2. Release repository slug is wildonrio

All three surfaces now agree on `github.com/wildonrio/pegasus-lucent`:
`release-manifest.json` asset URLs, `UpdateManager`'s latest-release API and
download prefixes, and `README.md`. The former `tyler-bam-ai/pegasus-lucent`
publish fork is no longer a release channel.

### 3. `release-manifest.json` version is stale

It advertises `3.2.0` (`themeVersion`, `companionVersionName`, `companionVersionCode: 74`)
while `unified-android/build.sh` builds `VERSION_NAME=3.2.15` / `VERSION_CODE=89`.
The manifest must be regenerated as part of whatever publishes 3.2.15, or the
updater will keep offering an older build than the one installed.
