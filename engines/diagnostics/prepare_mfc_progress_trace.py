#!/usr/bin/env python3
"""Wrap generic PS3 MFC calls in a bounded, isolated owner-thread diagnostic.

This is NOT a core correction or a performance-qualified build. Refuse source
drift and existing destinations. The original function body is retained intact
inside a bool-returning lambda, including all nested lambdas and early returns.
"""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = 'a2acd7bd1d442ddfcce28e91169ffc87209a52c494ca6f3ef4b685b63945c3fb'
HEADER = Path(__file__).with_name('lucent_mfc_progress_trace.h')
START = 'bool spu_thread::process_mfc_cmd()\n{\n'
END = '\n}\n\nbool spu_thread::reservation_check(u32 addr, const decltype(rdata)& data) const\n{'
PREFIX = r'''
	static thread_local lucent_mfc_progress::journal lucent_mfc_journal;
	const auto lucent_cmd = ch_mfc_cmd.cmd == MFC_GETLLAR_CMD ? lucent_mfc_progress::command::getllar
		: ch_mfc_cmd.cmd == MFC_PUTLLC_CMD ? lucent_mfc_progress::command::putllc
		: lucent_mfc_progress::command::other;
	return lucent_mfc_journal.run(lucent_cmd, id, [&]() -> bool
	{
'''
SUFFIX = r'''
	}, [&]() noexcept
	{
		const auto status = ch_atomic_stat.get_value();
		if (lucent_cmd == lucent_mfc_progress::command::getllar && status == MFC_GETLLAR_SUCCESS)
			return lucent_mfc_progress::outcome::get_ok;
		if (lucent_cmd == lucent_mfc_progress::command::putllc && status == MFC_PUTLLC_SUCCESS)
			return lucent_mfc_progress::outcome::put_ok;
		if (lucent_cmd == lucent_mfc_progress::command::putllc && status == MFC_PUTLLC_FAILURE)
			return lucent_mfc_progress::outcome::put_failed;
		return lucent_mfc_progress::outcome::unknown;
	}, [&]() noexcept
	{
		return lucent_mfc_progress::observation{id, pc, static_cast<u32>(ch_mfc_cmd.cmd),
			ch_mfc_cmd.eah, ch_mfc_cmd.eal, ch_mfc_cmd.lsa, raddr, rtime, ch_events.load().all};
	}, []() noexcept { return get_system_time(); }, [](const char* line) noexcept
	{
		__android_log_write(ANDROID_LOG_INFO, "LucentMfcProgress", line);
	});
'''


def additions():
    # Embed the reviewed helper, so the isolated source has no mutable extra
    # include dependency between preparation and compilation.
    return '\n#include <android/log.h>\n' + HEADER.read_text().replace('#pragma once\n', '', 1) + '\n'


def instrument(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError('SPUThread.cpp changed; review before instrumentation')
    text = payload.decode()
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError('ambiguous MFC function boundary')
    first = text.index(START) + len(START)
    last = text.index(END, first)
    # Includes/types precede the function, not stdafx.h or emulator declarations.
    return (text[:first - len(START)] + additions() + START + PREFIX +
            text[first:last] + SUFFIX + text[last:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = instrument(args.source.read_bytes())
    with args.output.open('x') as stream:
        stream.write(result)
    print('Source SHA256:', EXPECTED_SHA)
    print('Helper SHA256:', hashlib.sha256(HEADER.read_bytes()).hexdigest())
    print('Output SHA256:', hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
