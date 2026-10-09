"""Prevent narrow log searches from misreporting PS3 runtime evidence."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('ps3_capture_summary', ROOT /
    'docs/qa/android-portability-2026-10-06-ps3-wide-pointer/summarize_log.py')
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


class NativeCaptureSummaryTest(unittest.TestCase):
    def capture(self, text):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'capture-native.log.gz'
        data = text.encode()
        path.write_bytes(gzip.compress(data))
        path.with_suffix('').with_suffix('.json').write_text(json.dumps(dict(
            bytes=len(data), sha256=hashlib.sha256(data).hexdigest())))
        return path

    def test_actual_timeout_wording_and_runtime_boot_only(self):
        path = self.capture('·! 0:00:01.000001 SYS: Trying to load Shadow.self\n'
            '·! 0:00:41.854616 SYS: Path: /game/Shadow.self\n'
            '·E 0:01:10.360465 RSX: nv406e::semaphore_acquire has timed out. semaphore_address=0x40300490\n')
        result = SUMMARY.summarize(path)
        self.assertEqual(len(result['guestBoots']), 1)
        self.assertEqual(len(result['semaphoreTimeouts']), 1)
        self.assertFalse(result['gameplayProvenByThisAnalysis'])
        self.assertEqual(result['lastNativeTimestamp'], '0:01:10.360465')

    def test_handled_sig_is_not_a_fatal_record(self):
        path = self.capture('·E 0:00:02.000001 SIG: 崩溃 esr=0x92000007\n'
            '·F 0:00:03.000001 PPU: uncaught failure\n')
        result = SUMMARY.summarize(path)
        self.assertEqual(result['handledSigRecords'], 1)
        self.assertEqual(len(result['fatalRecords']), 1)

    def test_receipt_mismatch_is_rejected(self):
        path = self.capture('original')
        path.write_bytes(gzip.compress(b'modified'))
        with self.assertRaises(AssertionError):
            SUMMARY.summarize(path)


if __name__ == '__main__':
    unittest.main()
