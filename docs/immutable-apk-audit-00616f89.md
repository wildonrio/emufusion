# Immutable APK audit: 00616f89

Candidate:

`unified-android/build/lucent-3.2.15-phase2-qualification-00616f894c00d065ac0ffa198e09d8eb54ed83bde91fad1d40fc21a32826ab23.apk`

Exact SHA-256:

`00616f894c00d065ac0ffa198e09d8eb54ed83bde91fad1d40fc21a32826ab23`

## Static artifact findings

- The packaged ARM64 frontend contains the exact locked 28-byte subscriber
  replacement at file/virtual offset `0x75fd8`:
  `600640f93b3f0094601240f979170094fd7b41a9f30742f8c0035fd6`.
- The pinned upstream APK (`e595be19...`) contains the required old bytes at
  that offset:
  `600e40f949e0ff97680a40f9fd7b41a900810491f30742f8b0e3ff17`.
- Disassembly of the packaged replacement calls only
  `ApiObject::onGameProcessFinished` and `ProcessLauncher::afterRun`, restores
  registers, and returns. It does not call `FrontendLayer::teardown` or
  `GamepadManager::stop`.
- Exact decoded `MainActivity.launchAmCommand` invokes
  `InProcessGameLaunchCommand.tryLaunch` before the inherited parser and
  returns null when it consumes the internal command. The inherited
  `startActivity` path is reached only when interception returns false.
- The exact command bridge validates `start`, the EmuFusion internal action, and
  the exact MainActivity component, obtains the live MainActivity, and calls
  `InWindowGameHost.handleIntent` on its UI thread.
- The exact metadata command uses Pegasus-compatible `am start` syntax. The
  APK manifest contains no `GameLaunchReceiver`, its DEX contains no such
  class, and no broadcast is required for game launch.
- `theme.qml` is exactly
  `8578d2c16f750913c2af0edc7bc81f9bd7885a6a9222b178821a2ca8a365538a`.
- `theme.cfg` is exactly
  `555b32df5f07153d34e0e40addd3d70068768cb684aaccf1793e5f7a75f4350b`.
- Packaged BlastEm is exactly
  `1f2d4bc8878536d0f3a3783a61d7d73afca2c5797d85cc18f2f85b02ab351422`.
- Packaged Mupen64Plus-Next is exactly
  `fa0a07bb3d07cf61ae140099b6a90e6610a647e44d8e15d8d930ab18aa8c36a2`.
  Both core hashes equal the reproducibility lock and packaged artifact
  manifests. Both use 16 KiB-aligned load segments; Mupen has no unresolved
  `std::__ndk1`/`basic_stringstream` imports.
- One-app, Phase 1 APK, and Phase 2 APK static verifiers pass. The 61 targeted
  launch, routing, return, and APK tests pass.

## First runtime evidence

Evidence directory:

`unified-android/build/runtime-acceptance-00616f89-full`

Two physical-menu NES launches (10-Yard Fight and 1943) reached the lifecycle-
neutral interceptor and the in-window Mesen route. Across both launches:

- Activity starts: 0
- MainActivity resumes caused by launch: 0
- Qt surface recreations caused by launch: 0
- Visible splash/reset frames: 0
- Host return markers: 2 ms and 3 ms
- Exact original game selection restored: yes
- Immediate physical menu input after return: yes
- Background Quick Resume commit: yes

The initial run later stopped because its OCR crop read the correctly visible
selected title `2048` as `e`. That is a harness crop failure, not an emulator or
return failure; it does not constitute full-system runtime qualification.
