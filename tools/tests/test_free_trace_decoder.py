import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location(
    "free_trace", Path(__file__).resolve().parents[1] / "decode_free_trace.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def fixture(end=1, captured=1):
    data = bytearray(trace.HEADER.pack(b"EFREE001", 123, 4096, 32, end, 0, 0, captured, 1))
    data.extend(bytes(4096 * 32))
    trace.RECORD.pack_into(data, trace.HEADER.size + ((end - 1) % 4096) * 32,
                           end, 0xb400007000000000, 0x6000000020, 456)
    return data


class FreeTraceDecoderTest(unittest.TestCase):
    def test_preserves_raw_pointer_and_direct_caller(self):
        result = trace.decode(fixture())
        self.assertEqual(123, result["pid"])
        self.assertEqual([{"sequence": 1, "pointer": "0xb400007000000000",
                           "caller": "0x6000000020", "tid": 456}], result["records"])

    def test_accepts_ring_wrap(self):
        self.assertEqual(9000, trace.decode(fixture(9000))["records"][0]["sequence"])

    def test_rejects_empty_truncated_or_extended_data(self):
        for data in (b"", fixture()[:-1], fixture() + b"x"):
            with self.assertRaises(ValueError): trace.decode(data)

    def test_rejects_wrong_magic_or_version(self):
        for offset, replacement in ((0, b"X"), (64, struct.pack("<Q", 2))):
            data = fixture()
            data[offset:offset + len(replacement)] = replacement
            with self.assertRaises(ValueError): trace.decode(data)

    def test_rejects_count_mismatch(self):
        with self.assertRaises(ValueError): trace.decode(fixture(captured=2))

    def test_rejects_uncommitted_record_data(self):
        data = fixture()
        struct.pack_into("<Q", data, trace.HEADER.size, 0)
        with self.assertRaises(ValueError): trace.decode(data)

    def test_rejects_wrong_ring_position(self):
        data = fixture()
        struct.pack_into("<Q", data, trace.HEADER.size, 2)
        struct.pack_into("<Q", data, 32, 2)
        with self.assertRaises(ValueError): trace.decode(data)


if __name__ == "__main__": unittest.main()
