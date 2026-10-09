#!/bin/sh
# Complete one-APK qualification build; never silently drop a requested engine.
set -eu
PORTABLE_PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
if [ "$#" -ne 0 ]; then
    printf 'Usage: build-portable.sh (configuration uses LUCENT_ environment variables)\n' >&2
    exit 1
fi
for portable_flag in LUCENT_INCLUDE_EXPERIMENTAL_CORES \
        LUCENT_AUTOSELECT_EXPERIMENTAL_CORES LUCENT_INCLUDE_PHASE2_PPSSPP \
        LUCENT_INCLUDE_PHASE3_EDEN LUCENT_INCLUDE_PHASE3_CEMU \
        LUCENT_INCLUDE_PHASE3_APS3E LUCENT_REQUIRE_PORTABLE_BUNDLE; do
    eval "portable_value=\${$portable_flag-1}"
    if [ "$portable_value" != 1 ]; then
        printf 'Portable build requires %s=1; use build.sh only for deliberately reduced diagnostics.\n' \
            "$portable_flag" >&2
        exit 1
    fi
    export "$portable_flag=1"
done
# Existing staged artifacts still undergo the original identity/payload checks.
# Set either reuse flag to 0 when deliberately rebuilding the relevant cores.
export LUCENT_REUSE_QUALIFICATION_CORES=${LUCENT_REUSE_QUALIFICATION_CORES:-1}
export LUCENT_REUSE_PHASE2_PPSSPP=${LUCENT_REUSE_PHASE2_PPSSPP:-1}
# The complete qualification profile must retain the repaired Android frontend.
# An absent generated kit fails in build.sh rather than reverting to the old
# 4 KiB libraries. Explicit paired inputs still permit isolated comparisons.
if [ -z "${LUCENT_SOURCE_FRONTEND_DIR:-}" ] && [ -z "${LUCENT_SOURCE_FRONTEND_LOCK:-}" ]; then
    export LUCENT_SOURCE_FRONTEND_DIR="$PORTABLE_PROJECT_DIR/build/source-frontend"
    export LUCENT_SOURCE_FRONTEND_LOCK="$PORTABLE_PROJECT_DIR/source-frontend-artifact-lock.json"
fi
if [ "${LUCENT_SIGNING_PROFILE:-debug}" = release ]; then
    if [ "${LUCENT_REQUIRE_16K_ALIGNMENT-1}" != 1 ]; then
        printf 'A portable release build cannot waive whole-APK 16 KiB alignment.\n' >&2
        exit 1
    fi
    export LUCENT_REQUIRE_16K_ALIGNMENT=1
fi
exec "$PORTABLE_PROJECT_DIR/build.sh"
