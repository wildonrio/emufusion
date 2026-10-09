#!/system/bin/sh
# Qualification-only heap investigation. Applies to this app process, not the
# device allocator configuration. No generation, timing, or gameplay overrides.
# Android 13 supports these options; do not use Android 14 size-filter options.
# Thor's fast unwinder crashed during Qt startup (52df), and per-allocation
# full unwinding exposed invalid frees in libunwindstack's TLS cleanup (1103).
# Keep guards/free quarantine without routinely invoking either unwinder.
# Abort on the FIRST detected error: continuing produced an 842 MB poison-error
# storm in 2f8b, obscuring the first failure and adding severe diagnostic load.
# The tombstone is a detection-site stack, not the writer or original free.
# Allocation/free-site backtraces remain unavailable; backtrace_full only selects
# the unwinder for errors that request one (UAF poison reports do not).
export LIBC_DEBUG_MALLOC_OPTIONS='guard=32 free_track=64 free_track_backtrace_num_frames=0 backtrace_full abort_on_error'
exec logwrapper "$@"
