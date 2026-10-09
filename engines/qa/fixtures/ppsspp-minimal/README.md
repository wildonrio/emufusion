# PPSSPP minimal smoke fixture

This is Lucent-owned, CC0-1.0 source for a PSP homebrew smoke screen. It uses
only public PSPSDK interfaces and contains no Sony firmware, SDK, game code,
artwork, audio, keys, or other proprietary data.

There is intentionally no checked-in `EBOOT.PBP` yet. The official
`hrydgard/pspautotests` repository cannot be used as a redistributable binary
source because its pinned `LICENSE.txt` is an unfilled placeholder. EmuFusion must
first pin and source-build the PSPDEV toolchain and PSPSDK, preserve their
complete corresponding source and notices, and then record the resulting PBP
hash before this fixture can enter automated qualification.

Until that happens, this directory proves fixture authorship and build intent;
it does not prove PPSSPP gameplay, video, audio, input, or save-state behavior.
