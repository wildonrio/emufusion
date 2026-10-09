"""Production Android HTTPS transport against a synthetic localhost receiver.

Owned, offline emulator-5586 only; never installs/replaces the EmuFusion APK.
Trust is confined to the disposable test APK. No endpoint is activated in the app.
Android custom trust configuration: https://developer.android.com/privacy-and-security/security-config
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import threading
import time
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from tools.tests.test_private_diagnostics_https import CERT_CONFIG, ObservedHandler, SYSTEMS
from tools.private_diagnostics_receiver import AggregateStore, Receiver

QA = ROOT / 'docs/qa'
spec = importlib.util.spec_from_file_location('preserve', QA / 'android-portability-2026-10-05-ps2-descriptor-integration/device.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
d.PRIOR = json.loads((QA / 'android-portability-2026-10-06-n64-gl-error/finished.json').read_text())
SDK = ROOT.parent / 'cemu/Cemu-0.5/android-sdk'
BT = SDK / 'build-tools/36.0.0'
ANDROID = SDK / 'platforms/android-36/android.jar'
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
ENV = dict(os.environ, JAVA_HOME=str(JAVA.parent),
           JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true')
PROBE = 'com.emufusion.qa.privatetls20261006'
OUT = QA / 'android-portability-2026-10-06-android-private-https'

def write(name, value):
    with (OUT / name).open('x') as stream:
        json.dump(value, stream, indent=2)

def run(*args):
    return subprocess.run(list(map(str, args)), env=ENV, check=True,
                          capture_output=True, text=True, timeout=180)

def build():
    assert not (OUT / 'build.json').exists(), 'Do not overwrite a completed fixture build'
    OUT.mkdir(mode=0o700, exist_ok=True)
    (OUT / 'cert.cnf').write_text(CERT_CONFIG)
    for name in ('trusted', 'untrusted'):
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', OUT / (name + '.key'),
            '-out', OUT / (name + '.pem'), '-days', '1', '-config', OUT / 'cert.cnf')
        (OUT / (name + '.key')).chmod(0o600)
    for directory in ('res/raw', 'res/xml', 'classes', 'dex'):
        (OUT / directory).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT / 'trusted.pem', OUT / 'res/raw/fixture_ca.pem')
    shutil.copyfile(HERE / 'fixture_trust.xml', OUT / 'res/xml/fixture_trust.xml')
    sources = sorted((ROOT / 'android-companion/src/com/thorium/preview').glob('PrivateDiagnostic*.java'))
    sources.append(HERE / 'ProbeActivity.java')
    boot = str(BT / 'core-lambda-stubs.jar') + os.pathsep + str(ANDROID)
    run(JAVA / 'javac', '-source', '8', '-target', '8', '-bootclasspath', boot, '-d', OUT / 'classes', *sources)
    run(BT / 'd8', '--min-api', '30', '--lib', ANDROID, '--output', OUT / 'dex', *sorted((OUT / 'classes').rglob('*.class')))
    run(BT / 'aapt2', 'compile', '--dir', OUT / 'res', '-o', OUT / 'resources.zip')
    run(BT / 'aapt2', 'link', '-I', ANDROID, '--manifest', HERE / 'AndroidManifest.xml',
        '-o', OUT / 'unsigned.apk', '-R', OUT / 'resources.zip')
    with zipfile.ZipFile(OUT / 'unsigned.apk', 'a') as archive:
        archive.write(OUT / 'dex/classes.dex', 'classes.dex', compress_type=zipfile.ZIP_DEFLATED)
    run(BT / 'zipalign', '4', OUT / 'unsigned.apk', OUT / 'aligned.apk')
    run(BT / 'apksigner', 'sign', '--ks', ROOT / 'android-companion/debug.keystore',
        '--ks-pass', 'pass:android', '--out', OUT / 'probe.apk', OUT / 'aligned.apk')
    run(BT / 'apksigner', 'verify', OUT / 'probe.apk')
    write('build.json', dict(apk=str(OUT / 'probe.apk'), sha256=hashlib.sha256((OUT / 'probe.apk').read_bytes()).hexdigest(),
        sourceHashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        release=False, productionEndpointUnchanged=True))
    print('Synthetic test APK built from the reporting sources as-is.', flush=True)

def saves():
    result = d.saves()
    raw = d.adb('shell', 'run-as', d.PKG, 'find', 'app_engine-system/cemu/mlc01/usr/save',
                '-type', 'f', '-exec', 'sha256sum', '{}', '+')
    result['cemu0'] = {line.split(None, 1)[1]: line.split(None, 1)[0] for line in raw.splitlines()}
    return result

def prepare():
    identity = d.verify(d.NORMAL['sha256'])
    d.stop()
    d.adb('shell', 'am', 'start-user', '-w', '10')
    saved = saves()
    assert saved == d.PRIOR['saveFiles']
    assert not d.adb('shell', 'pm', 'path', PROBE, check=False)
    assert not d.adb('reverse', '--list')
    for key in ('wifi_on', 'mobile_data'):
        assert d.adb('shell', 'settings', 'get', 'global', key) == '0'
    rotation = {key: d.adb('shell', 'settings', '--user', '0', 'get', 'system', key)
                for key in ('accelerometer_rotation', 'user_rotation')}
    d.adb('shell', 'am', 'switch-user', '0')
    for key, value in (('accelerometer_rotation', '0'), ('user_rotation', '1')):
        d.adb('shell', 'settings', '--user', '0', 'put', 'system', key, value)
    write('prepared.json', dict(identity=identity, saveFiles=saved, rotationBefore=rotation))
    result = json.loads((OUT / 'build.json').read_text())
    d.adb('install', '--no-incremental', '-r', '--user', '0', result['apk'])
    path = d.adb('shell', 'pm', 'path', '--user', '0', PROBE)
    assert path.startswith('package:/data/app/') and '\n' not in path
    assert d.adb('shell', 'sha256sum', path[8:]).split()[0] == result['sha256']
    assert d.verify(d.NORMAL['sha256']) == identity and saves() == saved
    print('Synthetic fixture installed; EmuFusion APK/identities/all saves unchanged.', flush=True)

def operation(name):
    # Delete only this test fixture's prior synthetic result, never app/user data.
    d.adb('shell', 'run-as', PROBE, 'rm', '-f', 'files/result.json')
    d.adb('shell', 'am', 'start', '--user', '0', '-n', PROBE + '/com.thorium.preview.ProbeActivity',
          '--es', 'operation', name)
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        raw = d.adb('shell', 'run-as', PROBE, 'cat', 'files/result.json', check=False)
        if raw:
            result = json.loads(raw)
            assert result.get('operation') == name and 'failureClass' not in result, result
            return result
        time.sleep(0.2)
    raise AssertionError('Synthetic fixture timed out: ' + name)

def exchanges():
    store = AggregateStore(OUT / 'synthetic-counts.sqlite')
    assert store.summary() == [], 'Use a fresh synthetic database for each complete test run'
    cases = []
    for certificate in ('trusted', 'untrusted'):
        server = Receiver(0, store, {90})
        server.RequestHandlerClass = ObservedHandler
        server.observed, server.response_status = [], 204
        server.redirect_url = 'https://localhost/redirect-target'
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(OUT / 'fixed' / (certificate + '.pem'), OUT / 'fixed' / (certificate + '.key'))
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        logs = io.StringIO()
        with contextlib.redirect_stderr(logs):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                d.adb('reverse', '--no-rebind', 'tcp:443', 'tcp:' + str(server.server_address[1]))
                def case(name, wanted, requests, status=204):
                    server.response_status = status
                    before = len(server.observed)
                    result = operation(name)
                    assert result['results'] == wanted, result
                    assert len(server.observed) - before == requests
                    cases.append(dict(case=name, certificate=certificate, status=status,
                                      requests=requests, result=result))
                    print(name, certificate, 'PASS', flush=True)
                if certificate == 'trusted':
                    case('all', ['ACCEPTED'] * 20, 20)
                    assert store.summary() == sorted((90, s, 'engine_ready', 'ok', 1) for s in SYSTEMS)
                    case('retry', ['RETRY'], 1, 503)
                    case('redirect', ['REJECTED'], 1, 307)
                    case('wrong-host', ['TLS_REJECTED'], 0)
                    case('cookie', ['ACCEPTED'], 1)
                    case('auth', ['REJECTED'], 1, 401)
                    case('auth', ['REJECTED'], 1, 407)
                    case('queue', [], 0)
                    assert cases[-1]['result']['pending'] == '90|snes|engine_ready|ok\n'
                    case('flush', [], 1, 503)
                    assert cases[-1]['result']['pending'] == '90|snes|engine_ready|ok\n'
                    d.adb('shell', 'am', 'force-stop', '--user', '0', PROBE)
                    case('flush', [], 1)
                    assert cases[-1]['result']['pending'] == ''
                    case('queue', [], 0)
                    case('opt-out', [], 0)
                    assert cases[-1]['result']['pending'] == '' and not cases[-1]['result']['enabled']
                    case('flush', [], 0)
                else:
                    case('untrusted', ['TLS_REJECTED'], 0)
                for path, headers in server.observed:
                    h = {key.lower(): value for key, value in headers.items()}
                    assert path == '/v1/report' and h['user-agent'] == 'EmuFusion-Diagnostics/1'
                    assert h['content-type'] == 'application/json'
                    assert not h.get('cookie') and not h.get('authorization')
                    assert 'x-forwarded-for' not in h
            finally:
                d.adb('reverse', '--remove', 'tcp:443', check=False)
                server.shutdown(); server.server_close(); thread.join(5)
            assert not thread.is_alive() and not logs.getvalue()
    assert sum(row[-1] for row in store.summary()) == 22
    write('transport-results.json', dict(cases=cases, aggregates=store.summary(),
        productionSendWrapper=True, androidApi=36, physicalDevicesTouched=False,
        syntheticOnly=True, localOnly=True, serverLogsEmpty=True))

def tests():
    # send() intentionally permits only standard HTTPS. Root adbd is available
    # solely in this owned debug AVD and is needed to bind its loopback port 443.
    # This never changes production endpoint validation or physical-device policy.
    d.verify(d.NORMAL['sha256'])
    assert d.adb('shell', 'id', '-u') == '2000'
    d.adb('root')
    d.adb('wait-for-device')
    try:
        assert d.adb('shell', 'id', '-u') == '0'
        exchanges()
    finally:
        d.adb('unroot')
        d.adb('wait-for-device')
        assert d.adb('shell', 'id', '-u') == '2000'

def replace_fixture():
    before = json.loads((OUT / 'prepared.json').read_text())
    assert d.verify(d.NORMAL['sha256']) == before['identity'] and saves() == before['saveFiles']
    # This is a replacement of our synthetic fixture, not EmuFusion.
    import re
    def identity():
        data = d.adb('shell', 'dumpsys', 'package', PROBE)
        return re.findall(r'^\s*(?:appId=|firstInstallTime=)([^\r\n]+)', data, re.M)
    original = identity()
    assert len(original) == 3  # UID, installed user 0 and never-installed user 10 timestamps.
    d.adb('shell', 'am', 'force-stop', '--user', '0', PROBE)
    candidate = json.loads((OUT / 'fixed/build.json').read_text())
    d.adb('install', '--no-incremental', '-r', '--user', '0', candidate['apk'])
    assert identity() == original
    path = d.adb('shell', 'pm', 'path', '--user', '0', PROBE)
    assert path.startswith('package:/data/app/') and '\n' not in path
    assert d.adb('shell', 'sha256sum', path[8:]).split()[0] == candidate['sha256']
    assert d.verify(d.NORMAL['sha256']) == before['identity'] and saves() == before['saveFiles']
    write('fixture-replacement.json', dict(fixtureIdentityPreserved=True, emufusionUnchanged=True,
                                         fixtureSha256=candidate['sha256']))

def finish():
    d.adb('shell', 'am', 'force-stop', '--user', '0', PROBE)
    before = json.loads((OUT / 'prepared.json').read_text())
    assert d.verify(d.NORMAL['sha256']) == before['identity']
    d.stop()
    d.adb('shell', 'am', 'start-user', '-w', '10')
    assert saves() == before['saveFiles']
    assert not d.adb('reverse', '--list')
    for key, value in before['rotationBefore'].items():
        d.adb('shell', 'settings', '--user', '0', 'put', 'system', key, value)
    d.adb('shell', 'am', 'stop-user', '-w', '-f', '10')
    d.adb('shell', 'sync')
    write('finished.json', dict(identity=before['identity'], apkSha256=d.NORMAL['sha256'],
        saveFiles=before['saveFiles'], unchangedFiles=sum(map(len, before['saveFiles'].values())),
        productionApkUnchanged=True, fixtureRetainedStopped=True, rotationRestored=True,
        shutdownReply=d.adb('emu', 'kill')))
    print('EmuFusion APK/both identities/all checked files unchanged; simulator shutting down.', flush=True)

if __name__ == '__main__':
    if sys.argv[1] == 'rebuild':
        OUT = OUT / 'fixed'
        build()
    else:
        {'build': build, 'prepare': prepare, 'replace': replace_fixture,
         'tests': tests, 'finish': finish}[sys.argv[1]]()
