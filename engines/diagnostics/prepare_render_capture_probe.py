#!/usr/bin/env python3
"""QA L+R chord requests capture on the render owner before Exit starts."""
import argparse
import hashlib
from pathlib import Path
from prepare_fresh_savestate import prepare as prepare_fresh

FIELDS = '''    std::atomic<bool> qa_capture_left{false};
    std::atomic<bool> qa_capture_right{false};
    std::atomic<bool> qa_capture_requested{false};
    std::atomic<bool> qa_capture_done{false};
'''
HELPERS = r'''static std::size_t adapter_serialize_size(lucent_native_engine* engine);

static void qa_capture_input(lucent_native_engine* engine,
                             lucent_native_control control, float value) {
    if (!engine || !engine->loaded || !engine->started || engine->stopped ||
        (control != LUCENT_PAD_L && control != LUCENT_PAD_R) ||
        std::filesystem::path(engine->system_directory).filename() != "aps3e" ||
        std::filesystem::path(engine->system_directory).parent_path().filename() !=
            "app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee") return;
    (control == LUCENT_PAD_L ? engine->qa_capture_left : engine->qa_capture_right)
        .store(value > 0.5f);
    if (engine->qa_capture_left.load() && engine->qa_capture_right.load())
        engine->qa_capture_requested.store(true);
}

static void qa_capture_on_render_owner(lucent_native_engine* engine) {
    if (!engine->qa_capture_requested.exchange(false) ||
        engine->qa_capture_done.exchange(true)) return;
    std::error_code ec;
    const auto slot = capture_state_path();
    if (slot.empty() || std::filesystem::exists(slot, ec) || ec) {
        log_error("render-capture-probe skipped: preserve existing or unreadable QA slot");
        return;
    }
    __android_log_print(ANDROID_LOG_WARN, kTag, "render-capture-probe begin");
    const auto bytes = adapter_serialize_size(engine);
    __android_log_print(ANDROID_LOG_WARN, kTag,
                        "render-capture-probe end bytes=%zu stopped=%d path=%s",
                        bytes, engine->stopped, engine->restore_path.c_str());
}

'''


def prepare(payload):
    text = prepare_fresh(payload)
    text = text.replace('    bool save_requested = false;\n', '    bool save_requested = false;\n'+FIELDS, 1)
    text = text.replace('static bool adapter_run_frame(', HELPERS+'static bool adapter_run_frame(', 1)
    text = text.replace('    // RPCS3 owns its emulation/render threads.',
                        '    qa_capture_on_render_owner(engine);\n    // RPCS3 owns its emulation/render threads.', 1)
    text = text.replace('    bool pressed = false;\n',
                        '    qa_capture_input(engine, control, value);\n    bool pressed = false;\n', 1)
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
