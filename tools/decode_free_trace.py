#!/usr/bin/env python3
"""Decode the bounded diagnostic free-call ring; no allocation/writer claims.

Sequence is reservation order before calling real free, not completion order.
Pointers and direct return PCs are raw values; no implicit tag stripping.
"""
import argparse
import json
from pathlib import Path
import struct

HEADER = struct.Struct("<8s8Q")
RECORD = struct.Struct("<4Q")


def decode(data):
    if len(data) < HEADER.size:
        raise ValueError("truncated or undumped trace")
    magic, pid, capacity, record_size, end, dropped, skipped, captured, version = HEADER.unpack_from(data)
    if magic != b"EFREE001" or version != 1 or capacity != 4096 or record_size != RECORD.size:
        raise ValueError("unsupported trace format")
    if len(data) != HEADER.size + capacity * RECORD.size:
        raise ValueError("incomplete or oversized trace")
    if skipped > capacity or captured > capacity:
        raise ValueError("invalid snapshot counts")
    begin = max(1, end - capacity + 1)
    records = []
    for i in range(capacity):
        sequence, pointer, caller, tid = RECORD.unpack_from(data, HEADER.size + i * RECORD.size)
        if sequence == 0:
            if pointer or caller or tid:
                raise ValueError("nonempty uncommitted record")
            continue
        if not begin <= sequence <= end or (sequence - 1) % capacity != i:
            raise ValueError("record outside its reserved ring position/window")
        if not pointer or not caller or not tid:
            raise ValueError("incomplete committed record")
        records.append({"sequence": sequence, "pointer": hex(pointer),
                        "caller": hex(caller), "tid": tid})
    if captured != len(records):
        raise ValueError("captured count does not match records")
    return {"format": "EFREE001", "pid": pid, "capacity": capacity,
            "lastReservedSequence": end, "lifetimeDroppedReservations": dropped,
            "snapshotBusySkips": skipped, "captured": captured,
            "records": sorted(records, key=lambda r: r["sequence"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--pointer", type=lambda s: int(s, 0))
    parser.add_argument("--ignore-top-byte", action="store_true",
                        help="explicit Android TBI normalization for pointer matching only")
    args = parser.parse_args()
    result = decode(args.trace.read_bytes())
    if args.pointer is not None:
        mask = (1 << (56 if args.ignore_top_byte else 64)) - 1
        result["matches"] = [r for r in result["records"]
                             if int(r["pointer"], 16) & mask == args.pointer & mask]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
