#!/usr/bin/env python3
"""Restore the preserved Shadow QA capture through the actual adapter callback."""
import argparse
import hashlib
from pathlib import Path
from prepare_render_capture_probe import prepare as prepare_capture

HELPER = r'''static bool adapter_unserialize(lucent_native_engine*, const void*, std::size_t);

static void qa_restore_on_render_owner(lucent_native_engine* engine) {
    if (!engine->qa_capture_requested.exchange(false) ||
        engine->qa_capture_done.exchange(true)) return;
    const auto save = std::filesystem::path(engine->save_directory);
    if (save.filename() != "a2680fcb94d97bbe550e4a694bf99769" ||
        save.parent_path().filename() != "aps3e" ||
        save.parent_path().parent_path().filename() !=
            "qa-6ad510e4afd607fcabffb75570be37ee" ||
        save.parent_path().parent_path().parent_path().filename() != "engine-saves-qa") {
        log_error("state-restore-probe skipped: not the captured Shadow QA save directory");
        return;
    }
    const auto source = capture_state_path();
    const auto expected = std::filesystem::path(engine->system_directory) /
        "config/savestates/BCUS98259/BCUS98259_1_0.SAVESTAT.zst";
    if (source.lexically_normal() != expected.lexically_normal()) {
        log_error("state-restore-probe skipped: not the captured Shadow slot");
        return;
    }
    std::error_code ec;
    if (std::filesystem::exists(save / "lucent-restore.SAVESTAT.zst", ec) || ec) {
        log_error("state-restore-probe skipped: preserve existing or unreadable restore destination");
        return;
    }
    capture_file captured(source);
    // Pin the actual byte count produced by the preceding bounded device run.
    if (!captured.valid || captured.info.st_size != 318191507) {
        log_error("state-restore-probe skipped: captured file missing or size changed");
        return;
    }
    std::vector<std::uint8_t> data(static_cast<std::size_t>(captured.info.st_size));
    std::size_t offset = 0;
    while (offset < data.size()) {
        const auto count = ::read(captured.fd, data.data() + offset, data.size() - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) { log_error("state-restore-probe incomplete source read"); return; }
        offset += static_cast<std::size_t>(count);
    }
    struct stat final_info{};
    if (::fstat(captured.fd, &final_info) != 0 ||
        final_info.st_size != captured.info.st_size) {
        log_error("state-restore-probe source changed while reading");
        return;
    }
    __android_log_print(ANDROID_LOG_WARN, kTag, "state-restore-probe begin bytes=%zu", data.size());
    const bool restored = adapter_unserialize(engine, data.data(), data.size());
    __android_log_print(ANDROID_LOG_WARN, kTag,
                        "state-restore-probe end accepted=%d core_running=%d wrapper_running=%d",
                        restored, Emu.IsRunning(), ae::is_running());
}

'''


def prepare(payload):
    text = prepare_capture(payload)
    start = text.index('static void qa_capture_on_render_owner(')
    end = text.index('static bool adapter_run_frame(', start)
    text = text[:start] + HELPER + text[end:]
    text = text.replace('qa_capture_on_render_owner(engine);', 'qa_restore_on_render_owner(engine);', 1)
    text = text.replace('    std::atomic<bool> qa_capture_requested{false};',
                        '    std::atomic<bool> qa_restore_armed{false};\n    std::atomic<bool> qa_capture_requested{false};', 1)
    old = '''    if (engine->qa_capture_left.load() && engine->qa_capture_right.load())
        engine->qa_capture_requested.store(true);'''
    new = '''    if (engine->qa_capture_left.load() && engine->qa_capture_right.load())
        engine->qa_restore_armed.store(true);
    if (!engine->qa_capture_left.load() && !engine->qa_capture_right.load() &&
        engine->qa_restore_armed.exchange(false))
        engine->qa_capture_requested.store(true);'''
    if text.count(old) != 1:
        raise ValueError('QA chord anchor changed')
    text = text.replace(old, new, 1)
    text = text.replace('    qa_capture_input(engine, control, value);\n', '', 1)
    anchor = '    if (code != 0) ae::key_event(static_cast<std::uint32_t>(code), pressed, magnitude);'
    if text.count(anchor) != 1:
        raise ValueError('Control dispatch anchor changed')
    text = text.replace(anchor, anchor+'\n    qa_capture_input(engine, control, value);', 1)
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
