#!/usr/bin/env python3
"""Private aggregate diagnostics prototype. Localhost only; NOT deployed.

Only predefined release/system/event/bucket values reach storage. No raw report,
identifier, timestamp, IP address, header, path, stack trace or free text is saved.
There is deliberately no HTTP read endpoint. HTTPS ingress and its logging must
be reviewed before deployment; this module cannot control a provider's logs.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import threading

SYSTEMS = frozenset(('switch', 'wiiu', 'ps3', 'wii', 'gamecube', 'ps2', 'psp',
    'dreamcast', '3ds', 'psx', 'nds', 'n64', 'snes', 'nes', 'gb', 'gbc', 'gba',
    'megadrive', 'gamegear', 'pcenginecd'))
BUCKETS = {
    'launch_ok': frozenset(('ok',)),
    'engine_ready': frozenset(('ok',)),
    'launch_failed': frozenset(('missing_firmware', 'unsupported_gpu', 'invalid_content',
                               'out_of_memory', 'unknown')),
    'runtime_failed': frozenset(('missing_firmware', 'unsupported_gpu', 'invalid_content',
                                'out_of_memory', 'unknown')),
    'unexpected_exit': frozenset(('java', 'native', 'anr', 'out_of_memory', 'process_death', 'unknown')),
    'audio_starvation': frozenset(('1_9', '10_99', '100_plus')),
    'frame_deadline_miss': frozenset(('1_9', '10_99', '100_plus')),
}
MAX_BYTES = 4096

def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate field')
        value[key] = item
    return value

def validated_report(body, builds):
    if not body or len(body) > MAX_BYTES:
        raise ValueError('invalid size')
    try:
        item = json.loads(body.decode('utf-8'), object_pairs_hook=unique_object)
    except RecursionError as failure:
        raise ValueError('invalid nesting') from failure
    if not isinstance(item, dict) or set(item) != {'schema', 'build', 'system', 'event', 'bucket'}:
        raise ValueError('invalid fields')
    if type(item['schema']) is not int or item['schema'] != 1:
        raise ValueError('invalid schema')
    if type(item['build']) is not int or item['build'] not in builds:
        raise ValueError('unpublished build')
    if any(type(item[key]) is not str for key in ('system', 'event', 'bucket')):
        raise ValueError('invalid field types')
    if item['system'] not in SYSTEMS or item['bucket'] not in BUCKETS.get(item['event'], ()):
        raise ValueError('invalid category')
    return item['build'], item['system'], item['event'], item['bucket']

class AggregateStore:
    def __init__(self, path):
        path = Path(path)
        # Database directory must be dedicated; do not change a shared parent's mode.
        if not path.parent.is_dir() or path.parent.stat().st_mode & 0o077:
            raise ValueError('Use a dedicated private database directory (mode 700)')
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        self.path, self.lock = path, threading.Lock()
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS totals ('
                'build INTEGER NOT NULL, system TEXT NOT NULL, event TEXT NOT NULL, '
                'bucket TEXT NOT NULL, reports INTEGER NOT NULL, '
                'PRIMARY KEY(build,system,event,bucket))')

    def add(self, row):
        with self.lock, sqlite3.connect(self.path) as connection:
            connection.execute('INSERT INTO totals VALUES (?,?,?,?,1) '
                'ON CONFLICT(build,system,event,bucket) DO UPDATE SET reports=reports+1', row)

    def summary(self):
        with self.lock, sqlite3.connect(self.path) as connection:
            return connection.execute('SELECT build,system,event,bucket,reports FROM totals '
                                      'ORDER BY build,system,event,bucket').fetchall()

class Receiver(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, port, store, builds):
        if not builds or any(type(code) is not int or code <= 0 for code in builds):
            raise ValueError('Explicit published build codes required')
        self.store, self.builds = store, frozenset(builds)
        super().__init__(('127.0.0.1', port), Handler)

    def handle_error(self, request, client_address):
        # The default implementation prints the client address and traceback.
        pass

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def log_message(self, *args):
        pass  # Never log IPs, headers, URL paths, bodies, or parse failures.

    def empty(self, status):
        self.send_response_only(status)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        self.empty(code)  # Do not echo malformed input in an error page.

    def do_POST(self):
        if self.path != '/v1/report':
            self.empty(404)
            return
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type') != 'application/json':
            self.empty(415)
            return
        lengths = self.headers.get_all('Content-Length', [])
        if (len(lengths) != 1 or len(lengths[0]) > 4 or
                not lengths[0].isascii() or not lengths[0].isdigit()):
            self.empty(400)
            return
        length = int(lengths[0])
        if not 0 < length <= MAX_BYTES:
            self.empty(413)
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('incomplete report')
            row = validated_report(body, self.server.builds)
        except (ValueError, UnicodeError, TimeoutError, OSError):
            self.empty(400)
            return
        try:
            self.server.store.add(row)
        except sqlite3.Error:
            self.empty(503)
            return
        self.empty(204)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--build', type=int, action='append', required=True)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    server = Receiver(args.port, AggregateStore(args.database), args.build)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
