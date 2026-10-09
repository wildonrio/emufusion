#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
SDK_DIR=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk}}
BUILD_TOOLS_VERSION=${BUILD_TOOLS_VERSION:-36.0.0}
ANDROID_PLATFORM=${ANDROID_PLATFORM:-android-36}
BUILD_TOOLS="$SDK_DIR/build-tools/$BUILD_TOOLS_VERSION"
ANDROID_JAR="$SDK_DIR/platforms/$ANDROID_PLATFORM/android.jar"
BUILD_DIR="$PROJECT_DIR/build"
DEPS_DIR="$BUILD_DIR/deps"
COMMONS_COMPRESS_JAR="$DEPS_DIR/commons-compress-1.21.jar"
XZ_JAR="$DEPS_DIR/xz-1.9.jar"
THEME_DIR=$(CDPATH= cd -- "$PROJECT_DIR/../theme" && pwd)
THEME_ARCHIVE="$PROJECT_DIR/assets/emufusion-theme.zip"
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"
export PATH

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

mkdir -p "$BUILD_DIR/classes" "$BUILD_DIR/dex"
# The companion and theme ship as one versioned unit. Always rebuild the
# embedded archive from source before aapt packages assets; a stale ZIP can
# otherwise report the new version while silently reinstalling old QML.
rm -f "$THEME_ARCHIVE.partial.zip"
(cd "$THEME_DIR" && /usr/bin/zip -q -r "$THEME_ARCHIVE.partial.zip" .)
mv "$THEME_ARCHIVE.partial.zip" "$THEME_ARCHIVE"
"$BUILD_TOOLS/aapt2" compile --dir "$PROJECT_DIR/res" -o "$BUILD_DIR/resources.zip"
"$BUILD_TOOLS/aapt2" link \
    -I "$ANDROID_JAR" \
    --manifest "$PROJECT_DIR/AndroidManifest.xml" \
    -A "$PROJECT_DIR/assets" \
    -o "$BUILD_DIR/unsigned.apk" \
    "$BUILD_DIR/resources.zip"

"$JAVA_HOME/bin/javac" -source 8 -target 8 -encoding UTF-8 \
    -classpath "$ANDROID_JAR:$COMMONS_COMPRESS_JAR:$XZ_JAR" \
    -d "$BUILD_DIR/classes" \
    $(find "$PROJECT_DIR/src" -name '*.java' -print)

"$BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --output "$BUILD_DIR/dex" \
    $(find "$BUILD_DIR/classes" -name '*.class' -print) \
    "$COMMONS_COMPRESS_JAR" "$XZ_JAR"
(cd "$BUILD_DIR/dex" && "$BUILD_TOOLS/aapt" add "$BUILD_DIR/unsigned.apk" classes.dex)
"$BUILD_TOOLS/zipalign" -f 4 "$BUILD_DIR/unsigned.apk" "$BUILD_DIR/aligned.apk"

KEYSTORE=${LUCENT_KEYSTORE:-$PROJECT_DIR/debug.keystore}
STORE_PASS=${LUCENT_STORE_PASS:-android}
KEY_PASS=${LUCENT_KEY_PASS:-$STORE_PASS}
KEY_ALIAS=${LUCENT_KEY_ALIAS:-androiddebugkey}
if [ ! -f "$KEYSTORE" ]; then
    "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$KEYSTORE" -storepass "$STORE_PASS" \
        -keypass "$KEY_PASS" -alias "$KEY_ALIAS" -dname 'CN=EmuFusion,O=WildOnRio,C=US' \
        -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
fi

"$BUILD_TOOLS/apksigner" sign \
    --ks "$KEYSTORE" --ks-pass "pass:$STORE_PASS" --key-pass "pass:$KEY_PASS" \
    --ks-key-alias "$KEY_ALIAS" --out "$BUILD_DIR/emufusion.apk" "$BUILD_DIR/aligned.apk"
"$BUILD_TOOLS/apksigner" verify --verbose "$BUILD_DIR/emufusion.apk"
printf '%s\n' "$BUILD_DIR/emufusion.apk"
