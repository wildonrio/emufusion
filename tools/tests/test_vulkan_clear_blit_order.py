"""Source-level guard for the shared Vulkan destination write dependency.

This does not replace GPU validation or device playback verification.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class VulkanClearBlitOrderTest(unittest.TestCase):
    def test_overlapping_destination_writes_have_a_memory_dependency(self):
        source = (ROOT / "unified-android/native/lucent_android_vulkan_backend.c").read_text()
        record = source.split("static bool record_present_commands_for_target(", 1)[1]
        record = record.split("static bool record_present_commands(", 1)[0]
        clear = record.index("vkCmdClearColorImage(")
        blit = record.index("vkCmdBlitImage(")
        between = record[clear:blit]
        self.assertRegex(between, re.compile(
            r"image_barrier\(command, destination_image,\s*"
            r"VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,\s*"
            r"VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,\s*"
            r"VK_ACCESS_TRANSFER_WRITE_BIT,\s*VK_ACCESS_TRANSFER_WRITE_BIT,\s*"
            r"VK_QUEUE_FAMILY_IGNORED,\s*VK_QUEUE_FAMILY_IGNORED\);"))
        helper = source.split("static void image_barrier(", 1)[1].split("enum lucent_screen_crop", 1)[0]
        self.assertIn("barrier.srcAccessMask = src_access", helper)
        self.assertIn("barrier.dstAccessMask = dst_access", helper)
        self.assertEqual(2, helper.count("VK_PIPELINE_STAGE_ALL_COMMANDS_BIT"))


if __name__ == "__main__":
    unittest.main()
