#!/usr/bin/env python3
"""Test real state capture only in the already-existing isolated PS3 QA namespace."""
import argparse
import hashlib
from pathlib import Path
from prepare_fresh_savestate import prepare as prepare_fresh

OLD = 'static bool adapter_flush_save(lucent_native_engine* engine) {\n'
DECLARATION = 'static std::size_t adapter_serialize_size(lucent_native_engine* engine);\n\n'
HOOK = r'''    // QA-only trigger. Normal namespaces keep their persistent-save-only flush.
    if (engine && engine->loaded && engine->started && !engine->stopped &&
        std::filesystem::path(engine->system_directory).filename() == "aps3e" &&
        std::filesystem::path(engine->system_directory).parent_path().filename() ==
            "app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee") {
        // This first-capture test must not replace any previously saved QA state.
        std::error_code ec;
        const auto slot = capture_state_path();
        if (slot.empty() || std::filesystem::exists(slot, ec) || ec) {
            log_error("state-capture-probe skipped: preserve existing or unreadable QA slot");
            return false;
        }
        __android_log_print(ANDROID_LOG_WARN, kTag, "state-capture-probe begin");
        const auto bytes = adapter_serialize_size(engine);
        __android_log_print(ANDROID_LOG_WARN, kTag,
                            "state-capture-probe end bytes=%zu stopped=%d path=%s",
                            bytes, engine->stopped, engine->restore_path.c_str());
        return bytes > 0;
    }
'''


def prepare(payload):
    text = prepare_fresh(payload)
    if text.count(OLD) != 1:
        raise ValueError('Unexpected flush anchor')
    return text.replace(OLD, DECLARATION + OLD + HOOK, 1)


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
