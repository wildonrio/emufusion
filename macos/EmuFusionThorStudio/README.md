# EmuFusion Thor Studio

EmuFusion Thor Studio is a standalone, read-only macOS showcase recorder for an AYN Thor. It does not modify EmuFusion and does not inject input into the handheld.

## What it shows

- A custom SVG illustration of the open Thor viewed straight-on, calibrated to the published 150 × 94 × 25.6 mm enclosure. Its screen openings use the calculated physical sizes of the 6-inch 16:9 and 3.92-inch 1240:1080 panels.
- The Thor's top and lower displays mirrored into the matching screen openings.
- Live A/B/X/Y, D-pad, Play/Start, Stop/Select, Home, Back, and stick-click highlights. The square Stop key highlights immediately as Select and adds the Stop state after the same one-second hold used by EmuFusion.
- Live analog-stick travel.
- L1/L2/R1/R2 badges, including analog trigger travel, positioned where the hidden shoulder controls physically sit.
- Accent-colored light around both sticks. Automatic mode samples the current EmuFusion accent from the top display; a manual color well is available when sampling is not a good match.

## Recording

The Record button encodes the composition directly instead of screen-recording the whole app window. The sidebar and Record button therefore never appear in the output.

- 1920×1080 HEVC video.
- Output cadence follows the top display's active refresh rate (60 or 120 fps on Thor; capped at 120 fps).
- Android system audio is captured as stereo through the top read-only scrcpy feed.
- Optional current Mac microphone narration.
- Voice isolation requests Apple's voice-processing input path. If the selected device does not support it, the finalizer still applies a 90 Hz high-pass, 12.5 kHz low-pass, and speech compressor before mixing narration with Android audio.
- Final MP4 audio is AAC stereo at 256 kb/s.

## Requirements

- macOS 14 or newer.
- ADB access to the Thor.
- `/opt/homebrew/bin/scrcpy` 4.1 or newer.
- `/opt/homebrew/bin/ffmpeg` for microphone mixing.
- Screen Recording permission for EmuFusion Thor Studio.
- Microphone permission only when narration is enabled.

On the first connection, macOS asks for **Screen & System Audio Recording** permission. Approve EmuFusion Thor Studio in System Settings, then quit and reopen the app once. This permission is only used to ingest the two private, offscreen read-only Thor feeds; the app never records unrelated Mac windows or Mac system audio.

The current development device serial is `427c87b2`; change the default in `ADBBridge.swift` when using a different Thor. The production follow-up should add a device picker instead of retaining a development default.

## Build

```sh
chmod +x scripts/build-app.sh
scripts/build-app.sh
open "dist/EmuFusion Thor Studio.app"
```

The build is ad-hoc signed for local use. Distribution outside this Mac requires a Developer ID signature, hardened runtime, notarization, and a bundled or user-selected scrcpy/ffmpeg toolchain.

## Read-only capture design

Two scrcpy processes run with `--no-control`, one for display 0 and one for display 4. They are placed offscreen and captured independently with ScreenCaptureKit. Controller state is observed from `/dev/input/event9` with `getevent`; no events are written. The app does not launch or close anything on Android and never injects taps or keys.

The top scrcpy process duplicates rather than steals Android playback audio. ScreenCaptureKit filters the audio capture to that feed so unrelated Mac system audio is not included.
