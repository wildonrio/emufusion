from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
UPDATE = (ROOT / "android-companion" / "src" / "com" / "thorium" /
          "preview" / "UpdateManager.java").read_text(encoding="utf-8")
SERVICE = (ROOT / "android-companion" / "src" / "com" / "thorium" /
           "preview" / "PreviewService.java").read_text(encoding="utf-8")
APPLICATION = (ROOT / "unified-android" / "src" / "com" / "thorium" /
               "preview" / "LucentApplication.java").read_text(encoding="utf-8")
MANIFEST = (ROOT / "android-companion" / "AndroidManifest.xml").read_text(
    encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


class AutomaticAppUpdateTest(unittest.TestCase):
    def test_startup_checks_even_before_storage_permission(self):
        startup = SERVICE.split("updateManager = new UpdateManager(this);", 1)[1].split(
            "startServer();", 1)[0]
        self.assertIn("ThemeInstaller.hasStorageAccess(this)", startup)
        self.assertGreaterEqual(startup.count("updateManager.checkAsync(false)"), 2)
        self.assertIn("else {", startup)

    def test_latest_github_release_is_the_primary_app_channel(self):
        self.assertIn(
            "https://api.github.com/repos/wildonrio/emufusion/releases/latest",
            UPDATE,
        )
        self.assertNotIn("tyler-bam-ai", UPDATE)
        self.assertIn(
            "https://github.com/wildonrio/emufusion/releases/download/",
            UPDATE,
        )
        self.assertIn("for (String apiUrl : RELEASE_API_URLS)", UPDATE)
        self.assertIn('asset.optString("digest", "")', UPDATE)
        self.assertIn('digest.matches("(?i)^sha256:[0-9a-f]{64}$")', UPDATE)
        self.assertIn('"lucent-" + version + ".apk"', UPDATE)
        self.assertIn("RELEASE_DOWNLOAD_PREFIX", UPDATE)
        self.assertLess(UPDATE.index("AppRelease candidate = appRelease(release)"),
                        UPDATE.index("manifest.optInt(\"companionVersionCode\""))

    def test_failed_automatic_check_retries_soon(self):
        # October 9: the Thor's first post-release check ran with Wi-Fi
        # disconnected; it must not then wait six hours to try again.
        worker = UPDATE.split("void checkAsync(boolean userInitiated) {", 1)[1].split(
            "worker.start();", 1)[0]
        failure = worker.split("catch (Exception error) {", 1)[1].split("} finally {", 1)[0]
        self.assertIn("if (!userInitiated) retrySoonAfterFailure();", failure)
        retry = UPDATE.split("private void retrySoonAfterFailure() {", 1)[1].split("}", 1)[0]
        self.assertIn("- RECHECK_INTERVAL_MS + RETRY_AFTER_FAILURE_MS", retry)
        self.assertIn("RETRY_AFTER_FAILURE_MS = 10L * 60L * 1000L", UPDATE)

    def test_renamed_repository_keeps_the_legacy_channel_trusted(self):
        # pegasus-lucent was renamed to emufusion; installs from before the
        # rename and GitHub's redirects both still use the old name.
        for name in ("emufusion", "pegasus-lucent"):
            self.assertIn("https://api.github.com/repos/wildonrio/%s/releases/latest" % name, UPDATE)
            self.assertIn("https://github.com/wildonrio/%s/releases/download/" % name, UPDATE)
            self.assertIn("https://raw.githubusercontent.com/wildonrio/%s/main/release-manifest.json" % name,
                          UPDATE)
        self.assertIn("for (String url : MANIFEST_URLS)", UPDATE)
        self.assertNotIn("fetch(MANIFEST_URL,", UPDATE)

    def test_verified_download_automatically_opens_installer(self):
        app_branch = UPDATE.split("if (appNew) {", 1)[1].split("} else {", 1)[0]
        self.assertIn("download(appUrl, apk, MAX_APK, apkSha)", app_branch)
        self.assertIn("validateDownloadedApk(context, apk)", app_branch)
        self.assertIn("installDownloadedApk(true)", app_branch)
        self.assertIn("Intent.ACTION_VIEW", UPDATE)
        self.assertIn('"application/vnd.android.package-archive"', UPDATE)
        self.assertNotIn("Intent.ACTION_OPEN_DOCUMENT", UPDATE)
        self.assertNotIn("Intent.ACTION_GET_CONTENT", UPDATE)

    def test_every_build_checks_automatically(self):
        # The owner's devices run debug-signed personal builds; those must
        # update from GitHub on their own like any other install.
        check = UPDATE.split("void checkAsync(boolean userInitiated) {", 1)[1].split(
            "Thread worker", 1)[0]
        self.assertNotIn("isQualificationBuild", UPDATE)
        self.assertNotIn("return;", check.split("running.compareAndSet", 1)[0])

    def test_installer_waits_for_library_and_rechecks_there(self):
        app_branch = UPDATE.split("if (appNew) {", 1)[1].split("String remoteTheme", 1)[0]
        self.assertLess(app_branch.index("if (gameplayActive())"),
                        app_branch.index("installDownloadedApk(true)"))
        self.assertIn("deferInstallUntilLibrary()", app_branch)
        self.assertIn("if (!downloadedMatches(apk, apkSha))", app_branch)
        library = UPDATE.split("void onLibraryVisible() {", 1)[1].split("void checkAsync", 1)[0]
        self.assertIn("installDownloadedApk(true)", library)
        self.assertIn("RECHECK_INTERVAL_MS", library)
        self.assertIn("updateManager.setGameplayGate(() -> gameplayActive);", SERVICE)
        library_intent = SERVICE.split("ACTION_LIBRARY.equals(intent.getAction())", 1)[1].split(
            "} else if", 1)[0]
        self.assertIn("updateManager.onLibraryVisible();", library_intent)

    def test_apk_identity_is_checked_beyond_the_release_digest(self):
        validator = UPDATE.split("private static void validateDownloadedApk", 1)[1].split(
            "private static Signature[] signatures", 1)[0]
        self.assertIn("getPackageArchiveInfo", validator)
        self.assertIn("candidate.packageName", validator)
        self.assertIn("candidateCode <= installedCode", validator)
        self.assertIn("sharesSigner", validator)
        self.assertIn("apk.delete()", UPDATE)

    def test_permission_return_continues_without_file_manager(self):
        self.assertIn("Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES", UPDATE)
        self.assertIn("automaticInstallPending", UPDATE)
        self.assertIn("static void resumePendingInstall(Activity activity)", UPDATE)
        self.assertIn("UpdateManager.resumePendingInstall(activity);", APPLICATION)
        resume = UPDATE.split("static void resumePendingInstall", 1)[1].split(
            "private void installDownloadedApk", 1)[0]
        self.assertIn("openInstaller(context)", resume)
        self.assertIn("Display.DEFAULT_DISPLAY", resume)

    def test_android_declares_only_the_required_installer_boundary(self):
        self.assertIn("android.permission.REQUEST_INSTALL_PACKAGES", MANIFEST)
        self.assertIn('android:name=".UpdateFileProvider"', MANIFEST)
        self.assertIn('android:authorities="com.thorium.preview.updates"', MANIFEST)
        self.assertIn("there is no file-manager or Downloads-folder step", README)
        self.assertIn("final system Install confirmation", README)


if __name__ == "__main__":
    unittest.main()
