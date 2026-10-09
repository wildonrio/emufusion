# NES runtime UX acceptance contract

Status: source-hardened; a new exact-APK AYN Thor run is still required.

## Audio

The software-libretro session drains PCM from the native host on every emulated
frame, independently of whether Android accepted all of the previous write. A
bounded Java FIFO retains partial blocks in order. It never grows into seconds
of latency and never hides overflow: the first unexpected loss emits
`marker=audio-pcm-drop` and each rolling runtime sample reports:

- `audioProducedFrames` — PCM drained from the core;
- `audioWrittenFrames` — PCM accepted by `AudioTrack`;
- `audioDroppedFrames` — unexpected loss because no track/queue exists or the
  bounded FIFO filled;
- `audioFocusDroppedFrames` — intentional discard while another app owns audio;
- `audioQueuedFrames` — accepted PCM still awaiting the sink;
- `audioPartialWrites`, `audioZeroWrites`, and `audioWriteErrors`;
- `audioNativeDrainBoundHits` — the native ring still returned full blocks
  after eight consecutive 4,096-frame drains, so complete accounting cannot be
  claimed even though the remaining quantity is not exposed by the ABI;
- `audioUnderruns` — the `AudioTrack` underrun delta after warm-up, or `-1` only
  where the Android API cannot supply it.

NES audio acceptance requires zero unexpected dropped frames, zero write
errors, zero post-warm-up underrun growth, a bounded queue, and produced versus
written accounting consistent with that queue. These counters make failures
observable; they do not replace listening to or capturing a sustained physical
device run.

### Pre-sink PCM signal contract

`marker=audio-pcm-signal` is emitted beside each rolling runtime sample. Its
`audioSignalBoundary=pre-AudioTrack` and
`audioSignalAudibilityProven=false` fields are normative: this record proves
what the core supplied to Java before focus, buffering, the Android mixer,
amplifier, or speaker. It must never be treated as audible-output proof.

Both the measured window (`audioSignalWindow*`) and the session total
(`audioSignalTotal*`) contain:

- stereo frame and interleaved-sample counts;
- the configured `audioSignalSampleRateHz` and the observation's
  `FrequencyResolutionHz` (`sampleRate / (frames - 1)`);
- an explicit `Overflow` bit; a saturated observation is not qualification
  evidence;
- per-channel `Min`, `Max`, `Peak`, and raw-signal `Rms`;
- per-channel `ToneHz` and `Crossings` from positive-going crossings after a
  one-pole DC blocker and fixed hysteresis. `ToneHz=-1` means the observation
  did not contain enough crossings for an estimate.

The frequency field is deliberately narrow in meaning. It is suitable for the
isolated NES qualification fixture tone (nominally about 440.4 Hz) and remains
valid with a constant DC bias or arbitrary native callback chunk boundaries.
It is not a general pitch detector and must not be interpreted for music or
mixed game audio. Fixture qualification requires a non-silent range/peak/RMS
on both channels and a window tone consistent with the manifest frequency at
the declared sample rate and resolution. That signal gate must still be paired
with the existing AudioTrack written/drop/queue/error/underrun/playback-head
gate and, where the environment permits it, an external audible capture.

## Instant return and Quick Resume

Held Stop still reveals the warm library before serialization. The checkpoint
commits on the retiring session, so saving cannot put a progress screen between
the game and the library. If that background commit fails, EmuFusion posts a
nonblocking application toast in the already-visible library:

> EmuFusion could not save your current position. Your previous Quick Resume is still available.

The same event emits `marker=exit-save-failure-visible`. An acceptance run must
fail if `marker=save-failure` occurs, even though the user was returned safely
and the prior verified checkpoint remains intact.

## Live cheats

Mesen implements `retro_cheat_reset` and `retro_cheat_set`, but libretro defines
the latter as a `void` callback. A normal return proves that the exact callback
ran without a Java/native error; it cannot acknowledge that a code matched the
loaded ROM revision or produced its advertised effect.

Each stored or live operation therefore has a monotonically increasing attempt
identity and emits `marker=cheat-apply-attempt`, followed by either
`marker=cheat-apply-returned` with `acknowledged=false effectProofRequired=true`
or `marker=cheat-apply-failure`. The selection remains visible while the
owner-thread operation runs. A task rejected before native execution is rolled
back because non-application is certain. Other outcomes cannot honestly be
rolled back based on the void ABI alone. Device qualification must observe the
advertised game effect on the exact ROM and observe it cease when disabled.
