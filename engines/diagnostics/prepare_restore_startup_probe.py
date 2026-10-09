#!/usr/bin/env python3
"""Isolated, bounded owner-thread markers for the PS3 restore startup stall.

Does not change scheduling, flags, guest memory or cache decisions. Diagnostic
logging overhead disqualifies these binaries from performance qualification.
"""
import argparse
import hashlib
from pathlib import Path

PINS = {
    'CPUThread.cpp': '918932ffb788267452c7d480f7d031166644fdf80255a0f7f9d189ac37eeba3f',
    'PPUThread.cpp': '59b61cdc3d67389e1e190c090f1502da71bf172358531f2c009be606574d1f0b',
}
BEGIN = '// LUCENT_RESTORE_STARTUP_BEGIN\n'
END = '// LUCENT_RESTORE_STARTUP_END\n'


def block(code):
    return BEGIN + code + '\n' + END


def prepare(payload, name):
    if hashlib.sha256(payload).hexdigest() != PINS[name]:
        raise ValueError('pinned startup source changed; review before instrumentation')
    text = payload.decode()
    text = text.replace('#include "stdafx.h"\n', '#include "stdafx.h"\n' + block(
        '#include <android/log.h>'), 1)

    def after(anchor, code):
        nonlocal text
        if text.count(anchor) != 1:
            raise ValueError('ambiguous startup marker: ' + anchor)
        text = text.replace(anchor, anchor + block(code), 1)

    if name == 'CPUThread.cpp':
        after('\t// Check thread status\n', '\tu32 lucent_startup_samples = 0;')
        after('\t\tconst auto state0 = +state;\n',
              '\t\tif (lucent_startup_samples <= 1000000) ++lucent_startup_samples;\n'
              '\t\tif (lucent_startup_samples <= 4 || lucent_startup_samples == 1000000)\n'
              '\t\t\t__android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "%s", '
              'fmt::format("cpu-loop id=0x%x sample=%u flags=%s", id, lucent_startup_samples, state0).c_str());')
        after('\t\tif (!(state0 & cpu_flag::stop))\n\t\t{\n',
              '\t\t\tif (lucent_startup_samples <= 4) __android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "cpu-task begin id=0x%x", id);')
        after('\t\t\tcpu_task();\n',
              '\t\t\tif (lucent_startup_samples <= 4) __android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "cpu-task returned id=0x%x", id);')
        after('\t\tstate.wait(state0);\n',
              '\t\tif (lucent_startup_samples <= 4) __android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "cpu-stop wait returned id=0x%x", id);')
    else:
        after('\t\t\tppu_initialize();\n',
              '\t\t\t__android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "ppu initialize returned id=0x%x", id);')
        after('\t\t\tspu_cache::initialize();\n',
              '\t\t\t__android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "spu cache returned id=0x%x progress=%u", id, +g_progr_ptotal);')
        after('\t\t\t// Wait until the progress dialog is closed.\n',
              '\t\t\tu32 lucent_progress_samples = 0;')
        after('\t\t\twhile (u32 v = g_progr_ptotal)\n\t\t\t{\n',
              '\t\t\t\tif (lucent_progress_samples++ < 3) __android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "progress wait id=0x%x total=%u", id, v);\n'
              '\t\t\t\tif (lucent_progress_samples > 3) lucent_progress_samples = 3;')
        after('\t\t\tEmu.FixGuestTime();\n',
              '\t\t\t__android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "guest time fixed id=0x%x", id);')
        after('\t\t\t// Check if this is the only PPU left to initialize (savestates related)\n',
              '\t\t\t__android_log_print(ANDROID_LOG_WARN, "LucentRestoreStartup", "scheduler gate id=0x%x ready=%d starting=%d", id, lv2_obj::is_scheduler_ready(), Emu.IsStarting());')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source.read_bytes(), args.source.name)
    with args.output.open('x') as stream:
        stream.write(result)
    print(args.output, hashlib.sha256(result.encode()).hexdigest())


if __name__ == '__main__':
    main()
