#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT INT TERM

"$JAVA_HOME/bin/javac" --release 8 -encoding UTF-8 -d "$TEST_DIR" \
    "$PROJECT_DIR/native/tests/java/android/view/Surface.java" \
    "$PROJECT_DIR/native/tests/java/android/util/Log.java" \
    "$PROJECT_DIR/native/tests/java/android/os/Build.java" \
    "$PROJECT_DIR/src/com/thorium/lucent/timing/DisplaySyncPolicy.java" \
    "$PROJECT_DIR/src/com/thorium/lucent/video/NativeSourceImageProvider.java" \
    "$PROJECT_DIR/src/com/thorium/lucent/video/RuntimePresentationFailure.java" \
    "$PROJECT_DIR/src/com/thorium/preview/game/FrameGenerationRenderer.java" \
    "$PROJECT_DIR/src/com/thorium/preview/game/FrameGenerationRendererRegistry.java" \
    "$PROJECT_DIR/src/com/thorium/preview/LibretroHost.java" \
    "$PROJECT_DIR/src/com/thorium/preview/ExperimentalGlesLibretroHost.java" \
    "$PROJECT_DIR/src/com/thorium/preview/ExperimentalVulkanLibretroHost.java" \
    "$PROJECT_DIR/src/com/thorium/preview/ExperimentalGlesRenderLoop.java" \
    "$PROJECT_DIR/native/tests/java/com/thorium/preview/ExperimentalGlesLibretroHostLifecycleTest.java" \
    "$PROJECT_DIR/native/tests/java/com/thorium/preview/ExperimentalGlesRenderLoopTest.java"
"$JAVA_HOME/bin/java" -cp "$TEST_DIR" \
    com.thorium.preview.ExperimentalGlesLibretroHostLifecycleTest
"$JAVA_HOME/bin/java" -cp "$TEST_DIR" \
    com.thorium.preview.ExperimentalGlesRenderLoopTest
