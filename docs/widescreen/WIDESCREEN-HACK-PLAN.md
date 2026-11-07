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
| wii | 16 | Dolphin | most | Nothing to do, see below |
| ps2 | 25 | ARMSX2 | some | Per-game patches |
| nds | 4 games | melonDS DS | no | Nothing to widen on the top screen, see below |
| psp | 5 | PPSSPP | yes | Skip |
| 3ds, n3ds | 10 | Azahar | near (5:3) | Skip, see below |
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

The VDP already draws 256 columns and the handheld shows the middle 160. The picture stops at 248:
the map ring is exactly 256 wide, so a scrolled picture any wider shows one column at both ends and
one copy is wrong. At 16:9 that leaves about 30 black pixels on each side of a 1920 screen, because
pixels stay square. Sprite collisions outside the old window are ignored, so game logic sees what it
always saw. `emufusion_ws_scene` keeps a scene narrow; `emufusion_ws_hud` moves sprites out by the
added width, with an exact row and tile range so game objects are left alone.

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

## No stretching, ever (owner, 2026-11-05)

"NO STRETCHING ANY IMAGES, you are adding additional viewing area organically." A pixel keeps its
shape narrow and wide on every engine, for every image including logos and HUDs. Black bars beat any
stretch. `tools/widescreen/par_check.py` proves it for the 2D engines; run it after any engine change.

The 3D engines' generic hacks are where this bites:
- PS1 (Swanstation `GPU_WidescreenHack` with a 16:9 display) widens only 3D that goes through the GTE,
  and 2D logos, HUDs and menus stretched 33%. Fixed for the hardware renderer, see "PS1" below.
- N64 (GLideN64 `16:9 adjusted`) scales 2D back: Ocarina's title logo is the same width narrow and wide.
  Each game still needs that compared, because some draw 2D as polygons.
- GameCube and Dreamcast: not evaluated yet, and a generic hack is only acceptable under the same test.

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
| NES | 1 or 2 screens, read from the memory pages | 372x240 | Widen: Contra, Castlevania III, Tecmo Super Bowl, Life Force, Mega Man 2, Super Mario Bros. With a map reader: SMB3, Mega Man 3, Kirby, Ninja Gaiden II, Bionic Commando. Open: Final Fantasy III, Zelda rooms |
| Game Boy, Color | 256 wide on a 160 screen | 248x144 (see Game Gear) | Widen: Castlevania II, Mario Deluxe, Donkey Kong Country. Stale: Donkey Kong Land. Rooms: the Zelda games. Fixed: Tetris, Donkey Kong |
| GBA | 256 or 512 wide on 240 | 284x160 | Widen: Metroid Fusion, Zero Mission, Mario Kart. One-screen maps: Alien Hominid |

NES sprites have an 8-bit X, so enemies cannot be drawn in the new columns: they appear at the old
screen edge. GBA sprites have a 9-bit X and do reach them. Game Boy sprites can only reach the first
8 columns past each edge, enough that nothing is cut off at the old edge.

Game Boy menus often hold junk in the hidden map, so these systems have no fallback recipe: a title
without an entry is not offered widening until it has been played. The remaining titles still need
per-game routes past their name-entry screens. Stray HUD digits at Mario Kart's top edges are open.

3D systems were started the same day; see "No stretching, ever" and the recipe table's `tested` notes.
GameCube's 16:9 codes widen the 3D but stretch 2D by a third (Wind Waker's logo measured on the Thor), so
`engines/patches/dolphin-emufusion-keep-2d-shape.patch` draws 2D through a viewport narrower by the same
amount, which also clips whatever a game keeps just off its old screen. It leaves out what comes before an
EFB copy (the input of an effect) and, in a 3D frame, anything spanning the screen (a sky, a fade, or the frame
going through an effect). A frame with no 3D at all is a 2D screen and sits in bars. Dreamcast keeps 2D's
shape as it is: Crazy Taxi's PRESS START is the same width narrow and wide.

## The map reader (2026-11-05)

NES too: Super Mario Bros. 3 keeps its level in cartridge RAM, so its one-screen map ring is no limit.
Blocks are at 0x1B0 per screen, 16 columns by 27 rows; each tileset's bank opens with four 256-byte
lists (top left, bottom left, top right, bottom right); a block's palette is its top two bits. The
tileset-to-bank table is found by searching the ROM, so other revisions of the game still work. The
reader also fills the 8 columns NES games blank at the left, which sit mid-picture once widened.
`tools/widescreen/nes_map_find.py` looks for such maps in other games, but memory that barely repeats
matches by chance, so read its hits with care.

NES readers added the same day, each worked out from a CPU trace of the game loading a column:

| Game | Reader | Where the level is |
| --- | --- | --- |
| Mega Man 3 | `mm3` | ROM bank = stage ($22): screen list $AA00, room list $AA40, screens $AF00 (8x8), blocks $B700, tiles $BB00-$BE00, palette $BF00. Camera $FC, $F9 |
| Mega Man 4 | `mm4` | ROM bank = stage ($22) or $20: screen list $B500, room list $B530, screens $A900 (8x8), blocks $A500, tiles $A000-$A300, palette $A400. Mega Man 5 and 6 differ and have no reader yet |
| Kirby's Adventure | `kirby` | Battery RAM: size $67EE-F, page list $67F6, pages $68C8 (12 rows of 16), tiles $7A00-$7D00, palette $7E00. Camera $DD-E, $E0-1 |
| Ninja Gaiden II | `ng2` | ROM: running column pointer $86 (6 blocks a column), blocks $69, tiles $6B, colours $6D. Scroll read per line, it changes after the status panel |
| Bionic Commando | `bionic` | ROM banks named in $F0-$F7: screen list, screens (8x8), blocks 7 bytes each. Screen index comes from the game's column loader ($98, $99) |

Rules these share, all in `Core/PPU.cpp` of the Mesen patch:

- **A reader only draws while it is right.** Each frame it predicts 32 tiles in the middle of the real
  picture and compares. Under 70% for three frames in a row, the sides go black, so title screens, menus
  and briefings stay narrow with no per-screen rules.
- **The camera is read at vertical blank**, when the game commits its frame. Read mid-frame, a game's
  own sums show up as dashed lines in the new columns. The scroll registers then correct any lag.
- **A room's edge carries on.** Past a room's end the next page is often above or below, not beside it,
  so the last 16 pixels repeat. Walls continue as walls.
- **Room changes slide.** In Mega Man 3 both rooms are drawn beside the sliding picture.
- `emufusion_ws_hud=edge` carries a status panel's own border to the sides (Kirby).

Mega Man 2 needs no reader: its two-screen map shows all eight stages correctly.

Game Boy, in `Core/ef_wide.inc` of the SameBoy patch:

| Game | Reader | Where the map is |
| --- | --- | --- |
| Pokemon Red, Blue | `pokemon1` | Work RAM $C6E8: 32-pixel blocks with a 3-block border; size $D368-9, position $D361-2; 16-tile block lists from bank $D52B at $D52C |
| Pokemon Yellow | `pokemon1y` | The same, every variable one byte lower |
| Pokemon Gold, Silver | `pokemon2` | Work RAM $C700; size $D087-8, position $DA02-3; block lists from bank $D0C5 at $D0C6; each tile's colour in a 4-bit list in bank 2 at the address in $D0CF |
| Wario Land II (Color) | `wl2` | Battery RAM bank 1, a byte for each 16-pixel block, 256 to a row. Tiles at $C400 + block x 4 + corner, colours the same in work RAM bank 4 at $D400. A block number's top bit is dropped, as in the game's own sum |
| Wario Land 3 | `wl3` | The same in battery RAM bank 2, tiles at $C600, colours in work RAM bank 3 at $D300 |

The player stands still on screen and the map scrolls 16 pixels a step. The game's position changes when
a step begins, so the reader tries the positions a step could be at and keeps the one that explains the
picture. That check also keeps menus and battles narrow. Rooms sit in the map's own border colour.

The Wario games have no position to read: the level and the video scroll differ only by whole turns of the 256-pixel
ring, so the reader tries those and keeps the one that explains the picture. Donkey Kong Land and its sequel swap tile
graphics as they scroll, so their map numbers do not match the picture, and they stay narrow.

Tools: `~/.cache/emufusion-widescreen/host-build/mesen-trace` logs every CPU read and write with
(`host-build/sameboy-trace` does the same for Game Boy: it logs the code and data banks with each access.)
`EF_TRACE_FILE`, `EF_TRACE_FROM`, `EF_TRACE_COUNT`. `retro_play.py` gained `poke:ADDR=VALUE` to reach a test
case without playing there and `saveram:NAME` for battery RAM. All host-only so far; on the Thor next.

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
| Yoshi's Island | `yi` | 7F:8000, screens of 256 in rows of 16; 7E:0CE1 gives each level position its screen | Super FX ROM: page offsets at file C32A4, 8 bytes per entry from C33F2 |
| Donkey Kong Country | `dkc` | [$D3], 16 numbers a column, bits 14 and 15 flip the block; the camera stays from $1B23 to $1B25 | $1B11 in the same bank, 16 words a block in rows of 4 |
| Donkey Kong Country 2 | `dkc2` | [$98] in work RAM; six shapes (16 or 32 a column, or 16, 32, 80 or 96 a row), one column writer each, tried until one matches the picture; the camera ($17BA less 256) stops at $0AFC | $17B4 in the same bank, as above |
| Donkey Kong Country 3 | `dkc3` | As DKC 2, with [$8C], camera $196D and limit $04BC | $1967 |

Not done yet: Star Ocean, Live A Live, Super Mario RPG. Towns and rooms in Chrono Trigger, houses
and dungeons in A Link to the Past keep bars until they get decoders of their own.

## The rest of each library

`tools/widescreen/library_triage.py SYSTEM ROM_DIR OUT.json` plays every game on the Mac and asks one
question: do the pixels at the side of the picture later arrive in the old picture when the game scrolls?
Contra, Life Force and Super Mario Bros score about 99%; stale columns like Crisis Force score 43%. A pass
needs at least 90% over at least 10 scrolling frame pairs with sides that are not blank. It only shortlists:
a game still has to be seen before it gets a recipe. ROMs are in `~/.cache/emufusion-widescreen/library`.

NES, 2026-11-06: 1,030 games checked, 139 shortlisted, 85 new recipes after looking at two frames of each. Left out:
games where only a title or intro was captured, and any with visible junk at the sides. These recipes carry
`emufusion_ws_gate=scroll`: the sides stay black until the scene scrolls and close when the screen is rebuilt with
the picture off, so title screens and menus stay narrow in games nobody has played through. Being unplayed, they
may still show something wrong deeper in; the owner asked for a cursory pass here, not a deep one.

The first version counted blank and striped frames as scrolling, because they match themselves at every shift. The best
shift now has to stand out, and each game keeps the two frames that proved it, which are what the sheets show. Every
shortlist was checked again that way on 2026-11-06:

| System | Checked | Shortlisted | Still pass | Recipes now | Notes |
| --- | --- | --- | --- | --- | --- |
| NES | 1,030 | 139 | 77 of the 92 with recipes | 11 dropped, 4 keep their status panel in the middle | stale columns: Cobra Command, Urban Strike, Red Pig, TaleSpin and others |
| Game Boy | 524 | 141 | 74 | 35 added | |
| Game Boy Color | 450 | 67 | 29 | 11 added | Shantae fell from 100% to 31%: it was blank frames |
| Game Gear | 201 | 34 | 16 | 11 added, after adding the gate to Gearsystem | |
| GBA | 957 | 145 scrolled | see recipes | added after looking at two frames of each | uses the explorer instead of fixed routes |
| SNES | 853 | 107 scrolled and scored 55% or more | see below | the whole library by default | `emufusion_ws_strict`, stale cells stay black, plus the scroll rule |

A low score alone does not drop a game: sprites and animation cost some, so near misses that looked clean stayed.

SNES, 2026-11-06: the engine gained the same scroll rule as the others (`emufusion_ws_gate=scroll`). With it and strict tiles, two
frames of each of the 107 games that scrolled showed titles and menus narrow, and gameplay either wide and clean or narrow and clean.
Six showed junk, mostly in an intro or a menu, and have narrow entries: Spider-Man & Venom, Fever Pitch Soccer, Rocko's Modern Life,
Mecarobot Golf, Waterworld and Tom & Jerry 2. So the SNES now has a fallback for every title without its own entry. A game that
loads nothing past the old screen simply stays black at the sides, and the player can swipe it off. Most of these games have not been
played through. A mode 7 game whose ordinary scroll registers do not move stays narrow until it has an entry of its own. On the Thor,
Smart Ball and Tiny Toon: Buster Busts Loose keep their titles narrow, widen in the level and take the toggle in play. Harvest Moon is
black on the Thor with or without any widescreen option, though the identical file runs on the Mac, so that fault is not widescreen's.

GBA, 2026-11-06: the explorer rarely got far enough, so `explore` found only 7 games. A longer fixed run of START, A, walking and
jumping, seven shots a game, got much further. Over all 957 games, 218 showed content at both sides, because their video maps are 64
cells wide; the rest stay narrow by themselves. Two frames of each were looked at, and 79 games were added with the scroll rule, among
them F-Zero: Maximum Velocity, Street Fighter Alpha 3, Mega Man & Bass, Rayman Advance, Klonoa and Tekken Advance. Left out: stale tiles
or colour bands at the edges (Mega Man Zero 1, 3 and 4, Buffy, Tarzan), sky that stops short of the new corners (Road Rash, Simpsons Road
Rage, Wakeboarding Unleashed), cockpits narrower than the view (F-14, Super Hornet), and any that showed only a menu. Most have not been
played through. A separate search for level grids in work RAM over 61 games found about ten, nearly all minor licensed titles, so
it was not followed up. On the GBA the new columns are 22 pixels a side at 16:9, so a reader does less here than on the NES or SNES.

Game Boy, Game Boy Color, Game Gear and NES, 2026-11-06: the same longer run went over 524, 450, 201 and 1,030 games. Two frames of each
game that scrolled were looked at on the Mac, and 35, 16, 5 and 24 games were added with the scroll rule, among them Mega Man IV and V,
Bionic Commando, Mr. Gimmick, Ninja Gaiden, Chip 'n Dale and Blades of Steel. None has been played through and none of these has run on
the Thor, so a game here can still be wrong beyond the stretch those two frames show.

Mega Drive, 2026-11-06: all 748 games checked. 104 scrolled in the automatic run: 55 pass, and most low scorers still look right, their
score lowered by parallax and animation. The engine gained the scroll rule too, so the library fallback keeps titles and menus narrow.
Exo-Squad (black column), Caesars Palace (black gaps) and Warrior of Rome II (title wraps behind its menu) have narrow entries.

## GBA map reader (2026-11-06)

Many GBA games keep the whole level in memory as a grid of block numbers, with a table of blocks of four map entries,
and copy only what is near the screen into the 256-wide video map. `emufusion_ws_map=grid:...` gives the new columns the
same grid, so a further game needs its addresses in the recipe and no new code:

`grid:table=2020000,planes=2014000+201C000,cell=4,stride=200,cols=80,rows=80,mask=3FFF` (Golden Sun)
`grid:planes=200B654:2012654+2025EB4:202CEB4,cell=2,stride=80,cols=40,rows=40,width=3000C0E,height=3000C10` (Minish Cap)

Each frame, each background compares samples of the video map with the grid. The scroll registers say little about the
world position and a game may start a block on either tile row, so finding a place tries every one, drawn tiles first so
most fail at once. Only a search that has already matched runs every frame; an unmatched one looks every eighth frame. A
background that matches nothing, a menu for instance, draws nothing in the new columns. A sparse layer such as tree tops
cannot be found alone, so it takes the place of a layer moving with it. `width=`/`height=` name where the game keeps the
room's size, because the cells past it are left over from the last room. Out on the black around a room, sprites are not
drawn. `tools/widescreen/retro_play.py` has `iwram:NAME` for the fast work RAM these searches need.

Finding a game's addresses: `gbagrid.py` in the session notes looks for the video map's 2x2 groups in memory, then for a
grid whose differences match. For the games it could not place, a trace core (`host-build/mgba-trace`, `EF_TRACE_FILE`, now
logging fast work RAM too) shows the routine that loads a column as the camera moves.

| Game | Form | Where the level is |
| --- | --- | --- |
| Aria of Sorrow | `rooms=1,edge=1,ring=8,planes=200A094:200A108+200A0B0:200C0EC` | Each layer has a record (room pointer, camera at +4 and +8, 16.16). The room header gives width and height in 256-pixel screens, a tile list and a block list: blocks of 4x4 tiles, top two bits flip the block. Second table in RAM when the header's flag 2 is set |
| Harmony of Dissonance | `rooms=1,edge=1,ring=C,planes=200A440:200A494` | The same engine at other addresses. Its first table is 0x54 past the record, not 0x74 |
| Circle of the Moon | `rooms=2,edge=1,planes=20230F0+2023130+2023170+20231B0` | A record per background: tile table +4, RAM block grid +C, columns +10, rows +12, camera +18 and +1C. No flip bits |
| Final Fantasy VI Advance | `cell=1,stride=100,cols=100,rows=100,split=200,step=100,planes=2010000:201C000+2014000:201C800,front=2020000+2020400` | Two maps, one byte a block, 256 per row. A tile list per corner, 0x200 apart. Tiles in front of sprites form a background of their own, built from either map and a list of marks |

Rules these add. A room's header with no second pointer is a menu, so menus and maps keep their bars. A room's last block repeats
past its end (`edge`). `ring` names backgrounds drawn from the video map as they are, for backdrops that repeat at 256 anyway.
`step` limits the search when the world and the video scroll differ only by a multiple of 256.

Staying narrow, and why: Tony Hawk's Pro Skater 3, Tony Hawk's Underground and Alien Hominid load tile graphics only for what is
on screen, so the art for the new columns is not in video memory. WarioWare and Ultimate Card Games have no scrolling world.
Advance Wars and Fire Emblem open on maps that fit the screen, and their larger maps are behind long campaigns, so their readers
have not been tried. Mario & Luigi draws rooms on black and looks right in Mario's house, but its plain backdrop shows beside
some rooms and no outdoor area has been reached yet.

### GBA meters in the corners (2026-11-06)

`emufusion_ws_hud=obj:-8-24:0-119:-1:040-0FF;bg0:0-31:0-119:-1:0C0-0EF`: a layer (`obj` or `bgN`), lines, columns, a direction
and optionally a range of tile numbers. Sprites match by their top left corner. A matching sprite leaves the list the
original picture is drawn from; a layer's pixels are covered with what lies under them, worked out from the other layers. The
moved meter is then laid over the finished picture. A tile range keeps dialogs on the same layer out of it. If a scene drops out
of wide for a few frames while a reader finds its place, the meter stays put rather than jumping. Emulation is not touched.

| Game | Moved | Lives in |
| --- | --- | --- |
| Metroid Fusion, Zero Mission | Energy to the left corner, minimap to the right | Sprites |
| Aria of Sorrow | Health and magic | Background 0 and sprites |
| Circle of the Moon | Health, magic and hearts | Background 0. Also `void=1`: a white strip past a room's wall showed the game's backdrop, so empty new columns are now black |
| Minish Cap | Hearts left; item buttons and rupees right | Background 0 and sprites |
| Mario Kart: Super Circuit | Rank, lap, coins and speed left; time and track map right; item box stays centred | Background 0, map dots in sprites. Also a race rule, `30016E0=01,300040E=18`: the first byte alone blips for single frames on menus. Menus and the pause screen now stay narrow |

Mario Kart ran this way on the Thor at 60 to 120, with the toggle in mid-race. The others have been seen on the Mac so far. Super Mario
Advance 4's status bar is a panel across the bottom and stays where it is. Golden Sun, Final Fantasy VI Advance and Tactics Advance
show no meters during play.

The NES has the same kind of rule for sprites, `obj:y0-y1:x0-x1:dir:t0-t1`. A moved sprite still counts for sprite zero, so timing is
unchanged; it only stops being drawn in its old place. Mega Man 2 and 3's energy bars and Contra's lives use it. Status panels drawn in
the background, as in Castlevania III and Ninja Gaiden II, stay where they are. On the Mega Drive the meters of the top games left
(Gunstar Heroes, Contra: Hard Corps, Castle of Illusion, Monster World IV, Lightening Force) are panels in the window plane, so they
stay too.

### Top games looked at again (2026-11-06)

Several narrow top games had been judged from menus. Playing them changed one and gave the rest reasons from real play:

| Game | Now | Why |
| --- | --- | --- |
| Mario Tennis | Widens | Each court map is 256 wide, so the whole court and its surroundings fill the picture and the camera pans over real scenery. Menus are told apart by the game's graphics queue: its fourth entry points at sprite tiles only on a court (`C0BE=B0|C0BD=83,C0BE=00|C0BD=86,C0BE=C0|C0BD=87,C0BE=C0`). Followed frame by frame: wide on 0 of 9,472 menu frames, and one change to wide in each of a singles and a doubles match with pauses. A mini-game round flashes bars on a white screen for a frame or two |
| Metal Gear Solid | Narrow | The status panel sits inside the right of the picture |
| Warlocked | Narrow | The first mission's map is built only just past the old screen, so the sides stay mostly black |
| Cannon Fodder | Narrow | The first mission's sides show stale pieces and checker junk |
| Mario Golf | Narrow | The shot view's sides are half course and half unrelated tiles |
| Mole Mania | Narrow | Each room is one screen inside black |
| Advance Wars | Narrow | The first versus maps fit the screen exactly, and larger maps are locked behind the campaign |

## PS1 (2026-11-06)

The hack narrows what the GTE projects and the display stretches the whole picture back out. PGXP already knows which
vertices came from the GTE, so `engines/patches/swanstation-emufusion-keep-2d.patch` (option
`swanstation_GPU_EmufusionKeep2D`) draws everything else a quarter narrower about the centre in a 3D scene. One GTE vertex
makes a polygon 3D, because a game that clips a polygon itself keeps the others. A draw across most of the screen is left
alone: it is a fade or backdrop. A scene with no 3D for 8 frames in which something was drawn is left alone and shown at
4:3 as a whole, which also keeps movies, uploads and copies right. A loading screen left up stays what it was.

This lives in the hardware renderer, and the app ran SwanStation in its software session, where hardware requests are
refused. `hardwareWhenWide` in the recipe starts the GLES session when widescreen is on; with it off the game runs as it
always did. Resolution scale 4 makes a 2D pixel exactly 3 pixels wide before presentation, so narrowed sprites stay even.

The library has 13 PS1 games, 8 of them 3D. Tekken 2 played: right. Spyro's opening right, level not played. WipEout (USA)
stops at its Designers Republic screen in both renderers, still to explain. HUDs stay in the middle for now: moving them
to the corners needs a per-game rule, because splitting by screen side would break centred text like GAME OVER.

### PS1 and PS2 on the Thor (2026-11-06)

PS1: WipEout 3 and WipEout XL (races), Twisted Metal 2 (a battle), Die Hard Trilogy (the car park), Tekken 2 (a fight) and Spyro (a
level) play with the world at both edges and their status displays in shape, in the middle. Bushido Blade's demo fight and credits
look right; the coloured corners behind its faces are the game's own, seen narrow on the Mac too. WipEout (USA) stops at an intro
movie with or without widescreen, so its file is suspect and it stays out. The 2D games (Symphony of the Night, Mega Man 8, X4 to X6)
stay narrow. PS1 is released to players from the next build.

The software and hardware sessions keep separate memory cards and Quick Resume. The first version chose the session from the
player's choice, so swiping widescreen off went back to the state from when it was turned on. A PS1 game with a recipe now runs in
the hardware session narrow or wide, and its first run there copies the software session's card and Quick Resume, leaving the
originals in place. Twisted Metal 2 proved it: a software-session battle came across, then a swipe and a tap in play kept the same
battle going. A pause restored from Quick Resume looks like a 2D screen, so it stays narrow until play resumes.

PS2: DOA2's fight is right and its stale sides are gone. Kingdom Hearts keeps its menus and opening in shape; play not reached.
Sly Cooper's title and spy-goggle scenes look right. Its film bars were narrowed at first, leaving the rooftops showing above and
below them at the sides; plain untextured bars across the whole width now stay full width, as they have no shape to lose, and that
was seen right on the Thor. PS2 stays hidden from players until more of its games have been played.

New readers seen on the Thor at 60 to 120 the same day: Aria of Sorrow and Circle of the Moon (opening scenes), Harmony of Dissonance
(the bridge), Wario Land II (bedroom and coin room) and The Legend of Zelda (the overworld across screens, inventory narrow). Wario
Land 3 and Final Fantasy VI Advance have been played on the Mac only.

A game started over an open one is refused unless it needs a different kind of session, and the first game keeps running, so nothing
is lost.

### Turning widescreen off and on in play (2026-11-06)

Systems that restart their engine on a toggle were tried in live play on the Thor. N64 (Super Mario 64), Dreamcast (Jet Grind Radio) and
GameCube (Double Dash) each logged a Quick Resume commit and restore every time; Mario 64 came back at the same spot, Jet Grind Radio
kept playing its attract loop and Double Dash stayed on its opening menu. PS1 does too since its sessions were joined. One thing to
look at: Double Dash's card prompt changed after the first restore to "No Memory Card found", so a restore may make Dolphin's card look
missing for a moment. PS2 is the exception, below.

### PS2 stays hidden: its toggle restarts the game (2026-11-06)

Quick Resume is deliberately off for ARMSX2, because a restored state can run on with only black frames and no way to detect it
(`QuickResumePolicy`). So a swipe or tap in play, which restarts the engine on PS2, goes back to the game's logos: on GTA III a swipe
in the street landed on the Rockstar logo. Memory-card saves survive, unsaved progress does not. Good PS2 pictures are not enough until
this is solved. The likely way is to boot these games wide always and make off a live crop of the middle 3/4 of the picture, so neither
direction restarts anything; the widening keeps vertical view, so the crop should match the game's own 4:3 framing.
The core side is small: crop `CalculateDrawSrcRect`'s middle 3/4 when a scene is 3D, and its aspect sum keeps the pixel shape. The hardware
session has no way to change a core option while running, though, so it needs a new call through the native host first.

### More PS2, N64 and GameCube first looks (2026-11-06)

GTA III and Shadow of the Colossus play right. God of War I and II and Prince of Persia: The Sands of Time do not survive keeping 2D in
shape: full-screen passes they draw in many strips or through their own filters come out striped or hazed, so they stay narrow.
International Superstar Soccer 64's attract match and Wave Race 64's race are right, and so is Vice City on foot. Tekken 5's fight stays
narrow with faint seam lines, and Twilight Princess shows a stray black block over its title, so both stay narrow. Soulcalibur III has
only been seen as far as its menus and story pages. Both copies of Ocarina of Time: Master Quest on the Thor are truncated (397 MB of 935 MB).

### The rest of the N64 library (2026-11-06)

A short look on the Thor at 20 more N64 games, each started wide. Widen: Mario Kart 64, Mario Golf, Mario Tennis, Pokémon Snap, Kirby 64,
Castlevania, Doom 64, Harvest Moon 64, Ogre Battle 64, Turok and Yoshi's Story. Stay narrow: Donkey Kong 64 (draws in its own window, stale
pieces beside menus), Jet Force Gemini (stray pieces beside the title), Pilotwings 64 (black gaps down both sides), F-Zero X (sky stops short
of the corners on some courses) and Body Harvest (plays inside a narrow box). Only menus reached so far, so no entry yet: Smash Bros, Beetle
Adventure Racing, WWF No Mercy and Rogue Squadron. With about a quarter failing, the N64 gets no fallback: each game needs a look. On GameCube,
Mario Party 4 and Star Fox Assault did not get past their memory card prompts. Katamari Damacy on PS2 showed no picture in two minutes.

A second batch of 40 is under way, with the first 27 reviewed. Widen: Buck Bumble, Cruis'n USA, Duke Nukem 64, Extreme-G, Gex 64, Hybrid
Heaven, Indiana Jones and the Infernal Machine, Mario Party, Mortal Kombat 4, Mystical Ninja Starring Goemon, Quake II, Ridge Racer 64,
Rocket: Robot on Wheels, Shadow Man, Shadows of the Empire and Wipeout 64. Stay narrow: Resident Evil 2 and Top Gear Rally (bars of noise),
San Francisco Rush (flat bands down both edges), Snowboard Kids (a narrow box) and Space Station Silicon Valley (stray slices of picture).
All from short runs, none played through.

Three more of the 40 ran before the batch stopped so frame generation could have the Thor, and the undecided games were looked at again at full
size (2026-11-07). Widen: Turok 3, Vigilante 8, Bomberman Hero, Glover and Goemon's Great Adventure, whose forest scene before a stage shows bare
white past its backdrop at the far sides. Stay narrow: Mega Man 64 (the intro sky stops short and the item menu sits off-centre) and Castlevania:
Legacy of Darkness (Player Select shows a slab the game keeps off-screen, and its backdrop stops short). Still undecided: Bomberman 64, which never
left its logo; Quake, whose menus show wrapped logos and a stray strip, with play not reached; and Episode I: Racer, whose menus are right but
whose race was not reached. Nine of the 40 have not run: San Francisco Rush 2049, Pokémon Stadium, WrestleMania 2000, NFL Blitz, Tetrisphere,
Rayman 2, Army Men: Sarge's Heroes, Forsaken 64 and Star Soldier.

### Game Gear: asking the game to draw further (2026-11-07)

The earlier notes on Cool Spot and Ecco were wrong about the cause. Tracing their writes to the video map showed Cool Spot keeps a correct
32-column window, but starts it at the old left edge, so the far right of that window wraps round into the new left columns. Ecco's loaders stop
two columns past the old screen. Neither needs a map reader. A few bytes make the game itself draw the real level there:

`emufusion_ws_patch=ADDR:OLD>NEW;...` in hex, ROM file offsets. Every OLD is checked first and a ROM that differs stays narrow, so another revision
cannot be damaged. It is undone when the picture goes narrow, except code placed in free space. `emufusion_ws_freepc=A-B;C-D` gives lengthened
loaders no console time, so the wider picture costs no frames. `emufusion_ws_maxext=N` limits the new columns where a game's map reaches only so far.

| Game | Change | Check |
| --- | --- | --- |
| Cool Spot | All loaders six tiles further left: map position, tile within the block, place in video memory, including the routine that draws a level's first screen | 60 random-input shots match the original exactly in the old screen area. Video map matches the level in work RAM, 468 of 468 cells seen |
| Micro Machines | The game's own Master System lengths: 32-cell rows. Map window five columns left, right column five further out, and a first screen drawn across all 32 columns in the space of the old routine, which drew 21 | Random-input lockstep, 210 shots: only the first shot after loading a state saved narrow differs. The test found the first screen and a second row path |
| Ecco the Dolphin | Columns load from six left to 25 right of the camera, not 0 and 22. Rows fill 32 cells, not 23. Three shifts made arithmetic, or a row near the level's left edge loads wrong across the whole picture | 160 random-input shots match exactly against a run with the same timing and no patch. The first version showed that fault only when the reference state came from the original game |

The test that matters is lockstep. Random inputs through the original and the patched game, then every pixel of the old 160x144 area compared. A
state saved by a patched run must not be used as the reference: its video memory carries the fault into the original. Comparing a frame's side
columns with a later frame of the same run proves nothing, since it is the same cell.

Micro Machines 2 has a rewritten engine whose row buffer holds only 36 cells, so 32 visible cells would need that buffer moved in memory. It was not
tried and stays narrow. All three recipes are QA only until they have passed on the Thor.

### The top 20 on the way to the Thor (2026-11-06, evening)

A count of the top-20 lists found how few had run on the Thor: SNES 1 of 20, Mega Drive and Game Gear none, NES 5. Blind menu presses on the
device rarely reached play, so a QA launch can now start from a save state (`emufusion_qa_start_state`, `THOR_START_STATE` in `thor_game.py`).
Not yet run on a device, and whether a Mac core's state loads on the Android build of that core is still to be proven. States for 65 of the
72 games, in play or close to it, are in `~/.cache/emufusion-widescreen/states/top20`. Still on a menu or story screen: Super Mario Bros. 3,
Micro Machines, Madden NFL 95, Jungle Strike, NBA Jam Tournament Edition, Contra: Hard Corps, Final Fantasy Tactics Advance.

Looking at full frames of those states found real faults the earlier passes had missed:

| Game | Fault | Now |
| --- | --- | --- |
| Final Fantasy III | The game masks its first and last 8 columns, seen as black bands between the old picture and the new columns | `emufusion_ws_unmask=on` lifts it in wide scenes |
| Yoshi's Island | Mountains and ground stopped at the old edge | Map reader `yi`: everything reaches both edges in 1-1. Only levels widen |
| Super Mario All-Stars | Cut-off ground in play, cyan strips beside the World screen | Strict on the far layer only; rule `7E0079=01`. Only Super Mario Bros. widens |
| Tecmo Super Bowl | Other menu pages at the sides of the main menu | Scroll rule: menus keep bars, the field opens once play has scrolled |
| Jimmy Connors Pro Tennis Tour | Scrolled menu text at the sides | Rule `7E00B0=02`: only a match widens |
| Survival Kids | Junk beside story scenes | Rule `C131=04`: only the island widens |
| NHL Hockey (Mega Drive) | Flat patches of ice beside the rink ends | Narrow |

Yoshi's Island's table was found without reading code, since its columns are built through Super FX RAM: search the ROM for the four tile words of blocks on screen, then search RAM for numbers whose differences follow those table positions. Then every top game was walked far enough to reach the column-loading edge, which found more:

| Game | Fault | Now |
| --- | --- | --- |
| International Superstar Soccer Deluxe | Flat green strips | No strict rule: pitch and goal reach both edges |
| Sonic 2, Sonic & Knuckles | Streaks beside the SEGA screen | Rule `FFF600=0C`: only levels widen |
| Castle of Illusion | Slices of picture beside the intro, which scrolls | Rule `FF0005!=DD` with the scroll rule. Other stages not seen |
| Contra: Hard Corps | Font tiles beside story screens | Scroll rule |
| Donkey Kong Country (Color), Wario Land II (Game Boy) | Stale tiles beside static scenes | Scroll rule |
| NHL 94 (Mega Drive) | Coloured tile junk in the crowd | Narrow |
| Monster World IV | Black blocks in the clouds, in play | Narrow |

Open: Donkey Kong Country and DKC 2 still cut the near ground at the leading edge. Without the strict rule that edge shows hard seams from stale
columns, and level cards show junk. DKC's blocks are 4x4 tiles in ROM bank 19 but only about half match on screen, so some are probably stored
flipped. NHL '94 on the SNES shows flat ice at the rink corners. Castlevania II on the Game Boy has digits cut off at the far edges of its status bar.

A state restored into a game with the strict rule stays narrow on a static screen until the next redraw (Jimmy Connors, Mortal Kombat II), so those
need judging from a route. A state restored before BlastEm's first frame is lost, on the Mac harness only: the app runs a frame first, and the Thor
restored Sonic & Knuckles correctly. Mac states did load on the Android cores on the Thor for all six engines tried.

SNES colour math can tint closed sides: the game adds a fixed colour over the black. The engine now writes closed sides as black in the
finished line. A high share of filled side pixels does not mean a game is right, so each frame was looked at. All of this is Mac only so far.

### First full-size pass of the top 20 on the Thor (2026-11-06, night)

All 72 games ran on the Thor from Mac save states as a player would: prompt, tap, walk both ways, swipe off, tap on, at 60 to 120 fps. Prompt, tap and
swipe worked on every one. Save states from all six Mac cores load on the Android cores. Looking at the frames full size found these, none of which the
Mac pass had shown:

| Game | Fault on the Thor | Now |
| --- | --- | --- |
| Donkey Kong Country, DKC 2 | Near layer cut off at the leading edge, and DKC 2's cabin floating in open sea | Map readers `dkc` and `dkc2`, next section. Mac only so far |
| Super Mario All-Stars | Narrow unless a button was held: the rule's byte was the controller, and Mac shots were taken with one held | Scroll rule. A level opens once the camera has moved |
| All-Stars' Mario 3 | Sky-blue blocks beside its status bar, which Mario 1 does not have | `emufusion_ws_band=192-223@7E022D=C5`: a band can depend on a byte, here one only Mario 3 sets |
| Shinobi II (Game Gear) | A library entry under the same title overrode the tested one | Duplicate removed. A check of every system found no other conflicting duplicates |
| Road Rash (Game Gear) | Dotted blocks and road beside the panel; a pale strip at the left | `emufusion_ws_band`, and the masked column is now black and mirrored in every Game Gear game |
| Lightening Force, Castle of Illusion | Scrambled tiles or grey blocks beside the status bar | `emufusion_ws_band` |
| Castlevania II (Game Boy) | Digits cut off at the sides of the status bar | `emufusion_ws_band`: on the Game Boy, plain background rather than black |
| Super Mario Kart | The game's black rows stopped at its own columns | `emufusion_ws_band` |
| Mortal Kombat II | A wrapped wall and a gap at the arena's left end | `emufusion_ws_bounds` with a fixed edge. One arena seen |
| NHL '94 (SNES) | The ice colour past the crowd | `emufusion_ws_bounds` with the rink's measured ends |
| Gunstar Heroes | Pieces of the logo beside the title, black blocks in the select screens | Scroll rule |
| Star Ocean | The text window's gradient across the empty sides | `emufusion_ws_backdrop=black` |
| NBA Jam, NBA Jam TE | Once played past the menus: black wedges and repeated crowd, and TE's rule only held at tip-off | Fixed screen |
| Micro Machines, Micro Machines 2 | Once driven: stale pieces of track and hard-edged bubbles at the sides, since the game updates its map only near the old window | Fixed screen, until a map reader |

The games that had stayed on menus were then played into real play, and their states replaced: Super Mario Bros. 3, Micro Machines, Madden NFL 95,
Jungle Strike, Desert Strike, Contra: Hard Corps, Gunstar Heroes, both NBA Jams, Final Fantasy Tactics Advance. Star Ocean has reached its first
house but not yet walked outdoors. Those states have not yet run on the Thor.

All of those then ran again on the Thor (2026-11-07, QA build retry-441): 28 games, no crash, every state restored. Right on the device: both Donkey Kong
Country games, All-Stars, Super Mario Kart, Mortal Kombat II, Star Ocean, Road Rash, Shinobi II, Castlevania II, Lightening Force, Castle of Illusion, Gunstar
Heroes, Jungle Strike, Desert Strike, Contra: Hard Corps, Sonic & Knuckles and Donkey Kong Country on the Color. What that run found:

- A Game Gear state stores the picture width, so one saved wide scrambled Micro Machines once it became a narrow game. Fixed in the core: it could reach a player
  whose Quick Resume dates from before the change.
- bsnes-hd with no recipe drew its own 16:9 frame, which the app fitted into 4:3, squeezing the picture by a quarter. Players were not affected, because a narrow
  SNES game runs on Mesen-S and only a recipe moves one to bsnes-hd; the test forced that engine. The core now stays narrow without a recipe, so picking bsnes-hd
  by hand cannot squeeze a game either.
- Madden NFL 95's play-call screen had flat green beside it: its backdrop, closed with `emufusion_ws_backdrop=black`. NHL '94 cannot use that, since its ice is
  the backdrop, so a small ice-coloured patch stays above the crowd at the rink's corners.
- The Mega Drive side pass drew sprites one line off the old picture, a notch in anything crossing the old edge. The frame-generation agent spotted it. Fixed.
- Two test states were bad, not the games: Sonic's was saved paused, and Yoshi's Island's was branched from an old state that restored to black. Six generations of
  load, play and save from a clean start all came back fine, so Quick Resume itself is sound there.

Those fixes then ran on the Thor too (QA build retry-442): Micro Machines clean, Sonic with its clock running, Yoshi's Island's flowers to both edges, Madden's play-call screen on black. Donkey Kong Country 3 joined the readers, and an attract level was wide and clean on the Thor. It was not played by hand: its world map roams freely and a level was not reached. Super Mario Bros. 3 on the
NES did not get past the first Goomba on the Thor, so its wide level is still judged from the Mac.

Lessons:

- A rule found from shots taken while a button is held can be the controller. Check rules with no button down.
- A tile map can start lower than the column writes suggest. DKC's looked broken for hours because its first page is at 6C00, not 7000.
- Tracing every read on the frame a column is drawn found both DKC maps in minutes, where searching memory for the numbers had failed. The trace core's
  `EF_READ=000000-FFFFFF` does it, and `EF_SCROLLDUMP` gives each frame's scrolls and bank 7E to find a camera word.
- A reader that checks itself can be general. The DKC readers compare the middle of each picture with the real tile map, and anywhere they disagree the
  old closed sides return: the map screen, cabins, a game over.
- They place cells from the picture's own scroll, because the game's camera in RAM is already a frame ahead when the line is drawn.

Layer 3 can hold scenery, so every SNES top game was run with it on and off. Yoshi's Island's foreground flowers and DKC 2's ropes were stopping at the
old edge, and now widen, as do All-Stars' clouds. Mortal Kombat II and International Superstar Soccer keep it off: it holds their status text, which would
repeat in the sides. Final Fantasy III keeps it off too, since its dialogue text is there, at the cost of steam that stops at the old edge.

Open: FF3's scattered squares at Narshe's far left are what its map holds there, not a wrap; that the camera never shows them is inferred, and no limit is set for it. DKC 2's climbing levels are
read differently and not yet seen. Wario Land II on the Game Boy Color stays narrow in its opening rooms.

### Systems decided without a widening (2026-11-07)

**Wii.** Twelve top games ran on the Thor (2026-11-07) as far as their titles and menus. Super Mario Galaxy and Galaxy 2, Twilight Princess, Donkey Kong Country Returns, New Super Mario Bros. Wii, Punch-Out!!, Mario Kart Wii, Muramasa and Pandora's Tower draw 16:9 by themselves. Excite Truck ended on a heat stop at its first menu, which also fills the screen. Castlevania: The Adventure ReBirth is 2D at 4:3 and stays so; Contra ReBirth stopped at its save prompt, so it was not seen, but is expected to match. None of these were played past their menus, since nothing needs widening.

**DS.** The owner asked for the top screen only. Played on the Thor with both panels captured, Castlevania: Dawn of Sorrow runs its action on the touch screen,
which is the Thor's lower panel, and keeps only a status page or map on the top screen. Widening that page would add nothing, so no 2D side pass was built. Portrait
of Ruin and Order of Ecclesia are expected to match but were not run. The fourth game is a Metroid Prime Hunters kiosk demo, 3-D on the top screen, not worth a renderer change.
A player can swap the panels per game, which puts the action on the top screen at its own 4:3 with bars. If that ever matters, each line can be drawn three times with the
scroll shifted, keeping the outer columns of the two extra passes, and the lower panel cropped back to its own width through its source rectangle.

**3DS.** Its top screen is 5:3 against the Thor's 16:9, so a wide picture would add about 60 of 1920 pixels a side. Not worth per-game work. Decided from the numbers, not from a device run.

**PC Engine CD.** The one game, Castlevania: Rondo of Blood, needs a System Card (`syscard3.pce` in `ROMs/pcenginecd/BIOS`), which the Thor does not have and the app never
downloads. Without it the game does not start, so it cannot be tested. The widening code in the working copy has not drawn a frame.

## Game files that are not there

Many top-rated files on the Thor are 4 to 7 MB stubs, which the app refuses. They cannot be played, so they have no recipe:
GameCube's Burnout 2, F-Zero GX, Luigi's Mansion, Metroid Prime 2, Mega Man X Collection, SoulCalibur II, Zelda Collector's
Edition and Four Swords Adventures; PS2's Half-Life, Resident Evil 2 and The Simpsons: Hit & Run. Katamari Damacy was listed here by
mistake: what looked like a stub was a macOS `._` sidecar, and the real file is 3 GB.

## Release gate

Each system in the recipe table has `"release"`. Nothing shows to players until it is true, which
needs a system's games to have run on the Thor in real play.

On since 2026-11-05: Mega Drive, Game Gear, NES, SNES, Game Boy Color, GBA; v3.2.155 was the first public release to carry them. Next release adds Game Boy (Pokemon Red walked on the Thor) and Dreamcast (Crazy Taxi and Soul Calibur in real play, 2D the same width narrow and wide, swipe and tap both relaunch). It also adds N64 (compared narrow and wide per game; Excitebike 64 failed and stays narrow) and GameCube (Double Dash raced; 2D keeps its shape through the viewport patch). Titles not yet compared stay narrow. Each has at least one
game played on the Thor, with frame generation on, and Sonic & Knuckles and Contra also with it off.
`settings put global
emufusion_qa_widescreen_all 1` still enables everything for testing.

Mega Drive and SNES have a fallback for titles without their own entry. A map no wider than the picture
stays narrow by itself on the Mega Drive, and the scroll rule and strict tiles do that job on the SNES. Game Gear's was removed: 7 of its 19 top games could not widen
cleanly, so unlisted titles are not offered widening until the rest of the library is triaged.

Most recipes have only been played on the Mac. A device pass here means the engine, prompts and
toggle work on the Thor, not that each listed game has been seen there.
