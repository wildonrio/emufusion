#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
TEST_BUILD="$PROJECT_DIR/build/unit-tests"

rm -rf "$TEST_BUILD"
mkdir -p "$TEST_BUILD"

# Android adapters are compiled by build.sh. These host tests intentionally use
# only the platform-neutral state/input core and therefore need no device or SDK.
SOURCES=$(find "$PROJECT_DIR/src/com/thorium/emufusion/state" \
    "$PROJECT_DIR/src/com/thorium/emufusion/audio" \
    "$PROJECT_DIR/src/com/thorium/emufusion/input" \
    "$PROJECT_DIR/src/com/thorium/emufusion/navigation" \
    "$PROJECT_DIR/src/com/thorium/emufusion/metadata" \
    "$PROJECT_DIR/src/com/thorium/emufusion/timing" \
    "$PROJECT_DIR/src/com/thorium/emufusion/video" \
    "$PROJECT_DIR/src/com/thorium/emufusion/cheats" \
    "$PROJECT_DIR/src/com/thorium/emufusion/emulators" \
    "$PROJECT_DIR/src/com/thorium/emufusion/legal" "$PROJECT_DIR/test" \
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
    ! -name 'WidescreenCheatOverlay.java' ! -name 'FrameRateUnlockOverlay.java' \
    ! -name 'FrameRateUnlockPolicy.java' -print)"
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/game/CoreOptionOverrideFile.java"
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/game/WidescreenHackTable.java"
SOURCES="$SOURCES $PROJECT_DIR/src/com/thorium/preview/game/GpuDriverTable.java"
"$JAVA_HOME/bin/javac" --release 8 -encoding UTF-8 \
    -d "$TEST_BUILD" $SOURCES
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.emufusion.state.StateVaultTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.emufusion.emulators.NativeQualificationStorageTest
"$JAVA_HOME/bin/java" -Xmx192m -cp "$TEST_BUILD" com.thorium.emufusion.state.StateVaultHeapTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.emufusion.state.StateVaultPayloadValidationTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.emufusion.audio.PcmAudioQueueTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.emufusion.audio.PcmSignalTelemetryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" com.thorium.emufusion.input.InputRouterTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.input.LibretroJoypadLayoutTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.input.JoypadPressLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.input.WiiIrPointerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.navigation.RightStickViewRouterTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.timing.AbsoluteFramePacerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.timing.VsyncCadenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.timing.LatestValueMailboxTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.timing.DirectVideoTelemetryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.timing.DisplaySyncPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.metadata.MetadataLaunchNormalizerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.metadata.EngineSystemIdResolverTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.metadata.WallpaperAccentTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.metadata.TitleMatcherTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.DualScreenLayoutTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.PresentationGeometryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.FrameGenerationCadenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.FrameGenerationPresentationRequestTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.CompositorFrameTimelineTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.CompositorPredictionLatticeTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.ExternalPresentationLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.ExternalPresentationEvidenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.AppOwnedExternalPresentationEvidenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.ExternalGeneratedContentEvidenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.UniformFrameRatePlanTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.GpuWorkAdaptationPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.GpuPairTimingLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.GpuPhysicalHeadroomLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.MidpointPairBudgetTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.PhysicalPresentationCadenceTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.PhysicalPresentationClockTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.PresentationClockDiagnosticsTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.ExternalPhysicalClockBootstrapTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.PhysicalPresentMarginTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.PhysicalPresentationDeadlineTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.DenseFlowTrajectoryDiagnosticsTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.EndpointFrameSelectorTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.NativeSourceImageTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.NativeSourceImageLedgerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.NativeSourceImageObserverTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.FrameGenerationBackendPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.AdaptiveFrameRateControllerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.FrameGenerationAutoPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.DenseGpuTimerMathTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.FullResolutionFrameReadbackTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.cheats.CheatModelTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.legal.LegalNoticeTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.cheats.CheatPanelModelTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.cheats.CheatArchiveTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.emulators.ExternalEmulatorModelTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.emulators.NativeAdapterStopPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.WidescreenHackPolicyTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.game.GpuDriverTableTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.timing.PanelRefreshPlannerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.PanelClockMemoryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.TimelineFrameSchedulerTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.SourcePhaseAdvisorTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.CompositorBacklogCatchUpTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.emufusion.video.GeneratedFrameVerdictTest
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
    com.thorium.preview.cheats.sources.CuratedLibraryGamesTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.delivery.BootCheatWritersTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.delivery.CheatSessionRegistryTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.delivery.WidescreenCheatPickTest
"$JAVA_HOME/bin/java" -cp "$TEST_BUILD" \
    com.thorium.preview.cheats.delivery.FrameRateUnlockPickTest
