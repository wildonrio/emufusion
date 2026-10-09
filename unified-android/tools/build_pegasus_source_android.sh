#!/bin/sh
# Build only the pinned frontend ELF against the isolated 16KiB Qt kit.
# Packaging, UI branding, Java/manifest integration and runtime acceptance remain
# separate gates; this script never modifies the installed/production APK.
set -eu
PROJECT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
QT_WORK=${LUCENT_QT_BUILD_ROOT:-$PROJECT/build/qt-5.15.10-16k}
REVISION=6b322063a036db60cba5810fda82a3ce38f1e62f
SOURCE=$QT_WORK/source/pegasus-frontend-$REVISION
BUILD=$QT_WORK/build-pegasus
SDK=${ANDROID_SDK_ROOT:-/Users/tyleryoung/Library/Android/sdk}
export ANDROID_NDK_ROOT="$SDK/ndk/27.0.12077973"
export ANDROID_NDK_HOME="$ANDROID_NDK_ROOT"
export ANDROID_NDK_HOST=darwin-x86_64
export ANDROID_SDK_ROOT="$SDK"
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true'
export PATH="$QT_WORK/install/bin:$JAVA_HOME/bin:$PATH"
test -x "$QT_WORK/install/bin/qmake"
test -x "$QT_WORK/install/bin/lrelease"
test -f "$QT_WORK/build-apng/libpng16.a"
test -f "$SOURCE/pegasus.pro"
if [ ! -d "$SOURCE/.git" ]; then
    # Add pinned commit metadata without checking out or replacing source files.
    git -C "$SOURCE" init
    git -C "$SOURCE" fetch --depth=1 https://github.com/mmatyas/pegasus-frontend.git "$REVISION"
    git -C "$SOURCE" update-ref HEAD "$REVISION"
    git -C "$SOURCE" read-tree HEAD
fi
test "$(git -C "$SOURCE" rev-parse HEAD)" = "$REVISION"
for patch_name in pegasus-in-window-source.patch pegasus-ndk27-headers.patch pegasus-apng-link.patch pegasus-android-storage-startup.patch; do
    PATCH=$PROJECT/tools/$patch_name
    if ! patch -f -d "$SOURCE" -p1 --dry-run -R < "$PATCH" >/dev/null 2>&1; then
        patch -f -d "$SOURCE" -p1 --dry-run < "$PATCH"
        patch -f -d "$SOURCE" -p1 < "$PATCH"
    fi
done
mkdir -p "$BUILD"
cd "$BUILD"
# Match upstream Android build options. Suppress only its standalone APK staging
# hook (GNU sed + external OpenSSL paths); unified EmuFusion packaging owns that.
"$QT_WORK/install/bin/qmake" -r "$SOURCE/pegasus.pro" \
    'ANDROID_ABIS=arm64-v8a' 'ENABLE_APNG=1' \
    "PNG_INCLUDES=$QT_WORK/source/libpng-1.6.37 $QT_WORK/build-apng" \
    "PNG_LIBS=$QT_WORK/build-apng/libpng16.a -lz" \
    -after 'QMAKE_POST_LINK='
make -j4
