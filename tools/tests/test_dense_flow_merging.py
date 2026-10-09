import importlib.util
from pathlib import Path
import unittest
import struct
import tempfile

spec = importlib.util.spec_from_file_location("merging", Path(__file__).parents[1]/"analyze_dense_flow_merging.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MergingTest(unittest.TestCase):
    def test_native_endpoint_dimensions(self):
        def packet(current_width):
            result=struct.pack(">iffiiii", 0x4C464431, 32., 64., 60, 8, 8, 2)
            for name,w in [(b"previousFull",8),(b"currentFull",current_width)]:
                result+=struct.pack(">i",len(name))+name+struct.pack(">ii",w,8)+bytes(w*8*4)
            return result
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"full.bin"
            path.write_bytes(packet(8))
            _,planes=module.read_dump(path)
            self.assertEqual(planes["previousFull"][:2],(8,8))
            path.write_bytes(packet(4))
            with self.assertRaises(ValueError):
                module.read_dump(path)

    def test_dump_roundtrip_and_rejections(self):
        header = struct.pack(">iffiiii", 0x4C464431, 32., 64., 60, 8, 8, 1)
        name = b"validated0"
        data = header + struct.pack(">i", len(name)) + name + struct.pack(">ii", 1, 1) + bytes([1, 2, 3, 4])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"fixture.bin"
            path.write_bytes(data)
            metadata, planes = module.read_dump(path)
            self.assertEqual(metadata["history_width"], 8)
            self.assertEqual(planes["validated0"], (1, 1, bytes([1, 2, 3, 4])))
            for invalid in (data[:-1], data+b"extra", b"BAD!"+data[4:]):
                path.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    module.read_dump(path)

    def test_uniform_and_partial_coverage(self):
        plane = (1, 1, bytes([128, 128, 204, 255]))
        for w, h in [(64, 32), (63, 31), (9, 7), (1, 1)]:
            result = module.merging(plane, plane, w, h)
            self.assertEqual(result["covered_pixels"], w*h)
        self.assertEqual(module.merging(plane, plane, 64, 32)["nodes"], 32)

    def test_one_raw_bit_prevents_merging(self):
        w, h = 9, 7
        valid = (w, h, bytes([128, 128, 204, 255])*(w*h))
        raw = (w, h, b"".join(bytes([16, (x+y)&1, 0, 0]) for y in range(h) for x in range(w)))
        result = module.merging(valid, raw, w, h)
        self.assertEqual(result["nodes"], w*h)
        self.assertEqual(result["covered_pixels"], w*h)

    def test_analysis_to_source_mapping(self):
        plane = (2, 1, bytes([1, 2, 3, 4, 5, 6, 7, 8]))
        result = module.merging(plane, plane, 16, 8)
        self.assertEqual(result["nodes_by_side"][8], 2)
        self.assertEqual(result["covered_pixels"], 128)


if __name__ == "__main__":
    unittest.main()
