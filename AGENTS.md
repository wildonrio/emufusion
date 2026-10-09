# EmuFusion project instructions

Preserve the current dirty worktree, including other agents' changes. Read the
current status at the top of docs/FRAME-GENERATION-GOAL-2026-09-04.md before any
device mutation. The owner lifted the restriction on inspecting, editing and
building engines/build/switch-src/eden on October 4, 2026 for the internal-launch
portability work. Preserve existing edits there as elsewhere in this worktree.

## Critical Thor deployment constraint

**Never use implicit/default or explicit incremental APK installation.** On this
Thor, `adb install -r` selected incremental delivery, reported Success, then the
data loader failed and Android fully removed the app. This happened September 9
and September 11 and puts private saves/settings at risk.

Use an existing verified installer, or explicitly `install --no-incremental -r`.
Review unified-android/tools/run_runtime_acceptance_qa.py:exact_install and
tools/tests/test_qa_streamed_install.py. Verify the existing installed identity
before replacement, then the installed package path, exact APK hash, UID and
first-install time afterward. An installer success message is insufficient.
If the package disappears or its identity resets, STOP: preserve diagnostic
evidence and available backups, report the data risk, and obtain recovery
direction. Do not automatically reinstall a missing package or claim data was
preserved. Do not uninstall, clear app data or overwrite saves to run tests.

## OLED and acceptance

Keep both Thor panels OFF during host-side work. Use the existing host/device
OLED deadline guards for bounded testing and verify both physical panels OFF,
actual brightness 0/0, no game process and restored idle timeout afterward.
An installed candidate or passing host tests is not a device acceptance pass.

## Build disk budget

The owner requested ongoing cleanup of obsolete builds on October 6. Do not
accumulate APKs or temporary unsigned/aligned packaging copies after a trial.
`unified-android/build.sh` prunes superseded hash-named APKs automatically and
removes its unsigned/aligned intermediates after successful verification.
It also removes those reproducible intermediates on failure or handled signals.
After successful verification it also removes the decoded APK workspace and
Java/dex assembly scratch; these are always regenerated, not incremental caches.
Retention keeps two newest APKs per flavor plus a one-day grace period and all
explicit pins; do not expand retention or accumulate extra rollback copies
without a concrete active need.
Retention runs both before assembly and after verified publication, so newly
superseded packages do not wait for another build to be pruned.
The same build hook also retires explicitly named diagnostic APKs older than
14 days in build/test folders, docs/qa and engines/build/candidates. Hash pins,
open-file and tracked-file checks still apply; source, evidence and symbols stay.
Before deploying a new baseline, pin its SHA-256 with a reason in
`unified-android/build-retention.json`; retain required current/rollback APKs.
After a diagnostic trial closes and its installed baseline is restored, retire
its obsolete APK immediately: remove its stale pin and record its exact relative
path, SHA-256 and reason in `retired_diagnostic_apks` in that same policy. The
build hook then removes that verified APK and its signing sidecar without the
14-day delay. Keep recipes, native outputs, symbols and evidence; pins override
retirement, and open files, changed hashes, symlinks and tracked files are refused.
Exact-path retirement also accepts custom APK names such as `flow-export.apk`;
do not omit a completed trial just because its filename lacks `emufusion-`.
Custom names are never selected by age alone: record their path/hash/reason.
The owner reiterated this on October 7: apply immediate retirement to completed
trials for every system, not only PS3. Run the cleanup when closing the trial,
not just before the next build; do not leave obsolete test APKs for 14 days.
This includes rejected packages and superseded resource-only packaging inputs:
retain their small failure/build receipts, not unusable full APK copies. Record
their exact path/hash retirement as soon as the replacement is verified.
The same diagnostic cleanup removes orphaned generated APK signing sidecars
after one day, only when the corresponding APK is absent; pins, open files,
symlinks and tracked files remain protected.
For isolated diagnostic builders, remove their reproducible packaging
intermediates when finished, retaining logs, receipts and source/patches.
Never clean ROMs, saves, signing keys, source changes, active work, or required
native symbols. Check disk space before large builds and report space reclaimed.
Retired September PS3 static intermediates can be losslessly archived with
`unified-android/tools/archive_retired_ps3_intermediates.py --apply` (dry-run by
default). It excludes the active normal link inputs, verifies decompressed hashes
before deleting originals, and records recovery receipts. If an old diagnostic
needs its archived `.a` again, use `gzip -dk` on that exact `.a.gz`; do not keep an
expanded copy after the diagnostic finishes. Shared libraries and symbols remain.
For the closed October 4 Switch load/start-failure/handheld diagnostic link outputs, use
`--completed-switch-archives`. Only five explicitly allowlisted static/symbol
files are archived, with verified decompressed hashes and recovery receipts.
The runnable libraries, source, evidence and live configured build stay put.
Restore an exact archived input with `gzip -dk FILE.gz` only if needed for a
historical rebuild or symbol lookup, then remove that temporary expanded copy.
For retired September diagnostic symbol files, add `--retired-symbols` to that
archive command. This keeps every symbol recoverable in a verified `.gz` while
removing the expanded copy; runnable libraries and the active normal baseline
stay in place. Restore the exact file with `gzip -dk FILE.gz` only when needed.
The optional `--retired-switch` flag applies the same verified, lossless archival
to seven explicitly allowlisted September 9 Switch diagnostic builds. It does
not select the live Switch build tree, October portability inputs, multiplayer
rollback, source, runnable libraries or any other candidate folders.
The optional `--completed-ps2-archives` flag archives only static `.a` link
intermediates in the same three completed October 5 PS2 compiler output trees
used by `cleanup_completed_ps2_objects_20261006.py`. Final packaged cores,
unstripped libraries, source and build receipts are untouched. Recovery uses
the exact `.a.gz` and its recorded decompressed SHA-256, as above.
For the same three closed PS2 trials, `--completed-ps2-symbols` losslessly
archives only `out/pcsx2-libretro/armsx2_libretro.so`, retaining the separate
runnable `arm64-v8a` cores. Debug symbols remain recoverable with `gzip -dk`
on the exact `.so.gz`; decompressed hashes are checked before expanded copies
are removed. This does not select active compiler trees or any source files.
`compact_retired_build_outputs.py` safely compacts explicitly scoped old runtime
logcat files and the September 9 log-access diagnostic's decoded library copies.
Logs remain SHA-verified `.txt.gz` files; recover with `gzip -dk FILE.txt.gz`.
Keep that diagnostic's `manifest-build.apk` (SHA-256 starting `9998e201`): it is
the verified compressed recovery copy for those removed decoded libraries.
Exact original paths, ZIP member names and hashes are in retention receipts.
This maintenance never selects screenshots, ROMs, saves, source or native symbols.
The optional `--ocr-caches` flag removes only old generated `.ocr-boost.png`
aids with an intact original screenshot, retaining original hashes and recovery
instructions in the receipt. Original screenshots are never removed. The runtime
QA OCR helper now sends its derived PNG through stdin instead of writing these
caches; preserve this no-scratch behavior in future test changes.
The compaction tool's `--closed-traces` option losslessly compresses six exact
September 16 captures only after verifying their closed-watchdog markers. Recover
an exact trace with `gzip -dk FILE.atrace.gz`; receipts retain original hashes.
Use `archive_retired_ps3_intermediates.py --completed-cemu-symbols --apply` for
the four explicitly retired October 4–7 Cemu `linked-before.so` copies. These
historical debug copies are kept as hash-verified `.so.gz`; current configured
outputs, runnable libraries and source are untouched. Restore an exact copy with
`gzip -dk FILE.so.gz` only when needed, then retire the expanded copy afterward.
Run cleanup at each completed trial, and report actual space recovered rather
than accumulating outputs until the disk is nearly full.
`cleanup_retired_rife_objects.py --apply` removes only pre-October RIFE benchmark
`.cxx` compiler objects whose unstripped linked library is retained. It preserves
the newest configuration per build type, static archives, source, recipes and
all debug libraries; rejects open/tracked/aliased inputs; and verifies retained
hashes. Removed objects can be rebuilt using the benchmark's Gradle/CMake recipe.
Use its dry-run first. This does not remove the active emulator build caches.
Its optional `--static-archives` mode losslessly compresses static `.a` link
inputs from those same retired benchmark configurations. The newest cache per
variant, linked debug libraries, source and recipes remain. Use the dry-run first;
recovery is `gzip -dk` on the exact `.a.gz`, with original hashes in the receipt.
