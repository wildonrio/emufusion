# Built-in system inventory — 2026-09-06

## Scope and authoritative counts

This is a read-only inventory of the actual APK
`0a4a052d3fb4d9efe3d3a5a34e38f8f815ae1a58454d23995ff1452632733809`
and its source/runtime evidence. The APK SHA-256 was independently checked at
`unified-android/build/lucent-3.2.16-emufusion-plus-lsfg-internal-0a4a052d3fb4d9efe3d3a5a34e38f8f815ae1a58454d23995ff1452632733809.apk`.
It is a qualification build. **Built-in/routable does not mean qualified,
reliable, release-approved, or compatible with every game.**

| Inventory layer | Count | Meaning |
|---|---:|---|
| Acceptance matrix | 20 | The expected 19 console/handheld targets **plus Windows**; not the full built-in inventory. |
| Default internal-route-eligible canonical system IDs | 35 | 22 Phase 1 + 10 Phase 2 + 3 native-adapter systems, listed below. |
| Internal-route systems with dedicated theme cards | 34 | All of the above except ScummVM. |
| Complete theme platform catalog | 55 | Includes internal, external-only and unsupported platforms; excludes the aggregate All Systems card. |
| Discovery/metadata `GameSystems` catalog | 56 | Includes ScummVM, which the theme omits. |
| Packaged engine libraries | 30 | 27 libretro cores + 3 native adapters; excludes host/support libraries. |
| Runtime-verified engine factories | 29 | Virtual Jaguar is packaged but rejected; the other 29 registered. |

The menu is dynamic: a platform card appears only when its named collection
contains games. **Neither 19, 20, 34 nor 55 proves the device's current visible
card count.** The APK's nested `assets/emufusion-theme.zip/theme.qml` was
read directly and matches current `theme/theme.qml` SHA-256
`6357bd273ef7bcb09cac2365724446648cc57678de6de0732e86bfc189ff9920`.

## All 35 normal internal-route IDs

These are default engine owners when the catalog/runtime prerequisite gates
pass and no supported explicit External preference overrides them. If their
internal engine is unavailable, GameCube and Wii fail closed instead of
automatically falling back to External. PS3 is internal-only. Firmware, keys,
content validity and game compatibility remain separate launch requirements.

“Software/Canvas” means a software libretro video callback followed by the
direct-surface Canvas blit; on Thor this normally uses Hardware Canvas. It does
not mean an intermediate frame-generation renderer. “Software/GLES bridge”
distinguishes a software-producing core hosted by the Phase 2 GLES session.

| Canonical ID | Platform | Default engine | Current host / graphics API |
|---|---|---|---|
| `3ds` | Nintendo 3DS | `azahar` | Vulkan libretro |
| `amiga` | Commodore Amiga | `puae` | Software/GLES bridge |
| `amigacd32` | Amiga CD32 | `puae` | Software/GLES bridge |
| `apple2` | Apple II | `applewin` | Software/GLES bridge |
| `arcade` | Arcade | `mame` | Software/Canvas |
| `atari7800` | Atari 7800 | `prosystem` | Software/Canvas |
| `dos` | DOS | `dosbox-pure` | Software/Canvas |
| `dreamcast` | Sega Dreamcast | `flycast` | GLES libretro |
| `gamecube` | Nintendo GameCube | `dolphin` | GLES libretro |
| `gamegear` | Sega Game Gear | `gearsystem` | Software/Canvas |
| `gb` | Game Boy | `sameboy` | Software/Canvas |
| `gba` | Game Boy Advance | `mgba` | Software/Canvas |
| `gbc` | Game Boy Color | `sameboy` | Software/Canvas |
| `mastersystem` | Sega Master System | `gearsystem` | Software/Canvas |
| `megadrive` | Sega Genesis / Mega Drive | `blastem` | Software/Canvas |
| `n64` | Nintendo 64 | `mupen64plus-next` | GLES libretro |
| `nds` | Nintendo DS | `melonds-ds` | Software/Canvas |
| `neogeo` | SNK Neo Geo | `mame` | Software/Canvas |
| `neogeocd` | SNK Neo Geo CD | `mame` | Software/Canvas |
| `nes` | Nintendo Entertainment System | `mesen` | Software/Canvas |
| `ngp` | Neo Geo Pocket | `beetle-neopop` | Software/Canvas |
| `pcengine` | PC Engine / TurboGrafx-16 | `beetle-pce-fast` | Software/Canvas |
| `ps2` | PlayStation 2 | `armsx2` | Vulkan libretro |
| `ps3` | PlayStation 3 | `aps3e` | Native adapter / Vulkan |
| `psp` | PlayStation Portable | `ppsspp` | GLES libretro |
| `psx` | PlayStation | `swanstation` | Software/Canvas; see note below |
| `scummvm` | ScummVM | `scummvm` | Software/Canvas; no dedicated theme card |
| `sg1000` | Sega SG-1000 | `gearsystem` | Software/Canvas |
| `snes` | Super Nintendo | `mesen-s` | Software/Canvas |
| `switch` | Nintendo Switch | `eden` | Native adapter / Vulkan |
| `wii` | Nintendo Wii | `dolphin` | **Vulkan libretro override** |
| `wiiu` | Nintendo Wii U | `cemu` | Native adapter / Vulkan |
| `windows` | Windows / PC route | `dosbox-pure` | Software/Canvas; not Winlator or general modern Windows support |
| `wonderswancolor` | WonderSwan Color | `beetle-cygne` | Software/Canvas |
| `zxspectrum` | ZX Spectrum | `fuse` | Software/Canvas |

Aliases are not additional systems: for example `gc` resolves to `gamecube`,
`n3ds` to `3ds`, and `genesis` to `megadrive`.

SwanStation's registry renderer is `multi`, but the actual bootstrap selects
the hardware session only for `renderer=opengl`. SwanStation therefore enters
`LibretroEngineSession`, whose native constructor supplies no hardware context.
Do not advertise its upstream Vulkan/GLES capabilities as this route's API.
Similarly, PPSSPP's registry request and Dolphin's generic runtime label are
not sufficient: the packaged runtime is GLES for PSP, while current Java
explicitly overrides **Wii only** to Vulkan.

## Packaged experiments versus normal routes

- Phase 1 source opt-in defaults to `autoSelect=false`, but this APK's actual
  `assets/engine-qualification-opt-in.json` has **`autoSelect=true`**. Its 16
  selected engines own 22 normal system routes. The build performs this override
  under `LUCENT_AUTOSELECT_EXPERIMENTAL_CORES=1`.
- Phase 2 and native-adapter normal routes require explicit
  `libraryRouteSystems`. They are not inferred merely from a bundled library
  or from a registry's supported-system list.
- **Beetle Saturn** is packaged and registered, but has no normal Saturn route.
- **Play!** is packaged and registered, but has no normal PS2 route. Armsx2 is
  the default; the acceptance matrix allowing either engine does not change it.
- **Virtual Jaguar** is packaged but rejected by the current runtime catalog;
  it is not a working explicit route or a default Jaguar route.
- Flycast's broader registry lists Naomi/Atomiswave, but its normal route is
  Dreamcast only. These are not additional default built-ins.

All of these catalogs retain experimental/qualification gates; registration
and packaging are not release-approval or all-system QA evidence.

## External-only and unsupported menu platforms

The following **19 theme platforms have no default internal route** in this
APK, but do have external-emulator catalog options:

`odyssey2`, `atari2600`, `intellivision`, `atari5200`, `colecovision`, `c64`,
`atari800`, `amstradcpc`, `atarist`, `segacd`, `pcenginecd`, `3do`, `jaguar`,
`sega32x`, `saturn`, `virtualboy`, `wonderswan`, `psvita`, `msx`.

**Xbox and Xbox 360** are two additional theme platforms with neither a bundled
internal route nor a supported external catalog option. External options are
also available for many internal systems as explicit user choices; that does
not make those systems external-only. Apple II's external option is unsupported,
but its internal AppleWin route exists.

## QA snapshot and handoff warning

This inventory was audited before the root agent's new Wii run completed.
Check any subsequently written Wii evidence independently. Do not broaden a
single title/build pass to every title, engine or system in this inventory.

| Area | Latest retained evidence at this audit | Boundary |
|---|---|---|
| 3DS | [ABW transform candidate](qa/3ds-transform-candidate-2026-09-05/README.md) | **Current `0a4a`**: correct lower 1240x930 geometry, two wakes, movement/touch, ordinary Exit/save, same-PID restore and second Exit. One title; detach warnings and broader pacing/audio/FG qualification remain. |
| GameCube | [Mario Kart lifecycle](qa/gc-lifecycle-4a4f-2026-09-05-a/README.md) | **Previous `4a4f`**: post-wake acceleration/steering, normal Exit, same-PID relaunch, second Exit. Dolphin runtime-state restore remains quarantined; no `0a4a` regression in that report. |
| N64 | [Bounds-policy change](qa/gc-bounds-4a4f-2026-09-05/README.md) | Host fixtures retain N64 policy; shared-host device regression explicitly pending. |
| Wii | [Transport correction](qa/dolphin-transport-e3bf-2026-09-05/README.md), [Vulkan-test correction](qa/dolphin-vulkan-waw-9b0f-2026-09-05/README.md) | Older evidence; player-controlled gameplay not established there. The subsequent Vulkan-barrier check actually exercised GameCube GLES, leaving Wii's Vulkan path untested by that run. |
| PS3 | [ICO stall localization](qa/ps3-ico-stall-localization-2026-09-05/README.md), [rejected FIFO trial](qa/ps3-ico-atomic-fifo-2026-09-05/README.md) | Unresolved intro stall on older build; not fixed by inventory or packaging. |
| Wii U | [Resume](qa/wiiu-resume-5641-2026-09-05/README.md), [relaunch](qa/wiiu-relaunch-5641-2026-09-05/README.md) | Older `5641` bounded gameplay/wake/teardown; separate relaunch reached title only, not a second normal Exit. |
| Switch | [Native timestamps](qa/switch-direct-native-timestamps-2026-09-05/README.md) | Older `6951` gameplay/lifecycle evidence; measured direct pacing failed. No current-build qualification. |
| Other systems above | [Earlier strict-Off report](strict-off-physical-qa-2026-08-30.md) where applicable | No current `0a4a` per-system regression established by this audit. Earlier fixtures/reports do not certify today's shared host. |

**Scope mismatch to preserve:** an “all built-in systems” goal cannot silently
mean the historical 19. The checked-in acceptance matrix covers 20, while the
actual normal internal-route inventory is 35. A future agent must explicitly
name which scope it is testing and track the other systems as pending; it must
not infer completion from packaging counts or a subset of lifecycle passes.

## Source/evidence anchors

- `theme/theme.qml`: `rebuildVisibleSystems` at line 940; `systemCatalog` at
  line 5419. `android-companion/src/com/thorium/preview/GameSystems.java` is the
  broader discovery catalog.
- `unified-android/tools/runtime-acceptance-matrix.json`: 20 rows, including
  Windows. This is a QA target matrix, not the route authority.
- `android-companion/src/com/thorium/preview/GameLaunchRouter.java:37` resolves
  Phase 1, then explicit Phase 2 routes, then native adapters and prerequisites.
  `EngineRouteStore.java:70` applies default/explicit route policy.
- `unified-android/src/com/thorium/preview/game/InternalEngineCatalog.java:154`
  builds the auto-selected system map; `Phase2QualificationCatalog.java:305`
  and `NativeAdapterCatalog.java:94` enforce `libraryRouteSystems`.
- APK assets read directly: `engine-registry.json`,
  `engine-qualification-opt-in.json`, `phase1-engine-artifacts.json`,
  `phase2-engine-registry.json`, `phase2-qualification-opt-in.json`,
  `phase2-engine-artifacts.json`, `phase3-engine-registry.json`,
  `phase3-qualification-opt-in.json`, `phase3-engine-artifacts.json`.
  The corresponding source registries/opt-ins are under `engines/`.
- `unified-android/build.sh:680` stages Phase 1 and overrides auto-selection;
  line 708 stages the Phase 2 bundle. Current packaged native adapters are
  Eden, Cemu and aPS3e.
- `unified-android/src/com/thorium/preview/game/InternalEngineBootstrap.java:47`
  selects session factories; `PpssppGlesEngineSession.java:347` selects Wii
  Vulkan; `LibretroEngineSession.java:1654` is the software-output blit;
  `unified-android/native/lucent_libretro_jni.c:33` passes no hardware context
  for the software host. Native Vulkan profiles are recorded in
  `engines/{eden,cemu,aps3e}-source-lock.json`.
- `docs/qa/3ds-transform-candidate-2026-09-05/logcat.txt:226` onward records the
  current Phase 2/3 registrations; line 246 rejects Virtual Jaguar and line
  257 confirms **29** verified engine factories.
