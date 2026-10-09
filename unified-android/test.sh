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
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/game/FullResolutionFrameReadback.java"
SOURCES="$SOURCES $PROJECT_DIR/test-stubs/android/opengl/GLES20.java"
# Downloaded cheat sources: parsers, identity, codec, slicer are pure Java;
# DownloadedCheatFile is the Android binding and is compiled by build.sh.
SOURCES="$SOURCES $(find "$PROJECT_DIR/src/com/thorium/preview/cheats/sources" \
    -name '*.java' ! -name 'DownloadedCheatFile.java' -print)"
# Boot cheat delivery: the writers, registry, code text and OwnedFiles are pure
# Java; CheatLaunchHooks, EngineRoots and WidescreenCheatOverlay bind to
# Android/org.json and are compiled by build.sh.
SOURCES="$SOURCES $(find "$PROJECT_DIR/src/com/thorium/preview/cheats/delivery" \
    -name '*.java' ! -name 'CheatLaunchHooks.java' ! -name 'EngineRoots.java' \
    ! -name 'WidescreenCheatOverlay.java' -print)"
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/game/CoreOptionOverrideFile.java"
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/game/WidescreenHackTable.java"
"$JAVA_HOME/bin/javac" --release 8 -encoding UTF-8 \
    -d "$TEST_BUILD" $SOURCES
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.lucent.state.StateVaultTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.lucent.emulators.NativeQualificationStorageTest
"$JAVA_HOME/bin/java" -Xmx192m -cp "$TEST_BUILD" com.thorium.lucent.state.StateVaultHeapTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.lucent.state.StateVaultPayloadValidationTest
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
    com.thorium.lucent.timing.VsyncCadenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.timing.LatestValueMailboxTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.timing.DirectVideoTelemetryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.timing.DisplaySyncPolicyTest
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
    com.thorium.lucent.video.FrameGenerationPresentationRequestTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.CompositorFrameTimelineTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.CompositorPredictionLatticeTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.ExternalPresentationLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.ExternalPresentationEvidenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.AppOwnedExternalPresentationEvidenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.ExternalGeneratedContentEvidenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.UniformFrameRatePlanTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.GpuWorkAdaptationPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.GpuPairTimingLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.GpuPhysicalHeadroomLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.MidpointPairBudgetTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.PhysicalPresentationCadenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.PhysicalPresentationClockTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.PresentationClockDiagnosticsTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.ExternalPhysicalClockBootstrapTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.PhysicalPresentMarginTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.PhysicalPresentationDeadlineTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.DenseFlowTrajectoryDiagnosticsTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.EndpointFrameSelectorTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.NativeSourceImageTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.NativeSourceImageLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.NativeSourceImageObserverTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.FrameGenerationBackendPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.lucent.video.AdaptiveFrameRateControllerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.DenseGpuTimerMathTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.FullResolutionFrameReadbackTest
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
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.WidescreenHackPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.sources.CheatParsersTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.sources.CheatGameIdentityTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.sources.CheatSourceRegistryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.sources.DownloadedCheatFileTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.sources.CheatSourceSlicerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.sources.ChdIdentityTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.sources.CheatIdentityCrcTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.delivery.BootCheatWritersTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.delivery.CheatSessionRegistryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.delivery.WidescreenCheatPickTest
