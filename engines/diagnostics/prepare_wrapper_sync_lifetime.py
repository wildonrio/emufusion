#!/usr/bin/env python3
"""Keep aPS3e's global request synchronization alive while callers wake."""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = 'c78c5ff757ee2605e14aca759a5d3d7ca8a2a29a920ff2dc5c3cfab7ebe7be31'


def prepare(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError('Wrapper source changed; review before preparing')
    text = payload.decode()
    for name in ('key_event_mutex', 'emu_mutex'):
        text = text.replace('pthread_mutex_t '+name+';',
                            'pthread_mutex_t '+name+' = PTHREAD_MUTEX_INITIALIZER;')
    text = text.replace('pthread_cond_t emu_cond;',
                        'pthread_cond_t emu_cond = PTHREAD_COND_INITIALIZER;')
    text = text.replace('    int emu_status=-1;', '    std::atomic<int> emu_status{-1};')
    lines = text.splitlines(keepends=True)
    removed = [line for line in lines if any(token in line for token in
               ('pthread_mutex_init(', 'pthread_cond_init(',
                'pthread_mutex_destroy(', 'pthread_cond_destroy('))]
    if len(removed) != 9:
        raise ValueError('Unexpected wrapper synchronization lifetime calls')
    text = ''.join(line for line in lines if line not in removed)
    text = text.replace('    pthread_mutex_t key_event_mutex',
        '    // Process-lifetime synchronization: quit() must reacquire emu_mutex\n'
        '    // after the worker signals it. Worker exit must not destroy it first.\n'
        '    pthread_mutex_t key_event_mutex', 1)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.source.read_bytes())
    with args.output.open('x') as stream:
        stream.write(result)
    print('Output SHA256:', hashlib.sha256(result.encode()).hexdigest())


if __name__ == '__main__':
    main()
