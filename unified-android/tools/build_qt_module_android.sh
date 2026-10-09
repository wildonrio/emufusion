#!/bin/sh
# Isolated matching Qt modules; does not replace any normal APK payload.
set -eu
PROJECT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
QT_WORK=${LUCENT_QT_BUILD_ROOT:-$PROJECT/build/qt-5.15.10-16k}
MODULE=${1:?Specify a pinned Qt module}
case "$MODULE" in
    qtdeclarative|qtandroidextras|qtgamepad|qtgraphicaleffects|qtmultimedia|qtsvg|qtimageformats|qtquicktimeline|qttools) ;;
    *) printf 'Unsupported module: %s\n' "$MODULE" >&2; exit 2 ;;
esac
SOURCE=$QT_WORK/source/$MODULE-everywhere-src-5.15.10
BUILD=$QT_WORK/build-$MODULE
QMAKE_PROJECT=$SOURCE/$MODULE.pro
SDK=${ANDROID_SDK_ROOT:-/Users/tyleryoung/Library/Android/sdk}
export ANDROID_NDK_ROOT="$SDK/ndk/27.0.12077973"
export ANDROID_NDK_HOME="$ANDROID_NDK_ROOT"
export ANDROID_NDK_HOST=darwin-x86_64
export ANDROID_SDK_ROOT="$SDK"
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true'
export PATH="$JAVA_HOME/bin:$PATH"
test -x "$QT_WORK/install/bin/qmake"
test -f "$QMAKE_PROJECT"
if [ "$MODULE" = qtgamepad ]; then
    PATCH=$PROJECT/tools/qtgamepad-android-null-guard.patch
    if ! patch -f -d "$SOURCE" -p1 --dry-run -R < "$PATCH" >/dev/null 2>&1; then
        patch -f -d "$SOURCE" -p1 --dry-run < "$PATCH"
        patch -f -d "$SOURCE" -p1 < "$PATCH"
    fi
fi
if [ "$MODULE" = qtdeclarative ]; then
    PATCH=$PROJECT/tools/qtdeclarative-android-emulator-bgra.patch
    if ! patch -f -d "$SOURCE" -p1 --dry-run -R < "$PATCH" >/dev/null 2>&1; then
        patch -f -d "$SOURCE" -p1 --dry-run < "$PATCH"
        patch -f -d "$SOURCE" -p1 < "$PATCH"
    fi
fi
mkdir -p "$BUILD"
cd "$BUILD"
"$QT_WORK/install/bin/qmake" "$QMAKE_PROJECT" 'QT_BUILD_PARTS=libs' 'ANDROID_ABIS=arm64-v8a'
make -j4
make install
