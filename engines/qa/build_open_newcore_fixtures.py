#!/usr/bin/env python3
"""Fetch/build exact redistributable fixtures for the late Phase 1 cores."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "engines" / "build" / "qa-open-newcores"
PCE_SOURCE = ROOT / "engines" / "qa" / "fixtures" / "pce" / "emufusion_pce_qa.c"
A7800_SOURCE = (ROOT / "engines" / "qa" / "fixtures" / "atari7800" /
                "emufusion_atari7800_qa.bas")

CC65_COMMIT = "547d923588d870aacf0b0016c67d0f6a92a70f83"
CC65_ARCHIVE_SHA256 = "1915cf1ce467a726163618007e6c7a87ae8c8a5f7c8f7651640c4e90a941ed78"
PCE_FIXTURE_SHA256 = "bf15e23d6a20235717db494af91dcab4d557b83aa2573ed4d278f5e45c576be6"
A7800_TOOLCHAIN_URL = (
    "https://github.com/7800-devtools/7800basic/releases/download/v0.41/"
    "7800basic-0.41-wasm.tar.gz"
)
A7800_TOOLCHAIN_SHA256 = "62ef0a562541bff3f813c038a4609abc89ab125ebda3a371f57de2821e7a7fe7"
A7800_FIXTURE_SHA256 = "2cf0210fdf85765d0fcf0270144fb75f7565e134686a79ba9ef87629850b5a4d"
WASMTIME_VERSION = "47.0.3"
WASMTIME_RELEASES = {
    ("Darwin", "arm64"): (
        "aarch64-macos",
        "c2684249e5d9ef9351942cf2d315982cf201fe0300f05d63bc1527446f0cd37f",
    ),
    ("Darwin", "x86_64"): (
        "x86_64-macos",
        "424a50f76a9dcf4d02dab326b2374be1ad404030576ee915866e4af106058b35",
    ),
    ("Linux", "aarch64"): (
        "aarch64-linux",
        "497b518db00ae585f04390758eaa99ad555bee50612dce7d102602778fb46ff0",
    ),
    ("Linux", "x86_64"): (
        "x86_64-linux",
        "ca1fc56d1afc40c8782e96c297fd182a0da162f9a8f52a1e7b094e1dd648e178",
    ),
}

FILES = (
    (
        "stargunner.ngc",
        "https://raw.githubusercontent.com/Tixul/Stargunner/"
        "fb9295cd710ddb923dffb99a7513d954ff119fe0/Stargunner.ngc",
        "089e2d9520dc2f84d34a33b1dfa1710eb9a429d90b3b0a195a06ccab89c9022f",
    ),
    (
        "stargunner-LICENSE",
        "https://raw.githubusercontent.com/Tixul/Stargunner/"
        "fb9295cd710ddb923dffb99a7513d954ff119fe0/LICENSE",
        "3d0ffdce0e9f2096085e14e3794a644717127faac2ccdae06943d9e97aca3d0e",
    ),
    (
        "bug-witch.wsc",
        "https://github.com/RegionallyFamous/SwanSong-Originals/"
        "releases/download/v3.3.0/bug_witch.wsc",
        "ccacf10e9734630ad4f9a5b2301dcc3aca7b06a0e92771d92d95a2ced0487d21",
    ),
    (
        "swansong-originals-LICENSE",
        "https://raw.githubusercontent.com/RegionallyFamous/SwanSong-Originals/"
        "28547c5c6a1fafad14cfe026198f0efbee3c80a6/LICENSE",
        "ef8ce7d95f26b6cffca5f9928bd0f012e3ae58b305a3df1ff086dbcd0131b75c",
    ),
)
OUTPUT_HASHES = {
    **{name: expected for name, _url, expected in FILES},
    "emufusion-pce-qa.pce": PCE_FIXTURE_SHA256,
    "cc65-LICENSE": "8e87ae93bbc45dbe3def75c8b20ba2905b052ddf766fe61d55b8e16a807d57f3",
    "emufusion-atari7800-qa.a78": A7800_FIXTURE_SHA256,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_download(url: str, destination: Path, expected: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "EmuFusion-QA/1"})
    with urllib.request.urlopen(request) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = sha256(destination)
    if actual != expected:
        raise SystemExit(f"checksum mismatch for {url}: {actual}")


def build_pce_fixture(work: Path) -> Path:
    archive = work / "cc65.tar.gz"
    verified_download(
        f"https://codeload.github.com/cc65/cc65/tar.gz/{CC65_COMMIT}",
        archive,
        CC65_ARCHIVE_SHA256,
    )
    source = work / "cc65"
    with tarfile.open(archive, "r:gz") as package:
        top = package.getmembers()[0].name.split("/", 1)[0]
        package.extractall(work)
    (work / top).rename(source)
    jobs = str(max(1, min(os.cpu_count() or 1, 8)))
    subprocess.run(["make", "-s", f"-j{jobs}", "bin"], cwd=source, check=True)
    subprocess.run(["make", "-s", f"-j{jobs}", "lib"], cwd=source, check=True)

    outputs: list[Path] = []
    for index in range(2):
        output = work / f"emufusion-pce-qa-{index}.pce"
        subprocess.run(
            [
                str(source / "bin" / "cl65"), "-t", "pce", "-Oirs",
                "-I", str(source / "include"), "-L", str(source / "lib"),
                "-C", str(source / "cfg" / "pce.cfg"),
                "-o", str(output), str(PCE_SOURCE),
            ],
            cwd=ROOT,
            check=True,
        )
        outputs.append(output)
    if outputs[0].read_bytes() != outputs[1].read_bytes():
        raise SystemExit("cc65 PC Engine fixture build is not reproducible")
    actual = sha256(outputs[0])
    if actual != PCE_FIXTURE_SHA256:
        raise SystemExit(f"PC Engine fixture checksum mismatch: {actual}")
    shutil.copyfile(source / "LICENSE", OUTPUT / "cc65-LICENSE")
    return outputs[0]


def build_atari7800_fixture(work: Path) -> Path:
    target = WASMTIME_RELEASES.get((platform.system(), platform.machine()))
    if target is None:
        raise SystemExit(
            "Atari 7800 fixture builder has no pinned Wasmtime package for "
            f"{platform.system()} {platform.machine()}"
        )
    target_name, runtime_sha = target
    compiler_archive = work / "7800basic.tar.gz"
    runtime_archive = work / "wasmtime.tar.xz"
    verified_download(A7800_TOOLCHAIN_URL, compiler_archive,
                      A7800_TOOLCHAIN_SHA256)
    runtime_url = (
        "https://github.com/bytecodealliance/wasmtime/releases/download/"
        f"v{WASMTIME_VERSION}/wasmtime-v{WASMTIME_VERSION}-{target_name}.tar.xz"
    )
    verified_download(runtime_url, runtime_archive, runtime_sha)
    with tarfile.open(compiler_archive, "r:gz") as package:
        package.extractall(work)
    with tarfile.open(runtime_archive, "r:xz") as package:
        package.extractall(work)
    compiler = work / "7800basic"
    runtime = work / f"wasmtime-v{WASMTIME_VERSION}-{target_name}" / "wasmtime"
    if not compiler.is_dir() or not runtime.is_file():
        raise SystemExit("pinned Atari 7800 fixture toolchain is incomplete")

    outputs: list[Path] = []
    for index in range(2):
        build = work / f"a7800-build-{index}"
        build.mkdir()
        source = build / "emufusion-atari7800-qa.bas"
        shutil.copyfile(A7800_SOURCE, source)
        environment = os.environ.copy()
        environment["bas7800dir"] = str(compiler)
        environment["PATH"] = str(runtime.parent) + os.pathsep + environment["PATH"]
        subprocess.run(
            [str(compiler / "7800basic.sh"), source.name, "-O"],
            cwd=build, env=environment, check=True,
        )
        outputs.append(build / f"{source.name}.a78")
    if outputs[0].read_bytes() != outputs[1].read_bytes():
        raise SystemExit("7800basic Atari 7800 fixture build is not reproducible")
    actual = sha256(outputs[0])
    if actual != A7800_FIXTURE_SHA256:
        raise SystemExit(f"Atari 7800 fixture checksum mismatch: {actual}")
    shutil.copyfile(compiler / "LICENSE.txt", OUTPUT / "7800basic-LICENSE.txt")
    return outputs[0]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if all((OUTPUT / name).is_file() and sha256(OUTPUT / name) == expected
           for name, expected in OUTPUT_HASHES.items()):
        print(OUTPUT)
        return
    with tempfile.TemporaryDirectory(prefix="emufusion-newcore-fixtures-") as temporary:
        work = Path(temporary)
        for name, url, expected in FILES:
            verified_download(url, OUTPUT / name, expected)
        pce = build_pce_fixture(work)
        shutil.copyfile(pce, OUTPUT / "emufusion-pce-qa.pce")
        a7800 = build_atari7800_fixture(work)
        shutil.copyfile(a7800, OUTPUT / "emufusion-atari7800-qa.a78")
    print(OUTPUT)


if __name__ == "__main__":
    main()
