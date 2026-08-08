# Lucent licensing

Lucent is published in two forms with deliberately separate license scopes.

## Lucent application

The complete Android application combines a modified Pegasus Frontend runtime
with Lucent's Android integration, importer, media services, direct-launch
bridges, updater, and default theme. The combined application and all source
outside `theme/` are distributed under the **GNU General Public License,
version 3.0 only** (`GPL-3.0-only`). The complete license is in [`LICENSE`](LICENSE).

Pegasus Frontend is copyright Mátyás M. and its contributors. Lucent is not an
official Pegasus release and is not endorsed by the Pegasus project.

Known inconsistency: the notice paragraph at the top of [`LICENSE`](LICENSE)
still carries the Free Software Foundation's boilerplate wording "either version
3 of the License, or (at your option) any later version", which describes
`GPL-3.0-or-later`. **`GPL-3.0-only` is the intended and governing license for
the Lucent application**, and it is the license the combined work must carry,
because the qualification payload already includes `GPL-3.0-only` components.
Upstream Pegasus is `GPL-3.0-or-later`, which permits conveying the combined
work under GPLv3 alone. The exact wording change still needed in `LICENSE` is
recorded in
[`docs/qt-dependency-notes.md`](docs/qt-dependency-notes.md#1-gpl-30-only-vs-gpl-30-or-later--needs-a-one-line-edit-to-license).

## Qt

The application runs on **the Qt toolkit, version 5.15.10, used under the GNU
Lesser General Public License version 3** (`LGPL-3.0`). Lucent does not modify
Qt; the packaged Qt libraries are the ones linked into the checksum-pinned
upstream Pegasus Android build and are repacked unchanged.

The LGPLv3 text ships in the APK as `LICENSE-LGPL-3.0.txt` (source:
[`docs/licenses/LGPL-3.0.txt`](docs/licenses/LGPL-3.0.txt)); the GPLv3 text it
incorporates by reference is the same [`LICENSE`](LICENSE) file. Qt's complete
corresponding source, and the procedure for replacing the packaged Qt libraries
with your own modified build of Qt, are in
[`SOURCE_OFFER.md`](SOURCE_OFFER.md) and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

One packaged Qt component, the Qt Quick Timeline QML plugin, is offered under
GPL-3.0-or-later rather than LGPL and is conveyed here under GPLv3 like the rest
of the application. The APK also bundles OpenSSL 1.1.1t under the dual
OpenSSL/SSLeay license and LLVM libc++ under Apache-2.0 with the LLVM exception.
All of these are described in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Standalone Lucent theme

The contents of `theme/` may also be downloaded and used independently with an
existing Pegasus installation. That standalone theme is distributed under the
MIT License found in [`theme/LICENSE`](theme/LICENSE).

Bundling the theme into the Lucent application does not change the GPL terms
that govern the combined application as a whole.

## Corresponding source

The scripts and Lucent-authored source required to reproduce the distributed
APK are in this repository. The exact unmodified Pegasus base used by the build
is commit [`6b322063`](https://github.com/mmatyas/pegasus-frontend/tree/6b322063).
The reproducible transformation and packaging steps are in
[`unified-android/build.sh`](unified-android/build.sh). See
[`SOURCE_OFFER.md`](SOURCE_OFFER.md) for a complete source map.

Product names, console logos, emulator names, and other third-party marks and
artwork remain the property of their respective owners. Their use is for
identification and does not imply sponsorship or endorsement.
