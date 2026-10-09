#!/usr/bin/env python3
"""Link an isolated diagnostic adapter without replacing any staged artifact."""
import argparse
import hashlib
from pathlib import Path
import shlex
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--build-dir", type=Path, required=True)
parser.add_argument("--object", type=Path, required=True)
parser.add_argument("--additional-object", action="append", default=[],
                    metavar="MEMBER=PATH", help="Replace an explicit additional archive member")
parser.add_argument("--direct-object", action="append", default=[],
                    metavar="LINK_TOKEN=PATH", help="Replace an explicit standalone object in the link command")
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
build = args.build_dir.resolve()
destination = args.output_dir.resolve()
if destination.exists():
    parser.error("output directory already exists; choose a new isolated directory")
replacements = {"SPUThread.cpp.o": args.object.resolve()}
for value in args.additional_object:
    member, separator, path = value.partition("=")
    if not separator or not member.endswith(".o") or Path(member).name != member:
        parser.error("additional object must be a bare archive MEMBER.o=PATH")
    if member in replacements:
        parser.error("duplicate replacement member: " + member)
    replacements[member] = Path(path).resolve()
for member, path in replacements.items():
    if not path.is_file():
        parser.error("replacement object is absent: " + str(path))
sdk = Path("/Users/tyleryoung/Library/Android/sdk")
ninja = sdk / "cmake/3.22.1/bin/ninja"
llvm = sdk / "ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin"
commands = subprocess.check_output([str(ninja), "-t", "commands", "emu"], cwd=build, text=True)
tokens = shlex.split(commands.splitlines()[-1])
if tokens[:2] != [":", "&&"] or tokens[-2:] != ["&&", ":"]:
    parser.error("unexpected link shell structure")
tokens = tokens[2:-2]
if any(t in ("&&", ";", "|", ">") for t in tokens):
    parser.error("unexpected shell operation in linker command")
direct_replacements = {}
for value in args.direct_object:
    token, separator, path = value.partition("=")
    if (not separator or not token.endswith(".o") or Path(token).is_absolute()
            or ".." in Path(token).parts or tokens.count(token) != 1):
        parser.error("direct object must identify one existing relative object link token")
    source = Path(path).resolve()
    if token in direct_replacements or not source.is_file():
        parser.error("duplicate direct object or replacement file absent")
    direct_replacements[token] = source
archive_token = "rpcs3/rpcs3/Emu/librpcs3_emu.a"
if tokens.count(archive_token) != 1 or tokens.count("-o") != 1:
    parser.error("ambiguous archive or output")
archive = build / archive_token
members = subprocess.check_output([str(llvm / "llvm-ar"), "t", str(archive)], text=True).splitlines()
for member in replacements:
    if members.count(member) != 1:
        parser.error("absent or ambiguous archive member: " + member)
destination.mkdir(parents=True)
for index, (token, source) in enumerate(direct_replacements.items()):
    isolated = destination / ("direct-" + str(index) + "-" + Path(token).name)
    shutil.copyfile(source, isolated)
    tokens[tokens.index(token)] = str(isolated)
    print("Direct replacement:", token, "SHA256:", hashlib.sha256(isolated.read_bytes()).hexdigest(), flush=True)
isolated_objects = []
for member, source in replacements.items():
    replacement = destination / member
    shutil.copyfile(source, replacement)
    isolated_objects.append(str(replacement))
isolated_archive = destination / "librpcs3_emu.trace.a"
shutil.copyfile(archive, isolated_archive)
subprocess.run([str(llvm / "llvm-ar"), "r", str(isolated_archive), *isolated_objects], check=True)
subprocess.run([str(llvm / "llvm-ranlib"), str(isolated_archive)], check=True)
after = subprocess.check_output([str(llvm / "llvm-ar"), "t", str(isolated_archive)], text=True).splitlines()
if after != members:
    raise RuntimeError("archive member inventory changed")
for member in members:
    if member in replacements:
        inserted = subprocess.check_output([str(llvm / "llvm-ar"), "p", str(isolated_archive), member])
        expected = replacements[member].read_bytes()
        if inserted != expected:
            raise RuntimeError("replacement member differs from input: " + member)
        print("Replacement:", member, "SHA256:", hashlib.sha256(inserted).hexdigest(), flush=True)
        continue
    before_bytes = subprocess.check_output([str(llvm / "llvm-ar"), "p", str(archive), member])
    after_bytes = subprocess.check_output([str(llvm / "llvm-ar"), "p", str(isolated_archive), member])
    if hashlib.sha256(before_bytes).digest() != hashlib.sha256(after_bytes).digest():
        raise RuntimeError("unrelated archive member changed: " + member)
print("Verified unchanged archive members:", len(members) - len(replacements), flush=True)
tokens[tokens.index(archive_token)] = str(isolated_archive)
unstripped = destination / "liblucent_native_adapter_aps3e.trace.unstripped.so"
tokens[tokens.index("-o") + 1] = str(unstripped)
print("cwd:", build, flush=True)
print(shlex.join(tokens), flush=True)
subprocess.run(tokens, cwd=build, check=True)
stripped = destination / "liblucent_native_adapter_aps3e.trace.so"
subprocess.run([str(llvm / "llvm-strip"), "--strip-unneeded", "-o", str(stripped), str(unstripped)], check=True)
print("Diagnostic artifact:", stripped, flush=True)
digest = hashlib.sha256()
with stripped.open("rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
print("SHA256:", digest.hexdigest(), flush=True)
