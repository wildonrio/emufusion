package com.thorium.preview.game;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;

import java.io.File;

/** Exported, argument-validating bridge from Pegasus commands to EmuFusion's private activity. */
public final class InternalGameLaunchActivity extends Activity {
    public static final String ACTION_LAUNCH = "com.thorium.preview.LAUNCH_INTERNAL_GAME";
    private static final String AUTHORITY = "com.thorium.preview.roms";
    private static final String TAG = "LucentLaunch";

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        launch(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        launch(intent);
    }

    private void launch(Intent source) {
        if (source == null || !ACTION_LAUNCH.equals(source.getAction())) {
            finish();
            return;
        }
        String path = source.getStringExtra("path");
        if (path == null || path.trim().isEmpty()) {
            finish();
            return;
        }

        String filename = new File(path).getName();
        Uri uri = new Uri.Builder().scheme("content").authority(AUTHORITY)
                .appendPath("rom").appendPath(filename)
                .appendQueryParameter("path", path).build();
        GameLaunchRequest request = new GameLaunchRequest(
                source.getStringExtra("engine_id"),
                source.getStringExtra("system_id"),
                source.getStringExtra("game_id"),
                source.getStringExtra("title"),
                uri,
                SessionReturnState.from(source),
                "",
                FrameGenerationSettings.mode(this));
        if (!request.isValid()) {
            finish();
            return;
        }
        Log.i(TAG, "Internal route accepted engine=" + request.engineId +
                " system=" + request.systemId);

        Intent launch = LucentGameActivity.createIntent(this, request)
                .setDataAndType(uri, "application/octet-stream");
        launch.setClipData(ClipData.newRawUri("rom", uri));
        try {
            startActivity(launch);
        } finally {
            finish();
        }
    }
}
