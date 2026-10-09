#!/usr/bin/env python3
"""Prepare isolated exact-slot savestate capture; leave installed/staged code alone."""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = '6fea8f3eff0e6ab4e76cf578454950d2db9b8b2344027ddc4898d1ff53654dfa'

OLD_COMMIT = '''    std::filesystem::remove(destination, ec);
    ec.clear();
    std::filesystem::rename(pending, destination, ec);
    if (ec) std::filesystem::remove(pending, ec);
    return !ec;'''
NEW_COMMIT = '''    // POSIX rename replaces the old restore file atomically. Never delete it
    // first, and never let successful cleanup erase a failed commit result.
    std::filesystem::rename(pending, destination, ec);
    if (ec) {
        std::error_code cleanup_error;
        std::filesystem::remove(pending, cleanup_error);
        return false;
    }
    return true;'''

HELPERS = r'''// Hold the old file open across Kill: pending_file::commit() atomically
// replaces it, and a live descriptor prevents its inode being recycled.
struct capture_file {
    int fd;
    int error = 0;
    struct stat info{};
    bool valid = false;
    explicit capture_file(const std::filesystem::path& path)
        : fd(::open(path.c_str(), O_RDONLY | O_CLOEXEC)) {
        if (fd < 0) error = errno;
        else valid = ::fstat(fd, &info) == 0 && S_ISREG(info.st_mode);
    }
    ~capture_file() { if (fd >= 0) ::close(fd); }
    capture_file(const capture_file&) = delete;
    capture_file& operator=(const capture_file&) = delete;
};

std::filesystem::path capture_state_path() {
    // Match Emulator::Kill's writer, not a recursive "newest state" search.
    std::string path = get_savestate_file(Emu.GetTitleID(), Emu.GetBoot(), 0, 0);
    const auto suffix = path.rfind(".SAVESTAT");
    if (suffix == std::string::npos) return {};
    path.resize(suffix + std::strlen(".SAVESTAT"));
    return path + ".zst";
}

bool read_committed_state(const capture_file& before,
                          const std::filesystem::path& path,
                          std::vector<std::uint8_t>& out) {
    out.clear();
    capture_file after(path);
    if (!after.valid || after.info.st_size <= 0 ||
        static_cast<std::uint64_t>(after.info.st_size) > kMaxStateBytes ||
        (before.valid && before.info.st_dev == after.info.st_dev &&
         before.info.st_ino == after.info.st_ino)) return false;
    out.resize(static_cast<std::size_t>(after.info.st_size));
    std::size_t offset = 0;
    while (offset < out.size()) {
        const auto count = ::read(after.fd, out.data() + offset, out.size() - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) { out.clear(); return false; }
        offset += static_cast<std::size_t>(count);
    }
    struct stat final_info{};
    if (::fstat(after.fd, &final_info) != 0 || final_info.st_size != after.info.st_size) {
        out.clear();
        return false;
    }
    return true;
}

'''

SERIALIZE = r'''static std::size_t adapter_serialize_size(lucent_native_engine* engine) {
    if (!engine || !engine->started) return 0;
    std::lock_guard lock(engine->mutex);
    if (!engine->save_requested) {
        engine->save_requested = true;
        engine->serialized_state.clear();
        engine->restore_path.clear();
        if (engine->stopped || Emu.IsStopped()) return 0;
        const auto path = capture_state_path();
        if (path.empty()) return 0;
        const capture_file before(path);
        if (!before.valid && before.error != ENOENT) {
            log_error("Cannot identify the previous savestate slot");
            return 0;
        }
        Emu.Kill(false, true);
        const auto deadline = std::chrono::steady_clock::now() + kStopTimeout;
        while (std::chrono::steady_clock::now() < deadline && !Emu.IsStopped(true))
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        if (!Emu.IsStopped(true)) {
            log_error("Savestate capture did not complete before timeout");
            return 0;
        }
        // The wrapper must retire even when the core stopped without saving.
        if (ae::is_running() || ae::is_paused()) ae::quit();
        engine->stopped = true;
        if (!read_committed_state(before, path, engine->serialized_state)) {
            log_error("Savestate capture did not commit a fresh complete file");
            return 0;
        }
        engine->restore_path = path;
    }
    return engine->serialized_state.size();
}

'''


def prepare(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError('Adapter changed; review before preparing savestate correction')
    text = payload.decode()
    start = text.index('std::filesystem::path newest_state(')
    end = text.index('bool write_file_atomic(', start)
    text = text[:start] + HELPERS + text[end:]
    start = text.index('static std::size_t adapter_serialize_size(')
    end = text.index('static std::size_t adapter_serialize(', start)
    text = text[:start] + SERIALIZE + text[end:]
    if text.count(OLD_COMMIT) != 1:
        raise ValueError('Restore-file commit anchor changed')
    text = text.replace(OLD_COMMIT, NEW_COMMIT, 1)
    return text.replace('#include <fcntl.h>', '#include <cerrno>\n#include <sys/stat.h>\n#include <fcntl.h>', 1)


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
