#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
SDK_DIR=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk}}
BUILD_TOOLS_VERSION=${BUILD_TOOLS_VERSION:-36.0.0}
ANDROID_PLATFORM=${ANDROID_PLATFORM:-android-36}
BUILD_TOOLS="$SDK_DIR/build-tools/$BUILD_TOOLS_VERSION"
ANDROID_JAR="$SDK_DIR/platforms/$ANDROID_PLATFORM/android.jar"
BUILD_DIR="$PROJECT_DIR/build"
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"
export PATH

mkdir -p "$BUILD_DIR/classes" "$BUILD_DIR/dex" "$BUILD_DIR/compiled-res"
rm -rf "$BUILD_DIR/classes"/* "$BUILD_DIR/dex"/* "$BUILD_DIR/compiled-res"/*
"$BUILD_TOOLS/aapt2" compile --dir "$PROJECT_DIR/res" \
    -o "$BUILD_DIR/compiled-res/resources.zip"
"$BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" \
    --manifest "$PROJECT_DIR/AndroidManifest.xml" \
    "$BUILD_DIR/compiled-res/resources.zip" \
    -o "$BUILD_DIR/unsigned.apk"
"$JAVA_HOME/bin/javac" -source 8 -target 8 -encoding UTF-8 \
    -classpath "$ANDROID_JAR" -d "$BUILD_DIR/classes" \
    $(find "$PROJECT_DIR/src" -name '*.java' -print)
"$BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --output "$BUILD_DIR/dex" \
    $(find "$BUILD_DIR/classes" -name '*.class' -print)
(cd "$BUILD_DIR/dex" && "$BUILD_TOOLS/aapt" add "$BUILD_DIR/unsigned.apk" classes.dex)
"$BUILD_TOOLS/zipalign" -f 4 "$BUILD_DIR/unsigned.apk" "$BUILD_DIR/aligned.apk"
"$BUILD_TOOLS/apksigner" sign \
    --ks "${LUCENT_CONTROLLER_KEYSTORE:-$BUILD_DIR/debug.keystore}" \
    --ks-pass "pass:${LUCENT_CONTROLLER_STORE_PASS:-android}" \
    --key-pass "pass:${LUCENT_CONTROLLER_KEY_PASS:-android}" \
    --out "$BUILD_DIR/emufusion-controller.apk" "$BUILD_DIR/aligned.apk"
"$BUILD_TOOLS/apksigner" verify --verbose "$BUILD_DIR/emufusion-controller.apk"
printf '%s\n' "$BUILD_DIR/emufusion-controller.apk"
