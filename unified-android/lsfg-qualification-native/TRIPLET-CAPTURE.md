# Opt-in exact LSFG triplet capture

This diagnostic copies actual fixed LSFG input/output images. It is disabled by
default. With no arm file, there is no capture allocation, writer thread, GPU
copy, pixel readback, or frame-loop filesystem polling. One marker probe happens
during native host setup.

## Arming a future native host

Place a small regular text file at:

`/data/user/0/com.thorium.preview/files/lsfg-triplet-capture.arm`

Syntax (four whitespace-separated unsigned integers):

```text
maxCaptures skipEligiblePairs everyEligiblePairs delaySeconds
```

For example, `4 0 20 45` waits at least 45 monotonic seconds after host setup,
then selects eligible generated pair 1, 21, 41 and 61. This spaces a short burst
across moving gameplay after startup. `skipEligiblePairs` is applied after the
delay. The last three values default to `0 1 0`. Limits are 1–8 captures,
0–100000 skipped pairs, 1–100000 pairs between samples and 0–3600 delay seconds.
The first successfully initialized host consumes the arm file. A new arm file
only affects a newly created host; there is no live filesystem poll.

Selection is based on pair ordinal/time, **not a claim of motion**. JSON records
the sampling policy, selected eligible-pair ordinal and existing tiny-proof
endpoint MAD. Confirm gameplay and motion when reviewing captures. A skipped
busy candidate is counted; it is never silently treated as a successful sample.
The bounded capture budget includes selected captures that are later discarded.

## Output and identity

Output directory:

`/data/user/0/com.thorium.preview/files/lsfg-captures/session-<pid>-<monotonicNs>/`

Each complete generated capture has:

- `capture-N-A.rgba`: exact retained left input.
- `capture-N-G.rgba`: exact LSFG generated output.
- `capture-N-B.rgba`: exact retained right input.
- `capture-N.json`: completion marker and immutable source/session/presentation
  epochs, sequences, timestamps, exact 1/2 phase, physical present ID/time,
  GPU completion, dimensions, stride, pixel format and sampling policy.

These are full-resolution **LSFG endpoint images**, which may be smaller than
the panel when LSFG endpoint scaling is configured. No additional resize or
colorspace conversion happens during capture. Files are tightly packed RGBA8
UNORM, four bytes per pixel; row zero corresponds to Vulkan image coordinate
y=0. No rotation or flip is applied. This is a generated-only triplet exporter;
ordinary Direct screenshots use a separate capture path.

Interpolation phase is mathematically exactly 1/2. Integer content timestamps
use `left + (right-left)/2` with floor integer division; an odd-nanosecond span
therefore stores the lower neighboring nanosecond. JSON records this separately
as `content_timestamp_rounding: floor-nanosecond`; rounding does not change the
interpolation phase. Native preparation, enqueue, capture and decoder share this
contract, and reject the ceil neighbor for an odd span.

## Ownership and performance

One independent host-visible Vulkan staging allocation holds all three images,
with a hard 64 MiB bound (1920×1080 consumes 24,883,200 bytes). It is allocated
only at opted-in setup. Larger geometry is refused explicitly, not downscaled.
Three `vkCmdCopyImageToBuffer` commands execute while the existing proof command
already owns the fixed images. Its existing fence includes those copies and its
unchanged deadline gate still applies. There is no extra fence wait.

Only after that fence signals and the exact physical presentation joins does a
worker invalidate the mapping, if required, and write the files. The renderer
does not read pixels or write image files. The original live slot may retire;
the independent staging allocation cannot be reused while the writer owns it.
Teardown drains Vulkan, joins the writer, then releases the mapping/device.
Disk work is bounded by capture count/bytes; a pathological filesystem can still
delay teardown. There is no filesystem or GPU wait on a presentation deadline.

Debug GPU copies can affect measured timing. Every JSON says `instrumented:true`
and `quality_status:UNVERIFIED`; use an independent capture-disabled run for
production timing. No timing/safety threshold is weakened to obtain a capture.
Setup, busy skips, abandonment, compositor rejection, write failures and final
counts are reported through native diagnostics/logcat. Failed writes also attempt
`capture-N-FAILED.txt`. Raw files without the completed JSON are not valid captures.

## Offline screenshots

After retrieving an entire capture directory, run:

```sh
python3 unified-android/lsfg-qualification-native/decode_triplet_capture.py \
  /absolute/path/capture-1.json --output-dir /absolute/path/capture-1-png
```

The standard-library decoder creates `left.png`, `generated.png`, `right.png`
and a hash manifest. It preserves RGBA bytes, alpha, dimensions and row order;
labels stay in filenames/metadata outside image pixels. It rejects truncated
captures, path escapes, aliased roles and an existing output directory. The
decoder does not certify image quality, and its hashes are not native attestation.

## Local verification

```sh
clang++ -std=c++20 -Wall -Wextra -Werror -pthread \
  -I unified-android/lsfg-qualification-native \
  unified-android/lsfg-qualification-native/triplet_capture.cpp \
  unified-android/lsfg-qualification-native/tests/triplet_capture_test.cpp \
  -o /tmp/emufusion-triplet-capture-host-test
/tmp/emufusion-triplet-capture-host-test
python3 -m unittest discover \
  -s unified-android/lsfg-qualification-native/tests -p 'test_*.py'
```

These tests use synthetic mapped-buffer fixtures, not device proof. Android
native build (configured local tree):

```sh
/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/cmake/3.22.1/bin/cmake \
  --build unified-android/build/lsfg-qualification-native \
  --target lucent_lsfg_qualification -j 4
```

The Android build compiles `triplet_capture.cpp` through CMake and produces
`unified-android/build/lsfg-qualification-native/liblucent_lsfg_qualification.so`.
The normal `unified-android/build.sh` LSFG branch invokes this same CMake target
before APK packaging; use `LUCENT_INCLUDE_LSFG_FRAMEGEN=1` with the existing
verified `LUCENT_LSFG_WRAPPER_DIR`. Do not substitute a stale native library.
