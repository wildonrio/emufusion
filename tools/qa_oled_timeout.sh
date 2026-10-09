#!/bin/sh
# Bounded local QA guard: retain installed build/settings, release input and sleep.
set -eu
evidence_dir=${1:?absolute existing evidence directory required}
test_seconds=${2:-600}
case "$evidence_dir" in /*) ;; *) exit 2 ;; esac
# Longer opening sequences need a bounded 20-minute gameplay window; callers
# should still request stop-test promptly and reserve time for normal Exit.
case "$test_seconds" in 360|600|1200) ;; *) exit 2 ;; esac
test -d "$evidence_dir"
test ! -e "$evidence_dir/watchdog-ended"
test ! -e "$evidence_dir/stop-test"
adb_bin=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
# ADB can wake a closed clamshell. Never arm a gameplay test in that state:
# it defeats the lid's ordinary sleep behavior and makes thermal QA misleading.
# Read-only refusal occurs before settings, guard creation, or device writes.
"$adb_bin" -s 427c87b2 shell dumpsys input > "$evidence_dir/lid-preflight-input.txt"
python3 "$(dirname "$0")/qa_thor_lid_check.py" < "$evidence_dir/lid-preflight-input.txt"
# A connected cable is not proof of charging. Refuse hot/low/unknown telemetry
# before arming or writing settings; the operator must observe successful arm
# and a live guard before issuing any wake or launch command.
"$adb_bin" -s 427c87b2 shell dumpsys battery > "$evidence_dir/battery-preflight.txt"
python3 "$(dirname "$0")/qa_thor_battery_check.py" < "$evidence_dir/battery-preflight.txt"
idle_before=
idle_bounded=
case "${3:-}" in
    '') ;;
    bounded-idle)
        idle_before=$("$adb_bin" -s 427c87b2 shell settings get system screen_off_timeout | tr -d '\r')
        case "$idle_before" in ''|*[!0-9]*) exit 2 ;; esac
        idle_bounded=$((test_seconds * 1000))
        ;;
    *) exit 2 ;;
esac
guard_script=$(dirname "$0")/qa_oled_device_timeout.sh
device_guard_dir=$("$adb_bin" -s 427c87b2 shell mktemp -d /data/local/tmp/emufusion-oled-XXXXXX | tr -d '\r')
case "$device_guard_dir" in /data/local/tmp/emufusion-oled-*) ;; *) exit 2 ;; esac
"$adb_bin" -s 427c87b2 push "$guard_script" "$device_guard_dir/timeout.sh"
"$adb_bin" -s 427c87b2 shell "nohup sh '$device_guard_dir/timeout.sh' '$test_seconds' '$device_guard_dir/cancel' '$idle_before' '$idle_bounded' > '$device_guard_dir/log' 2>&1 < /dev/null &"
printf '%s\n' "$device_guard_dir" > "$evidence_dir/device-guard-dir.txt"
cleanup() {
    set +e
    "$adb_bin" -s 427c87b2 shell 'sendevent /dev/input/event9 1 304 0; sendevent /dev/input/event9 1 305 0; sendevent /dev/input/event9 1 307 0; sendevent /dev/input/event9 1 308 0; sendevent /dev/input/event9 1 310 0; sendevent /dev/input/event9 1 311 0; sendevent /dev/input/event9 1 314 0; sendevent /dev/input/event9 1 315 0; sendevent /dev/input/event9 3 0 0; sendevent /dev/input/event9 3 1 0; sendevent /dev/input/event9 3 2 0; sendevent /dev/input/event9 3 5 0; sendevent /dev/input/event9 3 16 0; sendevent /dev/input/event9 3 17 0; sendevent /dev/input/event9 0 0 0; input keyevent 223; am force-stop com.thorium.preview; settings put system screen_brightness 0; settings put global stay_on_while_plugged_in 0'
    cleanup_status=$?
    if [ -n "$idle_bounded" ]; then
        idle_current=$("$adb_bin" -s 427c87b2 shell settings get system screen_off_timeout | tr -d '\r')
        if [ "$idle_current" = "$idle_bounded" ]; then
            "$adb_bin" -s 427c87b2 shell settings put system screen_off_timeout "$idle_before" || cleanup_status=1
        elif [ -z "$idle_current" ]; then
            cleanup_status=1
        fi
    fi
    # Cancel only after host cleanup succeeds; otherwise the device must still
    # enforce its own deadline if this host or cable disappears.
    if [ "$cleanup_status" -eq 0 ]; then
        "$adb_bin" -s 427c87b2 shell "touch '$device_guard_dir/cancel'"
    fi
    "$adb_bin" -s 427c87b2 shell "cat '$device_guard_dir/log'" > "$evidence_dir/device-guard.log"
    "$adb_bin" -s 427c87b2 shell dumpsys power > "$evidence_dir/final-power.txt"
    "$adb_bin" -s 427c87b2 shell dumpsys display > "$evidence_dir/final-display.txt"
    "$adb_bin" -s 427c87b2 shell 'cat /sys/class/backlight/panel0-backlight/actual_brightness /sys/class/backlight/panel1-backlight/actual_brightness; pidof com.thorium.preview' > "$evidence_dir/final-panels.txt"
    touch "$evidence_dir/watchdog-ended"
    date -u '+cleanup %Y-%m-%dT%H:%M:%SZ'
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP
if [ -n "$idle_bounded" ]; then
    # Backup cleanup is already armed. Restore only our value, never a newer
    # user setting, and leave normal invocations completely unchanged.
    printf '%s\n' "$idle_before" > "$evidence_dir/original-idle-timeout.txt"
    "$adb_bin" -s 427c87b2 shell settings put system screen_off_timeout "$idle_bounded"
fi
date -u '+armed %Y-%m-%dT%H:%M:%SZ'
test_deadline=$(( $(date +%s) + test_seconds ))
while [ "$(date +%s)" -lt "$test_deadline" ] && [ ! -f "$evidence_dir/stop-test" ]; do sleep 1; done
