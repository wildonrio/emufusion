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
