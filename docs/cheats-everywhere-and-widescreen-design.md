# Cheats everywhere and the widescreen hack — design (2026-09-06)

Owner request: download every cheat available for every game on every
system as part of the per-game metadata update (the pass that fetches box
art, ratings, videos), show every downloaded cheat as an on/off switch in
the in-game cheat menu, and add a per-system "widescreen hack" option that
is off by default and, when on, produces real widescreen geometry the way
Dolphin does (projection/FOV, not stretching).

Another agent is editing the presentation/frame-generation code in the
same working tree. Everything here is therefore additive: new classes and
new files, plus a handful of one-line hooks in files that agent is not
editing. No APK is built or installed by this work; the next build picks
the code up automatically because `unified-android/build.sh` globs every
`.java` under `unified-android/src`, `android-companion/src` and
`android-launch-bridge/src`.

## 1. What exists (verified 2026-09-06)

- Model: `lucent/cheats/{Cheat,CheatDatabase,CheatSelection,CheatPanelModel,
  CheatPanelSnapshot}`; `Cheat{id,name,description,code}`; games keyed by
  `CheatDatabase.key(system, title)` = normalised system + normalised title
  (the runtime title is the ROM file stem).
- Aggregation: `preview/cheats/CheatCatalog.forGame(...)` merges the bundled
  `assets/cheats/cheat-database.json`, the Dolphin catalog
  (`DolphinCheatCatalog`, keyed by the disc ID read from raw ISO headers),
  the downloaded RetroArch `libretro-cheats.zip` (`CheatArchive`, queried per
  game, never expanded), and the user's `files/cheats/cheats.json` override.
- Selection: `files/cheats/selection.json` (`CheatStore`), toggled through
  `CheatControl.setEnabled` (companion `/cheats/set`) and the in-game panel
  (`EngineSession.setCheatEnabled`).
- Live application: libretro `retro_cheat_reset/retro_cheat_set` through
  `LibretroHost.applyCheats` / `ExperimentalGlesLibretroHost` for the cores
  listed in `LibretroEngineSession.supportsLiveCheats` and
  `PpssppGlesEngineSession.supportsLiveCheats`. Known gaps: SameBoy's
  pinned `retro_cheat_set` is an empty stub; Dolphin refuses codes unless
  `dolphin_cheats_enabled` is on (and `retro_cheat_reset` re-reads
  `User/GameSettings/<GameID>.ini`, which is the delivery path for new
  codes); PPSSPP runs a code once unless `ppsspp_cheats` is on; the
  vulkan-libretro runtime (ARMSX2, Azahar) has no cheat bridge; flycast and
  MAME stubs; the native adapters (Cemu, Eden, aPS3e) have no cheat ABI but
  read file-based patches at boot.
- Update: `UpdateManager` downloads the whole libretro archive once per
  manifest version. Per-game enrichment runs in `ImportManager.runScan`
  for newly imported games (box art, background, video, scores).
- Widescreen: one boolean (`WidescreenSettings`, default on) that only
  switches Dolphin's emulated Wii SYSCONF 16:9 flag; every hack key is
  pinned off in the native core-option table
  (`lucent_libretro_host.c register_core_variable_defaults`).

## 2. Cheat sources per system

The device fetches from upstream at the owner's request; EmuFusion bundles
and redistributes only the licensed catalogs it already ships. Each source
carries `license` and `bundled=false`; unlicensed community collections are
never copied into the APK or the repo, only fetched to the owner's device.
Every source is switchable in `files/cheats/sources.json` (all on by
default, per the owner's "every possible cheat").

| System | Source (bulk archive, cached 7 days) | Keyed by | Format |
|---|---|---|---|
| nes, snes, gb, gbc, gba, megadrive, mastersystem, gamegear, atari2600, pcengine, saturn, segacd, sega32x, jaguar, colecovision, intellivision | libretro `cheats.zip` (already installed) | No-Intro title | `.cht` |
| n64 | libretro `cheats.zip`; mupen64plus `mupencheat.txt`; Project64 `Config/Cheats/<title>.cht` | title; header CRC1-CRC2-C | GameShark pairs |
| psx | libretro `cheats.zip`; DuckStation chtdb `releases/download/latest/cheats.zip` | title; serial | `.cht`, DuckStation cht |
| ps2 | PCSX2 `pcsx2_patches` `releases/download/latest/patches.zip` (widescreen + patches); `xs1l3n7x/pcsx2_cheats_collection` `archive/master.zip` (gameplay cheats) | `SERIAL_CRC` / `CRC` (ELF CRC32) | pnach |
| psp | libretro `cheats.zip` (`Title [Region] [SERIAL].cht`); Saramagrean `CWCheat-Database-Plus-/master/cheat.db` | serial (`_S ULUS-10041`) | CWCheat `_C0/_L` |
| gamecube, wii | bundled Dolphin catalog; `https://codes.rc24.xyz/txt.php?txt=<GAMEID>` (per game, GameHacking mirror) | 6-char game ID (+ revision) | Gecko/AR |
| wiiu | `cemu_graphic_packs` `releases/latest` zip (CC0) | title IDs in `rules.txt` | graphic pack rules/patches |
| nds | libretro `cheats.zip` (derived from DeadSkullzJr) | No-Intro title | AR pairs |
| 3ds | FlagBrew Sharkive `releases/latest/download/3ds.json` (GPL-3) | 16-hex title ID | Gateway lines |
| switch | HamletDuFromage `switch-cheats-db` `contents_complete.zip` + `versions.json`; Sharkive `switch.json` | title ID + build ID | dmnt lines |
| ps3 | RPCS3 patch API `https://rpcs3.net/compatibility?patch&api=v1&v=1.2`; chidreams `Artemis-Patch-Collection-RPCS3` `imported_patch.yml` | serial (+ version) | RPCS3 patch YAML |
| dreamcast | libretro `cheats.zip`; bucanero `dreamcast-cheats` markdown | title / IP.BIN product id | `.cht`, raw codes |
| arcade, neogeo | FBNeo-cheats `archive/master.zip`; spludlow MAME cheats `latest.txt` -> `<ver>.zip` | romset name | FBNeo ini, MAME xml |

## 3. Identity extraction (at update time, once per game)

`CheatGameIdentity` (new, pure Java, host-testable) reads what a source
needs directly from the ROM, and the resolved identity is stored in the
per-game cheat file so the runtime never re-derives it:

- n64: header CRC1/CRC2 at 0x10/0x14 (byte-swap for `.v64`/`.n64`).
- psx/ps2: ISO9660 walk to `SYSTEM.CNF` for the serial (`BOOT2 =
  cdrom0:\SLUS_123.45;1`), PS2 ELF CRC32 (PCSX2's CRC is the CRC32 of the
  boot ELF). `.cue/.bin` and `.iso` supported; `.chd` is not decodable on
  the Java classpath, so CHD games fall back to serial-in-filename, then
  title matching.
- psp: `PSP_GAME/PARAM.SFO` `DISC_ID` from `.iso` (ISO9660); `.cso` falls
  back to the libretro `[SERIAL]` file-stem match by title.
- gamecube/wii: 6-char ID at offset 0 of raw ISO/GCM; RVZ/WIA disc header
  (the WIA "disc" struct carries the raw disc header) so compressed dumps
  get an ID too.
- nds: game code at 0x0C (4 chars) and header CRC at 0x15E.
- 3ds: `.3ds` (NCSD) partition 0 NCCH program ID; `.cia` title ID from the
  TMD.
- switch: `[0100...]` title ID in the file name, else `versions.json`
  title match; build IDs from `versions.json` (all builds for the title are
  written so Eden picks the one that matches the running executable).
- ps3: `PS3_GAME/PARAM.SFO` `TITLE_ID` and `APP_VER`.
- wiiu: `meta/meta.xml` `title_id` for loose dumps; pack `titleIds` by
  title match for `.wux/.wud`.
- arcade: file stem = romset name.

At import the candidate's original file name is still available; the
downloader runs before the import renames anything it needs, and it also
records the original name so serial regexes keep working after a rename.

## 4. Per-game cheat file (the update step's output)

`files/cheats/downloaded/<canonical-system>/<normalised-stem>.json`, the
existing `CheatCatalog` JSON shape plus provenance and delivery metadata
that the parser ignores if absent:

```json
{"schemaVersion":2,"system":"ps2","title":"Shadow of the Colossus",
 "identity":{"serial":"SCUS-97472","crc":"7D6F5B0E"},
 "fetchedAt":"2026-09-06T21:00:00Z",
 "games":[{"system":"ps2","title":"Shadow of the Colossus","cheats":[
   {"id":"pcsx2ws-...","name":"Widescreen 16:9","description":"PCSX2 patches • SCUS-97472_7D6F5B0E.pnach",
    "code":"patch=1,EE,...","source":"pcsx2-patches","delivery":"boot","tags":["widescreen"]}]}]}
```

`CheatCatalog.forGame` merges this file into the aggregate right before the
user override (one added line in the existing method), so the engine
sessions, the companion `/cheats/list`, and the in-game panel all see the
rows with no other change. `delivery` is `live` (retro_cheat_set),
`boot` (written into the engine's own patch/cheat files before load and
applied on the next launch), or `unsupported` (downloaded and listed, but
the packaged engine cannot consume it yet; the row says so).

## 5. Delivery per engine

- Live (unchanged): mesen, mesen-s, mgba, gearsystem, swanstation,
  melonds-ds, fuse, virtualjaguar, mupen64plus-next, ppsspp, dolphin.
  Two host overrides make the last two real: `dolphin_cheats_enabled=enabled`
  and `ppsspp_cheats=enabled` in the native core-option table.
- Dolphin: downloaded Gecko/AR codes are also written into
  `<per-game save dir>/User/GameSettings/<GAMEID>.ini` (the pinned libretro
  Dolphin core always resolves its user directory as `<save_dir>/User` when
  the frontend supplies one, which EmuFusion always does; the disc-side
  `engine-system/dolphin` root has no `User` tree Dolphin reads)
  (`[Gecko]`/`[ActionReplay]`, every code listed but none named in an
  `_Enabled` section) before launch, because `retro_cheat_reset` reloads
  that INI -- Dolphin's codes default to disabled on load, so the live
  session's own `retro_cheat_set` calls are what turn the current selection
  on after every reset -- and `retro_cheat_set` only accepts bodies the INI
  contains.
- PPSSPP: CWCheat lines are written to
  `<per-game save dir>/PSP/Cheats/<DISCID>.ini` before launch; live toggles
  keep working through `retro_cheat_set`.
- ARMSX2 (ps2): enabled cheats are written as
  `<engine-system>/pcsx2/cheats/<CRC>.pnach` (one file per CRC variant of
  the serial; PCSX2 loads the one matching the running ELF) before launch;
  `boot` delivery.
- Azahar (3ds): `<engine-system>/azahar/cheats/<TITLEID>.txt` (Gateway
  format, enabled cheats only); `boot`.
- Eden (switch): `<engine-system>/eden/load/<TITLEID>/EmuFusionCheats/cheats/<BUILDID>.txt`
  for every known build ID; `boot`.
- aPS3e (ps3): `<engine-system>/aps3e/config/patches/imported_patch.yml`
  plus `patch_config.yml` enabling the selected entries; `boot`.
- Cemu (wiiu): `<engine-system>/cemu/graphicPacks/EmuFusion_<id>/rules.txt`
  (+ `patches.txt`) and the `<GraphicPack>` entry in `settings.xml`; `boot`.
- flycast (dreamcast): `<engine-system>/dc/cheats/<title>.cht`; `boot`, and
  the core's own `reicast_widescreen_cheats` table for widescreen.
- MAME/FBNeo (arcade): downloaded and listed; `unsupported` until the
  packaged core gains a cheat path.

`CheatLaunchHooks.prepare(context, request, session)` (new) runs the boot
writers and registers the game's catalog in `CheatSessionRegistry` before
the session is returned from the factory in `InternalEngineBootstrap`
(three one-line wraps). `EngineSession`'s default `availableCheats /
enabledCheatIds / setCheatEnabled` consult that registry, so the pause-menu
"Cheats" button and the lower-display panel light up for every engine; the
engines with their own live override keep it. Boot-delivered rows render
with "applies on next launch" in the description.

## 6. Update integration

`GameCheatDownloader.fetch(context, systemFolder, title, rom, originalName,
cacheRoot)` (companion, new) is called from `ImportManager.runScan` inside
the per-game commit loop, with its own `setStatus("cheats", 0.76,
"Downloading cheats…")` line before the loop. Bulk archives are fetched at
most once per session per source (ETag/mtime cache under
`cacheRoot/cheats/`, bounded sizes, 7-day refresh, misses memoised 7 days),
then the game's rows are sliced out and written to the per-game file. A
manual "refresh cheats for the library" pass walks the existing metafiles
the same way (`fullDiscovery` block). Failures never block a game.

The companion writes `x-lucent-cheats: <count>` into the game's metadata
stanza so the theme can show that cheats are available.

## 7. Widescreen hack

- Preference: `WidescreenSettings.isHackEnabled()` (key `hackEnabled`,
  default false) plus per-system overrides (`hack.<system>` = on/off/auto).
  The existing `enabled` flag keeps its meaning (native Wii 16:9) and its
  default.
- `WidescreenHackPolicy` (new) maps a system to its true-geometry
  mechanism and reports availability honestly:

| System | Mechanism when on |
|---|---|
| n64 | `mupen64plus-aspect=16:9 adjusted`, `mupen64plus-169screensize=1920x1080` (GLideN64 widens the 3D projection and keeps 2D at 4:3) |
| psx | `swanstation_GPU_WidescreenHack=true`, `swanstation_Display_AspectRatio=16:9` (GTE projection widened) |
| ps2 | `armsx2_widescreen_patches=enabled`, `armsx2_aspect_ratio=16:9` (per-game FOV pnach from the shipped patches.zip) |
| gamecube, wii | per-game "16:9"/"widescreen" Gecko/AR codes from the catalog auto-enabled when present, else `dolphin_widescreen_hack=enabled` (projection hack) |
| dreamcast | `reicast_widescreen_cheats=enabled` (per-game FOV pokes from flycast's table), `reicast_widescreen_hack` only as fallback |
| psp | per-game "16:9"/"widescreen" CWCheat codes auto-enabled when the catalog has them |
| wiiu, switch, ps3 | native 16:9 already; reported as "native" |
| 3ds, nds, 2D consoles | not available (no geometry to extend); reported as "not available" |

- Plumbing without touching the JNI signatures: the policy writes
  `<engine root>/lucent-core-overrides.txt` (`key=value` per line) before
  launch, and `register_core_variable_defaults()` in
  `lucent_libretro_host.c` applies those overrides after its defaults.
  Overrides are launch-time only, matching the cores' "restart required".
- Companion endpoint `/settings/widescreen-hack` (GET/`?enabled=`/`?system=&mode=`)
  implemented in a new class and registered with a two-line route
  addition; theme settings slot "WIDESCREEN HACK".

## 8. Tests and docs

- New host tests: identity extraction from synthetic headers, each parser
  (DuckStation cht, pnach, CWCheat, Sharkive JSON, dmnt, RPCS3 yaml, Gecko
  txt, FBNeo ini, MAME xml), per-game file merge, boot writers' output,
  policy table, override-file parsing (native test).
- Existing pins kept: `test_cheat_catalog_updates.py` excluded-source ids
  remain in `reviewedButExcluded` (they are still not redistributed; the
  new `deviceFetched` section records that the device fetches them on the
  owner's request), `test_widescreen_enhancements.py` (the old flag's
  default stays true), `test_cheat_database.py`.
- Docs: `docs/cheat-system.md` and `docs/internal-core-aspect-contract.md`
  gain sections for the downloaded catalogs, boot delivery, and the hack.
