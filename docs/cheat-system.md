# Cheat catalogue and live-toggle contract

EmuFusion downloads the checksum-pinned official Libretro Database cheat
archive during its existing startup/update session. The archive stays
compressed and a game lookup reads only matching `.cht` entries. This avoids
expanding roughly 173 MB of text or parsing tens of thousands of games at
startup. The reviewed snapshot contains 28,301 game cheat files.
An independent full-archive scan counted 1,197,383 non-empty code rows;
1,190,125 remain after rejecting 7,258 unresolved placeholder rows. Runtime
deduplication reduces that further for each game before the menu is shown.

GameCube and Wii use a second, deterministic source: Action Replay and Gecko
sets shipped in the exact pinned Dolphin source tree. The generator accepts
only complete parseable code blocks, ignores OnFrame configuration patches,
deduplicates serialized bodies, and emits 4,071 switches across 261 exact
Dolphin Game IDs. The runtime reads the disc ID and revision before offering
these entries, so a title-only match cannot silently apply a code to the wrong
game revision. Compressed disc formats for which the frontend cannot read an
identity fail closed and show no Dolphin-derived rows.

## Matching and deduplication

- Libretro entries match canonical system plus normalized game/content title.
  An exact serial or filename region/revision wins when it is available. If
  the library cannot establish a variant, filenames for the same normalized
  title are aggregated and every row retains its source variant.
- An unresolved parameter (`??`, `XX`, and similar placeholders) is rejected.
- Identical normalized code bodies collapse to one switch, both within a
  source and across bundled/downloaded sources.
- A user's `files/cheats/cheats.json` remains an explicit per-game override.
- Enabled IDs persist per canonical system and normalized title.
- Both Android panels expose every retained row through bounded 96-row pages;
  even a 30,000-code N64 file never creates 30,000 Android Views at once.

## Live runtime boundary

A switch never restarts the game. The session serializes the complete enabled
set onto its render/lifecycle owner thread, calls `retro_cheat_reset`, then
replays enabled codes through indexed `retro_cheat_set` calls. Initial enabled
state is applied after content and save restoration and before normal play.

No cheat rows are advertised for a core whose exact packaged source has a
no-op or absent cheat callback. The pause-menu button remains disabled; the
controller shortcut may still open an explicit "no cheats available" sheet
instead of behaving like a dead input. Current audited live routes are:

- software libretro: Mesen, Mesen-S, SameBoy, mGBA, Gearsystem, SwanStation,
  melonDS DS, Fuse, and Virtual Jaguar;
- hardware libretro: Dolphin, PPSSPP, and Mupen64Plus-Next.

ARMSX2, Azahar, Flycast, FreeIntv, MAME, DOSBox Pure, and the native Cemu/Eden
adapters are not represented as working cheat engines: their current boundary
does not apply a live code. A large external database is not evidence that a
core can safely consume it. Those routes remain unavailable until they acquire
and prove an actual live ABI.

## Update and trust boundary

`release-manifest.json` pins archive version, URL, SHA-256, source, and license.
The updater downloads to cache with a 128 MiB compressed bound, validates the
digest and ZIP structure, and atomically replaces the installed archive while
retaining a rollback file. A failed catalogue update never prevents a game
from launching or removes the previous valid catalogue.

Source decisions and rejected databases are recorded in
`engines/cheats/sources.json`. Unlicensed community dumps are not copied merely
because they are public. Libretro Database attribution is shown in the in-app
legal notice and the project notices.

## Sources per system

Since 2026-09-06 the per-game metadata update (`ImportManager.runScan` →
`GameCheatDownloader.fetch`) also downloads every cheat available for the
game. The table lives in
`unified-android/src/com/thorium/preview/cheats/sources/CheatSourceRegistry.java`
and is mirrored, with licences and URLs, in `engines/cheats/sources.json`
(`deviceFetched`); `tools/tests/test_cheat_sources.py` keeps the two in sync.

| System | Source | Keyed by | Format | Delivery |
|---|---|---|---|---|
| nes, snes, gb, gbc, gba, megadrive, mastersystem, gamegear, sg1000, atari*, pcengine(cd), saturn, segacd, sega32x, jaguar, colecovision, intellivision, zxspectrum, dos | installed `libretro-cheats.zip` (sliced with `CheatArchive.forGame`, never re-downloaded) | title | RetroArch `.cht` | live where the core has a cheat ABI, else unsupported |
| n64 | libretro; Mupen64Plus `mupencheat.txt`; Project64 `Config/Cheats/<title>.cht` (listing by title, then CRC-verified) | header `CRC1-CRC2-C:CC` | GameShark pairs | live |
| psx | libretro; DuckStation chtdb `cheats.zip` | serial (`SLUS-00583`, plus revision-hash files) | DuckStation cht | live |
| ps2 | PCSX2 `patches.zip` (widescreen, fixes; group names kept as tags); xs1l3n7x cheats collection | `SERIAL_CRC` / CRC | pnach (group-aware) | boot |
| psp | libretro; CWCheat Database Plus `cheat.db` | serial (`ULUS-10041`) | `_L` lines joined by `+` (what PPSSPP's libretro front end rewrites) | live |
| gamecube, wii | bundled Dolphin catalog; `codes.rc24.xyz/txt.php?txt=<GAMEID>` per game | 6-char game ID | Gecko/AR lines joined by `+` | live (Dolphin INI written at boot by the delivery layer) |
| wiiu | Cemu community graphic packs (`releases/latest` asset) — one switch per pack naming the title id | title IDs in `rules.txt` | pack files concatenated with `#### file: <name>` markers | boot |
| nds | libretro (DeadSkullzJr-derived) | title | AR pairs | live |
| 3ds | FlagBrew Sharkive `3ds.json` | 16-hex title ID | Gateway lines | boot |
| switch | switch-cheats-db `contents_complete.zip` + `versions.json`; Sharkive `switch.json` | title ID + build ID (`buildid:` tags; every build ID recorded) | dmnt text | boot |
| ps3 | RPCS3 patch feed (`?patch&api=v1`); Artemis `imported_patch.yml` | serial + version (`ppu:`/`serial:`/`version:` tags) | patch YAML fragment | boot |
| dreamcast | libretro; bucanero dreamcast-cheats markdown | title / IP.BIN product ID | raw codes | boot |
| arcade, neogeo | FBNeo-cheats ini; Pugsy's MAME cheats (spludlow mirror, `latest.txt` → `<ver>.zip`) | romset name | FBNeo ini / MAME XML | unsupported (listed only) |

Every source is on by default and can be switched off in
`files/cheats/sources.json` (`{"sources":{"<id>":{"enabled":false}}}`).
Bulk archives are fetched at most once per process and cached for seven days
under `<cacheRoot>/cheats/<source>/` with ETag/Last-Modified revalidation;
misses are memoised for seven days; downloads are https-only, carry an explicit
User-Agent, use 15 s/45 s timeouts, are size-capped per source, and land via
`.part` + rename. Archives are read in place through `ZipFile` with entry
names validated and entry sizes bounded; nothing is expanded to disk.

## Identity

`CheatGameIdentity.identify(system, rom, originalName)` reads what the
sources key on straight from the ROM, never throws, and the result is stored
in the per-game file so the runtime never re-derives it:

- n64: CRC1/CRC2 at 0x10/0x14 and the country byte, for `.z64`, `.v64`
  (16-bit swapped) and `.n64` (32-bit swapped) → `n64Key`.
- psx/ps2: ISO9660 walk (`.iso`, `.bin`, `.cue`/`.bin` with MODE1/MODE2 raw
  sectors autodetected) to `SYSTEM.CNF` → `serial`; ps2 also reads the boot
  ELF and computes PCSX2's "CRC" (the XOR fold of every little-endian 32-bit
  word, which is what names `SERIAL_CRC.pnach`). `.chd` is not decodable on
  the Java classpath and falls back to a serial in the file name, then title.
- psp: `PSP_GAME/PARAM.SFO` `DISC_ID` → `serial`; `.cso` falls back to the
  serial in the libretro file name.
- gamecube/wii: 6-char ID and revision from raw ISO/GCM, RVZ/WIA (disc header
  at 0x58), WBFS (0x200) and CISO (0x8000) → `gameId`, `discIdentity`.
- nds: game code at 0x0C, header CRC16 at 0x15E, CRC32 of the first 512 bytes.
- 3ds: NCSD media ID (0x108) / NCCH program ID; `.cia` title ID from the TMD.
- switch: `[0100…]` title ID in the file name; build IDs come from
  `versions.json` and from the cheat archives themselves (`buildIds`).
- ps3: `PS3_GAME/PARAM.SFO` `TITLE_ID` and `APP_VER` for folder dumps.
- wiiu: `meta/meta.xml` `title_id` next to `code/*.rpx`; `.wux/.wud` match
  packs by title.
- dreamcast: IP.BIN product number from the `.gdi` third track or `.cue` data track.
- arcade/neogeo: the file stem is the romset name.

## Per-game file

`files/cheats/downloaded/<canonical-system>/<CheatDatabase.normalise(stem)>.json`,
written by `DownloadedCheatFile.write` (atomic, `.part` + rename) under the
ROM's on-disk stem and, when the import renamed the file, under the original
stem too. The shape is the `CheatCatalog` JSON plus provenance the older
parser ignores:

```json
{"schemaVersion":2,"system":"ps2","title":"Shadow of the Colossus",
 "identity":{"serial":"SCUS-97472","crc":"7D6F5B0E"},
 "fetchedAt":"2026-09-06T21:00:00Z","sources":["pcsx2-patches"],
 "games":[{"system":"ps2","title":"Shadow of the Colossus","cheats":[
   {"id":"pcsx2-patches-…","name":"Widescreen 16:9",
    "description":"PCSX2 patches (widescreen, fixes) • SCUS-97472_7D6F5B0E.pnach • Widens the FOV",
    "code":"patch=1,EE,…","source":"pcsx2-patches","delivery":"boot",
    "tags":["widescreen","widescreen-16:9","aspect:16:9","crc:7d6f5b0e"],"engineFormat":"pnach"}]}]}
```

Ids are `<source>-` + `sha256(system + "\n" + normalised code)[:24]`
(`CheatIdFactory`), so a re-download keeps the user's selection; libretro rows
reuse `CheatArchive`'s `libretro-` prefix and therefore the same ids.
`DownloadedCheatFile.read` returns plain `Cheat` rows whose description says
"applies on next launch" for `boot` rows and "not applied by the packaged
engine yet" for `unsupported` rows; `readDetailed` keeps source, delivery,
tags and engine format for the boot writers; `readIdentity` returns the
stored identity. Absence and corruption both read as "no cheats". The
companion writes `x-lucent-cheats: <count>` into the game's metadata stanza.

## Device-fetch legal posture

EmuFusion bundles and redistributes only the licensed catalogues it already
ships (Libretro Database, CC-BY-SA-4.0; Dolphin GameSettings, GPL-2.0+). The
community collections above — several of which declare no licence — are
never copied into the APK or this repository: `bundled=false` and
`redistribution=false` on every `deviceFetched` row, and the entries in
`reviewedButExcluded` remain excluded from redistribution. They are fetched
by the owner's own device, from the upstream host, on the owner's explicit
"download every possible cheat" request, stored only in that device's
`files/cheats/downloaded/`, and each can be disabled in
`files/cheats/sources.json`. Provenance (source name and file) is carried in
every row's description so the origin is visible in the cheat menu.
