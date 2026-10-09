# Internal core aspect-ratio contract

EmuFusion has one aspect authority for every packaged internal engine:
`PresentationGeometry.resolveAspect()`. The loaded engine/game's plausible AV
aspect always wins, including runtime mode changes. A hardware-native table is
consulted only when an engine reports no usable aspect; base pixel dimensions
are the final fallback. A frontend system default must never replace a running
game's declared mode.

Presentation uses uniform containment. Narrower pictures normally touch the top
and bottom and receive centred black pillars. A picture wider than the surface
fits to the width and is vertically centred. No source row or column may be
cropped, no destination may leave the panel, and no path may independently
stretch the horizontal or vertical axis.

There are no generic source-side crop rules. Mesen-S uses vertical overscan
`None`, PPSSPP's exact-16:9 crop is disabled, Mupen's overscan crop and offsets
are disabled, and the libretro frontend requests that cores expose their full
overscan signal. Bars or border pixels produced by the emulated game/video
signal are content and must not be deleted globally.

Core configuration must describe the original display before its live report
becomes authoritative. Mupen64Plus-Next and SwanStation use their documented
`4:3` modes, with every widescreen hack disabled. Mesen uses its region-aware
`Auto` mode, Dolphin uses `Auto`, ARMSX2 uses `Auto 4:3/3:2`, and fixed-pixel
handhelds retain their panel ratios. These are engine-wide defaults rather than
per-title exceptions; a live official mode reported by a running game still
wins at the presentation boundary.

The resolved value is applied before an Android gameplay surface can attach:

- Software libretro frames use `PresentationGeometry.fitFrame()` for the Canvas
  destination rectangle.
- Hardware GLES and Vulkan sessions query AV information after content load,
  resolve the display aspect in Java, and pass it through their JNI host before
  attach. An invalid or unresolved value aborts preparation rather than
  presenting a stretched frame.
- GLES frontend-framebuffer cores create an aspect-sized private target and
  blit the complete submitted viewport into a centered black destination.
  Render allocation is distinct from that display fit: it must be at least
  the current core-declared output dimensions. PPSSPP's1920x1088 output must
  not be clipped to its1906x1080 Thor display-fit size. This minimum is applied
  at attach, surface resize and rebind; spontaneous runtime geometry growth
  without those events still needs separate coverage.
- GLES cores that require framebuffer zero retain that rendering contract. If
  the resolved aspect differs from the actual Surface, presentation copies the
  complete rendered window through a private target and fits it back into the
  centered destination. It never trims the source to resemble another ratio.
  A matching Surface keeps the zero-copy direct path.
- Vulkan full-frame presentation prefers the same resolved value over the
  core-reported aspect. Top/bottom dual-screen crops deliberately use the crop's
  own pixel aspect instead of incorrectly reusing the whole-frame aspect.

`native/run_tests.sh` covers unchanged direct-window presentation and the
two-blit 4:3-on-16:9 direct fitting path, including the complete source
viewport. Geometry tests require wider-than-panel content to remain wholly
visible. `native/run_experimental_gles_java_test.sh` proves the resolved aspect
remains render-thread-affine and reaches the host before attach.
`tools/tests/test_proportional_video_scaling.py` checks the shared authority and
all software/GLES/Vulkan source plumbing.

This is host/source coverage only. Physical-device visual qualification is a
separate acceptance step and must not be inferred from these tests.

## Widescreen hack and the core-option override file (2026-09-06)

The engine-wide 4:3 defaults above remain the baseline. A separate, opt-in
"widescreen hack" (`WidescreenSettings.isHackEnabled()`, key `hackEnabled`,
default **false**, plus per-system overrides `hack.<system>` in
`on|off|auto`) selects each core's documented true-geometry mechanism for one
launch. It never stretches: every mechanism widens the game's projection or
applies a per-game FOV patch, and the core then reports 16:9 through the same
AV path, so `PresentationGeometry.resolveAspect()` stays the single aspect
authority. The historic `enabled` flag (Dolphin's native Wii SYSCONF 16:9)
keeps its meaning and its default.

`WidescreenHackPolicy` (`unified-android/src/com/thorium/preview/game/`) owns
the decision; the pure table lives in `WidescreenHackTable`:

| System | Availability | Options written when on |
|---|---|---|
| n64 (mupen64plus-next) | hack | `mupen64plus-aspect=16:9 adjusted`, `mupen64plus-169screensize=1920x1080` |
| psx (swanstation) | hack | `swanstation_GPU_WidescreenHack=true`, `swanstation_Display_AspectRatio=16:9` |
| ps2 (armsx2) | hack | `armsx2_widescreen_patches=enabled`, `armsx2_aspect_ratio=16:9`; `armsx2_cheats=enabled` always (the core maps it to `EmuCore/EnableCheats`, which gates the per-game pnach cheats) |
| gamecube, wii (dolphin) | hack | `dolphin_widescreen_hack=enabled` unless a per-game 16:9 code was selected; `dolphin_cheats_enabled=enabled` always |
| dreamcast (flycast) | hack | `reicast_widescreen_cheats=enabled`, `reicast_widescreen_hack=enabled` (the table pokes the game's FOV; the hack widens the viewport) |
| psp (ppsspp) | cheats | none; `ppsspp_cheats=enabled` always, per-game CWCheat codes via the cheat hooks |
| wiiu, switch, ps3 | native | none |
| 3ds, nds, 2D systems | unavailable | none |

Plumbing: before an engine opens, `WidescreenHackPolicy.prepareLaunch()`
writes or removes `<engine root>/lucent-core-overrides.txt`
(`CoreOptionOverrideFile`: `key=value` per line, 64 entries, 64 KiB, atomic
`.part` rename). `<engine root>` is `engine-system/<engineId>` for every
in-process engine, the same directory the libretro sessions pass to the native
host as `system_directory`. `register_core_variable_defaults()` in
`native/lucent_libretro_host.c` loads that file once per host and applies an
override only when the requested token is one the core itself advertises in
its v0 option string; anything else is logged and ignored. Overrides are
launch-time only, matching the cores' "restart required" semantics, and the
file is replaced on every launch so a stale value cannot leak between games.

Two host defaults changed for the cheat system rather than for aspect:
`dolphin_cheats_enabled=enabled` and `ppsspp_cheats=enabled`, so live
`retro_cheat_set` toggles execute continuously.

Companion: `GET /settings/widescreen-hack` (`WidescreenHackEndpoint`), with
`?enabled=0|1` and `?system=<id>&mode=on|off|auto`; theme settings row
"WIDESCREEN HACK". Tests: `native/tests/host_test.c` (override file flips
keys, unknown tokens ignored, removal restores defaults),
`test/com/thorium/preview/game/WidescreenHackPolicyTest.java`,
`tools/tests/test_widescreen_hack.py`, and the retained pins in
`tools/tests/test_widescreen_enhancements.py`.
