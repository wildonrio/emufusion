#!/bin/sh
# Compiles the working tree's EmuFusion Java into one dex for the replay bench
# (tools/qa/replay_bench.py --dex). Placed ahead of the installed APK on the
# replay process's CLASSPATH, it lets a generator change be scored without
# building or installing an APK. QA only; never packaged.
# usage: build_replay_dex.sh OUTPUT.dex [REPLACEMENT.java ...]
# A replacement compiles in place of the tree's file of the same name (a
# shader variant for the bench), leaving the working tree untouched.
set -eu
output=${1:?output dex path required}
shift
ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
PROJECT_DIR="$ROOT_DIR/unified-android"
SDK_DIR=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk}}
BUILD_TOOLS="$SDK_DIR/build-tools/${BUILD_TOOLS_VERSION:-36.0.0}"
ANDROID_JAR="$SDK_DIR/platforms/${ANDROID_PLATFORM:-android-36}/android.jar"
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
export JAVA_HOME PATH="$JAVA_HOME/bin:$PATH"
DEPS_DIR="$PROJECT_DIR/build/deps"
CLASSPATH_JARS="$ANDROID_JAR:$DEPS_DIR/commons-compress-1.21.jar:$DEPS_DIR/xz-1.9.jar"
CLASSPATH_JARS="$CLASSPATH_JARS:$DEPS_DIR/nv-websocket-client-2.14.jar"
CLASSPATH_JARS="$CLASSPATH_JARS:$DEPS_DIR/webrtc-android-150.7871.01/classes.jar"
work=$(mktemp -d "${TMPDIR:-/tmp}/emufusion-replay-dex.XXXXXX")
trap 'rm -rf "$work"' EXIT INT TERM
# The same source set as build.sh's dex, so the replay runs exactly what a
# build of this tree would ship.
SOURCES=$(find "$ROOT_DIR/android-companion/src" "$ROOT_DIR/android-launch-bridge/src" \
    "$PROJECT_DIR/src" "$PROJECT_DIR/stubs" -name '*.java' \
    ! -path '*/com/thorium/preview/MainActivity.java' \
    ! -path '*/com/thorium/launchbridge/LaunchActivity.java' \
    ! -path '*/com/thorium/launchbridge/RomFileProvider.java' \
    ! -path '*/com/thorium/launchbridge/StopButtonService.java' \
    ! -path '*/com/thorium/preview/game/InternalGameLaunchActivity.java' \
    ! -path '*/com/thorium/preview/game/EmuFusionGameActivity.java' \
    ! -path '*/com/thorium/preview/game/QualificationLaunchActivity.java' \
    ! -path '*/com/thorium/preview/game/SessionReturnRouter.java' -print)
for replacement in "$@"; do
    name=$(basename "$replacement")
    SOURCES=$(printf '%s\n' $SOURCES | grep -v "/$name\$")
    SOURCES="$SOURCES $replacement"
done
"$JAVA_HOME/bin/javac" -source 8 -target 8 -encoding UTF-8 -nowarn \
    -classpath "$CLASSPATH_JARS" -d "$work/classes" $SOURCES 2>&1 | grep -v '^Note:\|^warning:\|^1 warning' || true
test -f "$work/classes/com/thorium/preview/game/HoldoutReplay.class"
# The Qt stub's real class is in the APK's primary dex.
mkdir -p "$work/stub/org/qtproject/qt5/android/bindings"
mv "$work/classes/org/qtproject/qt5/android/bindings/QtApplication.class" \
    "$work/stub/org/qtproject/qt5/android/bindings/"
mkdir -p "$work/dex"
"$BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --classpath "$work/stub" --min-api 21 \
    $(printf ' --classpath %s' $(echo "${CLASSPATH_JARS#*:}" | tr ':' ' ')) \
    --output "$work/dex" $(find "$work/classes" -name '*.class') 2>&1 | grep -v '^Warning' || true
test -f "$work/dex/classes.dex"
cp "$work/dex/classes.dex" "$output"
echo "replay dex: $output ($(wc -c < "$output" | tr -d ' ') bytes)"
