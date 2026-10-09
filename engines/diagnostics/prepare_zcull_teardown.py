#!/usr/bin/env python3
"""Prepare an isolated Vulkan self-owned ZCULL teardown candidate, not staging."""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = "90bc7b06cf43269c6285f392d969bc9daf53e9bac73f684aa24556b4a0c1b7aa"
OLD = "VKGSRender::~VKGSRender()\n{\n"
NEW = OLD + """\t// on_exit may be skipped or throw before releasing this borrowed base.
\t// Never let rsx::thread's unique_ptr delete our ZCULL subobject again.
\tif (zcull_ctrl.get() == static_cast<::rsx::reports::ZCULL_control*>(this))
\t{
\t\tzcull_ctrl.release();
\t}

"""


def prepare(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError("VKGSRender changed; review other edits before preparing")
    text = payload.decode()
    if text.count(OLD) != 1:
        raise ValueError("destructor anchor absent or ambiguous")
    return text.replace(OLD, NEW, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.source.read_bytes())
    with args.output.open("x") as stream:
        stream.write(result)
    print("Output SHA256:", hashlib.sha256(result.encode()).hexdigest())


if __name__ == "__main__":
    main()
