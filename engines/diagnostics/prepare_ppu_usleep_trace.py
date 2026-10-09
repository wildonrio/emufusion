#!/usr/bin/env python3
"""Trace bounded owner-thread PPU usleep callers in an exclusive source copy."""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = 'ca62b485e2b5227bac072d62c50f1cf997d1c559efacad12b506d65c03ddb45e'
HEADER = Path(__file__).with_name('lucent_ppu_wait_trace.h')
START = 'error_code sys_timer_usleep(ppu_thread& ppu, u64 sleep_time)\n{\n'
HOOK = r'''
    static thread_local lucent_ppu_wait::budget lucent_budget;
    if (lucent_budget.sample([]() noexcept { return get_system_time(); }))
    {
        char regs[32 * 18 + 1]{};
        unsigned used = 0;
        for (unsigned i = 0; i < 32; ++i)
            used += std::snprintf(regs + used, sizeof(regs) - used, "%016llx%s",
                static_cast<unsigned long long>(ppu.gpr[i]), i == 31 ? "" : ",");
        __android_log_print(ANDROID_LOG_INFO, "LucentPpuWait",
            "v=1 sample=%u calls=%llu us=%llu owner=%08x cia=%08x lr=%016llx "
            "ctr=%016llx requested_us=%llu end_time=%llu gpr0_to_31=%s",
            lucent_budget.samples, static_cast<unsigned long long>(lucent_budget.calls),
            static_cast<unsigned long long>(lucent_budget.last_us), ppu.id, ppu.cia,
            static_cast<unsigned long long>(ppu.lr), static_cast<unsigned long long>(ppu.ctr),
            static_cast<unsigned long long>(sleep_time),
            static_cast<unsigned long long>(ppu.end_time), regs);
        if (lucent_budget.new_code_site(ppu.lr))
        {
            const u32 first = static_cast<u32>(ppu.lr - 64);
            if (vm::check_addr(first, vm::page_readable | vm::page_executable, 128))
            {
                PPUDisAsm dis(cpu_disasm_mode::dump, vm::g_base_addr);
                for (u32 offset = 0; offset < 128; offset += 4)
                {
                    dis.disasm(first + offset);
                    __android_log_print(ANDROID_LOG_INFO, "LucentPpuWait",
                        "code owner=%08x lr=%016llx pc=%08x asm=%s", ppu.id,
                        static_cast<unsigned long long>(ppu.lr), first + offset,
                        dis.last_opcode.c_str());
                }
            }
            else
            {
                __android_log_print(ANDROID_LOG_INFO, "LucentPpuWait",
                    "code-unavailable owner=%08x lr=%016llx", ppu.id,
                    static_cast<unsigned long long>(ppu.lr));
            }
        }
    }
'''


def additions():
    return ('\n#include <android/log.h>\n#include <cstdio>\n#include "Emu/Cell/PPUDisAsm.h"\n' +
            HEADER.read_text().replace('#pragma once\n', '', 1) + '\n')


def instrument(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError('sys_timer.cpp changed; review before instrumentation')
    text = payload.decode()
    if text.count(START) != 1:
        raise ValueError('ambiguous usleep function')
    return text.replace(START, additions() + START + HOOK, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = instrument(args.source.read_bytes())
    with args.output.open('x') as output:
        output.write(result)
    print('Original SHA256:', EXPECTED_SHA)
    print('Output SHA256:', hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
