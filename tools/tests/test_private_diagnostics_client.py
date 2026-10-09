"""Production Java execution and Java-to-Python receiver contract. No external I/O."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from tools.private_diagnostics_receiver import AggregateStore, Receiver, validated_report

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
ANDROID = ROOT.parent / 'cemu/Cemu-0.5/android-sdk/platforms/android-36/android.jar'
PACKAGE = ROOT / 'android-companion/src/com/thorium/preview'
ENV = dict(os.environ, JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true')


class PrivateDiagnosticsClientTest(unittest.TestCase):
    def test_transport_compiles_against_android_not_desktop_boot_classes(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-private-android-api-') as work:
            subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                            '-bootclasspath', str(ANDROID), '-d', work,
                            str(PACKAGE / 'PrivateDiagnosticReport.java'),
                            str(PACKAGE / 'PrivateDiagnosticsTransport.java')], env=ENV,
                           check=True, capture_output=True, timeout=60)

    def test_execute_production_client_and_actual_receiver(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-private-client-') as work:
            sources = list(PACKAGE.glob('PrivateDiagnostic*.java'))
            sources.append(ROOT / 'android-companion/tests/com/thorium/preview/PrivateDiagnosticsTest.java')
            subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8', '-cp', str(ANDROID),
                            '-d', work, *map(str, sources)], env=ENV, check=True,
                           capture_output=True, timeout=60)
            result = subprocess.run([str(JAVA / 'java'), '-ea', '-cp', work + os.pathsep + str(ANDROID),
                                     'com.thorium.preview.PrivateDiagnosticsTest'], env=ENV,
                                    check=True, capture_output=True, timeout=60)
            payloads = result.stdout.splitlines()
            self.assertEqual(len(payloads), 20)
            store = AggregateStore(Path(work) / 'counts.sqlite')
            server = Receiver(0, store, {90})
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                for body in payloads:
                    row = validated_report(body, {90})
                    self.assertEqual(row[2:], ('engine_ready', 'ok'))
                    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                    connection.request('POST', '/v1/report', body, {'Content-Type': 'application/json'})
                    reply = connection.getresponse()
                    self.assertEqual((reply.status, reply.read()), (204, b''))
                    connection.close()
                self.assertEqual(len(store.summary()), 20)
                for bucket in ('java', 'native', 'anr', 'out_of_memory'):
                    body = json.dumps(dict(schema=1, build=90, system='ps3',
                                           event='unexpected_exit', bucket=bucket)).encode()
                    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                    connection.request('POST', '/v1/report', body, {'Content-Type': 'application/json'})
                    reply = connection.getresponse()
                    self.assertEqual((reply.status, reply.read()), (204, b''))
                    connection.close()
                self.assertEqual(len(store.summary()), 24)
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=3)

    def test_hooks_use_fixed_categories_not_logs_and_off_is_default(self):
        host = (ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java').read_text()
        self.assertIn('PrivateDiagnostics.session(activity, request.systemId)', host)
        self.assertIn('privateDiagnostics.failed(cause instanceof OutOfMemoryError)', host)
        self.assertIn('privateDiagnostics.ready()', host)
        self.assertIn('privateDiagnostics.close()', host)
        manager = (PACKAGE / 'PrivateDiagnostics.java').read_text()
        self.assertIn('private static final String ENDPOINT = "";', manager)
        self.assertIn('preferences.getBoolean("enabled", false)', manager)
        for forbidden in ('Build.MODEL', 'Build.DEVICE', 'ANDROID_ID', 'getImei', 'getSerial',
                          'getMacAddress', 'getAccounts', 'Log.', 'getMessage()', 'printStackTrace',
                          'getHistoricalProcessExitReasons', 'getExternalStorageDirectory'):
            self.assertNotIn(forbidden, manager)

    def test_exit_recovery_reads_only_own_bounded_os_categories(self):
        recovery = (PACKAGE / 'PrivateDiagnosticsExitRecovery.java').read_text()
        self.assertIn('Build.VERSION.SDK_INT >= 30', recovery)
        self.assertIn('app.getPackageName(), pid, 8', recovery)
        self.assertIn('entry.getPid() != pid', recovery)
        self.assertIn('!ownProcess.equals(entry.getProcessName())', recovery)
        self.assertIn('entry.getTimestamp() < started', recovery)
        self.assertIn('entry.getTimestamp() >= before', recovery)
        for forbidden in ('getDescription(', 'getTraceInputStream(', 'getProcessStateSummary(',
                          'getPackageUid(', 'getRealUid(', 'getRss(', 'getPss(', 'Log.', 'getMessage('):
            self.assertNotIn(forbidden, recovery)
        report = (PACKAGE / 'PrivateDiagnosticReport.java').read_text()
        for forbidden in ('pid', 'timestamp', 'processName', 'getSerial', 'ANDROID_ID'):
            self.assertNotIn(forbidden, report)

    def test_user_control_is_confirmed_and_not_browser_mutable(self):
        theme = (ROOT / 'theme/theme.qml').read_text()
        self.assertIn('"PRIVATE DIAGNOSTICS"', theme)
        self.assertIn('status.enabled === true', theme)
        self.assertIn('!privateDiagnosticsConfigured', theme)
        service = (PACKAGE / 'PreviewService.java').read_text()
        for section in ('MUTATING_ENDPOINTS', 'THEME_CALLED_ENDPOINTS'):
            block = service.split(' ' + section + ' =', 1)[1].split('));', 1)[0]
            self.assertIn('"/settings/private-diagnostics"', block)
        self.assertIn('if (origin != null || referer != null)', service)
        self.assertIn('"explicit choice required', service.replace('\\"', '"'))


if __name__ == '__main__':
    unittest.main()
