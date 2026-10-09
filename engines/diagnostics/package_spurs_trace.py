#!/usr/bin/env python3
"""Repackage a pinned local diagnostic without touching production staging."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SDK = Path('/Users/tyleryoung/Library/Android/sdk')
BASE_SHA = '02d71f0930fcff2ccab27201fe7dbe214f83bd9e5e3416994e8e61438a0c5adc'
SO = 'lib/arm64-v8a/liblucent_native_adapter_aps3e.so'
LOCK = 'assets/phase3-aps3e-source-lock.json'
INDEX = 'assets/phase3-engine-artifacts.json'
NOTE = 'assets/local-spurs-trace-diagnostic.json'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def signature(name):
    return name.startswith('META-INF/') and (name.endswith(('.RSA', '.SF', '.DSA', '.EC')) or name == 'META-INF/MANIFEST.MF')

def trace_profile(mfc_progress=False, spurs_workload=False, retirement_only=False,
                  adapter_input_only=False, getllar_read_barrier=False,
                  combined_flip_retirement=False, restore_diagnostic=False):
    if combined_flip_retirement and not (adapter_input_only and getllar_read_barrier):
        raise ValueError('combined flip retirement requires retained input and read-barrier corrections')
    if getllar_read_barrier and not adapter_input_only:
        raise ValueError('combined read-barrier profile requires adapter input candidate')
    if adapter_input_only:
        if (mfc_progress and not restore_diagnostic) or spurs_workload or retirement_only:
            raise ValueError('input-only candidate cannot include other candidate profiles')
        return {'targetAddress': None,
                'traceScope': ('no added tracing; adapter stick-direction release correction'
                               + ('; GETLLAR payload-before-stamp read barrier'
                                  if getllar_read_barrier else '')
                               + ('; acquire-loss flip-retirement correction'
                                  if combined_flip_retirement else '')),
                'sourcePatch': 'engines/patches/aps3e-lucent-adapter.cpp',
                'helper': None}
    if retirement_only:
        if mfc_progress or spurs_workload:
            raise ValueError('retirement-only candidate cannot include CPU sampling')
        return {'targetAddress': None,
                'traceScope': 'no added tracing; isolated acquire-loss flip-retirement candidate',
                'sourcePatch': 'engines/diagnostics/prepare_flip_retirement.py',
                'helper': None}
    if spurs_workload:
        return {'targetAddress': None,
                'traceScope': 'bounded MFC progress with owner-local SPURS context and existing reservation-buffer snapshots',
                'sourcePatch': 'engines/diagnostics/prepare_spurs_workload_trace.py',
                'helper': 'engines/diagnostics/lucent_spurs_workload_snapshot.h'}
    if mfc_progress:
        return {'targetAddress': None,
                'traceScope': 'generic GETLLAR/PUTLLC owner-thread progress; no guest-memory payload',
                'sourcePatch': 'engines/diagnostics/prepare_mfc_progress_trace.py',
                'helper': 'engines/diagnostics/lucent_mfc_progress_trace.h'}
    return {'targetAddress': '0x31ee7680',
            'traceScope': 'historical SPURS taskset diagnostic',
            'sourcePatch': 'docs/qa/ps3-spurs-journal-2026-09-08/SPUThread.trace.patch',
            'helper': 'engines/diagnostics/lucent_spurs_taskset_trace.h'}

def select_base(base_path=None, base_sha256=None):
    """Allow a reviewed current APK without silently falling back to an old app."""
    if (base_path is None) != (base_sha256 is None):
        raise ValueError('base APK and SHA256 must be supplied together')
    if base_path is None:
        base_sha256 = BASE_SHA
        base_path = ROOT / ('unified-android/build/lucent-3.2.16-phase2-phase3-qualification-' + BASE_SHA + '.apk')
    if not re.fullmatch(r'[0-9a-f]{64}', base_sha256):
        raise ValueError('base SHA256 must be 64 lowercase hexadecimal characters')
    base = Path(base_path).resolve()
    base.relative_to(ROOT)
    if digest(base.read_bytes()) != base_sha256:
        raise ValueError('base APK hash mismatch')
    return base, base_sha256

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--trace-sha256', required=True)
    parser.add_argument('--trace-library', type=Path, required=True,
                        help='Exact isolated library to package; production staging is not changed')
    parser.add_argument('--base-apk', type=Path,
                        help='Explicit current base APK; requires --base-sha256')
    parser.add_argument('--base-sha256',
                        help='Expected hash of --base-apk; both options must be supplied')
    parser.add_argument('--extra-source-patch', type=Path, action='append', default=[],
                        help='Additional applied source patch to record in diagnostic provenance')
    parser.add_argument('--without-trace', action='store_true',
                        help='Record that the candidate was compiled with SPURS trace hooks disabled')
    parser.add_argument('--wsi-trace', action='store_true',
                        help='Record diagnostic logging in the isolated VKPresent translation unit')
    parser.add_argument('--core-error-trace', action='store_true',
                        help='Record mirroring existing core fatal/error messages to Android logcat')
    parser.add_argument('--mfc-progress-trace', action='store_true',
                        help='Record bounded generic MFC owner-thread sampling; requires --without-trace')
    parser.add_argument('--spurs-workload-trace', action='store_true',
                        help='Record owner-local SPURS snapshots; requires --mfc-progress-trace')
    parser.add_argument('--ppu-wait-trace', action='store_true',
                        help='Record bounded owner PPU usleep registers and executable caller windows')
    parser.add_argument('--retirement-only', action='store_true',
                        help='Record only the flip-retirement candidate; requires --without-trace and no tracing flags')
    parser.add_argument('--render-progress-trace', action='store_true',
                        help='Rate-limited render-boundary candidate; no CPU or verbose WSI tracing')
    parser.add_argument('--adapter-input-only', action='store_true',
                        help='Unqualified stick-release candidate without added tracing or flip-retirement changes')
    parser.add_argument('--getllar-read-barrier', action='store_true',
                        help='Combine input candidate with the trace-free GETLLAR read-ordering correction')
    parser.add_argument('--combined-flip-retirement', action='store_true',
                        help='Add acquire-loss retirement to the retained input/read-barrier composition')
    parser.add_argument('--native-stop-probe', type=Path,
                        help='Exact generated QA-namespace-only adapter source; no normal teardown opt-in')
    parser.add_argument('--zcull-teardown', action='store_true',
                        help='Record the isolated Vulkan borrowed-self-pointer teardown correction')
    parser.add_argument('--wrapper-sync-lifetime', action='store_true',
                        help='Record process-lifetime aPS3e request mutexes and atomic status')
    parser.add_argument('--state-capture-probe', type=Path,
                        help='Exact generated fresh-state correction with QA-only capture trigger')
    parser.add_argument('--render-capture-probe', type=Path,
                        help='Exact generated QA L+R capture on the live render owner before Exit')
    parser.add_argument('--state-restore-probe', type=Path,
                        help='Exact generated preserved-Shadow-state QA restore callback probe')
    parser.add_argument('--restore-phase-probe', type=Path,
                        help='QA-only restore phase markers, with --core-error-trace required')
    parser.add_argument('--restore-attempt', default='phase2',
                        help='Unique QA restore destination component for a new hypothesis')
    parser.add_argument('--restore-atomic-storage', action='store_true',
                        help='Record corrected savestate callbacks storing into actual atomic ID-map slots')
    args = parser.parse_args()
    if (args.restore_attempt != 'phase2' or args.restore_atomic_storage) and args.restore_phase_probe is None:
        parser.error('restore attempt/storage correction requires the scoped restore phase probe')
    if args.restore_phase_probe is not None:
        if any((args.state_restore_probe, args.render_capture_probe, args.state_capture_probe, args.native_stop_probe)) or not args.wrapper_sync_lifetime or not args.combined_flip_retirement or not args.without_trace or not args.core_error_trace:
            parser.error('restore phase requires retained wrapper/composition and core-error mirror without other probes')
        from prepare_restore_phase_probe import prepare
        if args.restore_phase_probe.read_bytes() != prepare((ROOT/'engines/patches/aps3e-lucent-adapter.cpp').read_bytes(), args.restore_attempt).encode():
            parser.error('restore phase source differs from the pinned generator')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_fresh_savestate.py',
                                   ROOT/'engines/diagnostics/prepare_render_capture_probe.py',
                                   ROOT/'engines/diagnostics/prepare_state_restore_probe.py',
                                   ROOT/'engines/diagnostics/prepare_restore_phase_probe.py',
                                   ROOT/'engines/diagnostics/prepare_core_error_trace.py', args.restore_phase_probe]
        if args.restore_atomic_storage:
            args.extra_source_patch += [ROOT/'engines/patches/aps3e-savestate-atomic-storage.patch']
    if args.state_restore_probe is not None:
        if args.render_capture_probe is not None or args.state_capture_probe is not None or args.native_stop_probe is not None or not args.wrapper_sync_lifetime or not args.combined_flip_retirement or not args.without_trace:
            parser.error('state restore requires wrapper/retained composition without other probes or tracing')
        from prepare_state_restore_probe import prepare
        if args.state_restore_probe.read_bytes() != prepare((ROOT/'engines/patches/aps3e-lucent-adapter.cpp').read_bytes()).encode():
            parser.error('state restore source differs from the pinned scoped generator')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_fresh_savestate.py',
                                   ROOT/'engines/diagnostics/prepare_render_capture_probe.py',
                                   ROOT/'engines/diagnostics/prepare_state_restore_probe.py', args.state_restore_probe]
    if args.render_capture_probe is not None:
        if args.state_capture_probe is not None or args.native_stop_probe is not None or not args.wrapper_sync_lifetime or not args.combined_flip_retirement or not args.without_trace:
            parser.error('render capture requires wrapper/retained composition without other probes or tracing')
        from prepare_render_capture_probe import prepare
        if args.render_capture_probe.read_bytes() != prepare((ROOT/'engines/patches/aps3e-lucent-adapter.cpp').read_bytes()).encode():
            parser.error('render capture source differs from the pinned scoped generator')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_fresh_savestate.py',
                                   ROOT/'engines/diagnostics/prepare_render_capture_probe.py', args.render_capture_probe]
    if args.state_capture_probe is not None:
        if args.native_stop_probe is not None or not args.wrapper_sync_lifetime or not args.combined_flip_retirement or not args.without_trace:
            parser.error('state capture requires wrapper/retained composition without tracing or native-stop probe')
        from prepare_state_capture_probe import prepare
        if args.state_capture_probe.read_bytes() != prepare((ROOT/'engines/patches/aps3e-lucent-adapter.cpp').read_bytes()).encode():
            parser.error('state capture source differs from the pinned scoped generator')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_fresh_savestate.py',
                                   ROOT/'engines/diagnostics/prepare_state_capture_probe.py', args.state_capture_probe]
    if args.native_stop_probe is not None:
        if not args.combined_flip_retirement or not args.without_trace:
            parser.error('native stop probe requires retained composition without tracing')
        from prepare_native_stop_probe import prepare
        if args.native_stop_probe.read_bytes() != prepare((ROOT/'engines/patches/aps3e-lucent-adapter.cpp').read_bytes()).encode():
            parser.error('native stop probe source differs from the pinned scoped generator')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_native_stop_probe.py', args.native_stop_probe]
    if args.zcull_teardown:
        if not args.combined_flip_retirement or not args.without_trace:
            parser.error('ZCULL teardown requires retained composition without tracing')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_zcull_teardown.py']
    if args.wrapper_sync_lifetime:
        if not args.combined_flip_retirement or not args.without_trace:
            parser.error('wrapper lifetime requires retained composition without tracing')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_wrapper_sync_lifetime.py',
                                   ROOT/'engines/patches/aps3e-wrapper-sync-lifetime.patch']
    if args.combined_flip_retirement and not (args.adapter_input_only and args.getllar_read_barrier):
        parser.error('combined flip retirement requires --adapter-input-only and --getllar-read-barrier')
    if args.getllar_read_barrier and not args.adapter_input_only:
        parser.error('read-barrier composition requires --adapter-input-only')
    if args.adapter_input_only and (not args.without_trace or args.wsi_trace
            or ((args.core_error_trace or args.mfc_progress_trace or args.ppu_wait_trace) and args.restore_phase_probe is None)
            or args.spurs_workload_trace or args.render_progress_trace or args.retirement_only):
        parser.error('input-only requires --without-trace and no other candidate flags')
    if args.retirement_only and (not args.without_trace or args.wsi_trace
            or args.core_error_trace or args.mfc_progress_trace
            or args.spurs_workload_trace or args.ppu_wait_trace or args.render_progress_trace):
        parser.error('retirement-only requires --without-trace and no tracing flags')
    if args.render_progress_trace and (not args.without_trace or args.wsi_trace
            or args.core_error_trace or args.mfc_progress_trace
            or args.spurs_workload_trace or args.ppu_wait_trace):
        parser.error('render-progress requires --without-trace and no other tracing flags')
    if args.mfc_progress_trace and not args.without_trace:
        parser.error('generic MFC candidate requires --without-trace for historical SPURS hooks')
    if args.spurs_workload_trace and not args.mfc_progress_trace:
        parser.error('SPURS workload candidate requires --mfc-progress-trace')
    profile = trace_profile(args.mfc_progress_trace, args.spurs_workload_trace,
                            args.retirement_only, args.adapter_input_only,
                            args.getllar_read_barrier, args.combined_flip_retirement,
                            restore_diagnostic=args.restore_phase_probe is not None)
    if args.native_stop_probe is not None:
        profile = dict(profile, traceScope=profile['traceScope'] + '; native shutdown probe restricted to existing PS3 QA namespace')
    if args.state_capture_probe is not None:
        profile = dict(profile, traceScope=profile['traceScope'] + '; exact fresh-state capture/restore-file correction with existing QA-namespace-only capture trigger')
    if args.render_capture_probe is not None:
        profile = dict(profile, traceScope=profile['traceScope'] + '; exact fresh-state correction with QA-only render-owner capture before Exit')
    if args.state_restore_probe is not None:
        profile = dict(profile, traceScope=profile['traceScope'] + '; preserved Shadow QA state through actual adapter restore on render owner')
    if args.restore_phase_probe is not None:
        profile = dict(profile, traceScope=profile['traceScope'].replace('no added tracing; ', '', 1) + '; QA-only restore phase markers and existing fatal/error mirror; not a performance build')
    if args.restore_atomic_storage:
        profile = dict(profile, traceScope=profile['traceScope'] + '; savestate callbacks retain atomic ID-map pointer encoding and ownership')
    if args.restore_phase_probe is not None and args.mfc_progress_trace:
        profile = dict(profile, traceScope=profile['traceScope'] + '; bounded owner-local MFC command tracing during restore; not performance-qualified')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_mfc_progress_trace.py',
                                   ROOT/'engines/diagnostics/lucent_mfc_progress_trace.h']
    if args.zcull_teardown:
        profile = dict(profile, traceScope=profile['traceScope'] + '; Vulkan ZCULL borrowed-self-pointer teardown correction')
    if args.wrapper_sync_lifetime:
        profile = dict(profile, traceScope=profile['traceScope'] + '; process-lifetime wrapper synchronization and atomic status')
    if args.getllar_read_barrier:
        args.extra_source_patch += [ROOT/'engines/patches/aps3e-getllar-read-barrier-build.patch']
    if args.combined_flip_retirement:
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_flip_retirement.py']
    if args.render_progress_trace:
        profile = {'targetAddress': None,
                   'traceScope': 'rate-limited render call boundaries; no guest memory or image readback',
                   'sourcePatch': 'engines/diagnostics/prepare_render_progress.py',
                   'helper': 'engines/diagnostics/lucent_render_progress.h'}
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_flip_retirement.py']
    if args.ppu_wait_trace:
        profile = dict(profile, traceScope=profile['traceScope'] + '; bounded PPU usleep caller snapshots')
        args.extra_source_patch += [ROOT/'engines/diagnostics/prepare_ppu_usleep_trace.py',
                                   ROOT/'engines/diagnostics/lucent_ppu_wait_trace.h']
    out = args.output_dir.resolve()
    if out.exists():
        parser.error('output directory exists; refuse overwrite')
    base, base_sha256 = select_base(args.base_apk, args.base_sha256)
    trace = args.trace_library.resolve()
    trace.relative_to(ROOT)  # Embedded provenance uses repository-relative paths.
    extra_patches = [str(path.resolve().relative_to(ROOT)) for path in args.extra_source_patch]
    for path in extra_patches:
        if not (ROOT / path).is_file():
            parser.error('extra source patch does not exist: ' + path)
    trace_sha = args.trace_sha256
    if digest(trace.read_bytes()) != trace_sha:
        raise ValueError('input artifact hash mismatch')
    out.mkdir(parents=True)
    buildid_output = subprocess.check_output([str(SDK/'ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-readelf'), '-n', str(trace)], text=True)
    buildid = re.search(r'Build ID: ([0-9a-f]+)', buildid_output).group(1)
    with zipfile.ZipFile(base) as source:
        lock = json.loads(source.read(LOCK))
        lock['artifact'].update(sha256=trace_sha, bytes=trace.stat().st_size,
                                gnuBuildId=buildid, stagedPath=str(trace.relative_to(ROOT)))
        note = {'purpose':'LOCAL DIAGNOSTIC ONLY; NOT A CRASH FIX OR PERFORMANCE BUILD',
                'baseApkSha256':base_sha256, 'traceLibrarySha256':trace_sha,
                'manifestUnchanged':True, 'targetAddress':profile['targetAddress'],
                'traceScope':profile['traceScope'],
                'productionStagingChanged':False, 'deviceQualified':False,
                'traceEnabled':not args.without_trace or args.wsi_trace or args.core_error_trace or args.mfc_progress_trace or args.ppu_wait_trace or args.render_progress_trace,
                'spursTraceEnabled':not args.without_trace,
                'wsiTraceEnabled':args.wsi_trace,
                'coreErrorTraceEnabled':args.core_error_trace,
                'mfcProgressTraceEnabled':args.mfc_progress_trace,
                'spursWorkloadTraceEnabled':args.spurs_workload_trace,
                'ppuWaitTraceEnabled':args.ppu_wait_trace,
                'renderProgressTraceEnabled':args.render_progress_trace,
                'getllarReadBarrierEnabled':args.getllar_read_barrier,
                'combinedFlipRetirementEnabled':args.combined_flip_retirement,
                'nativeStopProbeEnabled':args.native_stop_probe is not None,
                'stateCaptureProbeEnabled':args.state_capture_probe is not None,
                'renderCaptureProbeEnabled':args.render_capture_probe is not None,
                'stateRestoreProbeEnabled':args.state_restore_probe is not None,
                'restorePhaseProbeEnabled':args.restore_phase_probe is not None,
                'restoreAttempt':args.restore_attempt if args.restore_phase_probe is not None else None,
                'restoreAtomicStorageEnabled':args.restore_atomic_storage,
                'zcullTeardownEnabled':args.zcull_teardown,
                'wrapperSyncLifetimeEnabled':args.wrapper_sync_lifetime,
                'sourcePatch':profile['sourcePatch'],
                'extraSourcePatches':extra_patches,
                'normalBuildToRestore':str(base.relative_to(ROOT))}
        lock['localDiagnostic'] = note
        lock['reproducible'] = False
        lock['reproducibleNote'] = 'Isolated translation-unit compile/archive replacement/relink; see localDiagnostic and the recorded build commands. Not an independent clean build.'
        adapter_source = None
        if args.adapter_input_only:
            adapter_source = (args.restore_phase_probe or args.state_restore_probe or args.render_capture_probe or args.state_capture_probe or args.native_stop_probe or ROOT / profile['sourcePatch']).read_bytes()
            matches = [patch for patch in lock['patches'] if patch['path'] == profile['sourcePatch']]
            if len(matches) != 1:
                raise ValueError('expected one original adapter source identity')
            matches[0].update(sha256=digest(adapter_source), bytes=len(adapter_source),
                              note='Local unqualified adapter candidate; see localDiagnostic and scoped probe provenance.')
        for path in [profile['helper'], note['sourcePatch']] + extra_patches:
            if path is None:
                continue
            if args.adapter_input_only and path == profile['sourcePatch']:
                continue  # Existing adapter identity was updated, not duplicated.
            payload = (ROOT/path).read_bytes()
            lock['patches'].append({'path':path, 'sha256':digest(payload), 'bytes':len(payload), 'role':'local-diagnostic-only'})
        index = json.loads(source.read(INDEX))
        for artifact in index['artifacts']:
            if artifact['engineId'] == 'aps3e': artifact['sha256'] = trace_sha
        replacements = {SO:trace.read_bytes(),
                        LOCK:json.dumps(lock, indent=2).encode(), INDEX:json.dumps(index, indent=2).encode()}
        if adapter_source is not None:
            replacements['assets/phase3-aps3e-lucent-adapter.cpp'] = adapter_source
        with zipfile.ZipFile(out/'unsigned.apk', 'w') as destination:
            for entry in source.infolist():
                if not signature(entry.filename):
                    destination.writestr(entry, replacements.get(entry.filename, source.read(entry.filename)))
            destination.writestr(NOTE, json.dumps(note, indent=2))
    tools = SDK/'build-tools/36.0.0'
    subprocess.run([str(tools/'zipalign'), '-f', '4', str(out/'unsigned.apk'), str(out/'aligned.apk')], check=True)
    signed = out/'emufusion-spurs-trace.apk'
    subprocess.run([str(tools/'apksigner'), 'sign', '--ks', str(ROOT/'android-companion/debug.keystore'),
                    '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--ks-key-alias', 'androiddebugkey',
                    '--out', str(signed), str(out/'aligned.apk')], check=True)
    subprocess.run([str(tools/'apksigner'), 'verify', '--verbose', str(signed)], check=True)
    with zipfile.ZipFile(base) as old, zipfile.ZipFile(signed) as new:
        changed = [name for name in old.namelist() if not signature(name) and old.read(name) != new.read(name)]
        added = [name for name in new.namelist() if name not in old.namelist() and not signature(name)]
        # An explicitly supplied replacement may already equal the base payload
        # (for example, the retained adapter source in a CPU-only diagnostic).
        # Verify every requested byte and reject unrelated differences as before.
        expected_changed = [name for name, payload in replacements.items() if old.read(name) != payload]
        assert all(new.read(name) == payload for name, payload in replacements.items())
        assert sorted(changed) == sorted(expected_changed) and added == [NOTE], (changed, added)
        print('Changed payloads:', json.dumps(changed), flush=True)
        print('All other existing payloads are byte-identical; added:', added, flush=True)
    print('APK:', signed, flush=True)
    print('SHA256:', digest(signed.read_bytes()), flush=True)

if __name__ == '__main__':
    main()
