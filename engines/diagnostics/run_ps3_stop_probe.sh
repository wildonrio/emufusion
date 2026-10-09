#!/bin/sh
# Bounded on-device diagnostic; always restore the exact reviewed entry APK.
set -eu
repo=/Users/tyleryoung/Code/emufusion
adb=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
# Reviewed retained normal build; reject any different current device identity.
entry=$repo/engines/build/candidates/aps3e-wrapper-sync-clean-apk-2026-09-09/emufusion-spurs-trace.apk
entry_sha=eb3c40836062d48f2b65fb9a6a51a9a4a8aedf192bb399248cdba157de6eeb40
diagnostic=${1:?absolute diagnostic APK required}
diagnostic_sha=${2:?exact diagnostic SHA256 required}
evidence=${3:?new absolute evidence directory required}
case "$diagnostic" in "$repo"/engines/build/candidates/*/emufusion-spurs-trace.apk) ;; *) exit 2 ;; esac
case "$evidence" in "$repo"/docs/qa/ps3-stop-probe-*) ;; *) exit 2 ;; esac
test ! -e "$evidence"
test "$(shasum -a 256 "$entry" | cut -d ' ' -f 1)" = "$entry_sha"
test "$(shasum -a 256 "$diagnostic" | cut -d ' ' -f 1)" = "$diagnostic_sha"
installed_sha() {
    package_path=$("$adb" -s 427c87b2 shell pm path com.thorium.preview | tr -d '\r')
    case "$package_path" in package:/data/app/*/base.apk) ;; *) return 1 ;; esac
    "$adb" -s 427c87b2 shell sha256sum "${package_path#package:}" | cut -d ' ' -f 1
}
test "$(installed_sha)" = "$entry_sha"
test -z "$("$adb" -s 427c87b2 shell pidof com.thorium.preview || true)"
mkdir "$evidence"
"$adb" -s 427c87b2 shell dumpsys package com.thorium.preview > "$evidence/package-before.txt"
restore_needed=0
guard_pid=
cleanup() {
    trap - EXIT INT TERM HUP
    set +e
    if [ -n "$guard_pid" ]; then
        touch "$evidence/stop-test"
        wait "$guard_pid"
    fi
    "$adb" -s 427c87b2 shell 'input keyevent 223; am force-stop com.thorium.preview'
    if [ "$restore_needed" -eq 1 ]; then
        "$adb" -s 427c87b2 install --no-incremental -r "$entry" > "$evidence/restore.txt" 2>&1
        restored=$(installed_sha)
        printf '%s\n' "$restored" > "$evidence/restored-sha256.txt"
        if [ "$restored" != "$entry_sha" ]; then
            echo 'ERROR: exact entry APK restore not verified' >&2
            exit 1
        fi
    fi
    "$adb" -s 427c87b2 shell 'input keyevent 223; am force-stop com.thorium.preview; dumpsys power | grep mWakefulness=; cat /sys/class/backlight/panel0-backlight/actual_brightness /sys/class/backlight/panel1-backlight/actual_brightness; pidof com.thorium.preview; settings get system screen_off_timeout' > "$evidence/restored-state.txt"
    date -u '+restored and asleep %Y-%m-%dT%H:%M:%SZ'
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
restore_needed=1
"$adb" -s 427c87b2 install --no-incremental -r "$diagnostic" > "$evidence/install.txt" 2>&1
test "$(installed_sha)" = "$diagnostic_sha"
printf '%s\n' "$diagnostic_sha" > "$evidence/diagnostic-sha256.txt"
sh "$repo/tools/qa_oled_timeout.sh" "$evidence" 600 bounded-idle &
guard_pid=$!
echo 'Diagnostic installed; wait for OLED guard armed before waking.'
wait "$guard_pid"
guard_pid=
