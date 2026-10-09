"""Synthetic-only privacy and actual localhost HTTP/storage tests; no device data."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from tools.private_diagnostics_receiver import AggregateStore, Receiver, validated_report

REPORT = dict(schema=1, build=90, system='n64', event='launch_failed', bucket='unsupported_gpu')

class PrivateDiagnosticsTest(unittest.TestCase):
    def test_exact_allowlist(self):
        self.assertEqual(validated_report(json.dumps(REPORT).encode(), {90}),
                         (90, 'n64', 'launch_failed', 'unsupported_gpu'))
        for key in ('deviceId', 'androidId', 'model', 'ip', 'account', 'rom', 'path',
                    'logcat', 'stack', 'recording', 'timestamp', 'sessionId'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validated_report(json.dumps(dict(REPORT, **{key: 'PRIVATE_VALUE'})).encode(), {90})

    def test_values_cannot_smuggle_free_text_or_identifiers(self):
        for key in REPORT:
            for value in ('PRIVATE@example.invalid', '/storage/owner/game.iso',
                          'device-123', '192.0.2.1', [], {}, None, True):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validated_report(json.dumps(dict(REPORT, **{key: value})).encode(), {90})
        with self.assertRaises(ValueError):
            validated_report(json.dumps(dict(REPORT, build=123456789)).encode(), {90})
        with self.assertRaises(ValueError):
            validated_report(b'{"schema":1,"schema":1,"build":90,"system":"n64",'
                             b'"event":"launch_failed","bucket":"unknown"}', {90})
        with self.assertRaises(ValueError):
            validated_report(b'[' * 1100 + b'0' + b']' * 1100, {90})

    def test_actual_http_aggregates_only_and_has_no_public_read_route(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-private-receiver-') as folder:
            os.chmod(folder, 0o700)
            store = AggregateStore(Path(folder) / 'counts.sqlite')
            server = Receiver(0, store, {90})
            self.assertEqual(server.server_address[0], '127.0.0.1')
            logs = io.StringIO()
            with contextlib.redirect_stderr(logs):
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    def request(method, path, body=None, headers=None):
                        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                        connection.request(method, path, body=body, headers=headers or {})
                        response = connection.getresponse()
                        result = response.status, response.read(), dict(response.getheaders())
                        connection.close()
                        return result
                    headers = {'Content-Type': 'application/json',
                               'User-Agent': 'PRIVATE_DEVICE', 'X-Forwarded-For': '192.0.2.1'}
                    for _ in range(2):
                        status, body, reply_headers = request('POST', '/v1/report',
                            json.dumps(REPORT), headers)
                        self.assertEqual((status, body), (204, b''))
                        self.assertNotIn('Set-Cookie', reply_headers)
                    bad = dict(REPORT, deviceId='PRIVATE_DEVICE')
                    self.assertEqual(request('POST', '/v1/report', json.dumps(bad), headers)[:2], (400, b''))
                    self.assertEqual(request('GET', '/v1/report?owner=PRIVATE_DEVICE')[:2], (501, b''))
                    self.assertEqual(request('POST', '/private/PRIVATE_DEVICE', '{}', headers)[:2], (404, b''))
                    self.assertEqual(request('POST', '/v1/report', 'x' * 4097, headers)[:2], (413, b''))
                    self.assertEqual(store.summary(), [(90, 'n64', 'launch_failed', 'unsupported_gpu', 2)])
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=3)
            self.assertEqual(logs.getvalue(), '')
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(store.path) as connection:
                self.assertEqual([row[1] for row in connection.execute('PRAGMA table_info(totals)')],
                    ['build', 'system', 'event', 'bucket', 'reports'])
            for path in Path(folder).iterdir():
                data = path.read_bytes()
                for secret in (b'PRIVATE_DEVICE', b'192.0.2.1', b'User-Agent', b'owner='):
                    self.assertNotIn(secret, data)

    def test_database_requires_private_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder, 0o755)
            with self.assertRaises(ValueError):
                AggregateStore(Path(folder) / 'counts.sqlite')

if __name__ == '__main__':
    unittest.main()
