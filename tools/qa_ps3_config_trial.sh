#!/bin/sh
# One temporary Accurate SPU DMA trial, with host and detached device rollback.
# Prepare both evidence YAMLs first. This arms the trial but never launches a game.
set -eu
evidence=${1:?absolute evidence directory required}
case "$evidence" in /*) ;; *) exit 2 ;; esac
test -f "$evidence/config-candidate.yml"
test -f "$evidence/config-before.yml"
test ! -e "$evidence/stop-test"
test ! -e "$evidence/watchdog-ended"
test ! -e "$evidence/trial-ready"
tools_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Overrides are for host-only fake-ADB tests; the serial and package stay fixed.
adb=${PS3_TRIAL_ADB:-/Users/tyleryoung/.codex/tools/android-platform-tools/adb}
oled_guard=${PS3_TRIAL_OLED_GUARD:-$tools_dir/qa_oled_timeout.sh}
# Binary comparison deliberately preserves CRLF and the final-newline state.
# Reject extra edits, an already-enabled value, or ambiguous duplicate keys.
perl -0777 -e '
    sub bytes { open my $f, "<:raw", $_[0] or die "$!\n"; local $/; return <$f>; }
    my ($before, $candidate) = map { bytes($_) } @ARGV;
    my $keys = () = $before =~ /^[\t ]*Accurate SPU DMA:/mg;
    die "Expected one Accurate SPU DMA key\n" unless $keys == 1;
    my $changed = $before =~ s/^([\t ]*Accurate SPU DMA: )false(?=\r?$)/${1}true/m;
    die "Expected Accurate SPU DMA: false\n" unless $changed == 1;
    die "Candidate must change only Accurate SPU DMA false to true\n" unless $before eq $candidate;
' "$evidence/config-before.yml" "$evidence/config-candidate.yml"
"$adb" -s 427c87b2 shell 'if pidof com.thorium.preview >/dev/null; then exit 1; fi'
backup_dir=$("$adb" -s 427c87b2 shell run-as com.thorium.preview mktemp -d cache/qa-ps3-config-XXXXXX | tr -d '\r')
case "$backup_dir" in cache/qa-ps3-config-??????) ;; *) exit 2 ;; esac
case "${backup_dir#cache/qa-ps3-config-}" in *[!A-Za-z0-9]*) exit 2 ;; esac
printf '%s\n' "$backup_dir" > "$evidence/config-backup-dir.txt"
"$adb" -s 427c87b2 shell run-as com.thorium.preview cp app_engine-system/aps3e/config/config.yml "$backup_dir/config-before.yml"
"$adb" -s 427c87b2 exec-out run-as com.thorium.preview cat "$backup_dir/config-before.yml" > "$evidence/device-backup.yml"
cmp "$evidence/device-backup.yml" "$evidence/config-before.yml"
guard_pid=
watchdog_started=false
restore() {
    trial_status=$?
    trap - EXIT HUP INT TERM
    set +e
    if [ -n "$guard_pid" ]; then
        kill -TERM "$guard_pid" 2>/dev/null
        wait "$guard_pid" 2>/dev/null
    fi
    restored=true
    if [ "$watchdog_started" = true ]; then
        restored=false
        "$adb" -s 427c87b2 shell run-as com.thorium.preview touch "$backup_dir/restore-request"
        for attempt in 1 2 3 4 5 6 7 8 9 10; do
            if "$adb" -s 427c87b2 shell run-as com.thorium.preview test -f "$backup_dir/restored"; then
                restored=true
                break
            fi
            sleep 1
        done
    fi
    if [ "$restored" = true ] &&
       "$adb" -s 427c87b2 exec-out run-as com.thorium.preview cat app_engine-system/aps3e/config/config.yml > "$evidence/config-restored.yml" &&
       cmp "$evidence/config-before.yml" "$evidence/config-restored.yml"; then
        printf '%s\n' 'Original PS3 configuration restored and byte-verified.'
    else
        printf '%s\n' 'Host restoration failed; detached device rollback remains armed. Do not start another trial.' >&2
        trial_status=1
    fi
    exit "$trial_status"
}
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
"$adb" -s 427c87b2 push "$tools_dir/qa_ps3_config_restore_device.sh" /data/local/tmp/qa_ps3_config_restore_device.sh
"$adb" -s 427c87b2 push "$evidence/config-candidate.yml" /data/local/tmp/qa_ps3_config_candidate.yml
"$adb" -s 427c87b2 shell run-as com.thorium.preview cp /data/local/tmp/qa_ps3_config_candidate.yml "$backup_dir/config-candidate.yml"
"$adb" -s 427c87b2 exec-out run-as com.thorium.preview cat "$backup_dir/config-candidate.yml" > "$evidence/config-staged.yml"
cmp "$evidence/config-candidate.yml" "$evidence/config-staged.yml"
# The detached process alone applies and restores the active config. A delayed
# host command can never apply candidate bytes after that process has retired.
watchdog_started=true
"$adb" -s 427c87b2 shell "nohup sh /data/local/tmp/qa_ps3_config_restore_device.sh '$backup_dir' > /data/local/tmp/qa_ps3_config_restore.log 2>&1 < /dev/null &"
# Do not advertise readiness until the detached process confirms application.
armed=false
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if "$adb" -s 427c87b2 shell run-as com.thorium.preview test -f "$backup_dir/armed"; then
        armed=true
        break
    fi
    sleep 1
done
test "$armed" = true
"$adb" -s 427c87b2 exec-out run-as com.thorium.preview cat app_engine-system/aps3e/config/config.yml > "$evidence/config-applied.yml"
cmp "$evidence/config-candidate.yml" "$evidence/config-applied.yml"
if "$adb" -s 427c87b2 shell run-as com.thorium.preview test -f "$backup_dir/restored"; then exit 1; fi
sh "$oled_guard" "$evidence" 600 &
guard_pid=$!
touch "$evidence/trial-ready"
printf '%s\n' 'PS3 Accurate SPU DMA trial ready; detached rollback deadline is 600 seconds from arming.'
guard_status=0
wait "$guard_pid" || guard_status=$?
guard_pid=
exit "$guard_status"
