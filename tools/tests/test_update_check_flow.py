"""Execute the production update-check orchestration with deterministic I/O.

Only Android, JSON parsing, network, disk download and installer boundaries are
faked. The check/version-comparison method bodies are extracted unchanged from
UpdateManager.java. This is NOT an Android installer or internet acceptance test.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "android-companion/src/com/thorium/preview/UpdateManager.java"
JAVA = Path(os.environ.get("JAVA_HOME",
    "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")) / "bin"


HARNESS = r'''
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class UpdateCheckFlowTest {
    static final String TAG = "test";
    static final String MANIFEST_URL = "fixture:manifest";
    // The renamed repository is tried first; it is absent here, so every
    // manifest scenario also exercises the fallback to the legacy name.
    static final String[] MANIFEST_URLS = {"fixture:manifest-renamed", MANIFEST_URL};
    static final String[] RELEASE_API_URLS = {"fixture:release"};
    static final String UPDATE_PREFERENCES = "fixture";
    static final long MAX_THEME=1000, MAX_CHEATS=1000, MAX_APK=1000;
    static final String SHA = "a".repeat(64);
    static final Map<String, JSONObject> documents = new HashMap<>();
    final Map<String, String> responses = new HashMap<>();
    final List<String> operations = new ArrayList<>();
    final Context context = new Context();
    JSONObject latest;
    String state = "idle", failedDownload = "";
    boolean installed, validApk = true, inGame, alreadyDownloaded, deferred;
    File apk;

    static final class JSONObject {
        final Map<String, Object> values = new HashMap<>();
        JSONObject() {}
        JSONObject(String token) throws IOException {
            JSONObject document = documents.get(token);
            if (document == null) throw new IOException("invalid fixture JSON");
            values.putAll(document.values);
        }
        JSONObject put(String key, Object value) { values.put(key, value); return this; }
        String optString(String key) { return optString(key, ""); }
        String optString(String key, String fallback) {
            Object value = values.get(key); return value == null ? fallback : (String)value;
        }
        int optInt(String key, int fallback) {
            Object value = values.get(key); return value == null ? fallback : (Integer)value;
        }
    }
    static final class Context {
        Preferences getSharedPreferences(String name, int mode) { return new Preferences(); }
        File getCacheDir() { return new File(System.getProperty("java.io.tmpdir")); }
    }
    static final class Preferences {
        String getString(String key, String fallback) { return fallback; }
        Preferences edit() { return this; }
        Preferences putString(String key, String value) { return this; }
        void apply() {}
    }
    static final class ThemeInstaller {
        static String installedVersion() { return "3.2.16"; }
        static void installZip(File file, String version) {}
    }
    static final class CheatControl {
        static File downloadedArchive(Context c) { return new File("unused-fixture-cheats.zip"); }
    }
    static final class CheatArchive { static void verify(File f) {} }
    static final class Log { static void w(String tag, String message, Exception e) {} }
    static final class AppRelease {
        String version, url, sha256;
        AppRelease(String v, String u, String s) { version=v; url=u; sha256=s; }
    }
    static AppRelease appRelease(JSONObject json) {
        String version = json.optString("version", "");
        return version.isEmpty() ? null : new AppRelease(version, "fixture:apk", SHA);
    }
    long currentVersionCode() { return 90; }
    String currentVersionName() { return "3.2.16"; }
    byte[] fetch(String url, long limit) throws IOException {
        operations.add("fetch:" + url);
        String response = responses.get(url);
        if (response == null) throw new IOException("fixture unavailable");
        return response.getBytes(StandardCharsets.UTF_8);
    }
    void setStatus(String s, double progress, String message, boolean available, boolean ready) {
        state = s; operations.add("status:" + s);
    }
    void download(String url, File target, long limit, String digest) throws IOException {
        operations.add("download:" + url);
        if (url.equals(failedDownload)) throw new IOException("fixture download failure");
        if (!SHA.equals(digest)) throw new IOException("fixture checksum mismatch");
    }
    File updateFile() { return apk; }
    void validateDownloadedApk(Context ignored, File file) throws IOException {
        operations.add("validate");
        if (!validApk) throw new IOException("fixture identity rejected");
    }
    void installDownloadedApk(boolean automatic) {
        operations.add("installer"); installed = true;
    }
    boolean downloadedMatches(File file, String digest) { return alreadyDownloaded; }
    boolean gameplayActive() { return inGame; }
    void deferInstallUntilLibrary() { operations.add("deferred"); deferred = true; }
    static void installCheatArchive(File staged, File target) {}

    // PRODUCTION_METHODS

    void release(String version) {
        documents.put("release", new JSONObject().put("version", version));
        responses.put(RELEASE_API_URLS[0], "release");
    }
    JSONObject manifest() {
        JSONObject json = new JSONObject();
        documents.put("manifest", json);
        responses.put(MANIFEST_URL, "manifest");
        return json;
    }
    void expectInstall() throws Exception {
        check(true);
        require(installed, "APK installer was not reached: " + operations);
        require(operations.indexOf("validate") < operations.indexOf("installer"),
                "identity validation must precede the installer");
        for (String op : operations)
            require(!op.equals("download:fixture:theme") && !op.equals("download:fixture:cheats"),
                    "optional download must not precede a needed APK update: " + operations);
    }
    void expectFailure() throws Exception {
        boolean failed = false;
        try { check(true); } catch (IOException expected) { failed = true; }
        require(failed || "error".equals(state), "must fail, not report up to date: " + operations);
        require(!installed, "failure must not open installer");
    }
    static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    void run(String scenario) throws Exception {
        switch (scenario) {
            case "missing_manifest":
                release("3.2.17"); expectInstall();
                require(!operations.contains("fetch:fixture:manifest"),
                        "primary APK update should not even wait for legacy manifest");
                break;
            case "malformed_manifest":
                release("3.2.17"); responses.put(MANIFEST_URL, "not-json"); expectInstall(); break;
            case "theme_unavailable":
                release("3.2.17");
                manifest().put("themeVersion", "4.0.0").put("themeSha256", SHA)
                    .put("themeZipUrl", "fixture:theme");
                failedDownload = "fixture:theme"; expectInstall(); break;
            case "cheats_unavailable":
                release("3.2.17");
                manifest().put("cheatCatalogVersion", "new").put("cheatCatalogSha256", SHA)
                    .put("cheatCatalogUrl", "fixture:cheats");
                failedDownload = "fixture:cheats"; expectInstall(); break;
            case "legacy_fallback":
                manifest().put("companionVersionCode", 91).put("companionSha256", SHA)
                    .put("companionApkUrl", "fixture:apk")
                    .put("themeVersion", "4.0.0").put("themeZipUrl", "fixture:theme");
                expectInstall(); break;
            case "missing_apk_checksum":
                manifest().put("companionVersionCode", 91).put("companionApkUrl", "fixture:apk");
                expectFailure(); break;
            case "wrong_apk_checksum":
                manifest().put("companionVersionCode", 91).put("companionApkUrl", "fixture:apk")
                    .put("companionSha256", "b".repeat(64));
                expectFailure(); break;
            case "identity_rejected":
                release("3.2.17"); manifest(); validApk = false;
                expectFailure();
                require(operations.contains("validate"), "must reach APK identity validation"); break;
            case "both_offline": expectFailure(); break;
            case "unusable_release": release(""); expectFailure(); break;
            case "already_current":
                release("3.2.16"); manifest(); check(true);
                require(!installed && "complete".equals(state), "no unnecessary install"); break;
            case "theme_only":
                release("3.2.16");
                manifest().put("themeVersion", "4.0.0").put("themeSha256", SHA)
                    .put("themeZipUrl", "fixture:theme");
                check(true);
                require(!installed && operations.contains("download:fixture:theme") &&
                    "complete".equals(state), "independent theme update must remain available"); break;
            case "cheats_only":
                release("3.2.16");
                manifest().put("cheatCatalogVersion", "new").put("cheatCatalogSha256", SHA)
                    .put("cheatCatalogUrl", "fixture:cheats");
                check(true);
                require(!installed && operations.contains("download:fixture:cheats") &&
                    "complete".equals(state), "independent cheat update must remain available"); break;
            case "deferred_during_gameplay":
                release("3.2.17"); inGame = true; check(false);
                require(!installed && deferred && operations.contains("validate") &&
                    "available".equals(state), "installer must wait for the library: " + operations);
                break;
            case "reuse_verified_download":
                release("3.2.17"); alreadyDownloaded = true; expectInstall();
                require(!operations.contains("download:fixture:apk"),
                    "an already verified APK must not be downloaded again: " + operations);
                break;
            default: throw new AssertionError("unknown scenario");
        }
    }
    public static void main(String[] args) throws Exception {
        UpdateCheckFlowTest test = new UpdateCheckFlowTest();
        test.apk = new File(args[1], "fixture.apk");
        test.run(args[0]);
        System.out.println("PASS " + args[0]);
    }
}
'''


class UpdateCheckFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (JAVA / "javac").is_file():
            raise unittest.SkipTest("JDK required")
        source = SOURCE.read_text()
        check = source[source.index("    private void check(boolean userInitiated)"):
                       source.index("    private static AppRelease appRelease(")]
        comparison = source[source.index("    private static boolean isVersionNewer("):
                            source.index("    private File updateFile()")]
        comparison += source[source.index("    /** First manifest that loads;"):
                             source.index("    private static boolean trustedReleaseUrl(")]
        cls.work = tempfile.TemporaryDirectory(prefix="emufusion-update-flow-")
        cls.addClassCleanup(cls.work.cleanup)
        cls.env = dict(os.environ, JAVA_TOOL_OPTIONS=
                       "-Djava.awt.headless=true -Dapple.awt.UIElement=true")
        path = Path(cls.work.name) / "UpdateCheckFlowTest.java"
        path.write_text(HARNESS.replace("    // PRODUCTION_METHODS", check + comparison))
        subprocess.run([str(JAVA / "javac"), "-d", cls.work.name, str(path)],
                       env=cls.env, check=True, capture_output=True, timeout=30)

    def test_production_check_with_controlled_failure_boundaries(self):
        for scenario in ("missing_manifest", "malformed_manifest", "theme_unavailable",
                         "cheats_unavailable", "legacy_fallback", "missing_apk_checksum",
                         "wrong_apk_checksum", "identity_rejected", "both_offline",
                         "unusable_release", "already_current", "theme_only", "cheats_only",
                         "deferred_during_gameplay", "reuse_verified_download"):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(JAVA / "java"), "-ea", "-cp", self.work.name,
                    "UpdateCheckFlowTest", scenario, self.work.name], env=self.env,
                    text=True, capture_output=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
