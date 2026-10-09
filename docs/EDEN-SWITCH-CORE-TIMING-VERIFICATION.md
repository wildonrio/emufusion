# Eden Switch CoreTiming crash: diagnosis and verification gate

## What is known

The observed failures are a `SIGSEGV` with fault address `0x28` while
`CoreTiming::UnscheduleEvent` is walking/erasing a Boost fibonacci heap, and a
separate stack ending in `fibonacci_heap::consolidate()` from `Advance()`.
Those stacks establish a damaged or invalid heap node. They do **not**, without
the faulting PC and register dump, prove which earlier operation damaged it.

DWARF from the AArch64 `core_timing.cpp.o` before the replacement records this
exact `Event` layout:

| Member | Offset |
|---|---:|
| `time` | `0x00` |
| `fifo_order` | `0x08` |
| `type` (`weak_ptr`) | `0x10` |
| `reschedule_time` | `0x20` |
| `handle` | `0x28` |

Therefore the old source-lock explanation was wrong to call `0x28` the
`weak_ptr` control block. It was the stored Boost node handle. Depending on the
inlined instruction, a fault at `0x28` can mean either an `Event*` base was null
while loading that member or a null Boost node was dereferenced inside an
inlined handle operation. The retained crash material is insufficient to choose
between those two.

The original upstream implementation did retain `const Event& evt` across
`basic_lock.unlock()`, but it also compared `EventType::sequence_number` before
using the reference after a concurrent same-type unschedule. Consequently the
simple claim “Unschedule frees the current node, then Advance always uses it” is
not a complete causal explanation. The sequence guard handles that source-level
path. Compiler motion, an untracked queue mutation, or independent corruption
would require evidence that is not present.

## Replacement invariant

The local implementation now makes the safety property structural rather than
dependent on that reasoning:

1. `Advance()` copies the due event and pops its node while `basic_lock` is held.
2. No queue reference or heap handle exists when the lock is released for the
   callback.
3. A looping event is newly emplaced only after the lock is reacquired and only
   if its sequence number was not changed by `UnscheduleEvent`.
4. `Event` no longer stores a self-referential Boost handle. `UnscheduleEvent`
   obtains the handle from its locked iterator through Boost's public
   `s_handle_from_iterator` API.
5. An expired weak event is still popped, so it cannot spin forever at the top
   of the queue.

This removes the member that occupied `0x28`, eliminates the update-through-a-
retained-node path, and makes it impossible for this implementation to access a
queue node across the unlocked callback window. It is a justified defensive
replacement. It is **not yet a device-proven fix**.

## Host gates

The native Eden test source contains three deterministic regressions:

- a looping callback is held on a condition-variable barrier while another
  thread completes a `NoWait` unschedule, then the test proves it did not rearm;
- 256 queued instances of one event type are all removed through iterator-
  derived handles;
- an expired due event is consumed instead of spinning.

`tools/tests/test_phase3_eden_core_timing.py` additionally enforces the source
invariants, exact source-lock hash, and soak-harness contract.

## Device gate (not run by this change)

`tools/verify_eden_switch_soak.py` is deliberately observation-only. It contains
no launch command or input injection. An operator first opens a known game and
reaches moving gameplay. Each run then requires all of the following:

- the same single `com.thorium.preview` PID for the full run;
- EmuFusion remains the top resumed activity;
- a fresh, positive Eden `averageGameFps` sample in every interval;
- a new screenshot in every interval and finite PSNR below the configured
  near-freeze ceiling;
- every screenshot matches a cropped gameplay feature from a human-approved,
  SHA-256-pinned proof image;
- no crash, package-kill, or install-contention marker.

The formal minimum is 600 seconds. A release claim needs three distinct passed
formal results accepted by `verify-series`. Any failure or invalidated run
resets the consecutive count. Short runs can be requested only with
`--allow-short-smoke` and are permanently marked non-formal.

Example invocation after a device owner has prepared gameplay:

```sh
python3 tools/verify_eden_switch_soak.py observe \
  --adb /absolute/path/to/adb \
  --serial DEVICE_SERIAL \
  --proof-manifest /absolute/path/to/gameplay-proof.json \
  --output /absolute/path/to/evidence
```

The proof manifest is schema version 1 and must contain `gameId`,
`referenceImage`, `referenceSha256`, `crop` (`[x,y,width,height]`),
`minimumSsim`, `approvedBy`, and `approvedAt`.

After three independently prepared runs:

```sh
python3 tools/verify_eden_switch_soak.py verify-series \
  run-1/result.json run-2/result.json run-3/result.json \
  --output three-run-gate.json
```
