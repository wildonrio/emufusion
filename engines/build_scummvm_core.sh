#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LOCK="$ROOT/engines/scummvm-source-lock.json"
SOURCE_CACHE="$ROOT/engines/build/sources"
# Candidate builds may redirect both; the defaults are the staged output.
WORK=${EMUFUSION_SCUMMVM_WORK_DIR:-$ROOT/engines/build/scummvm-arm64-work}
OUTPUT=${EMUFUSION_SCUMMVM_OUTPUT_DIR:-$ROOT/engines/build/arm64-v8a}

json_value() {
    /usr/bin/python3 -c 'import json,sys
value=json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    value=value[int(key)] if isinstance(value,list) else value[key]
print(value)' "$LOCK" "$1"
}

sha256() { shasum -a 256 "$1" | awk '{print $1}'; }

fetch_locked() {
    destination=$1
    url=$2
    expected=$3
    if [ -f "$destination" ] && [ "$(sha256 "$destination")" = "$expected" ]; then
        return
    fi
    rm -f "$destination.pending"
    curl -L --fail --retry 3 -o "$destination.pending" "$url"
    actual=$(sha256 "$destination.pending")
    if [ "$actual" != "$expected" ]; then
        rm -f "$destination.pending"
        printf 'SHA-256 mismatch for %s: expected %s, got %s\n' \
            "$url" "$expected" "$actual" >&2
        exit 1
    fi
    mv "$destination.pending" "$destination"
}

commit=$(json_value core.commit)
core_archive="$SOURCE_CACHE/scummvm-$commit.tar.gz"
deps_commit=$(json_value dependencies.0.commit)
deps_archive="$SOURCE_CACHE/scummvm-libretro-deps-$deps_commit.tar.gz"
common_commit=$(json_value dependencies.1.commit)
common_archive="$SOURCE_CACHE/scummvm-libretro-common-$common_commit.tar.gz"

mkdir -p "$SOURCE_CACHE" "$OUTPUT"
fetch_locked "$core_archive" "$(json_value core.archive)" \
    "$(json_value core.archiveSha256)"
fetch_locked "$deps_archive" "$(json_value dependencies.0.archive)" \
    "$(json_value dependencies.0.archiveSha256)"
fetch_locked "$common_archive" "$(json_value dependencies.1.archive)" \
    "$(json_value dependencies.1.archiveSha256)"

ndk=${ANDROID_NDK_ROOT:-${ANDROID_NDK_HOME:-}}
if [ -z "$ndk" ] && [ -n "${ANDROID_SDK_ROOT:-}" ]; then
    ndk="$ANDROID_SDK_ROOT/ndk/$(json_value toolchain.ndkVersion)"
fi
if [ -z "$ndk" ]; then
    ndk="$HOME/Library/Android/sdk/ndk/$(json_value toolchain.ndkVersion)"
fi
if [ ! -x "$ndk/ndk-build" ]; then
    printf 'Pinned Android NDK %s was not found. Set ANDROID_NDK_ROOT.\n' \
        "$(json_value toolchain.ndkVersion)" >&2
    exit 1
fi
if [ "$(sha256 "$ndk/source.properties")" != \
        "$(json_value toolchain.ndkSourcePropertiesSha256)" ]; then
    printf 'Android NDK source.properties does not match the pinned toolchain.\n' >&2
    exit 1
fi

rm -rf "$WORK"
mkdir -p "$WORK/source/backends/platform/libretro/deps/libretro-deps"
mkdir -p "$WORK/source/backends/platform/libretro/deps/libretro-common"
tar -xzf "$core_archive" --strip-components=1 -C "$WORK/source"
tar -xzf "$deps_archive" --strip-components=1 \
    -C "$WORK/source/backends/platform/libretro/deps/libretro-deps"
tar -xzf "$common_archive" --strip-components=1 \
    -C "$WORK/source/backends/platform/libretro/deps/libretro-common"

lifecycle_patch="$ROOT/engines/patches/scummvm-emufusion-exit-autosave.patch"
if [ "$(sha256 "$lifecycle_patch")" != "$(json_value patches.0.sha256)" ]; then
    printf 'EmuFusion ScummVM lifecycle patch does not match the source lock.\n' >&2
    exit 1
fi
patch -d "$WORK/source" -p1 < "$lifecycle_patch"

helper="$WORK/source/backends/platform/libretro/scripts/configure_submodules.sh"
perl -0pi -e 's/set -e\n/set -e\nif [ "\${EMUFUSION_OFFLINE_PINNED_DEPS:-0}" = "1" ]; then echo 0; exit 0; fi\n/' \
    "$helper"
chmod +x "$helper"
rm -f "$WORK/source/backends/platform/libretro/deps/libretro-deps/libmad/version"
android_mk="$WORK/source/backends/platform/libretro/jni/Android.mk"
perl -0pi -e 's/LOCAL_LDFLAGS         := -Wl,-version-script=\$\(ROOT_PATH\)\/link\.T/LOCAL_LDFLAGS         := -Wl,-version-script=\$\(ROOT_PATH\)\/link.T -Wl,-z,max-page-size=16384/' \
    "$android_mk"
if ! grep -q 'max-page-size=16384' "$android_mk"; then
    printf 'Unable to apply ScummVM Android 16 KiB page-size linker setting.\n' >&2
    exit 1
fi

base="$WORK/source/backends/platform/libretro"
export EMUFUSION_OFFLINE_PINNED_DEPS=1
export SOURCE_DATE_EPOCH=$(json_value sourceDateEpoch)
"$ndk/ndk-build" -C "$base" \
    NDK_PROJECT_PATH="$base" \
    APP_BUILD_SCRIPT="$base/jni/Android.mk" \
    NDK_APPLICATION_MK="$base/jni/Application.mk" \
    APP_ABI=arm64-v8a APP_PLATFORM=android-21 \
    NDK_OUT="$WORK/obj" NDK_LIBS_OUT="$WORK/libs" \
    -j"${EMUFUSION_BUILD_JOBS:-4}" LITE=1 NO_WIP=1

core="$WORK/libs/arm64-v8a/libretro.so"
if [ ! -f "$core" ]; then
    printf 'ScummVM Android build completed without libretro.so\n' >&2
    exit 1
fi
readelf="$ndk/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-readelf"
if [ ! -x "$readelf" ]; then
    prebuilt=$(find "$ndk/toolchains/llvm/prebuilt" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    readelf="$prebuilt/bin/llvm-readelf"
fi
if [ ! -x "$readelf" ]; then
    printf 'llvm-readelf is missing from the pinned Android NDK.\n' >&2
    exit 1
fi
if "$readelf" -lW "$core" | \
        awk '$1 == "LOAD" && $NF != "0x4000" { bad=1 } END { exit bad }'; then
    :
else
    printf 'ScummVM core is not compatible with Android 16 KiB pages.\n' >&2
    "$readelf" -lW "$core" | awk '$1 == "LOAD" { print }' >&2
    exit 1
fi
cp "$core" "$OUTPUT/scummvm_libretro.so"
cp "$WORK/source/COPYING" "$OUTPUT/scummvm-COPYING.txt"
python3 "$ROOT/tools/generate_scummvm_compliance_bundle.py" \
    --source "$WORK/source" \
    --objects "$WORK/obj/local/arm64-v8a/objs/retro" \
    --artifact "$OUTPUT/scummvm_libretro.so" \
    --audit "$ROOT/engines/scummvm-dependency-audit.json" \
    --repository "$ROOT" \
    --output "$OUTPUT/scummvm-compliance"
rm -rf "$OUTPUT/scummvm-system"
mkdir -p "$OUTPUT/scummvm-system"
make -C "$base" datafiles
unzip -q "$base/scummvm.zip" -d "$OUTPUT/scummvm-system"

printf '%s  %s\n' "$(sha256 "$OUTPUT/scummvm_libretro.so")" \
    "$OUTPUT/scummvm_libretro.so"
