#!/bin/sh
# Isolated Qt 5.15.10 / OpenSSL 1.1.1t source build for Android page portability.
# Qualification only: never copies libraries into an APK or normal staging.
set -eu
PROJECT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
QT_WORK=${LUCENT_QT_BUILD_ROOT:-$PROJECT/build/qt-5.15.10-16k}
SDK=${ANDROID_SDK_ROOT:-/Users/tyleryoung/Library/Android/sdk}
NDK=$SDK/ndk/27.0.12077973
LLVM=$NDK/toolchains/llvm/prebuilt/darwin-x86_64
QT_SOURCE=$QT_WORK/source/qtbase-everywhere-src-5.15.10
SSL_SOURCE=$QT_WORK/source/openssl-1.1.1t
ACTION=${1:-configure}
export ANDROID_NDK_ROOT="$NDK"
export ANDROID_NDK_HOME="$NDK"
export ANDROID_NDK_HOST=darwin-x86_64
export ANDROID_SDK_ROOT="$SDK"
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true'
export PATH="$LLVM/bin:$JAVA_HOME/bin:$PATH"

check_archive() {
    actual=$(shasum -a 256 "$QT_WORK/downloads/$1" | awk '{print $1}')
    [ "$actual" = "$2" ] || { printf 'Source checksum mismatch: %s\n' "$1" >&2; exit 1; }
}
check_archive qtbase-everywhere-opensource-src-5.15.10.tar.xz c0d06cb18d20f10bf7ad53552099e097ec39362d30a5d6f104724f55fa1c8fb9
check_archive openssl-1.1.1t.tar.gz 8dee9b24bdb1dcbf0c3d1e9b02fb8f6bf22165e807f45adeb7c9677536859d3b
test -x "$LLVM/bin/clang"

apply_source_patch() {
    # -f prevents patch from guessing the reverse direction and falsely
    # reporting that an unapplied patch is already present.
    if ! patch -f -d "$QT_SOURCE" -p1 --dry-run -R < "$PROJECT/tools/$1" >/dev/null 2>&1; then
        patch -f -d "$QT_SOURCE" -p1 --dry-run < "$PROJECT/tools/$1"
        patch -f -d "$QT_SOURCE" -p1 < "$PROJECT/tools/$1"
    fi
}

case "$ACTION" in
    configure)
        mkdir -p "$QT_WORK/build-base" "$QT_WORK/build-openssl" "$QT_WORK/source"
        [ -d "$QT_SOURCE" ] || tar -xf "$QT_WORK/downloads/qtbase-everywhere-opensource-src-5.15.10.tar.xz" -C "$QT_WORK/source"
        [ -d "$SSL_SOURCE" ] || tar -xf "$QT_WORK/downloads/openssl-1.1.1t.tar.gz" -C "$QT_WORK/source"
        # Retain host-tool flags unchanged. Only Android links need page layout.
        apply_source_patch qtbase-android-16k.patch
        apply_source_patch qtbase-ndk27-api.patch
        apply_source_patch qtbase-android-emulator-bgra.patch
        apply_source_patch qtbase-android-emulator-texture-upload.patch
        cd "$QT_WORK/build-openssl"
        perl "$SSL_SOURCE/Configure" android-arm64 -D__ANDROID_API__=23 shared no-tests \
            -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384 \
            --prefix="$QT_WORK/install-openssl" --openssldir="$QT_WORK/install-openssl/ssl"
        make -j4 build_generated
        cd "$QT_WORK/build-base"
        "$QT_SOURCE/configure" -opensource -confirm-license -release -shared \
            -platform macx-clang -xplatform android-clang -android-abis arm64-v8a \
            -android-sdk "$SDK" -android-ndk "$NDK" -android-ndk-host darwin-x86_64 \
            -android-ndk-platform android-23 -prefix "$QT_WORK/install" \
            -nomake tests -nomake examples -no-widgets -no-dbus -no-icu -no-pch \
            -opengl es2 -openssl-runtime \
            -I "$QT_WORK/build-openssl/include" -I "$SSL_SOURCE/include"
        ;;
    build)
        apply_source_patch qtbase-android-16k.patch
        apply_source_patch qtbase-ndk27-api.patch
        apply_source_patch qtbase-android-emulator-bgra.patch
        apply_source_patch qtbase-android-emulator-texture-upload.patch
        cd "$QT_WORK/build-openssl"
        make -j4 build_libs
        cd "$QT_WORK/build-base"
        make -j4
        ;;
    install-base)
        cd "$QT_WORK/build-openssl"
        make install_sw
        cd "$QT_WORK/build-base"
        make install
        ;;
    *) printf 'Usage: %s configure|build|install-base\n' "$0" >&2; exit 2 ;;
esac
