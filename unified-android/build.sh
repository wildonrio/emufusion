#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$PROJECT_DIR/.." && pwd)
SDK_DIR=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk}}
BUILD_TOOLS_VERSION=${BUILD_TOOLS_VERSION:-36.0.0}
ANDROID_PLATFORM=${ANDROID_PLATFORM:-android-36}
BUILD_TOOLS="$SDK_DIR/build-tools/$BUILD_TOOLS_VERSION"
ANDROID_JAR="$SDK_DIR/platforms/$ANDROID_PLATFORM/android.jar"
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
APKTOOL=${APKTOOL:-/opt/homebrew/bin/apktool}
BUILD_DIR="$PROJECT_DIR/build"
BUILD_LOCK="$BUILD_DIR/.lucent-build-lock"
VERSION_NAME=3.2.20
VERSION_CODE=94

case "${LUCENT_REQUIRE_PORTABLE_BUNDLE:-0}" in
    0|1) ;;
    *) printf 'LUCENT_REQUIRE_PORTABLE_BUNDLE must be 0 or 1\n' >&2; exit 1 ;;
esac

# Explicit diagnostic opt-in; a typo must not silently disable heap evidence.
case "${LUCENT_GWP_ASAN:-0}" in
    0|1) ;;
    *) printf 'LUCENT_GWP_ASAN must be 0 or 1\n' >&2; exit 1 ;;
esac
case "${LUCENT_MALLOC_DEBUG:-0}" in
    0|1) ;;
    *) printf 'LUCENT_MALLOC_DEBUG must be 0 or 1\n' >&2; exit 1 ;;
esac
if [ "${LUCENT_GWP_ASAN:-0}" = 1 ] && [ "${LUCENT_MALLOC_DEBUG:-0}" = 1 ]; then
    printf 'Select one heap diagnostic per build, not GWP-ASan and malloc_debug together.\n' >&2
    exit 1
fi
if [ -n "${LUCENT_MALLOC_FREE_TRACE_LIBRARY:-}" ] && [ "${LUCENT_MALLOC_DEBUG:-0}" != 1 ]; then
    printf 'LUCENT_MALLOC_FREE_TRACE_LIBRARY requires LUCENT_MALLOC_DEBUG=1\n' >&2
    exit 1
fi

# An earlier build was invoked with the unprefixed names below, silently
# defaulted every flag to 0, and produced a zero-core APK that passed its
# gates. Refuse the build outright when a caller sets an unprefixed name.
for stray_flag in INCLUDE_EXPERIMENTAL_CORES AUTOSELECT_EXPERIMENTAL_CORES \
        REUSE_QUALIFICATION_CORES INCLUDE_PHASE2_PPSSPP REUSE_PHASE2_PPSSPP \
        INCLUDE_PHASE3_EDEN INCLUDE_PHASE3_CEMU INCLUDE_PHASE3_APS3E \
        INCLUDE_RIFE_FRAMEGEN INCLUDE_LSFG_FRAMEGEN INTERNAL_LSFG_PLUS \
        KEYSTORE STORE_PASS KEY_PASS KEY_ALIAS; do
    if eval "[ \"\${$stray_flag+set}\" = set ]"; then
        printf 'Refusing to build: %s is set but this build only reads LUCENT_%s\n' \
            "$stray_flag" "$stray_flag" >&2
        exit 1
    fi
done
# A misspelled LUCENT_ flag (LUCENT_INCLUDE_EXPERIMENTAL_CORE, ...) would be
# just as silently ignored as an unprefixed one. Reject every core-selection
# style LUCENT_ name this build does not actually read.
for lucent_flag in $(env | LC_ALL=C sed -n 's/^\(LUCENT_[A-Za-z0-9_]*\)=.*/\1/p'); do
    case "$lucent_flag" in
        LUCENT_INCLUDE_EXPERIMENTAL_CORES) ;;
        LUCENT_AUTOSELECT_EXPERIMENTAL_CORES) ;;
        LUCENT_REUSE_QUALIFICATION_CORES) ;;
        LUCENT_INCLUDE_PHASE2_PPSSPP) ;;
        LUCENT_REUSE_PHASE2_PPSSPP) ;;
        LUCENT_INCLUDE_PHASE3_EDEN) ;;
        LUCENT_INCLUDE_PHASE3_CEMU) ;;
        LUCENT_INCLUDE_PHASE3_APS3E) ;;
        LUCENT_INCLUDE_RIFE_FRAMEGEN) ;;
        LUCENT_INCLUDE_LSFG_FRAMEGEN) ;;
        LUCENT_INCLUDE_*|LUCENT_REUSE_*|LUCENT_AUTOSELECT_*)
            printf 'Refusing to build: unknown build flag %s (known flags: LUCENT_INCLUDE_EXPERIMENTAL_CORES LUCENT_AUTOSELECT_EXPERIMENTAL_CORES LUCENT_REUSE_QUALIFICATION_CORES LUCENT_INCLUDE_PHASE2_PPSSPP LUCENT_REUSE_PHASE2_PPSSPP LUCENT_INCLUDE_PHASE3_EDEN LUCENT_INCLUDE_PHASE3_CEMU LUCENT_INCLUDE_PHASE3_APS3E LUCENT_INCLUDE_RIFE_FRAMEGEN LUCENT_INCLUDE_LSFG_FRAMEGEN)\n' \
                "$lucent_flag" >&2
            exit 1
            ;;
        *) ;;
    esac
done

INCLUDE_EXPERIMENTAL_CORES=${LUCENT_INCLUDE_EXPERIMENTAL_CORES:-0}
AUTOSELECT_EXPERIMENTAL_CORES=${LUCENT_AUTOSELECT_EXPERIMENTAL_CORES:-0}
REUSE_QUALIFICATION_CORES=${LUCENT_REUSE_QUALIFICATION_CORES:-0}
# The Phase 2 bundle contains the in-process Dolphin runtime used by the normal
# GameCube/Wii route. It is included by default so a normal build can never
# degrade those systems to a standalone emulator. Set the flag to 0 only for a
# deliberately stripped diagnostic package; routing then fails closed unless
# the user explicitly selected External.
INCLUDE_PHASE2_PPSSPP=${LUCENT_INCLUDE_PHASE2_PPSSPP:-1}
REUSE_PHASE2_PPSSPP=${LUCENT_REUSE_PHASE2_PPSSPP:-0}
# Optional debug-only candidate pair; never changes the normal core staging.
ARMSX2_CORE_DIR=${LUCENT_ARMSX2_QUALIFICATION_DIR:-$ROOT_DIR/engines/build/arm64-v8a}
# Phase 3 packages an already-built in-process native adapter; this build never
# compiles one. There is no LUCENT_REUSE_ flag because there is nothing to
# rebuild: the staged artifact is the only input and its hash is the gate.
INCLUDE_PHASE3_EDEN=${LUCENT_INCLUDE_PHASE3_EDEN:-0}
PHASE3_EDEN_ADAPTER="$ROOT_DIR/engines/build/arm64-v8a/liblucent_native_adapter_eden.so"
# Eden does not open libvulkan itself on arm64: it takes the driver library the
# frontend loaded, and that load goes through adrenotools, which ALWAYS builds a
# linker namespace over the hook directory and dlopens these two by name --
# even when no custom driver is requested. Without them the driver handle is
# null and the failure surfaces much later as the misleading "Vulkan library not
# available". They are packaged beside the adapter so the app's own native
# library directory is a valid hook directory.
PHASE3_EDEN_HOOK_IMPL="$ROOT_DIR/engines/build/arm64-v8a/libhook_impl.so"
PHASE3_EDEN_MAIN_HOOK="$ROOT_DIR/engines/build/arm64-v8a/libmain_hook.so"
# Cemu (Wii U) needs no hook pair: it reaches adrenotools only for a custom
# driver and plain-dlopens libvulkan otherwise. It also needs no keys, no
# firmware, and no Java shim classes, so this is just the adapter.
INCLUDE_PHASE3_CEMU=${LUCENT_INCLUDE_PHASE3_CEMU:-0}
PHASE3_CEMU_ADAPTER="$ROOT_DIR/engines/build/arm64-v8a/liblucent_native_adapter_cemu.so"
# PS3 is a built-in EmuFusion system, not an external-app fallback. The pinned,
# hash-verified adapter is therefore part of normal builds; an explicit 0 is
# retained only for narrow packaging diagnostics.
INCLUDE_PHASE3_APS3E=${LUCENT_INCLUDE_PHASE3_APS3E:-1}
INCLUDE_RIFE_FRAMEGEN=${LUCENT_INCLUDE_RIFE_FRAMEGEN:-0}
INCLUDE_LSFG_FRAMEGEN=${LUCENT_INCLUDE_LSFG_FRAMEGEN:-0}
INTERNAL_LSFG_PLUS=${LUCENT_INTERNAL_LSFG_PLUS:-0}
LSFG_EXPERIMENT_DIR="$ROOT_DIR/experiments/lsfg-vulkan-android-inprocess"
LSFG_WRAPPER_DIR=${LUCENT_LSFG_WRAPPER_DIR:-}
LSFG_NATIVE_SOURCE="$PROJECT_DIR/lsfg-qualification-native"
LSFG_NATIVE_BUILD="$BUILD_DIR/lsfg-qualification-native"
LSFG_NATIVE_LIBRARY="$LSFG_NATIVE_BUILD/liblucent_lsfg_qualification.so"
LSFG_CMAKE="$SDK_DIR/cmake/3.22.1/bin/cmake"
LSFG_NINJA="$SDK_DIR/cmake/3.22.1/bin/ninja"
LSFG_NDK="$SDK_DIR/ndk/27.0.12077973"
RIFE_EXPERIMENT_DIR="$ROOT_DIR/experiments/rife-ncnn-vulkan-android"
RIFE_BENCHMARK_DIR="$RIFE_EXPERIMENT_DIR/android-benchmark"
RIFE_APP_APK="$RIFE_BENCHMARK_DIR/app/build/outputs/apk/release/app-release-unsigned.apk"
RIFE_TEST_APK="$RIFE_BENCHMARK_DIR/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
RIFE_PREPARED_MANIFEST="$RIFE_BENCHMARK_DIR/build/upstream-prepared-v23-flow-only/prepared-manifest.json"
RIFE_SPATIAL_DISPATCH=${LUCENT_RIFE_SPATIAL_DISPATCH:-0}
case "$RIFE_SPATIAL_DISPATCH" in
    0) ;;
    1) RIFE_PREPARED_MANIFEST="$RIFE_BENCHMARK_DIR/build/upstream-prepared-v23-flow-only-spatial/prepared-manifest.json" ;;
    *) printf 'LUCENT_RIFE_SPATIAL_DISPATCH must be 0 or 1\n' >&2; exit 1 ;;
esac
RIFE_CACHE_DIR="$RIFE_BENCHMARK_DIR/build/upstream-cache"
RIFE_HOST_RECORD="$PROJECT_DIR/build/rife-framegen-host-artifacts.json"
RIFE_GRADLE=${RIFE_GRADLE:-/opt/homebrew/bin/gradle}
RIFE_LLVM_READELF="$SDK_DIR/ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-readelf"
PHASE3_APS3E_ADAPTER="$ROOT_DIR/engines/build/arm64-v8a/liblucent_native_adapter_aps3e.so"
DEPS_DIR="$BUILD_DIR/deps"
COMMONS_COMPRESS_JAR="$DEPS_DIR/commons-compress-1.21.jar"
XZ_JAR="$DEPS_DIR/xz-1.9.jar"
# Alpha multiplayer transport: a WebSocket client for the presence/
# matchmaking backend, and WebRTC for the actual peer-to-peer game-input
# DataChannel. Neither has ever been vendored here before -- this build has
# no Gradle/AAR handling at all, so the WebRTC AAR is fetched like any other
# hash-pinned dependency below and then unpacked by hand (see
# WEBRTC_AAR_STAMP) into the same classes-jar/native-.so shapes the rest of
# this script already knows how to place.
NV_WEBSOCKET_CLIENT_JAR="$DEPS_DIR/nv-websocket-client-2.14.jar"
WEBRTC_AAR="$DEPS_DIR/webrtc-android-150.7871.01.aar"
WEBRTC_AAR_EXTRACTED="$DEPS_DIR/webrtc-android-150.7871.01"
WEBRTC_CLASSES_JAR="$WEBRTC_AAR_EXTRACTED/classes.jar"
WEBRTC_NATIVE_SO="$WEBRTC_AAR_EXTRACTED/jni/arm64-v8a/libjingle_peerconnection_so.so"
BASE_NAME=pegasus-fe_alpha16-105-g6b322063_android64.apk
BASE_URL="https://raw.githubusercontent.com/mmatyas/pegasus-deploy-staging/continuous-android64/$BASE_NAME"
BASE_SHA256=e595be198bfd21c1855eaf563d5af0deae9c9601e6efb195ed299f2065287c67
BASE_APK=${PEGASUS_BASE_APK:-$BUILD_DIR/$BASE_NAME}
SOURCE_FRONTEND_DIR=${LUCENT_SOURCE_FRONTEND_DIR:-}
SOURCE_FRONTEND_LOCK=${LUCENT_SOURCE_FRONTEND_LOCK:-}
if [ -n "$SOURCE_FRONTEND_DIR" ] || [ -n "$SOURCE_FRONTEND_LOCK" ]; then
    if [ -z "$SOURCE_FRONTEND_DIR" ] || [ -z "$SOURCE_FRONTEND_LOCK" ]; then
        printf 'Source frontend qualification requires both LUCENT_SOURCE_FRONTEND_DIR and LUCENT_SOURCE_FRONTEND_LOCK\n' >&2
        exit 1
    fi
    if [ "${LUCENT_SIGNING_PROFILE:-debug}" = release ]; then
        printf 'Source frontend migration is not release-qualified yet\n' >&2
        exit 1
    fi
fi

export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"
export PATH

# The APK assembly directory is intentionally shared so large verified inputs
# stay cached. Refuse concurrent writers instead of allowing two builds to
# delete or replace each other's decoded resources and dex output.
mkdir -p "$BUILD_DIR"
if ! mkdir "$BUILD_LOCK" 2>/dev/null; then
    printf 'Another Lucent Android build is using %s\n' "$BUILD_DIR" >&2
    exit 1
fi
printf '%s\n' "$$" > "$BUILD_LOCK/pid"
cleanup_build_lock() {
    # These are always regenerated; a failed/signalled build must not retain
    # two extra full APKs. Keep signed outputs, decoded inputs and diagnostics.
    rm -f "$BUILD_DIR/lucent-unified-unsigned.apk" "$BUILD_DIR/lucent-unified-aligned.apk"
    rm -f "$BUILD_LOCK/pid"
    rmdir "$BUILD_LOCK" 2>/dev/null || true
}
trap cleanup_build_lock 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 131' 3
trap 'exit 143' 15

# Bound historical APK disk use before creating another large package. The
# retention tool shares this lock and protects pinned rollback/release hashes.
python3 "$PROJECT_DIR/tools/prune_build_apks.py" --apply --retired-diagnostics \
    --build-lock-owner "$$" >&2

if [ "$AUTOSELECT_EXPERIMENTAL_CORES" = 1 ] &&
        [ "$INCLUDE_EXPERIMENTAL_CORES" != 1 ]; then
    printf 'Experimental auto-selection requires LUCENT_INCLUDE_EXPERIMENTAL_CORES=1\n' >&2
    exit 1
fi

case "$INCLUDE_PHASE2_PPSSPP:$REUSE_PHASE2_PPSSPP" in
    0:0|0:1|1:0|1:1) ;;
    *) printf 'Phase 2 PPSSPP flags must be 0 or 1\n' >&2; exit 1 ;;
esac
if [ "$REUSE_PHASE2_PPSSPP" = 1 ] && [ "$INCLUDE_PHASE2_PPSSPP" != 1 ]; then
    printf 'Reusing Phase 2 PPSSPP requires LUCENT_INCLUDE_PHASE2_PPSSPP=1\n' >&2
    exit 1
fi

# BEGIN PS2 qualification input preflight
if [ -n "${LUCENT_ARMSX2_QUALIFICATION_DIR:-}" ]; then
    if [ "${LUCENT_SIGNING_PROFILE:-debug}" != debug ] ||
            [ "$INCLUDE_PHASE2_PPSSPP:$REUSE_PHASE2_PPSSPP" != 1:1 ]; then
        printf 'PS2 candidate inputs require debug signing and Phase 2 reuse\n' >&2
        exit 1
    fi
    case "$ARMSX2_CORE_DIR" in
        /*) ;;
        *) printf 'PS2 candidate directory must be absolute\n' >&2; exit 1 ;;
    esac
fi
if [ "$INCLUDE_PHASE2_PPSSPP:$REUSE_PHASE2_PPSSPP" = 1:1 ]; then
    # Fail before fetching dependencies or rebuilding any host output.
    python3 "$ROOT_DIR/engines/tools/armsx2_build_identity.py" verify \
        --root "$ROOT_DIR" --pages 4096 \
        --core "$ARMSX2_CORE_DIR/armsx2_libretro.so"
    python3 "$ROOT_DIR/engines/tools/armsx2_build_identity.py" verify \
        --root "$ROOT_DIR" --pages 16384 \
        --core "$ARMSX2_CORE_DIR/armsx2_16k_libretro.so"
fi
# END PS2 qualification input preflight

case "$INCLUDE_PHASE3_EDEN" in
    0|1) ;;
    *) printf 'LUCENT_INCLUDE_PHASE3_EDEN must be 0 or 1\n' >&2; exit 1 ;;
esac
if [ "$INCLUDE_PHASE3_EDEN" = 1 ] && [ ! -f "$PHASE3_EDEN_ADAPTER" ]; then
    # Fail closed before any APK work: an opted-in Phase 3 build that silently
    # produced an APK without the adapter would look qualified and route Switch
    # externally with no signal at all.
    printf 'LUCENT_INCLUDE_PHASE3_EDEN=1 requires the staged adapter: %s\n' \
        "$PHASE3_EDEN_ADAPTER" >&2
    exit 1
fi
if [ "$INCLUDE_PHASE3_EDEN" = 1 ]; then
    # Same fail-closed reasoning: shipping the adapter without its hook pair
    # produces an APK that installs, routes Switch INTERNAL, and then cannot
    # create a GPU. Better to refuse the build than to ship that.
    for phase3_hook in "$PHASE3_EDEN_HOOK_IMPL" "$PHASE3_EDEN_MAIN_HOOK"; do
        if [ ! -f "$phase3_hook" ]; then
            printf 'LUCENT_INCLUDE_PHASE3_EDEN=1 requires the adrenotools hook library: %s\n' \
                "$phase3_hook" >&2
            exit 1
        fi
    done
fi
case "$INCLUDE_PHASE3_CEMU" in
    0|1) ;;
    *) printf 'LUCENT_INCLUDE_PHASE3_CEMU must be 0 or 1\n' >&2; exit 1 ;;
esac
if [ "$INCLUDE_PHASE3_CEMU" = 1 ] && [ ! -f "$PHASE3_CEMU_ADAPTER" ]; then
    # Same fail-closed rule as Eden: an opted-in build with no adapter would
    # look qualified and silently route Wii U externally.
    printf 'LUCENT_INCLUDE_PHASE3_CEMU=1 requires the staged adapter: %s\n' \
        "$PHASE3_CEMU_ADAPTER" >&2
    exit 1
fi
if [ "$INCLUDE_PHASE3_CEMU" = 1 ]; then
    # Source changes tested in derivative APKs must reach the normal build.
    # A self-consistent old artifact hash alone cannot establish that identity.
    python3 "$ROOT_DIR/engines/tools/cemu_build_identity.py" \
        --root "$ROOT_DIR" --core "$PHASE3_CEMU_ADAPTER"
fi
case "$INCLUDE_PHASE3_APS3E" in
    0|1) ;;
    *) printf 'LUCENT_INCLUDE_PHASE3_APS3E must be 0 or 1\n' >&2; exit 1 ;;
esac
if [ "$INCLUDE_PHASE3_APS3E" = 1 ] && [ ! -f "$PHASE3_APS3E_ADAPTER" ]; then
    printf 'LUCENT_INCLUDE_PHASE3_APS3E=1 requires the staged adapter: %s\n' \
        "$PHASE3_APS3E_ADAPTER" >&2
    exit 1
fi
case "$INCLUDE_RIFE_FRAMEGEN" in
    0|1) ;;
    *) printf 'LUCENT_INCLUDE_RIFE_FRAMEGEN must be 0 or 1\n' >&2; exit 1 ;;
esac
case "$INCLUDE_LSFG_FRAMEGEN" in
    0|1) ;;
    *) printf 'LUCENT_INCLUDE_LSFG_FRAMEGEN must be 0 or 1\n' >&2; exit 1 ;;
esac
case "$INTERNAL_LSFG_PLUS" in
    0|1) ;;
    *) printf 'LUCENT_INTERNAL_LSFG_PLUS must be 0 or 1\n' >&2; exit 1 ;;
esac
if [ "$INTERNAL_LSFG_PLUS" = 1 ] && [ "$INCLUDE_LSFG_FRAMEGEN" != 1 ]; then
    printf 'LUCENT_INTERNAL_LSFG_PLUS=1 requires LUCENT_INCLUDE_LSFG_FRAMEGEN=1\n' >&2
    exit 1
fi
if [ "$INCLUDE_RIFE_FRAMEGEN" = 1 ] && [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then
    printf 'RIFE and LSFG qualification payloads are mutually exclusive\n' >&2
    exit 1
fi

if [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then
    if [ -z "$LSFG_WRAPPER_DIR" ] || [ ! -d "$LSFG_WRAPPER_DIR" ]; then
        printf 'LUCENT_INCLUDE_LSFG_FRAMEGEN=1 requires LUCENT_LSFG_WRAPPER_DIR\n' >&2
        exit 1
    fi
    for lsfg_tool in "$LSFG_CMAKE" "$LSFG_NINJA"; do
        if [ ! -x "$lsfg_tool" ]; then
            printf 'LSFG qualification requires executable: %s\n' "$lsfg_tool" >&2
            exit 1
        fi
    done
    python3 "$LSFG_EXPERIMENT_DIR/tools/verify_patched_checkout.py" \
        --checkout "$LSFG_WRAPPER_DIR" >/dev/null
    python3 "$LSFG_EXPERIMENT_DIR/tools/verify_nonblocking_patch.py" \
        --checkout "$LSFG_WRAPPER_DIR" >/dev/null
    python3 "$LSFG_EXPERIMENT_DIR/tools/verify_owned_wsi_setup_source.py" \
        --native-dir "$LSFG_NATIVE_SOURCE" >/dev/null
    "$LSFG_CMAKE" -S "$LSFG_NATIVE_SOURCE" -B "$LSFG_NATIVE_BUILD" -G Ninja \
        -DCMAKE_MAKE_PROGRAM="$LSFG_NINJA" \
        -DCMAKE_TOOLCHAIN_FILE="$LSFG_NDK/build/cmake/android.toolchain.cmake" \
        -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-29 \
        -DEMUFUSION_LSFG_PIXEL_PROBE=OFF \
        -DLSFG_WRAPPER_DIR="$LSFG_WRAPPER_DIR" -DCMAKE_BUILD_TYPE=Release >/dev/null
    "$LSFG_CMAKE" --build "$LSFG_NATIVE_BUILD" \
        --target lucent_lsfg_qualification -j 8 >/dev/null
    if [ ! -f "$LSFG_NATIVE_LIBRARY" ]; then
        printf 'LSFG qualification native build produced no library\n' >&2
        exit 1
    fi
fi

if [ "$INCLUDE_RIFE_FRAMEGEN" = 1 ]; then
    # This is an explicitly named qualification payload, never a product-route
    # switch. Gradle re-verifies every locked upstream tree before building.
    for rife_tool in "$RIFE_GRADLE" "$RIFE_LLVM_READELF"; do
        if [ ! -x "$rife_tool" ]; then
            printf 'LUCENT_INCLUDE_RIFE_FRAMEGEN=1 requires executable: %s\n' \
                "$rife_tool" >&2
            exit 1
        fi
    done
    (cd "$RIFE_BENCHMARK_DIR" && \
        if [ "$RIFE_SPATIAL_DISPATCH" = 1 ]; then set -- -PspatialDispatch; else set --; fi && \
        ANDROID_HOME="$SDK_DIR" ANDROID_SDK_ROOT="$SDK_DIR" \
        "$RIFE_GRADLE" --no-daemon "$@" \
            :app:assembleRelease :app:assembleDebugAndroidTest)
    python3 "$RIFE_BENCHMARK_DIR/tools/verify_host_artifacts.py" \
        --app-apk "$RIFE_APP_APK" \
        --test-apk "$RIFE_TEST_APK" \
        --prepared-manifest "$RIFE_PREPARED_MANIFEST" \
        --llvm-readelf "$RIFE_LLVM_READELF" \
        --output "$RIFE_HOST_RECORD" >/dev/null
fi

fetch_dependency() {
    dependency_url=$1
    dependency_path=$2
    expected_sha=$3
    mkdir -p "$(dirname "$dependency_path")"
    if [ ! -f "$dependency_path" ] ||
            [ "$(shasum -a 256 "$dependency_path" | awk '{print $1}')" != "$expected_sha" ]; then
        rm -f "$dependency_path.partial"
        curl -fL "$dependency_url" -o "$dependency_path.partial"
        actual_sha=$(shasum -a 256 "$dependency_path.partial" | awk '{print $1}')
        if [ "$actual_sha" != "$expected_sha" ]; then
            rm -f "$dependency_path.partial"
            printf 'Unexpected dependency checksum: %s\n' "$actual_sha" >&2
            exit 1
        fi
        mv "$dependency_path.partial" "$dependency_path"
    fi
}

fetch_dependency \
    "https://repo1.maven.org/maven2/org/apache/commons/commons-compress/1.21/commons-compress-1.21.jar" \
    "$COMMONS_COMPRESS_JAR" \
    "6aecfd5459728a595601cfa07258d131972ffc39b492eb48bdd596577a2f244a"
fetch_dependency \
    "https://repo1.maven.org/maven2/org/tukaani/xz/1.9/xz-1.9.jar" \
    "$XZ_JAR" \
    "211b306cfc44f8f96df3a0a3ddaf75ba8c5289eed77d60d72f889bb855f535e5"
fetch_dependency \
    "https://repo1.maven.org/maven2/com/neovisionaries/nv-websocket-client/2.14/nv-websocket-client-2.14.jar" \
    "$NV_WEBSOCKET_CLIENT_JAR" \
    "eed0fb6f5ef5db17d087039f1e829cfe827363b2863265258a96f0ed323313b7"
fetch_dependency \
    "https://repo1.maven.org/maven2/io/github/webrtc-sdk/android/150.7871.01/android-150.7871.01.aar" \
    "$WEBRTC_AAR" \
    "0a1627b1a48c2bc17d9a40d62fc47bd45166f44a311e95917f147c402de379b0"
# fetch_dependency only verifies and caches the single .aar file; this build
# has no AAR tooling at all, so unpack the two pieces every other step below
# actually needs (a plain classes.jar for the existing javac/d8 classpath,
# and the arm64-v8a .so for the existing native-library staging step) by
# hand. Guarded by WEBRTC_CLASSES_JAR's own presence so a cached, unchanged
# .aar is not re-unzipped on every build.
if [ ! -f "$WEBRTC_CLASSES_JAR" ] || [ ! -f "$WEBRTC_NATIVE_SO" ]; then
    rm -rf "$WEBRTC_AAR_EXTRACTED"
    mkdir -p "$WEBRTC_AAR_EXTRACTED"
    unzip -q -o "$WEBRTC_AAR" -d "$WEBRTC_AAR_EXTRACTED" \
        classes.jar 'jni/arm64-v8a/*'
fi

rm -rf "$BUILD_DIR/work" "$BUILD_DIR/classes" "$BUILD_DIR/stub-classes" \
    "$BUILD_DIR/dex"
mkdir -p "$BUILD_DIR/work" "$BUILD_DIR/classes" "$BUILD_DIR/stub-classes" \
    "$BUILD_DIR/dex"

# Fail closed before any core or APK work starts. Runtime checks are a second
# boundary, not a substitute for validating the release registry.
python3 "$ROOT_DIR/tools/validate_engine_registry.py" \
    "$ROOT_DIR/engines/registry.json" >/dev/null
python3 "$ROOT_DIR/tools/validate_phase3_registry.py" \
    "$ROOT_DIR/engines/phase3-registry.json" >/dev/null
if [ "$INCLUDE_PHASE2_PPSSPP" = 1 ]; then
    # Phase 2 remains a qualification-only path. The policy validator insists
    # every release/device/renderer gate is still closed, while the optional
    # artifact pass proves the exact pinned compiler output is what we package.
    python3 "$ROOT_DIR/tools/validate_phase2_registry.py" \
        "$ROOT_DIR/engines/phase2-registry.json" --verify-artifacts >/dev/null
fi

# Build EmuFusion's independent libretro API host. This packages only the host;
# engine binaries remain excluded until their registry entry is approved.
"$PROJECT_DIR/native/build.sh" >/dev/null
if [ "$INCLUDE_EXPERIMENTAL_CORES" = 1 ]; then
    # Qualification-only APKs may opt into the pinned Phase 1A source builds. They
    # remain disabled in the default/release path and are not auto-selected.
    for qualification_core in mesen mesen-s sameboy mgba gearsystem swanstation melonds-ds fuse mame dosbox-pure prosystem beetle-pce-fast beetle-neopop beetle-cygne blastem mupen64plus-next; do
        if [ "$REUSE_QUALIFICATION_CORES" = 1 ] &&
                [ -f "$ROOT_DIR/engines/build/arm64-v8a/${qualification_core}_libretro.so" ]; then
            continue
        fi
        "$ROOT_DIR/engines/build_core.sh" "$qualification_core"
    done
    python3 "$ROOT_DIR/tools/verify_phase1_reproducibility.py" \
        --artifact-dir "$ROOT_DIR/engines/build/arm64-v8a" >/dev/null
fi
if [ "$INCLUDE_PHASE2_PPSSPP" = 1 ]; then
    for phase2_core in applewin puae beetle-saturn dolphin ppsspp play armsx2 flycast azahar virtualjaguar; do
        phase2_input_dir="$ROOT_DIR/engines/build/arm64-v8a"
        if [ "$phase2_core" = armsx2 ]; then phase2_input_dir="$ARMSX2_CORE_DIR"; fi
        if [ "$REUSE_PHASE2_PPSSPP" != 1 ] ||
                [ ! -f "$phase2_input_dir/${phase2_core}_libretro.so" ]; then
            "$ROOT_DIR/engines/build_core.sh" "$phase2_core"
        fi
    done
    if [ "$REUSE_PHASE2_PPSSPP" != 1 ] ||
            [ ! -f "$ARMSX2_CORE_DIR/armsx2_16k_libretro.so" ]; then
        LUCENT_ARMSX2_HOST_PAGE_SIZE=0x4000 "$ROOT_DIR/engines/build_core.sh" armsx2
    fi
    # An existing filename is not evidence that the binary includes today's
    # PS2 timing patches. Never stamp the current source lock onto an old core.
    python3 "$ROOT_DIR/engines/tools/armsx2_build_identity.py" verify \
        --root "$ROOT_DIR" --pages 4096 \
        --core "$ARMSX2_CORE_DIR/armsx2_libretro.so"
    python3 "$ROOT_DIR/engines/tools/armsx2_build_identity.py" verify \
        --root "$ROOT_DIR" --pages 16384 \
        --core "$ARMSX2_CORE_DIR/armsx2_16k_libretro.so"
    if [ "$REUSE_PHASE2_PPSSPP" != 1 ] ||
            [ ! -f "$ROOT_DIR/engines/build/arm64-v8a/scummvm_libretro.so" ]; then
        "$ROOT_DIR/engines/build_scummvm_core.sh"
    else
        # Reuse still executes the exact binary/object/license compliance gate.
        python3 "$ROOT_DIR/tools/generate_scummvm_compliance_bundle.py" \
            --source "$ROOT_DIR/engines/build/scummvm-arm64-work/source" \
            --objects "$ROOT_DIR/engines/build/scummvm-arm64-work/obj/local/arm64-v8a/objs/retro" \
            --artifact "$ROOT_DIR/engines/build/arm64-v8a/scummvm_libretro.so" \
            --audit "$ROOT_DIR/engines/scummvm-dependency-audit.json" \
            --repository "$ROOT_DIR" \
            --output "$ROOT_DIR/engines/build/arm64-v8a/scummvm-compliance"
    fi
fi

if [ ! -f "$BASE_APK" ]; then
    mkdir -p "$(dirname "$BASE_APK")"
    curl -fL "$BASE_URL" -o "$BASE_APK.partial"
    mv "$BASE_APK.partial" "$BASE_APK"
fi
ACTUAL_BASE_SHA=$(shasum -a 256 "$BASE_APK" | awk '{print $1}')
if [ "$ACTUAL_BASE_SHA" != "$BASE_SHA256" ]; then
    printf 'Unexpected Pegasus base checksum: %s\n' "$ACTUAL_BASE_SHA" >&2
    exit 1
fi

# Build the exact theme delivered by the unified package.
THEME_ARCHIVE="$ROOT_DIR/android-companion/assets/emufusion-theme.zip"
THEME_FINGERPRINT="$ROOT_DIR/android-companion/assets/emufusion-theme.sha256"
rm -f "$THEME_ARCHIVE.partial.zip"
(cd "$ROOT_DIR/theme" && /usr/bin/zip -q -r "$THEME_ARCHIVE.partial.zip" .)
mv "$THEME_ARCHIVE.partial.zip" "$THEME_ARCHIVE"
shasum -a 256 "$THEME_ARCHIVE" | awk '{print $1}' > "$THEME_FINGERPRINT"

DECODED="$BUILD_DIR/work/apk"
"$APKTOOL" d -f "$BASE_APK" -o "$DECODED" >/dev/null

# Qt owns the full window. Correct the upstream non-namespaced theme typo and
# disable framework action-bar creation before Android inflates the decor.
python3 "$PROJECT_DIR/tools/patch_frontend_window_theme.py" "$DECODED"

# Rebrand the compiled Qt startup wordmark without shifting ELF resource
# offsets. Attribution remains visible in the splash and legal/About pages.
if [ -n "$SOURCE_FRONTEND_DIR" ]; then
    python3 "$PROJECT_DIR/tools/stage_source_frontend.py" \
        --source "$SOURCE_FRONTEND_DIR" --lock "$SOURCE_FRONTEND_LOCK" --decoded "$DECODED"
else
python3 "$PROJECT_DIR/tools/patch_pegasus_splash.py" \
    "$DECODED/lib/arm64-v8a/libpegasus-fe_arm64-v8a.so"
python3 "$PROJECT_DIR/tools/patch_emufusion_branding.py" \
    "$DECODED/lib/arm64-v8a/libpegasus-fe_arm64-v8a.so"
# EmuFusion's internal engines live in the inherited MainActivity. Preserve the
# already-rendered QML scene and its exact navigation selection instead of
# running Pegasus's external-process teardown/rebuild lifecycle.
python3 "$PROJECT_DIR/tools/patch_pegasus_in_process_launch.py" \
    "$DECODED/lib/arm64-v8a/libpegasus-fe_arm64-v8a.so"
# Android can deliver a final controller event after Qt has destroyed qApp.
# Guard both pinned Qt Gamepad key paths before they call qApp->thread().
python3 "$PROJECT_DIR/tools/patch_qt_android_gamepad_null_guard.py" \
    "$DECODED/lib/arm64-v8a/libplugins_gamepads_androidgamepad_arm64-v8a.so"
fi

# Keep Pegasus's JNI class names, but make EmuFusion the Android package and the
# only launcher. The package intentionally matches the existing companion so
# this unified build installs in place without deleting its settings.
APP_ICON_SOURCE="$PROJECT_DIR/res/drawable/lucent_icon.png"
if [ "$INTERNAL_LSFG_PLUS" = 1 ]; then
    APP_ICON_SOURCE="$PROJECT_DIR/res/drawable/lucent_plus_icon.png"
    if [ ! -f "$APP_ICON_SOURCE" ]; then
        printf 'EmuFusion+ icon is absent: %s\n' "$APP_ICON_SOURCE" >&2
        exit 1
    fi
fi
perl -0pi -e 's/package="org\.pegasus_frontend\.android"/package="com.thorium.preview"/g;
    s/android:name="org\.qtproject\.qt5\.android\.bindings\.QtApplication"/android:name="com.thorium.preview.LucentApplication"/g;
    s/android:label="Pegasus"/android:label="EmuFusion"/g;
    s/org\.pegasus_frontend\.android\.files/com.thorium.preview.files/g' \
    "$DECODED/AndroidManifest.xml"
if [ "$INTERNAL_LSFG_PLUS" = 1 ]; then
    perl -0pi -e 's/android:label="EmuFusion"/android:label="EmuFusion+"/g' \
        "$DECODED/AndroidManifest.xml"
fi
perl -0pi -e 's#android:icon="[^"]+"#android:icon="\@drawable/lucent_icon"#' \
    "$DECODED/AndroidManifest.xml"
# DIAGNOSTIC ONLY, enabled by LUCENT_DEBUGGABLE=1. Makes the app debuggable so
# an authorized debugger can inspect it. App-packaged wrap.sh below is a separate
# rootless allocator diagnostic; do not depend on global wrap.<pkg> properties.
# NEVER set this for a build that will be released.
if [ "${LUCENT_DEBUGGABLE:-0}" = 1 ] || [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then
    # The LSFG qualification payload also uses run-as for owner-staged shaders.
    # Apply both diagnostic switches here, once, before packaging.
    # apktool may already emit debuggable=false. Replace that attribute rather
    # than adding a duplicate that Android's resource linker rejects.
    perl -0pi -e 's#(<application\b[^>]*?)\s+android:debuggable="[^"]*"#$1#;
        s#(<application\b)#$1 android:debuggable="true"#' \
        "$DECODED/AndroidManifest.xml"
    printf 'WARNING: built DEBUGGABLE for diagnosis. Do not release this APK.\n' >&2
fi
if [ "${LUCENT_GWP_ASAN:-0}" = 1 ]; then
    python3 "$PROJECT_DIR/tools/enable_gwp_asan.py" "$DECODED/AndroidManifest.xml"
    printf 'WARNING: GWP-ASan diagnostic APK; sampled heap checks, not a pacing qualification build.\n' >&2
fi
# EmuFusion never enumerates or terminates standalone emulator applications.  The
# pinned frontend requested broad package visibility and the old companion
# requested process-kill authority; neither belongs in the one-app product.
# apktool may emit either "/>" or " />" (including a wrapped closing tag).
perl -0pi -e 's#<uses-permission android:name="android\.permission\.QUERY_ALL_PACKAGES"\s*/>##g;
    s#<uses-permission android:name="android\.permission\.KILL_BACKGROUND_PROCESSES"\s*/>##g' \
    "$DECODED/AndroidManifest.xml"
# Android 11 package visibility is required by the external-emulator picker.
# The source manifest owns that generated allowlist, but this unified APK is
# assembled from a decoded Pegasus manifest rather than Gradle's normal
# manifest merger, so copy the exact <queries> block here. LSFG is in-process
# and requires no companion package or package-visibility declaration.
python3 - "$ROOT_DIR/android-companion/AndroidManifest.xml" \
    "$DECODED/AndroidManifest.xml" <<'PY'
import pathlib
import re
import sys

source_path = pathlib.Path(sys.argv[1])
decoded_path = pathlib.Path(sys.argv[2])
source = source_path.read_text(encoding="utf-8")
decoded = decoded_path.read_text(encoding="utf-8")
match = re.search(r"<queries>.*?</queries>", source, re.DOTALL)
if match is None:
    raise SystemExit(f"{source_path} has no generated <queries> block")
if "<queries>" not in decoded:
    decoded = decoded.replace("<application", match.group(0) + "\n    <application", 1)
decoded_path.write_text(decoded, encoding="utf-8")
PY
perl -0pi -e 's/android:launchMode="singleTop" android:name="org\.pegasus_frontend\.android\.MainActivity"/android:launchMode="singleTask" android:name="org.pegasus_frontend.android.MainActivity"/' \
    "$DECODED/AndroidManifest.xml"
perl -0pi -e "s/versionCode: .*/versionCode: $VERSION_CODE/; s/versionName: .*/versionName: $VERSION_NAME/" \
    "$DECODED/apktool.yml"
# SoundPool opens a raw resource through a file descriptor, which only works
# when the entry is stored rather than deflated. apktool's default list does
# not cover .wav, so a compressed menu sound made every Service creation throw
# Resources$NotFoundException and crash-looped the app on launch.
perl -0pi -e 's/^doNotCompress:\n/doNotCompress:\n- wav\n/m' "$DECODED/apktool.yml"
grep -q '^- wav$' "$DECODED/apktool.yml" || {
    printf 'apktool.yml is missing the wav doNotCompress entry\n' >&2
    exit 1
}
perl -0pi -e 's/org\.pegasus_frontend\.android\.files/com.thorium.preview.files/g;
    s/"org\.pegasus_frontend\.android"/"com.thorium.preview"/g' \
    "$DECODED/smali/org/pegasus_frontend/android/MainActivity.smali" \
    "$DECODED/smali/org/pegasus_frontend/android/BuildConfig.smali"
python3 "$PROJECT_DIR/tools/patch_main_activity_right_stick.py" \
    "$DECODED/smali/org/pegasus_frontend/android/MainActivity.smali"
python3 "$PROJECT_DIR/tools/patch_qt_terminal_retirement.py" "$DECODED/smali"

MANIFEST_COMPONENTS="$BUILD_DIR/work/manifest-components.xml"
printf '%s\n' \
'        <activity android:name="com.thorium.preview.FrontendRestartActivity" android:excludeFromRecents="true" android:exported="false" android:noHistory="true" android:process=":frontend_restart" android:screenOrientation="userLandscape" android:theme="@android:style/Theme.DeviceDefault.NoActionBar.Fullscreen"/>' \
'        <activity android:name="com.thorium.preview.PreviewActivity" android:configChanges="keyboard|keyboardHidden|orientation|screenLayout|screenSize|smallestScreenSize|uiMode" android:excludeFromRecents="true" android:launchMode="singleTop" android:resizeableActivity="true" android:screenOrientation="landscape" android:taskAffinity="com.thorium.preview.preview" android:exported="false"/>' \
'        <activity android:name="com.thorium.preview.BrowserActivity" android:configChanges="density|keyboard|keyboardHidden|orientation|screenLayout|screenSize|smallestScreenSize|uiMode" android:excludeFromRecents="true" android:launchMode="singleTask" android:resizeableActivity="true" android:taskAffinity="com.thorium.preview.browser" android:exported="false"/>' \
'        <activity android:name="com.thorium.preview.VoiceFeedbackActivity" android:excludeFromRecents="true" android:exported="false" android:noHistory="true" android:screenOrientation="userLandscape" android:theme="@android:style/Theme.Translucent.NoTitleBar"/>' \
'        <activity android:name="com.thorium.preview.RomLaunchActivity" android:excludeFromRecents="true" android:noHistory="true" android:taskAffinity="com.thorium.preview.romlaunch" android:exported="false"/>' \
'        <service android:name="com.thorium.preview.PreviewService" android:exported="false"/>' \
'        <service android:name="com.thorium.preview.ExternalStopAccessibilityService" android:exported="true" android:label="EmuFusion external game return" android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"><intent-filter><action android:name="android.accessibilityservice.AccessibilityService"/></intent-filter><meta-data android:name="android.accessibilityservice" android:resource="@xml/external_stop_accessibility"/></service>' \
'        <provider android:name="com.thorium.preview.UpdateFileProvider" android:authorities="com.thorium.preview.updates" android:exported="false" android:grantUriPermissions="true"/>' \
'        <provider android:name="com.thorium.preview.RomFileProvider" android:authorities="com.thorium.preview.roms" android:exported="false" android:grantUriPermissions="true"/>' \
'        <receiver android:name="com.thorium.preview.BootReceiver" android:enabled="true" android:exported="true"><intent-filter><action android:name="android.intent.action.BOOT_COMPLETED"/><action android:name="android.intent.action.MY_PACKAGE_REPLACED"/></intent-filter></receiver>' \
    > "$MANIFEST_COMPONENTS"
if [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then
    # One shell-launched, in-process surface proves the native LSFG transport
    # before any ROM or gameplay session is allowed to open it. This component
    # exists only in the explicit qualification APK and has no intent filter.
    printf '%s\n' \
'        <activity android:name="com.thorium.preview.game.LsfgQualificationSelfTestActivity" android:excludeFromRecents="true" android:exported="true" android:finishOnTaskLaunch="true" android:noHistory="true" android:screenOrientation="landscape" android:taskAffinity="com.thorium.preview.lsfg.selftest" android:theme="@android:style/Theme.DeviceDefault.NoActionBar.Fullscreen"/>' \
        >> "$MANIFEST_COMPONENTS"
fi
# The component fragment is interpolated into Perl source below.  Resource
# references contain '@' (for example @xml/external_stop_accessibility), which
# Perl would otherwise treat as an array variable and silently rewrite to an
# invalid absolute-looking path.  Escape it along with the replacement
# delimiter and replacement metacharacter before interpolation.
COMPONENTS=$(sed 's/[@&/]/\\&/g' "$MANIFEST_COMPONENTS" | tr '\n' ' ')
perl -0pi -e "s#</application>#$COMPONENTS</application>#" "$DECODED/AndroidManifest.xml"
perl -0pi -e 's#<application#<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE"/><uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE"/><uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/><uses-permission android:name="android.permission.RECORD_AUDIO"/><uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED"/><uses-permission android:name="android.permission.FOREGROUND_SERVICE"/><uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES"/><uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW"/><application#' \
    "$DECODED/AndroidManifest.xml"
perl -0pi -e 's#<application#<application android:largeHeap="true"#' \
    "$DECODED/AndroidManifest.xml"
# Run after the diagnostic/qualification manifest edits above.
# The diagnostic transformer replaces existing attributes without duplicates.
if [ "${LUCENT_MALLOC_DEBUG:-0}" = 1 ]; then
    python3 "$PROJECT_DIR/tools/enable_malloc_debug.py" "$DECODED" --free-trace-library "${LUCENT_MALLOC_FREE_TRACE_LIBRARY:-}"
    printf 'WARNING: malloc_debug diagnostic APK; allocation guards alter performance. Do not release or qualify pacing with this build.\n' >&2
fi

mkdir -p "$DECODED/res/raw" "$DECODED/res/drawable" "$DECODED/res/xml" "$DECODED/assets"
if ! grep -q 'android.permission.WAKE_LOCK' "$DECODED/AndroidManifest.xml"; then
    perl -0pi -e 's#<application#<uses-permission android:name="android.permission.WAKE_LOCK"/><application#' "$DECODED/AndroidManifest.xml"
fi
cp "$ROOT_DIR/android-companion/res/raw/"* "$DECODED/res/raw/"
cp "$ROOT_DIR/android-companion/res/xml/"* "$DECODED/res/xml/"
cp "$APP_ICON_SOURCE" "$DECODED/res/drawable/lucent_icon.png"
cp "$THEME_ARCHIVE" "$THEME_FINGERPRINT" \
    "$ROOT_DIR/android-companion/assets/emufusion-version.txt" \
    "$DECODED/assets/"
# Cheat catalogue. Data, not code: CheatCatalog reads it at launch and a user
# file under files/cheats/ overrides any game in it.
mkdir -p "$DECODED/assets/cheats"
cp "$ROOT_DIR/engines/cheats/cheat-database.json" "$DECODED/assets/cheats/"
cp "$ROOT_DIR/engines/cheats/dolphin-cheats.json" "$DECODED/assets/cheats/"
# Startup video. The repository-root loading.mp4 is the product-owned source
# the owner replaces. BootVideoOverlay copies the packaged asset out to files/
# on first launch because MediaPlayer needs a real file rather than a
# compressed asset. Do not introduce a second mutable copy under engines/boot:
# that previously made it possible to build an obsolete loading screen even
# after the root video had been replaced.
mkdir -p "$DECODED/assets/boot"
cp "$ROOT_DIR/loading.mp4" "$DECODED/assets/boot/"
shasum -a 256 "$ROOT_DIR/loading.mp4" | awk '{print $1}' \
    > "$DECODED/assets/boot/loading.sha256"
cp "$ROOT_DIR/LICENSE" "$DECODED/assets/LICENSE"
cp "$ROOT_DIR/LICENSING.md" "$DECODED/assets/LICENSING.md"
cp "$ROOT_DIR/SOURCE_OFFER.md" "$DECODED/assets/SOURCE_OFFER.md"
cp "$ROOT_DIR/THIRD_PARTY_NOTICES.md" "$DECODED/assets/THIRD_PARTY_NOTICES.md"
cp "$ROOT_DIR/theme/LICENSE" "$DECODED/assets/THEME_LICENSE"
# LGPL-3.0 obligation for the bundled Qt: the license text has to travel with
# the binaries, not just be linked from a README. LGPLv3 incorporates GPLv3 by
# reference, and that text is already packaged above as assets/LICENSE.
cp "$ROOT_DIR/docs/licenses/LGPL-3.0.txt" "$DECODED/assets/LICENSE-LGPL-3.0.txt"

if [ "$INCLUDE_RIFE_FRAMEGEN" = 1 ]; then
    python3 "$PROJECT_DIR/tools/stage_rife_framegen_qualification.py" \
        --lock "$RIFE_EXPERIMENT_DIR/upstream-lock.json" \
        --cache-dir "$RIFE_CACHE_DIR" \
        --app-apk "$RIFE_APP_APK" \
        --host-record "$RIFE_HOST_RECORD" \
        --decoded-apk "$DECODED" >/dev/null
fi
if [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then
    # Only the public-wrapper host library is packaged. Lossless.dll and all
    # derived shaders remain outside the APK and are accepted solely from the
    # app-private, owner-staged qualification directory at runtime.
    cp "$LSFG_NATIVE_LIBRARY" \
        "$DECODED/lib/arm64-v8a/liblucent_lsfg_qualification.so"
fi

# Licence gate. Qt and OpenSSL were shipped undocumented for several releases
# because nothing tied the packaged library set to the notices. This binds
# them: a bundled base library with no THIRD_PARTY_NOTICES.md entry, or a
# notice whose version no longer matches the binary, fails the build here
# rather than in a release audit. The libretro cores have their own generated
# notice bundles and are excluded; so is Pegasus, which is the base itself.
NOTICES="$DECODED/assets/THIRD_PARTY_NOTICES.md"
UNDOCUMENTED_LIBS=
for lib_path in "$DECODED/lib/arm64-v8a/"*.so; do
    [ -f "$lib_path" ] || continue
    lib_name=${lib_path##*/}
    case "$lib_name" in
        liblucent_lsfg_qualification.so) notice_heading='## LSFG public-wrapper qualification host' ;;
        libemufusion_free_trace.so) notice_heading='## EmuFusion optional local crash tracer' ;;
        liblucent_*|libpegasus-fe_*) continue ;;
        # Not liblucent_-prefixed and not ours: these are libadrenotools' own
        # hook libraries, packaged beside the Eden adapter because adrenotools
        # dlopens them by name from the app's native library directory.
        libhook_impl.so|libmain_hook.so) notice_heading='## libadrenotools' ;;
        libqml_QtQuick_Timeline_*) notice_heading='### Qt Quick Timeline' ;;
        libQt5*|libplugins_*|libqml_*) notice_heading='## The Qt Toolkit' ;;
        libcrypto.so|libssl.so) notice_heading='## OpenSSL' ;;
        libc++_shared.so) notice_heading='## LLVM libc++' ;;
        librife_benchmark.so) notice_heading='## RIFE v4.6 frame-generation qualification payload' ;;
        libjingle_peerconnection_so.so) notice_heading='## WebRTC (io.github.webrtc-sdk)' ;;
        *) notice_heading= ;;
    esac
    if [ -z "$notice_heading" ] || ! grep -q "^$notice_heading" "$NOTICES"; then
        UNDOCUMENTED_LIBS="$UNDOCUMENTED_LIBS $lib_name"
    fi
done
# A blanket libQt5* rule would let a newly bundled Qt module - Qt WebEngine
# and Qt Charts do not have the plain LGPL terms the rest of Qt has - ride in
# under the general Qt notice. The notice enumerates the modules it covers, so
# require each packaged module to actually be named there.
for lib_path in "$DECODED/lib/arm64-v8a/"libQt5*.so; do
    [ -f "$lib_path" ] || continue
    qt_module=${lib_path##*/lib}
    qt_module=${qt_module%_arm64-v8a.so}
    grep -q "$qt_module" "$NOTICES" ||
        UNDOCUMENTED_LIBS="$UNDOCUMENTED_LIBS $qt_module"
done
if [ -n "$UNDOCUMENTED_LIBS" ]; then
    printf 'Refusing to build: bundled libraries with no THIRD_PARTY_NOTICES.md entry:%s\n' \
        "$UNDOCUMENTED_LIBS" >&2
    exit 1
fi
# The notices name exact versions, so the binaries must still agree with them.
PACKAGED_QT_VERSION=$(LC_ALL=C grep -a -o 'Qt 5\.[0-9][0-9]*\.[0-9][0-9]*' \
    "$DECODED/lib/arm64-v8a/libQt5Core_arm64-v8a.so" | head -1)
if ! grep -q "${PACKAGED_QT_VERSION#Qt }" "$NOTICES"; then
    printf 'Refusing to build: packaged %s is not the version documented in THIRD_PARTY_NOTICES.md\n' \
        "$PACKAGED_QT_VERSION" >&2
    exit 1
fi
PACKAGED_OPENSSL_VERSION=$(LC_ALL=C grep -a -o 'OpenSSL [0-9][0-9.]*[a-z]*' \
    "$DECODED/lib/arm64-v8a/libcrypto.so" | head -1)
if ! grep -q "$PACKAGED_OPENSSL_VERSION" "$NOTICES"; then
    printf 'Refusing to build: packaged %s is not the version documented in THIRD_PARTY_NOTICES.md\n' \
        "$PACKAGED_OPENSSL_VERSION" >&2
    exit 1
fi
# The Settings route picker's per-system external-emulator directory. Data, not
# code: ExternalEmulatorDirectoryLoader reads it to name each option and reach
# its install source, and a missing or damaged copy only degrades presentation —
# EmulatorCatalog still owns every launch recipe.
cp "$ROOT_DIR/engines/external-emulators.json" \
    "$DECODED/assets/external-emulators.json"
cp "$ROOT_DIR/engines/registry.json" "$DECODED/assets/engine-registry.json"
cp "$ROOT_DIR/engines/registry.schema.json" "$DECODED/assets/engine-registry.schema.json"
cp "$ROOT_DIR/engines/phase3-registry.json" "$DECODED/assets/phase3-engine-registry.json"
cp "$ROOT_DIR/engines/phase3-registry.schema.json" \
    "$DECODED/assets/phase3-engine-registry.schema.json"
mkdir -p "$DECODED/lib/arm64-v8a"
cp "$BUILD_DIR/native/arm64-v8a/liblucent_libretro_host.so" \
    "$DECODED/lib/arm64-v8a/liblucent_libretro_host.so"
cp "$BUILD_DIR/native/arm64-v8a/liblucent_framegen_timer.so" \
    "$DECODED/lib/arm64-v8a/liblucent_framegen_timer.so"
cp "$BUILD_DIR/native/arm64-v8a/liblucent_vulkan_host.so" \
    "$DECODED/lib/arm64-v8a/liblucent_vulkan_host.so"
# The Phase 3 loader is packaged with the other EmuFusion hosts, not with the
# adapter itself: NativeAdapterHost loads it in its static initializer, so a
# build that stages an adapter without this library fails at dlopen with the
# engine already approved.
cp "$BUILD_DIR/native/arm64-v8a/liblucent_native_adapter_host.so" \
    "$DECODED/lib/arm64-v8a/liblucent_native_adapter_host.so"
# Alpha multiplayer's WebRTC DataChannel transport. org.webrtc's Java classes
# (staged into the dex above) load this exact native library by name.
cp "$WEBRTC_NATIVE_SO" \
    "$DECODED/lib/arm64-v8a/libjingle_peerconnection_so.so"
# The engine-artifact manifests must list exactly the cores this flag
# combination stages: zero for the no-cores release path, and the length of
# the hardcoded core lists for qualification paths. Count each staged copy so
# a zero-core (or partially staged) APK can never pass the manifest gate.
PHASE1_STAGED_CORE_COUNT=0
PHASE2_STAGED_CORE_COUNT=0
PHASE3_STAGED_ADAPTER_COUNT=0
if [ "$INCLUDE_EXPERIMENTAL_CORES" = 1 ]; then
    for qualification_core in mesen mesen-s sameboy mgba gearsystem swanstation melonds-ds fuse mame dosbox-pure prosystem beetle-pce-fast beetle-neopop beetle-cygne blastem mupen64plus-next; do
        normalized_core=$(printf '%s' "$qualification_core" | tr '-' '_')
        cp "$ROOT_DIR/engines/build/arm64-v8a/${qualification_core}_libretro.so" \
            "$DECODED/lib/arm64-v8a/liblucent_core_${normalized_core}.so"
        PHASE1_STAGED_CORE_COUNT=$((PHASE1_STAGED_CORE_COUNT + 1))
    done
    cp "$ROOT_DIR/engines/qualification-opt-in.json" \
        "$DECODED/assets/engine-qualification-opt-in.json"
    if [ "$AUTOSELECT_EXPERIMENTAL_CORES" = 1 ]; then
        perl -0pi -e 's/"autoSelect": false/"autoSelect": true/' \
            "$DECODED/assets/engine-qualification-opt-in.json"
    fi
    # Generate compliance material from the exact staged binaries. Hand-edited
    # notice lists are intentionally not trusted for qualification packages.
    python3 "$PROJECT_DIR/tools/generate_phase1_compliance_bundle.py" \
        --registry "$ROOT_DIR/engines/registry.json" \
        --opt-in "$ROOT_DIR/engines/qualification-opt-in.json" \
        --library-dir "$DECODED/lib/arm64-v8a" \
        --manifest "$DECODED/assets/phase1-engine-artifacts.json" \
        --sbom "$DECODED/assets/phase1-sbom.spdx.json" \
        --notice "$DECODED/assets/PHASE1-CORE-NOTICES.txt"
    mkdir -p "$DECODED/assets/core-licenses"
    for license_file in "$ROOT_DIR/engines/build/arm64-v8a/"*-LICENSE.txt; do
        [ -f "$license_file" ] || continue
        cp "$license_file" "$DECODED/assets/core-licenses/"
    done
fi
if [ "$INCLUDE_PHASE2_PPSSPP" = 1 ]; then
    # Keep Phase 2 artifacts visibly separate from Phase 1. No production
    # auto-selection consumes them; the qualification catalog requires the
    # explicit package flag plus all signed asset and artifact identities.
    for phase2_core in applewin puae beetle-saturn dolphin ppsspp play armsx2 flycast azahar virtualjaguar scummvm; do
        normalized_core=$(printf '%s' "$phase2_core" | tr '-' '_')
        phase2_input_dir="$ROOT_DIR/engines/build/arm64-v8a"
        if [ "$phase2_core" = armsx2 ]; then phase2_input_dir="$ARMSX2_CORE_DIR"; fi
        cp "$phase2_input_dir/${phase2_core}_libretro.so" \
            "$DECODED/lib/arm64-v8a/liblucent_core_${normalized_core}.so"
        PHASE2_STAGED_CORE_COUNT=$((PHASE2_STAGED_CORE_COUNT + 1))
    done
    cp "$ARMSX2_CORE_DIR/armsx2_16k_libretro.so" \
        "$DECODED/lib/arm64-v8a/liblucent_core_armsx2_16k.so"
    cp "$ROOT_DIR/engines/phase2-registry.json" \
        "$DECODED/assets/phase2-engine-registry.json"
    if [ -n "${LUCENT_ARMSX2_QUALIFICATION_DIR:-}" ]; then
        python3 "$PROJECT_DIR/tools/stage_ps2_candidate_registry.py" \
            --root "$ROOT_DIR" --core-dir "$ARMSX2_CORE_DIR" --decoded "$DECODED"
    fi
    cp "$ROOT_DIR/engines/phase2-registry.schema.json" \
        "$DECODED/assets/phase2-engine-registry.schema.json"
    cp "$ROOT_DIR/engines/phase2-qualification-opt-in.json" \
        "$DECODED/assets/phase2-qualification-opt-in.json"
    cp "$ROOT_DIR/engines/applewin-source-lock.json" \
        "$DECODED/assets/phase2-applewin-source-lock.json"
    cp "$ROOT_DIR/engines/applewin-firmware-policy.json" \
        "$DECODED/assets/phase2-applewin-firmware-policy.json"
    cp "$ROOT_DIR/engines/play-source-lock.json" \
        "$DECODED/assets/phase2-play-source-lock.json"
    cp "$ROOT_DIR/engines/armsx2-source-lock.json" \
        "$DECODED/assets/phase2-armsx2-source-lock.json"
    cp "$ROOT_DIR/engines/flycast-source-lock.json" \
        "$DECODED/assets/phase2-flycast-source-lock.json"
    cp "$ROOT_DIR/engines/azahar-source-lock.json" \
        "$DECODED/assets/phase2-azahar-source-lock.json"
    cp "$ROOT_DIR/engines/dolphin-source-lock.json" \
        "$DECODED/assets/phase2-dolphin-source-lock.json"
    cp "$ROOT_DIR/engines/puae-source-lock.json" \
        "$DECODED/assets/phase2-puae-source-lock.json"
    cp "$ROOT_DIR/engines/puae-firmware-policy.json" \
        "$DECODED/assets/phase2-puae-firmware-policy.json"
    cp "$ROOT_DIR/engines/puae-dependency-audit.json" \
        "$DECODED/assets/phase2-puae-dependency-audit.json"
    cp "$ROOT_DIR/engines/puae-test-content-lock.json" \
        "$DECODED/assets/phase2-puae-test-content-lock.json"
    cp "$ROOT_DIR/engines/PUAE-CORE-NOTICES.txt" \
        "$DECODED/assets/PUAE-CORE-NOTICES.txt"
    cp "$ROOT_DIR/engines/scummvm-source-lock.json" \
        "$DECODED/assets/phase2-scummvm-source-lock.json"
    cp "$ROOT_DIR/engines/scummvm-dependency-audit.json" \
        "$DECODED/assets/phase2-scummvm-dependency-audit.json"
    cp "$ROOT_DIR/engines/scummvm-test-content-lock.json" \
        "$DECODED/assets/phase2-scummvm-test-content-lock.json"
    cp "$ROOT_DIR/engines/build/arm64-v8a/ppsspp-LICENSE.txt" \
        "$DECODED/assets/PPSSPP-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/play-LICENSE.txt" \
        "$DECODED/assets/PLAY-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/armsx2-LICENSE.txt" \
        "$DECODED/assets/ARMSX2-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/flycast-LICENSE.txt" \
        "$DECODED/assets/FLYCAST-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/azahar-LICENSE.txt" \
        "$DECODED/assets/AZAHAR-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/virtualjaguar-LICENSE.txt" \
        "$DECODED/assets/VIRTUALJAGUAR-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/puae-LICENSE.txt" \
        "$DECODED/assets/PUAE-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/beetle-saturn-LICENSE.txt" \
        "$DECODED/assets/BEETLE-SATURN-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/dolphin-LICENSE.txt" \
        "$DECODED/assets/DOLPHIN-LICENSE.txt"
    cp "$ROOT_DIR/engines/build/arm64-v8a/applewin-LICENSE.txt" \
        "$DECODED/assets/APPLEWIN-LICENSE.txt"
    cp -R "$ROOT_DIR/engines/build/arm64-v8a/scummvm-compliance" \
        "$DECODED/assets/scummvm-compliance"
    mkdir -p "$DECODED/assets/phase2-system/ppsspp"
    cp -R "$ROOT_DIR/engines/build/arm64-v8a/ppsspp-system/PPSSPP" \
        "$DECODED/assets/phase2-system/ppsspp/"
    mkdir -p "$DECODED/assets/phase2-system/armsx2"
    cp -R "$ROOT_DIR/engines/build/arm64-v8a/armsx2-system/pcsx2" \
        "$DECODED/assets/phase2-system/armsx2/"
    mkdir -p "$DECODED/assets/phase2-system/dolphin"
    cp -R "$ROOT_DIR/engines/build/arm64-v8a/dolphin-system/dolphin-emu" \
        "$DECODED/assets/phase2-system/dolphin/"
    mkdir -p "$DECODED/assets/phase2-system/scummvm"
    cp -R "$ROOT_DIR/engines/build/arm64-v8a/scummvm-system/scummvm" \
        "$DECODED/assets/phase2-system/scummvm/"
    python3 "$PROJECT_DIR/tools/generate_engine_artifact_manifest.py" \
        --registry "$ROOT_DIR/engines/phase2-registry.json" \
        --library-dir "$DECODED/lib/arm64-v8a" \
        --expected-count "$PHASE2_STAGED_CORE_COUNT" \
        --output "$DECODED/assets/phase2-engine-artifacts.json"
    python3 "$PROJECT_DIR/tools/generate_phase2_sbom.py" \
        --registry "$ROOT_DIR/engines/phase2-registry.json" \
        --dependency-lock "applewin=$ROOT_DIR/engines/applewin-source-lock.json" \
        --dependency-lock "puae=$ROOT_DIR/engines/puae-source-lock.json" \
        --dependency-lock "ppsspp=$ROOT_DIR/engines/ppsspp-source-lock.json" \
        --dependency-lock "play=$ROOT_DIR/engines/play-source-lock.json" \
        --dependency-lock "armsx2=$ROOT_DIR/engines/armsx2-source-lock.json" \
        --dependency-lock "flycast=$ROOT_DIR/engines/flycast-source-lock.json" \
        --dependency-lock "azahar=$ROOT_DIR/engines/azahar-source-lock.json" \
        --dependency-lock "dolphin=$ROOT_DIR/engines/dolphin-source-lock.json" \
        --dependency-lock "scummvm=$ROOT_DIR/engines/scummvm-source-lock.json" \
        --artifacts "$DECODED/assets/phase2-engine-artifacts.json" \
        --output "$DECODED/assets/phase2-sbom.spdx.json"
fi
python3 "$PROJECT_DIR/tools/generate_engine_artifact_manifest.py" \
    --registry "$ROOT_DIR/engines/registry.json" \
    --library-dir "$DECODED/lib/arm64-v8a" \
    --expected-count "$PHASE1_STAGED_CORE_COUNT" \
    --output "$DECODED/assets/engine-artifacts.json"
if [ "$INCLUDE_PHASE3_EDEN" = 1 ]; then
    # Phase 3 stages an ALREADY-BUILT in-process native adapter; this build
    # never compiles one. The .so is not a libretro core, so it is staged under
    # the exact name NativeAdapterCatalog reconstructs from the engine id and is
    # hashed into its own manifest. The catalog then re-verifies that hash on
    # device, so a swapped or truncated adapter fails closed at runtime too.
    cp "$PHASE3_EDEN_ADAPTER" \
        "$DECODED/lib/arm64-v8a/liblucent_native_adapter_eden.so"
    # adrenotools resolves these two by name from the hook directory, which is
    # the app's own native library directory. They are Eden build outputs, not
    # adapters, so they are deliberately not counted as staged adapters.
    cp "$PHASE3_EDEN_HOOK_IMPL" "$DECODED/lib/arm64-v8a/libhook_impl.so"
    cp "$PHASE3_EDEN_MAIN_HOOK" "$DECODED/lib/arm64-v8a/libmain_hook.so"
    PHASE3_STAGED_ADAPTER_COUNT=$((PHASE3_STAGED_ADAPTER_COUNT + 1))
    cp "$ROOT_DIR/engines/phase3-qualification-opt-in.json" \
        "$DECODED/assets/phase3-qualification-opt-in.json"
    cp "$ROOT_DIR/engines/eden-source-lock.json" \
        "$DECODED/assets/phase3-eden-source-lock.json"
    cp "$ROOT_DIR/engines/patches/eden-lucent-adapter.cpp" \
        "$DECODED/assets/phase3-eden-lucent-adapter.cpp"
    python3 "$PROJECT_DIR/tools/generate_engine_artifact_manifest.py" \
        --registry "$ROOT_DIR/engines/phase3-registry.json" \
        --library-dir "$DECODED/lib/arm64-v8a" \
        --artifact-kind native-adapter \
        --expected-count "$PHASE3_STAGED_ADAPTER_COUNT" \
        --output "$DECODED/assets/phase3-engine-artifacts.json"
fi
if [ "$INCLUDE_PHASE3_CEMU" = 1 ]; then
    # Wii U. Unlike Eden this needs no hook pair, no keys and no firmware, so
    # the adapter and its source lock are the whole payload. The opt-in asset
    # and the artifact manifest are shared with Eden, so the manifest is
    # regenerated here against the running staged-adapter count -- staging both
    # engines in one build must produce a manifest naming both.
    cp "$PHASE3_CEMU_ADAPTER" \
        "$DECODED/lib/arm64-v8a/liblucent_native_adapter_cemu.so"
    PHASE3_STAGED_ADAPTER_COUNT=$((PHASE3_STAGED_ADAPTER_COUNT + 1))
    cp "$ROOT_DIR/engines/phase3-qualification-opt-in.json" \
        "$DECODED/assets/phase3-qualification-opt-in.json"
    cp "$ROOT_DIR/engines/cemu-source-lock.json" \
        "$DECODED/assets/phase3-cemu-source-lock.json"
    cp "$ROOT_DIR/engines/patches/cemu-lucent-adapter.cpp" \
        "$DECODED/assets/phase3-cemu-lucent-adapter.cpp"
    python3 "$PROJECT_DIR/tools/generate_engine_artifact_manifest.py" \
        --registry "$ROOT_DIR/engines/phase3-registry.json" \
        --library-dir "$DECODED/lib/arm64-v8a" \
        --artifact-kind native-adapter \
        --expected-count "$PHASE3_STAGED_ADAPTER_COUNT" \
        --output "$DECODED/assets/phase3-engine-artifacts.json"
fi
if [ "$INCLUDE_PHASE3_APS3E" = 1 ]; then
    cp "$PHASE3_APS3E_ADAPTER" \
        "$DECODED/lib/arm64-v8a/liblucent_native_adapter_aps3e.so"
    PHASE3_STAGED_ADAPTER_COUNT=$((PHASE3_STAGED_ADAPTER_COUNT + 1))
    cp "$ROOT_DIR/engines/phase3-qualification-opt-in.json" \
        "$DECODED/assets/phase3-qualification-opt-in.json"
    cp "$ROOT_DIR/engines/aps3e-source-lock.json" \
        "$DECODED/assets/phase3-aps3e-source-lock.json"
    cp "$ROOT_DIR/engines/patches/aps3e-lucent-adapter.cpp" \
        "$DECODED/assets/phase3-aps3e-lucent-adapter.cpp"
    cp "$ROOT_DIR/engines/compliance/aps3e/GPL-2.0-only.txt" \
        "$DECODED/assets/LICENSE-GPL-2.0-APS3E.txt"
    python3 "$PROJECT_DIR/tools/generate_engine_artifact_manifest.py" \
        --registry "$ROOT_DIR/engines/phase3-registry.json" \
        --library-dir "$DECODED/lib/arm64-v8a" \
        --artifact-kind native-adapter \
        --expected-count "$PHASE3_STAGED_ADAPTER_COUNT" \
        --output "$DECODED/assets/phase3-engine-artifacts.json"
fi

# Compile all Java services together. The QtApplication stub is compile-only;
# the real superclass remains in Pegasus's primary classes.dex.
# The old standalone-emulator bridges and superseded game Activities remain in
# source history for migration/reference, but they are deliberately absent
# from EmuFusion's dex. Every emulator session is hosted by MainActivity through
# InWindowGameHost.
SOURCES=$(find "$ROOT_DIR/android-companion/src" "$ROOT_DIR/android-launch-bridge/src" \
    "$PROJECT_DIR/src" "$PROJECT_DIR/stubs" -name '*.java' \
    ! -path '*/com/thorium/preview/MainActivity.java' \
    ! -path '*/com/thorium/launchbridge/LaunchActivity.java' \
    ! -path '*/com/thorium/launchbridge/RomFileProvider.java' \
    ! -path '*/com/thorium/launchbridge/StopButtonService.java' \
    ! -path '*/com/thorium/preview/game/InternalGameLaunchActivity.java' \
    ! -path '*/com/thorium/preview/game/LucentGameActivity.java' \
    ! -path '*/com/thorium/preview/game/QualificationLaunchActivity.java' \
    ! -path '*/com/thorium/preview/game/SessionReturnRouter.java' -print)
if [ "$INCLUDE_RIFE_FRAMEGEN" = 1 ]; then
    SOURCES="$SOURCES \
$RIFE_BENCHMARK_DIR/app/src/main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java \
$RIFE_BENCHMARK_DIR/app/src/main/java/com/emufusion/rifebenchmark/ModelIntegrity.java \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/RifeQualificationRuntime.java \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/RifePresentationTransport.java \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/RifeQualificationTransportFactory.java"
fi
if [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then
    SOURCES="$SOURCES \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/NativeLsfgBridge.java \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/LsfgQualificationRuntime.java \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/LsfgPresentationTransport.java \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/LsfgQualificationTransportFactory.java \
$PROJECT_DIR/qualification-src/com/thorium/preview/game/LsfgQualificationSelfTestActivity.java"
fi
"$JAVA_HOME/bin/javac" -source 8 -target 8 -encoding UTF-8 \
    -classpath "$ANDROID_JAR:$COMMONS_COMPRESS_JAR:$XZ_JAR:$NV_WEBSOCKET_CLIENT_JAR:$WEBRTC_CLASSES_JAR" \
    -d "$BUILD_DIR/classes" $SOURCES
mkdir -p "$BUILD_DIR/stub-classes/org/qtproject/qt5/android/bindings"
mv "$BUILD_DIR/classes/org/qtproject/qt5/android/bindings/QtApplication.class" \
    "$BUILD_DIR/stub-classes/org/qtproject/qt5/android/bindings/"

CLASS_INPUTS=$(find "$BUILD_DIR/classes" -name '*.class' -print)
"$BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --classpath "$BUILD_DIR/stub-classes" \
    --output "$BUILD_DIR/dex" $CLASS_INPUTS "$COMMONS_COMPRESS_JAR" "$XZ_JAR" \
    "$NV_WEBSOCKET_CLIENT_JAR" "$WEBRTC_CLASSES_JAR"

UNSIGNED="$BUILD_DIR/lucent-unified-unsigned.apk"
# Later bootstrap/lifecycle patches must not reintroduce Qt's runtime theme
# override after the no-action-bar manifest/resource repair.
python3 "$PROJECT_DIR/tools/patch_frontend_window_theme.py" "$DECODED" --check
"$APKTOOL" b "$DECODED" -o "$UNSIGNED" >/dev/null
cp "$BUILD_DIR/dex/classes.dex" "$BUILD_DIR/work/classes2.dex"
(cd "$BUILD_DIR/work" && "$BUILD_TOOLS/aapt" add "$UNSIGNED" classes2.dex >/dev/null)

ALIGNED="$BUILD_DIR/lucent-unified-aligned.apk"
# EITHER Phase 3 adapter makes this a qualification artifact, so the name is
# driven by "any phase 3 engine" rather than by Eden alone. A Cemu-only build
# was previously named lucent-$VERSION_NAME.apk -- indistinguishable from a
# release -- while carrying a debug-signed, unshipped native adapter.
INCLUDE_PHASE3_ANY=0
if [ "$INCLUDE_PHASE3_EDEN" = 1 ] || [ "$INCLUDE_PHASE3_CEMU" = 1 ] || [ "$INCLUDE_PHASE3_APS3E" = 1 ]; then
    INCLUDE_PHASE3_ANY=1
fi
if [ "$INTERNAL_LSFG_PLUS" = 1 ]; then
    OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-emufusion-plus-lsfg-internal.apk"
elif [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then
    OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-lsfg-framegen-qualification.apk"
elif [ "$INCLUDE_RIFE_FRAMEGEN" = 1 ]; then
    OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-rife-framegen-qualification.apk"
elif [ "$INCLUDE_PHASE2_PPSSPP" = 1 ] && [ "$INCLUDE_PHASE3_ANY" = 1 ]; then
    OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-phase2-phase3-qualification.apk"
elif [ "$INCLUDE_PHASE2_PPSSPP" = 1 ]; then
    OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-phase2-qualification.apk"
elif [ "$INCLUDE_PHASE3_ANY" = 1 ]; then
    OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-phase3-qualification.apk"
else
    OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME.apk"
fi
"$BUILD_TOOLS/zipalign" -f 4 "$UNSIGNED" "$ALIGNED"
# Falling back to the debug keystore must be a stated choice, never the
# silent result of a misspelled LUCENT_KEYSTORE. A release cannot be
# produced by accident with the public debug identity.
SIGNING_PROFILE=${LUCENT_SIGNING_PROFILE:-debug}
case "$SIGNING_PROFILE" in
    debug)
        KEYSTORE=${LUCENT_KEYSTORE:-$ROOT_DIR/android-companion/debug.keystore}
        STORE_PASS=${LUCENT_STORE_PASS:-android}
        KEY_ALIAS=${LUCENT_KEY_ALIAS:-androiddebugkey}
        ;;
    release)
        KEYSTORE=${LUCENT_KEYSTORE:?LUCENT_SIGNING_PROFILE=release requires LUCENT_KEYSTORE}
        STORE_PASS=${LUCENT_STORE_PASS:?LUCENT_SIGNING_PROFILE=release requires LUCENT_STORE_PASS}
        KEY_ALIAS=${LUCENT_KEY_ALIAS:?LUCENT_SIGNING_PROFILE=release requires LUCENT_KEY_ALIAS}
        ;;
    *)
        printf 'LUCENT_SIGNING_PROFILE must be debug or release, not %s\n' \
            "$SIGNING_PROFILE" >&2
        exit 1
        ;;
esac
KEY_PASS=${LUCENT_KEY_PASS:-$STORE_PASS}
printf 'Signing profile: %s keystore=%s alias=%s\n' \
    "$SIGNING_PROFILE" "$KEYSTORE" "$KEY_ALIAS" >&2
"$BUILD_TOOLS/apksigner" sign --ks "$KEYSTORE" --ks-pass "pass:$STORE_PASS" \
    --key-pass "pass:$KEY_PASS" --ks-key-alias "$KEY_ALIAS" \
    --out "$OUTPUT" "$ALIGNED"
"$BUILD_TOOLS/apksigner" verify --verbose "$OUTPUT" >/dev/null
set --
if [ "$INTERNAL_LSFG_PLUS" = 1 ]; then
    set -- --internal-lsfg-plus
fi
if [ -n "$SOURCE_FRONTEND_LOCK" ]; then
    set -- "$@" --source-frontend-lock "$SOURCE_FRONTEND_LOCK"
fi
python3 "$PROJECT_DIR/tools/verify_one_app_apk.py" \
    "$@" --aapt "$BUILD_TOOLS/aapt" "$OUTPUT"
# 16 KiB page-size policy. The allowlist below is the exact 4 KiB-aligned
# set measured in lucent-3.2.15-phase2-qualification-cc15c076... (the pinned
# Qt/frontend base libraries plus the cores whose recipes do not yet pin
# max-page-size). Every library NOT named here must be 16 KiB aligned, so a
# new or regressed 4 KiB library fails the build immediately.
# THIS LIST MUST SHRINK TO ZERO BEFORE RELEASE; LUCENT_REQUIRE_16K_ALIGNMENT=1
# (the release path) ignores it and gates on every library.
ALLOWED_4K_LIBS="
libQt5AndroidExtras_arm64-v8a.so
libQt5Core_arm64-v8a.so
libQt5Gamepad_arm64-v8a.so
libQt5Gui_arm64-v8a.so
libQt5MultimediaQuick_arm64-v8a.so
libQt5Multimedia_arm64-v8a.so
libQt5Network_arm64-v8a.so
libQt5QmlModels_arm64-v8a.so
libQt5QmlWorkerScript_arm64-v8a.so
libQt5Qml_arm64-v8a.so
libQt5QuickParticles_arm64-v8a.so
libQt5QuickShapes_arm64-v8a.so
libQt5Quick_arm64-v8a.so
libQt5Sql_arm64-v8a.so
libQt5Svg_arm64-v8a.so
libc++_shared.so
libcrypto.so
liblucent_core_applewin.so
liblucent_core_azahar.so
liblucent_core_beetle_cygne.so
liblucent_core_beetle_neopop.so
liblucent_core_beetle_pce_fast.so
liblucent_core_beetle_saturn.so
liblucent_core_flycast.so
liblucent_core_fuse.so
liblucent_core_gearsystem.so
liblucent_core_mame.so
liblucent_core_mesen.so
liblucent_core_mesen_s.so
liblucent_core_mgba.so
liblucent_core_play.so
liblucent_core_ppsspp.so
liblucent_core_prosystem.so
liblucent_core_puae.so
liblucent_core_sameboy.so
liblucent_core_virtualjaguar.so
libpegasus-fe_arm64-v8a.so
libplugins_audio_qtaudio_opensles_arm64-v8a.so
libplugins_gamepads_androidgamepad_arm64-v8a.so
libplugins_iconengines_qsvgicon_arm64-v8a.so
libplugins_imageformats_qgif_arm64-v8a.so
libplugins_imageformats_qicns_arm64-v8a.so
libplugins_imageformats_qico_arm64-v8a.so
libplugins_imageformats_qjpeg_arm64-v8a.so
libplugins_imageformats_qsvg_arm64-v8a.so
libplugins_imageformats_qtga_arm64-v8a.so
libplugins_imageformats_qwbmp_arm64-v8a.so
libplugins_imageformats_qwebp_arm64-v8a.so
libplugins_mediaservice_qtmedia_android_arm64-v8a.so
libplugins_platforms_qtforandroid_arm64-v8a.so
libplugins_playlistformats_qtmultimedia_m3u_arm64-v8a.so
libplugins_sqldrivers_qsqlite_arm64-v8a.so
libplugins_video_videonode_qtsgvideonode_android_arm64-v8a.so
libqml_QtGraphicalEffects_private_qtgraphicaleffectsprivate_arm64-v8a.so
libqml_QtGraphicalEffects_qtgraphicaleffectsplugin_arm64-v8a.so
libqml_QtMultimedia_declarative_multimedia_arm64-v8a.so
libqml_QtQml_Models.2_modelsplugin_arm64-v8a.so
libqml_QtQml_StateMachine_qtqmlstatemachine_arm64-v8a.so
libqml_QtQml_WorkerScript.2_workerscriptplugin_arm64-v8a.so
libqml_QtQml_qmlplugin_arm64-v8a.so
libqml_QtQuick.2_qtquick2plugin_arm64-v8a.so
libqml_QtQuick_Layouts_qquicklayoutsplugin_arm64-v8a.so
libqml_QtQuick_Particles.2_particlesplugin_arm64-v8a.so
libqml_QtQuick_Shapes_qmlshapesplugin_arm64-v8a.so
libqml_QtQuick_Timeline_qtquicktimelineplugin_arm64-v8a.so
libqml_QtQuick_Window.2_windowplugin_arm64-v8a.so
libqml_Qt_labs_qmlmodels_labsmodelsplugin_arm64-v8a.so
libssl.so
"
if [ "${LUCENT_REQUIRE_16K_ALIGNMENT:-0}" = 1 ]; then
    python3 "$PROJECT_DIR/tools/verify_elf_alignment.py" "$OUTPUT"
else
    set --
    for allowed_4k_lib in $ALLOWED_4K_LIBS; do
        set -- "$@" --allow-4k-lib "$allowed_4k_lib"
    done
    python3 "$PROJECT_DIR/tools/verify_elf_alignment.py" "$@" "$OUTPUT"
fi
if [ "$INCLUDE_EXPERIMENTAL_CORES" = 1 ]; then
    python3 "$PROJECT_DIR/tools/verify_phase1_apk.py" "$OUTPUT"
fi
if [ "$INCLUDE_PHASE2_PPSSPP" = 1 ]; then
    python3 "$PROJECT_DIR/tools/verify_phase2_apk.py" "$OUTPUT"
fi
if [ "$INCLUDE_PHASE3_ANY" = 1 ]; then
    python3 "$PROJECT_DIR/tools/verify_phase3_apk.py" "$OUTPUT"
fi
if [ "${LUCENT_REQUIRE_PORTABLE_BUNDLE:-0}" = 1 ]; then
    python3 "$PROJECT_DIR/tools/verify_portable_bundle.py" "$OUTPUT"
fi
# A mutable convenience filename is useful for local installs, but QA evidence
# must never point at a path that a later build can overwrite.  Emit a
# content-addressed copy as the authoritative artifact.
OUTPUT_SHA=$(shasum -a 256 "$OUTPUT" | awk '{print $1}')
case "$OUTPUT" in
    *-emufusion-plus-lsfg-internal.apk)
        IMMUTABLE_OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-emufusion-plus-lsfg-internal-$OUTPUT_SHA.apk" ;;
    *-lsfg-framegen-qualification.apk)
        IMMUTABLE_OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-lsfg-framegen-qualification-$OUTPUT_SHA.apk" ;;
    *-rife-framegen-qualification.apk)
        IMMUTABLE_OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-rife-framegen-qualification-$OUTPUT_SHA.apk" ;;
    *-phase2-phase3-qualification.apk)
        IMMUTABLE_OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-phase2-phase3-qualification-$OUTPUT_SHA.apk" ;;
    *-phase2-qualification.apk)
        IMMUTABLE_OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-phase2-qualification-$OUTPUT_SHA.apk" ;;
    *-phase3-qualification.apk)
        IMMUTABLE_OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-phase3-qualification-$OUTPUT_SHA.apk" ;;
    *)  IMMUTABLE_OUTPUT="$BUILD_DIR/lucent-$VERSION_NAME-$OUTPUT_SHA.apk" ;;
esac
if [ -f "$IMMUTABLE_OUTPUT" ]; then
    IMMUTABLE_SHA=$(shasum -a 256 "$IMMUTABLE_OUTPUT" | awk '{print $1}')
    if [ "$IMMUTABLE_SHA" != "$OUTPUT_SHA" ]; then
        printf 'Immutable Lucent artifact collision: %s\n' "$IMMUTABLE_OUTPUT" >&2
        exit 1
    fi
else
    # Do not leave a truncated, hash-named artifact after ENOSPC. On APFS a
    # copy-on-write clone also avoids duplicating this large, verified APK.
    # Keep the ordinary copy fallback for other filesystems/platforms.
    IMMUTABLE_TEMP=$(mktemp "$BUILD_DIR/.immutable-apk.XXXXXX")
    if [ "$(uname -s)" = Darwin ] && cp -c "$OUTPUT" "$IMMUTABLE_TEMP" 2>/dev/null; then
        :
    elif ! cp "$OUTPUT" "$IMMUTABLE_TEMP"; then
        rm -f "$IMMUTABLE_TEMP"
        exit 1
    fi
    IMMUTABLE_SHA=$(shasum -a 256 "$IMMUTABLE_TEMP" | awk '{print $1}')
    if [ "$IMMUTABLE_SHA" != "$OUTPUT_SHA" ]; then
        rm -f "$IMMUTABLE_TEMP"
        printf 'Immutable Lucent artifact copy verification failed\n' >&2
        exit 1
    fi
    # link is atomic and refuses an existing destination; never replace an
    # immutable artifact even if another process publishes this hash first.
    if ! ln "$IMMUTABLE_TEMP" "$IMMUTABLE_OUTPUT"; then
        rm -f "$IMMUTABLE_TEMP"
        exit 1
    fi
    rm -f "$IMMUTABLE_TEMP"
fi
if [ "$SIGNING_PROFILE" = debug ]; then
    printf '############################################################\n' >&2
    printf '# DEBUG-SIGNED (qualification only): %s\n' "$IMMUTABLE_OUTPUT" >&2
    printf '# This APK carries the public debug identity and MUST NOT\n' >&2
    printf '# be released. Set LUCENT_SIGNING_PROFILE=release with\n' >&2
    printf '# LUCENT_KEYSTORE/LUCENT_STORE_PASS/LUCENT_KEY_ALIAS to sign\n' >&2
    printf '# a releasable artifact.\n' >&2
    printf '############################################################\n' >&2
fi
# Verified signed output and its immutable copy are sufficient. These two
# assembly intermediates are regenerated on every build, never rollback inputs.
rm -f "$UNSIGNED" "$ALIGNED"
# Successful assembly scratch is not a cache: the next build always recreates
# these exact directories. Keep dependencies, native symbols and failed-build
# diagnostics, but do not leave another decoded copy of every bundled core.
rm -rf "$BUILD_DIR/work" "$BUILD_DIR/classes" "$BUILD_DIR/stub-classes" \
    "$BUILD_DIR/dex"
# Publishing changes the newest-per-flavor set. Prune again now instead of
# retaining a newly superseded old APK until another build happens to run.
python3 "$PROJECT_DIR/tools/prune_build_apks.py" --apply --retired-diagnostics \
    --build-lock-owner "$$" >&2
printf '%s\n' "$IMMUTABLE_OUTPUT"
