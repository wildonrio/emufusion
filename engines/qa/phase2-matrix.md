# Phase 2 engine registry and qualification matrix

Date: 2026-08-07

This is the checked-in research baseline for every target named in
`docs/in-process-emulation-plan.md` section 8. It is deliberately fail-closed:
no row is approved, shipped, renderer-qualified, state-qualified, or
device-qualified. Some rows now have an off-device compiler/linker proof; that
evidence does not claim the engine runs or may be distributed in EmuFusion.

The machine-readable authority is `engines/phase2-registry.json`; the policy
validator is `tools/validate_phase2_registry.py`.

## Result

**PPSSPP is the first technically and legally runnable candidate.** The choice
is evidence-based rather than a compatibility guess:

- official PPSSPP tag `v1.20.4` peels to a pinned commit;
- Android ARM64, Vulkan, libretro, JIT, and save-state source paths exist;
- the PSP path does not require a proprietary console BIOS;
- EmuFusion has checked in a source-only CC0 smoke fixture; a pinned PSPSDK source
  archive is candidate SDK provenance for the later deterministic toolchain;
- PPSSPP's exact FFmpeg gitlink, Android ARM64 archives, corresponding source,
  and license closure are pinned and audited.

This designation selects the first qualification job. PPSSPP remains
`experimental`; its checked-in, toolchain-locked recipe has produced two
byte-identical normalized FFmpeg-enabled Android AArch64 compiler/linker
proofs. An earlier FFmpeg-off APK passed a bounded one-window AYN Thor
gameplay/audio/input/Stop-return and process-death restore checkpoint, but that
does not qualify the current binary or replace the still-open FMV transition,
legal-content, 100-cycle, migration, Vulkan, sustained-performance,
distribution, or broader-device release gates.

## Qualification matrix

Legend: **locked** means the exact top-level source archive is identified;
**candidate** means evidence exists but the gate has not passed; **blocked**
means work cannot proceed safely without resolving the named issue; **open**
means the qualification work has not run.

| Engine | Systems | Route | Source | License/dependencies | Android ARM64 | Firmware | State | Renderer | Legal content | Registry status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AppleWin | Apple II | in-process libretro | locked plus firmware-removal patch | GPL-2.0-or-later primary; deps open | two byte-identical ARM64 builds; qualification-packaged | exact six-file user profile; provenance gate remains blocked; no ROMs bundled | serialize source; open | software; open | **blocked**: no bootable fixture plus legal ROM path | experimental / qualification only |
| PUAE | Amiga, CD32 | libretro | locked; two clean ARM64 builds match | GPL-2.0-or-later primary; exact 227-object inventory; WHDLoad/data and AROS provenance open | packaged proof core only; device unverified | Amiga: exact hash-bound built-in AROS snapshot, source reproduction open. CD32: exact-size user-only alternatives, never bundled | serialize source; open | software; open | deterministic CC0 boot-block artifact pinned; device execution open | experimental; normal route only in qualification APK |
| Beetle Saturn | Saturn | libretro | locked | GPL-2.0-or-later primary; deps open | published upstream; unverified | **blocked**: Saturn BIOS | serialize source; open | software; open | candidate Jo Engine source; artifact unpinned | experimental |
| Ymir | Saturn | benchmark | locked | GPL-3.0; dependency audit open | **unsupported upstream** | **blocked**: Saturn BIOS | native state; open | Vulkan target; no Android route | candidate Jo Engine source; artifact unpinned | experimental |
| YabaSanshiro | Saturn | benchmark | **blocked**: official source URL unavailable | **blocked**: no primary source to audit | historical app only; unverified | blocked | unverified | unverified | shared Saturn candidate only | source-blocked |
| Flycast | Dreamcast, Naomi, Atomiswave | libretro | locked | GPL-2.0-or-later primary; deps open | exact ARM64 build; hardened Dreamcast one-window checkpoint passed | Dreamcast HLE candidate; **Naomi/Atomiswave blocked** | one Dreamcast process-death restore passed; matrix open | physical GLES Dreamcast passed; Vulkan/loss open | KallistiOS 240pSuite user fixture passed; arcade fixtures absent | experimental |
| Play! | PlayStation 2 | in-process libretro; native route remains a later benchmark | locked | BSD-3-Clause primary; exact staged closure pinned, dependency audit open | **two byte-identical patched Android ARM64 builds; hardened runtime performance failed** | no BIOS required for target route | historical process-death restore; current full state gate not reached | GLES renders but 33–48 FPS and increasing underruns; Vulkan/context-loss open | PS2SDK sample candidate; artifact unpinned | experimental / performance failed |
| Dolphin | GameCube, Wii | in-process libretro | locked, including 30-input staged closure | GPL-2.0-or-later aggregate candidate; dependency SPDX audit open | exact normalized ARM64 build; qualification-packaged in EmuFusion's single-Activity host | no GameCube BIOS; Wii NAND feature-gated | serialize works; final three-title/process-death matrix open | GLES/FBO integration works; final visual/lifecycle matrix open | user-owned Thor titles available for device qualification; distributable fixture still open | experimental / qualification only |
| **PPSSPP** | **PSP** | **libretro** | **locked including FFmpeg** | combined GPL-3.0-only; exact compiled-source/FFmpeg audit complete, final distribution review open | **byte-identical normalized FFmpeg-enabled AArch64 build; current binary not device-tested** | **no BIOS required** | earlier-profile restore only; 100-cycle/migration open | earlier-profile physical GLES only; current GLES/FMV and Vulkan/loss open | **Lucent-owned CC0 source-only fixture; no PBP yet** | **experimental / first candidate** |
| Azahar | Nintendo 3DS | libretro | locked | GPL-2.0-or-later primary; dependency audit open | checksum-pinned official 2125.1.3 ARM64 core; source reproduction open; **hardened Thor first-frame test fails** | **blocked**: keys/system-data policy and identities | serialize exports; runtime blocked | Vulkan and GLES both stall before first frame in MainActivity | devkitPro 3DS example candidate; artifact unpinned | experimental / runtime failed |
| ScummVM | ScummVM | in-process libretro | exact core/dependency closure locked | GPL-3.0-or-later plus exact 15-component/337-object notice bundle | exact reproducible, 16 KiB-aligned ARM64 core; qualification-packaged | no firmware | held-Stop engine-native autosave is fail-closed; generic serialize/history unavailable | GLES host; device matrix open | official Flight of the Amazon Queen freeware download pinned, never bundled | experimental / qualification only |
| Virtual Jaguar | Atari Jaguar | libretro | locked | GPL-3.0 primary; bundled data audit open | **two byte-identical Android ARM64 proof builds** | **blocked**: embedded BIOS provenance | serialize source; open | software; open | Jaguar SDK candidate; artifact unpinned | experimental |

All 14 plan identifiers are covered: `apple2`, `amiga`, `amigacd32`, `saturn`,
`dreamcast`, `naomi`, `atomiswave`, `ps2`, `gamecube`, `wii`, `psp`, `3ds`,
`scummvm`, and `jaguar`. Saturn deliberately has three benchmark candidates.

## Exact top-level source locks

| Engine | Primary upstream | Commit | Commit-archive SHA-256 |
| --- | --- | --- | --- |
| AppleWin libretro fork | <https://github.com/audetto/AppleWin> | `2045a52d89363005476e670e45df048655edccf7` | `64f76dc39d7ea9f83f506bfaf7ae8b2c28117feb19a59d224debbd3c04df954b` |
| PUAE | <https://github.com/libretro/libretro-uae> | `96ebfcfc2c66233ad37f6dc99ee991211dc719ad` | `af671aa1b42eb5b97a05b3ac2e57b6f397f3e17bbd0be7ac204636c2321d3cf0` |
| Beetle Saturn | <https://github.com/libretro/beetle-saturn-libretro> | `84461434f249c1b5cd10c83ae922feae84e1acf8` | `8d7c0e57c4dd31ca1e6e9122e5b4a306abe289963918809a16872a3a3b72d750` |
| Ymir | <https://github.com/StrikerX3/Ymir> | `6ef1ad7077e1209aa36f25d64b225362b8e5a7c9` | `55467d296d8e14542ac479874c0da756aeaff82086bf185613730de9f56325cb` |
| YabaSanshiro | historical <https://github.com/devmiyax/yabause> | unavailable | unavailable; do not substitute a mirror |
| Flycast | <https://github.com/flyinghead/flycast> | `d4fc0774107c4c307346b469499b9303a6ca0ffa` | `fb19f122cb1c8bb9eae302c0e97ef75df168dacc2807da53a3af829cd6a98e71` |
| Play! | <https://github.com/jpd002/Play-> | `50aedca2639521bc498ace0b2be1ea012801a86a` | `a1dffa7cff03de6e40297a2a16ce6a61da31305b74b9233de9fa97238888758f` |
| Dolphin libretro fork | <https://github.com/libretro/dolphin> | `0ff12a5a2835762e0665afe6a161a648b433f996` | `3c6698d6da772065194be118871ce24620f0fdc76894bc568e34d48f93de7494` |
| PPSSPP v1.20.4 | <https://github.com/hrydgard/ppsspp> | `fa50bb1976065c4f8b1b47af227d367fe9771555` | `9054138072d49c306d65c17059bd85662b4ff46abe1ea6bb53d854dc80592ea6` |
| Azahar 2125.1.3 | <https://github.com/azahar-emu/azahar> | `b42d0916ba9799297ae0e27c07d56801da1b5de5` | `8da46436e9d4cd937af2dba5ed39a33c2102e4f833c9051a9bb6e2711831e065` |
| ScummVM | <https://github.com/scummvm/scummvm> | `6aa8fa9b6f9e5a7ae670cc355af1b727ff75c995` | `8e2080a442b4e78c045795714ac4b699023f631e2045fb133d496cd29419fa67` |
| Virtual Jaguar | <https://github.com/libretro/virtualjaguar-libretro> | `59f7f9cc594ae6c6982c2bd8fc0dbf36873f9869` | `81b2d166f1539d6278894965ed049b3267ad6260957bf25046eab2d98dd27c0b` |

Hashes identify GitHub commit tarballs downloaded on the audit date. They are
not upstream release signatures. A release pipeline must mirror the accepted
archives and verify these hashes offline.

## PPSSPP dependency and fixture lock

The official annotated tag `v1.20.4` peels to
commit `fa50bb1976065c4f8b1b47af227d367fe9771555`; the full annotated tag
object is `3a31057b7e44270b4d5cef8c31b6559d51802a3b`. The Android ARM64 libretro
production profile enables the exact pinned FFmpeg gitlink. The following
staged gitlinks are compile inputs and therefore exact registry data. This is
the exact staged compile-input closure for this profile, not a claim about
every unused upstream submodule:

The staged dependency repositories, commits, and archive SHA-256 values are
machine-readable in `engines/ppsspp-source-lock.json`. Two isolated
epoch-fixed builds matched byte-for-byte after removing only LLD's
absolute-root-sensitive GNU build-ID note: normalized Android AArch64 ELF
SHA-256 `1c1b192451375445badc7b69c917b82058d411fd94d66bd6bc00bc781e205487`,
no retained build-ID note, and zero embedded absolute builder paths. That
proves reproducibility only for the FFmpeg-enabled compiler/linker profile.
The production candidate remains
`reproducible=false` and is not legal-content-, gameplay-, renderer-, state-,
performance-, device-, or distribution-qualified.

| Path | Commit |
| --- | --- |
| `ext/SPIRV-Cross` | `4212eef67ed0ca048cb726a6767185504e7695e5` |
| `ext/aemu_postoffice` | `530fee545c27ffb8524a8f496cbbcfdb687fe8c5` |
| `ext/armips` | `a8d71f0f279eb0d30ecf6af51473b66ae0cf8e8d` |
| `ext/armips/ext/filesystem` | `3f1c185ab414e764c694b8171d1c4d8c5c437517` |
| `ext/cpu_features` | `fd4ffc1632db7b4e763bd28ffa6fc9d761cf3587` |
| `ext/glslang` | `50e0708ec3a5c16020c4f845c654b80b8edb80bd` |
| `ext/libadrenotools` | `8fae8ce254dfc1344527e05301e43f37dea2df80` |
| `ext/libadrenotools/lib/linkernsbypass` | `aa3975893d83ef1bc84c321ec60c65fbf1287887` |
| `ext/libchdr` | `8bba7745d758627258b315997a860039244cedaf` |
| `ext/lua` | `7648485f14e8e5ee45e8e39b1eb4d3206dbd405a` |
| `ext/miniupnp` | `27d13ca9beeb5541f5fbf11959dced03dac39972` |
| `ext/naett` | `5f695cfa9fcbf30668a4d3ac4b4abf1cd89a1302` |
| `ext/OpenXR-SDK` | `be392bf6949adeeabad5082aa79d12aacbda781f` |
| `ext/rapidjson` | `73063f5002612c6bf64fe24f851cd5cc0d83eef9` |
| `ext/rcheevos` | `ebfe8ca1bf944358e27200d66964fcb4e00e2487` |
| `ext/zstd` | `f8745da6ff1ad1e7bab384bd1f9d742439278e99` |
| `ffmpeg` | `1e3b4965632f60b1d85360261d1b9dd45444bc71` |
| `libretro/libretro-common` | `76a3d54feb0ee0ce9d59b90aa24694f3782063d3` |

`ext/OpenXR-SDK` remains a header compile input with `OPENXR=OFF`; its commit
archive SHA-256 is
`f91007ec5cd5380184678cb282353a6b97b6ba2278ef4911e217472186a31762`.
`ext/miniupnp` headers remain required with `USE_MINIUPNPC=OFF`; its commit
archive SHA-256 is
`a07a32b2db1f6c5f2823847d47ba6e326b08fbcfe78690801fda9c3aeddf25a3`.

The legal content authority is Lucent-owned CC0 source in
`engines/qa/fixtures/ppsspp-minimal`. There is intentionally no checked-in or
approved `EBOOT.PBP`. PSPSDK commit
`314b2083f2e1eaf145fc5de342736336fe1f0148`, archive SHA-256
`dac46dbb30b8ceaf0780e61f6f23252c2c788315d0f9b57fc694f7a5bc16b562`,
is candidate SDK provenance only. The complete PSPDEV/PSPSDK toolchain must be
pinned, source-built, and noticed before the fixture artifact is built and
hashed. Upstream `pspautotests` binaries must not be used: that repository's
placeholder license text is not a redistribution grant.

## Required qualification sequence

1. Physically validate the exact FFmpeg-enabled artifact through FMV-to-game
   transitions with non-black video callbacks, stable audio, and clean return.
2. Build the EmuFusion CC0 fixture using a completely pinned source-built
   PSPDEV/PSPSDK toolchain and record all source/toolchain/artifact hashes.
3. Run the normal and sanitizer hardware-render host suites without a physical
   device, then execute callback/state probes on an Android ARM64 emulator.
4. Require nonzero video, audio, and input callbacks; 100 state cycles;
   process-death restore; Vulkan context destroy/recreate; GLES fallback; and
   explicit state-version rejection/migration behavior.
5. Run two clean offline builds and compare normalized outputs. No recipe may
   become approved merely because compilation succeeds once.
6. Measure sustained performance, thermal behavior, controller mapping, audio
   underruns, frame pacing, and lifecycle behavior on explicitly authorized
   target hardware; device observations do not bypass the other gates.

Virtual Jaguar now also has an exact-pin Android ARM64 compiler/linker proof:
two fresh checksum-verified archive extractions produced the byte-identical
artifact SHA-256
`9644e815b82776f7633e2d6408b93738ef0ce9d7294a63c529ce2deda77e64ed`
through `engines/build_core.sh virtualjaguar`. This advances only the Android
build gate. The embedded BIOS/data provenance, legal fixture, compatibility,
renderer, state, performance, and physical-device gates remain closed, so the
engine is neither packaged nor selected.

Play! now has an exact-pin Android ARM64 compiler/linker proof as well. The
official top-level archive plus all six direct and six nested gitlinks used by
the Android libretro profile are locked in `engines/play-source-lock.json`.
Two fresh archive restagings with pinned NDK 27.0.12077973, CMake 3.31.6, and
Ninja 1.12.1, plus EmuFusion's reviewed host/audio/state patches, produced the
byte-identical stripped AArch64 ELF SHA-256
`a90adf7f06c12c8a7505420a18b18bfaca812737a7612436b69041a89fb86843`
through `engines/build_core.sh play`. On the authorized AYN Thor, the exact
artifact booted a user-owned God of War disc inside `LucentGameActivity`,
accepted controller input, returned to EmuFusion, and restored the exact
difficulty menu after process death with live graphics and audio. A later
strict gameplay run exposed sustained ~38 FPS throughput and accumulating
AudioTrack underruns, so the performance gate explicitly fails. This passes
the Android build gate and records a first runtime checkpoint without implying
gameplay qualification. The dependency license audit,
legal PS2 fixture, Vulkan/context-loss lifecycle, broad compatibility,
100-cycle state, sustained performance, and multi-device gates remain closed;
Play! is qualification-packaged but not auto-selected for release.

The next Play! work is its 100-cycle/multi-title/device matrix and comparison
against a thin native adapter. Dolphin follows because its mature Android
engine has a much larger adapter/state scope, then Flycast after its dependency audit.
Firmware- and source-blocked rows remain behind those candidates regardless
of apparent technical convenience.
