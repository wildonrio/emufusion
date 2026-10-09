"""Eden fastmem bounds must fail closed before Android MAP_FIXED calls."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOST_MEMORY = (ROOT / "engines" / "build" / "switch-src" / "eden" /
               "src" / "common" / "host_memory.cpp").read_text(encoding="utf-8")


class EdenHostMemoryBoundsTest(unittest.TestCase):
    def test_map_uses_overflow_safe_bounds_and_returns_before_impl(self):
        body = HOST_MEMORY.split("void HostMemory::Map(", 1)[1].split(
            "void HostMemory::Unmap(", 1)[0]
        self.assertIn("virtual_offset <= virtual_size", body)
        self.assertIn("length <= virtual_size - virtual_offset", body)
        self.assertIn("host_offset <= backing_size", body)
        self.assertIn("Rejected out-of-range host map", body)
        self.assertLess(body.index("if (!virtual_in_range || !host_in_range)"),
                        body.index("impl->Map("))

    def test_unmap_refuses_bad_teardown_range_before_placeholder_tracker(self):
        body = HOST_MEMORY.split("void HostMemory::Unmap(", 1)[1].split(
            "void HostMemory::Protect(", 1)[0]
        self.assertIn("Ignored out-of-range host unmap", body)
        self.assertLess(body.index("if (!in_range)"), body.index("impl->Unmap("))
        self.assertNotIn("virtual_offset + length <= virtual_size", body)

    def test_protect_also_fails_closed_before_mprotect(self):
        body = HOST_MEMORY.split("void HostMemory::Protect(", 1)[1].split(
            "void HostMemory::ClearBackingRegion", 1)[0]
        self.assertIn("Rejected out-of-range host protect", body)
        self.assertLess(body.index("if (!in_range)"), body.index("impl->Protect("))

    def test_shutdown_releases_guest_memory_for_the_next_in_process_title(self):
        core = (ROOT / "engines" / "build" / "switch-src" / "eden" /
                "src" / "core" / "core.cpp").read_text(encoding="utf-8")
        shutdown = core.split("void ShutdownMainProcess()", 1)[1].split(
            "bool IsShuttingDown()", 1)[0]
        self.assertLess(shutdown.index("kernel.Shutdown();"),
                        shutdown.index("device_memory.reset();"))
        # ReinitializeIfNecessary is the upstream-supported path for a missing
        # DeviceMemory, so the next title recreates a clean reservation.
        self.assertIn("!device_memory.has_value()", core)


if __name__ == "__main__":
    unittest.main()
