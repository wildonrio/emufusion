# Switch/Wii U prerequisite-aware routing audit — 2026-08-10

## Scope and verdict

This is a host-only, fail-closed audit. No ADB command or Thor interaction was
used. It covers update/import discovery, readiness persistence, internal versus
external routing, Eden provenance/direct launch, title-time Switch fallback,
and the held-Stop contract while a standalone emulator owns the foreground.

| Requirement | Host verdict | Evidence / limitation |
|---|---|---|
| Search readable internal and removable storage during update/import | PASS | `ImportManager.runScan()` refreshes prerequisites before ROM discovery. `NativeAdapterPrerequisites` supplies shared storage plus readable `/storage/*` volumes; the executing test finds valid inputs in arbitrary nested internal and removable locations and fails closed on unreadable/missing roots. |
| Persist only readiness | PASS | The route preference contains only `READY` or `NOT_READY`. Source markers use SHA-256 content identities and hashed marker names; no source/archive filename or path is stored or logged. |
| No missing-filename UI | PASS | Launch revalidation collapses all detail to `Internal emulator prerequisites are unavailable`. The title fallback and Settings authorization text contain no key or firmware filename. |
| Switch baseline | PASS | A valid production-key manifest is required. Firmware is optional at the system route and is installed only when a valid NCA-bearing archive is voluntarily present. Invalid optional firmware does not disable keys-only readiness. |
| Wii U key validation | PASS | The scanner mirrors Cemu's parser: comments, whitespace, hyphens, and underscores are accepted, malformed lines are rejected, and Cemu's generated example key is explicitly rejected. |
| Internal default only when ready | PASS | The native-adapter catalog plus persisted readiness gates the internal route. An explicit External choice remains External. A stale explicit Internal choice safely resolves External while prerequisites are not ready. |
| Eden source/package | PASS | The catalog links the official `https://eden-emu.dev/downloads/` source and prefers `dev.eden.eden_emulator`. Independent inspection of the official v0.2.1 standard APK confirmed that exact package. |
| Direct external game launch | PASS (host) | Switch uses EmuFusion's non-exported content-URI trampoline and targets Eden's exported `org.yuzu.yuzu_emu.activities.EmulationActivity`. Independent APK inspection confirmed its `ACTION_VIEW` + `content` + `application/octet-stream` filter. No launcher/menu intent is used. |
| Switch title needing an unavailable prerequisite | PASS (host) | Firmware is not made globally mandatory. Only an explicit Eden prerequisite error retires the internal session and invokes the already-selected/default installed direct-game external route. Generic crashes and unsupported-content errors do not trigger it. |
| Held Stop in external emulator | PARTIAL pending device proof | One same-package `AccessibilityService` observes only Select/Media-Stop, only for a one-second hold, and only when the exact package/session launched by EmuFusion owns display 0. Lower-display EmuFusion events cannot affect ownership, transient SystemUI events are ignored, and any other display-0 app disarms it. Window-content retrieval is disabled; no node or view text is read. It issues a bounded natural Back sequence. A display-0 EmuFusion window before fallback proves the external gameplay window naturally yielded; otherwise EmuFusion is brought forward and closure remains unproven. Save remains unproven. A Thor run must prove the physical key and visible return. |

## One-time Android authorization

Android does not allow an app to silently enable its own AccessibilityService.
When the user selects or links an installed external emulator, EmuFusion checks
the service first. If it is disabled, nothing is persisted and Android's own
Accessibility settings opens for one-time authorization. Returning to
EmuFusion and selecting the emulator again completes the link. This is setup,
not an intermediary game-launch menu. Once enabled, selecting a game follows
the same direct launch path as before.

The ROM trampoline also fails closed if the service is disabled, including for
an older already-persisted external route. This prevents the app from silently
launching a standalone emulator while implying that held Stop can return.

## External Stop claims

The implementation deliberately does **not** claim any of the following:

- that the external emulator saved state;
- that the external emulator process terminated;
- that EmuFusion can force-stop the external package;
- that two Back actions are a universal native save API.

It records only the exact launched package/component/session, whether the
bounded natural return was requested, whether a fallback launch was issued,
and whether an EmuFusion window was later observed on display 0. It marks the
external gameplay window naturally closed only when that EmuFusion window is
observed after Back and before any fallback launch. No ROM path, game title,
key name, firmware name, or storage path is stored in that session record.

## Reproducible host evidence

Run:

```sh
python3 -m unittest \
  tools.tests.test_native_adapter_prerequisites \
  tools.tests.test_one_app_apk_verifier -v

cd unified-android && ./test.sh
```

The targeted suite executes the real Java storage/key parser and adversarial
classification cases. The exact-APK verifier now also requires the same-package
AccessibilityService declaration, its binding permission and configuration,
and both implementation classes in DEX. A source-only pass cannot substitute
for those exact-APK checks.

## Required Thor closure

This host audit cannot mark the external held-Stop row fully complete. The next
device run must:

1. install the exact APK that passed `verify_one_app_apk.py`;
2. select External in Settings and prove the one-time OS authorization opens;
3. enable the EmuFusion service and select the emulator again;
4. launch a Switch game from the existing EmuFusion library menu directly into
   Eden gameplay, with no Eden library/menu visible;
5. hold the physical Thor Stop button for at least one second;
6. capture continuous video/input/log evidence showing the existing EmuFusion
   task visible again; and
7. report `saveProven=false`; report `externalClosedProven=true` only if the
   display-0 EmuFusion return was observed before the fallback launch, otherwise
   keep it false.

Until that run passes, direct routing and packaging are host-verified, while
physical held-Stop operability remains honestly unproven.
