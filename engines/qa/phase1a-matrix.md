# Phase 1A operability matrix

Evidence captured 2026-08-06 on an Android 15 ARM64 emulator, 180 frames per
test. Full machine-readable evidence is regenerated at
`engines/build/qa-results/results.json`; it is intentionally not committed
because it contains locally built artifacts and an emulator serial.

| System | Core | Result | Callback/state evidence | Save RAM evidence / blocker |
|---|---|---:|---|---|
| NES | Mesen | PASS | video 183; audio 146,092 frames; input polls 183; state 35,840 B equal over 100 cycles | 8,192 B, writable |
| SNES | Mesen-S | PASS | video 183; audio 97,486; input 183; state 600,064 B equal over 100 cycles | 32,768 B, writable |
| Game Boy | SameBoy | PASS | video 183; audio 6,401,242; input 183; state 252,666 B equal over 100 cycles | Fixture exposes no save RAM |
| Game Boy Color | SameBoy | PASS | video 183; audio 6,401,874; input 183; state 252,666 B equal over 100 cycles | Fixture exposes no save RAM |
| Game Boy Advance | mGBA | PASS | video 183; audio 99,930; input 183; state 528,448 B equal over 100 cycles | 131,072 B, writable |
| SG-1000 | Gearsystem | PASS | video 183; audio 134,414; input 183; state 181,309 B equal over 100 cycles | Fixture exposes no save RAM |
| Master System | Gearsystem | PASS | video 183; audio 134,414; input 183; state 181,309 B equal over 100 cycles | Fixture exposes no save RAM |
| Game Gear | Gearsystem | PASS | video 183; audio 134,414; input 183; state 181,315 B equal over 100 cycles | Fixture exposes no save RAM |
| ColecoVision | Gearcoleco | BLOCKED | Non-release technical probe produced non-black video, audio/input callbacks, and 100 deterministic state cycles | Candidate minimal BIOS source did not reproduce its adjacent binary using the pinned upstream build path; accepted firmware hashes remain empty |
| Intellivision | FreeIntv | BLOCKED | The primary jzIntv mini firmware can technically boot legal 4-Tris and pass 100 state cycles, but it is binary-only in the source archive and intentionally incomplete | No corresponding source or file-scoped license evidence for both required files; accepted firmware hashes remain empty and runtime fails closed |
| PlayStation | SwanStation | PASS | video 183 (178 nonzero); audio 134,893; input 183; state 11,534,336 B equal over 100 cycles after one metadata canonicalization | 131,072 B memory card, writable; legal two-instruction PS-X EXE with MIT OpenBIOS |
| Nintendo DS | melonDS DS | PASS | video 183 (all nonzero); audio 100,589 frames; input polls 183; state 19,235,885 B equal over 100 consecutive cycles | Fixture exposes no save RAM; legal upstream homebrew ROM with built-in BIOS/firmware |
| ZX Spectrum | Fuse | PASS | video 183 (all nonzero); audio 161,195; input 183; state 131,072 B equal over 100 consecutive cycles | Fixture exposes no save RAM; original visible 48K SNA checkerboard snapshot |
| Arcade | MAME | PASS | video 183 (180 nonzero); audio 145,248 frames; input polls 183; 6,199,374 B state equal over 100 consecutive cycles after first-cycle metadata canonicalization | Fixture exposes no save RAM; legal `pong.cmd` selects MAME's ROMless Pong driver and contains no ROM data |
| Neo Geo | MAME | PASS | video 183 (182 nonzero); audio 149,216 frames; input polls 183; 963,493 B state equal over 100 consecutive cycles after first-cycle metadata canonicalization | Fixture exposes no save RAM; pinned LGPL ngdevkit nullbios plus GPL homebrew cartridge, with every support file SHA-256 checked |
| PC Engine | Beetle PCE Fast | PASS | video 366 (all nonzero); audio 269,752 frames; input 366 plus divergent button-held replay; 80,586 B state equal over 100 cycles | 2,048 B save RAM, writable; original cc65-built EmuFusion fixture |
| Neo Geo Pocket Color | Beetle NeoPop | PASS | video 366 (362 nonzero); audio 269,057 frames; input 366 plus divergent button-held replay; 31,743 B state equal over 100 cycles | MIT Stargunner fixture; no save RAM exposed |
| WonderSwan Color | Beetle Cygne | PASS | video 366 (362 nonzero); audio 213,810 frames; input 366 plus divergent button-held replay; 86,923 B state equal over 100 cycles | MIT Bug Witch fixture; no save RAM exposed; monochrome WonderSwan remains unadvertised pending its own fixture |
| Neo Geo CD | MAME | BLOCKED | Not run | Open `000-lo.lo` and open content exist, but no explicitly licensed compatible replacement for the required CD/CDZ main BIOS was found |

Summary: **16 PASS, 0 FAIL, 3 BLOCKED**. No entry is promoted to `approved`,
`shipped`, or device-qualified by this result.

## Lucent-owned Android path

The qualification APK exercised all 13 runnable systems through the same path
a user takes: Pegasus collection → controller Select/A action →
`InternalGameLaunchActivity` → `LucentGameActivity`. The final single-run
Activity report recorded **13 PASS and 0 FAIL**. Each case required both a
core-originated RGB frame log and a visible emulator screenshot, so callback
counts alone could not pass the gate. The emulator confirmed:

- direct launch into the Lucent-owned activity with no emulator window;
- non-black core video presented at the correct aspect ratio;
- the EmuFusion touch fallback composited above video on a device with no gamepad;
- gamepad-focus pause, Resume, and Exit interaction plus return to Pegasus;
- an atomically committed Quick Resume state after Exit to EmuFusion;
- automatic Quick Resume restore on a second launch for every runnable system;
- no Java fatal exception, native signal, ANR, or `LucentEngine` error.

This Activity suite is Android-emulator evidence, not a substitute for the physical
controller, audio, display-timing, process-death, reboot, and power-loss checks
required before device qualification.

## Defects found

- The initial probe followed the common callback-before-`retro_init` ordering.
  Mesen/Mesen-S dereference callback-owning objects created by `retro_init`, so
  the harness now initializes after `retro_set_environment` and before the
  other setters. This is a harness interoperability defect, not a core patch.
- Gearcoleco's no-BIOS path returns content-load success and draws a firmware
  error image, so generic callback counts are insufficient. A legal test
  cartridge and candidate minimal BIOS proved technical feasibility, but the
  upstream source/build path did not reproduce the adjacent ROM byte-for-byte;
  it remains unaccepted and Gearcoleco stays blocked.
- Gearcoleco left its libretro save-state header uninitialized before probing
  desktop-versus-libretro formats. The reproducible source patch zeroes that
  header; the patched core completed 100 byte-stable state cycles.
- FreeIntv returns load success without both firmware images and then halts.
  The jzIntv mini binaries technically boot 4-Tris, but absent corresponding
  source and specific licensing keep them out of EmuFusion and FreeIntv blocked.
- SwanStation rewrites 20 bytes of descriptive save-container metadata on the
  first load/save cycle. The emulated payload then remains byte-stable over a
  second cycle; the probe records this explicitly as `stateCanonicalized`.
- melonDS DS required a narrow Android-only source patch: direct PCAP mode is
  disabled because Android has no system libpcap headers, while indirect
  libslirp networking remains compiled. The same patch also guards upstream
  direct-PCAP-only declarations and formatting code.
- MAME's libretro path parser treats an empty `pong.zip` as both a system and
  content argument. QA now uses a deterministic command file containing only
  `pong`; logs confirm `src/mame/atari/pong.cpp` and driver name `pong`, and the
  probe requires non-black video plus 100 consecutive state cycles.
- Neo Geo AES/MVS now uses ngdevkit's open nullbios and hello-world cartridge.
  The replacement differs from MAME's historical SNK checksum and produces an
  expected warning before continuing; the machine boots and passes the full
  callback/state gate. Neo Geo CD is still blocked on its distinct main BIOS.
- Fuse's upstream `empty.z80` snapshot emitted only one non-black startup frame.
  QA now uses an original deterministic 48K SNA snapshot with a persistent
  checkerboard display, so all 183 sampled frames contain visible output.
- The first qualification APK synchronously extracted the bundled theme in
  `Application.onCreate`, producing an avoidable startup ANR. Theme installation
  now runs through EmuFusion's background bootstrap service.
- The real host registered video/audio/input callbacks before `retro_init` and
  crashed in Mesen's callback setter. Host and probe now share the compatible
  environment → init → callback sequence, enforced by a mock-core regression.
- `SurfaceView` could miss its creation callback and its separate composition
  layer obscured EmuFusion overlays. The engine-neutral surface now uses a
  lifecycle-safe `TextureView`, which passed the visible-frame and pause-overlay
  smoke test.
