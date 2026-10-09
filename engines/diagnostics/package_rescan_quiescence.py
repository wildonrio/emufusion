"""Package only the verified hidden-rescan-spinner correction on the current APK."""
import copy
import io
import json
import subprocess
import zipfile
from package_spurs_trace import ROOT, SDK, digest, signature

BASE = ROOT / 'engines/build/candidates/switch-isolated-storage-2026-09-09/emufusion-switch-storage.apk'
BASE_SHA = '58a72882a598fcb7ec9c36a8e845421adc4904717cc8c453f864d0aee1b67035'

OUT = ROOT / 'engines/build/candidates/frontend-rescan-quiescence-2026-09-09'
THEME = 'assets/emufusion-theme.zip'
FINGERPRINT = 'assets/emufusion-theme.sha256'
NOTE = 'assets/local-rescan-quiescence.json'
assert not OUT.exists(), 'Refusing to overwrite an existing candidate'
assert digest(BASE.read_bytes()) == BASE_SHA
current = (ROOT / 'theme/theme.qml').read_bytes()
before = b'''                    RotationAnimation on rotation {
                        running: root.importState !== "idle" &&'''
after = b'''                    RotationAnimation on rotation {
                        // Import polling pauses during gameplay, so its last
                        // busy status can remain stale. Do not keep rendering
                        // this hidden spinner underneath the emulator.
                        running: !root.gameplayActive && root.importState !== "idle" &&'''
with zipfile.ZipFile(BASE) as base:
    with zipfile.ZipFile(io.BytesIO(base.read(THEME))) as old:
        names = [n for n in old.namelist() if n in ('theme.qml', './theme.qml', 'lucent/theme.qml')]
        assert len(names) == 1
        qml = names[0]
        original = old.read(qml)
        assert digest(original) == '889902168381a11b45848b8d38e62ef5d11e22e1dc55bc1f41f1e9b63eb41ad5'
        assert original.count(before) == 1
        assert current == original.replace(before, after), 'Unrelated source edits require a new reviewed base'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as new:
            for entry in old.infolist():
                new.writestr(copy.copy(entry), current if entry.filename == qml else old.read(entry.filename))
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as new:
            assert [n for n in old.namelist() if old.read(n) != new.read(n)] == [qml]
    updates = {THEME: buf.getvalue(), FINGERPRINT: (digest(buf.getvalue()) + '\n').encode()}
    OUT.mkdir()
    with zipfile.ZipFile(OUT / 'unsigned.apk', 'w') as new:
        for entry in base.infolist():
            if not signature(entry.filename):
                new.writestr(copy.copy(entry), updates.get(entry.filename, base.read(entry.filename)))
        new.writestr(NOTE, json.dumps(dict(baseSha256=BASE_SHA, themeQmlSha256=digest(current),
            purpose='Stop hidden rescan rotation during gameplay; all emulator, Java and other theme bytes unchanged'), indent=2))
bt = SDK / 'build-tools/36.0.0'
subprocess.run([str(bt/'zipalign'), '-f', '4', str(OUT/'unsigned.apk'), str(OUT/'aligned.apk')], check=True)
signed = OUT / 'emufusion-rescan-quiescence.apk'
subprocess.run([str(bt/'apksigner'), 'sign', '--ks', str(ROOT/'android-companion/debug.keystore'),
    '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--ks-key-alias', 'androiddebugkey',
    '--out', str(signed), str(OUT/'aligned.apk')], check=True)
subprocess.run([str(bt/'apksigner'), 'verify', '--verbose', str(signed)], check=True)
with zipfile.ZipFile(BASE) as old, zipfile.ZipFile(signed) as new:
    changed = [n for n in old.namelist() if not signature(n) and old.read(n) != new.read(n)]
    added = [n for n in new.namelist() if not signature(n) and n not in old.namelist()]
    assert set(changed) == set(updates) and added == [NOTE]
print(json.dumps(dict(apk=str(signed), sha256=digest(signed.read_bytes()),
    changed=changed, added=added, themeQmlSha256=digest(current)), indent=2))
