#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
TEST_BUILD="$PROJECT_DIR/build/unit-tests"

rm -rf "$TEST_BUILD"
mkdir -p "$TEST_BUILD"

# Android adapters are compiled by build.sh. These host tests intentionally use
# only the platform-neutral state/input core and therefore need no device or SDK.
SOURCES=$(find "$PROJECT_DIR/src/com/thorium/lucent/state" \
    "$PROJECT_DIR/src/com/thorium/lucent/audio" \
    "$PROJECT_DIR/src/com/thorium/lucent/input" \
    "$PROJECT_DIR/src/com/thorium/lucent/navigation" \
    "$PROJECT_DIR/src/com/thorium/lucent/metadata" \
    "$PROJECT_DIR/src/com/thorium/lucent/timing" \
    "$PROJECT_DIR/src/com/thorium/lucent/video" \
    "$PROJECT_DIR/src/com/thorium/lucent/cheats" \
    "$PROJECT_DIR/src/com/thorium/lucent/emulators" \
    "$PROJECT_DIR/src/com/thorium/lucent/legal" "$PROJECT_DIR/test" \
    -name '*.java' ! -path '*/input/android/*' \
    ! -name 'RightStickMotionBridge.java' -print)
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/cheats/CheatArchive.java"
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/game/DenseGpuTimer.java"
"$JAVA_HOME/bin/javac" --release 8 -encoding UTF-8 \
    -d "$TEST_BUILD" $SOURCES
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.lucent.state.StateVaultTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.lucent.audio.PcmAudioQueueTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.lucent.audio.PcmSignalTelemetryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.lucent.input.InputRouterTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.input.LibretroJoypadLayoutTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.input.JoypadPressLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.input.WiiIrPointerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.navigation.RightStickViewRouterTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.timing.AbsoluteFramePacerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.timing.LatestValueMailboxTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.metadata.MetadataLaunchNormalizerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.metadata.EngineSystemIdResolverTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.metadata.WallpaperAccentTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.metadata.TitleMatcherTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.DualScreenLayoutTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.PresentationGeometryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.FrameGenerationCadenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.EndpointFrameSelectorTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.AdaptiveFrameRateControllerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.DenseGpuTimerMathTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.cheats.CheatModelTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.legal.LegalNoticeTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.cheats.CheatPanelModelTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.cheats.CheatArchiveTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.emulators.ExternalEmulatorModelTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.emulators.NativeAdapterStopPolicyTest
