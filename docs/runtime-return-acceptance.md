# EmuFusion launch/return acceptance

The host's `latencyMs` log is diagnostic evidence, not proof of a successful
return. Release acceptance is based on the user's visible and interactive
result.

## Required evidence per tested game

1. Launch the game with physical A from the normal EmuFusion menu. Direct intents
   and qualification activities do not count.
2. Preserve a raw logcat trace covering menu selection, gameplay, held Stop,
   restored menu input, and background checkpoint completion.
3. Preserve the original Activity token, task ID, window, and PID across both
   transitions.
4. Record the composed primary display continuously across held Stop. The MP4
   must contain AOSP Winscope v2 per-frame elapsed-realtime timestamps, plus a
   composed frame before the one-second Stop threshold and dense transition
   samples (no gap over 100 ms). Full-resolution ADB screenshots remain useful
   still evidence but are not a latency clock.
5. OCR every captured transition frame. `EmuFusion`, `Pegasus`, `Preparing`,
   `Saving and returning`, branding, or progress UI is an unconditional fail.
6. The exact prior view, system, sort, and game selection must be visible no
   later than 500 ms after the Stop threshold. It must accept a physical menu
   movement immediately; a visually similar but input-blocking splash fails.
7. The background Quick Resume commit must complete without delaying the menu.

## Visible latency clock

The return runner starts a 960x540 `screenrecord` before Stop. Android records
composed display buffers continuously and stores each buffer's presentation
timestamp in the MP4's `#VV1NSC0PET1ME2#` Winscope metadata sample. The gate
parses that binary sample directly, requires exactly one v2 sample, requires a
strictly increasing timestamp for every decoded frame, and rejects missing,
truncated, duplicated, sparse, or count-mismatched evidence.

Stop is injected from one device-side shell. That shell reads `/proc/uptime`,
emits the controller DOWN and SYN events, holds for 1.150 seconds, emits UP and
SYN, and reads `/proc/uptime` again. A concurrent raw `getevent` trace must show
exactly one DOWN and UP, no repeat, and a 1100–1300 ms kernel hold. Both
`/proc/uptime` and Winscope v2 use Android elapsed-realtime. The latency origin
is deliberately the *pre-DOWN* uptime plus one second. The real DOWN is later,
so the measured first-menu latency is an upper bound; shell overhead cannot
turn a slow return into a pass.

Every decoded transition frame is OCR-checked for prohibited branding,
preparing, saving, or progress UI. A restored frame must both resemble the
exact pre-launch menu and contain the actual view label. The reported latency
is rounded upward and must remain at or below 500 ms. The app's internal
`latencyMs` must independently remain at or below 500 ms, but it is corroboration
rather than visible proof.

This method intentionally fails closed on Android builds whose `screenrecord`
does not provide Winscope v2 metadata. It does not fall back to host timestamps,
MP4 playback time, screenshot command start/end times, or interpolation.

## Evidence migration

Evidence made by the older sequential-screenshot runner cannot be upgraded in
place. In particular, the `03cd44` GameCube, Wii, and PS2 directories contain
only sparse PNG captures timestamped by the host before each blocking
`screencap`. They do not contain a continuous MP4, Winscope v2 timestamps, or a
device elapsed-realtime pre-DOWN sample. Their first PNG proves that the menu
was eventually visible and their app log is useful diagnostic evidence, but
neither proves which composed frame first appeared inside the 500 ms budget.
Those exact systems require a new physical run with the video gate.

## Lifecycle rejection

A normal menu game launch must be intercepted inside the already-live
MainActivity's `launchAmCommand` bridge. Pegasus accepts its normal `am start`
metadata syntax, but the exact internal EmuFusion action is attached directly to
the live window before `startActivity` and before any Activity lifecycle can
run. Any `ActivityTaskManager START` for that action is a release failure, even
if the Activity token and PID remain unchanged. On the Thor, starting the
existing `singleTask` Activity can still drive `onPause`/`onResume`; Qt then
recreates its Surface and exposes the startup splash when the gameplay overlay
is removed.

The pinned Android frontend also replaces Pegasus's external-process success
subscriber. It completes API/provider play bookkeeping and launcher cleanup
without deleting the `QQmlApplicationEngine` or stopping the gamepad. The
exact APK verifier rejects a frontend that lacks this byte-locked patch.

An Activity launch followed by `performResumeActivity` or a new
`QtActivityDelegate.createSurface` during a menu game transition is additional
proof of this failure mode.

Run the offline evidence gate with:

```sh
python3 unified-android/tools/verify_runtime_return_evidence.py \
  unified-android/build/runtime-acceptance-<candidate>
```

The verifier fails closed when raw lifecycle logs are absent, and it ignores a
nominal `PASS` in `results.json` if stored OCR or screenshots show a reset.
