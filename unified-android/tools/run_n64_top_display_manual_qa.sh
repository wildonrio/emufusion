#!/bin/bash
set -euo pipefail

# This harness exists only for the final human-observed N64 top-display gate.
# It never manufactures a manual PASS. The observer's verdict must be recorded
# separately and bound to the resulting immutable evidence after the run.

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
ADB=${ADB:-/Users/tyleryoung/.codex/tools/android-platform-tools/adb}
SERIAL=${ANDROID_SERIAL:-427c87b2}
APK=${1:-}
OUTPUT=${2:-}
MATRIX="$ROOT/unified-android/tools/runtime-acceptance-matrix.json"

if [ "${EMUFUSION_OWNER_WATCHING_TOP:-}" != YES ]; then
    printf '%s\n' \
        'Refusing to light Thor: set EMUFUSION_OWNER_WATCHING_TOP=YES only while the owner is watching the top display.' >&2
    exit 2
fi
if [ -z "$APK" ] || [ -z "$OUTPUT" ]; then
    printf 'usage: %s APK OUTPUT_DIRECTORY\n' "$0" >&2
    exit 2
fi
if [ ! -f "$APK" ]; then
    printf 'APK does not exist: %s\n' "$APK" >&2
    exit 2
fi

mkdir -p "$OUTPUT"
APK=$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")
OUTPUT=$(cd "$OUTPUT" && pwd)
EXPECTED_SHA256=$(shasum -a 256 "$APK" | awk '{print $1}')
ORIGINAL_MIN_REFRESH_RATE=
ORIGINAL_PEAK_REFRESH_RATE=
ORIGINAL_USB_NOTICE=

device() { "$ADB" -s "$SERIAL" "$@"; }

read_setting() {
    device shell settings get "$1" "$2" 2>/dev/null | tr -d '\r'
}

restore_setting() {
    local namespace=$1 key=$2 value=$3
    if [ -n "$value" ] && [ "$value" != null ]; then
        device shell settings put "$namespace" "$key" "$value" \
            >/dev/null 2>&1 || true
    else
        device shell settings delete "$namespace" "$key" \
            >/dev/null 2>&1 || true
    fi
}

clear_framegen_globals() {
    local key
    while IFS= read -r key; do
        case "$key" in
            emufusion_framegen*|thorium_rife*|thorium_lsfg*)
                device shell settings delete global "$key" \
                    >/dev/null 2>&1 || true
                ;;
        esac
    done < <(device shell settings list global 2>/dev/null | \
        sed 's/=.*//' | tr -d '\r')
}

blacken() {
    device shell am force-stop com.thorium.preview >/dev/null 2>&1 || true
    device shell am force-stop org.pegasus_frontend >/dev/null 2>&1 || true
    clear_framegen_globals
    device shell settings put system screen_brightness 0 >/dev/null 2>&1 || true
    # Thor's DisplayManager can deadlock if its live brightness/mode APIs are
    # mutated while both OLEDs are already dark. Put the device to sleep
    # instead; hardware backlight verification below remains authoritative.
    device shell input keyevent 223 >/dev/null 2>&1 || true
}

verify_black() {
    local p0 p1
    p0=$(device shell cat \
        /sys/class/backlight/panel0-backlight/actual_brightness 2>/dev/null | \
        tr -d '\r')
    p1=$(device shell cat \
        /sys/class/backlight/panel1-backlight/actual_brightness 2>/dev/null | \
        tr -d '\r')
    printf 'panel0_actual=%s\npanel1_actual=%s\n' "$p0" "$p1" | \
        tee "$OUTPUT/final-oled-state.txt"
    [ "$p0" = 0 ] && [ "$p1" = 0 ]
}

verify_top_lit() {
    local p0=0 p1=0
    local unused
    # Thor firmware does not reliably honor injected WAKEUP/POWER key events
    # from ADB while asleep. Give the present owner a bounded window to press
    # the physical power button, while refusing to proceed unless sysfs proves
    # that the top OLED actually illuminated.
    for unused in $(seq 1 600); do
        p0=$(device shell cat \
            /sys/class/backlight/panel0-backlight/actual_brightness \
            2>/dev/null | tr -d '\r')
        p1=$(device shell cat \
            /sys/class/backlight/panel1-backlight/actual_brightness \
            2>/dev/null | tr -d '\r')
        [ "$p0" -gt 0 ] && break
        sleep 0.05
    done
    printf 'panel0_actual=%s\npanel1_actual=%s\n' "$p0" "$p1" | \
        tee "$OUTPUT/initial-oled-lit-state.txt"
    [ "$p0" -gt 0 ]
}

cleanup() {
    trap - EXIT INT TERM HUP
    blacken
    restore_setting system min_refresh_rate "$ORIGINAL_MIN_REFRESH_RATE"
    restore_setting system peak_refresh_rate "$ORIGINAL_PEAK_REFRESH_RATE"
    restore_setting system notice_me_when_usb_connected "$ORIGINAL_USB_NOTICE"
    verify_black
}

device wait-for-device
ORIGINAL_MIN_REFRESH_RATE=$(read_setting system min_refresh_rate)
ORIGINAL_PEAK_REFRESH_RATE=$(read_setting system peak_refresh_rate)
ORIGINAL_USB_NOTICE=$(read_setting system notice_me_when_usb_connected)

# The reads above do not mutate the device. Install the fail-safe before the
# first mutation and before any command is permitted to emit OLED light.
trap cleanup EXIT INT TERM HUP
blacken
verify_black

printf '%s  %s\n' "$EXPECTED_SHA256" "$APK" > \
    "$OUTPUT/requested-apk-sha256.txt"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$OUTPUT/manual-observation-start-utc.txt"
device install -r "$APK" | tee "$OUTPUT/install.txt"

clear_framegen_globals
device shell settings put global emufusion_framegen_rife_qualification 1
device shell settings put system notice_me_when_usb_connected 0
device shell settings put system min_refresh_rate 120.00001
device shell settings put system peak_refresh_rate 120.00001

# This is the only light-emitting transition in the harness. It occurs after
# installation, configuration, cleanup trapping, and explicit observer opt-in.
device shell settings put system screen_brightness 8
device shell input keyevent 224
printf '%s\n' \
    'WAKE WINDOW: if the top OLED is still black, press Thor physical POWER once now.'
verify_top_lit

stable=0
for unused in $(seq 1 100); do
    if device shell dumpsys display | grep -q \
            'width=1080, height=1920,.*refreshRate=120\.0'; then
        stable=$((stable + 1))
        [ "$stable" -ge 20 ] && break
    else
        stable=0
    fi
    sleep 0.1
done
[ "$stable" -ge 20 ]

python3 "$ROOT/unified-android/tools/run_runtime_acceptance_qa.py" \
    --serial "$SERIAL" \
    --adb "$ADB" \
    --apk "$APK" \
    --expected-sha256 "$EXPECTED_SHA256" \
    --output "$OUTPUT" \
    --matrix "$MATRIX" \
    --system n64 \
    --titles-per-system 3 \
    --skip-list-view-smoke \
    --stop-on-first-failure \
    --allow-physical-thor \
    --already-installed

date -u '+%Y-%m-%dT%H:%M:%SZ' > "$OUTPUT/manual-observation-end-utc.txt"
printf '%s\n' \
    'PENDING: no manual visual verdict is created by the automated harness.' > \
    "$OUTPUT/manual-observer-verdict.txt"
