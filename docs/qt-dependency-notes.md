# Qt dependency notes

Evidence-backed record of which Qt libraries the Lucent APK actually ships,
which of them can be dropped, and what the shipped versions are. Written while
auditing whether `libQt5Gamepad_arm64-v8a.so` could be removed from the package.

Every measurement below was taken from the decoded upstream base under
`unified-android/build/work/apk/`, which is produced by `unified-android/build.sh`
from the checksum-pinned upstream Pegasus APK
(`pegasus-fe_alpha16-105-g6b322063_android64.apk`,
SHA-256 `e595be198bfd21c1855eaf563d5af0deae9c9601e6efb195ed299f2065287c67`).
Lucent does not compile Qt; it repacks the Qt that upstream Pegasus's CI linked.

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
Lucent code runs.

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

## The licensing premise behind the removal request was wrong

The removal was proposed on the belief that Qt Gamepad is GPL-3.0/commercial
only in Qt 5.15, and would therefore impose GPL independently of Pegasus. That
is not the case.

`qt/qtgamepad` branch `5.15` ships both `LICENSE.GPL` and `LICENSE.LGPLv3`, and
its sources carry the `$QT_BEGIN_LICENSE:LGPL3$` header — commercial, **LGPLv3**,
or GPLv2-or-later at the recipient's option. Qt Gamepad is therefore on exactly
the same LGPL-3.0 footing as the other Qt modules in the package, and removing it
would not have changed Lucent's licensing position at all.

### The GPL-only Qt module in the package is Qt Quick Timeline

Found while checking the above. `libqml_QtQuick_Timeline_qtquicktimelineplugin_arm64-v8a.so`
comes from `qt/qtquicktimeline`, whose `5.15` branch ships **only** `LICENSE.GPL2`
and `LICENSE.GPL3` — there is no LGPL option. Its sources carry
`$QT_BEGIN_LICENSE:GPL$` and grant "version 3 or (at your option) any later
version approved by the KDE Free Qt Foundation".

This has no practical consequence today: Lucent is already a modified Pegasus
distribution conveyed under GPLv3, and GPL-3.0-or-later material may be conveyed
under GPL-3.0. It is recorded in `THIRD_PARTY_NOTICES.md` rather than removed,
because:

- the Lucent theme never imports `QtQuick.Timeline` (`theme/theme.qml` imports
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

### 2. Release repository slug is split three ways

- `release-manifest.json` asset URLs point at `github.com/tyler-bam-ai/pegasus-lucent`
- `android-companion/src/com/thorium/preview/UpdateManager.java:31` fetches the
  manifest from `raw.githubusercontent.com/wildonrio/pegasus-lucent/main/release-manifest.json`
- `README.md` links releases at `github.com/wildonrio/pegasus-lucent`

The updater therefore reads a manifest from one account and downloads assets from
another. Pick one canonical slug and make all three agree. `UpdateManager.java`
and `release-manifest.json` are owned by other workstreams and were not changed
here.

### 3. `release-manifest.json` version is stale

It advertises `3.2.0` (`themeVersion`, `companionVersionName`, `companionVersionCode: 74`)
while `unified-android/build.sh` builds `VERSION_NAME=3.2.15` / `VERSION_CODE=89`.
The manifest must be regenerated as part of whatever publishes 3.2.15, or the
updater will keep offering an older build than the one installed.
