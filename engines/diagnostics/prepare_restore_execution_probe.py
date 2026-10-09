#!/usr/bin/env python3
"""Combine bounded MFC tracing with retained GETLLAR ordering and SPU entry markers."""
import argparse
import hashlib
from pathlib import Path
import prepare_mfc_progress_trace as mfc

BEGIN = '// LUCENT_RESTORE_EXEC_BEGIN\n'
END = '// LUCENT_RESTORE_EXEC_END\n'
BARRIER = ('\t\t\t// Complete payload reads before rechecking the reservation stamp.\n'
           '\t\t\t// An acquire stamp load only orders operations that follow it; on\n'
           '\t\t\t// ARM it cannot prevent this check from passing the preceding copy.\n'
           '\t\t\tatomic_fence_acquire();\n')
STAMP = '\t\t\tif (u64 time0 = vm::reservation_acquire(addr); (ntime & test_mask) != (time0 & test_mask))'


def instrument(payload):
    text = mfc.instrument(payload)  # Existing exact source pin and original MFC body.
    assert text.count(BARRIER+STAMP) == 1  # Already retained in the pinned source.
    # Logging include must precede cpu_task(), not just the later MFC definition.
    text = text.replace('#include "stdafx.h"\n', '#include "stdafx.h"\n'+BEGIN+'#include <android/log.h>\n'+END, 1)
    anchor = '\tif (jit)\n\t{\n\t\twhile (true)\n\t\t{\n'
    assert text.count(anchor) == 1
    text = text.replace(anchor, BEGIN+'\tu32 lucent_exec_samples = 0;\n'+END+anchor+BEGIN+
        '\t\t\tif (lucent_exec_samples <= 1000000) ++lucent_exec_samples;\n'
        '\t\t\tif (lucent_exec_samples <= 4 || lucent_exec_samples == 1000000)\n'
        '\t\t\t\t__android_log_print(ANDROID_LOG_WARN, "LucentRestoreExecution", "%s", '
        'fmt::format("spu-loop id=0x%x sample=%u pc=0x%x flags=%s", id, lucent_exec_samples, pc, +state).c_str());\n'+END, 1)
    anchor = '\t\t\tspu_runtime::g_gateway(*this, _ptr<u8>(0), nullptr);\n'
    assert text.count(anchor) == 1
    text = text.replace(anchor, BEGIN+
        '\t\t\tif (lucent_exec_samples <= 4) __android_log_print(ANDROID_LOG_WARN, "LucentRestoreExecution", "gateway begin id=0x%x pc=0x%x", id, pc);\n'+END+
        anchor+BEGIN+
        '\t\t\tif (lucent_exec_samples <= 4) __android_log_print(ANDROID_LOG_WARN, "LucentRestoreExecution", "gateway returned id=0x%x pc=0x%x", id, pc);\n'+END, 1)
    return text


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = instrument(a.source.read_bytes())
    with a.output.open('x') as stream:
        stream.write(result)
    print(hashlib.sha256(result.encode()).hexdigest())


if __name__ == '__main__':
    main()
