#!/usr/bin/env python3
"""Isolated, bounded SPURS workload snapshots layered on reviewed MFC sampling.

No production source writes and no changes to guest command results. Samples
copy only owner local-store context and the owner's existing reservation buffer.
"""
import argparse
import hashlib
from pathlib import Path
import prepare_mfc_progress_trace as mfc

HEADER = Path(__file__).with_name('lucent_spurs_workload_snapshot.h')
OLD_SINK = '''}, []() noexcept { return get_system_time(); }, [](const char* line) noexcept
\t{
\t\t__android_log_write(ANDROID_LOG_INFO, "LucentMfcProgress", line);
\t});'''
NEW_SINK = '''}, []() noexcept { return get_system_time(); }, [&](const char* line) noexcept
\t{
\t\t__android_log_write(ANDROID_LOG_INFO, "LucentMfcProgress", line);
\t\tif (group && spurs_addr && spurs_addr != 0u - 0x80u)
\t\t{
\t\t\tlucent_spurs_workload::snapshot sample{spurs_addr, group->id, index,
\t\t\t\tgroup->max_num, atomic_storage<u32>::load(group->max_run),
\t\t\t\tgroup->spurs_running.load(), spurs_entered_wait, spurs_waited};
\t\t\tstd::memcpy(sample.kernel, _ptr<u8>(0x180), sizeof(sample.kernel));
\t\t\tstd::memcpy(sample.reservation, rdata, sizeof(sample.reservation));
\t\t\tlucent_spurs_workload::emit(line, sample, [](const char* record) noexcept
\t\t\t{
\t\t\t\t__android_log_write(ANDROID_LOG_INFO, "LucentSpursWorkload", record);
\t\t\t});
\t\t}
\t});'''


def instrument(payload):
    result = mfc.instrument(payload)  # Retains original source SHA gate.
    if result.count(OLD_SINK) != 1:
        raise ValueError('MFC sink changed; review before instrumentation')
    helper = '\n' + HEADER.read_text().replace('#pragma once\n', '', 1) + '\n'
    return result.replace(mfc.START, helper + mfc.START, 1).replace(OLD_SINK, NEW_SINK, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = instrument(args.source.read_bytes())
    with args.output.open('x') as output:
        output.write(result)
    print('Source SHA256:', mfc.EXPECTED_SHA)
    print('Output SHA256:', hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
