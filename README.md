# Lucent

Lucent is a single Android game-library and emulation application, with a standalone visual theme available for existing Pegasus Frontend users. The Lucent app supports conventional single-screen Android devices and dual-screen hardware such as the AYN Thor. Pegasus is the credited upstream frontend base; it is not a second app in the Lucent package.

## Download

The [latest release](https://github.com/wildonrio/pegasus-lucent/releases/latest) provides two downloads:

- **Lucent App** — the recommended, complete APK. It contains the Lucent frontend, importer and media services, updater, and in-process emulator runtime. No separate Pegasus, theme, controller, companion, or emulator app is required for qualified internal systems.
- **Lucent Theme** — the standalone theme ZIP for people who already use Pegasus and only want Lucent's visual experience. Android-only automation and services are not available from a QML theme alone.

Lucent checks this repository at startup and can also check manually from Settings. When an update is available it asks before downloading and opens Android's standard installer confirmation; Android does not permit a normal third-party app to silently replace itself.

## What Lucent adds

- Installs and selects the Lucent theme without touching ROM files.
- Scans internal and removable-storage Downloads folders for newly downloaded games.
- Discovers existing libraries in common ROM and emulation folders.
- Imports identified games into the correct collection and removes a source archive only after a verified import.
- Retrieves box art, wallpaper, and preview media on demand.
- Supplies the lower-screen preview service used on dual-screen Android hardware.
- Checks GitHub for app and theme updates at startup and on manual request.
- Keeps games without box art out of the visual library while retaining them in the archive list for manual inclusion.

## Installation

1. Download and install `lucent-<version>.apk` from the latest release.
2. Open Lucent and grant the storage permissions Android requests. The first library discovery runs automatically.
3. On an AYN Thor, the square Stop/Select button works as Select when tapped. Holding it continuously for one second saves and exits the active game back to Lucent.

## Source layout

- `theme/` — Pegasus QML theme and artwork.
- `android-companion/` — dependency-free Android companion, importer, preview service, media enrichment, and updater.
- `android-launch-bridge/` — legacy compatibility source; it is not packaged in the unified app.
- `unified-android/` — reproducible build that combines the credited upstream frontend runtime and every Lucent component into one release APK.
- `release-manifest.json` — signed-artifact versions, stable release URLs, and SHA-256 checksums used by the updater.
- `docs/in-process-emulation-plan.md` — durable three-phase specification for
  Lucent's own libretro/native game runtime, unified controls, and automatic
  save history. Its implementation snapshot distinguishes finished host code
  from cores that still require legal, state, performance, and device
  qualification before release routing changes.

## Privacy and safety

Lucent does not bundle games, firmware, or keys, and it does not download ROMs. Qualified open-source emulator engines are built into the Lucent APK with their licenses and source references. Library discovery and metadata generation happen on the device. Source files are deleted from Downloads only after a game import is verified.

## Licensing

The complete Lucent application is a modified Pegasus distribution licensed under GPLv3 (`GPL-3.0-only`), with corresponding source and reproducible build instructions provided in this repository. The standalone `theme/` package is independently available under the MIT License.

This application uses the **Qt toolkit, version 5.15.10, under the GNU Lesser General Public License version 3**. Qt is not modified by Lucent, its complete corresponding source is available from the Qt project, and the packaged Qt libraries can be replaced with your own build — see [SOURCE_OFFER.md](SOURCE_OFFER.md) for the procedure. The APK also bundles OpenSSL 1.1.1t under the dual OpenSSL/SSLeay license and LLVM libc++ under Apache-2.0 with the LLVM exception.

See [LICENSING.md](LICENSING.md), [SOURCE_OFFER.md](SOURCE_OFFER.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and [docs/qt-dependency-notes.md](docs/qt-dependency-notes.md).
