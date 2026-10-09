# Frame-generation checkpoint: coordination resolved; goal still incomplete

## Resolution, approximately 21:57 September 4

The owner asked to check again. The other Claude EMUFUSION task was inspected
through its visible UI: it explicitly acknowledges the owner's **Stop all tasks**
instruction and repeatedly says it is paused until the owner resumes it. Its
background cards are stopped/completed. Two independent host snapshots found no
active build, install or recent source editing. The remaining orphaned ADB log/input
readers alone do not establish an active writer. No other agent/process was killed
or resumed by this task. Shared source/build work can now continue.

Both Thor displays were verified Asleep/OFF; charging stay-awake was disabled.
The following blocked-state sections are historical records, not a current blocker.
The full goal remains active and incomplete. The other agent's older six-system
claims have a [separate artifact audit](qa/other-agent-six-system-claims-2026-09-04.md)
and do not transfer to the current at-most-2x, guest-clock and exact-capture contract.

The isolated admission-expiry correction has now been integrated into the shared
native/JNI source, with the matching Java preflight correction. Ordinary expiry
before ownership becomes NOT_READY; malformed contracts remain errors. Accepted
GPU work retains its identity until the existing cutoff-drop retirement completes.
A sanitizer test additionally found signed overflow at an impossible adjacent JNI
sequence; both native preparation/enqueue validation sites now reject INT64_MAX
before calculating its successor. Actual extracted-method/JNI tests pass all 23
scenarios after that guard. These are host tests, not hardware qualification.

The first new APK c22646 was installed and hash-verified, but the diagnostic launch
defaulted to display 4, where LSFG is intentionally unavailable. Its Direct fallback
and lower-panel title are **excluded from LSFG testing**, not a successful test of
the correction. The timed watchdog slept both panels after 180 seconds. The mode
was restored to built-in-alpha and the paused test was force-stopped; normal exit
was not verified. The JNI overflow guard was not in c22646. The subsequent build
and explicitly top-display retest must be recorded separately.

The explicit top-display follow-ups are now preserved separately:
[a4f1](qa/frame-generation-v2-switch-a4f1-2026-09-04/README.md) failed endpoint
identity validation (1,297 presents/0 generated) and native shutdown hung;
[611be](qa/frame-generation-v2-switch-611be-2026-09-04/README.md) includes the
subsequent exact carrier-gap/timing-contract corrections and failed a missing
SurfaceControl present fence (4,951 presents/0 generated). It did not exercise
carrier recovery and ended with an input-focus ANR during attempted Back/sleep.
All 42 focused host tests and the full Java suite passed for 611be; no system
qualified. The existing built-in-alpha setting was restored, the restarted
service was force-stopped, and both OLED panels verified Asleep/OFF/brightness 0.
The separate worker remains paused; the historical coordination blocker is resolved.

## Historical blocked checkpoint — approximately 21:22 America/Denver

The [goal](FRAME-GENERATION-GOAL-2026-09-04.md) remains **incomplete** and is now
**blocked pending shared-repository/device control coordination**.
No console system is qualified under that contract. Source changes and device
installs by this Codex task are paused pending owner clarification about another
worker using the shared repository and Thor. This is not a request to kill,
interrupt, revert, or overwrite the other worker's work.

## Why coordination is needed

- This task last installed and tested private APK `7c739d29227c1a8e97566bee8547cd7622406a370f79323b44114c505c623a86`.
- A separate APK appeared at approximately 21:07, with independently checked
  SHA-256 `b8e065e4fb8faffc94d4e15894858652001ab8866c8ebcca8f1f78a8fc80c1e3`.
  This task and its three agents did not build it. Its purpose/source delta and
  installed-file hash have not been established; do not attribute it to this task.
- EmuFusion restarted as device PID 20134 after this task had force-stopped its
  PID 14164 test. Separate host ADB clients began `getevent` for the controller
  and `logcat --pid 20134` using the Cemu SDK ADB binary, not this task's ADB path.
- Package `lastUpdateTime` now reports `2026-09-04 20:05:37` on the device,
  after this task's install. Device log wall time differs from Mac wall time;
  use immutable hashes and monotonic identities, not version 3.2.16/code 90.

The other worker has not been contacted or interrupted. The owner was asked
whether another AI/person is using the Thor. Do not resume builds against shared
output directories or device tests until the ownership overlap is resolved.

## Last empirical result

[7c739 evidence](qa/frame-generation-v2-switch-7c739-2026-09-04/README.md)
preserves the full scoped log, title screenshot, source snapshot and reproducible
timing analysis. It **failed**: 1,280 presentation-counter events, zero generated
presents, uneven three/five-scan holds, and a pre-submit cutoff failure. The
first 32 raw present rows had no additive timestamp offset and were close to
their requested scan times; that does not qualify their uneven spacing.

## Preserved follow-up source, not device-qualified

- `GameSurfaceView` and `GameSurface` now keep a delivered runtime failure
  terminal for that game view across Android surface recreation. Explicit game
  reopen creates a new view. Sleep/wake must not initialize another LSFG host
  behind a still-paused failed game.
- `DisplayFrameGenerator.reportStats` uses elapsed diagnostic windows; changing
  target millihertz no longer erases the window and suppresses health rows.
  Physical/epoch qualification remains separate from app-swap averages.
- [Pre-submit cutoff retirement](qa/lsfg-pre-submit-cutoff-retirement-2026-09-04.md)
  retains the exact request and GPU fences, emits a dropped original-ID row only
  after safe retirement, orders it against older physical requests and bounds
  unresolved drain at one second. Deadlines are not extended. This native/JNI
  patch is host-tested but has not been rebuilt into an APK by this task.
- `NativeSourceImage` sealed snapshot transfers and `NativeSourceImageLedger`
  retain raw timestamps/provider epochs/status/original queue identity with
  bounded setup-allocated storage and stale-lease protection. This foundation
  is **not wired to the renderer** and grants no generation/guest-clock authority.
  See the [remaining integration plan](EDEN-CONSUMED-IMAGE-AND-GUEST-CLOCK-PLAN-2026-09-04.md).

The native **admission** deadline race remains unfixed: `validateLiveRequest`
still throws for expiry, `activatePrivatePrepared` is still void, and JNI still
resets `preparedGenerated` after successful activation. No partial admission fix
was applied. Next correction should preserve structural validation failures but
return NOT_READY for ordinary pre-admission expiry without consuming a slot,
private output, identity or generation credit. It must not change any deadline.

## Verification completed before the pause

- 28 integrated cutoff/raw-timing/endpoint/lifecycle/packaging/runtime/health
  regressions passed: `/tmp/emufusion-v2-cutoff-integrated-root-tests.log`.
- 16 source-image ledger/parser/native join/clock tests passed independently:
  `/tmp/emufusion-v2-source-ledger-root-review-tests.log`.
- Full Java host suite passed:
  `/tmp/emufusion-v2-retention-foundation-full-host-tests.log`.
- All Android Java, including legacy hosts and LSFG/RIFE qualification sources,
  compiled against Android 36:
  `/tmp/emufusion-v2-retention-foundation-android-javac.log`.
- View-failure and health-window changes received independent read-only review.
  Cutoff-retirement independent review completed on the following read-only
  continuation and found no new actionable blocker; the separately known
  admission-deadline race remains unresolved.

These are code tests, not a native build, guest-speed proof, pixel-quality result,
or system acceptance. Preserve existing dirty changes; do not reset the checkout.

## Device safety and settings

This task restored the prior `built-in-alpha` preference after its LSFG test and
removed its own TCP 19800 ADB forward. Subsequent changes by another worker are
unknown. Factory/default Off behavior was not changed.

At approximately 21:17, the device's `stay_on_while_plugged_in` setting was found
to be `7`; this task changed it to `0` to allow sleep while charging. The previous
value is recorded here for traceability, not as a recommendation to restore it.
At **03:21:39 UTC / 21:21:39 Denver**, read-only checks showed `mWakefulness=Asleep`,
`mStayOn=false`, and **both displays OFF with actual brightness 0**. No further
device input/install commands should run here until control is coordinated.

## Isolated native build, 21:27 continuation

The current native source and verified wrapper were copied into
`/tmp/emufusion-cutoff-native-review.XGXudF/`. No shared build directory was used.
The copied native source compared byte-for-byte equal with the repository before
and after compilation. The pinned wrapper, nonblocking sync-FD and owned-WSI
source checks passed. Android arm64/API 29 Release compilation with NDK
27.0.12077973 and CMake 3.22.1 completed all 41 build steps successfully.

- Native source archive: `native-source.tgz`, SHA-256
  `c206ad021951ccad15e0616815b9131a859cf893e90075182a9c166687fc8924`.
- Output: `build/liblucent_lsfg_qualification.so`, SHA-256
  `5ac80e0cc685fde50523a9ed95a89d3a8c5af53672d07866d0439d035fca004a`;
  AArch64 ELF64, build ID `d00ff27b4b45433b03f7e28bbd9f42610398b4df`,
  all LOAD segments aligned to 16 KiB.
- `build.log` SHA-256
  `9c6cf06bb78514be5983b1411314b7458c9ef5106047a56a76035bdf3f220882`.
- `configure.log` SHA-256
  `5369d3ec259841a3c3619288958e9b36ded63bc0e35c105f9fc34a5068acdda1`.

This is a compile/link result, not an installed APK or runtime test. No source,
APK, or device-input changes were made by that continuation. Both panels were
again verified asleep/OFF/brightness 0 by read-only inspection. The separately
started ADB controller-input/logging processes 53844 and 53853 were still live at
03:26:54 UTC. Their presence does not by itself establish who is controlling the
device or whether they are presently modifying code; the independent build and
app restart still require owner coordination before testing resumes.

## Third coordination check, 21:30

The prior continuation made concrete progress by compiling the native correction
in isolation and completing independent review. On the third consecutive goal
turn encountering this same coordination blocker, the separate device processes
53844 and 53853 were confirmed live again and the independently produced b8e APK
remained the newest shared build. The repository native source still matched the
isolated compile snapshot; no further changes/builds were attempted here.

At **03:29:47 UTC**, a read-only power check showed the Thor **Awake**, both
displays **ON** with reported brightness 0, and `mStayOn=true` again. This differs
from the earlier verified Asleep/OFF state and disabled stay-awake setting. Do not
claim the device remained asleep, or that brightness 0 proves black pixel content.
No new input or setting writes were issued here because another controller may
be actively testing. Exclusive device control must be established before this
task can safely enforce OLED cleanup or run attributable tests.

The goal is blocked, not achieved. All fixes/evidence remain preserved; the
admission race, useful generated-frame captures, complete physical/guest/audio
proof, and every system's acceptance remain unfinished. Resume after the owner
confirms which worker controls the shared source/build directories and Thor.
