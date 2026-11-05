# Widescreen Hack: goal, plan and status

Started 2026-11-04 at the owner's request. This file is the project's source of
truth; per-system results go in the sections at the end. `top20-by-critic.json`
holds the generated test lists (critic score, bundled metadata; one entry per
canonical title).

## What the owner asked for

- **True widescreen, not a stretch.** The playable area is expanded so the player
  sees more of the game, as if it had been made for this screen. Target width is
  whatever the player's screen is (16:9, 20:9, 22:9, ...), computed at runtime.
  Only the top screen on dual-screen devices.
- **Game by game, no blanket hack.** Each game gets its own strategy. Region and
  revision variants of a game share it. Start with the top 20 critic-rated games
  of each system (fewer where the library has fewer), tested by actually playing:
  through the menus and into gameplay on the Thor, screen off when not testing.
- **Then recipes for the rest.** What worked on the top 20 becomes recipes (by
  genre, renderer and style) for the remaining games, at a cursory level.
- **Lower systems first.** Games and systems that already support widescreen are
  not touched.
- **Gameplay matters, menus do not.** Do not fight menus: if widening a menu cannot
  look good, leave it alone.
- **HUD.** Hearts, scores and life meters in the corners move out to the new
  corners where possible.
- **Player experience.** At game start, on the side bars: a glowing "tap here for
  widescreen" that fades as the game starts. Tapping turns widescreen on and briefly
  shows "swipe in from the edge to disable widescreen". Swiping in from the edge
  turns it off, any time during play.
- **Works with frame generation.** Both off, either on, or both on.
- **Data ships in the APK** if it does not grow the download much: no online lookup.
- **Quality bar:** "I don't want this to be, no pun intended, a hack job."

## Constraints found

- EmuFusion is GPL-3.0-only, so engines must be GPL-compatible. **bsnes-hd** (SNES,
  GPLv3) qualifies. **Genesis Plus GX Wide** does not (non-commercial licence), so
  Mega Drive widescreen must be built into BlastEm (GPLv3).
- **ROMs come from the owner's library on the Thor.** The project does not download
  ROMs from the internet.
- Android builds use the survey recipe, never a bare `build.sh` (see build notes in
  the frame-generation goal document).

## Library and engines

| System (folder) | Games on Thor | Engine | Native widescreen? | Starting technique |
| --- | --- | --- | --- | --- |
| nes | 1035 | Mesen | no | Renderer extension + per-game patches; research first |
| gb | 528 | SameBoy | no | Per-game; many fixed-screen |
| gamegear | 202 | Gearsystem | no | Renderer extension (the SMS VDP has off-screen tiles) |
| megadrive | 750 | BlastEm | no | Renderer extension in BlastEm (planes up to 512 px wide) |
| snes | 859 | Mesen-S | no | bsnes-hd core (BG, sprite and Mode 7 widening) |
| gbc | 457 | SameBoy | no | Per-game |
| gba | 789 | mGBA | no | Renderer extension + per-game |
| pcenginecd | 1 | Beetle PCE Fast | no | Research |
| n64 | 302 | Mupen64Plus-Next | no | GLideN64 widening + per-game codes |
| psx | 14 | SwanStation | no | GTE widening + per-game |
| dreamcast | 27 | Flycast | some | Per-game widescreen cheat table + widening |
| gc | 43 | Dolphin | some | Per-game Gecko codes + widening |
| wii | 16 | Dolphin | most | Only where the game lacks it |
| ps2 | 25 | ARMSX2 | some | Per-game patches |
| nds | 6 | melonDS DS | no | Dual screen: research |
| psp | 5 | PPSSPP | yes | Skip |
| 3ds, n3ds | 10 | Azahar | near (5:3) | Research |
| wiiu | 9 | Cemu | yes | Skip |
| switch | 20 | Eden | yes | Skip |
| ps3 | 1 | aPS3e | yes | Skip |

The 3-D systems already have a per-system hack (`WidescreenHackTable`), off by
default and with no per-game logic or in-game toggle. This project replaces that
with recipes.

## Architecture

1. **Recipe table** (`widescreen-recipes.json`, an APK asset): keyed by system and
   canonical title (`TitleMatcher`, so regions and revisions share one entry). Each
   entry: strategy (`widen`, `fixed-screen`, `already-native`, ...), engine options,
   the widest aspect that looks right, HUD rectangles with their anchors, per-scene
   rules, and test evidence (who tested what, on which build).
2. **Fallback recipes** by system and style for games without an entry.
3. **Runtime** (`WidescreenSession`): resolves the recipe at launch; computes the
   target aspect from the top screen; applies and removes engine options live;
   changes the presented geometry.
4. **Touch UX**: glowing bar prompts, tap to enable, a brief hint, swipe in from the
   edge to disable. Shown only when the game has a recipe that widens and the
   screen has bars. The choice is remembered per game.
5. **Engines**: each gains a way to render past the original edges. The host passes
   geometry changes to the renderer and frame generator.
6. **Frame generation**: a geometry change is a source-mode change; history restarts.

## Order of work

1. Infrastructure: recipe table + lookup, runtime, touch UX, live geometry.
2. SNES first: mature widening exists, so it proves the whole path end to end.
3. Mega Drive (BlastEm renderer extension), then Game Gear.
4. NES, GB/GBC, GBA: research the technique per game; expect many fixed-screen.
5. N64, PS1, Dreamcast, GameCube, PS2, Wii: per-game recipes on top of existing hacks.
6. Fallback recipes from what the top 20s teach.

## Status

See the per-system sections below as they are added.

### Foundation (2026-11-04)

- **Engine:** bsnes-hd at a pinned commit plus `engines/patches/bsnes-hd-emufusion-widescreen.patch`:
  exact picture width, per-game scene rule from RAM (`emufusion_ws_scene`), HUD pieces moved
  to the new corners (`emufusion_ws_hud`). Registered as an alternate engine, so Mesen-S stays
  the default for SNES games with no recipe.
- **App:** `WidescreenRecipes` (table: `engines/widescreen/widescreen-recipes.json`),
  `WidescreenSession` (choice remembered per game), `WidescreenOverlayView` (prompts and gestures).
- **Tools:** `tools/widescreen/retro_play.py` plays a core on the Mac from a button script
  and saves screenshots, `contact_sheet.py` tiles them, `ram_scene.py` finds the RAM byte that
  tells gameplay from menus, `thor_game.py` runs the same on the Thor with real touches and pad.
- **Proven on the Thor (3.2.154 test build, frame generation on, 60 to 120):** Super Mario World:
  glowing prompt, tap to widen, hint, HUD in the corners, overworld keeps its bars, swipe in
  from the edge to turn off, tap to turn back on.

## SNES (first pass, 2026-11-04, all on the Mac harness unless noted; engine bsnes-hd)

General technique that came out of it:

- `emufusion_ws_strict`: the core tags each tilemap cell with the world position it was written
  for, and hides wide-area pixels of any cell that is not this position's. This removes wrapped
  maps, stale columns and never-loaded VRAM without per-game work, and most menus go clean by
  themselves. Parallax layers with per-line scroll must stay out of it (DKC2's sky), because a
  cell's tag cannot match every line.
- `emufusion_ws_scene`: RAM test for gameplay; other scenes keep their bars.
- `emufusion_ws_hud`: moves HUD pieces to the corners, per layer, scanline range and column range.
- `emufusion_ws_bounds`: world limits from RAM; outside them the wide area is black.
- Save RAM is exposed to the host (bsnes-hd returned nothing before), so saves carry over.

| Game | Status | Notes |
| --- | --- | --- |
| Super Mario World | widen, Thor pass | Gameplay only; HUD in corners; map keeps bars. Pop-in at the far edge when reversing. |
| Super Mario Kart | widen | Mode 7 scenes only. HUD not moved yet. |
| Donkey Kong Country | widen, Thor pass | Thin unloaded band at the leading edge while running. |
| DKC 2 | widen | Foreground only in strict; small parked-sprite artifact at bottom right to remove. |
| Yoshi's Island | widen | `center`: VRAM beside the tilemap is junk. First screen of a level is narrow until it scrolls. |
| Super Metroid | widen | Gameplay only, HUD in corners. Only Ceres tested; Zebes to check. |
| Super Mario All-Stars | widen | SMB 1-1 tested; SMB2, SMB3, Lost Levels to check. |
| NHL '94, Madden 95, Jimmy Connors, NBA Jam, NBA Live 95 | widen | Field and court extend. |
| Final Fantasy III, Chrono Trigger, A Link to the Past, Star Ocean, Live A Live | not yet | Map engines load only at the screen edge, so strict shows bars and non-strict shows stale tiles. Needs a per-game patch to load further out. No prompt until then. |
| Super Mario RPG | not yet | Same; not played past the name screen. |
| Mortal Kombat II | not yet | Fights stay inside the original view, arena is not loaded beyond it. |
| ISS Deluxe | not yet | Not played past the menu. |

## Mega Drive (first pass, 2026-11-05, Mac harness; engine BlastEm)

Technique: `engines/patches/blastem-emufusion-widescreen.patch`. BlastEm's cycle-accurate renderer
still draws the original 320 or 256 columns untouched; at the end of each line `ef_wide_line`
draws the new columns beside them from the same VDP state (planes, window, sprites, priorities,
shadow/highlight). Timing and game behaviour cannot change. Interlaced modes and 32X stay narrow.

The Mega Drive turned out much easier than the SNES. Planes are usually 64 cells wide and games
load well past the edge, so most games need nothing per-game. Tile tracking (`emufusion_ws_strict`)
is off by default here because it hides more than it helps; it stays available per game.

| Game | Status | Notes |
| --- | --- | --- |
| Sonic & Knuckles, Sonic (this library's file is Sonic 2) | widen | Score, time, rings and lives moved to the corners by sprite tile range. |
| Disney's Aladdin, Ristar | widen | HUD moved to the corners. |
| Gunstar Heroes, Flashback, Lightening Force, Castle of Illusion, Shinobi III, Contra Hard Corps, Desert Strike, Jungle Strike, Madden 92, Monster World IV | widen | HUDs still where the game puts them. Gunstar's weapon menu wraps. |
| NHL 94, NHL 96, NHL Hockey, NBA Jam TE | widen | Scene rule from RAM: gameplay wide, menus and pause keep bars. NHL Hockey shows stale ice past the crowd near the rink ends. |
| PGA Tour Golf III | left alone | Bitmap views; nothing beyond the picture. |
| Shining Force II | not yet | Only the intro played. |

The rest of the library uses a fallback recipe (widen, no per-game rule).

## Game Gear (played, 2026-11-05, Mac harness; engine Gearsystem)

The VDP already draws 256 columns and the handheld shows the middle 160. The picture stops at 240:
the map ring is exactly 256 wide, so a scrolled picture shows one column at both ends and one copy
is wrong. 240 columns reach 16:9 with pixels 6.7% wider than square, still narrower than the
handheld's own LCD pixels. Sprite collisions outside the old window are ignored, so game logic sees
what it always saw. `emufusion_ws_scene` keeps a scene narrow; `emufusion_ws_hud` moves sprites out
by the added width, with an exact row and tile range so game objects are left alone.

Playing past the menus changed the first-pass answers. The first pass called 16 games clean, and 8
of those had only been seen at a title or menu. In play:

| Result | Games |
| --- | --- |
| Widen, HUD moved to the corners | Sonic, Triple Trouble, Dracula, Shinobi II, Micro Machines, Micro Machines 2 |
| Widen, HUD in the map stays centred | Streets of Rage 2, Fatal Fury Special, Road Rash, GP Rider |
| Widen, no corner HUD | Lucky Dime Caper, Pete Sampras Tennis |
| Narrow: rows refresh only across the old screen | Cool Spot, Ecco the Dolphin (a map reader could widen them) |
| Narrow: level built only inside the old screen | Lemmings |
| Narrow: fixed pictures | Ernie Els Golf, Mean Bean Machine, Chessmaster |
| Never offered: Master System mode, 256x192 | Prince of Persia |

Road Rash's and Triple Trouble's titles stay narrow by a scene rule, their hidden columns hold junk.

**The rest of the library.** Master System mode cartridges are refused whatever their title: the
recipe sets `exactBase`, and the core reports them at 256x192. A runtime check for stale columns
does not work: the share of map writes to far columns does not separate good games from bad
(Dracula 54%, Ecco 43%, Cool Spot 18%, Triple Trouble 19%). So the fallback stays `widen` until the
remaining titles are triaged offline: `tools/widescreen/seam_check.py` over frames of each title
finds Cool Spot's seam on 21 of 24 frames and none on most good games, then failures get
`fixed-screen`. It misses joins that are not long straight lines (Ecco, Lemmings), so a zoomed look
is still part of the pass. Shinobi II's level start flags it too, a true edge past the map's end.

Host rebuilds after changing a Gearsystem header need `make clean`: the makefile does not track
headers, and stale objects allocate the old `Video` size (random crashes in `Sms_Apu::volume`).

## On the Thor (2026-11-05)

Sonic 2 (Mega Drive) and Sonic (Game Gear) ran on the Thor with frame generation at 60 to 120: prompt,
tap, wide play with the HUD in the corners, swipe back to bars, tap back to wide, no crashes. The
Mega Drive core reported 1.549 until a game was first widened, stretching every normal Mega Drive
picture about 16% and leaving side bars too thin for the prompt; it now reports 4:3 throughout.

Later the same day, also on the Thor: Contra, Metroid Zero Mission, Super Mario Bros. Deluxe, Road Rash
(title narrow, race wide) and Super Mario Bros. 3 with its map reader, all with frame generation on and
no crashes. Open: Chrono Trigger shows black on the Thor though it renders on the Mac.

Testing note: Quick Resume restores the last state in a QA namespace too. A run that ends paused
starts paused, so a script's START presses toggle pause and the game looks frozen.

## NES, Game Boy, Game Boy Color and GBA (first pass, 2026-11-05, Mac harness)

All four use the Game Gear and Mega Drive method: the engine's renderer is untouched, and a new
function draws the extra columns beside each finished line from the same video state, so timing
cannot change. Nothing runs when the width option is 0. Engines: Mesen, SameBoy, mGBA, each the
system's normal engine. None of them has passed on the Thor yet.

**The rule that decides most games: can the map hold more than the old screen?** A map only one
screen wide can only repeat the far side, and that looks plausible while lying about the level
(Flashback's "extra" columns were 99% identical to the far side). The engines now read the map size
every frame and stay narrow when there is nothing more to show, also in unknown games.

| System | Map | Picture at 16:9 | Top-20 status |
| --- | --- | --- | --- |
| NES | 1 or 2 screens, read from the memory pages | 372x240 | Widen: Contra, Castlevania III, Tecmo Super Bowl, Life Force. One-screen rooms that need a map reader: SMB3, Kirby, Mega Man 3, Ninja Gaiden II, Super Mario Bros 2 |
| Game Boy, Color | 256 wide on a 160 screen | 240x144 (see Game Gear) | Widen: Castlevania II, Mario Deluxe, Donkey Kong Country. Stale: Donkey Kong Land. Rooms: the Zelda games. Fixed: Tetris, Donkey Kong |
| GBA | 256 or 512 wide on 240 | 284x160 | Widen: Metroid Fusion, Zero Mission, Mario Kart. One-screen maps: Alien Hominid |

NES sprites have an 8-bit X, so enemies cannot be drawn in the new columns: they appear at the old
screen edge. GBA sprites have a 9-bit X and do reach them. Game Boy sprites can only reach the first
8 columns past each edge, enough that nothing is cut off at the old edge.

Game Boy menus often hold junk in the hidden map, so these systems have no fallback recipe: a title
without an entry is not offered widening until it has been played. The remaining titles still need
per-game routes past their name-entry screens. Stray HUD digits at Mario Kart's top edges are open.

3D systems (N64, PS1, Dreamcast, GC, PS2, Wii) are not started.

## The map reader (2026-11-05)

NES too: Super Mario Bros. 3 keeps its level in cartridge RAM, so its one-screen map ring is no limit.
Blocks are at 0x1B0 per screen, 16 columns by 27 rows; each tileset's bank opens with four 256-byte
lists (top left, bottom left, top right, bottom right); a block's palette is its top two bits. The
tileset-to-bank table is found by searching the ROM, so other revisions of the game still work. The
reader also fills the 8 columns NES games blank at the left, which sit mid-picture once widened.
`tools/widescreen/nes_map_find.py` looks for such maps in other games, but memory that barely repeats
matches by chance, so read its hits with care.

Tile tracking removes wrong tiles but cannot show tiles a game has not loaded yet, so a side
scroller has a thin unloaded band at the leading edge and an RPG shows nothing at all. Most of
these games keep their whole map in RAM, though. `emufusion_ws_map` names a decoder, a few lines
written per game engine, that fetches each wide-area cell from the game's own map. No game code
runs differently; wide areas are right from the first frame, in every direction.

How a decoder is found: `tools/widescreen/snes_disasm.py` plus the trace core (`EF_WATCH`, `EF_READ`,
`EF_VRAM` in `~/.cache/emufusion-widescreen/host-build/bsnes-trace`) locate the routine that fills
the column buffer; it shows the map address and tile table. Check against VRAM before trusting it.
A Link to the Past matched 192 of 192 visible tiles.

| Game | Decoder | Map | Tile words |
| --- | --- | --- | --- |
| Final Fantasy III | `ff6` | 7F:0000 and 7F:4000, 256 per row | 7F:C000 tables, one per corner |
| A Link to the Past | `lttp` | 7E:2000, 64 per row from the area's corner | ROM 0F:8000 |
| Super Mario World | `smw` | 7E:C800 and 7F:C800, 27 rows per screen | $0FBE pointers into bank 0D |
| Chrono Trigger, world map | `ct` | 7E:4000 and 7E:5800, 96 per row, wraps | 7E:3000 and 7E:3800, 8 bytes per tile |

Not done yet: Star Ocean, Live A Live, Super Mario RPG. Towns and rooms in Chrono Trigger, houses
and dungeons in A Link to the Past keep bars until they get decoders of their own.

## Release gate

Each system in the recipe table has `"release"`. Nothing shows to players until it is true, which
happens only after that system passes on a real device, because frame-generation releases carry
this branch. `settings put global emufusion_qa_widescreen_all 1` turns everything on for testing
(`thor_game.py` does this and clears it afterwards; the recipe table is read once per app process).
