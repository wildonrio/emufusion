# aPS3e internal PS3 device qualification checkpoint

Date: 2026-08-11  
Status: partial qualification only; every Phase 3 registry gate remains false and `shipped=false`.

## Immutable identity

- Device: AYN Thor, serial `427c87b2`
- Fingerprint: `qti/kalama/kalama:13/TKQ1.231222.001/eng.Thor.20260206.163241:user/release-keys`
- Repository HEAD: `3052b617b8aa6664ae9fa23a9187ba43a7df0e1a`
- Qualification APK: `lucent-3.2.15-phase2-phase3-qualification-38e7d4da6b92042d06740030b39d54fd543cc75138f6f7ad5d62cdc347743980.apk`
  - bytes `369839184`; SHA-256 `38e7d4da6b92042d06740030b39d54fd543cc75138f6f7ad5d62cdc347743980`
  - same-certificate normal qualification build, non-debuggable
- Embedded `liblucent_native_adapter_aps3e.so`
  - bytes `58677544`; SHA-256 `2a5573bb9d0524f1a6296a775f30f4abbd03bb31a44e435d019bbfaf19b21767`
  - GNU Build ID `80948c636546759b69703a3e0f94a82a56eeb05d`; core `2.40-b5ae1af`
- Upstream commit `b5ae1af50d5e2f3b705506e7380a4504e086840b`; tree `c07c8811ac2ad590cffc11050924f5e82ad2896d`
- Upstream archive: bytes `102044362`; SHA-256 `37fb172d3cd115aa13b29571710f8223c19783ead44cd174f64d686911533ee1`
- Android tagged-pointer patch: bytes `7813`; SHA-256 `fbd05c4975c92b5593fd1a8b6808d28f26aab4977b798cee2216985e666785ea`

## Owner-supplied inputs

No firmware or game content was copied into the repository or APK.

- `/sdcard/Download/PS3UPDAT.PUP`: bytes `206177436`; SHA-256 `99c044293290d0338ffee4ea7d21f993523b1b69012af7f09ae719efe2c9d464`; `SCEUF` container
- Game directory: `/sdcard/Games/ps3/Ico & Shadow of the Colossus Collection, The (World) (En,Fr,Es)`
- `PS3_GAME/USRDIR/EBOOT.BIN`: bytes `798472`; SHA-256 `1544e5ca7de6a56663b28ed706d2500cba009b54573922f3a2dfd576ec30c8e5`
- `PS3_GAME/PARAM.SFO`: bytes `1040`; SHA-256 `53610a67cbe5a340a5f817e4e02e79c32dcd8039c1fb8fbfda95b6b7f59d2185`

Firmware installation is a PASS for this exact identity. A bounded same-certificate diagnostic run independently verified the private PUP copy byte-for-byte; the signed upstream parser was not weakened; and the installed `dev_flash/vsh/etc/version.txt` sentinel was accepted. The diagnostic build was replaced by the normal non-debuggable qualification APK. Firmware remains owner-controlled on the device and was not redistributed.

## Bounded cold-run evidence

The exact run passed `adapter-preopen-environment`, versioned JavaVM handoff, `adapter-open`, `system-directory`, `adapter-create`, `content-load`, adapter-ready, Vulkan setup, `engine-start`, first-run PPU module compilation, and real 1920x1080 Ico/Shadow collection-menu rendering. Adapter-ready occurred at 102 ms and engine-start at 735 ms. The process remained alive without a native crash through the bounded observation.

This is a content-load, real-render/menu, and bounded-stability PASS for this APK/SO/PUP/game identity. It is not a general PS3 gameplay or compatibility pass.

The Android arm64 pointer fix preserves allocator top-byte tags in the two source-proven RPCS3 lock-free paths (`atomic_ptr` and `lf_queue`) with one layout: top 8-bit tag, low 40-bit heap address, and original 16-bit metadata. It rejects nonzero middle address bits before packing and does not disable Android pointer tagging. The run cleared both prior tagged-pointer aborts.

## Frame-generation checkpoint

- Contract `native-pixel-refined-regional-flow-v21-content-unique`; proof schema `21`
- Surface 1920x1080 at approximately 120 Hz
- Dynamic lock observed at `60/120` during compilation and `30/120` at the live collection menu
- Later telemetry observed `generated=2195`, `real=969`, `promoted=711`, with producer estimates varying approximately 27–60 Hz

Frame generation is **not qualified**. The run had `qualificationProof=false`; content-quality counters including proof samples, substantive synthetic pixels, motion correlation, and v21 correct-vector prediction remained zero. Numeric generation counters and 120-Hz presentation alone cannot establish interpolation quality.

## Explicitly unqualified

- Physical AYN controls and final button mapping. A reversible ADB left/right smoke produced distinct animated screenshots but did not prove a selection change or physical controls.
- Audible audio quality. Audio focus and a 48 kHz stereo stream initialized, but device media volume was `0/15`.
- Starting either included game, sustained gameplay, visual correctness beyond the collection menu, gameplay aspect ratio, performance, stutter, or thermals.
- Stop-hold latency and return-to-library behavior.
- Semantic Quick Resume/save-state restoration at the same gameplay position.
- Cheats and immediate activation.
- Frame-generation content quality.

## Fail-closed disposition

The APK verifier passed and confirmed no `PS3UPDAT.PUP` in the APK. Owner firmware and game remain in their original device paths. Failed firmware installation removes only an incomplete `dev_flash` created by that same adapter attempt, never a pre-existing installation. The installed artifact remains the exact normal non-debuggable qualification APK above. Release and all broad Phase 3 gates remain false because they represent the full qualification contract, not the bounded subchecks recorded here.
