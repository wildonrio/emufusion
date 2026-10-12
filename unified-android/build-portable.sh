#!/bin/sh
# Complete one-APK qualification build; never silently drop a requested engine.
set -eu
PORTABLE_PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
if [ "$#" -ne 0 ]; then
    printf 'Usage: build-portable.sh (configuration uses LUCENT_ environment variables)\n' >&2
    exit 1
fi
for portable_flag in EMUFUSION_INCLUDE_EXPERIMENTAL_CORES \
        EMUFUSION_AUTOSELECT_EXPERIMENTAL_CORES EMUFUSION_INCLUDE_PHASE2_PPSSPP \
        EMUFUSION_INCLUDE_PHASE3_EDEN EMUFUSION_INCLUDE_PHASE3_CEMU \
        EMUFUSION_INCLUDE_PHASE3_APS3E EMUFUSION_REQUIRE_PORTABLE_BUNDLE; do
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
export EMUFUSION_REUSE_QUALIFICATION_CORES=${EMUFUSION_REUSE_QUALIFICATION_CORES:-1}
export EMUFUSION_REUSE_PHASE2_PPSSPP=${EMUFUSION_REUSE_PHASE2_PPSSPP:-1}
# The complete qualification profile must retain the repaired Android frontend.
# An absent generated kit fails in build.sh rather than reverting to the old
# 4 KiB libraries. Explicit paired inputs still permit isolated comparisons.
if [ -z "${EMUFUSION_SOURCE_FRONTEND_DIR:-}" ] && [ -z "${EMUFUSION_SOURCE_FRONTEND_LOCK:-}" ]; then
    export EMUFUSION_SOURCE_FRONTEND_DIR="$PORTABLE_PROJECT_DIR/build/source-frontend"
    export EMUFUSION_SOURCE_FRONTEND_LOCK="$PORTABLE_PROJECT_DIR/source-frontend-artifact-lock.json"
fi
if [ "${EMUFUSION_SIGNING_PROFILE:-debug}" = release ]; then
    if [ "${EMUFUSION_REQUIRE_16K_ALIGNMENT-1}" != 1 ]; then
        printf 'A portable release build cannot waive whole-APK 16 KiB alignment.\n' >&2
        exit 1
    fi
    export EMUFUSION_REQUIRE_16K_ALIGNMENT=1
fi
exec "$PORTABLE_PROJECT_DIR/build.sh"
