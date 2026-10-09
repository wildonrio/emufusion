# EmuFusion Android emulator catalog

The long-term plan for replacing visible standalone emulator launches with a
Lucent-owned libretro/native runtime is documented in
[`in-process-emulation-plan.md`](in-process-emulation-plan.md). The table below
describes the current standalone fallback catalog, not completed in-process
integration.

EmuFusion uses standalone Android emulators and does not require RetroArch. The
catalog is keyed by systems that actually contain games. A missing emulator is
never removed automatically, even after the final game for its system is
deleted.

| Systems | Preferred emulator | Update source |
| --- | --- | --- |
| Arcade | MAME4droid Current | <https://github.com/seleuco/MAME4droid-2024/releases> |
| Atari 2600 | 2600.emu | <https://www.explusalpha.com/contents/emuex> |
| NES | NES.emu | <https://www.explusalpha.com/contents/emuex> |
| SNES | Snes9x EX+ | <https://www.explusalpha.com/contents/emuex> |
| Game Boy / Game Boy Color | GBC.emu | <https://www.explusalpha.com/contents/emuex> |
| Game Boy Advance | GBA.emu | <https://www.explusalpha.com/contents/emuex> |
| SG-1000 / Master System / Genesis / Sega CD / 32X | MD.emu | <https://www.explusalpha.com/contents/emuex> |
| PC Engine / PC Engine CD | PCE.emu | <https://www.explusalpha.com/contents/emuex> |
| Neo Geo / Neo Geo CD | NEO.emu | <https://www.explusalpha.com/contents/emuex> |
| Neo Geo Pocket | NGP.emu | <https://www.explusalpha.com/contents/emuex> |
| WonderSwan / WonderSwan Color | Swan.emu | <https://www.explusalpha.com/contents/emuex> |
| Sega Saturn | Saturn.emu | <https://www.explusalpha.com/contents/emuex> |
| Commodore 64 | C64.emu | <https://www.explusalpha.com/contents/emuex> |
| MSX | MSX.emu | <https://www.explusalpha.com/contents/emuex> |
| ColecoVision | ColEm | <https://www.explusalpha.com/contents/emuex> |
| Nintendo 64 | M64Plus FZ Pro, then free edition | <https://github.com/mupen64plus-ae/mupen64plus-ae> |
| PlayStation | DuckStation | <https://github.com/stenzek/duckstation/releases> |
| PlayStation 2 | ARMSX2 | <https://github.com/ARMSX2/ARMSX2> |
| Dreamcast | Flycast | <https://github.com/flyinghead/flycast/releases> |
| Nintendo DS | melonDS | <https://github.com/rafaelvcaetano/melonDS-android/releases> |
| GameCube / Wii | Dolphin | <https://api.dolphin-emu.org/download/> |
| Nintendo 3DS | Azahar | <https://github.com/azahar-emu/azahar/releases> |
| PSP | PPSSPP | <https://dev.ppsspp.org/download/> |
| PlayStation Vita | Vita3K | <https://github.com/Vita3K/Vita3K-Android/releases> |
| Wii U | Cemu | <https://github.com/cemu-project/Cemu/releases> |
| Nintendo Switch | Eden | <https://eden-emu.dev/downloads/> |
| Windows / PC | **Internal DOSBox Pure by default** (DOS and user-supplied Windows 3.x/9x images); optional external Winlator | <https://github.com/schellingb/dosbox-pure>, <https://github.com/brunodev85/winlator/releases> |
| DOS | Magic DOSBox | <https://magicbox.imejl.sk/> |
| ScummVM | ScummVM | <https://www.scummvm.org/downloads/> |

## Android installation boundary

A normal Android application cannot silently install a new third-party APK.
EmuFusion can identify the required emulator, fetch from a trusted official
source, and stage the package, but Android displays a package-installer
confirmation unless EmuFusion is provisioned as the device/profile owner. This is
an Android security boundary, not a theme limitation.

Systems without a maintained standalone Android emulator remain visible when
games are detected, but EmuFusion marks the emulator state as unsupported rather
than silently installing an abandoned or untrusted build.
