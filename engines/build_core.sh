#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SDK_DIR=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk}}
NDK_VERSION=${NDK_VERSION:-27.0.12077973}
NDK_DIR=${ANDROID_NDK_ROOT:-$SDK_DIR/ndk/$NDK_VERSION}
CMAKE_VERSION=${CMAKE_VERSION:-3.31.6}
CMAKE=${CMAKE:-$SDK_DIR/cmake/$CMAKE_VERSION/bin/cmake}
NINJA=${NINJA:-$SDK_DIR/cmake/$CMAKE_VERSION/bin/ninja}
API=${LUCENT_NATIVE_API:-23}
ABI=${LUCENT_NATIVE_ABI:-arm64-v8a}
ENGINE=${1:-}
BUILD_ROOT=${LUCENT_ENGINE_BUILD_DIR:-$ROOT/engines/build}
SOURCE_DIR="$BUILD_ROOT/sources"
OUTPUT_DIR="$BUILD_ROOT/$ABI"
mkdir -p "$SOURCE_DIR" "$OUTPUT_DIR"

fetch_source() {
    name=$1
    commit=$2
    expected_sha=$3
    repository=$4
    archive="$SOURCE_DIR/$name-$commit.tar.gz"
    source="$SOURCE_DIR/$name-$commit"
    if [ ! -f "$archive" ] || [ "$(shasum -a 256 "$archive" | awk '{print $1}')" != "$expected_sha" ]; then
        rm -f "$archive.partial"
        curl -fL "$repository/archive/$commit.tar.gz" -o "$archive.partial"
        actual_sha=$(shasum -a 256 "$archive.partial" | awk '{print $1}')
        if [ "$actual_sha" != "$expected_sha" ]; then
            rm -f "$archive.partial"
            printf 'Source checksum mismatch for %s: %s\n' "$name" "$actual_sha" >&2
            exit 1
        fi
        mv "$archive.partial" "$archive"
    fi
    if [ ! -d "$source" ]; then
        unpack="$SOURCE_DIR/.unpack-$name-$commit"
        rm -rf "$unpack"
        mkdir -p "$unpack"
        tar -xzf "$archive" --strip-components=1 -C "$unpack"
        mv "$unpack" "$source"
    fi
    printf '%s\n' "$source"
}

# Re-extract a checksum-verified archive instead of trusting an existing
# mutable source directory. Heavy-engine recipes use this for deterministic
# closure staging; the archive cache itself remains reusable.
fetch_source_fresh() {
    fresh_name=$1
    fresh_commit=$2
    rm -rf "$SOURCE_DIR/$fresh_name-$fresh_commit"
    fetch_source "$@"
}

fetch_source_url_fresh() {
    fresh_name=$1
    fresh_commit=$2
    expected_sha=$3
    archive_url=$4
    archive="$SOURCE_DIR/$fresh_name-$fresh_commit.tar.gz"
    source="$SOURCE_DIR/$fresh_name-$fresh_commit"
    if [ ! -f "$archive" ] || [ "$(shasum -a 256 "$archive" | awk '{print $1}')" != "$expected_sha" ]; then
        rm -f "$archive.partial"
        curl -fL "$archive_url" -o "$archive.partial"
        actual_sha=$(shasum -a 256 "$archive.partial" | awk '{print $1}')
        if [ "$actual_sha" != "$expected_sha" ]; then
            rm -f "$archive.partial"
            printf 'Source checksum mismatch for %s: %s\n' "$fresh_name" "$actual_sha" >&2
            exit 1
        fi
        mv "$archive.partial" "$archive"
    fi
    rm -rf "$source"
    unpack="$SOURCE_DIR/.unpack-$fresh_name-$fresh_commit"
    rm -rf "$unpack"
    mkdir -p "$unpack"
    tar -xzf "$archive" --strip-components=1 -C "$unpack"
    mv "$unpack" "$source"
    printf '%s\n' "$source"
}

fetch_file() {
    name=$1
    expected_sha=$2
    url=$3
    destination="$SOURCE_DIR/$name"
    if [ ! -f "$destination" ] || [ "$(shasum -a 256 "$destination" | awk '{print $1}')" != "$expected_sha" ]; then
        rm -f "$destination.partial"
        curl -fL "$url" -o "$destination.partial"
        actual_sha=$(shasum -a 256 "$destination.partial" | awk '{print $1}')
        if [ "$actual_sha" != "$expected_sha" ]; then
            rm -f "$destination.partial"
            printf 'Source checksum mismatch for %s: %s\n' "$name" "$actual_sha" >&2
            exit 1
        fi
        mv "$destination.partial" "$destination"
    fi
    printf '%s\n' "$destination"
}

# PPSSPP's FFmpeg gitlink contains the complete FFmpeg source tree plus more
# than a gigabyte of unrelated, already-built libraries for other platforms.
# Fetch the exact git object while materializing only the corresponding source,
# build controls, and Android ARM64 inputs used by Lucent.  The SHA-256 closure
# digest covers every checked-out path and byte, not merely the five archives
# consumed by CMake.
fetch_ppsspp_ffmpeg_fresh() {
    ffmpeg_commit=$1
    expected_file_count=$2
    expected_closure_sha=$3
    ffmpeg_repository=$4
    ffmpeg_source="$SOURCE_DIR/ppsspp-ffmpeg-$ffmpeg_commit"
    rm -rf "$ffmpeg_source"
    git init -q "$ffmpeg_source"
    git -C "$ffmpeg_source" remote add origin "$ffmpeg_repository"
    git -C "$ffmpeg_source" config core.sparseCheckout true
    git -C "$ffmpeg_source" config core.sparseCheckoutCone false
    cat > "$ffmpeg_source/.git/info/sparse-checkout" <<'EOF'
/*
!/*/
/android/
!/android/*/
/android/arm64/
/compat/
/doc/
/libavcodec/
/libavdevice/
/libavfilter/
/libavformat/
/libavresample/
/libavutil/
/libpostproc/
/libswresample/
/libswscale/
/tools/
EOF
    git -C "$ffmpeg_source" fetch --quiet --depth=1 --filter=blob:none \
        origin "$ffmpeg_commit"
    git -C "$ffmpeg_source" checkout -q --detach FETCH_HEAD
    actual_ffmpeg_commit=$(git -C "$ffmpeg_source" rev-parse HEAD)
    if [ "$actual_ffmpeg_commit" != "$ffmpeg_commit" ]; then
        printf 'PPSSPP FFmpeg commit mismatch: %s\n' \
            "$actual_ffmpeg_commit" >&2
        exit 1
    fi
    closure_result=$(python3 - "$ffmpeg_source" <<'PY'
import hashlib
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
paths = subprocess.check_output(
    ["git", "-C", str(root), "ls-files", "-z"]
).split(b"\0")
digest = hashlib.sha256()
count = 0
for raw in sorted(path for path in paths if path):
    candidate = root / raw.decode("utf-8")
    if not candidate.is_file():
        continue
    file_sha = hashlib.sha256(candidate.read_bytes()).hexdigest().encode("ascii")
    digest.update(raw + b"\0" + file_sha + b"\0")
    count += 1
print(f"{count} {digest.hexdigest()}")
PY
    )
    actual_file_count=${closure_result%% *}
    actual_closure_sha=${closure_result#* }
    if [ "$actual_file_count" != "$expected_file_count" ] || \
        [ "$actual_closure_sha" != "$expected_closure_sha" ]; then
        printf 'PPSSPP FFmpeg sparse closure mismatch (files=%s sha=%s)\n' \
            "$actual_file_count" "$actual_closure_sha" >&2
        exit 1
    fi
    rm -rf "$ffmpeg_source/.git"
    printf '%s\n' "$ffmpeg_source"
}

apply_locked_patch() {
    patch_root=$1
    patch_path=$2
    expected_sha=$3
    full_path="$ROOT/$patch_path"
    if [ ! -f "$full_path" ]; then
        printf 'Locked patch is missing: %s\n' "$patch_path" >&2
        exit 1
    fi
    actual_sha=$(shasum -a 256 "$full_path" | awk '{print $1}')
    if [ "$actual_sha" != "$expected_sha" ]; then
        printf 'Patch checksum mismatch for %s: %s\n' "$patch_path" "$actual_sha" >&2
        exit 1
    fi
    patch -d "$patch_root" -p1 < "$full_path"
}

build_mednafen_software_core() {
    core_id=$1
    core_commit=$2
    core_sha=$3
    core_repository=$4
    upstream_output=$5
    link_mode=$6
    core_source=$(fetch_source_fresh "$core_id" "$core_commit" \
        "$core_sha" "$core_repository")
    case "$ABI" in
        arm64-v8a) core_target=aarch64-linux-android ;;
        *) printf '%s recipe currently supports arm64-v8a only\n' "$core_id" >&2; exit 1 ;;
    esac
    core_host=darwin-x86_64
    [ "$(uname -s)" = Linux ] && core_host=linux-x86_64
    core_toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$core_host/bin"
    core_stage="$BUILD_ROOT/work/$core_id-$ABI"
    rm -rf "$core_stage"
    mkdir -p "$core_stage"
    cp -R "$core_source/." "$core_stage/"
    /usr/bin/make -C "$core_stage" clean platform=unix \
        CC="$core_toolchain/$core_target$API-clang" \
        CXX="$core_toolchain/$core_target$API-clang++" \
        LD="$core_toolchain/$core_target$API-clang++"
    if [ "$link_mode" = no-librt ]; then
        /usr/bin/make -C "$core_stage" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix CC="$core_toolchain/$core_target$API-clang" \
            CXX="$core_toolchain/$core_target$API-clang++" \
            LD="$core_toolchain/$core_target$API-clang++" \
            GIT_VERSION="$core_commit" \
            LDFLAGS="-fPIC -shared -Wl,--no-undefined -Wl,--version-script=link.T -Wl,--build-id=none -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"
    else
        /usr/bin/make -C "$core_stage" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix CC="$core_toolchain/$core_target$API-clang" \
            CXX="$core_toolchain/$core_target$API-clang++" \
            LD="$core_toolchain/$core_target$API-clang++" \
            GIT_VERSION="$core_commit" \
            SHARED="-shared -Wl,--no-undefined -Wl,--version-script=link.T -Wl,--build-id=none -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"
    fi
    cp "$core_stage/$upstream_output" "$OUTPUT_DIR/${core_id}_libretro.so"
    cp "$core_stage/COPYING" "$OUTPUT_DIR/${core_id}-LICENSE.txt"
}

case "$ENGINE" in
    applewin)
        # AppleWin's libretro frontend is technically suitable for Lucent's
        # in-process software host.  The pinned GitHub archive preserves a
        # symlink into an SDL-only ImGui submodule as a dangling link, even
        # though CMake's common resource target still consumes that font.  Pin
        # the exact upstream ImGui object rather than fetching a mutable branch
        # or recursively cloning unrelated frontend submodules.
        commit=2045a52d89363005476e670e45df048655edccf7
        source=$(fetch_source_fresh applewin "$commit" \
            64f76dc39d7ea9f83f506bfaf7ae8b2c28117feb19a59d224debbd3c04df954b \
            https://github.com/audetto/AppleWin)
        cousine=$(fetch_file \
            applewin-Cousine-Regular-8936b58fe26e8c3da834b8f60b06511d537b4c63.ttf \
            0d5d5eeb6a342432bd63a3c0d16e8470160e019933ee5af3e159d06d665dacce \
            https://raw.githubusercontent.com/ocornut/imgui/8936b58fe26e8c3da834b8f60b06511d537b4c63/misc/fonts/Cousine-Regular.ttf)
        rm -f "$source/resource/Cousine-Regular.ttf"
        cp "$cousine" "$source/resource/Cousine-Regular.ttf"
        apply_locked_patch "$source" \
            engines/patches/applewin-external-firmware.patch \
            83c6b91f7af264a6e868a01a1684094a60a85f4441c717f160593b056cce1569
        stage="$BUILD_ROOT/work/applewin-$ABI"
        rm -rf "$stage"
        SOURCE_DATE_EPOCH=0 "$CMAKE" -S "$source" -B "$stage" -G Ninja \
            -DCMAKE_MAKE_PROGRAM="$NINJA" \
            -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" \
            -DCMAKE_BUILD_TYPE=Release -DBUILD_LIBRETRO=ON \
            -DBUILD_APPLEN=OFF -DBUILD_QAPPLE=OFF -DBUILD_SA2=OFF \
            -DENABLE_NETWORKING=OFF \
            -DCMAKE_SHARED_LINKER_FLAGS="-Wl,--build-id=none -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DCMAKE_MODULE_LINKER_FLAGS="-Wl,--build-id=none -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"
        SOURCE_DATE_EPOCH=0 "$CMAKE" --build "$stage" --target applewin_libretro \
            -j"${LUCENT_BUILD_JOBS:-4}"
        cp "$stage/source/frontends/libretro/applewin_libretro.so" \
            "$OUTPUT_DIR/applewin_libretro.so"
        cp "$source/LICENSE" "$OUTPUT_DIR/applewin-LICENSE.txt"
        python3 "$ROOT/tools/verify_applewin_firmware_exclusion.py" \
            --core "$OUTPUT_DIR/applewin_libretro.so" \
            --source-archive "$SOURCE_DIR/applewin-$commit.tar.gz" \
            --policy "$ROOT/engines/applewin-firmware-policy.json"
        ;;
    puae)
        commit=96ebfcfc2c66233ad37f6dc99ee991211dc719ad
        source=$(fetch_source_fresh puae "$commit" \
            af671aa1b42eb5b97a05b3ac2e57b6f397f3e17bbd0be7ac204636c2321d3cf0 \
            https://github.com/libretro/libretro-uae)
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'PUAE recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        stage="$BUILD_ROOT/work/puae-$ABI"
        rm -rf "$stage"
        mkdir -p "$stage"
        cp -R "$source/." "$stage/"
        SOURCE_DATE_EPOCH=0 /usr/bin/make -C "$stage" clean platform=unix \
            CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" \
            AR="$toolchain/llvm-ar" LD="$toolchain/$target$API-clang++" \
            TARGET=puae_libretro.so
        SOURCE_DATE_EPOCH=0 /usr/bin/make -C "$stage" \
            -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" AR="$toolchain/llvm-ar" \
            LD="$toolchain/$target$API-clang++" TARGET=puae_libretro.so \
            LDFLAGS='-lm -ldl -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384' \
            SHARED='-shared -Wl,--version-script=libretro/link.T -Wl,--no-undefined -Wl,--build-id=none' \
            GIT_VERSION="$commit"
        cp "$stage/puae_libretro.so" "$OUTPUT_DIR/puae_libretro.so"
        cp "$stage/COPYING" "$OUTPUT_DIR/puae-LICENSE.txt"
        python3 "$ROOT/tools/verify_puae_firmware_policy.py" \
            --core "$OUTPUT_DIR/puae_libretro.so" \
            --source "$SOURCE_DIR/puae-$commit.tar.gz" \
            --policy "$ROOT/engines/puae-firmware-policy.json"
        ;;
    beetle-saturn)
        build_mednafen_software_core beetle-saturn \
            84461434f249c1b5cd10c83ae922feae84e1acf8 \
            8d7c0e57c4dd31ca1e6e9122e5b4a306abe289963918809a16872a3a3b72d750 \
            https://github.com/libretro/beetle-saturn-libretro \
            mednafen_saturn_libretro.so no-librt
        ;;
    beetle-pce-fast)
        build_mednafen_software_core beetle-pce-fast \
            b211204c7026dff6e86e79b00185512e2421fff8 \
            ec3ef1874f0590ab6d5cd4bba86969ee085e8bef2de4b4e5f2422fe38a2c2d3d \
            https://github.com/libretro/beetle-pce-fast-libretro \
            mednafen_pce_fast_libretro.so no-librt
        ;;
    beetle-neopop)
        build_mednafen_software_core beetle-neopop \
            a50d5ac288a81f2104ddf43195a4efdd15c72227 \
            ffeabf2a357548f3a55423d542c31bb1e08571d81d7104f8213df3bfa2eb9c9f \
            https://github.com/libretro/beetle-ngp-libretro \
            mednafen_ngp_libretro.so standard
        ;;
    beetle-cygne)
        build_mednafen_software_core beetle-cygne \
            4b01295838ea89e3f1355bbe4cb5cf98aa6108cd \
            bce15c0e2505e15b7b55fa1d51b4a12219d07a67be62bbca5c26678d0d89c659 \
            https://github.com/libretro/beetle-wswan-libretro \
            mednafen_wswan_libretro.so standard
        ;;
    beetle-vb)
        build_mednafen_software_core beetle-vb \
            3f53a40bf8aa18777514fd4b220960427e312a3f \
            141f9b7a869c5632c2a59ca417f6d04b79687fd1ff05a2b62ed406139f317719 \
            https://github.com/libretro/beetle-vb-libretro \
            mednafen_vb_libretro.so standard
        ;;
    prosystem)
        commit=363b6dfbd3e240762e022c2b4897b4fe55722be3
        source=$(fetch_source_fresh prosystem "$commit" \
            7abed225b58d306bd3988c6950f851aa52a4c7b30d97cedcf626aa18fbf05282 \
            https://github.com/libretro/prosystem-libretro)
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'ProSystem recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        staged_source="$BUILD_ROOT/work/prosystem-$ABI"
        rm -rf "$staged_source"
        mkdir -p "$staged_source"
        cp -R "$source/." "$staged_source/"
        /usr/bin/make -C "$staged_source" clean \
            platform=unix CC="$toolchain/$target$API-clang" \
            LD="$toolchain/$target$API-clang"
        /usr/bin/make -C "$staged_source" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix CC="$toolchain/$target$API-clang" \
            LD="$toolchain/$target$API-clang" GIT_VERSION="$commit" \
            LDFLAGS="-shared -Wl,--no-undefined -Wl,--version-script=link.T -Wl,--build-id=none -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"
        cp "$staged_source/prosystem_libretro.so" \
            "$OUTPUT_DIR/prosystem_libretro.so"
        cp "$staged_source/License.txt" "$OUTPUT_DIR/prosystem-LICENSE.txt"
        ;;
    dosbox-pure)
        commit=7f6e8fb7385fa446d1444d671063268520bf9b54
        source=$(fetch_source_fresh dosbox-pure "$commit" \
            b413767bf4d61e03c9a779cb0001bcc1bb68c78afbb058fd68d947a9f065f300 \
            https://github.com/schellingb/dosbox-pure)
        case "$ABI" in
            arm64-v8a) ;;
            *) printf 'DOSBox Pure recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        staged_source="$BUILD_ROOT/work/dosbox-pure-$ABI"
        rm -rf "$staged_source"
        mkdir -p "$staged_source"
        cp -R "$source/." "$staged_source/"
        "$NDK_DIR/ndk-build" -C "$staged_source" \
            NDK_PROJECT_PATH="$staged_source" \
            APP_BUILD_SCRIPT="$staged_source/jni/Android.mk" \
            NDK_APPLICATION_MK="$staged_source/jni/Application.mk" \
            APP_ABI="$ABI" APP_PLATFORM="android-$API" \
            LDFLAGS="-Wl,--build-id=none" \
            -j"${LUCENT_BUILD_JOBS:-4}"
        cp "$staged_source/libs/$ABI/libretro.so" \
            "$OUTPUT_DIR/dosbox-pure_libretro.so"
        cp "$staged_source/LICENSE" "$OUTPUT_DIR/dosbox-pure-LICENSE.txt"
        ;;
    melonds-ds)
        commit=2748dfb9409c94e6828d937d04e334f35127ba7c
        source=$(fetch_source melonds-ds "$commit" \
            502d33556397836b32c2b81d0ef066558710eb1e22758d53c3463a63b91796a5 \
            https://github.com/JesseTG/melonds-ds)
        melonds=$(fetch_source melonds-upstream \
            f6692dff8c0c53f77639a08e5e746a286312bb41 \
            99332b46d4b69b17ba8a0f9c508c0292987056e367a91657e24ae8c1f74938e4 \
            https://github.com/JesseTG/melonDS)
        libretro_common=$(fetch_source libretro-common \
            8e2b884db16711a999a0e46a02a3dc0be294b048 \
            967fc5680bda0c9411a34509a5b4bf289cc2af1263edc0ef41fd2f1226668c1b \
            https://github.com/JesseTG/libretro-common)
        embed_binaries=$(fetch_source embed-binaries \
            078b62beba97e8192c99bfb16d5e17220cfc7598 \
            3b1017d10077de692e19c3772d824010705533ec441583587fac4a959ae77bd5 \
            https://github.com/andoalon/embed-binaries)
        glm=$(fetch_source glm e7970a8b26732f1b0df9690f7180546f8c30e48e \
            2111416bc7cf67aeac54d4eeb0fd68109ac20b97df7bf860114bf18679e8467e \
            https://github.com/g-truc/glm)
        libslirp=$(fetch_source libslirp-mirror \
            e61dbd459c8c06607b3a84694489427e8ec60f17 \
            2269005f612868c31027ea992bd88f0f7c89c69e7f2eef495479cb2a2f9e2ed3 \
            https://github.com/JesseTG/libslirp-mirror)
        pntr=$(fetch_source pntr 650237a524ea4fc953de7223a1587c83f2696794 \
            0980b1f0b2dc74b77be3e956834ffce2876b02043c52fb8d8bb51c4ec4a6f6b4 \
            https://github.com/robloach/pntr)
        fmt=$(fetch_source fmt 0c9fce2ffefecfdce794e1859584e25877b7b592 \
            f94052c10b611fd374194ca6e0dc4d159459c0b370abfe9002c13058863b7039 \
            https://github.com/fmtlib/fmt)
        yamc=$(fetch_source yamc 4e015a7e8eb0d61c34e6928676c8c78881a72d73 \
            f322d79bfd7dda607c69c867a1cc57192173f02d973e6c9bae02c3ad984c114e \
            https://github.com/yohhoy/yamc)
        span_lite=$(fetch_source span-lite \
            00afc281a8c3c7657bb9c5b000d6e7082c1bbc7f \
            0d98623e0a6ee6bbc84b9dee049c3ddfeb8fb4cfe3ad21cae598c5869deb2b82 \
            https://github.com/martinmoene/span-lite)
        date=$(fetch_source date 1ead6715dec030d340a316c927c877a3c4e5a00c \
            8b4096b7b49e06d756f4aa0949151863ab7b812679a1646039fab6e821d3c049 \
            https://github.com/HowardHinnant/date)
        zlib=$(fetch_source zlib 51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf \
            d9e270d46252734aa49770fbc544125391617956266f220bd63216c834f3a522 \
            https://github.com/madler/zlib)

        build="$BUILD_ROOT/work/melonds-ds-$ABI"
        staged_source="$build/source"
        deps="$build/_deps"
        rm -rf "$build"
        mkdir -p "$staged_source" "$deps"
        cp -R "$source/." "$staged_source/"
        patch -s -d "$staged_source" -p1 \
            < "$ROOT/engines/patches/melonds-ds-no-pcap-without-direct-networking.patch"
        ln -s "$melonds" "$deps/melonds-src"
        ln -s "$libretro_common" "$deps/libretro-common-src"
        ln -s "$embed_binaries" "$deps/embed-binaries-src"
        ln -s "$glm" "$deps/glm-src"
        ln -s "$libslirp" "$deps/libslirp-src"
        ln -s "$pntr" "$deps/pntr-src"
        ln -s "$fmt" "$deps/fmt-src"
        ln -s "$yamc" "$deps/yamc-src"
        ln -s "$span_lite" "$deps/span-lite-src"
        ln -s "$date" "$deps/date-src"
        ln -s "$zlib" "$deps/zlib-src"

        "$CMAKE" -S "$staged_source" -B "$build" -G Ninja \
            -DCMAKE_MAKE_PROGRAM="$NINJA" \
            -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" \
            -DCMAKE_BUILD_TYPE=Release -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
            -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DCMAKE_MODULE_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DENABLE_OPENGL=OFF -DENABLE_NETWORKING=ON -DENABLE_JIT=OFF \
            -DENABLE_THREADED_RENDERER=OFF -DBUILD_TESTING=OFF
        "$CMAKE" --build "$build" --target melondsds_libretro \
            -j"${LUCENT_BUILD_JOBS:-4}"
        cp "$build/src/libretro/melondsds_libretro_android.so" \
            "$OUTPUT_DIR/melonds-ds_libretro.so"
        cp "$build/melondsds-LICENSE.txt" \
            "$OUTPUT_DIR/melonds-ds-LICENSE.txt"
        ;;
    swanstation)
        commit=5430a4a53b89fa5827c97b84ada29d23317245bc
        source=$(fetch_source swanstation "$commit" \
            df747c49b9038499b8d8762cd2662f0b8c128ee3999b74b19979e5ab20dd622d \
            https://github.com/libretro/swanstation)
        build="$BUILD_ROOT/work/swanstation-$ABI"
        rm -rf "$build"
        staged_source="$BUILD_ROOT/work/swanstation-source-$ABI"
        rm -rf "$staged_source"
        mkdir -p "$staged_source"
        cp -R "$source/." "$staged_source/"
        patch -s -d "$staged_source" -p1 \
            < "$ROOT/engines/patches/swanstation-disable-forced-ipo.patch"
        source="$staged_source"
        # CMake exposes its binary directory through generated code. Resolve
        # macOS's /tmp -> /private/tmp alias, then canonicalize both source and
        # build paths so independent checkout locations cannot perturb ELF.
        mkdir -p "$(dirname "$build")"
        build_parent=$(CDPATH= cd -- "$(dirname "$build")" && pwd -P)
        build="$build_parent/$(basename "$build")"
        canonical_source=$(CDPATH= cd -- "$source" && pwd -P)
        "$CMAKE" -S "$source" -B "$build" -G Ninja \
            -DCMAKE_MAKE_PROGRAM="$NINJA" \
            -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" \
            -DCMAKE_BUILD_TYPE=Release \
            -DLUCENT_DISABLE_IPO=ON -DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF \
            -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DCMAKE_MODULE_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DCMAKE_C_FLAGS="-ffile-prefix-map=$source=/usr/src/lucent/swanstation -fmacro-prefix-map=$source=/usr/src/lucent/swanstation -ffile-prefix-map=$canonical_source=/usr/src/lucent/swanstation -fmacro-prefix-map=$canonical_source=/usr/src/lucent/swanstation -ffile-prefix-map=$build=/usr/src/lucent/swanstation-build -fmacro-prefix-map=$build=/usr/src/lucent/swanstation-build" \
            -DCMAKE_CXX_FLAGS="-ffile-prefix-map=$source=/usr/src/lucent/swanstation -fmacro-prefix-map=$source=/usr/src/lucent/swanstation -ffile-prefix-map=$canonical_source=/usr/src/lucent/swanstation -fmacro-prefix-map=$canonical_source=/usr/src/lucent/swanstation -ffile-prefix-map=$build=/usr/src/lucent/swanstation-build -fmacro-prefix-map=$build=/usr/src/lucent/swanstation-build"
        "$CMAKE" --build "$build" -j"${LUCENT_BUILD_JOBS:-4}"
        cp "$build/swanstation_libretro_android.so" \
            "$OUTPUT_DIR/swanstation_libretro.so"
        ;;
    mgba)
        commit=afd6f14eaf8bd35214ed3fb9dc69a92bfc3877a9
        source=$(fetch_source mgba "$commit" \
            f996cbd5971acacff4227761bf01ac3d0f0ac30796bcb0bfbd1cc9a8f3fd6e93 \
            https://github.com/mgba-emu/mgba)
        build="$BUILD_ROOT/work/mgba-$ABI"
        rm -rf "$build"
        # Keep source-location strings stable across clean build roots. Archive
        # sources must not inherit the enclosing EmuFusion checkout's Git version.
        mgba_path_flags="-ffile-prefix-map=$source=/usr/src/mgba -fdebug-prefix-map=$source=/usr/src/mgba -fmacro-prefix-map=$source=/usr/src/mgba -ffile-prefix-map=$build=/usr/src/mgba-build -fdebug-prefix-map=$build=/usr/src/mgba-build -fmacro-prefix-map=$build=/usr/src/mgba-build"
        GIT_CEILING_DIRECTORIES="$SOURCE_DIR" \
        "$CMAKE" -S "$source" -B "$build" -G Ninja \
            -DCMAKE_MAKE_PROGRAM="$NINJA" \
            -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" \
            -DCMAKE_BUILD_TYPE=Release -DBUILD_LIBRETRO=ON -DSKIP_LIBRARY=ON \
            -DCMAKE_C_FLAGS="$mgba_path_flags" -DCMAKE_CXX_FLAGS="$mgba_path_flags" \
            -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DCMAKE_MODULE_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DBUILD_QT=OFF -DBUILD_SDL=OFF -DBUILD_SHARED=OFF \
            -DBUILD_STATIC=OFF -DBUILD_TEST=OFF -DBUILD_SUITE=OFF \
            -DBUILD_CINEMA=OFF -DBUILD_EXAMPLE=OFF -DBUILD_PYTHON=OFF
        GIT_CEILING_DIRECTORIES="$SOURCE_DIR" \
        "$CMAKE" --build "$build" --target mgba_libretro -j"${LUCENT_BUILD_JOBS:-4}"
        cp "$build/mgba_libretro.so" "$OUTPUT_DIR/mgba_libretro.so"
        ;;
    mesen)
        commit=0102910c39ad1a62bc3f784466f3f67ca9eae335
        source=$(fetch_source mesen "$commit" \
            360f97e907ada9b8e28a95652aa1d07656340e1d84ff868312745a566b250e01 \
            https://github.com/libretro/Mesen)
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'Mesen recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        /usr/bin/make -C "$source/Libretro" clean
        /usr/bin/make -C "$source/Libretro" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix ARCHFLAGS=-march=armv8-a \
            CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" \
            AR="$toolchain/llvm-ar" STRIP="$toolchain/llvm-strip" \
            LDFLAGS='-static-libstdc++ -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384'
        cp "$source/Libretro/mesen_libretro.so" "$OUTPUT_DIR/mesen_libretro.so"
        ;;
    mesen-s)
        commit=1d475abd174d16ecb1fb030961ff26076ab51ee6
        source=$(fetch_source mesen-s "$commit" \
            9dc6b2762769cae40ff2d008562fa0f8883d89906a693b44f1fbe8d8cfaedbd4 \
            https://github.com/libretro/Mesen-S)
        # Build a fresh, patched copy without modifying a developer's cached
        # checkout. fetch_source has verified this archive's exact checksum.
        patched_source=$(mktemp -d "$BUILD_ROOT/mesen-s-dsp1.XXXXXX")
        tar -xzf "$SOURCE_DIR/mesen-s-$commit.tar.gz" --strip-components=1 -C "$patched_source"
        source="$patched_source"
        apply_locked_patch "$source" engines/patches/mesen-s-dsp1-fallback.patch \
            70da6abc56814107dcef11b8a2e58c0205673f59cf67f6808bc4f9e549cee5a3
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'Mesen-S recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        /usr/bin/make -C "$source/Libretro" clean
        /usr/bin/make -C "$source/Libretro" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix ARCHFLAGS=-march=armv8-a \
            CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" \
            AR="$toolchain/llvm-ar" STRIP="$toolchain/llvm-strip" \
            LDFLAGS='-static-libstdc++ -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384'
        cp "$source/Libretro/mesen-s_libretro.so" "$OUTPUT_DIR/mesen-s_libretro.so"
        ;;
    sameboy)
        commit=213a12ce93d66b105a113debd9396306066a7cfc
        source=$(fetch_source sameboy "$commit" \
            21f5f230268808d9a2d17d1a8e01d3763891a2a8240b9459fa61e005fff56aa1 \
            https://github.com/LIJI32/SameBoy)
        # fetch_source reuses the cached checkout across builds (unlike
        # fetch_source_fresh), so patch a throwaway copy -- mirrors
        # gearcoleco's build-dir copy below -- rather than the shared source.
        build="$BUILD_ROOT/work/sameboy-$ABI"
        rm -rf "$build"
        mkdir -p "$build"
        cp -R "$source/." "$build/"
        apply_locked_patch "$build" \
            engines/patches/sameboy-libretro-cheat-support.patch \
            546c488029fcf7e7817aa8cf120236c1d3e3ea83a3e96f7421a6849a2fa258c7
        source="$build"
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'SameBoy recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        rgbds_dir="$BUILD_ROOT/tools/rgbds-1.0.3-$(uname -s)"
        if [ ! -x "$rgbds_dir/rgbasm" ]; then
            rm -rf "$rgbds_dir"
            mkdir -p "$rgbds_dir"
            case "$(uname -s)" in
                Darwin)
                    rgbds_archive=$(fetch_file rgbds-1.0.3-macos.zip \
                        dc1804b187895c4e1b730ba9d4b476052979607e613113b72dc7a494f88c898e \
                        https://github.com/gbdev/rgbds/releases/download/v1.0.3/rgbds-macos.zip)
                    unzip -q "$rgbds_archive" -d "$rgbds_dir"
                    ;;
                Linux)
                    rgbds_archive=$(fetch_file rgbds-1.0.3-linux-x86_64.tar.xz \
                        280a52061a0c516999bee75ac357628d6d50784309e0486cef25f7460e6f330b \
                        https://github.com/gbdev/rgbds/releases/download/v1.0.3/rgbds-linux-x86_64.tar.xz)
                    tar -xJf "$rgbds_archive" -C "$rgbds_dir"
                    ;;
                *) printf 'SameBoy RGBDS bootstrap supports Darwin and Linux hosts only\n' >&2; exit 1 ;;
            esac
            chmod +x "$rgbds_dir/rgbasm" "$rgbds_dir/rgblink" "$rgbds_dir/rgbfix" "$rgbds_dir/rgbgfx"
        fi
        /usr/bin/make -C "$source" bootroms RGBDS="$rgbds_dir/" GIT_VERSION="$commit"
        /usr/bin/make -C "$source/libretro" clean
        LDFLAGS='-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384' \
        /usr/bin/make -C "$source/libretro" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix ARCHFLAGS=-march=armv8-a GIT_VERSION="$commit" \
            BOOTROMS_DIR="$source/build/bin/BootROMs" BIN="$source/build/bin" \
            CC="$toolchain/$target$API-clang" \
            AR="$toolchain/llvm-ar" STRIP="$toolchain/llvm-strip"
        cp "$source/build/bin/sameboy_libretro.so" "$OUTPUT_DIR/sameboy_libretro.so"
        ;;
    gearsystem|gearcoleco)
        case "$ENGINE" in
            gearsystem)
                commit=3c4cfcf54dfe9e36070815e76ee2bab9e754104f
                expected_sha=47a13565cfa00bc169969e84bd2f94228badc52f8dd10fb43735013aa258518f
                repository=https://github.com/drhelius/Gearsystem
                ;;
            gearcoleco)
                commit=5eb0d5fa8865de28b16a304431ca1d4bd4dd4e96
                expected_sha=ba398326d1ac98585b73b52eb6f0bae4e3659cbf39d8aecc274b7cd49eee0d18
                repository=https://github.com/drhelius/Gearcoleco
                ;;
        esac
        source=$(fetch_source "$ENGINE" "$commit" "$expected_sha" "$repository")
        if [ "$ENGINE" = gearcoleco ]; then
            build="$BUILD_ROOT/work/gearcoleco-$ABI"
            rm -rf "$build"
            mkdir -p "$build"
            cp -R "$source/." "$build/"
            patch -s -d "$build" -p1 \
                < "$ROOT/engines/patches/gearcoleco-initialize-libretro-state-header.patch"
            source="$build"
        fi
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf '%s recipe currently supports arm64-v8a only\n' "$ENGINE" >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        make_dir="$source/platforms/libretro"
        /usr/bin/make -C "$make_dir" clean
        /usr/bin/make -C "$make_dir" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix ARCHFLAGS=-march=armv8-a GIT_VERSION="$commit" \
            CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" \
            AR="$toolchain/llvm-ar" STRIP="$toolchain/llvm-strip" \
            LDFLAGS='-static-libstdc++ -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384'
        cp "$make_dir/${ENGINE}_libretro.so" "$OUTPUT_DIR/${ENGINE}_libretro.so"
        ;;
    freeintv)
        commit=428915baf2bfc032fc03e645f4f8f9c6c3144979
        source=$(fetch_source freeintv "$commit" \
            bc2826e362f78276c21f696c8bece86257d4a7be7484e96eaa79696016a3aac3 \
            https://github.com/libretro/FreeIntv)
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'FreeIntv recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        /usr/bin/make -C "$source" clean
        /usr/bin/make -C "$source" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix ARCHFLAGS=-march=armv8-a GIT_VERSION="$commit" \
            CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" \
            AR="$toolchain/llvm-ar" STRIP="$toolchain/llvm-strip"
        cp "$source/freeintv_libretro.so" "$OUTPUT_DIR/freeintv_libretro.so"
        ;;
    fuse)
        commit=000a8ae51a5141d75c109a22150e37ba06d57910
        source=$(fetch_source fuse "$commit" \
            1be02e95ce7854b4fbe134f86a0023d058c7aa0c3d2cc4d81de0249d94cf5174 \
            https://github.com/libretro/fuse-libretro)
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'Fuse recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        /usr/bin/make -C "$source" clean platform=unix
        LDFLAGS='-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384' \
        /usr/bin/make -C "$source" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=unix ARCHFLAGS=-march=armv8-a GIT_VERSION="$commit" \
            CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" \
            AR="$toolchain/llvm-ar" STRIP="$toolchain/llvm-strip"
        cp "$source/fuse_libretro.so" "$OUTPUT_DIR/fuse_libretro.so"
        ;;
    blastem)
        commit=84e567e17b6fb3cea23146c4209c18d50d46cbf0
        source=$(fetch_source_fresh blastem "$commit" \
            7bf9a28959fbced50479e59b7832bf9b2a9746bb06620bdd5c28c89d205e8fc7 \
            https://github.com/libretro/blastem)
        apply_locked_patch "$source" \
            engines/patches/blastem-libretro-android-portability.patch \
            4966522359464467f8b9f150356fdc03ba7f056a12f24ca822f71a9c8b173eed
        apply_locked_patch "$source" \
            engines/patches/blastem-new-core-frame-end-rebase-hang.patch \
            d899b13fe0728e5e927e30736e1c1c7c57d2906a6814c6150823e911cc73686c
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'BlastEm recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        stage="$BUILD_ROOT/work/blastem-$ABI"
        rm -rf "$stage"
        mkdir -p "$stage"
        cp -R "$source/." "$stage/"
        PYTHONHASHSEED=0 /usr/bin/make -C "$stage" -f Makefile.libretro \
            -j"${LUCENT_BUILD_JOBS:-4}" core \
            UNAME=Linux UNAMEM=aarch64 OS=Linux CPU=aarch64 ABI=aarch64 \
            CC="$toolchain/$target$API-clang" AR="$toolchain/llvm-ar" \
            NOLTO=1 \
            CFLAGS='-O2 -std=gnu99 -Wreturn-type -Werror=return-type -Wno-unused-value -Wpointer-arith -Werror=pointer-arith -DHAVE_UNISTD_H -DNEW_CORE -fPIC' \
            LDFLAGS='-O2 -lm -Wl,--no-undefined -Wl,--build-id=none -Wl,-z,max-page-size=16384'
        cp "$stage/blastem_libretro.so" "$OUTPUT_DIR/blastem_libretro.so"
        cp "$stage/COPYING" "$OUTPUT_DIR/blastem-LICENSE.txt"
        ;;
    mupen64plus-next)
        commit=f275caf4b2bfa1e6d1c51636746ea793f3d80320
        source=$(fetch_source_fresh mupen64plus-next "$commit" \
            1810b7bbdc4abfdeee8a9f7f99c4a91dab601a228935802317c25a43d7cf9dbb \
            https://github.com/libretro/mupen64plus-libretro-nx)
        apply_locked_patch "$source" \
            engines/patches/mupen64plus-next-android-arm64.patch \
            751a6ace68e14da2562210e20ee5c88ac9f5c4616dd5c8ae5c51160071c30b35
        apply_locked_patch "$source" \
            engines/patches/mupen64plus-next-context-setup.patch \
            8396947b663386db0eb1358dd201c2bcc3005e6faf3fd64d010a1287ea7be066
        apply_locked_patch "$source" \
            engines/patches/mupen64plus-next-host-page-protection.patch \
            d1562bd10b82830ccb1524401354c5360b5aaf7745b9122eb7d5d41134ae6d67
        apply_locked_patch "$source" \
            engines/patches/mupen64plus-next-egl-reader-capability.patch \
            611c2d214989ebfc985258bb12d9cadf61c8248cd0bbf3bfedf18ea00ab1530e
        case "$ABI" in
            arm64-v8a) target=aarch64-linux-android ;;
            *) printf 'Mupen64Plus-Next recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        toolchain="$NDK_DIR/toolchains/llvm/prebuilt/$host/bin"
        stage="$BUILD_ROOT/work/mupen64plus-next-$ABI"
        rm -rf "$stage"
        mkdir -p "$stage"
        cp -R "$source/." "$stage/"
        # The Pegasus/Qt base APK carries its own older libc++_shared.so.
        # Binding this pinned NDK-r27 core to that process-wide library caused
        # an unresolved basic_stringstream VTT on the Thor. Link the exact NDK
        # libc++ statically into the core so Lucent does not replace or depend
        # on Qt's C++ runtime.
        LDFLAGS='-Wl,--build-id=none -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384 -static-libstdc++' \
            /usr/bin/make -C "$stage" -j"${LUCENT_BUILD_JOBS:-4}" \
            platform=android-arm64-gles3 ANDROID_GRAPHIC_BUFFER=0 \
            ARCH=aarch64 GIT_VERSION="$commit" \
            CC="$toolchain/$target$API-clang" \
            CXX="$toolchain/$target$API-clang++" \
            AR="$toolchain/llvm-ar" STRINGS="$toolchain/llvm-strings"
        cp "$stage/mupen64plus_next_gles3_libretro_android.so" \
            "$OUTPUT_DIR/mupen64plus-next_libretro.so"
        {
            cat "$stage/LICENSE"
            printf '\n\n==== Android NDK r27 static C++ runtime notices ====\n\n'
            cat "$NDK_DIR/NOTICE.toolchain"
        } > "$OUTPUT_DIR/mupen64plus-next-LICENSE.txt"
        ;;
    armsx2)
        # PCSX2 has compile-time host-page geometry. Keep both variants in the
        # same APK and select the matching one at runtime; do not waive its
        # hardware check or replace the working 4 KiB core with a 16 KiB build.
        armsx2_host_page_size=${LUCENT_ARMSX2_HOST_PAGE_SIZE:-0x1000}
        armsx2_variant_suffix=
        armsx2_link_flags='-Wl,--build-id=none'
        case "$armsx2_host_page_size" in
            0x1000) ;;
            0x4000)
                armsx2_variant_suffix=_16k
                armsx2_link_flags="$armsx2_link_flags -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"
                ;;
            *) printf 'Unsupported ARMSX2 host page size: %s\n' "$armsx2_host_page_size" >&2; exit 1 ;;
        esac
        if [ "$ABI" != arm64-v8a ]; then
            printf 'ARMSX2 proof requires ABI arm64-v8a\n' >&2
            exit 1
        fi
        if [ "$(uname -s)" != Darwin ]; then
            printf 'ARMSX2 proof currently pins the Darwin CMake/Ninja toolchain only\n' >&2
            exit 1
        fi
        commit=788a59d641c777cb7f70726ea573d420508e0931
        source=$(fetch_source_fresh armsx2 "$commit" \
            bc2bb2f106ca499252e3bfe0a40366de5e9749fd84bebbbe80ed52c4b07abf63 \
            https://github.com/ARMSX2/ARMSX2)
        abseil=$(fetch_source_fresh armsx2-abseil \
            1315c900e1ddbb08a23e06eeb9a06450052ccb5e \
            4ae9fc64860d5204f0ca6bd6c7a5f8e59ced118494db7e14537d8ed55dce5715 \
            https://github.com/abseil/abseil-cpp)
        effcee=$(fetch_source_fresh armsx2-effcee \
            08da24ec245a274fea3a128ba50068f163390565 \
            d6d6b602f1b6f09d3a83c44a067d087c23fdc3d3530e2e5dd27be2adda91fe4d \
            https://github.com/google/effcee)
        glslang=$(fetch_source_fresh armsx2-glslang \
            09c541ee5b22bbac307987b50d86ec2b4f683d75 \
            e8dbf161cb49ae882076455d2146fff699b90caa092bcb65938a6cd4bc46ea10 \
            https://github.com/KhronosGroup/glslang)
        googletest=$(fetch_source_fresh armsx2-googletest \
            1d17ea141d2c11b8917d2c7d029f1c4e2b9769b2 \
            7aca173cc96c0feaa01035184e34b020daaa93ddc132c5a829b7ea34006f701b \
            https://github.com/google/googletest)
        re2=$(fetch_source_fresh armsx2-re2 \
            4a8cee3dd3c3d81b6fe8b867811e193d5819df07 \
            f0a65168e64a10ab556b265f2f411678e6b9555f21e04202f84f250b659954ba \
            https://github.com/google/re2)
        spirv_headers=$(fetch_source_fresh armsx2-spirv-headers \
            465055f6c9128772e20082e893d974146acf7a02 \
            fddd1edaea6e436970efa9a06cdc43f0522b37ba7edfbf042ab076b5ea53527b \
            https://github.com/KhronosGroup/SPIRV-Headers)
        spirv_tools=$(fetch_source_fresh armsx2-spirv-tools \
            e4bceacf59fdfe742047e94e41ef65a48999a0dd \
            92d1ba1042df2a2dcaa1946d12751c18c7c0e6bc71618dc9988ede838c13021e \
            https://github.com/KhronosGroup/SPIRV-Tools)

        build="$BUILD_ROOT/work/armsx2${armsx2_variant_suffix}-$ABI"
        staged_source="$build/source"
        shaderc_deps="$staged_source/platforms/android/app/src/main/cpp/3rdparty/shaderc/third_party"
        rm -rf "$build"
        mkdir -p "$staged_source" "$shaderc_deps"
        "${PYTHON:-python3}" "$ROOT/engines/tools/armsx2_build_identity.py" begin \
            --root "$ROOT" --pages "$armsx2_host_page_size" \
            --snapshot "$build/build-inputs.json"
        # This recipe is Darwin-only. APFS clones keep isolated source staging
        # cheap without sharing mutable files; other filesystems use full copies.
        cp -cR "$source/." "$staged_source/" 2>/dev/null || \
            cp -R "$source/." "$staged_source/"
        for dependency in \
            "$abseil:abseil_cpp" "$effcee:effcee" "$glslang:glslang" \
            "$googletest:googletest" "$re2:re2" \
            "$spirv_headers:spirv-headers" "$spirv_tools:spirv-tools"; do
            dependency_source=${dependency%%:*}
            dependency_name=${dependency#*:}
            mkdir -p "$shaderc_deps/$dependency_name"
            cp -cR "$dependency_source/." "$shaderc_deps/$dependency_name/" 2>/dev/null || \
                cp -R "$dependency_source/." "$shaderc_deps/$dependency_name/"
        done
        apply_locked_patch "$staged_source" \
            engines/patches/armsx2-libretro-android-build.patch \
            f8d1f6c46125ab953c9333eb57400a8f4ff339ea91ebc3221ab8638514bded78
        apply_locked_patch "$staged_source" \
            engines/patches/armsx2-libretro-frame-clock.patch \
            c94ef2e4fc1440fbbfceef124433343df8f1bbddd320307dc6719effd838d49f
        apply_locked_patch "$staged_source" \
            engines/patches/armsx2-libretro-descriptor-batch.patch \
            d7e781701ad7c05494310aebcc1750cc9f816289048b00d85ffbc1db9a95ff61
        apply_locked_patch "$staged_source" \
            engines/patches/armsx2-libretro-input-attachment.patch \
            0312e9a6d7f45caefb1d62784dfac1fbda196c87b67a3f5252307b2a945af9e4

        armsx2_ndk_dir="$SDK_DIR/ndk/27.0.12077973"
        armsx2_cmake="$SDK_DIR/cmake/3.31.6/bin/cmake"
        armsx2_ninja="$SDK_DIR/cmake/3.31.6/bin/ninja"
        expected_armsx2_ndk_sha=1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515
        expected_armsx2_cmake_sha=94d4a3ce9e70cd9dae26e5fc7bb6ff4de67c58759762d4118a96ad2bc1b76be8
        expected_armsx2_ninja_sha=3d508e91d5c159986bea2a472b1bfa849909da133aa05582a7174d33328af933
        for required in \
            "$armsx2_ndk_dir/source.properties" \
            "$armsx2_cmake" \
            "$armsx2_ninja"
        do
            if [ ! -f "$required" ]; then
                printf 'Missing pinned ARMSX2 toolchain input: %s\n' "$required" >&2
                exit 1
            fi
        done
        actual_armsx2_ndk_sha=$(shasum -a 256 \
            "$armsx2_ndk_dir/source.properties" | awk '{print $1}')
        actual_armsx2_cmake_sha=$(shasum -a 256 "$armsx2_cmake" | awk '{print $1}')
        actual_armsx2_ninja_sha=$(shasum -a 256 "$armsx2_ninja" | awk '{print $1}')
        if [ "$actual_armsx2_ndk_sha" != "$expected_armsx2_ndk_sha" ] || \
            [ "$actual_armsx2_cmake_sha" != "$expected_armsx2_cmake_sha" ] || \
            [ "$actual_armsx2_ninja_sha" != "$expected_armsx2_ninja_sha" ]; then
            printf 'ARMSX2 toolchain identity mismatch (NDK=%s CMake=%s Ninja=%s)\n' \
                "$actual_armsx2_ndk_sha" "$actual_armsx2_cmake_sha" \
                "$actual_armsx2_ninja_sha" >&2
            exit 1
        fi
        source_date_epoch=1786094134
        path_map_flags="-O3 -g -ffile-prefix-map=$ROOT=. -fdebug-prefix-map=$ROOT=. -fmacro-prefix-map=$ROOT=. -ffile-prefix-map=$build=armsx2-build -fdebug-prefix-map=$build=armsx2-build -fmacro-prefix-map=$build=armsx2-build -ffile-prefix-map=$staged_source=armsx2-source -fdebug-prefix-map=$staged_source=armsx2-source -fmacro-prefix-map=$staged_source=armsx2-source"
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$source_date_epoch" \
        "$armsx2_cmake" \
            -S "$staged_source/platforms/android/app/src/main/cpp" \
            -B "$build/out" -G Ninja \
            -DCMAKE_MAKE_PROGRAM="$armsx2_ninja" \
            -DCMAKE_TOOLCHAIN_FILE="$armsx2_ndk_dir/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="$ABI" -DANDROID_PLATFORM=android-26 \
            -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release \
            -DLTO_PCSX2_CORE=ON -DARMSX2_ANDROID_HOST_PAGE_SIZE="$armsx2_host_page_size" \
            -DCMAKE_SHARED_LINKER_FLAGS="$armsx2_link_flags" \
            -DCMAKE_C_FLAGS="$path_map_flags" \
            -DCMAKE_CXX_FLAGS="$path_map_flags"
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$source_date_epoch" \
        "$armsx2_cmake" --build "$build/out" --target pcsx2-libretro \
            -j"${LUCENT_BUILD_JOBS:-4}"
        "$armsx2_ndk_dir/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip" \
            --strip-unneeded "$build/out/pcsx2-libretro/armsx2_libretro.so" \
            -o "$OUTPUT_DIR/armsx2${armsx2_variant_suffix}_libretro.so"
        "${PYTHON:-python3}" "$ROOT/engines/tools/armsx2_build_identity.py" finish \
            --root "$ROOT" --pages "$armsx2_host_page_size" \
            --snapshot "$build/build-inputs.json" \
            --core "$OUTPUT_DIR/armsx2${armsx2_variant_suffix}_libretro.so"
        cp "$staged_source/COPYING.GPLv3" "$OUTPUT_DIR/armsx2-LICENSE.txt"
        rm -rf "$OUTPUT_DIR/armsx2-system"
        mkdir -p "$OUTPUT_DIR/armsx2-system/pcsx2/resources"
        cp -R "$staged_source/bin/resources/." \
            "$OUTPUT_DIR/armsx2-system/pcsx2/resources/"
        cp "$staged_source/platforms/android/app/src/main/assets/resources/patches.zip" \
            "$OUTPUT_DIR/armsx2-system/pcsx2/resources/patches.zip"
        ;;
    azahar)
        # The older official binary is only 4 KiB aligned. Build the same
        # pinned source with its locked submodules and Android 16 KiB fix.
        if [ "$ABI" != arm64-v8a ] || [ "$API" != 23 ]; then
            printf 'Azahar source build requires ABI arm64-v8a and API 23\n' >&2
            exit 1
        fi
        "${PYTHON:-python3}" "$ROOT/engines/tools/build_azahar.py" \
            --sdk "$SDK_DIR" \
            --work "${LUCENT_AZAHAR_WORK_DIR:-$BUILD_ROOT/azahar-source-arm64}" \
            --output "$OUTPUT_DIR" --jobs "${LUCENT_BUILD_JOBS:-4}"
        ;;
    play)
        # Phase 2 compiler/linker proof for Play!'s upstream Android libretro
        # adapter. This is not a release qualification: renderer lifecycle,
        # save states, performance, legal fixtures, and device behavior remain
        # independently fail-closed in the Phase 2 registry.
        if [ "$ABI" != arm64-v8a ] || [ "$API" != 23 ]; then
            printf 'Play! proof requires ABI arm64-v8a and API 23\n' >&2
            exit 1
        fi
        if [ "$(uname -s)" != Darwin ]; then
            printf 'Play! proof currently pins the Darwin CMake/Ninja toolchain only\n' >&2
            exit 1
        fi
        play_ndk_dir="$SDK_DIR/ndk/27.0.12077973"
        play_cmake="$SDK_DIR/cmake/3.31.6/bin/cmake"
        play_ninja="$SDK_DIR/cmake/3.31.6/bin/ninja"
        expected_play_ndk_sha=1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515
        expected_play_cmake_sha=94d4a3ce9e70cd9dae26e5fc7bb6ff4de67c58759762d4118a96ad2bc1b76be8
        expected_play_ninja_sha=3d508e91d5c159986bea2a472b1bfa849909da133aa05582a7174d33328af933
        for required in \
            "$play_ndk_dir/source.properties" \
            "$play_cmake" \
            "$play_ninja"
        do
            if [ ! -f "$required" ]; then
                printf 'Pinned Play! toolchain component is missing: %s\n' "$required" >&2
                exit 1
            fi
        done
        actual_play_ndk_sha=$(shasum -a 256 \
            "$play_ndk_dir/source.properties" | awk '{print $1}')
        actual_play_cmake_sha=$(shasum -a 256 "$play_cmake" | awk '{print $1}')
        actual_play_ninja_sha=$(shasum -a 256 "$play_ninja" | awk '{print $1}')
        if [ "$actual_play_ndk_sha" != "$expected_play_ndk_sha" ] || \
            [ "$actual_play_cmake_sha" != "$expected_play_cmake_sha" ] || \
            [ "$actual_play_ninja_sha" != "$expected_play_ninja_sha" ]; then
            printf 'Pinned Play! toolchain identity mismatch: NDK=%s CMake=%s Ninja=%s\n' \
                "$actual_play_ndk_sha" "$actual_play_cmake_sha" \
                "$actual_play_ninja_sha" >&2
            exit 1
        fi

        commit=50aedca2639521bc498ace0b2be1ea012801a86a
        source=$(fetch_source_fresh play "$commit" \
            a1dffa7cff03de6e40297a2a16ce6a61da31305b74b9233de9fa97238888758f \
            https://github.com/jpd002/Play-)
        altkit=$(fetch_source_fresh play-AltKit \
            f799f60ef6fa8b9676b4102b7dfa169fb40b6c92 \
            ca348273563d836765dbe48a1fd446f9efb75d778822a09d14a7fd1d1f325ff2 \
            https://github.com/jpd002/AltKit)
        codegen=$(fetch_source_fresh play-CodeGen \
            a5009f7dca062695b8e5aebbd71e67b4ddfa9251 \
            c9699563583ff4811d0c227259da1782a685303f7c3f5de0af0696e47ed706b5 \
            https://github.com/jpd002/Play--CodeGen)
        dependencies=$(fetch_source_fresh play-Dependencies \
            8a5f6b1dea0b888b5a42b821e79470142bbea4e3 \
            fa8dc6c346a5141af959260037f6ac30b9987456dc07d13405e7bfb065076f93 \
            https://github.com/jpd002/Play-Dependencies)
        framework=$(fetch_source_fresh play-Framework \
            587f278917acc0026bf5fc34b39f995fc26bd015 \
            3e4f87b6df7228dad15d9270cb15d855f8dd1b8803c7c30361549ff0f89326bc \
            https://github.com/jpd002/Play--Framework)
        nuanceur=$(fetch_source_fresh play-Nuanceur \
            d96578b5a18edc67a268ed4811f0a035c56de7a0 \
            07e63150025de47068f9be3146af92e34aba884887c20ad441e536e32fe3f1ef \
            https://github.com/jpd002/Nuanceur)
        libchdr=$(fetch_source_fresh play-libchdr \
            284e38b6e53e0a7270cc234934e45230ed915a25 \
            5c184845ac1c40fc5edd351887eb32ef42c2c016fe9daaeb6eeb2bab378bd148 \
            https://github.com/jpd002/libchdr)
        sdwebimage=$(fetch_source_fresh play-SDWebImage \
            0df32ea232aca587d5b67760b7f877079c51966c \
            5f0b0ff2793c88127caa913f3777bbbcde8c140539da8c8bee75841705226dd3 \
            https://github.com/rs/SDWebImage)
        ghc_filesystem=$(fetch_source_fresh play-ghc_filesystem \
            2a8b380f8d4e77b389c42a194ab9c70d8e3a0f1e \
            e11db30e695764cb19daf5058a9997c933c5ebdb3e29c697898258cbded8d65f \
            https://github.com/gulrak/filesystem)
        xxhash=$(fetch_source_fresh play-xxHash \
            e626a72bc2321cd320e953a0ccf1584cad60f363 \
            34e71c085636fbc1726482996d92719d0a16e6a6097970ecf2990a27b3821162 \
            https://github.com/Cyan4973/xxHash)
        zlib=$(fetch_source_fresh play-zlib \
            5a82f71ed1dfc0bec044d9702463dbdf84ea3b71 \
            54577b3e64db3d85268e909609faac1410d816376b037a1a415418f87f35814d \
            https://github.com/madler/zlib)
        zstd=$(fetch_source_fresh play-zstd \
            f8745da6ff1ad1e7bab384bd1f9d742439278e99 \
            4b0bd1f0cfb25e61b9103c35f27395530ff5b4c0d2513a00fd745849e85ea52c \
            https://github.com/facebook/zstd)
        vkrunner=$(fetch_source_fresh play-vkrunner \
            1b28778d9593d708aaa9dfa579e61c6cb08146dc \
            7e3b0128b696ac80178589727b3d76aae5413abb5d06192b6391c5fe9e63a0e6 \
            https://github.com/jpd002/vkrunner)

        build="$BUILD_ROOT/work/play-$ABI"
        staged_source="$build/source"
        rm -rf "$build"
        mkdir -p "$staged_source/deps/Dependencies" \
            "$staged_source/deps/Nuanceur/deps"
        cp -R "$source/." "$staged_source/"
        rm -rf "$staged_source/deps/AltKit" \
            "$staged_source/deps/CodeGen" \
            "$staged_source/deps/Dependencies" \
            "$staged_source/deps/Framework" \
            "$staged_source/deps/Nuanceur" \
            "$staged_source/deps/libchdr"
        mkdir -p "$staged_source/deps/Dependencies" \
            "$staged_source/deps/Nuanceur/deps"
        cp -R "$altkit/." "$staged_source/deps/AltKit/"
        cp -R "$codegen/." "$staged_source/deps/CodeGen/"
        cp -R "$dependencies/." "$staged_source/deps/Dependencies/"
        cp -R "$framework/." "$staged_source/deps/Framework/"
        cp -R "$nuanceur/." "$staged_source/deps/Nuanceur/"
        cp -R "$libchdr/." "$staged_source/deps/libchdr/"
        rm -rf "$staged_source/deps/Dependencies/SDWebImage" \
            "$staged_source/deps/Dependencies/ghc_filesystem" \
            "$staged_source/deps/Dependencies/xxHash" \
            "$staged_source/deps/Dependencies/zlib" \
            "$staged_source/deps/Dependencies/zstd" \
            "$staged_source/deps/Nuanceur/deps/vkrunner"
        mkdir -p "$staged_source/deps/Nuanceur/deps"
        cp -R "$sdwebimage/." "$staged_source/deps/Dependencies/SDWebImage/"
        cp -R "$ghc_filesystem/." "$staged_source/deps/Dependencies/ghc_filesystem/"
        cp -R "$xxhash/." "$staged_source/deps/Dependencies/xxHash/"
        cp -R "$zlib/." "$staged_source/deps/Dependencies/zlib/"
        cp -R "$zstd/." "$staged_source/deps/Dependencies/zstd/"
        cp -R "$vkrunner/." "$staged_source/deps/Nuanceur/deps/vkrunner/"

        apply_locked_patch "$staged_source" \
            engines/patches/play-expose-android-javavm-hook.patch \
            decbff7956d8b4817f15fc360588bb8338d4cccf6038089c4df87b66ced47de3
        # Upstream stores PS2VM.cpp with CRLF. Normalize the staged copy so the
        # exact reviewed patch applies identically on Darwin and Linux.
        LC_ALL=C perl -pi -e 's/\r$//' "$staged_source/Source/PS2VM.cpp"
        apply_locked_patch "$staged_source" \
            engines/patches/play-libretro-no-jni-thread-attach.patch \
            ea5f4ca8243f614638287581a5d2d72894aa4b998726f7aaeb5b26e21a0df350
        apply_locked_patch "$staged_source" \
            engines/patches/play-libretro-chain-ee-signal-handler.patch \
            3d1297d9d76acc380ba4bad650b827dc1dbe1001fa149c61145e1bd3b3b02a56
        apply_locked_patch "$staged_source" \
            engines/patches/play-libretro-output-size-hook.patch \
            76111c03a3ebf4d579b6a555259bb211ad53ee4e63ba9e2da0692643f9aab3c2
        apply_locked_patch "$staged_source" \
            engines/patches/play-libretro-lossless-audio-fifo.patch \
            f6871409fefe83709f85aaa50b8d223681f9be34f5d825b3e26b98f7d1899398
        apply_locked_patch "$staged_source" \
            engines/patches/play-libretro-safe-state.patch \
            fa6f7891fe25080d630af3ee0f24af0505153ad5d795bd0a00b5e11127a2520d

        path_map_flags="-DLUCENT_LIBRETRO=1 -ffile-prefix-map=$ROOT=. -fdebug-prefix-map=$ROOT=. -fmacro-prefix-map=$ROOT=. -ffile-prefix-map=$build=play-build -fdebug-prefix-map=$build=play-build -fmacro-prefix-map=$build=play-build -ffile-prefix-map=$staged_source=play-source -fdebug-prefix-map=$staged_source=play-source -fmacro-prefix-map=$staged_source=play-source"
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=1783783385 \
            "$play_cmake" -S "$staged_source" -B "$build/out" -G Ninja \
                -DCMAKE_MAKE_PROGRAM="$play_ninja" \
                -DCMAKE_TOOLCHAIN_FILE="$play_ndk_dir/build/cmake/android.toolchain.cmake" \
                -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" \
                -DCMAKE_BUILD_TYPE=Release -DBUILD_LIBRETRO_CORE=ON \
                -DBUILD_PLAY=OFF -DBUILD_TESTS=OFF \
                -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
                -DCMAKE_MODULE_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
                -DCMAKE_C_FLAGS="$path_map_flags" \
                -DCMAKE_CXX_FLAGS="$path_map_flags"
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=1783783385 \
            "$play_cmake" --build "$build/out" --target play_libretro \
                -j"${LUCENT_BUILD_JOBS:-4}"
        built="$build/out/Source/ui_libretro/play_libretro_android.so"
        if [ ! -f "$built" ]; then
            printf 'Play! build completed without an Android ARM64 core\n' >&2
            exit 1
        fi
        cp "$built" "$OUTPUT_DIR/play_libretro.so"
        "$play_ndk_dir/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip" \
            --strip-unneeded "$OUTPUT_DIR/play_libretro.so"
        cp "$staged_source/License.txt" "$OUTPUT_DIR/play-LICENSE.txt"
        ;;
    flycast)
        # Flycast's Android libretro adapter is hosted directly by Lucent. It
        # does not include or launch the RetroArch frontend. Keep the closure
        # deliberately small for the first Dreamcast qualification: GLES3,
        # no standalone UI, no Lua, no breakpad, and no OpenMP. Vulkan remains
        # a separate renderer gate rather than an implicit build dependency.
        if [ "$ABI" != arm64-v8a ]; then
            printf 'Flycast proof currently supports arm64-v8a only\n' >&2
            exit 1
        fi
        if [ "$(uname -s)" != Darwin ]; then
            printf 'Flycast proof currently pins the Darwin CMake/Ninja toolchain only\n' >&2
            exit 1
        fi
        flycast_api=24
        flycast_ndk_dir="$SDK_DIR/ndk/27.0.12077973"
        flycast_cmake="$SDK_DIR/cmake/3.31.6/bin/cmake"
        flycast_ninja="$SDK_DIR/cmake/3.31.6/bin/ninja"
        expected_flycast_ndk_sha=1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515
        expected_flycast_cmake_sha=94d4a3ce9e70cd9dae26e5fc7bb6ff4de67c58759762d4118a96ad2bc1b76be8
        expected_flycast_ninja_sha=3d508e91d5c159986bea2a472b1bfa849909da133aa05582a7174d33328af933
        for required in \
            "$flycast_ndk_dir/source.properties" \
            "$flycast_cmake" \
            "$flycast_ninja"
        do
            if [ ! -f "$required" ]; then
                printf 'Missing pinned Flycast toolchain input: %s\n' "$required" >&2
                exit 1
            fi
        done
        actual_flycast_ndk_sha=$(shasum -a 256 \
            "$flycast_ndk_dir/source.properties" | awk '{print $1}')
        actual_flycast_cmake_sha=$(shasum -a 256 "$flycast_cmake" | awk '{print $1}')
        actual_flycast_ninja_sha=$(shasum -a 256 "$flycast_ninja" | awk '{print $1}')
        if [ "$actual_flycast_ndk_sha" != "$expected_flycast_ndk_sha" ] || \
            [ "$actual_flycast_cmake_sha" != "$expected_flycast_cmake_sha" ] || \
            [ "$actual_flycast_ninja_sha" != "$expected_flycast_ninja_sha" ]; then
            printf 'Flycast toolchain identity mismatch (NDK=%s CMake=%s Ninja=%s)\n' \
                "$actual_flycast_ndk_sha" "$actual_flycast_cmake_sha" \
                "$actual_flycast_ninja_sha" >&2
            exit 1
        fi

        commit=d4fc0774107c4c307346b469499b9303a6ca0ffa
        source=$(fetch_source_fresh flycast "$commit" \
            fb19f122cb1c8bb9eae302c0e97ef75df168dacc2807da53a3af829cd6a98e71 \
            https://github.com/flyinghead/flycast)
        flycast_libchdr=$(fetch_source_fresh flycast-libchdr \
            5f82799f2c8cad1e9cd26d39a0f8d36369a5534b \
            11b01f5d376128c78100e48ad5db34edd0d33510fd047a5a22c03aa8e35cfd00 \
            https://github.com/flyinghead/libchdr)
        flycast_tinygettext=$(fetch_source_fresh flycast-tinygettext \
            41572a67f96013691685a38f0032f3c97aa34f79 \
            1ceb1c0f77caaf500806cdd8a14e122762e43ce3a399a2aa228dfc0174ede709 \
            https://github.com/flyinghead/tinygettext)
        flycast_tinycmmc=$(fetch_source_fresh flycast-tinycmmc \
            9a51e13802d930feb7261ba8876940659b258cb7 \
            60ed6cd061401ad76ebcde9e4b8847b85b4dfa0a86cf2bd7d99fa01f9a233a1d \
            https://github.com/Grumbel/tinycmmc)
        flycast_asio=$(fetch_source_fresh flycast-asio \
            d3402006e84efb6114ff93e4f2b8508412ed80d5 \
            0364ea2e2b9c1623e32a9587e0e2da08669f0f8d0f6be9abaa48e57d992ed079 \
            https://github.com/flyinghead/asio)

        build="$BUILD_ROOT/work/flycast-$ABI"
        staged_source="$build/source"
        rm -rf "$build"
        mkdir -p "$staged_source"
        cp -R "$source/." "$staged_source/"
        for mapping in \
            "$flycast_libchdr:core/deps/libchdr" \
            "$flycast_tinygettext:core/deps/tinygettext" \
            "$flycast_asio:core/deps/asio"
        do
            dependency=${mapping%%:*}
            destination=${mapping#*:}
            rm -rf "$staged_source/$destination"
            mkdir -p "$staged_source/$destination"
            cp -R "$dependency/." "$staged_source/$destination/"
        done
        rm -rf "$staged_source/core/deps/tinygettext/external/tinycmmc"
        mkdir -p "$staged_source/core/deps/tinygettext/external/tinycmmc"
        cp -R "$flycast_tinycmmc/." \
            "$staged_source/core/deps/tinygettext/external/tinycmmc/"
        # The exact source/dependency closure and locked patches are mirrored
        # in flycast-source-lock.json.
        apply_locked_patch "$staged_source" \
            engines/patches/flycast-libretro-cheat-support.patch \
            058b22158921a14d0bd965449e8fd4c25235ac27db379bfd4cb865748aad54d6
        apply_locked_patch "$staged_source" \
            engines/patches/flycast-android-shared-memory.patch \
            61335599add3e70cbaab2e8a3dad8062eb0cae97df2cf15c54935b87e8c95f62

        path_map_flags="-ffile-prefix-map=$ROOT=. -fdebug-prefix-map=$ROOT=. -fmacro-prefix-map=$ROOT=. -ffile-prefix-map=$build=flycast-build -fdebug-prefix-map=$build=flycast-build -fmacro-prefix-map=$build=flycast-build -ffile-prefix-map=$staged_source=flycast-source -fdebug-prefix-map=$staged_source=flycast-source -fmacro-prefix-map=$staged_source=flycast-source"
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=1750281767 \
            "$flycast_cmake" -S "$staged_source" -B "$build/out" -G Ninja \
                -DCMAKE_MAKE_PROGRAM="$flycast_ninja" \
                -DCMAKE_TOOLCHAIN_FILE="$flycast_ndk_dir/build/cmake/android.toolchain.cmake" \
                -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$flycast_api" \
                -DCMAKE_OSX_ARCHITECTURES=arm64 \
                -DCMAKE_BUILD_TYPE=Release -DLIBRETRO=ON \
                -DUSE_OPENGL=ON -DUSE_VULKAN=OFF -DUSE_OPENMP=OFF \
                -DUSE_LUA=OFF -DUSE_BREAKPAD=OFF -DENABLE_CTEST=OFF \
                -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
                -DCMAKE_MODULE_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
                -DCMAKE_C_FLAGS="$path_map_flags" \
                -DCMAKE_CXX_FLAGS="$path_map_flags"
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=1750281767 \
            "$flycast_cmake" --build "$build/out" \
                --target flycast_libretro -j"${LUCENT_BUILD_JOBS:-4}"
        built="$build/out/flycast_libretro.so"
        if [ ! -f "$built" ]; then
            printf 'Flycast build completed without an Android ARM64 core\n' >&2
            exit 1
        fi
        cp "$built" "$OUTPUT_DIR/flycast_libretro.so"
        "$flycast_ndk_dir/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip" \
            --strip-unneeded "$OUTPUT_DIR/flycast_libretro.so"
        cp "$staged_source/LICENSE" "$OUTPUT_DIR/flycast-LICENSE.txt"
        ;;
    virtualjaguar)
        commit=59f7f9cc594ae6c6982c2bd8fc0dbf36873f9869
        source=$(fetch_source_fresh virtualjaguar "$commit" \
            81b2d166f1539d6278894965ed049b3267ad6260957bf25046eab2d98dd27c0b \
            https://github.com/libretro/virtualjaguar-libretro)
        case "$ABI" in
            arm64-v8a) ;;
            *) printf 'Virtual Jaguar recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        # Build from a checksum-verified fresh extraction. The upstream
        # ndk-build recipe owns its complete source closure, so no mutable
        # checkout or network fetch participates after the archive is staged.
        build="$BUILD_ROOT/work/virtualjaguar-$ABI"
        staged_source="$build/source"
        rm -rf "$build"
        mkdir -p "$staged_source"
        cp -R "$source/." "$staged_source/"
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=1778934711 \
            "$NDK_DIR/ndk-build" -C "$staged_source" \
                NDK_PROJECT_PATH=. APP_BUILD_SCRIPT=jni/Android.mk \
                NDK_APPLICATION_MK=jni/Application.mk APP_ABI="$ABI" \
                APP_PLATFORM="android-$API" \
                APP_LDFLAGS='-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384' \
                -j"${LUCENT_BUILD_JOBS:-4}"
        built="$staged_source/libs/$ABI/libretro.so"
        if [ ! -f "$built" ]; then
            printf 'Virtual Jaguar build completed without an Android ARM64 core\n' >&2
            exit 1
        fi
        cp "$built" "$OUTPUT_DIR/virtualjaguar_libretro.so"
        cp "$staged_source/LICENSE" "$OUTPUT_DIR/virtualjaguar-LICENSE.txt"
        ;;
    dolphin)
        # Build the maintained Dolphin libretro fork used by Lucent's
        # single-activity GLES host.  The exact source/dependency closure and
        # toolchain identities are mirrored in dolphin-source-lock.json.
        case "$ABI" in
            arm64-v8a) ;;
            *) printf 'Dolphin proof recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        if [ "$(uname -s)" != Darwin ]; then
            printf 'Dolphin proof currently pins the Darwin CMake/Ninja toolchain only\n' >&2
            exit 1
        fi
        dolphin_ndk_dir="$SDK_DIR/ndk/27.0.12077973"
        dolphin_cmake="$SDK_DIR/cmake/3.22.1/bin/cmake"
        dolphin_ninja="$SDK_DIR/cmake/3.22.1/bin/ninja"
        expected_dolphin_ndk_sha=1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515
        expected_dolphin_cmake_sha=e46c7ffb232c25a43e130509368dd6b88f492f110ab6b44c69c639ac1ed8c8f6
        expected_dolphin_ninja_sha=5b861a9e1e062ad8e01a1370f5909b36c086774899b4ac2029192744352404d0
        for required in \
            "$dolphin_ndk_dir/source.properties" \
            "$dolphin_cmake" \
            "$dolphin_ninja"
        do
            if [ ! -f "$required" ]; then
                printf 'Pinned Dolphin toolchain component is missing: %s\n' "$required" >&2
                exit 1
            fi
        done
        actual_dolphin_ndk_sha=$(shasum -a 256 \
            "$dolphin_ndk_dir/source.properties" | awk '{print $1}')
        actual_dolphin_cmake_sha=$(shasum -a 256 "$dolphin_cmake" | awk '{print $1}')
        actual_dolphin_ninja_sha=$(shasum -a 256 "$dolphin_ninja" | awk '{print $1}')
        if [ "$actual_dolphin_ndk_sha" != "$expected_dolphin_ndk_sha" ] || \
            [ "$actual_dolphin_cmake_sha" != "$expected_dolphin_cmake_sha" ] || \
            [ "$actual_dolphin_ninja_sha" != "$expected_dolphin_ninja_sha" ]; then
            printf 'Dolphin toolchain identity mismatch (NDK=%s CMake=%s Ninja=%s)\n' \
                "$actual_dolphin_ndk_sha" "$actual_dolphin_cmake_sha" \
                "$actual_dolphin_ninja_sha" >&2
            exit 1
        fi
        commit=0ff12a5a2835762e0665afe6a161a648b433f996
        source=$(fetch_source_fresh dolphin "$commit" \
            3c6698d6da772065194be118871ce24620f0fdc76894bc568e34d48f93de7494 \
            https://github.com/libretro/dolphin)
        # Dolphin embeds source paths through assertion diagnostics.  Use one
        # stable, explicitly owned temporary root so the checksum proof is
        # independent of the caller's workspace path.  Refuse to touch a
        # pre-existing directory unless this recipe created it previously.
        build=/tmp/lucent-dolphin-libretro-clone
        dolphin_owner_marker="$build/.lucent-deterministic-build-root"
        if [ -e "$build" ] && [ ! -f "$dolphin_owner_marker" ]; then
            printf 'Refusing to replace unowned Dolphin build root: %s\n' "$build" >&2
            exit 1
        fi
        rm -rf "$build"
        mkdir -p "$build"
        : > "$dolphin_owner_marker"
        staged_source="$build"
        out="$build/build/lucent-android-arm64"
        cp -R "$source/." "$staged_source/"

        apply_locked_patch "$staged_source" \
            engines/patches/dolphin-libretro-submit-rendered-duplicate-xfb.patch \
            5dd844b8546eea62706a4dd84304077cddaf83c68987459a532f6055f2f5919b
        apply_locked_patch "$staged_source" \
            engines/patches/dolphin-libretro-own-signal-stack.patch \
            68c853fa395b8c87c41729355c2149dbb83f024b9cb851123b21cfc575ac074b
        apply_locked_patch "$staged_source" \
            engines/patches/dolphin-libretro-descriptor-errors.patch \
            d508e5c96869b925a8a1c01139c76ee2ae13abcd74a0475c4f5281aded85cbcd

        while IFS='|' read -r dep_path dep_repository dep_commit dep_sha; do
            [ -n "$dep_path" ] || continue
            dep_name=$(printf '%s' "$dep_path" | tr '/_' '--')
            if [ "$dep_path" = "Externals/bzip2/bzip2" ]; then
                dep_source=$(fetch_source_url_fresh "$dep_name" "$dep_commit" "$dep_sha" \
                    "$dep_repository/-/archive/$dep_commit/bzip2-$dep_commit.tar.gz")
            else
                dep_source=$(fetch_source_fresh "$dep_name" "$dep_commit" "$dep_sha" \
                    "$dep_repository")
            fi
            rm -rf "$staged_source/$dep_path"
            mkdir -p "$staged_source/$dep_path"
            cp -R "$dep_source/." "$staged_source/$dep_path/"
        done <<'DOLPHIN_DEPENDENCIES'
Externals/mGBA/mgba|https://github.com/mgba-emu/mgba|0b40863f64d0940f333fa1c638e75f86f8a26a33|9b59ed1422914f605ce912e9cafcd84d1c5b1bf9abcf0fef1b49e1d810f6f5e5
Externals/libusb/libusb|https://github.com/libusb/libusb|15a7ebb4d426c5ce196684347d2b7cafad862626|4ae78a9c6c540a3ccd7153c77e24947fa2ba50d845714bbbfccf8783832ed704
Externals/spirv_cross/SPIRV-Cross|https://github.com/KhronosGroup/SPIRV-Cross|ebe2aa0cd80f5eb5cd8a605da604cacf72205f3b|ff848426a2eabfa0dfb5ee961440210f6cdec190883ed438ee7252ba595c9128
Externals/zlib-ng/zlib-ng|https://github.com/zlib-ng/zlib-ng|ce01b1e41da298334f8214389cc9369540a7560f|64a6d355d2d5c9449fc047e5bb0ca32875fc385061dfaf1df3aa791577b7ff5e
Externals/libspng/libspng|https://github.com/randy408/libspng|fb768002d4288590083a476af628e51c3f1d47cd|d656813290d70a750b69e768323ff3b3875adf8c2e8c2fdb4e57ca1467abf86a
Externals/VulkanMemoryAllocator|https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator|3bab6924988e5f19bf36586a496156cf72f70d9f|618dc35e4f571a508575fc1fc914eb15ab513e4443986509aff08dfb8844ba24
Externals/cubeb/cubeb|https://github.com/mozilla/cubeb|54217bca3f3e0cd53c073690a23dd25d83557909|a795511bf56183ff7bad8fb2d2836ca5bb158e12ddd519caced62946ffa69c83
Externals/implot/implot|https://github.com/epezent/implot|3da8bd34299965d3b0ab124df743fe3e076fa222|4700b44ef00ca2feba0b35a31922c240045bbeb900da5b3eb3830b56871ada45
Externals/rcheevos/rcheevos|https://github.com/RetroAchievements/rcheevos|926e4608f8dca7989267c787bbefb3ab1c835ac5|11e5fc43c4676289ff4637c04a9f43070235006d826c363628dcb194d5182ebd
Externals/libadrenotools|https://github.com/bylaws/libadrenotools|8fae8ce254dfc1344527e05301e43f37dea2df80|ceffce971676d4cfdf348a082df06fc92a1dca6d95bea892a480d63f200961cb
Externals/libadrenotools/lib/linkernsbypass|https://github.com/bylaws/liblinkernsbypass|aa3975893d83ef1bc84c321ec60c65fbf1287887|da1128c8aa771c4d24766b53a47822d0717baa5c536ca8491220402942b80638
Externals/curl/curl|https://github.com/curl/curl|cfbfb65047e85e6b08af65fe9cdbcf68e9ad496a|fce60dc771129b50010a91efc575657550a83ce6b81eb4a77c4ebd0af44582c3
Externals/fmt/fmt|https://github.com/fmtlib/fmt|e424e3f2e607da02742f73db84873b8084fc714c|8e9b9d9e5b4d5e0a9094f349bec933f83e48a22e587bcf677534499fc5549202
Externals/lz4/lz4|https://github.com/lz4/lz4|5fc0630a0ed55e9755b0fe3990cd021ae1c3edc1|e969c292da59dd1163b3daabf31728f14f1dbe6a007e73e1cc6659fee6979bd2
Externals/xxhash/xxHash|https://github.com/Cyan4973/xxHash|e626a72bc2321cd320e953a0ccf1584cad60f363|34e71c085636fbc1726482996d92719d0a16e6a6097970ecf2990a27b3821162
Externals/enet/enet|https://github.com/lsalzman/enet|2662c0de09e36f2a2030ccc2c528a3e4c9e8138a|37381831c5ccbb41c3c71e867203fee847670f67717f297f930290d18985ad5f
Externals/hidapi/hidapi-src|https://github.com/libusb/hidapi|d6b2a974608dec3b76fb1e36c189f22b9cf3650c|a93a9bfb599831b82c6cef50f42359e0f5f31abfc8f6954862c328a464cbc4d0
Externals/tinygltf/tinygltf|https://github.com/syoyo/tinygltf|c5641f2c22d117da7971504591a8f6a41ece488b|6352803f1ed18d479ea93abf96ac75c0222a21403be22840bde1072ee5935dfa
Externals/minizip-ng/minizip-ng|https://github.com/zlib-ng/minizip-ng|55db144e03027b43263e5ebcb599bf0878ba58de|e0fa42896ad244261f100fd06fae7c64f6054ce02d143f4d0f55df5fced9f63d
Externals/Vulkan-Headers|https://github.com/KhronosGroup/Vulkan-Headers|39f924b810e561fd86b2558b6711ca68d4363f68|8c5a5dae1baf6b8eabe6eb04625940eac8af4f1bf3ae3121c28dbc1583d36553
Externals/watcher/watcher|https://github.com/e-dant/watcher|b03bdcfc11549df595b77239cefe2643943a3e2f|61e97c12c3d23f2b6588d99ce61c8ad462b4382f979d14c7a338a11af507edd1
Externals/zstd/zstd|https://github.com/facebook/zstd|711e17da98510a3567bf47f85a08a76f64811474|68458484cdc8c1e5aa6a2bf3a0253eedb1db9387e42bfb80598e392553162cee
Externals/miniupnpc/miniupnp|https://github.com/miniupnp/miniupnp|bf4215a7574f88aa55859db9db00e3ae58cf42d6|213a37a83f1b77a3c4f90b4dad70a5d2460d1b1042d3b0b4aef20234ae809add
Externals/glslang/glslang|https://github.com/KhronosGroup/glslang|a57276bf558f5cf94d3a9854ebdf5a2236849a5a|02f4321a3ed01b9a9a9874f76e2d8ad078825818fcc9aae12dbf2c01674fb8af
Externals/pugixml/pugixml|https://github.com/zeux/pugixml|ee86beb30e4973f5feffe3ce63bfa4fbadf72f38|51c102d4187fac99daa38af281b0772c5e6c586f65004cdc63f8f2e011a21492
Externals/cpp-ipc/cpp-ipc|https://github.com/mutouyun/cpp-ipc|ce0773b3e6d5abaa8d104100c5704321113853ca|01613a09deb56de754d5f3b284cb7d21c7286dbb61cd148f26515b1a0bd04d79
Externals/cpp-optparse/cpp-optparse|https://github.com/weisslj/cpp-optparse|2265d647232249a53a03b411099863ceca35f0d3|6f38fff3c4d2788eead7a28626b3220cc4c101510fc984678ad55f77756b107e
Externals/bzip2/bzip2|https://gitlab.com/bzip2/bzip2|6a8690fc8d26c815e798c588f796eabe9d684cf0|bc40651201886d3e126a8fff33163076e65918d422ce1f18749362984a8ce01d
Externals/imgui/imgui|https://github.com/ocornut/imgui|45acd5e0e82f4c954432533ae9985ff0e1aad6d5|97484925aec2f4d3e913d6644d46b234f8d6d8d98c6aa9c50109e0f0df772090
Externals/SFML/SFML|https://github.com/SFML/SFML|0fa201c969e48ecc253581c5841ce73f44d42f49|df03afdc2858d0e15e1c9ff06bddd113c18b2a6c089532f5b8d05dbb2e653f2a
DOLPHIN_DEPENDENCIES

        dolphin_git_shim="$ROOT/engines/tools/dolphin-git-shim/git"
        expected_dolphin_git_shim_sha=7f0591b727b7961b72092778de867b3c4498b1fe3eb935fa38bb47a9cf6a462c
        actual_dolphin_git_shim_sha=$(shasum -a 256 "$dolphin_git_shim" | awk '{print $1}')
        if [ "$actual_dolphin_git_shim_sha" != "$expected_dolphin_git_shim_sha" ]; then
            printf 'Dolphin Git identity shim mismatch: %s\n' \
                "$actual_dolphin_git_shim_sha" >&2
            exit 1
        fi
        dolphin_git_path=$(dirname "$dolphin_git_shim")

        dolphin_api=26
        mkdir -p "$out"
        PATH="$dolphin_git_path:$PATH" SOURCE_DATE_EPOCH=1785987178 \
            "$dolphin_cmake" -S "$staged_source" -B "$out" -G Ninja \
            -DCMAKE_MAKE_PROGRAM="$dolphin_ninja" \
            -DCMAKE_TOOLCHAIN_FILE="$dolphin_ndk_dir/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$dolphin_api" \
            -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release -DLIBRETRO=ON \
            -DUSE_SYSTEM_LIBS=AUTO -DENABLE_CUBEB=OFF -DENABLE_VULKAN=ON \
            -DUSE_UPNP=OFF -DUSE_MGBA=ON -DUSE_RETRO_ACHIEVEMENTS=OFF \
            -DENABLE_TESTS=OFF -DENABLE_SDL=OFF -DENABLE_QT=OFF \
            -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384"
        PATH="$dolphin_git_path:$PATH" SOURCE_DATE_EPOCH=1785987178 \
            "$dolphin_cmake" --build "$out" \
            --target dolphin_libretro \
            -j"${LUCENT_BUILD_JOBS:-4}"
        host=darwin-x86_64
        [ "$(uname -s)" = Linux ] && host=linux-x86_64
        dolphin_strip="$dolphin_ndk_dir/toolchains/llvm/prebuilt/$host/bin/llvm-strip"
        dolphin_objcopy="$dolphin_ndk_dir/toolchains/llvm/prebuilt/$host/bin/llvm-objcopy"
        raw_core="$out/dolphin_libretro_android.so"
        candidate_dir=$(mktemp -d "$OUTPUT_DIR/.dolphin-candidate.XXXXXX")
        stripped_core="$candidate_dir/dolphin_libretro.stripped.so"
        normalized_core="$candidate_dir/dolphin_libretro.so"
        "$dolphin_strip" --strip-unneeded "$raw_core" -o "$stripped_core"
        "$dolphin_objcopy" --remove-section=.note.gnu.build-id \
            "$stripped_core" "$normalized_core"
        rm -f "$stripped_core"
        normalized_sha=$(shasum -a 256 "$normalized_core" | awk '{print $1}')
        if [ "$normalized_sha" != \
                12fecae4b12872ff80d6c677cbb2c65504cae439d86e0cad204cd1166642c6a6 ]; then
            printf 'Normalized Dolphin core checksum mismatch: %s\n' \
                "$normalized_sha" >&2
            rm -rf "$candidate_dir"
            exit 1
        fi
        # Publish only after the candidate passes its exact checksum.  A
        # failed verification can never clobber a previously qualified core.
        mv "$normalized_core" "$OUTPUT_DIR/dolphin_libretro.so"
        rm -rf "$candidate_dir"
        cp "$staged_source/COPYING" "$OUTPUT_DIR/dolphin-LICENSE.txt"
        rm -rf "$OUTPUT_DIR/dolphin-system"
        mkdir -p "$OUTPUT_DIR/dolphin-system/dolphin-emu"
        cp -R "$staged_source/Data/Sys/." \
            "$OUTPUT_DIR/dolphin-system/dolphin-emu/Sys/"
        ;;
    ppsspp)
        # This uses PPSSPP's own libretro adapter behind Lucent's host; it does
        # not import RetroArch frontend code.  Production compatibility keeps
        # PPSSPP's exact FFmpeg gitlink enabled.  Its complete source/build
        # controls and only the Android ARM64 prebuilt inputs are sparse-fetched
        # and checked as one file-level SHA-256 closure.
        #
        # This recipe deliberately ignores the generic CMAKE, NINJA,
        # CMAKE_VERSION, NDK_VERSION, and ANDROID_NDK_ROOT overrides above.
        # PPSSPP's proof is tied to the exact checked toolchain identities
        # below.  A build using another host toolchain must earn a separate
        # lock entry and reproducibility proof.
        if [ "$ABI" != arm64-v8a ] || [ "$API" != 23 ]; then
            printf 'PPSSPP proof requires ABI arm64-v8a and API 23\n' >&2
            exit 1
        fi
        ppsspp_ndk_dir="$SDK_DIR/ndk/27.0.12077973"
        ppsspp_cmake="$SDK_DIR/cmake/3.31.6/bin/cmake"
        ppsspp_ninja="$SDK_DIR/cmake/3.31.6/bin/ninja"
        expected_ppsspp_ndk_sha=1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515
        expected_ppsspp_cmake_sha=94d4a3ce9e70cd9dae26e5fc7bb6ff4de67c58759762d4118a96ad2bc1b76be8
        expected_ppsspp_ninja_sha=3d508e91d5c159986bea2a472b1bfa849909da133aa05582a7174d33328af933
        if [ "$(uname -s)" != Darwin ]; then
            printf 'PPSSPP proof currently pins the Darwin CMake/Ninja toolchain only\n' >&2
            exit 1
        fi
        for required in \
            "$ppsspp_ndk_dir/source.properties" \
            "$ppsspp_cmake" \
            "$ppsspp_ninja"
        do
            if [ ! -f "$required" ]; then
                printf 'Missing pinned PPSSPP toolchain input: %s\n' "$required" >&2
                exit 1
            fi
        done
        actual_ppsspp_ndk_sha=$(shasum -a 256 \
            "$ppsspp_ndk_dir/source.properties" | awk '{print $1}')
        actual_ppsspp_cmake_sha=$(shasum -a 256 "$ppsspp_cmake" | awk '{print $1}')
        actual_ppsspp_ninja_sha=$(shasum -a 256 "$ppsspp_ninja" | awk '{print $1}')
        if [ "$actual_ppsspp_ndk_sha" != "$expected_ppsspp_ndk_sha" ] || \
            [ "$actual_ppsspp_cmake_sha" != "$expected_ppsspp_cmake_sha" ] || \
            [ "$actual_ppsspp_ninja_sha" != "$expected_ppsspp_ninja_sha" ]; then
            printf 'PPSSPP toolchain identity mismatch (NDK=%s CMake=%s Ninja=%s)\n' \
                "$actual_ppsspp_ndk_sha" "$actual_ppsspp_cmake_sha" \
                "$actual_ppsspp_ninja_sha" >&2
            exit 1
        fi
        # Source extraction is intentionally destructive within BUILD_ROOT.
        # Serialize builds that share that root so concurrent runs cannot
        # remove one another's staged inputs.  Callers may instead provide a
        # distinct LUCENT_ENGINE_BUILD_DIR for an isolated build root.
        ppsspp_lock_dir="$BUILD_ROOT/locks/ppsspp"
        ppsspp_candidate_dir=
        mkdir -p "$BUILD_ROOT/locks"
        if ! mkdir "$ppsspp_lock_dir" 2>/dev/null; then
            printf 'Another PPSSPP build owns %s; use a unique LUCENT_ENGINE_BUILD_DIR or wait\n' \
                "$ppsspp_lock_dir" >&2
            exit 1
        fi
        printf '%s\n' "$$" > "$ppsspp_lock_dir/pid"
        cleanup_ppsspp_lock() {
            if [ -n "$ppsspp_candidate_dir" ]; then
                rm -rf "$ppsspp_candidate_dir"
            fi
            rm -f "$ppsspp_lock_dir/pid"
            rmdir "$ppsspp_lock_dir" 2>/dev/null || true
        }
        trap cleanup_ppsspp_lock 0
        trap 'exit 129' 1
        trap 'exit 130' 2
        trap 'exit 143' 15

        commit=fa50bb1976065c4f8b1b47af227d367fe9771555
        source=$(fetch_source_fresh ppsspp "$commit" \
            9054138072d49c306d65c17059bd85662b4ff46abe1ea6bb53d854dc80592ea6 \
            https://github.com/hrydgard/ppsspp)
        spirv_cross=$(fetch_source_fresh ppsspp-SPIRV-Cross \
            4212eef67ed0ca048cb726a6767185504e7695e5 \
            a7adf77b5680795302aee160309c6cb81b0da341d92bd7face01f9a156b65aeb \
            https://github.com/KhronosGroup/SPIRV-Cross)
        aemu_postoffice=$(fetch_source_fresh ppsspp-aemu-postoffice \
            530fee545c27ffb8524a8f496cbbcfdb687fe8c5 \
            b3eb2372c5f4f611ab66e3b596be7ba12fe96b9bb347e7b2bcd4d7c979363e53 \
            https://github.com/Kethen/aemu_postoffice)
        armips=$(fetch_source_fresh ppsspp-armips \
            a8d71f0f279eb0d30ecf6af51473b66ae0cf8e8d \
            a520df5b673fc1649661f8506ddf35f62fb55e05d9f5a6c44b4d807b6aab3fbd \
            https://github.com/Kingcom/armips)
        filesystem=$(fetch_source_fresh ppsspp-filesystem \
            3f1c185ab414e764c694b8171d1c4d8c5c437517 \
            cc1c5439d29031477868bdea25b68b4210dc8ed018bb63a65e708afe405db4e1 \
            https://github.com/Kingcom/filesystem)
        cpu_features=$(fetch_source_fresh ppsspp-cpu-features \
            fd4ffc1632db7b4e763bd28ffa6fc9d761cf3587 \
            60b2e0e7adfbf40f0c69fb77ad197440a8435532285a83b19f99b4f886cca67a \
            https://github.com/google/cpu_features)
        glslang=$(fetch_source_fresh ppsspp-glslang \
            50e0708ec3a5c16020c4f845c654b80b8edb80bd \
            15941716c09bdb476e8eefcec24b8c8359e5e7bca3bfebe648b6a2206689c485 \
            https://github.com/hrydgard/glslang)
        libadrenotools=$(fetch_source_fresh ppsspp-libadrenotools \
            8fae8ce254dfc1344527e05301e43f37dea2df80 \
            ceffce971676d4cfdf348a082df06fc92a1dca6d95bea892a480d63f200961cb \
            https://github.com/bylaws/libadrenotools)
        linkernsbypass=$(fetch_source_fresh ppsspp-liblinkernsbypass \
            aa3975893d83ef1bc84c321ec60c65fbf1287887 \
            da1128c8aa771c4d24766b53a47822d0717baa5c536ca8491220402942b80638 \
            https://github.com/bylaws/liblinkernsbypass)
        libchdr=$(fetch_source_fresh ppsspp-libchdr \
            8bba7745d758627258b315997a860039244cedaf \
            169e3d2edf86d5501434301fa2505319ebd40aae83d4a5eedf05f6becbf13a3b \
            https://github.com/rtissera/libchdr)
        lua=$(fetch_source_fresh ppsspp-lua \
            7648485f14e8e5ee45e8e39b1eb4d3206dbd405a \
            ee31027159979d7be564e19710e10339179992f6d663d38337e78340dd31987b \
            https://github.com/hrydgard/ppsspp-lua)
        miniupnp=$(fetch_source_fresh ppsspp-miniupnp \
            27d13ca9beeb5541f5fbf11959dced03dac39972 \
            a07a32b2db1f6c5f2823847d47ba6e326b08fbcfe78690801fda9c3aeddf25a3 \
            https://github.com/miniupnp/miniupnp)
        naett=$(fetch_source_fresh ppsspp-naett \
            5f695cfa9fcbf30668a4d3ac4b4abf1cd89a1302 \
            65b68d645290ecd7478747d52feebf73b390021137a10897cc2a692bf6446afe \
            https://github.com/erkkah/naett)
        openxr=$(fetch_source_fresh ppsspp-OpenXR-SDK \
            be392bf6949adeeabad5082aa79d12aacbda781f \
            f91007ec5cd5380184678cb282353a6b97b6ba2278ef4911e217472186a31762 \
            https://github.com/KhronosGroup/OpenXR-SDK)
        rapidjson=$(fetch_source_fresh ppsspp-rapidjson \
            73063f5002612c6bf64fe24f851cd5cc0d83eef9 \
            896eb817fb2bc62a0a84ca65fac3e3c385b410e6dbf70d69c411e25776663e39 \
            https://github.com/Tencent/rapidjson)
        rcheevos=$(fetch_source_fresh ppsspp-rcheevos \
            ebfe8ca1bf944358e27200d66964fcb4e00e2487 \
            5a5afc951f1d485acd1b532a104a2a73b859a359ac0563704b1911c862c3854e \
            https://github.com/RetroAchievements/rcheevos)
        zstd=$(fetch_source_fresh ppsspp-zstd \
            f8745da6ff1ad1e7bab384bd1f9d742439278e99 \
            4b0bd1f0cfb25e61b9103c35f27395530ff5b4c0d2513a00fd745849e85ea52c \
            https://github.com/facebook/zstd)
        libretro_common=$(fetch_source_fresh ppsspp-libretro-common \
            76a3d54feb0ee0ce9d59b90aa24694f3782063d3 \
            da3c61d2d47df12536a7977443387c1c3d7a750fe8c916c943860788b590db7e \
            https://github.com/libretro/libretro-common)
        ppsspp_use_ffmpeg=ON
        ffmpeg_commit=1e3b4965632f60b1d85360261d1b9dd45444bc71
        ffmpeg=$(fetch_ppsspp_ffmpeg_fresh "$ffmpeg_commit" 3381 \
            93b942daa799dedf4f7a1a3f143c081c1945f2a67b7d13717f9fbb5c0ef4dd51 \
            https://github.com/hrydgard/ppsspp-ffmpeg.git)
        for ffmpeg_input in \
            libavcodec.a:12932e1719efb45ce1298841b3f65b7e99fff07cad8f7403efba4a7fdcf1948d \
            libavformat.a:d00ec5483c7049032c86a3d293dc23d3440b454eb93c8e7e6662481821ba5b60 \
            libavutil.a:876e4c820646f5de1de63fcc6f362c57049de9837bc00d05b12dc6a57954ccca \
            libswresample.a:d5480c4b18b4fc1aeb537af8934ddae52e167e5b8b6bdec8f67176beebced162 \
            libswscale.a:7cfc492242f0ddccdc7a9cd60fe5809070a41b719c7c0d98132e15d31d07e03c
        do
            ffmpeg_name=${ffmpeg_input%%:*}
            expected_ffmpeg_sha=${ffmpeg_input#*:}
            actual_ffmpeg_sha=$(shasum -a 256 \
                "$ffmpeg/android/arm64/lib/$ffmpeg_name" | awk '{print $1}')
            if [ "$actual_ffmpeg_sha" != "$expected_ffmpeg_sha" ]; then
                printf 'PPSSPP FFmpeg input mismatch for %s: %s\n' \
                    "$ffmpeg_name" "$actual_ffmpeg_sha" >&2
                exit 1
            fi
        done

        host=darwin-x86_64
        ppsspp_tool_bin="$ppsspp_ndk_dir/toolchains/llvm/prebuilt/$host/bin"
        strip="$ppsspp_tool_bin/llvm-strip"
        objcopy="$ppsspp_tool_bin/llvm-objcopy"
        readelf="$ppsspp_tool_bin/llvm-readelf"
        nm="$ppsspp_tool_bin/llvm-nm"
        for locked_tool in \
            "$strip:ee9c7fafc3fa353fa2720450921aafa124a00d5074d348d72e216eb47e52befa" \
            "$objcopy:ee9c7fafc3fa353fa2720450921aafa124a00d5074d348d72e216eb47e52befa" \
            "$readelf:412cf6d6533d64fc098af2ad69c5b12574b675289efd3d30a1a8701c83f164d2" \
            "$nm:84da402b6e155ab5979a070bdfa9e4fe840cacc6a092b302a08f68d9b3e1966d"
        do
            locked_tool_path=${locked_tool%%:*}
            locked_tool_sha=${locked_tool#*:}
            actual_tool_sha=$(shasum -a 256 "$locked_tool_path" | awk '{print $1}')
            if [ "$actual_tool_sha" != "$locked_tool_sha" ]; then
                printf 'PPSSPP ELF tool identity mismatch for %s: %s\n' \
                    "$locked_tool_path" "$actual_tool_sha" >&2
                exit 1
            fi
        done
        source_date_epoch=1778934711
        build="$BUILD_ROOT/work/ppsspp-$ABI"
        staged_source="$build/source"
        path_map_flags="-ffile-prefix-map=$ROOT=. -fdebug-prefix-map=$ROOT=. -fmacro-prefix-map=$ROOT=. -ffile-prefix-map=$build=ppsspp-build -fdebug-prefix-map=$build=ppsspp-build -fmacro-prefix-map=$build=ppsspp-build -ffile-prefix-map=$staged_source=ppsspp-source -fdebug-prefix-map=$staged_source=ppsspp-source -fmacro-prefix-map=$staged_source=ppsspp-source"
        rm -rf "$build"
        mkdir -p "$staged_source"
        cp -R "$source/." "$staged_source/"
        patch_path="$ROOT/engines/patches/ppsspp-pin-version-without-git.patch"
        expected_patch_sha=a4029bd6a82ff26f8b6d8c3e7d519342fbbae685c0d266cc77045393b2287e99
        actual_patch_sha=$(shasum -a 256 "$patch_path" | awk '{print $1}')
        if [ "$actual_patch_sha" != "$expected_patch_sha" ]; then
            printf 'Pinned PPSSPP patch checksum mismatch: %s\n' \
                "$actual_patch_sha" >&2
            exit 1
        fi
        patch -s -d "$staged_source" -p1 \
            < "$patch_path"
        for mapping in \
            "$spirv_cross:ext/SPIRV-Cross" \
            "$aemu_postoffice:ext/aemu_postoffice" \
            "$armips:ext/armips" \
            "$cpu_features:ext/cpu_features" \
            "$glslang:ext/glslang" \
            "$libadrenotools:ext/libadrenotools" \
            "$libchdr:ext/libchdr" \
            "$lua:ext/lua" \
            "$miniupnp:ext/miniupnp" \
            "$naett:ext/naett" \
            "$openxr:ext/OpenXR-SDK" \
            "$rapidjson:ext/rapidjson" \
            "$rcheevos:ext/rcheevos" \
            "$zstd:ext/zstd" \
            "$libretro_common:libretro/libretro-common"
        do
            dependency=${mapping%%:*}
            destination=${mapping#*:}
            rm -rf "$staged_source/$destination"
            mkdir -p "$(dirname "$staged_source/$destination")"
            cp -R "$dependency" "$staged_source/$destination"
        done
        rm -rf "$staged_source/ext/armips/ext/filesystem"
        cp -R "$filesystem" "$staged_source/ext/armips/ext/filesystem"
        rm -rf "$staged_source/ext/libadrenotools/lib/linkernsbypass"
        cp -R "$linkernsbypass" \
            "$staged_source/ext/libadrenotools/lib/linkernsbypass"
        rm -rf "$staged_source/ffmpeg"
        cp -R "$ffmpeg" "$staged_source/ffmpeg"

        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$source_date_epoch" \
        "$ppsspp_cmake" -S "$staged_source" -B "$build" -G Ninja \
            -DCMAKE_MAKE_PROGRAM="$ppsspp_ninja" \
            -DCMAKE_TOOLCHAIN_FILE="$ppsspp_ndk_dir/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API" \
            -DCMAKE_BUILD_TYPE=Release -DLIBRETRO=ON -DHEADLESS=OFF \
            -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DCMAKE_MODULE_LINKER_FLAGS="-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384" \
            -DCMAKE_C_FLAGS="$path_map_flags" \
            -DCMAKE_CXX_FLAGS="$path_map_flags" \
            -DATLAS_TOOL=OFF -DUNITTEST=OFF -DUSE_FFMPEG="$ppsspp_use_ffmpeg" \
            -DUSE_MINIUPNPC=OFF -DUSE_DISCORD=OFF -DOPENXR=OFF \
            -DUSE_CCACHE=OFF -DUSE_SYSTEM_LIBPNG=OFF \
            -DUSE_SYSTEM_ZSTD=OFF -DUSE_SYSTEM_LIBCHDR=OFF \
            -DUSE_SYSTEM_RAPIDJSON=OFF
        LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$source_date_epoch" \
        "$ppsspp_cmake" --build "$build" --target ppsspp_libretro \
            -j"${LUCENT_BUILD_JOBS:-4}"
        # LLD's default build-ID note varies with the absolute build root even
        # when the linked payload is byte-identical.  Remove only that note,
        # then gate the normalized ELF before publishing any canonical file.
        ppsspp_candidate_dir=$(mktemp -d "$OUTPUT_DIR/.ppsspp-candidate.XXXXXX")
        stripped_core="$ppsspp_candidate_dir/ppsspp_libretro.stripped.so"
        normalized_core="$ppsspp_candidate_dir/ppsspp_libretro.so"
        "$strip" --strip-unneeded "$build/ppsspp_libretro_android.so" \
            -o "$stripped_core"
        "$objcopy" --remove-section=.note.gnu.build-id \
            "$stripped_core" "$normalized_core"
        rm -f "$stripped_core"
        normalized_sha=$(shasum -a 256 "$normalized_core" | awk '{print $1}')
        expected_normalized_sha=376659948724e422876d31d61cc5dd130bfe5a2e941d64c6bf4225c2f2a23c6d
        if [ "$normalized_sha" != "$expected_normalized_sha" ]; then
            printf 'Normalized FFmpeg-enabled PPSSPP checksum mismatch: %s\n' \
                "$normalized_sha" >&2
            exit 1
        fi
        elf_header=$("$readelf" -h "$normalized_core")
        printf '%s\n' "$elf_header" | grep -q 'Class:.*ELF64'
        printf '%s\n' "$elf_header" | grep -q 'Type:.*DYN (Shared object file)'
        printf '%s\n' "$elf_header" | grep -q 'Machine:.*AArch64'
        if "$readelf" -S "$normalized_core" | grep -q '\.note\.gnu\.build-id'; then
            printf 'Normalized PPSSPP core still contains a GNU build-ID note\n' >&2
            exit 1
        fi
        actual_needed=$("$readelf" -d "$normalized_core" | \
            sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p' | LC_ALL=C sort)
        expected_needed=$(printf '%s\n' libc.so libdl.so libEGL.so libGLESv2.so \
            liblog.so libm.so libOpenSLES.so libandroid.so | LC_ALL=C sort)
        if [ "$actual_needed" != "$expected_needed" ]; then
            printf 'PPSSPP DT_NEEDED closure changed:\n%s\n' "$actual_needed" >&2
            exit 1
        fi
        defined_symbols_file="$ppsspp_candidate_dir/ppsspp-defined-symbols.txt"
        "$nm" -D --defined-only "$normalized_core" | awk '{print $3}' > \
            "$defined_symbols_file"
        for required_symbol in retro_api_version retro_deinit retro_get_system_av_info \
            retro_get_system_info retro_init retro_load_game retro_run \
            retro_serialize retro_serialize_size retro_set_audio_sample_batch \
            retro_set_environment retro_set_input_poll retro_set_input_state \
            retro_set_video_refresh retro_unload_game retro_unserialize
        do
            grep -qx "$required_symbol" "$defined_symbols_file" || {
                printf 'PPSSPP core is missing required export: %s\n' \
                    "$required_symbol" >&2
                exit 1
            }
        done
        rm -f "$defined_symbols_file"
        cp "$staged_source/LICENSE.TXT" \
            "$ppsspp_candidate_dir/ppsspp-LICENSE.txt"
        mkdir -p "$ppsspp_candidate_dir/ppsspp-system/PPSSPP"
        cp -R "$staged_source/assets/." \
            "$ppsspp_candidate_dir/ppsspp-system/PPSSPP/"
        python3 "$ROOT/tools/generate_ppsspp_compliance_bundle.py" \
            --source "$staged_source" \
            --build "$build" \
            --artifact "$normalized_core" \
            --audit "$ROOT/engines/ppsspp-dependency-audit.json" \
            --lock "$ROOT/engines/ppsspp-source-lock.json" \
            --repository "$ROOT" \
            --ninja "$ppsspp_ninja" \
            --ar "$ppsspp_tool_bin/llvm-ar" \
            --output "$ppsspp_candidate_dir/ppsspp-compliance"
        rm -rf "$OUTPUT_DIR/ppsspp-compliance" "$OUTPUT_DIR/ppsspp-system"
        mv "$ppsspp_candidate_dir/ppsspp-compliance" \
            "$OUTPUT_DIR/ppsspp-compliance"
        mv "$ppsspp_candidate_dir/ppsspp-system" "$OUTPUT_DIR/ppsspp-system"
        mv "$ppsspp_candidate_dir/ppsspp-LICENSE.txt" \
            "$OUTPUT_DIR/ppsspp-LICENSE.txt"
        # Publish the core last.  Every identity, ABI, dependency, export, and
        # corresponding-source gate above has succeeded at this point.
        mv "$normalized_core" "$OUTPUT_DIR/ppsspp_libretro.so"
        rmdir "$ppsspp_candidate_dir"
        ppsspp_candidate_dir=
        ;;
    mame)
        commit=85eaed9c22242206b68eaca8310cf0dbde331b43
        source_archive_sha=938efbe6bdd2d6e54fad7d9d53e93e9b09a0a708243e5929c286f21b1438833f
        source=$(fetch_source mame "$commit" \
            "$source_archive_sha" \
            https://github.com/libretro/mame)
        case "$ABI" in
            arm64-v8a) platform=android-arm64 ;;
            *) printf 'MAME recipe currently supports arm64-v8a only\n' >&2; exit 1 ;;
        esac
        # Keep the Phase 1 binary bounded to the mapped systems. The three
        # driver translation units pull their complete dependency closure via
        # MAME's makedep generator; no commercial ROM or BIOS data is embedded.
        sources=src/mame/atari/pong.cpp,src/mame/snk/neogeo.cpp,src/mame/snk/neogeocd.cpp
        subtarget=lucent
        # This core is large enough that rebuilding it for every qualification
        # APK is counterproductive. Reuse is deliberately stricter than a
        # timestamp check: source archive, upstream makefile, recipe revision,
        # ABI/API, exact NDK metadata and the output itself are all pinned.
        # A stale or locally modified binary can therefore never enter cache.
        expected_makefile_sha=08e3e6f9e21ea6ec1c9d9b0882f576a9abb03aa5aeeeefb3ad8bc4a3f13d96de
        expected_ndk_sha=1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515
        expected_core_sha=1160d48a52f0271e3a83bb57498fe5f86069336be6eb175be9d3842795fc0d07
        actual_makefile_sha=$(shasum -a 256 "$source/Makefile.libretro" | awk '{print $1}')
        actual_ndk_sha=$(shasum -a 256 "$NDK_DIR/source.properties" | awk '{print $1}')
        if [ "$actual_makefile_sha" != "$expected_makefile_sha" ]; then
            printf 'Pinned MAME Makefile checksum mismatch: %s\n' "$actual_makefile_sha" >&2
            exit 1
        fi
        if [ "$actual_ndk_sha" != "$expected_ndk_sha" ]; then
            printf 'MAME recipe requires the exact qualified NDK metadata (27.0.12077973); found %s\n' "$actual_ndk_sha" >&2
            exit 1
        fi
        identity=$(printf '%s\n' \
            "sourceCommit=$commit" \
            "sourceArchiveSha256=$source_archive_sha" \
            "makefileSha256=$actual_makefile_sha" \
            "ndkSourcePropertiesSha256=$actual_ndk_sha" \
            "abi=$ABI" \
            "api=$API" \
            "platform=$platform" \
            "subtarget=$subtarget" \
            "sources=$sources" \
            "recipeRevision=3" \
            "elfMaxPageSize=16384" \
            "elfCommonPageSize=16384" | shasum -a 256 | awk '{print $1}')
        cache_dir="$BUILD_ROOT/cache/mame/$identity"
        cache_core="$cache_dir/mame_libretro.so"
        cache_identity="$cache_dir/build-fingerprint.sha256"
        output_core="$OUTPUT_DIR/mame_libretro.so"
        if [ "${LUCENT_FORCE_REBUILD:-0}" != 1 ]; then
            for candidate in "$output_core" "$cache_core"; do
                if [ -f "$candidate" ] && \
                    [ "$(shasum -a 256 "$candidate" | awk '{print $1}')" = "$expected_core_sha" ]; then
                    mkdir -p "$cache_dir"
                    if [ "$candidate" != "$output_core" ]; then
                        cp "$candidate" "$output_core"
                    fi
                    if [ "$candidate" != "$cache_core" ]; then
                        cp "$candidate" "$cache_core"
                    fi
                    printf '%s\n' "$identity" > "$cache_identity"
                    printf 'Reusing checksum-qualified MAME core (%s). Set LUCENT_FORCE_REBUILD=1 to rebuild.\n' "$identity" >&2
                    printf '%s\n' "$output_core"
                    exit 0
                fi
            done
        fi
        ANDROID_NDK_HOME="$NDK_DIR" ANDROID_NDK_ROOT="$NDK_DIR" \
            /usr/bin/make -C "$source" -f Makefile.libretro clean \
                platform="$platform" ARCHITECTURE= \
                SUBTARGET="$subtarget" SOURCES="$sources"
        ANDROID_NDK_HOME="$NDK_DIR" ANDROID_NDK_ROOT="$NDK_DIR" \
            /usr/bin/make -C "$source" -f Makefile.libretro \
                -j"${LUCENT_BUILD_JOBS:-4}" platform="$platform" \
                ARCHITECTURE= \
                SUBTARGET="$subtarget" SOURCES="$sources" \
                LDOPTS='-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384' \
                PYTHON_EXECUTABLE=python3
        # Makefile.libretro inherits the host suffix on macOS even though the
        # linker target and resulting file are Android AArch64 ELF. Accept the
        # mislabeled upstream suffix and normalize Lucent's staged filename.
        built=$(find "$source" -type f \( \
            -name "${subtarget}_libretro_android.so" -o \
            -name "${subtarget}_libretro_android.dylib" \
            \) -print | head -n 1)
        if [ -z "$built" ]; then
            printf 'MAME build completed without an Android libretro artifact for %s\n' "$subtarget" >&2
            exit 1
        fi
        built_sha=$(shasum -a 256 "$built" | awk '{print $1}')
        if [ "$built_sha" != "$expected_core_sha" ]; then
            printf 'MAME output checksum mismatch: expected %s, got %s\n' \
                "$expected_core_sha" "$built_sha" >&2
            exit 1
        fi
        mkdir -p "$cache_dir"
        cp "$built" "$output_core"
        cp "$built" "$cache_core"
        printf '%s\n' "$identity" > "$cache_identity"
        ;;
    *)
        printf 'usage: %s {beetle-pce-fast|beetle-neopop|beetle-cygne|beetle-vb|prosystem|dosbox-pure|melonds-ds|swanstation|mgba|mesen|mesen-s|sameboy|gearsystem|gearcoleco|freeintv|fuse|armsx2|play|flycast|virtualjaguar|dolphin|ppsspp|mame}\n' "$0" >&2
        exit 2
        ;;
esac

if [ "$ENGINE" = armsx2 ]; then
    printf '%s\n' "$OUTPUT_DIR/armsx2${armsx2_variant_suffix}_libretro.so"
else
    printf '%s\n' "$OUTPUT_DIR/${ENGINE}_libretro.so"
fi
