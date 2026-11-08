#!/bin/sh
# A Mac dolphin-emu-nogui built from the same locked Dolphin source, dependencies and patches as the Android core, to test the
# GameCube keep-2D rule without the Thor. Two bench-only patches in dolphin-mac-bench/ read the 2D scale (EMUFUSION_WS_2D, the
# libretro option's value on Android) and a frame-dump interval (EMUFUSION_DUMP_EVERY) from the environment. Run games with
# gc_bench.py. "build-only" rebuilds the staged tree without restaging it.
set -eu
REPO=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
SOURCES=$REPO/engines/build/sources
DEST=${DOLPHIN_MAC_BENCH:-$HOME/.cache/emufusion-widescreen/host-build/dolphin-mac}
MARK=$DEST/.emufusion-mac-bench
BENCH=$REPO/tools/widescreen/dolphin-mac-bench

if [ -e "$DEST" ] && [ ! -f "$MARK" ]; then
    echo "refusing to replace $DEST" >&2
    exit 1
fi
if [ "${1:-}" != "build-only" ]; then
    rm -rf "$DEST"
    mkdir -p "$DEST"
    : > "$MARK"
    cp -R "$SOURCES/dolphin-0ff12a5a2835762e0665afe6a161a648b433f996/." "$DEST/"
    awk '/<<.DOLPHIN_DEPENDENCIES./{f=1;next} /^DOLPHIN_DEPENDENCIES/{f=0} f' "$REPO/engines/build_core.sh" |
    while IFS='|' read -r dep_path dep_repository dep_commit dep_sha; do
        archive=$(find "$SOURCES" -maxdepth 2 -name "*$dep_commit*.tar.gz" | head -1)
        rm -rf "${DEST:?}/$dep_path"
        mkdir -p "$DEST/$dep_path"
        tar -xzf "$archive" --strip-components=1 -C "$DEST/$dep_path"
    done
    for p in dolphin-libretro-submit-rendered-duplicate-xfb dolphin-libretro-own-signal-stack dolphin-libretro-descriptor-errors \
             dolphin-libretro-low-queue-priority dolphin-emufusion-keep-2d-shape; do
        patch -s -d "$DEST" -p1 < "$REPO/engines/patches/$p.patch"
    done
    patch -s -d "$DEST" -p1 < "$BENCH/mac-bench-env.patch"
    patch -s -d "$DEST" -p1 < "$BENCH/mac-bench-dump.patch"
    # A bare macOS binary looks for its data where a bundle keeps it.
    mkdir -p "$DEST/build-mac/Binaries/Contents/Resources"
    ln -s "$DEST/Data/Sys" "$DEST/build-mac/Binaries/Contents/Resources/Sys"
fi
cmake -S "$DEST" -B "$DEST/build-mac" -G Ninja -DCMAKE_BUILD_TYPE=Release -DENABLE_QT=OFF -DENABLE_NOGUI=ON -DLIBRETRO=OFF \
    -DUSE_DISCORD_PRESENCE=OFF -DENABLE_ANALYTICS=OFF -DENABLE_AUTOUPDATE=OFF -DUSE_MGBA=OFF -DENABLE_TESTS=OFF \
    -DUSE_RETRO_ACHIEVEMENTS=OFF -DENABLE_CLI_TOOL=OFF -DSKIP_POSTPROCESS_BUNDLE=ON -DMACOS_CODE_SIGNING=OFF -DUSE_UPNP=OFF \
    -DENABLE_VULKAN=OFF -DENABLE_CUBEB=OFF
ninja -C "$DEST/build-mac" dolphin-nogui
