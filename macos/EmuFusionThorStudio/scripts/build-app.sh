#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
APP_DIR="$PROJECT_DIR/dist/EmuFusion Thor Studio.app"
BUILD_DIR="$PROJECT_DIR/.build/arm64-apple-macosx/release"

cd "$PROJECT_DIR"
swift build -c release

mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$PROJECT_DIR/App/Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$BUILD_DIR/EmuFusionThorStudio" "$APP_DIR/Contents/MacOS/EmuFusionThorStudio"
rm -rf "$APP_DIR/EmuFusionThorStudio_EmuFusionThorStudio.bundle"
rm -rf "$APP_DIR/Contents/Resources/EmuFusionThorStudio_EmuFusionThorStudio.bundle"
cp -R "$BUILD_DIR/EmuFusionThorStudio_EmuFusionThorStudio.bundle" "$APP_DIR/Contents/Resources/EmuFusionThorStudio_EmuFusionThorStudio.bundle"
codesign --force --deep --sign - --entitlements "$PROJECT_DIR/App/EmuFusionThorStudio.entitlements" "$APP_DIR"
echo "$APP_DIR"
