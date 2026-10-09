# Open firmware qualification

EmuFusion never downloads or bundles proprietary console firmware. Every accepted
firmware identity must have a primary upstream source, an explicit
redistribution license, a pinned source archive, and a SHA-256 identity.

## ColecoVision

The pinned 8bitworkshop tree contains `minbios.asm`, an adjacent 8 KiB ROM,
and the repository's GPL-3.0 license text. `fetch_open_firmware.sh gearcoleco`
can stage the candidate for audit, but EmuFusion does **not** accept or package it.

The upstream Makefile specifies `naken_asm -b minbios.asm` followed by an
8,192-byte extraction. A pinned contemporary naken_asm build and the current
assembler both reject the checked-in source's mixed legacy directive syntax,
so the source-to-ROM relationship was not reproduced byte-for-byte. The ROM's
official-looking MAME filename and proximity to GPL source are not sufficient
licensing provenance. Gearcoleco therefore remains fail-closed with no accepted
firmware SHA-256 identity.

Reproduction audit details:

- 8bitworkshop commit: `5391cefbc2a3af33e3283362ae854e3862059a07`
- source archive SHA-256: `a62445862e2aaccfe0c4f86fb1c524bb0512bd7beaf3f4b82dc536040611c0cb`
- `minbios.asm` SHA-256: `0def2276404e4a7ff5485a65fdc0103cdfafbc0da2a9506ded1208787972c4b2`
- adjacent ROM SHA-256: `9edcba7a13f7b4852185ad1213bcd2185251b38e80381bfeef3da7cf5817b03d`
- upstream command: `naken_asm -b minbios.asm`, then
  `dd if=out.bin of=minbios.rom bs=1 count=8192`
- pinned 2020-era naken_asm commit
  `cdb829c0c16e5cadf464433e5f621c5d4f64fac7` (built with
  `./configure && make -j4`) rejects `DS` at source line 11
- current audited naken_asm commit
  `247c23706909f09bac77c587780b8a826bbda27c` rejects `O EQU` at source line 3

Because neither exact attempt produces `out.bin`, there is no byte-identical
source-build claim. A future qualification must pin a working assembler or an
independently licensed binary and demonstrate the expected ROM hash.

The candidate is deliberately described as **minimal direct-boot firmware**. It starts
cartridges with a `55 AA` header that initialize the hardware and do not call
Coleco's BIOS routines. It does not make BIOS-dependent commercial cartridges
compatible. The non-release Phase 1 probe establishes only technical feasibility
of the Gearcoleco engine, callbacks, input path, and save-state implementation;
it is not firmware approval and does not claim universal compatibility.

Primary upstream evidence:

- <https://github.com/sehugg/8bitworkshop/tree/5391cefbc2a3af33e3283362ae854e3862059a07/meta/romsrc/coleco>
- <https://github.com/sehugg/8bitworkshop/blob/5391cefbc2a3af33e3283362ae854e3862059a07/LICENSE>

## Intellivision

FreeIntv requires both `exec.bin` and `grom.bin`. Joe Zbiciak's primary jzIntv
source archive distributes `miniexec.bin` and `minigrom.bin`, and those files
can boot its GPL-licensed 4-Tris test content. The same archive does not include
their corresponding assembly source or file-scoped copyright/license notices,
however, and the replacements are intentionally incomplete and incompatible
with many original cartridges. A top-level GPL text beside binary-only firmware
is not enough evidence for EmuFusion to represent those firmware images as clearly
open and safely redistributable.

Consequently FreeIntv remains deny-by-default: its registry entry requires
firmware but has no accepted SHA-256 identities. Neither the core nor the two
mini firmware images may enter a release or qualification APK until complete
primary-source provenance and corresponding source are audited.

Primary upstream evidence:

- <http://spatula-city.org/~im14u2c/intv/dl/jzintv-20200712-src.zip>
- <https://github.com/libretro/FreeIntv/blob/428915baf2bfc032fc03e645f4f8f9c6c3144979/README.md#bios>

## Neo Geo AES/MVS

ngdevkit commit `b36a345dd65097040d48933408586e0a9d7c764b` contains
`nullbios`, an LGPL-3.0-or-later replacement BIOS for the AES and MVS cartridge
hardware. Its own `zoom-rom.py` generates `000-lo.lo`; `sfix.sfix`, `sm1.sm1`,
the main AES/MVS programs, and the support ROMs are likewise generated from
that pinned source. The accepted AES archive is SHA-256
`c9412cfd819b18b57c6c02d360b652ebe9a0fad80225ac3f30c376205c54516f`.

The QA cartridge comes from the primary `ngdevkit-examples` repository at
commit `60f1bd113471ade1a1850e0dca945cffeef38231`. Its checked-in GPL-3.0
license is the conservative distribution label for the canonicalized fixture.
`build_neogeo_open_fixture.py` pins both source archives, rejects any BIOS that
does not match the open nullbios identity, and verifies every generated output.
No SNK BIOS or commercial cartridge data is read or downloaded.

On the Android ARM64 emulator, the constrained MAME core booted that fixture
as Neo-Geo AES and passed 182/183 non-black video frames, 149,216 audio frames,
183 input polls, and 100/100 serialization cycles. MAME reports the expected
checksum warning because its machine declaration names the historical SNK ROM
hash while nullbios is an independently implemented replacement; the running
machine and callback/state proof are recorded in `qa-results/neogeo.log`.

Primary upstream evidence:

- <https://github.com/dciabrin/ngdevkit/tree/b36a345dd65097040d48933408586e0a9d7c764b/nullbios>
- <https://github.com/dciabrin/ngdevkit/blob/b36a345dd65097040d48933408586e0a9d7c764b/COPYING.LESSER>
- <https://github.com/dciabrin/ngdevkit-examples/tree/60f1bd113471ade1a1850e0dca945cffeef38231/01-helloworld>
- <https://github.com/dciabrin/ngdevkit-examples/blob/60f1bd113471ade1a1850e0dca945cffeef38231/COPYING>

## Neo Geo CD/CDZ

Neo Geo CD remains **BLOCKED**. The pinned MAME driver requires a CD/CDZ main
BIOS (`top-sp1.bin`, `front-sp1.bin`, `neocd.bin`, or a supported UniBIOS CD
variant) in addition to `000-lo.lo`. The latter can be generated openly by
ngdevkit, and open disc programs exist, but neither ngdevkit nullbios nor the
older ISC-licensed neopenbios implements the CD/CDZ main BIOS. No primary
upstream source with an explicit redistribution license was found for a
compatible replacement main BIOS. A user dump or an unlicensed BIOS download
is not a legal QA input, so callback output cannot honestly qualify this
system.

Primary upstream evidence:

- <https://github.com/libretro/mame/blob/85eaed9c22242206b68eaca8310cf0dbde331b43/src/mame/snk/neogeocd.cpp>
- <https://github.com/neogeodev/neopenbios/tree/2b28ff0f4adf296757467f179d70d0e64a847f29>
