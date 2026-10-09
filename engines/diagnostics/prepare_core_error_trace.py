#!/usr/bin/env python3
"""Expose existing PS3 fatal/error messages in an isolated diagnostic only.

No extra guest-memory reads or emulation decisions. Existing file logging remains
intact. This adds logging overhead and must not qualify performance or pacing.
"""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = 'c78c5ff757ee2605e14aca759a5d3d7ca8a2a29a920ff2dc5c3cfab7ebe7be31'
LISTENER = r'''
#include <algorithm>
#include <android/log.h>
namespace {
class LucentCoreErrorListener final : public logs::listener {
public:
    void log(u64 stamp, const logs::message& msg, const std::string& prefix,
             const std::string& text) override {
        const auto severity = static_cast<logs::level>(msg);
        if (severity != logs::level::fatal && severity != logs::level::error) return;
        // Split long core register/exception dumps below Android's entry limit.
        // Each fragment retains its core timestamp, channel and thread prefix.
        constexpr std::size_t chunk = 2800;
        std::size_t offset = 0;
        do {
            const std::size_t length = std::min(chunk, text.size() - offset);
            __android_log_print(ANDROID_LOG_ERROR, "LucentCoreError",
                "stamp=%llu level=%u channel=%.96s thread=%.160s offset=%zu %.*s",
                static_cast<unsigned long long>(stamp), static_cast<unsigned>(severity),
                msg->name ? msg->name : "", prefix.c_str(), offset,
                static_cast<int>(length), text.c_str() + offset);
            offset += length;
        } while (offset < text.size());
    }
};
void install_lucent_core_error_listener() {
    static LucentCoreErrorListener listener;
    static const bool registered = [] {
        logs::listener::add(&listener);
        __android_log_print(ANDROID_LOG_INFO, "LucentCoreError", "READY fatal/error mirror");
        return true;
    }();
    (void)registered;
}
}
'''


def instrument(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError('aps3e_emu source changed; review before instrumentation')
    text = payload.decode()
    anchor = '    void init(){\n'
    if text.count(anchor) != 1 or text.count('namespace ae{') != 1:
        raise ValueError('ambiguous diagnostic anchor')
    text = text.replace('namespace ae{', LISTENER + '\nnamespace ae{', 1)
    return text.replace(anchor, anchor + '        install_lucent_core_error_listener();\n', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = instrument(args.source.read_bytes())
    with args.output.open('x') as stream:
        stream.write(result)
    print('Output SHA256:', hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
