#!/system/bin/sh
# Detached owner of application AND restoration, outside the app process.
# It never touches saves or firmware. Host loss cannot cause a later host copy.
set -eu
backup_dir=${1:?app-relative QA backup directory required}
case "$backup_dir" in cache/qa-ps3-config-??????) ;; *) exit 2 ;; esac
case "${backup_dir#cache/qa-ps3-config-}" in *[!A-Za-z0-9]*) exit 2 ;; esac
run-as com.thorium.preview test -f "$backup_dir/config-before.yml"
run-as com.thorium.preview test -f "$backup_dir/config-candidate.yml"
restore() {
    trial_status=$?
    trap - EXIT HUP INT TERM
    set +e
    # Keep the only rollback owner alive if a transient device command fails.
    while :; do
        if am force-stop com.thorium.preview &&
           run-as com.thorium.preview cp "$backup_dir/config-before.yml" app_engine-system/aps3e/config/config.yml &&
           run-as com.thorium.preview cmp "$backup_dir/config-before.yml" app_engine-system/aps3e/config/config.yml &&
           run-as com.thorium.preview touch "$backup_dir/restored"; then
            input keyevent 223
            exit "$trial_status"
        fi
        sleep 1
    done
}
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
if run-as com.thorium.preview test -f "$backup_dir/restore-request"; then exit 0; fi
run-as com.thorium.preview cp "$backup_dir/config-candidate.yml" app_engine-system/aps3e/config/config.yml
run-as com.thorium.preview cmp "$backup_dir/config-candidate.yml" app_engine-system/aps3e/config/config.yml
deadline=$(( $(date +%s) + 600 ))
run-as com.thorium.preview touch "$backup_dir/armed"
while [ "$(date +%s)" -lt "$deadline" ]; do
    if run-as com.thorium.preview test -f "$backup_dir/restore-request"; then exit 0; fi
    sleep 1
done
