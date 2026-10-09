"""Real localhost TLS exchange with production Java transport and Python receiver.

Synthetic reports only. Trust is restricted to disposable JVMs, never the OS or
an Android device. This covers connect(), not Android networking, the fixed
production endpoint/send() wrapper, public hosting, or OTA installation.
"""
import contextlib
import io
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest

from tools.private_diagnostics_receiver import AggregateStore, Handler, Receiver


ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
PACKAGE = ROOT / 'android-companion/src/com/thorium/preview'
SYSTEMS = ('switch', 'wiiu', 'ps3', 'wii', 'gamecube', 'ps2', 'psp', 'dreamcast',
           '3ds', 'psx', 'nds', 'n64', 'snes', 'nes', 'gb', 'gbc', 'gba',
           'megadrive', 'gamegear', 'pcenginecd')

HARNESS = r'''
package com.thorium.preview;
import java.net.URL;
import javax.net.ssl.SSLException;

public final class PrivateHttpsProbe {
    public static void main(String[] args) throws Exception {
        String trust = System.getenv("EMUFUSION_TEST_TRUST_STORE");
        if (trust != null) {
            System.setProperty("javax.net.ssl.trustStore", trust);
            System.setProperty("javax.net.ssl.trustStorePassword",
                    System.getenv("EMUFUSION_TEST_TRUST_PASSWORD"));
        }
        for (int index = 2; index < args.length; ++index) {
            URL target = new URL(args[0]);
            try {
                PrivateDiagnosticsTransport.Result result = PrivateDiagnosticsTransport.connect(
                        target.getHost(), target.getPort(),
                        PrivateDiagnosticReport.create(90, args[index], "engine_ready", "ok"));
                if (args[1].equals("reject_tls")) throw new AssertionError("TLS unexpectedly accepted");
                System.out.println(result.name());
            } catch (SSLException expected) {
                if (!args[1].equals("reject_tls")) throw expected;
                System.out.println("TLS_REJECTED");
            }
        }
    }
}
'''

CERT_CONFIG = '''[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = localhost
[ext]
subjectAltName = DNS:localhost
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
'''


class ObservedHandler(Handler):
    def do_POST(self):
        # Test-only in-memory inspection. No real account/device values are used.
        self.server.observed.append((self.path, dict(self.headers)))
        if self.server.response_status == 204:
            return super().do_POST()
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.send_response_only(self.server.response_status)
        if self.server.response_status == 307:
            self.send_header('Location', self.server.redirect_url)
        if self.server.response_status == 401:
            self.send_header('WWW-Authenticate', 'Basic realm="synthetic"')
        if self.server.response_status == 407:
            self.send_header('Proxy-Authenticate', 'Basic realm="synthetic"')
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True


class PrivateDiagnosticsHttpsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (JAVA / 'javac').is_file() or not shutil.which('openssl'):
            raise unittest.SkipTest('JDK17 and OpenSSL/LibreSSL required')
        cls.work = tempfile.TemporaryDirectory(prefix='emufusion-private-https-')
        cls.addClassCleanup(cls.work.cleanup)
        cls.folder = Path(cls.work.name)
        cls.env = dict(os.environ,
                       JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true',
                       EMUFUSION_TEST_TRUST_PASSWORD=secrets.token_hex(24))
        for key in ('EMUFUSION_TEST_TRUST_STORE', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS'):
            cls.env.pop(key, None)
        (cls.folder / 'cert.cnf').write_text(CERT_CONFIG)
        cls.run_tool(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                      '-keyout', str(cls.folder / 'key.pem'), '-out', str(cls.folder / 'cert.pem'),
                      '-days', '1', '-config', str(cls.folder / 'cert.cnf')])
        cls.run_tool([str(JAVA / 'keytool'), '-importcert', '-noprompt', '-alias', 'fixture',
                      '-file', str(cls.folder / 'cert.pem'), '-keystore', str(cls.folder / 'trust.p12'),
                      '-storetype', 'PKCS12', '-storepass:env', 'EMUFUSION_TEST_TRUST_PASSWORD'])
        probe = cls.folder / 'PrivateHttpsProbe.java'
        probe.write_text(HARNESS)
        cls.run_tool([str(JAVA / 'javac'), '-source', '8', '-target', '8', '-d', str(cls.folder),
                      str(PACKAGE / 'PrivateDiagnosticReport.java'),
                      str(PACKAGE / 'PrivateDiagnosticsTransport.java'), str(probe)])

    @classmethod
    def run_tool(cls, args, env=None):
        return subprocess.run(args, env=env or cls.env, check=True, capture_output=True,
                              text=True, timeout=60)

    def setUp(self):
        self.storage = tempfile.TemporaryDirectory(prefix='emufusion-private-tls-counts-')
        self.addCleanup(self.storage.cleanup)
        self.store = AggregateStore(Path(self.storage.name) / 'counts.sqlite')
        self.server = Receiver(0, self.store, {90})
        self.addCleanup(self.server.server_close)
        self.server.RequestHandlerClass = ObservedHandler
        self.server.observed = []
        self.server.response_status = 204
        self.url = 'https://localhost:%d/v1/report' % self.server.server_address[1]
        self.server.redirect_url = self.url.replace('/v1/report', '/redirect-target')
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(self.folder / 'cert.pem', self.folder / 'key.pem')
        self.server.socket = tls.wrap_socket(self.server.socket, server_side=True)
        self.logs = io.StringIO()
        self.redirect_logs = contextlib.redirect_stderr(self.logs)
        self.redirect_logs.__enter__()
        self.addCleanup(self.redirect_logs.__exit__, None, None, None)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.worker.join(timeout=5)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.logs.getvalue(), '')

    def exchange(self, systems=('ps3',), trust=True, bad_host=False, tls_rejection=False):
        env = dict(self.env)
        if trust:
            env['EMUFUSION_TEST_TRUST_STORE'] = str(self.folder / 'trust.p12')
        url = self.url.replace('localhost', '127.0.0.1') if bad_host else self.url
        result = self.run_tool([str(JAVA / 'java'), '-cp', str(self.folder),
            'com.thorium.preview.PrivateHttpsProbe', url,
            'reject_tls' if tls_rejection else 'exchange', *systems], env=env)
        return result.stdout.splitlines()

    def test_all_systems_reach_actual_receiver_over_tls(self):
        self.assertEqual(self.exchange(SYSTEMS), ['ACCEPTED'] * 20)
        self.assertEqual(self.store.summary(), sorted(
            (90, system, 'engine_ready', 'ok', 1) for system in SYSTEMS))
        self.assertEqual(len(self.server.observed), 20)
        for path, headers in self.server.observed:
            headers = {key.lower(): value for key, value in headers.items()}
            self.assertEqual(path, '/v1/report')
            self.assertEqual(headers['user-agent'], 'EmuFusion-Diagnostics/1')
            self.assertEqual(headers['content-type'], 'application/json')
            self.assertFalse(headers.get('cookie'))
            self.assertFalse(headers.get('authorization'))
            self.assertNotIn('x-forwarded-for', headers)

    def test_retry_response(self):
        self.server.response_status = 503
        self.assertEqual(self.exchange(), ['RETRY'])
        self.assertEqual(len(self.server.observed), 1)
        self.assertEqual(self.store.summary(), [])

    def test_authentication_challenge_is_not_retried(self):
        for status in (401, 407):
            self.server.response_status = status
            self.assertEqual(self.exchange(), ['REJECTED'])
        self.assertEqual(len(self.server.observed), 2)
        self.assertEqual(self.store.summary(), [])

    def test_redirect_is_not_followed(self):
        self.server.response_status = 307
        self.assertEqual(self.exchange(), ['REJECTED'])
        self.assertEqual([path for path, _ in self.server.observed], ['/v1/report'])
        self.assertEqual(self.store.summary(), [])

    def test_untrusted_certificate_sends_no_report(self):
        self.assertEqual(self.exchange(trust=False, tls_rejection=True), ['TLS_REJECTED'])
        self.assertEqual(self.server.observed, [])
        self.assertEqual(self.store.summary(), [])

    def test_wrong_hostname_sends_no_report(self):
        self.assertEqual(self.exchange(bad_host=True, tls_rejection=True), ['TLS_REJECTED'])
        self.assertEqual(self.server.observed, [])
        self.assertEqual(self.store.summary(), [])


if __name__ == '__main__':
    unittest.main()
