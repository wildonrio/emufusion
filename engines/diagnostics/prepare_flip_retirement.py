#!/usr/bin/env python3
"""Isolate the acquire-surface-loss flip-retirement correction; preserve staging."""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = "b50eaf61cea6c6d6d1928777b48f8a9e5db8639d3b32815871c10ea66cb756f9"
OLD = """                reinitialize_swapchain();
                return;
		case VK_ERROR_OUT_OF_DATE_KHR:"""
NEW = """                reinitialize_swapchain();
                // handle_emu_flip still sends the guest completion on return.
                // Consume this request, as the unavailable-surface path does,
                // so do_local_task cannot replay it and notify the guest twice.
                rsx::thread::flip(info);
                return;
		case VK_ERROR_OUT_OF_DATE_KHR:"""


def prepare(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError("VKPresent changed; review before preparing this candidate")
    text = payload.decode()
    if text.count(OLD) != 1:
        raise ValueError("surface-loss return is absent or ambiguous")
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
