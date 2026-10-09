#!/usr/bin/env python3
"""Native-stop trigger restricted to the existing isolated PS3 QA namespace."""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = "6fea8f3eff0e6ab4e76cf578454950d2db9b8b2344027ddc4898d1ff53654dfa"
OLD = "static bool adapter_flush_save(lucent_native_engine* engine) {\n"
NEW = OLD + """    // LOCAL DIAGNOSTIC: do not enable native teardown for ordinary saves.
    if (engine && engine->loaded && engine->started && !engine->stopped &&
        std::filesystem::path(engine->system_directory).filename() == "aps3e" &&
        std::filesystem::path(engine->system_directory).parent_path().filename() ==
            "app_engine-system-qa-qa-6ad510e4afd607fcabffb75570be37ee") {
        __android_log_print(ANDROID_LOG_WARN, kTag, "native-stop-probe begin");
        ae::quit();
        const auto deadline = std::chrono::steady_clock::now() + kStopTimeout;
        while (std::chrono::steady_clock::now() < deadline && !Emu.IsStopped(true))
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        const bool fully_stopped = Emu.IsStopped(true);
        __android_log_print(ANDROID_LOG_WARN, kTag,
                            "native-stop-probe end fullyStopped=%d", fully_stopped);
        if (!fully_stopped) return false;
        engine->stopped = true;
    }
"""


def prepare(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError("Adapter changed; review before preparing probe")
    text = payload.decode()
    if text.count(OLD) != 1:
        raise ValueError("flush anchor absent or ambiguous")
    return text.replace(OLD, NEW, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.source.read_bytes())
    with args.output.open("x") as stream:
        stream.write(result)
    print("Output SHA256:", hashlib.sha256(result.encode()).hexdigest())


if __name__ == "__main__":
    main()
