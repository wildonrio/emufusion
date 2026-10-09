package com.thorium.preview;

import android.app.Activity;
import android.content.ClipData;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Toast;

import com.thorium.preview.game.DiscImagePreflight;

import java.io.File;
import java.io.IOException;

/**
 * EmuFusion's own content-URI trampoline for scoped-storage external emulators.
 *
 * Pegasus executes an {@code am start} recipe that targets this Activity for any
 * emulator whose delivery is {@code content-uri} (see EmulatorCatalog). It
 * converts the ROM filesystem path from Pegasus into a one-time, read-only
 * content URI, grants that exact URI to the target emulator, and forwards the
 * launch directly into the emulator's gameplay Activity.
 *
 * The Activity is declared {@code android:exported="false"}: Android then only
 * lets components in EmuFusion's own uid start it, which is exactly the boundary
 * required — only Pegasus's in-process {@code am start} reaches it, never
 * another app. It is a trampoline, not an emulator, and carries no launcher or
 * home category.
 */
public final class RomLaunchActivity extends Activity {
    public static final String ACTION_LAUNCH_FILE = "com.thorium.preview.LAUNCH_FILE";
    private static final String AUTHORITY = "com.thorium.preview.roms";

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        launch(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        launch(intent);
    }

    private void launch(Intent request) {
        if (request == null) { finish(); return; }
        String path = request.getStringExtra("path");
        String targetPackage = request.getStringExtra("target_package");
        String targetActivity = request.getStringExtra("target_activity");
        String targetAction = request.getStringExtra("target_action");
        String launchProfile = request.getStringExtra("launch_profile");
        if (path == null || targetPackage == null || targetActivity == null ||
                targetPackage.isEmpty() || targetActivity.isEmpty()) {
            finish();
            return;
        }
        // A standalone emulator cannot inherit EmuFusion's in-window Stop
        // handler. Never launch while the same-APK accessibility monitor is
        // disabled: doing so would silently promise a held-Stop return Android
        // cannot deliver. Authorization is requested when External is linked
        // in Settings, not as an intermediary game-launch screen.
        if (!ExternalEmulationSession.stopControlEnabled(this) &&
                !"ps3".equals(launchProfile) && !"dolphin".equals(launchProfile)) {
            Toast.makeText(this,
                    "Finish external emulator setup in EmuFusion Settings first.",
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }

        // Confine the source to the same storage roots RomFileProvider serves,
        // so a malformed recipe can never hand out an arbitrary system file.
        File rom;
        try {
            rom = new File(path).getCanonicalFile();
        } catch (IOException error) {
            finish();
            return;
        }
        String canonical = rom.getPath();
        if (!(canonical.startsWith("/storage/") || canonical.startsWith("/mnt/media_rw/")) ||
                !rom.isFile()) {
            finish();
            return;
        }

        if ("ps3".equals(launchProfile)) {
            launchPs3(rom, targetPackage, targetActivity, targetAction);
            return;
        }

        if ("dolphin".equals(launchProfile)) {
            try {
                // RVZ and WIA carry their declared container length and header
                // checksums. Reject a partial copy before Dolphin opens it; ISO,
                // WBFS and NKit keep their normal direct-launch path.
                DiscImagePreflight.validate("gamecube", rom);
            } catch (Exception invalid) {
                Toast.makeText(this, invalid.getMessage(), Toast.LENGTH_LONG).show();
                finish();
                return;
            }
        }

        Uri uri = new Uri.Builder().scheme("content").authority(AUTHORITY)
                .appendPath("rom").appendPath(rom.getName())
                .appendQueryParameter("path", canonical).build();
        int grant = Intent.FLAG_GRANT_READ_URI_PERMISSION;
        grantUriPermission(targetPackage, uri, grant);
        if (targetActivity.startsWith(".")) targetActivity = targetPackage + targetActivity;
        if (targetAction == null || targetAction.isEmpty()) targetAction = Intent.ACTION_VIEW;

        Intent launch = new Intent(targetAction)
                .setComponent(new ComponentName(targetPackage, targetActivity))
                .setDataAndType(uri, "application/octet-stream")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                        Intent.FLAG_ACTIVITY_CLEAR_TOP | grant);
        launch.setClipData(ClipData.newRawUri("rom", uri));
        ExternalEmulationSession.Snapshot previous =
                ExternalEmulationSession.snapshot(this);
        if (previous.active)
            ExternalEmulationSession.abandon(this, previous.token);
        try {
            startActivity(launch);
            String token = ExternalEmulationSession.begin(
                    this, targetPackage, launch.getComponent().flattenToString());
            if (token.isEmpty())
                throw new IllegalStateException("external session identity was rejected");
        } catch (RuntimeException error) {
            // A missing target simply ends the trampoline; the external route's
            // install flow surfaces the missing emulator elsewhere.
        } finally {
            finish();
        }
    }

    private void launchPs3(File indexedPath, String targetPackage,
                           String targetActivity, String targetAction) {
        if (targetActivity.startsWith(".")) targetActivity = targetPackage + targetActivity;
        if (targetAction == null || targetAction.isEmpty())
            targetAction = "aenu.intent.action.APS3E";
        // launch_profile=ps3 is not a generic custom-emulator surface. Keep it
        // pinned to aPS3e's exported contract so stale or hand-edited metadata
        // cannot silently revive the retired Emulator_ui/game_path recipe.
        if (!"aenu.aps3e".equals(targetPackage) ||
                !"aenu.aps3e.EmulatorActivity".equals(targetActivity) ||
                !"aenu.intent.action.APS3E".equals(targetAction)) {
            Toast.makeText(this,
                    "Refresh the PS3 emulator route in EmuFusion Settings.",
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        Intent launch = new Intent(targetAction)
                .setComponent(new ComponentName(targetPackage, targetActivity))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int grant = Intent.FLAG_GRANT_READ_URI_PERMISSION;
        String lower = indexedPath.getName().toLowerCase(java.util.Locale.US);
        if ("eboot.bin".equals(lower)) {
            File usrdir = indexedPath.getParentFile();
            File ps3Game = usrdir == null ? null : usrdir.getParentFile();
            File titleRoot = ps3Game == null ? null : ps3Game.getParentFile();
            if (usrdir == null || ps3Game == null || titleRoot == null ||
                    !"usrdir".equalsIgnoreCase(usrdir.getName()) ||
                    !"ps3_game".equalsIgnoreCase(ps3Game.getName()) ||
                    !new File(ps3Game, "PARAM.SFO").isFile()) {
                Toast.makeText(this,
                        "This PS3 folder is incomplete (EBOOT/PARAM.SFO mismatch).",
                        Toast.LENGTH_LONG).show();
                finish();
                return;
            }
            launch.putExtra("game_dir", titleRoot.getAbsolutePath());
        } else if (lower.endsWith(".iso")) {
            Uri uri = new Uri.Builder().scheme("content").authority(AUTHORITY)
                    .appendPath("rom").appendPath(indexedPath.getName())
                    .appendQueryParameter("path", indexedPath.getAbsolutePath()).build();
            grantUriPermission(targetPackage, uri, grant);
            launch.putExtra("iso_uri", uri.toString());
            launch.addFlags(grant);
            launch.setClipData(ClipData.newRawUri("ps3-iso", uri));
        } else {
            Toast.makeText(this,
                    "PS3 games must be a decrypted folder dump or ISO.",
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        ExternalEmulationSession.Snapshot previous =
                ExternalEmulationSession.snapshot(this);
        if (previous.active) ExternalEmulationSession.abandon(this, previous.token);
        try {
            startActivity(launch);
            String token = ExternalEmulationSession.begin(
                    this, targetPackage, launch.getComponent().flattenToString());
            if (token.isEmpty())
                throw new IllegalStateException("external PS3 session identity was rejected");
        } catch (RuntimeException error) {
            Toast.makeText(this, "aPS3e could not start this game.", Toast.LENGTH_LONG).show();
        } finally {
            finish();
        }
    }
}
