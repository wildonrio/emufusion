#!/usr/bin/env python3
"""Package rootless, app-scoped allocator guards into a diagnostic APK staging tree.

The wrapper requires a debuggable app with extracted native libraries. It is not
a release configuration, performance evidence, or proof that all writes are safe.
Refuse a conflicting wrapper or simultaneous GWP-ASan; preserve native payloads.
"""
import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ANDROID = "{http://schemas.android.com/apk/res/android}"
ATTRIBUTES = {"debuggable": "true", "extractNativeLibs": "true", "gwpAsanMode": "never"}
WRAPPER = Path(__file__).with_name("malloc-debug-wrap.sh")


def manifest_for_debug(text):
    applications = ET.fromstring(text).findall("application")
    if len(applications) != 1:
        raise ValueError("expected exactly one application")
    if applications[0].get(ANDROID + "gwpAsanMode") == "always":
        raise ValueError("GWP-ASan and malloc_debug must be separate experiments")
    if not re.search(r'xmlns:android\s*=\s*[\"\']http://schemas.android.com/apk/res/android[\"\']', text):
        raise ValueError("expected Android namespace prefix")
    matches = list(re.finditer(r'<application\b(?:[^>\"\']|\"[^\"]*\"|\'[^\']*\')*>', text))
    if len(matches) != 1:
        raise ValueError("ambiguous application opening tag")
    match = matches[0]
    opening = match.group()
    for name in ATTRIBUTES:
        opening = re.sub(r'\s+android:' + name + r'\s*=\s*(?:\"[^\"]*\"|\'[^\']*\')', '', opening)
    attributes = ''.join(f' android:{name}="{value}"' for name, value in ATTRIBUTES.items())
    opening = opening.replace("<application", "<application" + attributes, 1)
    updated = text[:match.start()] + opening + text[match.end():]
    application = ET.fromstring(updated).find("application")
    if any(application.get(ANDROID + name) != value for name, value in ATTRIBUTES.items()):
        raise ValueError("diagnostic manifest verification failed")
    return updated


def enable(staging, free_trace_library=None):
    staging = Path(staging)
    manifest = staging / "AndroidManifest.xml"
    original = manifest.read_text(encoding="utf-8")
    updated = manifest_for_debug(original)
    wrapper = WRAPPER.read_bytes()
    # Only ABI directories that actually contain native libraries. Never create
    # an architecture the app did not already support or replace its own wrapper.
    directories = sorted({path.parent for path in (staging / "lib").glob("*/*.so")})
    if not directories:
        raise ValueError("no native ABI directories in staging")
    trace_targets = []
    trace_bytes = None
    if free_trace_library:
        if any(directory.name != 'arm64-v8a' for directory in directories):
            raise ValueError("free tracer supports only arm64-v8a staging")
        trace_bytes = Path(free_trace_library).read_bytes()
        if (len(trace_bytes) < 64 or trace_bytes[:7] != b'\x7fELF\x02\x01\x01'
                or trace_bytes[16:20] != b'\x03\x00\xb7\x00'):
            raise ValueError("free tracer must be an AArch64 ELF shared library")
        package = ET.fromstring(original).get('package', '')
        if package != 'com.thorium.preview':
            raise ValueError("free tracer output directory requires com.thorium.preview")
        marker = b'exec logwrapper "$@"'
        if wrapper.count(marker) != 1:
            raise ValueError("unexpected wrapper entry point")
        wrapper = wrapper.replace(marker, (
            b'export EMUFUSION_FREE_TRACE_DIR=/data/user/0/com.thorium.preview/files\n'
            b'export LD_PRELOAD="${0%/*}/libemufusion_free_trace.so${LD_PRELOAD:+:$LD_PRELOAD}"\n'
            + marker))
        trace_targets = [directory / 'libemufusion_free_trace.so' for directory in directories]
        for target in trace_targets:
            if target.is_symlink() or (target.exists() and target.read_bytes() != trace_bytes):
                raise ValueError(f"refusing to overwrite existing tracer: {target}")
    targets = [directory / "wrap.sh" for directory in directories]
    for target in targets:
        if target.is_symlink() or (target.exists() and target.read_bytes() != wrapper):
            raise ValueError(f"refusing to overwrite existing wrapper: {target}")
    # Validate all inputs before changing generated files.
    if updated != original:
        manifest.write_text(updated, encoding="utf-8")
    for target in trace_targets:
        if not target.exists():
            target.write_bytes(trace_bytes)
        target.chmod(0o755)
    for target in targets:
        if not target.exists():
            target.write_bytes(wrapper)
        target.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staging", type=Path)
    parser.add_argument("--free-trace-library", default=None)
    args = parser.parse_args()
    enable(args.staging, args.free_trace_library)


if __name__ == "__main__":
    main()
