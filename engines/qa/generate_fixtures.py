#!/usr/bin/env python3
"""Create or stage deterministic, legally redistributable Phase 1A QA ROMs."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "engines" / "build"
SOURCES = BUILD / "sources"
OUTPUT = BUILD / "qa-fixtures"
OPEN_NEOGEO = BUILD / "qa-open-neogeo"
OPEN_NEWCORES = BUILD / "qa-open-newcores"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(name: str, data: bytes) -> Path:
    path = OUTPUT / name
    path.write_bytes(data)
    return path


def make_mame_command() -> bytes:
    # MAME's libretro command-file path avoids pretending an empty archive is
    # a ROM set. The pinned Pong driver is ROMless; this command contains only
    # the public driver identifier and therefore distributes no game data.
    return b"pong\n"


def make_dos_zip() -> bytes:
    # Original 16-bit DOS .COM program. It selects VGA mode 13h, fills the
    # framebuffer with a visible color, then loops. A single executable inside
    # a ZIP is DOSBox Pure's documented direct-content form and needs neither a
    # guest operating system nor third-party game data.
    program = bytes([
        0xB8, 0x13, 0x00, 0xCD, 0x10,       # mov ax,13h; int 10h
        0xB8, 0x00, 0xA0, 0x8E, 0xC0,       # mov ax,a000h; mov es,ax
        0x31, 0xFF,                         # xor di,di
        0xB0, 0x2A,                         # mov al,2ah
        0xB9, 0x00, 0xFA,                   # mov cx,64000
        0xF3, 0xAA,                         # rep stosb
        0xEB, 0xFE,                         # loop forever
    ])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        info = zipfile.ZipInfo("LUCENT.COM", date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 0
        info.external_attr = 0
        archive.writestr(info, program)
    return output.getvalue()


def make_neogeo_command() -> bytes:
    # The support files are staged beside this command by the Android runner.
    # Explicit absolute paths avoid MAME's ambiguous content-directory parser.
    remote = "/data/local/tmp/lucent-phase1a-qa/fixtures"
    return (
        f"aes -hash {remote} -rompath {remote} -cart 01_helloworld\n"
    ).encode("ascii")


def stage(name: str, source: Path, expected_sha256: str) -> Path:
    if not source.is_file():
        raise SystemExit(f"missing upstream fixture: {source}")
    actual = sha256(source)
    if actual != expected_sha256:
        raise SystemExit(f"fixture checksum mismatch for {source}: {actual}")
    destination = OUTPUT / name
    shutil.copyfile(source, destination)
    return destination


class _NesAssembler:
    """The tiny, deterministic subset of 6502 assembly used by the NES ROM.

    Keeping the source here avoids depending on a downloaded assembler while
    still making every branch and absolute address reviewable.  It deliberately
    supports only the two relocation forms used below.
    """

    def __init__(self, origin: int = 0x8000) -> None:
        self.origin = origin
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[str, int, str]] = []

    def emit(self, *values: int) -> None:
        self.code.extend(value & 0xFF for value in values)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate NES label: {name}")
        self.labels[name] = self.origin + len(self.code)

    def absolute(self, opcode: int, label: str) -> None:
        self.emit(opcode, 0, 0)
        self.fixups.append(("absolute", len(self.code) - 2, label))

    def branch(self, opcode: int, label: str) -> None:
        self.emit(opcode, 0)
        self.fixups.append(("branch", len(self.code) - 1, label))

    def finish(self) -> bytes:
        for kind, offset, label in self.fixups:
            if label not in self.labels:
                raise ValueError(f"missing NES label: {label}")
            target = self.labels[label]
            if kind == "absolute":
                self.code[offset:offset + 2] = target.to_bytes(2, "little")
                continue
            source_after_operand = self.origin + offset + 1
            displacement = target - source_after_operand
            if not -128 <= displacement <= 127:
                raise ValueError(
                    f"NES branch {label} is out of range: {displacement}"
                )
            self.code[offset] = displacement & 0xFF
        return bytes(self.code)


def make_nes() -> bytes:
    """Build EmuFusion's original, redistributable NES qualification ROM.

    The NROM-128 cartridge deliberately exercises what a physical acceptance
    run must prove instead of merely calling libretro callbacks:

    * a white one-tile border touches all four 256x240 source edges, with a
      solid coloured interior, so full-height 4:3 geometry is measurable;
    * broad spatial motion, a sprite and a counter advance on deterministic
      60/50/40/30 unique-image schedules while callbacks remain native-rate;
    * A/B/Select/Start/Up/Down/Left/Right each select a distinct interior
      colour, while Start also freezes motion for exact Quick Resume evidence;
    * pulse channel 1 emits an approximately 440 Hz constant-volume tone; and
    * a Mesen custom cheat ``6000:3F`` changes the border from white to red.

    All mutable state is ordinary CPU/PPU/APU/RAM state and therefore belongs
    to the core's serialized snapshot.  No proprietary code or artwork is
    embedded.
    """
    # Mapper 0, horizontal mirroring, battery-backed 8 KiB PRG RAM.
    header = bytearray(b"NES\x1a" + bytes([1, 1, 0x02, 0x00]) + bytes(8))
    asm = _NesAssembler()

    # Zero-page contract used by the physical verifier.
    pad, last_pad, frame, motion_x = 0x00, 0x01, 0x02, 0x03
    frozen, control_colour, border_colour = 0x04, 0x05, 0x06
    cadence_mode, cadence_phase, scroll_x, control_hold = 0x07, 0x08, 0x09, 0x0A
    last_direction, direction_hold = 0x0B, 0x0C

    asm.label("reset")
    asm.emit(0x78, 0xD8)                    # SEI; CLD
    asm.emit(0xA2, 0x40, 0x8E, 0x17, 0x40) # disable APU frame IRQ
    asm.emit(0xA2, 0xFF, 0x9A, 0xE8)       # stack=$01FF; X=0
    asm.emit(0x8E, 0x00, 0x20)             # PPUCTRL=0
    asm.emit(0x8E, 0x01, 0x20)             # PPUMASK=0
    asm.emit(0x8E, 0x10, 0x40)             # disable DMC IRQ
    asm.emit(0x2C, 0x02, 0x20)
    asm.label("wait_vblank_1")
    asm.emit(0x2C, 0x02, 0x20)
    asm.branch(0x10, "wait_vblank_1")      # BPL

    # Clear all 2 KiB internal RAM, including the OAM staging page.
    asm.emit(0xA9, 0x00, 0xA2, 0x00)       # LDA #0; LDX #0
    asm.label("clear_ram")
    for page in range(8):
        asm.emit(0x9D, 0x00, page)
    asm.emit(0xE8)
    asm.branch(0xD0, "clear_ram")
    asm.emit(0x8D, 0x00, 0x60)             # actual cheat-observable RAM=0
    # NES OAM treats Y=0 as visible. Hide all 64 entries before defining the
    # two authored sprites below; zero-filled unused entries would otherwise
    # contaminate the upper-left geometry/control oracle after the first DMA.
    asm.emit(0xA9, 0xF8, 0xA2, 0x00)
    asm.label("hide_oam")
    asm.emit(0x9D, 0x00, 0x02, 0xE8, 0xE8, 0xE8, 0xE8)
    asm.branch(0xD0, "hide_oam")

    asm.label("wait_vblank_2")
    asm.emit(0x2C, 0x02, 0x20)
    asm.branch(0x10, "wait_vblank_2")

    # Palette $3F00-$3F1F.
    asm.emit(0xA9, 0x3F, 0x8D, 0x06, 0x20)
    asm.emit(0xA9, 0x00, 0x8D, 0x06, 0x20)
    asm.emit(0xA2, 0x00)
    asm.label("copy_palette")
    asm.absolute(0xBD, "palette_data")     # LDA palette_data,X
    asm.emit(0x8D, 0x07, 0x20, 0xE8, 0xE0, 0x20)
    asm.branch(0xD0, "copy_palette")

    # Copy one complete 32x30 nametable plus attributes. Each source page has
    # its own 256-byte loop: interleaving page0[X], page1[X], ... would scramble
    # the intended row-major border even though it still writes 1024 bytes.
    asm.emit(0xA9, 0x20, 0x8D, 0x06, 0x20)
    asm.emit(0xA9, 0x00, 0x8D, 0x06, 0x20)
    for page in range(4):
        asm.emit(0xA2, 0x00)
        asm.label(f"copy_nametable_{page}")
        asm.absolute(0xBD, f"nametable_{page}")
        asm.emit(0x8D, 0x07, 0x20)
        asm.emit(0xE8)
        asm.branch(0xD0, f"copy_nametable_{page}")

    # Sprite 0 is continuous motion. Sprite 1 is a per-control position marker.
    asm.emit(0xA9, 0x70, 0x8D, 0x00, 0x02) # Y
    asm.emit(0xA9, 0x02, 0x8D, 0x01, 0x02) # tile
    asm.emit(0xA9, 0x00, 0x8D, 0x02, 0x02) # attributes
    asm.emit(0xA9, 0x20, 0x8D, 0x03, 0x02) # X
    asm.emit(0xA9, 0xF8, 0x8D, 0x04, 0x02) # hidden Y
    asm.emit(0xA9, 0x07, 0x8D, 0x05, 0x02) # tile
    asm.emit(0xA9, 0x01, 0x8D, 0x06, 0x02) # palette 1
    asm.emit(0xA9, 0x18, 0x8D, 0x07, 0x02) # X

    # Pulse 1: duty=50%, constant volume=15, timer=253 (~440.4 Hz NTSC).
    asm.emit(0xA9, 0x01, 0x8D, 0x15, 0x40) # enable pulse 1
    asm.emit(0xA9, 0xBF, 0x8D, 0x00, 0x40)
    asm.emit(0xA9, 0x00, 0x8D, 0x01, 0x40)
    asm.emit(0xA9, 0xFD, 0x8D, 0x02, 0x40)
    asm.emit(0xA9, 0xF8, 0x8D, 0x03, 0x40)

    # Enable NMI, background and sprites (including the leftmost 8 pixels).
    asm.emit(0xA9, 0x80, 0x8D, 0x00, 0x20)
    asm.emit(0xA9, 0x1E, 0x8D, 0x01, 0x20)
    asm.emit(0xA9, 0x00, 0x8D, 0x05, 0x20, 0x8D, 0x05, 0x20)
    asm.label("main")
    asm.absolute(0x4C, "main")

    asm.label("nmi")
    asm.emit(0x48, 0x8A, 0x48, 0x98, 0x48) # preserve A/X/Y

    # Read controller 1 into $00 in canonical NES bit order:
    # bit0=A, 1=B, 2=Select, 3=Start, 4=Up, 5=Down, 6=Left, 7=Right.
    asm.emit(0xA9, 0x01, 0x8D, 0x16, 0x40)
    asm.emit(0xA9, 0x00, 0x8D, 0x16, 0x40, 0x85, pad)
    asm.emit(0xA2, 0x08)
    asm.label("read_pad")
    asm.emit(0xAD, 0x16, 0x40, 0x4A, 0x66, pad, 0xCA)
    asm.branch(0xD0, "read_pad")

    # Retain a recent direction long enough for the host's reviewed Stop/Select
    # latch to deliver Select on release. Select+direction can then select a
    # mode directly even though the two guest edges are intentionally ordered.
    asm.emit(0xA5, pad, 0x29, 0xF0)
    asm.branch(0xF0, "direction_neutral")
    asm.emit(0x85, last_direction, 0xA9, 0x1E, 0x85, direction_hold)
    asm.absolute(0x4C, "direction_done")
    asm.label("direction_neutral")
    asm.emit(0xA5, direction_hold)
    asm.branch(0xF0, "direction_done")
    asm.emit(0xC6, direction_hold)
    asm.label("direction_done")

    # Plain Select cycles the unique-image cadence 60->50->40->30. A recently
    # held direction selects directly: Up=60, Right=50, Down=40, Left=30.
    # Emulation continues at native cadence; intentionally repeated images are
    # submitted normally and production's latestImageIsUnique() decides which
    # ones are real producer frames. No test clock or timestamp is fabricated.
    asm.emit(0xA5, pad, 0x29, 0x04)
    asm.branch(0xF0, "select_done")
    asm.emit(0xA5, last_pad, 0x29, 0x04)
    asm.branch(0xD0, "select_done")
    asm.emit(0xA5, direction_hold)
    asm.branch(0xF0, "select_cycle")
    asm.emit(0xA5, last_direction, 0xC9, 0x10)
    asm.branch(0xF0, "select_mode_60")
    asm.emit(0xC9, 0x80)
    asm.branch(0xF0, "select_mode_50")
    asm.emit(0xC9, 0x20)
    asm.branch(0xF0, "select_mode_40")
    asm.emit(0xA9, 0x03)
    asm.absolute(0x4C, "select_store_mode")
    asm.label("select_mode_60")
    asm.emit(0xA9, 0x00)
    asm.absolute(0x4C, "select_store_mode")
    asm.label("select_mode_50")
    asm.emit(0xA9, 0x01)
    asm.absolute(0x4C, "select_store_mode")
    asm.label("select_mode_40")
    asm.emit(0xA9, 0x02)
    asm.absolute(0x4C, "select_store_mode")
    asm.label("select_cycle")
    asm.emit(0xE6, cadence_mode, 0xA5, cadence_mode, 0x29, 0x03,
             0x85, cadence_mode)
    asm.absolute(0x4C, "select_reset_phase")
    asm.label("select_store_mode")
    asm.emit(0x85, cadence_mode)
    asm.label("select_reset_phase")
    asm.emit(0xA9, 0x00, 0x85, cadence_phase)
    asm.label("select_done")

    # Start's rising edge toggles a persistent freeze.  A frozen screenshot is
    # the semantic state oracle for Stop -> Quick Resume -> relaunch.
    asm.emit(0xA5, pad, 0x29, 0x08)
    asm.branch(0xF0, "start_done")
    asm.emit(0xA5, last_pad, 0x29, 0x08)
    asm.branch(0xD0, "start_done")
    asm.emit(0xA5, frozen, 0x49, 0x01, 0x85, frozen)
    asm.label("start_done")
    asm.emit(0xA5, pad, 0x85, last_pad)
    asm.emit(0xA5, frozen)
    asm.branch(0xD0, "motion_done")
    # Six-NMI schedule: mode0 updates 6/6, mode1 5/6, mode2 4/6 and
    # mode3 3/6. Broad tile scrolling makes every scheduled update visible to
    # the generator's 16x9 content signature; unscheduled callbacks are exact
    # repeated pixels and therefore remain submitted-but-not-unique evidence.
    asm.emit(0xE6, cadence_phase, 0xA5, cadence_phase, 0xC9, 0x06)
    asm.branch(0x90, "phase_ready")         # BCC
    asm.emit(0xA9, 0x00, 0x85, cadence_phase)
    asm.label("phase_ready")
    asm.emit(0xA5, cadence_mode)
    asm.branch(0xF0, "visual_update")
    asm.emit(0xC9, 0x01)
    asm.branch(0xF0, "mode_50")
    asm.emit(0xC9, 0x02)
    asm.branch(0xF0, "mode_40")
    # mode 30: update phases 0,2,4 only.
    asm.emit(0xA5, cadence_phase, 0x29, 0x01)
    asm.branch(0xD0, "motion_done")
    asm.absolute(0x4C, "visual_update")
    asm.label("mode_50")
    asm.emit(0xA5, cadence_phase)
    asm.branch(0xF0, "motion_done")
    asm.absolute(0x4C, "visual_update")
    asm.label("mode_40")
    asm.emit(0xA5, cadence_phase)
    asm.branch(0xF0, "motion_done")
    asm.emit(0xC9, 0x03)
    asm.branch(0xF0, "motion_done")
    asm.label("visual_update")
    asm.emit(0xE6, frame, 0xE6, motion_x, 0xE6, scroll_x,
             0xA5, scroll_x, 0x29, 0x07, 0x85, scroll_x)
    asm.label("motion_done")
    asm.emit(0xA5, motion_x, 0x8D, 0x03, 0x02)

    # Every control has both a unique colour and a unique marker Y position.
    asm.emit(0xA5, pad)
    asm.branch(0xF0, "neutral_control")
    asm.emit(0xA2, 0x00, 0xA5, pad)
    asm.label("find_control")
    asm.emit(0x4A)
    asm.branch(0xB0, "control_found")
    asm.emit(0xE8, 0xE0, 0x08)
    asm.branch(0xD0, "find_control")
    asm.label("control_found")
    asm.absolute(0xBD, "control_colours")
    asm.emit(0x85, control_colour)
    asm.absolute(0xBD, "control_y")
    asm.emit(0x8D, 0x04, 0x02)
    asm.emit(0xA9, 0x1E, 0x85, control_hold)
    asm.absolute(0x4C, "control_done")
    asm.label("neutral_control")
    # The Thor host intentionally latches a short Stop/Select tap only after
    # release. Retain every control's authored colour/marker for 30 NMIs so the
    # physical screenshot proves Select as reliably as ordinary face buttons.
    asm.emit(0xA5, control_hold)
    asm.branch(0xF0, "neutral_expired")
    asm.emit(0xC6, control_hold)
    asm.absolute(0x4C, "control_done")
    asm.label("neutral_expired")
    asm.emit(0xA9, 0x21, 0x85, control_colour)
    asm.emit(0xA9, 0xF8, 0x8D, 0x04, 0x02)
    asm.label("control_done")

    # Mesen's custom-code format 6000:3F overrides this read.  The border's
    # white->red transition is large and deterministic, not a log-only pass.
    asm.emit(0xAD, 0x00, 0x60, 0xC9, 0x3F)
    asm.branch(0xD0, "cheat_off")
    asm.emit(0xA9, 0x16)
    asm.absolute(0x4C, "cheat_colour_done")
    asm.label("cheat_off")
    asm.emit(0xA9, 0x30)
    asm.label("cheat_colour_done")
    asm.emit(0x85, border_colour)

    # Update the two background colours and one visible four-state counter tile.
    asm.emit(0xA9, 0x3F, 0x8D, 0x06, 0x20)
    asm.emit(0xA9, 0x01, 0x8D, 0x06, 0x20)
    asm.emit(0xA5, control_colour, 0x8D, 0x07, 0x20)
    asm.emit(0xA5, border_colour, 0x8D, 0x07, 0x20)
    asm.emit(0xA9, 0x20, 0x8D, 0x06, 0x20)
    asm.emit(0xA9, 0x6F, 0x8D, 0x06, 0x20)
    asm.emit(0xA5, frame, 0x4A, 0x4A, 0x4A, 0x4A, 0x29, 0x03,
             0x18, 0x69, 0x03, 0x8D, 0x07, 0x20)
    asm.emit(0xA9, 0x02, 0x8D, 0x14, 0x40) # OAM DMA
    asm.emit(0xA5, scroll_x, 0x8D, 0x05, 0x20)
    asm.emit(0xA9, 0x00, 0x8D, 0x05, 0x20)
    asm.emit(0x68, 0xA8, 0x68, 0xAA, 0x68, 0x40) # restore; RTI

    asm.label("irq")
    asm.emit(0x40)
    asm.label("palette_data")
    asm.emit(*([0x0F, 0x21, 0x30, 0x16] * 4))
    # Sprite palette 1 is reserved for the control-position marker. Its
    # palette-index-1 magenta can never equal any control background (including
    # Up's white field), making the unique authored Y oracle observable for all
    # eight controls on the physical scaler.
    asm.emit(*( [0x0F, 0x30, 0x27, 0x16] +
                [0x0F, 0x25, 0x27, 0x16] +
                [0x0F, 0x30, 0x27, 0x16] * 2 ))
    asm.label("control_colours")
    asm.emit(0x16, 0x2A, 0x28, 0x24, 0x30, 0x12, 0x1A, 0x27)
    asm.label("control_y")
    asm.emit(0x18, 0x30, 0x48, 0x60, 0x78, 0x90, 0xA8, 0xC0)

    # Border tile 1 surrounds the complete source image. A deterministic,
    # nonperiodic field of eight authored texture tiles fills it. This avoids
    # aliasing against the generator's 16x9 signature lattice and gives its
    # block matcher unique local patches instead of repeating vertical stripes.
    nametable = bytearray(1024)
    for row in range(30):
        for column in range(32):
            nametable[row * 32 + column] = (
                1 if row in {0, 29} or column in {0, 31}
                else 9 + ((row * 17 + column * 29 + row * column * 7 +
                           (column >> 1) * 3) % 8)
            )
    for page in range(4):
        asm.label(f"nametable_{page}")
        asm.emit(*nametable[page * 256:(page + 1) * 256])

    program = asm.finish()
    if len(program) > 0x3FFA:
        raise ValueError("NES qualification program overlaps interrupt vectors")
    prg = bytearray([0xEA] * 0x4000)
    prg[:len(program)] = program
    for offset, label in ((0x3FFA, "nmi"), (0x3FFC, "reset"), (0x3FFE, "irq")):
        prg[offset:offset + 2] = asm.labels[label].to_bytes(2, "little")

    chr_rom = bytearray(0x2000)

    def tile(index: int, low: tuple[int, ...], high: tuple[int, ...]) -> None:
        if len(low) != 8 or len(high) != 8:
            raise ValueError("NES CHR tiles require two eight-byte planes")
        start = index * 16
        chr_rom[start:start + 16] = bytes(low + high)

    tile(0, (0xF0,) * 8, (0x0F,) * 8)       # colour1 | colour2 stripes
    tile(1, (0x00,) * 8, (0xFF,) * 8)       # solid palette colour 2
    tile(2, (0x3C, 0x7E, 0xFF, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C), (0x00,) * 8)
    tile(3, (0x18,) * 8, (0x00,) * 8)
    tile(4, (0xF0,) * 8, (0x00,) * 8)
    tile(5, (0xAA, 0x55) * 4, (0x00,) * 8)
    tile(6, (0x7E, 0x42, 0x42, 0x42, 0x42, 0x42, 0x42, 0x7E), (0x00,) * 8)
    tile(7, (0x18, 0x18, 0x18, 0xFF, 0xFF, 0x18, 0x18, 0x18), (0x00,) * 8)
    tile(8, (0x0F,) * 8, (0xF0,) * 8)       # inverse broad-motion stripes
    for tile_index in range(9, 17):
        low_rows = []
        high_rows = []
        for y in range(8):
            seed = (tile_index * 37 + y * 73 + 0x5A) & 0xFF
            low = ((seed * 109) ^ (seed >> 3) ^ (y * 0x33) ^
                   (tile_index * 0x17)) & 0xFF
            # Complementary planes make every pixel palette value 1 or 2
            # (never transparent) while retaining the PRNG-like spatial bits.
            high = (~low) & 0xFF
            low_rows.append(low)
            high_rows.append(high)
        tile(tile_index, tuple(low_rows), tuple(high_rows))
    return bytes(header + prg + chr_rom)


def make_snes() -> bytes:
    # Original 32 KiB LoROM that deliberately presents a bright, non-black
    # backdrop.  A bare CPU loop can make a probe report changing/nonzero
    # storage bytes while the actual SNES image remains black, so initialize
    # CGRAM color zero and release forced blank before entering the loop.
    rom = bytearray([0xEA] * 0x8000)
    rom[:34] = bytes([
        0x78,                         # SEI
        0x18, 0xFB,                   # CLC; XCE (native mode)
        0xC2, 0x30,                   # REP #$30 (16-bit A/X)
        0xA9, 0xFF, 0x1F, 0x1B,       # LDA #$1FFF; TCS
        0xE2, 0x20,                   # SEP #$20 (8-bit A)
        0xA9, 0x80, 0x8D, 0x00, 0x21, # forced blank
        0x9C, 0x21, 0x21,             # CGRAM address = 0
        0xA9, 0x1F, 0x8D, 0x22, 0x21, # color 0 low: full red
        0x9C, 0x22, 0x21,             # color 0 high
        0xA9, 0x0F, 0x8D, 0x00, 0x21, # display on, full brightness
        0x80, 0xFE,                   # loop forever
    ])
    title = b"LUCENT CALLBACK TEST "
    rom[0x7FC0 : 0x7FC0 + 21] = title.ljust(21, b" ")
    rom[0x7FD5] = 0x20  # LoROM
    rom[0x7FD6] = 0x02  # ROM + RAM + battery
    rom[0x7FD7] = 0x08  # 32 KiB ROM
    rom[0x7FD8] = 0x05  # 32 KiB SRAM
    rom[0x7FD9] = 0x01
    rom[0x7FDA] = 0x33
    rom[0x7FDB] = 0x00
    for offset in (0x7FEA, 0x7FEC, 0x7FEE, 0x7FFA, 0x7FFC, 0x7FFE):
        rom[offset : offset + 2] = b"\x00\x80"
    rom[0x7FDC : 0x7FE0] = b"\x00\x00\xff\xff"
    return bytes(rom)


def make_sega(region_size: int | None) -> bytes:
    rom = bytearray([0x00] * 0x8000)
    # Original Z80 program that fully initializes the video hardware and draws
    # a solid, non-black tile. Merely selecting the VDP backdrop is not enough:
    # several implementations keep a black active image while display output
    # is disabled. The explicit mode/register, palette, and tile writes make
    # the visual-output gate meaningful without embedding third-party assets.
    program = bytearray([0xF3, 0x31, 0xF0, 0xDF])  # DI; LD SP,$DFF0

    def out_a(value: int, port: int) -> None:
        program.extend([0x3E, value & 0xFF, 0xD3, port & 0xFF])

    def vdp_register(register: int, value: int) -> None:
        out_a(value, 0xBF)
        out_a(0x80 | register, 0xBF)

    def vdp_write_address(address: int, *, cram: bool = False) -> None:
        out_a(address & 0xFF, 0xBF)
        out_a(((address >> 8) & 0x3F) | (0xC0 if cram else 0x40), 0xBF)

    if region_size is None:
        # SG-1000/TMS9918 Mode 2. Display on, name table at $1800, pattern
        # table at $0000, and colour table at $2000.
        for register, value in enumerate((0x02, 0xE0, 0x06, 0xFF,
                                          0x03, 0x36, 0x07, 0x04)):
            vdp_register(register, value)
        vdp_write_address(0x0000)
        for _ in range(8):
            out_a(0xFF, 0xBE)  # tile 0: foreground pixels on every row
        vdp_write_address(0x2000)
        for _ in range(8):
            out_a(0xF4, 0xBE)  # white foreground, blue backdrop
    else:
        # Master System / Game Gear Mode 4. Display on with the same table
        # locations used by devkitSMS, then define palette entry 1 and tile 0.
        for register, value in enumerate((0x04, 0x40, 0xFF, 0xFF, 0xFF,
                                          0xFF, 0xFF, 0x00, 0x00, 0x00,
                                          0xFF)):
            vdp_register(register, value)
        vdp_write_address(2 if region_size == 0x6C else 1, cram=True)
        out_a(0xFF if region_size == 0x6C else 0x3F, 0xBE)
        if region_size == 0x6C:
            out_a(0x0F, 0xBE)  # Game Gear 12-bit white, high byte
        vdp_write_address(0x0000)
        for _ in range(8):
            # Four bitplanes per row; plane 0 set selects palette entry 1.
            for byte in (0xFF, 0x00, 0x00, 0x00):
                out_a(byte, 0xBE)
    loop = len(program)
    program.extend([0xC3, loop & 0xFF, loop >> 8])
    rom[:len(program)] = program
    if region_size is not None:
        rom[0x7FF0 : 0x7FF8] = b"TMR SEGA"
        rom[0x7FFF] = region_size
        checksum = sum(rom[:0x7FF0]) & 0xFFFF
        rom[0x7FFA : 0x7FFC] = checksum.to_bytes(2, "little")
    return bytes(rom)


def make_colecovision() -> bytes:
    # Original 32 KiB cartridge with a direct-boot 55AA header. It calls no
    # proprietary BIOS routines: the legal minimal 8bitworkshop BIOS only
    # validates the header and jumps to Cart_Start at offset $000A. The program
    # initializes the TMS9918 itself, draws a solid non-black tile, starts an
    # SN76489 tone, and continuously samples controller port 1.
    rom = bytearray([0x00] * 0x8000)
    rom[:2] = b"\x55\xaa"
    start = 0x8100
    rom[0x0A:0x0C] = start.to_bytes(2, "little")
    program = bytearray([0xF3, 0x31, 0xFF, 0x73])  # DI; LD SP,$73FF

    def out_a(value: int, port: int) -> None:
        program.extend([0x3E, value & 0xFF, 0xD3, port & 0xFF])

    def vdp_register(register: int, value: int) -> None:
        out_a(value, 0xBF)
        out_a(0x80 | register, 0xBF)

    def vdp_write_address(address: int) -> None:
        out_a(address & 0xFF, 0xBF)
        out_a(((address >> 8) & 0x3F) | 0x40, 0xBF)

    # TMS9918 Mode 2, display enabled without NMI, name table $1800,
    # pattern table $0000, colour table $2000, blue backdrop.
    for register, value in enumerate((0x02, 0xC0, 0x06, 0xFF,
                                      0x03, 0x36, 0x07, 0x04)):
        vdp_register(register, value)
    vdp_write_address(0x0000)
    for _ in range(8):
        out_a(0xFF, 0xBE)
    vdp_write_address(0x2000)
    for _ in range(8):
        out_a(0xF4, 0xBE)

    # SN76489 tone channel 0, audible volume.
    for value in (0x84, 0x20, 0x90):
        out_a(value, 0xFF)
    loop = len(program)
    program.extend([0xDB, 0xFC, 0xC3, (start + loop) & 0xFF,
                    ((start + loop) >> 8) & 0xFF])
    rom[start - 0x8000:start - 0x8000 + len(program)] = program
    return bytes(rom)


def make_psx() -> bytes:
    # Original PS-X EXE containing two MIPS instructions: jump to self, then a
    # branch-delay-slot NOP. SwanStation boots it with its bundled MIT OpenBIOS,
    # so qualification needs neither a commercial disc nor proprietary BIOS.
    header = bytearray(0x800)
    header[:8] = b"PS-X EXE"
    struct.pack_into(
        "<IIIIIIIIII", header, 0x10,
        0x80010000, 0, 0x80010000, 0x800, 0, 0, 0, 0, 0x801FFFF0, 0,
    )
    payload = bytearray(0x800)
    struct.pack_into("<II", payload, 0, 0x08004000, 0x00000000)
    return bytes(header + payload)


def make_zx_spectrum() -> bytes:
    # Original 48K .sna snapshot. The display bitmap is a checkerboard and its
    # attributes select bright white over blue, while a three-byte Z80 loop at
    # $8000 keeps the machine alive. A 48K SNA stores PC on the emulated stack.
    header = bytearray(27)
    header[19] = 0x04                  # IFF2 enabled
    header[23:25] = (0x9000).to_bytes(2, "little")
    header[25] = 0x01                  # interrupt mode 1
    header[26] = 0x01                  # blue border

    ram = bytearray(0xC000)            # address range $4000-$FFFF
    for row in range(192):
        # ZX bitmap rows are interleaved by character row and pixel line.
        bitmap_row = ((row & 0xC0) << 5) | ((row & 0x07) << 8) | ((row & 0x38) << 2)
        for column in range(32):
            ram[bitmap_row + column] = 0xAA if (row + column) & 1 else 0x55
    ram[0x1800:0x1B00] = bytes([0x4F]) * 0x300  # bright white ink, blue paper
    ram[0x4000:0x4003] = b"\xC3\x00\x80"       # JP $8000
    ram[0x5000:0x5002] = (0x8000).to_bytes(2, "little")
    return bytes(header + ram)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sameboy = SOURCES / "sameboy-213a12ce93d66b105a113debd9396306066a7cfc"
    mgba = SOURCES / "mgba-afd6f14eaf8bd35214ed3fb9dc69a92bfc3877a9"
    freeintv = SOURCES / "freeintv-428915baf2bfc032fc03e645f4f8f9c6c3144979"
    melonds_ds = SOURCES / "melonds-ds-2748dfb9409c94e6828d937d04e334f35127ba7c"

    fixtures: list[dict[str, object]] = []

    def add(system: str, core: str, path: Path, provenance: str, license_id: str,
            support_files: list[dict[str, str]] | None = None,
            qualification: dict[str, object] | None = None) -> None:
        entry: dict[str, object] = {
            "system": system,
            "core": core,
            "file": path.name,
            "sha256": sha256(path),
            "provenance": provenance,
            "license": license_id,
        }
        if support_files:
            entry["supportFiles"] = support_files
        if qualification:
            entry["qualification"] = qualification
        fixtures.append(entry)

    add("nes", "mesen", write("lucent-callback-test.nes", make_nes()),
        "Deterministically generated by this script; original EmuFusion qualification fixture",
        "GPL-3.0-only", qualification={
            "profile": "emufusion-nes-v1",
            "nativeGeometry": {"width": 256, "height": 240,
                               "displayAspect": "4:3"},
            "edgeMarker": "one-tile solid-white border on all four source edges",
            "continuousMotion": "broad nonperiodic textured field scroll, sprite X and counter advance on scheduled unique frames",
            "cadenceModes": {
                "selection": "plain Select cycles 60->50->40->30; Select+Up=60, Select+Right=50, Select+Down=40, Select+Left=30",
                "schedulePeriodNmis": 6,
                "60": {"uniqueFramesPerPeriod": 6, "repeatedFramesPerPeriod": 0},
                "50": {"uniqueFramesPerPeriod": 5, "repeatedFramesPerPeriod": 1},
                "40": {"uniqueFramesPerPeriod": 4, "repeatedFramesPerPeriod": 2},
                "30": {"uniqueFramesPerPeriod": 3, "repeatedFramesPerPeriod": 3},
                "clockSource": "native NES NMI; no host or timestamp override",
            },
            "audio": {"channel": "APU pulse 1", "frequencyHzApprox": 440.4,
                      "constantVolume": 15},
            "controls": {
                "A": {"nesBit": 0, "palette": "16", "markerY": 24},
                "B": {"nesBit": 1, "palette": "2A", "markerY": 48},
                "Select": {"nesBit": 2, "palette": "28", "markerY": 72},
                "Start": {"nesBit": 3, "palette": "24", "markerY": 96,
                          "semanticAction": "toggle-motion-freeze"},
                "Up": {"nesBit": 4, "palette": "30", "markerY": 120},
                "Down": {"nesBit": 5, "palette": "12", "markerY": 144},
                "Left": {"nesBit": 6, "palette": "1A", "markerY": 168},
                "Right": {"nesBit": 7, "palette": "27", "markerY": 192},
            },
            "quickResumeOracle": "Start freezes all continuous visible state",
            "cheat": {"format": "mesen-custom", "code": "6000:3F",
                      "address": "6000", "value": "3F",
                      "visibleEffect": "border white-to-red"},
        })
    add("snes", "mesen-s", write("lucent-callback-test.sfc", make_snes()),
        "Deterministically generated by this script; original Lucent QA fixture",
        "GPL-3.0-only")
    add("gb", "sameboy", stage(
        "dmg-acid2.gb", sameboy / ".github/actions/dmg-acid2.gb",
        "464e14b7d42e7feea0b7ede42be7071dc88913f75b9ffa444299424b63d1dff1"),
        "SameBoy commit 213a12c .github/actions; Matt Currie Acid2 test",
        "MIT")
    add("gbc", "sameboy", stage(
        "cgb-acid2.gbc", sameboy / ".github/actions/cgb-acid2.gbc",
        "197fb0bcec544f0400527fc707e0a94f55435974986e6986b424ace5de81720e"),
        "SameBoy commit 213a12c .github/actions; Matt Currie Acid2 test",
        "MIT")
    add("gba", "mgba", stage(
        "mgba-2d-wrap-test.gba", mgba / "cinema/gba/obj/2d-wrap/test.gba",
        "e6b82e57a15f7878e116761e7c2a31ead6885f972a118adaf97acf39102309dd"),
        "mGBA commit afd6f14 cinema/gba/obj/2d-wrap upstream test fixture",
        "MPL-2.0")
    add("sg1000", "gearsystem", write("lucent-callback-test.sg", make_sega(None)),
        "Deterministically generated by this script; original Lucent QA fixture",
        "GPL-3.0-only")
    add("mastersystem", "gearsystem", write("lucent-callback-test.sms", make_sega(0x4C)),
        "Deterministically generated by this script; original Lucent QA fixture",
        "GPL-3.0-only")
    add("gamegear", "gearsystem", write("lucent-callback-test.gg", make_sega(0x6C)),
        "Deterministically generated by this script; original Lucent QA fixture",
        "GPL-3.0-only")
    add("colecovision", "gearcoleco", write(
        "lucent-firmware-gate-test.col", make_colecovision()),
        "Deterministically generated by this script; original Lucent QA fixture",
        "GPL-3.0-only")
    add("psx", "swanstation", write("lucent-callback-test.psexe", make_psx()),
        "Deterministically generated by this script; original Lucent QA PS-X EXE",
        "GPL-3.0-only")
    add("intellivision", "freeintv", stage(
        "4-tris.rom", freeintv / "open-content/4-Tris/4-tris.rom",
        "ee6a16ef1cf4af171396a049656fc8d4ad7d00c3ca349ed9b9f269e688f30af4"),
        "FreeIntv commit 428915b open-content/4-Tris by Joe Zbiciak",
        "GPL-2.0-only")
    add("zxspectrum", "fuse", write(
        "lucent-visible-test.sna", make_zx_spectrum()),
        "Deterministically generated by this script; original Lucent QA fixture",
        "GPL-3.0-only")
    add("arcade", "mame", write("pong.cmd", make_mame_command()),
        "Deterministically generated MAME command selecting the ROMless Pong driver; contains no ROM data",
        "GPL-3.0-only")
    neogeo_expected = {
        "aes.zip": "c9412cfd819b18b57c6c02d360b652ebe9a0fad80225ac3f30c376205c54516f",
        "neogeo.xml": "98eb7ec517e56e5c3998fd40b05310666ae8e4c65c00f0972c017aad50f6b4f6",
        "01_helloworld.zip": "9c39bb9391f10974361c0383a4811a94fa2fe8a3b619294f4bfa019b7d82cca4",
    }
    if all((OPEN_NEOGEO / name).is_file() for name in neogeo_expected):
        support_files: list[dict[str, str]] = []
        for name, expected in neogeo_expected.items():
            staged = stage(name, OPEN_NEOGEO / name, expected)
            support_files.append({
                "file": staged.name,
                "sha256": expected,
                "provenance": (
                    "dciabrin/ngdevkit nullbios nightly-202607191609"
                    if name == "aes.zip" else
                    "dciabrin/ngdevkit-examples commit 60f1bd113471ade1a1850e0dca945cffeef38231"
                ),
                "license": "LGPL-3.0-or-later" if name == "aes.zip" else "GPL-3.0-only",
            })
        add("neogeo", "mame", write("ngdevkit-open.cmd", make_neogeo_command()),
            "Generated command selecting the pinned open ngdevkit AES cartridge fixture",
            "GPL-3.0-only", support_files)
    add("nds", "melonds-ds", stage(
        "melonds-homebrew-periph-slot2.nds", melonds_ds / "test/nds/periph_slot2.nds",
        "4eaf6d5b0450b9a658273cccead71f432f6c191b75e7066fc7201b0ce5d0285b"),
        "melonDS DS commit 2748dfb test/nds/periph_slot2.nds upstream homebrew fixture",
        "GPL-3.0-or-later")
    add("dos", "dosbox-pure", write("lucent-dos-callback-test.zip", make_dos_zip()),
        "Deterministically generated by this script; original Lucent DOS COM fixture",
        "CC0-1.0")
    add("windows", "dosbox-pure", write(
        "emufusion-internal-pc-callback-test.zip", make_dos_zip()),
        "Deterministically generated by this script; original EmuFusion internal-PC fixture",
        "CC0-1.0")
    add("atari7800", "prosystem", stage(
        "lucent-atari7800-qa.a78", OPEN_NEWCORES / "lucent-atari7800-qa.a78",
        "2cf0210fdf85765d0fcf0270144fb75f7565e134686a79ba9ef87629850b5a4d"),
        "Original CC0 Lucent fixture reproducibly built with 7800basic v0.41 tag 03aebb85206f53046425c19a236f65ae80d9f498; source is engines/qa/fixtures/atari7800/lucent_atari7800_qa.bas",
        "CC0-1.0")
    add("pcengine", "beetle-pce-fast", stage(
        "lucent-pce-qa.pce", OPEN_NEWCORES / "lucent-pce-qa.pce",
        "bf15e23d6a20235717db494af91dcab4d557b83aa2573ed4d278f5e45c576be6"),
        "Original Lucent fixture reproducibly built with cc65 commit 547d923; source is engines/qa/fixtures/pce/lucent_pce_qa.c",
        "GPL-3.0-only")
    add("ngp", "beetle-neopop", stage(
        "stargunner.ngc", OPEN_NEWCORES / "stargunner.ngc",
        "089e2d9520dc2f84d34a33b1dfa1710eb9a429d90b3b0a195a06ccab89c9022f"),
        "Tixul/Stargunner commit fb9295cd710ddb923dffb99a7513d954ff119fe0",
        "MIT")
    add("wonderswancolor", "beetle-cygne", stage(
        "bug-witch.wsc", OPEN_NEWCORES / "bug-witch.wsc",
        "ccacf10e9734630ad4f9a5b2301dcc3aca7b06a0e92771d92d95a2ced0487d21"),
        "RegionallyFamous/SwanSong-Originals v3.3.0 (commit 28547c5c); Bug Witch",
        "MIT")

    manifest = {"schemaVersion": 1, "fixtures": fixtures}
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(OUTPUT / "manifest.json")


if __name__ == "__main__":
    main()
