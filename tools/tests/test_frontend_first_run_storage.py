"""Execute the real frontend permission branches with denied/pending access."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'unified-android/build/qt-5.15.10-16k/source/pegasus-frontend-6b322063a036db60cba5810fda82a3ce38f1e62f'

class FirstRunStorageTest(unittest.TestCase):
    def test_normal_frontend_recipe_and_lock_include_permission_repair(self):
        tools = ROOT/'unified-android/tools'
        patch = tools/'pegasus-android-storage-startup.patch'
        lock = json.loads((ROOT/'unified-android/source-frontend-artifact-lock.json').read_text())
        self.assertEqual(lock['patches'][patch.name], hashlib.sha256(patch.read_bytes()).hexdigest())
        self.assertIn(patch.name, (tools/'build_pegasus_source_android.sh').read_text())
        self.assertFalse(lock['runtimeQualified'])

    def execute(self, code):
        with tempfile.TemporaryDirectory(prefix='frontend-storage-') as temp:
            executable = Path(temp)/'probe'
            result = subprocess.run(['/usr/bin/clang++','-std=c++17','-x','c++','-','-o',str(executable)],
                                    input=code,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result = subprocess.run([str(executable)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_permission_pending_or_denied_does_not_terminate_android_frontend(self):
        source = (SOURCE/'src/app/main.cpp').read_text()
        start = source.index('    if (!request_runtime_permissions())')
        branch = source[start:source.index('    backend::CliArgs cli_args',start)]
        self.execute(r'''
#define Q_OS_ANDROID
bool permission=false;
bool request_runtime_permissions() { return permission; }
void qWarning(const char*) {}
int frontend_startup() {
''' + branch + r'''
    return 2; // The actual backend startup immediately follows this branch.
}
int main() {
    if (frontend_startup()!=2) return 1;
    permission=true;
    return frontend_startup()==2 ? 0 : 2;
}
''')

    def test_all_files_access_is_authoritative_on_android_11_and_later(self):
        source = (SOURCE/'src/backend/platform/AndroidHelpers.cpp').read_text()
        start = source.index('bool has_external_storage_access()')
        body = source[start:source.index('\nQString run_am_call',start)]
        self.execute(r'''
#include <algorithm>
#include <string>
#include <vector>
using QString=std::string;
using QStringList=std::vector<QString>;
using jboolean=bool;
#define QStringLiteral(value) QString(value)
int sdk=36, legacyChecks=0, requests=0, allFilesQueries=0;
bool allFiles=false, legacyGranted=false, requestGranted=false;
namespace QtAndroid {
enum class PermissionResult { Granted, Denied };
struct PermissionResultMap {
    PermissionResult value(const QString&,PermissionResult) const {
        return requestGranted ? PermissionResult::Granted : PermissionResult::Denied;
    }
};
int androidSdkVersion() { return sdk; }
PermissionResult checkPermission(const QString&) {
    ++legacyChecks;
    return legacyGranted ? PermissionResult::Granted : PermissionResult::Denied;
}
PermissionResultMap requestPermissionsSync(const QStringList&) { ++requests; return {}; }
}
const char* jni_classname() { return "MainActivity"; }
struct QAndroidJniObject {
    template<class T> static T callStaticMethod(const char*,const char*) {
        ++allFilesQueries; return allFiles;
    }
};
''' + body + r'''
int main() {
    for (int version : {30,31,33,36}) {
        sdk=version; allFiles=false;
        if (has_external_storage_access()) return 1;
        allFiles=true;
        if (!has_external_storage_access()) return 2;
        if (legacyChecks || requests) return 3;
    }
    int queries=allFilesQueries;
    sdk=29; legacyGranted=true;
    if (!has_external_storage_access() || requests) return 4;
    legacyGranted=false; requestGranted=false;
    if (has_external_storage_access() || requests!=1) return 5;
    requestGranted=true;
    if (!has_external_storage_access() || requests!=2) return 6;
    return allFilesQueries==queries ? 0 : 7;
}
''')

if __name__ == '__main__': unittest.main()
