# Apple II / AppleWin Phase 2 qualification closure

Apple II support is present only in the explicitly requested Phase 2
qualification package. It is not release-approved, auto-selected, or marked
shipped. No Apple ROM, peripheral firmware, game image, or bootable test title
is stored in this repository or APK.

## Exact core and build

- Source: `audetto/AppleWin` commit
  `2045a52d89363005476e670e45df048655edccf7`
- Source archive SHA-256:
  `64f76dc39d7ea9f83f506bfaf7ae8b2c28117feb19a59d224debbd3c04df954b`
- Integration patch:
  `engines/patches/applewin-external-firmware.patch`, SHA-256
  `83c6b91f7af264a6e868a01a1684094a60a85f4441c717f160593b056cce1569`
- Android ARM64 proof artifact SHA-256:
  `e3d45ec269f2ea558225a55e70e4c34661fa7162c6e7d217edd10f0e8c2efc84`

October 5 normal staging uses the 16 KiB-aligned candidate accepted by the
strict Android loader. Two clean builds at the same isolated path produced
that artifact; path-independent reproduction is not proven. No gameplay or
release gate was advanced by this staging change. The checked-in build verifier
compares every `.rom` and `.bin` resource in the pinned upstream archive with
the resulting ELF and rejects any exact embedded match.

## Fail-closed firmware boundary

Upstream AppleWin normally compiles machine, video, disk-controller, and
peripheral firmware into its resource library. EmuFusion's locked patch removes
all of those resources from the core. The libretro frontend instead reads
firmware from the app-private system directory supplied by EmuFusion's host.

Before the core is loaded, `Phase2QualificationCatalog` requires the complete
six-file Apple IIe Enhanced profile in
`engines/applewin-firmware-policy.json`. Files are located in user storage,
verified by exact size and MD5, copied into private app storage, and verified
again. A missing or mismatched file aborts the launch. The files are never
placed in the APK.

The hash profile identifies compatibility bytes; it is not a statement that a
particular user's copy is lawful. The user is responsible for supplying ROMs
they are entitled to use. The registry's firmware and legal-content gates
remain false.

## Host-side integration

The qualification opt-in maps `apple2` to `applewin` through EmuFusion's normal
in-window `MainActivity` route. The physical QA harness accepts
`--apple2-rom` and creates an AppleWin case, but no hardware run has been
claimed by this work. Running the case still requires an explicitly authorized
Thor, user-supplied firmware, and user-supplied game content.

## Still blocked

- complete file-level dependency and license audit;
- lawful firmware-provenance review;
- explicitly licensed bootable test content;
- renderer, audio, controller, save-state, process-death, and migration proof;
- sustained performance and multi-title compatibility;
- physical-device qualification and non-debug release signing.

These blockers intentionally keep `shipped`, firmware, legal-content,
renderer, state, performance, and device gates false.
