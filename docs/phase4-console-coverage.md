# Phase 4 — console coverage

Phases 1-3 registered 48 engines across 56 systems. None of them ships: every
row in every registry is still `shipped: false`. Phase 4 is about *coverage*,
not qualification — it asks which consoles Lucent can reach at all, and closes
the gaps.

The authoritative data is [`engines/phase4-registry.json`](../engines/phase4-registry.json),
validated by `tools/validate_phase4_registry.py`. This document explains it.

## The headline finding

**Six of the nine systems Phase 1 recorded as licence-blocked were never
blocked.** Phase 1 recorded a flat SPDX identifier with an empty `evidence`
field for each, and in six cases the pinned upstream licence text contradicts
it:

| System | Phase 1 recorded | Actual grant | Evidence |
|---|---|---|---|
| Atari 2600 | `GPL-2.0-only` | **GPL-2.0-or-later** | Stella `Copyright.txt`: "either version 2 of the License, or any later version" |
| Atari 5200 / 8-bit | `GPL-2.0-only` | **GPL-2.0-or-later** | atari800 `src/atari.c` and 7 other core files |
| Amstrad CPC | `GPL-2.0-only` | **GPL-2.0-or-later** | Caprice32 `src/cap32.cpp`; 20 of 20 licence-carrying files |
| Atari ST | `GPL-2.0-only` | **GPL-2.0-or-later** | Hatari `src/main.c`, `readme.txt` §1, `hatari.spec` (`GPLv2+`) |
| Commodore 64 | `GPL-2.0-only` | **GPL-2.0-or-later** | VICE `vice/src/main.c` in the exact pinned libretro tree |
| Odyssey² | `Artistic-1.0` | **ClArtistic** | O2EM `COPYING` is titled "The Clarified Artistic License", which the FSF lists as GPL-compatible |

The common cause is a single reading error worth naming so it does not recur:

> **A bare GPLv2 `COPYING` or `LICENSE` document does not establish
> only-versus-or-later.** It is the same document either way. Only the per-file
> grant, or an explicit project declaration, decides it.

The registry now encodes this as policy. `licensePolicy` in
`phase4-registry.json` lists the compatible and incompatible inbound licences,
`tools/validate_phase4_registry.py` refuses any candidate whose SPDX expression
contains an atom outside the allowlist, and a `misaudited` row must quote the
exact wrong SPDX still on record in the earlier registry via
`correctsRecordedSpdx` — so a correction cannot be asserted without being
checkable.

Three Phase 1 blocks were **correct** and are confirmed:

- **PicoDrive** (Sega CD, 32X) — `COPYING`: "Redistributions may not be sold,
  nor may they be used in a commercial product or activity."
- **blueMSX** (MSX) — `license.txt` admits sources are "either under BSD
  license, GPL or freeware", and `Src/VideoChips/V9938.c` adds a field-of-use
  restriction.
- **Beetle VB** (Virtual Boy) — carries SoftFloat 2b. Arguably over-strict
  (see below), but the concern was real.

## Top consoles of all time versus Lucent's coverage

Ranked roughly by lifetime hardware sales, then by library significance.
"Packaged" means the engine is staged into the APK by `unified-android/build.sh`;
no engine is *shipped* in any sense yet.

| Console | Lucent engine | Coverage |
|---|---|---|
| PlayStation 2 | Play / ARMSX2 | covered, packaged |
| Nintendo DS | melonDS DS | covered, packaged |
| Game Boy / Color | SameBoy | covered, packaged |
| PlayStation | SwanStation | covered, packaged |
| Nintendo Switch | Eden | Phase 3 research (opt-in only) |
| Game Boy Advance | mGBA | covered, packaged |
| PlayStation 4 | — | **cannot be covered** |
| PlayStation 3 | aPS3e | Phase 3 research |
| Wii | Dolphin | covered, packaged |
| Xbox 360 | Xenia | Phase 3 research |
| PSP | PPSSPP | covered, packaged |
| Nintendo 3DS | Azahar | covered, packaged |
| Nintendo 64 | Mupen64Plus-Next | covered, packaged |
| NES / Famicom | Mesen | covered, packaged |
| SNES | Mesen-S | covered, packaged |
| Mega Drive / Genesis | BlastEm | covered, packaged |
| Xbox (original) | xemu | Phase 3 research |
| Master System | Gearsystem | covered, packaged |
| Dreamcast | Flycast | covered, packaged |
| PlayStation Vita | Vita3K | Phase 3 research |
| Wii U | Cemu | Phase 3 research |
| Sega Saturn | Beetle Saturn / Ymir | covered, packaged |
| Game Gear | Gearsystem | covered, packaged |
| Atari 2600 | Stella | **blocked → misaudited (Phase 4)** |
| Sega CD | PicoDrive | **blocked (Phase 4)** |
| Sega 32X | PicoDrive | **blocked (Phase 4)** |
| Nintendo Switch 2 | — | **cannot be covered** |
| Xbox One / Series | — | **cannot be covered** |
| PC Engine / TurboGrafx-16 | Beetle PCE Fast | covered, packaged |
| **PC Engine CD** | Beetle PCE Fast | **covered but unadvertised (Phase 4)** |
| Neo Geo AES / MVS | MAME | covered, packaged |
| Neo Geo CD | MAME | covered, packaged (CD BIOS blocked) |
| Atari 7800 | ProSystem | covered, packaged |
| **ColecoVision** | Gearcoleco | **covered but unpackaged (Phase 4)** |
| **Intellivision** | FreeIntv | **covered but unpackaged (Phase 4)** |
| Virtual Boy | Beetle VB | **blocked (Phase 4)** |
| **Neo Geo Pocket / Color** | Beetle NeoPop | packaged; **mono id unrouted (Phase 4)** |
| **WonderSwan / Color** | Beetle Cygne | packaged; **mono id unrouted (Phase 4)** |
| Atari Jaguar | Virtual Jaguar | covered, packaged |
| 3DO | Opera | Phase 3 research |
| **Atari Lynx** | — | **missing (Phase 4)** |
| **Vectrex** | — | **missing (Phase 4)** |
| **Philips CD-i** | — | **missing (Phase 4)** |
| **NEC PC-FX** | — | **missing (Phase 4)** |
| Odyssey² / Videopac | O2EM | **blocked → misaudited (Phase 4)** |
| Commodore 64 | VICE x64sc | **blocked → misaudited (Phase 4)** |
| MSX | blueMSX | **blocked (Phase 4)** |
| Amstrad CPC | Caprice32 | **blocked → misaudited (Phase 4)** |
| Atari ST | Hatari | **blocked → misaudited (Phase 4)** |
| Atari 8-bit / 5200 | Atari800 | **blocked → misaudited (Phase 4)** |
| ZX Spectrum | Fuse | covered, packaged |
| Amiga / CD32 | PUAE | covered, packaged |
| Apple II | AppleWin | covered, packaged |
| **Sharp X68000** | — | **missing, no good candidate (Phase 4)** |
| Arcade | MAME | covered, packaged |
| DOS | DOSBox Pure | covered, packaged |
| ScummVM | ScummVM | covered, packaged |
| Windows / PC | Internal DOSBox Pure for DOS/Windows 3.x/9x; Wine/Box64 for modern Windows | Phase 1 internal baseline implemented; modern Phase 3 container research |

Deliberately **out of Phase 4 scope**, so the boundary is explicit rather than
implied: Fairchild Channel F, Sega Pico, Pokémon Mini, Game & Watch, Mega Duck,
SuperGrafx, PC-98, PC-88, classic Macintosh, the other Commodore 8-bits
(VIC-20, Plus/4, PET, C128), and Nintendo DSi. These are listed as catalog
expansion in [`in-process-emulation-plan.md`](in-process-emulation-plan.md) §10
and are genuinely uncovered, but none is a top console and each would add
compliance surface for a small library.

## The Phase 4 plan, row by row

Every row starts with all ten gates `false` and `shipped: false`. Phase 4
identifies candidates and evidence; it pins no source commit and qualifies
nothing. That is why the `source` gate is closed on every row — no Phase 4 row
carries a pinned commit yet.

The 21 canonical system ids Phase 4 covers, grouped by category. These are the
exact strings in `expectedSystems`; two of the gaps below are literally id bugs,
so the ids matter as much as the names:

```
misaudited          atari2600  atari5200  atari800  amstradcpc  atarist
                    c64  odyssey2
blocked-replacement segacd  sega32x  virtualboy  msx
unpackaged          colecovision  intellivision
unadvertised        wonderswan  neogeopocket
missing             atarilynx  vectrex  pcfx  cdi  x68000
```

### Category `misaudited` — re-audit the incumbent, do not replace it

| System | Engine | Corrected licence | What qualification needs |
|---|---|---|---|
| Atari 2600 | Stella | GPL-2.0-or-later | File-level re-audit; adopt upstream's in-tree libretro core at `src/os/libretro/` (`jni/Application.mk`, `APP_ABI := all`). No firmware. |
| Atari 5200 / 8-bit | Atari800 | GPL-2.0-or-later | File-level re-audit, plus resolving that the tree's `debian/copyright` and `.spec` say GPLv2 while every per-file grant says or-later. **Firmware already solved** — the tree bundles AltirraOS under the FSF all-permissive licence, so all seven Atari ROMs are optional. |
| Amstrad CPC | Caprice32 | GPL-2.0-or-later | Re-audit, then move the recorded blocker to where it belongs: the core `#include`s `rom/464.h`, `rom/6128.h` and `rom/amsdos.h`, compiling Amstrad's firmware in. Upstream's own `debian/copyright` marks `rom/*` as `Copyright: 1984-1990 Amstrad`, `License: Commercial`. Strip and require user-supplied ROMs, as the AppleWin patch already does. |
| Atari ST | Hatari | GPL-2.0-or-later | Re-audit; **ship EmuTOS** (GPL-2.0-or-later) as the default OS ROM instead of demanding `tos.img`, with user TOS as an override. Build must leave IPF/libcapsimage **off** — that exception permits linking proprietary code Lucent must not take. |
| Commodore 64 | VICE x64sc | GPL-2.0-or-later | Re-audit, then handle the real blocker: VICE ships Commodore's KERNAL/BASIC/character ROMs in-tree. Strip and require user-supplied. MEGA65 open-roms (LGPL-3.0-or-later) is the free replacement but its own `STATUS.md` lists most BASIC commands as missing. |
| Odyssey² | O2EM | ClArtistic | Re-audit against the **upstream** grant, not the fork's `COPYING` (which is an Artistic-2.0 text added in 2020 by a libretro contributor, not the copyright holders — harmless here since both are GPL-compatible). BIOS is mandatory and has no free replacement; user-supplied only. |

### Category `blocked-replacement` — genuinely blocked

| System | Blocked engine | Candidate | Licence |
|---|---|---|---|
| Sega CD, 32X | PicoDrive (non-commercial) | **BlastEm** | GPL-3.0-or-later AND Zlib |
| Virtual Boy | Beetle VB (SoftFloat 2b) | **Beetle VB with `v810_fp_ops` ported in** | GPL-2.0-or-later |
| MSX | blueMSX (mixed + field-of-use) | **none** | — |

**Sega CD / 32X** is the best outcome in Phase 4. BlastEm is already a
registered, licence-audited, reproducibly built, APK-staged Lucent engine — and
its tree already contains complete Sega CD support (`segacd.c`,
`cd_graphics.c`, `cdd_mcu.c`, `lc8951.c`, `rf5c164.c`, `cdimage.c`) and 32X
support (`32x.c`, `32x_video.c`, `sh7095.c`, with `libblastem.c` registering
the `32x` and `32xcd` system types). Phase 4 only has to enable two extra
system targets on an engine it already ships. Sega CD needs a user-supplied
regional BIOS read from an external path; 32X needs none. Caveat: 32X
compatibility is unproven — upstream's own FAQ is stale and still claims 32X
has not been started, so it needs validation before it is advertised.

*Rejected:* **Genesis Plus GX**, which is the commonly suggested answer and is
wrong — its `LICENSE.txt` carries the identical "may not be sold" clause as
PicoDrive. Also **ares** (ISC, perfect licence, no Android path) and
**ClownMDEmu** (AGPL, whose network clause would follow the code into the
combined work).

**Virtual Boy**'s block is probably over-strict. The FSF objection to SoftFloat
2b that QEMU acted on in 2014 was a *GPLv2* finding, and GPLv2 §6 tolerates no
additional terms at all; GPLv3 §7 expressly permits limiting liability (a),
preserving notices (b) and requiring indemnification (f), and 2b itself allows
the indemnity to be discharged "possibly via similar legal warning". Debian
ships this exact package in `main`. But rather than rely on that argument, the
plan removes the component: the exposure is one file (`Makefile.common` adds
`fpu-new/softfloat.c`; `v810_cpu.h` includes it), and Mednafen replaced
SoftFloat between 2014-2016 with its own clean-room `v810_fp_ops.cpp`
(GPL-2.0-or-later) — which `beetle-pcfx-libretro` already ships for the
*identical* V810 CPU. Two corrections for anyone re-reading this trail:
SoftFloat 2c did **not** relax those terms (it broadened them; only release 3
is BSD-3-Clause), and the replacement is Mednafen's own code, not SoftFloat 3.
Also note `v810_cpu.cpp` is dual-licensed GPL-2.0-or-later **or** non-commercial
"Reality Boy" terms — take the GPL arm, delete the other.

**MSX has no good candidate and needs a product decision.** Every MSX core with
a working Android build is licence-blocked (blueMSX, fMSX), and the one clearly
licensed emulator cannot run: openMSX declares `license: 'GPL-2.0-only'` on
line 3 of its `meson.build`, contains third-party GPL-2.0-only code that cannot
be upgraded, has no libretro core, and its own release notes call the Android
build "totally broken" and unplanned. FBNeo forbids commercial use. The only
compatible path is MAME/MESS, which is a poor fit: a very large core, MAME
romset naming, and no C-BIOS machine. Note the frustrating shape of this one —
C-BIOS *is* BSD-2-Clause and freely shippable, and would remove the proprietary
BIOS blocker for cartridge games, but MAME cannot use it. The one compatible
core and the one free BIOS cannot be paired.

### Category `unpackaged` — the engine builds but is never staged

`unified-android/build.sh` stages 16 Phase 1 cores and 11 Phase 2 cores.
`gearcoleco` and `freeintv` are in neither list, so two systems with working,
licence-compatible engines have no coverage in any APK.

**ColecoVision** (Gearcoleco, GPL-3.0-only). The BIOS position improved during
this work and the Phase 1 record in `engines/firmware/README.md` is now out of
date. The 8bitworkshop `minbios.asm` (GPL-3.0) **is** reproducible: build
`naken_asm` from source, apply three syntax ports for the modern assembler
(`EQU`→`equ`, `DS`→`resb`, `.DB`→`.db`), assemble and zero-pad to 8192 bytes,
and the result is byte-identical at sha1
`5a84aad05fabab07a48738bdeea7cd620d1ece8b`. It is genuinely clean-room — 20
instructions and 47 code bytes against ~7418 non-filler bytes in the real BIOS,
with a generic 6x8 font rather than the BIOS font. So Lucent can lawfully ship
it as a default so the core boots. **It does not clear the firmware gate**: it
has no BIOS jump table, `0x0F00-0x1FFF` is zero, and its cold-start path
accepts only a `55 AA` header while commercial cartridges use `AA 55` (Coleco
mandated the branded title screen), so real cartridges hit `RST 0` and hang.
Keep a user-supplied slot for the original NTSC BIOS
(sha1 `45bedc4cbdeac66c7df59e9e599195c778d86a92`) and surface ColecoVision as
needing the user's own BIOS. Implementation note: `Memory::LoadBios` validates
only `size == 0x2000` and performs no hash check, so Lucent must enforce the
accepted identity itself.

**Intellivision** (FreeIntv, GPL-2.0-or-later — verified in `LICENSE` and every
source header; GitHub's `NOASSERTION` is a detector artefact caused by a custom
preamble before the verbatim GPL body). Firmware is blocking with **no path at
all**: `exec.bin` and `grom.bin` are both mandatory with no HLE and no core
option, and jzIntv's `miniexec`/`minigrom` have no source, no licence
statement, and populate only 557 of 4096 EXEC words (13.6%), driving only their
author's homebrew. Unlike ColecoVision there is no lawful default; user-supplied
firmware is the only route.

### Category `unadvertised` — the hardware is already emulated, the id is not routed

This category did not exist in the seeded registry and is the correction I am
most confident about. `EngineSystemIdResolver` maps library system names onto
canonical engine ids, and it has aliases for GameCube, 3DS, Mega Drive, DS,
PSX, Dreamcast, Master System, PC Engine, arcade, SNES and NES — **and nothing
else**. So:

| System id | Engine that already emulates it | Why it does not launch |
|---|---|---|
| `wonderswan` | Beetle Cygne (staged, reproducible, audited) | Engine claims only `wonderswancolor`; no alias. Phase 1 deliberately withheld the mono model pending a separately licensed fixture. |
| `neogeopocket` | Beetle NeoPop (staged, reproducible, audited) | Engine claims `ngp`; no alias for `neogeopocket`, `neogeopocketcolor` or `ngpc`. `SystemControlLayouts` and `docs/controller-mapping.md` already name those ids, so such a library gets controls but no engine. |

`pcenginecd` has since left Phase 4: Phase 1's Beetle PCE Fast row now advertises
it behind a user-supplied system-card firmware contract (`PcEngineCdFirmware`).

None of these needs a new engine, and adding one would be a mistake — it would
add compliance surface for no capability. What they need is a QA fixture, an
alias, and in the PC Engine CD case a firmware contract. **PC Engine CD is the
cheapest genuine coverage gain in Phase 4**: the largest library reachable by
an already-approved, already-staged, already-state-qualified engine.

### Category `missing` — no engine anywhere

| System | Candidate | Licence | Android | Firmware |
|---|---|---|---|---|
| Atari Lynx | **Gearlynx** | GPL-3.0-or-later | `platforms/libretro/jni`, `APP_ABI := all`; not on the buildbot, so Lucent builds it (as it already does for sibling Gearsystem) | none |
| Vectrex | **VecX** | GPL-3.0-only | `jni/`, buildbot arm64-v8a binary exists | **embedded copyrighted ROM — must patch** |
| NEC PC-FX | **Beetle PC-FX** | GPL-2.0-or-later | `jni/`, `APP_ABI := all`, buildbot binary | `pcfx.rom`, user-supplied only |
| Philips CD-i | **SAME CDi** | GPL-2.0-or-later | explicit `android-arm64` target, buildbot binary | `cdimono1.zip`, user-supplied only |
| Sharp X68000 | MAME x68000 driver | GPL-2.0-or-later | `mamemess` buildbot binary | IPL + font ROM, user-supplied only |

**Atari Lynx** is clean. Gearlynx is by Ignacio Sanchez, author of Gearsystem
and Gearcoleco which Lucent already builds, so the recipe shape is understood
in-house, and GPL-3.0-or-later needs no compatibility argument at all. Worth
recording that the widely repeated claim that Beetle Lynx's underlying Handy
code is non-commercial is **false** — `mednafen/lynx/license.txt` is the Zlib
licence, which grants use "for any purpose, including commercial
applications". Beetle Lynx is therefore a perfectly good fallback if a
buildbot-tested binary matters more than maintenance activity.

**Vectrex needs a patch, not just a firmware contract.** `libretro-vecx` is
GPL-3.0 code, but `libretro.c` contains `#define STANDARD_BIOS`,
`#include "bios/system.h"` and `memcpy(rom, bios_data, bios_data_size);` with
**no code path that reads a BIOS from the system directory at all**.
`bios/system.bin` is byte-identical to MAME's copyrighted `exec_rom.bin`
(sha1 `65d07426b520ddd3115d40f255511e0fd2e20ae7`), and `bios/fast.bin` matches
MAME's `us-fastboot.bin`, a hack of the original and so still derivative. Smith
Engineering's permission covers not-for-profit circulation only — a
non-commercial restriction GPLv3 §§7 and 10 forbid adding. Lucent must strip
the embedded ROM and add an external user-supplied path, the same pattern as
the existing AppleWin ROM-removal patch. Recorded as `audit-required` rather
than `compatible-candidate` because `vecx.c`, `e6809.c` and `libretro.c` carry
no per-file licence headers at all.

**PC-FX is the cleanest result of the missing set** — verified by whole-tree
grep rather than sampling: 41 files granting GPL-2.0-or-later, one granting
GPL-3.0-or-later, zero version-2-only, zero non-commercial. It also contains
`v810_fp_ops.cpp` and no `fpu-new/`, so unlike Beetle VB it carries no
SoftFloat at all.

**CD-i turns out to be reachable**, which was not expected. SAME CDi is a MAME
fork trimmed to the CD-i driver, with an explicit `android-arm64` target and a
buildbot binary. The alternative, CD-i Emulator, is closed-source Windows-only.

**Sharp X68000 should probably be dropped.** The obvious candidate, `px68k`,
has an actively misleading `COPYING`: it ships the bare GPLv2 text and GitHub
detects GPL-2.0, but upstream `hissorii/px68k` has **no licence at all**, only
five files in the whole repository carry a GPL header, and the entire `x68k/`
emulation directory is unlicensed. Its true origin is Kenjo's WinX68k, whose
`LICENSES` prohibits incorporating the source into commercial software without
consent and permits use only for 非営利 (non-profit) software. Libretro's own
metadata classifies it `license = "Custom Non-Commercial"`. The MAME route is
recorded as the honest floor, not a recommendation: it means MAME romset
conventions and a heavy core for one system, and Sharp's own 2000 IPL ROM
release was granted for non-commercial use, so those bytes cannot be bundled
either. **Recommendation: drop Sharp X68000 from scope.**

## A note on MAME

Three Phase 4 rows reach for MAME. Its `COPYING` says "version 2, as provided
in docs/legal/GPL-2.0" with no or-later clause, which reads as GPL-2.0-only and
would be fatal. That is stale boilerplate:
[`engines/audits/mame-license.json`](../engines/audits/mame-license.json)
enumerated every licence tag under `src/` and found **zero** GPL-2.0-only tags
against 434 GPL-2.0+ ones, and `docs/source/license.rst` states "The MAME
project as a whole is distributed under the terms of the GNU General Public
License, version 2 or later (GPL-2.0+)". Copyright compatibility is
established.

**Trademark is a separate obligation.** MAME is a registered trademark and
`docs/source/license.rst` requires permission to use the name, logo or
wordmark. Copyright compatibility does not carry trademark permission, so any
Lucent surface or generated compliance notice naming this engine must respect
it. Also: only the current `mame`/`mamemess` cores are GPL-2.0+. The
year-numbered legacy cores are not — `mame2000`, `mame2003` and `mame2010`
carry `license = "MAME"` and `mame2003_plus` carries `"MAME Noncommercial"`.
Lucent uses current `libretro/mame`, which is the correct one.

## Cannot be covered

Stated explicitly so the scope boundary is not left implied.

**PlayStation 4.** shadPS4 is an x86 emulator whose only supported platforms
are Windows, Linux, macOS and FreeBSD. It does not run on Android or ARM
handhelds. The one unofficial ARM64 fork, `shandroidPS4`, was abandoned in
early 2025. APKs and "ShadPS4 Plus" branding circulating online have no
relationship to the official project. **No viable path.**

**PlayStation 5.** No emulator project exists.

**Xbox One and Xbox Series.** No credible emulator exists for either. Searches
surface names like "BolXEmu", "Xeon" and various "Xbox Series X emulator"
download sites; these are not real projects and several are outright scam or
adware distribution pages. They must not be treated as candidates. **No viable
path.**

**Nintendo Switch 2.** The only publicly known project, Pound, can boot
firmware with heavy visual artifacts; no commercial game is playable. The
Tegra X1 vulnerabilities that made Switch 1 emulation tractable are patched,
there is no established hardware exploit, and the chip has no consumer
equivalent. Community projections put broad compatibility at 2028-2030 at the
earliest. **No viable path today.**

Note the asymmetry with Phase 3: Switch 1, PS3, Xbox 360, Wii U, Vita and
original Xbox all have real, active emulator projects and are legitimately
"research" rows. The five systems above have nothing to research.

## What Phase 4 does not claim

- No row is qualified. All ten gates are `false` on all 19 rows and
  `shipped` is `false` everywhere. `tools/validate_phase4_registry.py` enforces
  this, and separately enforces that no row can ever set `shipped: true` while
  any gate is `false`.
- No Phase 4 row pins a source commit or archive hash. Candidate identification
  is not source pinning, which is why the `source` gate is closed on every row.
- Licence findings here are engineering records built from primary licence
  text, not legal advice. The `misaudited` rows assert that the recorded SPDX is
  contradicted by the pinned upstream grant — they do **not** assert that a
  file-level audit has been completed. That is exactly why the `license` gate
  stays closed.
- No Phase 4 system may collide with a system an earlier phase already owns
  unless the row explicitly names that engine as its `priorEngine`. The
  validator checks this against `registry.json`, `phase2-registry.json` and
  `phase3-registry.json` on every run.
