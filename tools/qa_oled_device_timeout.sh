#!/system/bin/sh
# Device-side backup: survives loss of the host QA process/ADB connection.
test_seconds=${1:?duration required}
cancel_file=${2:?unique cancellation file required}
idle_before=${3:-}
idle_bounded=${4:-}
case "$test_seconds" in 360|600|1200) ;; *) exit 2 ;; esac
case "$cancel_file" in /data/local/tmp/emufusion-oled-*/cancel) ;; *) exit 2 ;; esac
if [ -n "$idle_bounded" ]; then
    case "$idle_before" in ''|*[!0-9]*) exit 2 ;; esac
    case "$idle_bounded" in *[!0-9]*) exit 2 ;; esac
    [ "$idle_bounded" -eq "$((test_seconds * 1000))" ] || exit 2
fi
deadline=$(( $(date +%s) + test_seconds ))
echo "armed device deadline=$deadline"
while [ "$(date +%s)" -lt "$deadline" ]; do
    [ -e "$cancel_file" ] && exit 0
    sleep 1
done
[ -e "$cancel_file" ] && exit 0
sendevent /dev/input/event9 1 304 0
sendevent /dev/input/event9 1 305 0
sendevent /dev/input/event9 1 307 0
sendevent /dev/input/event9 1 308 0
sendevent /dev/input/event9 1 310 0
sendevent /dev/input/event9 1 311 0
sendevent /dev/input/event9 1 314 0
sendevent /dev/input/event9 1 315 0
sendevent /dev/input/event9 3 0 0
sendevent /dev/input/event9 3 1 0
sendevent /dev/input/event9 3 2 0
sendevent /dev/input/event9 3 5 0
sendevent /dev/input/event9 3 16 0
sendevent /dev/input/event9 3 17 0
sendevent /dev/input/event9 0 0 0
input keyevent 223
am force-stop com.thorium.preview
settings put system screen_brightness 0
settings put global stay_on_while_plugged_in 0
if [ -n "$idle_bounded" ] && [ "$(settings get system screen_off_timeout)" = "$idle_bounded" ]; then
    settings put system screen_off_timeout "$idle_before"
fi
echo "blanked device $(date +%s)"
