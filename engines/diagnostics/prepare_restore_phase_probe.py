#!/usr/bin/env python3
"""Separate restore commit/shutdown/boot; preserve the previous QA destination."""
import argparse
import hashlib
import re
from pathlib import Path
from prepare_state_restore_probe import prepare as prepare_restore
from prepare_core_error_trace import LISTENER

WRAPPER_SHA = 'e5dcd71772b27c5b6f73f150e3e0fc54ce51421b6804f2c7a1cb3448c1ae39c0'
QA_PARENT = 'app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee'


def prepare_wrapper(payload):
    if hashlib.sha256(payload).hexdigest() != WRAPPER_SHA:
        raise ValueError('Retained wrapper source changed')
    text = payload.decode()
    anchor = '    void init(){\n'
    if text.count(anchor) != 1 or text.count('namespace ae{') != 1:
        raise ValueError('Wrapper listener anchors changed')
    text = text.replace('namespace ae{', LISTENER+'\nnamespace ae{', 1)
    return text.replace(anchor, anchor+'        install_lucent_core_error_listener();\n', 1)


def prepare(payload, attempt='phase2'):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,48}', attempt):
        raise ValueError('Restore attempt must be a simple QA filename component')
    text = prepare_restore(payload)
    # Keep the original destination intact even if the first restore committed it.
    old = 'std::filesystem::exists(save / "lucent-restore.SAVESTAT.zst", ec)'
    assert text.count(old) == 1
    text = text.replace(old, 'std::filesystem::exists(save / "lucent-restore-phase2.SAVESTAT.zst", ec)', 1)
    start = text.index('static bool adapter_unserialize(lucent_native_engine* engine,')
    end = text.index('static bool adapter_surface_recreated(', start)
    original = text[start:end]
    body = original
    anchor = '    const std::filesystem::path incoming =\n'
    body = body.replace(anchor, '''    const bool qa_phase =
        std::filesystem::path(engine->system_directory).parent_path().filename() ==
            "'''+QA_PARENT+'''";
    const auto phase = [qa_phase](const char* name) {
        if (qa_phase) __android_log_print(ANDROID_LOG_WARN, kTag,
                                         "state-restore-phase %s", name);
    };
'''+anchor, 1)
    body = body.replace('/ "lucent-restore.SAVESTAT.zst";',
        '/ (qa_phase ? "lucent-restore-phase2.SAVESTAT.zst" : "lucent-restore.SAVESTAT.zst");', 1)
    body = body.replace('    if (!write_file_atomic(incoming, data, size)) return false;',
        '''    if (qa_phase && g_cfg.savestate.suspend_emu) {
        phase("skipped: suspend mode would consume preserved state");
        return false;
    }
    Dl_info image_info{};
    if (qa_phase && dladdr(reinterpret_cast<const void*>(&adapter_unserialize), &image_info))
        __android_log_print(ANDROID_LOG_WARN, kTag, "state-restore image-base=%p", image_info.dli_fbase);
    phase("commit begin");
    if (!write_file_atomic(incoming, data, size)) { phase("commit failed"); return false; }
    phase("commit complete");''', 1)
    body = body.replace('    Emu.GracefulShutdown(false, false, false);',
        '''    phase("shutdown begin");
    Emu.GracefulShutdown(false, false, false);
    phase("shutdown returned");''', 1)
    body = body.replace('    if (!Emu.IsStopped(true)) return false;',
        '''    if (!Emu.IsStopped(true)) { phase("shutdown timeout"); return false; }
    phase("fully stopped");''', 1)
    body = body.replace('    return Emu.BootGame(incoming.string(), "", true) == game_boot_result::no_errors;',
        '''    phase("boot begin");
    const auto result = Emu.BootGame(incoming.string(), "", true);
    if (qa_phase) __android_log_print(ANDROID_LOG_WARN, kTag,
                                     "state-restore-phase boot returned result=%d", static_cast<int>(result));
    return result == game_boot_result::no_errors;''', 1)
    for phase in ('commit begin', 'commit complete', 'shutdown begin', 'shutdown returned',
                  'fully stopped', 'boot begin', 'boot returned'):
        if phase not in body:
            raise ValueError('Missing restore phase anchor: '+phase)
    result = text[:start]+body+text[end:]
    return result.replace('lucent-restore-phase2.SAVESTAT.zst',
                          'lucent-restore-'+attempt+'.SAVESTAT.zst')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--wrapper', action='store_true')
    parser.add_argument('--attempt', default='phase2')
    args = parser.parse_args()
    result = prepare_wrapper(args.source.read_bytes()) if args.wrapper else prepare(args.source.read_bytes(), args.attempt)
    with args.output.open('x') as stream:
        stream.write(result)
    print('Output SHA256:', hashlib.sha256(result.encode()).hexdigest())


if __name__ == '__main__':
    main()
