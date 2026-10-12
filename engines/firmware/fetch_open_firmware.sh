#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
TARGET=${1:-}
BUILD_ROOT=${EMUFUSION_ENGINE_BUILD_DIR:-$ROOT/engines/build}
SOURCE_DIR="$BUILD_ROOT/sources"
OUTPUT_DIR="$BUILD_ROOT/firmware/$TARGET"
mkdir -p "$SOURCE_DIR" "$OUTPUT_DIR"

download_archive() {
    name=$1
    expected_sha=$2
    url=$3
    destination="$SOURCE_DIR/$name"
    if [ ! -f "$destination" ] ||
            [ "$(shasum -a 256 "$destination" | awk '{print $1}')" != "$expected_sha" ]; then
        rm -f "$destination.partial"
        curl -fL "$url" -o "$destination.partial"
        actual_sha=$(shasum -a 256 "$destination.partial" | awk '{print $1}')
        if [ "$actual_sha" != "$expected_sha" ]; then
            rm -f "$destination.partial"
            printf 'Firmware source checksum mismatch for %s: %s\n' "$name" "$actual_sha" >&2
            exit 1
        fi
        mv "$destination.partial" "$destination"
    fi
    printf '%s\n' "$destination"
}

case "$TARGET" in
    gearcoleco)
        commit=5391cefbc2a3af33e3283362ae854e3862059a07
        archive=$(download_archive \
            "8bitworkshop-$commit.tar.gz" \
            a62445862e2aaccfe0c4f86fb1c524bb0512bd7beaf3f4b82dc536040611c0cb \
            "https://github.com/sehugg/8bitworkshop/archive/$commit.tar.gz")
        unpack="$SOURCE_DIR/.unpack-8bitworkshop-$commit"
        rm -rf "$unpack"
        mkdir -p "$unpack"
        tar -xzf "$archive" --strip-components=1 -C "$unpack"

        firmware_source="$unpack/meta/romsrc/coleco/minbios.asm"
        firmware_binary="$unpack/mame/roms/coleco/313 10031-4005 73108a.u2"
        firmware_license="$unpack/LICENSE"
        for required in "$firmware_source" "$firmware_binary" "$firmware_license"; do
            if [ ! -f "$required" ]; then
                printf 'Pinned 8bitworkshop archive is missing %s\n' "$required" >&2
                exit 1
            fi
        done
        binary_sha=$(shasum -a 256 "$firmware_binary" | awk '{print $1}')
        if [ "$binary_sha" != 9edcba7a13f7b4852185ad1213bcd2185251b38e80381bfeef3da7cf5817b03d ]; then
            printf 'Open ColecoVision BIOS checksum mismatch: %s\n' "$binary_sha" >&2
            exit 1
        fi
        cp "$firmware_binary" "$OUTPUT_DIR/colecovision.rom"
        cp "$firmware_source" "$OUTPUT_DIR/minbios.asm"
        cp "$firmware_license" "$OUTPUT_DIR/LICENSE.GPL-3.0.txt"
        rm -rf "$unpack"
        printf '%s\n' "$OUTPUT_DIR/colecovision.rom"
        ;;
    *)
        printf 'usage: %s gearcoleco\n' "$0" >&2
        exit 2
        ;;
esac
