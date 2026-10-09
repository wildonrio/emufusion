# External-emulator routing

Design note for the per-system launch-route backend **and** the Settings screen
that drives it. The `/route/*` HTTP surface described below now exists in
`PreviewService`; the QML that calls it lands separately (`theme/theme.qml`).

## Product rule

- **Internal is the default** for every system that has a bundled,
  release-qualified in-process engine. Nothing selects external automatically for
  a system that can run internally.
- **External is a per-system user choice**, never a default.
- **Systems with no internal engine route external automatically** so their games
  still launch. Today that is PS3, Wii U, Switch and 3DS (not yet integrated
  internally). They boot the external emulator **directly into gameplay** — no
  emulator menu.
- Choosing or needing external **installs nothing silently**. When the chosen
  emulator is absent the launch opens its official install source and lets
  Android's package installer confirm.

## Components

| Piece | Responsibility |
| --- | --- |
| `EngineRouteStore` | Single source of truth. Persists the per-canonical-system route + chosen emulator id, resolves the effective route, and produces the metadata `launch:` command. |
| `EmulatorCatalog` | Ordered candidate emulators per canonical system, each with a direct-launch recipe. Builds the `am start` recipe and the install intent. |
| `engines/external-emulators.json` | The per-system directory the picker presents: display name, package ids, and the one place a missing emulator is installed from (Play listing or website). Packaged as asset `external-emulators.json`. |
| `ExternalEmulatorDirectory` / `…Loader` | Model (`com.thorium.lucent.emulators`, host-testable) and the Android/`org.json` loader that fills it. |
| `InstalledPackages` | The single link-detection path, plus the Android 11+ package-visibility handling everything else depends on. |
| `CustomEmulatorSpec` / `CustomEmulatorStore` | Validation (pure) and per-system persistence for a user-supplied emulator. |
| `RoutePicker` | Everything the Settings screen asks for: the system list, the per-system options payload, and the tap that links or installs. |
| `RomLaunchActivity` + `RomFileProvider` | EmuFusion's own content-URI trampoline for scoped-storage emulators (Switch `.xci/.nsp`, Wii U `.wux/.wud`). Non-exported, own-uid gated, storage-confined, read-only. |
| `ImportManager.launchCommand` / `rewriteLaunchRoutes` | Emits the launch command per system via `EngineRouteStore`; re-emits every system's command after a route change. |
| `LaunchMetadataRouter` | Normalizes on-disk Pegasus metadata through the same `EngineRouteStore.launchCommand`. |

## Resolution (`EngineRouteStore.resolve`)

1. Explicit user **EXTERNAL** choice → EXTERNAL.
2. Explicit user **INTERNAL** choice → INTERNAL if an engine exists, else EXTERNAL
   (a stored preference never becomes unlaunchable).
3. No explicit choice → INTERNAL if an engine exists (`GameLaunchRouter.supportsSystem`,
   backed by `InternalEngineCatalog` / `Phase2QualificationCatalog`), else EXTERNAL.

`setRoute` refuses an INTERNAL choice with no engine, an EXTERNAL choice with no
catalog option, and an unknown emulator id, so an unlaunchable preference is
never persisted. A route change calls `ImportManager.rewriteLaunchRoutes`, which
regenerates fresh metadata, normalizes on-disk metadata, and requests a Pegasus
library reload so the new `launch:` lines take effect.

## Launch mechanism

Pegasus natively runs `am start` via `launchAmCommand`; EmuFusion only intercepts
its internal action. So the emitted command is:

- **Internal** → `MetadataGameLaunchCommand` (`am start -a <internal action> …`)
  which the patched `MainActivity` intercepts in-process.
- **External, path-accepting emulator** → `am start -n <pkg>/<activity> --es <ROM key> "{file.path}" --activity-clear-task`.
- **External, `ACTION_VIEW` emulator** → `am start … -d "file://{file.path}"`.
- **External, scoped-storage emulator** → `am start … -n com.thorium.preview/…RomLaunchActivity`,
  which grants a one-time read-only content URI and forwards into the emulator's
  gameplay Activity.
- **External but not installed** → `am start -a VIEW -d market://…` (or the
  release page) so the user can install; never a silent install.
- **No option at all** → empty command (fail closed).

## Per-system routing today

- **PS3** → no maintained Android emulator (RPCS3 has no Android port); stays
  explicitly optionless. It cannot launch on-device until an engine exists — an
  open product decision, not a routing bug.
- **Wii U** → **internal** in a build made with `LUCENT_INCLUDE_PHASE3_CEMU=1`
  (in-process Cemu native adapter, TV on display 0 and the GamePad/DRC view on
  the Thor's display 4). Falls back to external Cemu (content-URI trampoline)
  only when that flag was omitted, so no adapter is bundled and
  `NativeAdapterCatalog` fails closed.
- **Switch** → **internal** in a build made with `LUCENT_INCLUDE_PHASE3_EDEN=1`
  (in-process Eden native adapter); otherwise external Eden (content-URI
  trampoline).
- **3DS** → external Azahar (path-accepting) or RetroArch.

## The Settings picker

### What the user does

1. Settings lists every system with **Internal** or **External** beside it.
   Internal is shown, and is the default, for any system with a bundled engine —
   `RoutePicker` derives that from `EngineRouteStore.hasInternalEngine`, which is
   backed by the real `InternalEngineCatalog` state. It is never a hardcoded list.
2. Switching a system to External lists that system's emulators, in catalog
   order, each marked installed or not.
3. **Tapping an emulator that is not installed** opens its install source — the
   Play listing via `market://` (the Play app is the only thing that can install
   from one), or the project's own release page in EmuFusion's lower-display
   browser. Nothing is recorded.
4. **Tapping it again after installing** finds the package present and binds it
   to that system, and that system only.
5. **Custom** runs a guided setup for an emulator the catalog has never heard of.

The first row in each system's picker is **Automatic default**. It is selected
when that system has no explicit override. Pressing it calls `/route/clear` for
that system only and then reads `/route/resolve` before reporting the effective
result. Consequently, restoring automatic means built-in for a system with a
qualified internal engine and external for a system without one; the QML never
reimplements that policy. Clearing the route removes the chosen-emulator id but
does not delete a configured custom-emulator definition, so the user can select
that custom target again later without re-entering it.

The clear/read-back is shown as an in-progress operation and all three failure
points are visible in the picker: the clear request, the resolve request, and
the subsequent options refresh. A failed or malformed response is never
presented as a successful reset.

Steps 3 and 4 are the same request. `/route/link` reads install state fresh on
every tap and branches; the UI holds no state between the two taps, and there is
no path that binds an emulator which is not there.

### Endpoints (`PreviewService`, localhost:43821, GET, `Connection: close`)

| Endpoint | Effect |
| --- | --- |
| `GET /route/systems` | Every system with route, `internalAvailable`, `active` (has games) and `ready` (launching now does something). Read-only. |
| `GET /route/options?system=<id>` | The per-system picker payload: internal availability, current route, every external option with live install state and install destination, and the custom entry. Read-only. |
| `GET /route/resolve?system=<id>` | The effective route + chosen emulator, without the option list. Read-only. |
| `GET /route/set?system&route&emulator` | `EngineRouteStore.setRoute`. Refusals carry a `reason` sentence the UI shows. |
| `GET /route/clear?system` | Back to the automatic default. Its success payload uses the same effective-route fields as `/route/resolve`, plus `ok:true`. |
| `GET /route/link?system&emulator` | The tap. Installed → bound (`linked:true`); missing → install source opened (`linked:false`, `opened`). |
| `GET /route/custom?system&package&activity&delivery&romExtraKey` | Validate and store a custom emulator, then select it. `clear=1` removes it. Failures return `problems:[{field,message}]`. |

The four mutating endpoints sit in `THEME_CALLED_ENDPOINTS`, so — like every
other endpoint the theme calls — they are reachable without the per-boot control
token, and rely on the `Origin`/`Referer` rejection that blocks page-initiated
requests. The residual local-process risk is narrower than it looks: a route may
only be pointed at a catalog entry, and `/route/custom` refuses anything that is
not an **already installed** package exposing a **real exported activity**, so a
local caller cannot invent a target that does not already exist on the device.

A successful change runs `ImportManager.rewriteLaunchRoutes()` on a daemon
thread — walking the library inline would stall a control plane with only two
HTTP workers — and the existing `needsReload` flag is what tells the theme the
library has caught up.

### Native-adapter readiness and automatic routing

Switch and Wii U do not become automatically internal merely because their
research adapters are packaged. During the normal update/import scan,
`NativeAdapterPrerequisites` performs a bounded read-only search of readable
internal and removable storage roots and stores only `READY`/`NOT_READY` per
system. It never stores or returns the source path or a missing filename.

For Switch, valid production keys are the baseline. Firmware is optional and
title-specific; a valid archive is installed opportunistically when present.
For Wii U, a valid disc-key list is the baseline. The effective automatic route
is internal only when the adapter is hash-valid and readiness is `READY`.
Otherwise it is external. Explicit external choices remain external, while an
explicit internal choice degrades safely to external if later validation fails.
Every internal launch revalidates the private/user source before loading and
uses a generic failure message rather than a prerequisite checklist.

The preferred Switch external target is the official Eden application ID
`dev.eden.eden_emulator`; legacy Eden and Citron IDs remain fallback-compatible.
Its install source is <https://eden-emu.dev/downloads/> and the existing
one-time content-URI route launches the selected game directly.

### `engines/external-emulators.json`

The per-system directory the picker presents: `emulators[]` (id, display name,
package ids, `install: {kind: play|web, url}`, `verified`) and `systems{}`
(ordered `{option, app}` references). `option` is the `EmulatorCatalog` id that
gets persisted; `app` is the application the user installs. They differ only
where one app serves many systems — RetroArch is option `retroarch-psx` but app
`retroarch` — and collapsing them would either lose the per-system core or list
one download thirty times.

Two rules hold it honest:

- **It can only ever subtract.** A name here never makes an emulator launchable;
  `EmulatorCatalog` owns every recipe, and `test_settings_emulator_picker.py`
  asserts the two agree option-for-option and package-for-package. A missing or
  damaged asset degrades presentation only — the picker still enumerates the
  compiled catalog.
- **`packageIdsVerified` is `false`.** No package id in the file has been checked
  against a live Play listing or release page; they are the ids the shipping
  `EmulatorCatalog` already used. A per-entry `verified: true` while the file
  says otherwise fails the suite.

### Package visibility — the silent failure this feature is built on

From Android 11, an app targeting API 30+ sees only packages it declares in
`<queries>`. Everything else answers *exactly* as if it were not installed:
`getPackageInfo` throws, `getLaunchIntentForPackage` returns null, nothing logs,
no permission prompt appears. A picker built on a bare `getPackageInfo` would
degrade into "nothing is ever installed, tap forever".

EmuFusion still declares `targetSdkVersion 28`, so filtering is not active today
— which is exactly why the declarations are already in place, since raising the
target would otherwise break every emulator at once with no visible symptom:

- one `<queries><package>` entry per directory package id, generated by
  `tools/sync_external_emulator_queries.py` and kept in sync by the test suite;
- one `<queries><intent>` MAIN/LAUNCHER filter, which is what makes a **custom**
  emulator visible at all — a package chosen at runtime cannot be in a static
  list, so without it the guided setup could never confirm an install.

`QUERY_ALL_PACKAGES` is deliberately not requested; Play treats it as restricted
and the two declarations above answer the only question EmuFusion asks.
`InstalledPackages` is the single detection path, and tries both probes because
they fail differently under filtering.

### Custom emulators

`CustomEmulatorSpec` (pure, host-tested) validates the package id, activity
name, delivery mechanism and ROM extra key, and reports **every** problem at
once as `{field, message}` pairs the guided setup prints onto the form. It is
whitelist-only, for two reasons: the messages have to be actionable, and these
values are interpolated into the `am start` string Pegasus executes as a shell
command, which makes an unvalidated activity name argument injection rather than
a typo. Pointing a system at EmuFusion's own package is refused by name so it
cannot produce a launch loop.

`CustomEmulatorStore` then stores nothing until the device agrees: the package
must be installed and the named activity must exist and be exported. A stored
target whose app is later uninstalled resolves to null, so the system falls back
to the catalog rather than becoming unlaunchable, and the picker reports it as
needing setup again.

## Known tension: `verify_one_app_apk.py`

The one-app APK verifier (`unified-android/tools/verify_one_app_apk.py`) encodes
the **superseded** "internal is the only route" boundary. It will reject an APK
built with this workstream because:

- `RomLaunchActivity` is in its `FORBIDDEN_DEX_CLASSES` and is a 4th Activity
  outside its `ALLOWED_ACTIVITIES` whitelist, and
- `EmulatorCatalog` embeds external emulator package identities that appear in
  its `FORBIDDEN_DEX_IDENTITIES` list.

No manifest-attribute change can satisfy a name whitelist / identity blocklist.
Reconciling the verifier with the new authoritative product rule (updating
`ALLOWED_ACTIVITIES` to include the non-exported trampoline and narrowing the
identity ban to *launcher/home* components) is required before this ships, and is
out of scope here (the verifier must not be edited by this workstream).
