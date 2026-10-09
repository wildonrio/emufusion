#!/bin/sh
# Preserve the pinned frontend's APNG feature in a source-only rebuild.
set -eu
PROJECT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
QT_WORK=${LUCENT_QT_BUILD_ROOT:-$PROJECT/build/qt-5.15.10-16k}
SDK=${ANDROID_SDK_ROOT:-/Users/tyleryoung/Library/Android/sdk}
SOURCE=$QT_WORK/source/libpng-1.6.37
BUILD=$QT_WORK/build-apng
PATCH=$QT_WORK/downloads/libpng-1.6.37-apng.patch.gz
test "$(shasum -a 256 "$PATCH" | awk '{print $1}')" = 823bb2d1f09dc7dae4f91ff56d6c22b4b533e912cbd6c64e8762255e411100b6
test -f "$SOURCE/CMakeLists.txt"
if ! gzip -dc "$PATCH" | patch -f -d "$SOURCE" -p1 --dry-run -R >/dev/null 2>&1; then
    gzip -dc "$PATCH" | patch -f -d "$SOURCE" -p1 --dry-run
    gzip -dc "$PATCH" | patch -f -d "$SOURCE" -p1
fi
/opt/homebrew/bin/cmake -S "$SOURCE" -B "$BUILD" -G Ninja \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DCMAKE_MAKE_PROGRAM=/opt/homebrew/bin/ninja \
    -DCMAKE_TOOLCHAIN_FILE="$SDK/ndk/27.0.12077973/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=23 \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_C_FLAGS=-fvisibility=hidden \
    -DPNG_SHARED=OFF -DPNG_STATIC=ON -DPNG_TESTS=OFF -DPNG_EXECUTABLES=OFF
/opt/homebrew/bin/cmake --build "$BUILD" -j4
