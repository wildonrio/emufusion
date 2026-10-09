#!/bin/sh
# Reproducible Android ARM64 build recipe for a EmuFusion Phase 3 native-adapter
# engine (Wii U/Cemu first).
#
# STATUS: SKELETON ONLY. The actual Cemu-as-adapter core build is a separate,
# multi-week milestone and is NOT implemented here. This script documents the
# exact reproducible steps a real implementation must follow, validates its
# inputs, and then exits with a clear "core build not yet implemented" message.
# It never attempts to fetch, patch, or compile Cemu.
#
# What a real implementation must do, deterministically:
#
#   1. Pin toolchain: the NDK, CMake, and Ninja versions/hashes recorded in
#      engines/cemu-source-lock.json (Android ARM64, arm64-v8a, API 24, the same
#      NDK 27.0.12077973 the other in-process engines use). Fail closed on any
#      hash mismatch.
#   2. Fetch source by commit + archiveSha256 from cemu-source-lock.json and
#      verify every vendored submodule against the (to-be-populated) dependencies
#      closure, exactly as engines/build_core.sh does for libretro cores.
#   3. Apply only the reviewed patches listed in the lock (there are none yet).
#   4. Configure Cemu's CMake for a Vulkan, headless, no-Qt/no-wxWidgets core
#      target that builds Cemu WITHOUT its own Android Activity/UI, and links a
#      thin adapter translation unit implementing the vtable in
#      unified-android/native/include/lucent_native_adapter.h.
#   5. Export EXACTLY one public symbol, lucent_native_adapter_entry, returning a
#      static const lucent_native_adapter whose abi_version equals
#      LUCENT_NATIVE_ADAPTER_ABI_VERSION. Everything else stays hidden
#      (-fvisibility=hidden -Wl,--no-undefined -Wl,--exclude-libs,ALL).
#   6. Apply EmuFusion's 16 KiB page-size link policy
#      (-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384) and produce
#      liblucent_native_adapter_cemu.so.
#   7. Normalize (strip .note.gnu.build-id), record artifactSha256, and prove
#      byte-identical independent builds before flipping "reproducible": true and
#      generating the signed phase3 artifact manifest the APK verifies.
#
# Until all of that exists, the Java NativeAdapterCatalog stays fail-closed on
# the HASH: a build that does not pass LUCENT_INCLUDE_PHASE3_CEMU=1 packages no
# adapter .so at all, and only then does Wii U resolve to its external Cemu
# route. With the flag, the staged adapter is bundled and Wii U runs internally.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
ENGINE=${1:-cemu}
LOCK="$ROOT/engines/$ENGINE-source-lock.json"
ABI=${LUCENT_NATIVE_ABI:-arm64-v8a}

if [ ! -f "$LOCK" ]; then
    printf 'No native-adapter source lock for engine "%s": %s\n' "$ENGINE" "$LOCK" >&2
    exit 1
fi

# Confirm the pinned identity and ABI contract are present so a future
# implementation starts from a validated, fail-closed baseline.
python3 - "$ENGINE" "$LOCK" "$ROOT/unified-android/native/include/lucent_native_adapter.h" <<'PY'
import json, re, sys
engine, lock_path, header_path = sys.argv[1], sys.argv[2], sys.argv[3]
lock = json.load(open(lock_path))
errors = []
if lock.get("route") != "native-adapter":
    errors.append("route must be native-adapter")
if lock.get("reproducible") is not False:
    errors.append("reproducible must remain false until a real build is proven")
core = lock.get("core") or {}
if not str(core.get("repository", "")).startswith("https://") or \
        not re.fullmatch(r"[0-9a-f]{40}", str(core.get("commit", ""))):
    errors.append("core repository/commit identity is incomplete")
# archive/archiveSha256 are an optional PAIR, exactly as the phase 3 registry
# validator treats them: a source cloned by commit has no release tarball, and
# inventing an archive hash for one that was never downloaded is false
# provenance. Declaring an archive without its hash stays an error.
archive, archive_hash = core.get("archive"), core.get("archiveSha256")
if bool(archive) != bool(archive_hash) or (archive_hash and
        not re.fullmatch(r"[0-9a-f]{64}", str(archive_hash))):
    errors.append("core archive identity is incomplete")
abi = lock.get("adapterAbi") or {}
if abi.get("entrySymbol") != "lucent_native_adapter_entry":
    errors.append("adapter entry symbol must be lucent_native_adapter_entry")
header = open(header_path).read()
if "#define LUCENT_NATIVE_ADAPTER_ABI_VERSION" not in header:
    errors.append("ABI header does not define LUCENT_NATIVE_ADAPTER_ABI_VERSION")
if errors:
    print("\n".join("  - " + e for e in errors)); sys.exit(1)
print(f"{engine} native-adapter source lock and ABI contract validated")
PY

printf '\n'
printf 'engine=%s abi=%s lock=%s\n' "$ENGINE" "$ABI" "$LOCK"
printf 'Native-adapter core build not yet implemented for %s.\n' "$ENGINE" >&2
printf 'This recipe is a documented skeleton; no adapter .so was produced.\n' >&2
printf 'The Eden/Switch adapter that IS staged in engines/build/arm64-v8a was\n' >&2
printf 'built out of band and is NOT reproduced by this script: see\n' >&2
printf 'engines/eden-source-lock.json, which records reproducible=false.\n' >&2
exit 3
