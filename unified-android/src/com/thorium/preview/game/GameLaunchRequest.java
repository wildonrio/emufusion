package com.thorium.preview.game;

import android.content.Intent;
import android.net.Uri;

/** Immutable, engine-neutral description of one in-process game launch. */
public final class GameLaunchRequest {
    public static final String EXTRA_ENGINE_ID = "lucent.engine_id";
    public static final String EXTRA_SYSTEM_ID = "lucent.system_id";
    public static final String EXTRA_GAME_ID = "lucent.game_id";
    public static final String EXTRA_GAME_TITLE = "lucent.game_title";
    public static final String EXTRA_CONTENT_URI = "lucent.content_uri";
    public static final String EXTRA_QUALIFICATION_SESSION =
            "lucent.qualification_session";
    public static final String EXTRA_FRAME_GENERATION_MODE =
            "lucent.frame_generation_mode";

    public final String engineId;
    public final String systemId;
    public final String gameId;
    public final String gameTitle;
    public final Uri contentUri;
    /** Non-empty only for an explicitly validated QA launch with supported storage isolation. */
    public final String qualificationSession;
    /** Owner mode captured once, before any engine or Surface is created. */
    public final FrameGenerationSettings.Mode frameGenerationMode;
    public final SessionReturnState returnState;

    public GameLaunchRequest(String engineId, String systemId, String gameId,
                             String gameTitle, Uri contentUri,
                             SessionReturnState returnState) {
        this(engineId, systemId, gameId, gameTitle, contentUri, returnState, "");
    }

    public GameLaunchRequest(String engineId, String systemId, String gameId,
                             String gameTitle, Uri contentUri,
                             SessionReturnState returnState,
                             String qualificationSession) {
        this(engineId, systemId, gameId, gameTitle, contentUri, returnState,
                qualificationSession, FrameGenerationSettings.Mode.OFF);
    }

    public GameLaunchRequest(String engineId, String systemId, String gameId,
                             String gameTitle, Uri contentUri,
                             SessionReturnState returnState,
                             String qualificationSession,
                             FrameGenerationSettings.Mode frameGenerationMode) {
        this.engineId = clean(engineId);
        this.systemId = clean(systemId);
        this.gameId = clean(gameId);
        this.gameTitle = clean(gameTitle);
        this.contentUri = contentUri;
        this.qualificationSession = clean(qualificationSession);
        this.frameGenerationMode = frameGenerationMode == null ?
                FrameGenerationSettings.Mode.OFF : frameGenerationMode;
        this.returnState = returnState == null ? SessionReturnState.EMPTY : returnState;
    }

    public boolean isValid() {
        return !engineId.isEmpty() && !systemId.isEmpty() && !gameId.isEmpty()
                && contentUri != null;
    }

    public Intent putInto(Intent intent) {
        intent.putExtra(EXTRA_ENGINE_ID, engineId)
                .putExtra(EXTRA_SYSTEM_ID, systemId)
                .putExtra(EXTRA_GAME_ID, gameId)
                .putExtra(EXTRA_GAME_TITLE, gameTitle)
                .putExtra(EXTRA_CONTENT_URI, contentUri.toString())
                .putExtra(EXTRA_QUALIFICATION_SESSION, qualificationSession)
                .putExtra(EXTRA_FRAME_GENERATION_MODE,
                        frameGenerationMode.storedValue());
        returnState.putInto(intent);
        return intent;
    }

    public static GameLaunchRequest from(Intent intent) {
        if (intent == null) {
            return new GameLaunchRequest("", "", "", "", null,
                    SessionReturnState.EMPTY);
        }
        String rawUri = value(intent, EXTRA_CONTENT_URI);
        return new GameLaunchRequest(
                value(intent, EXTRA_ENGINE_ID),
                value(intent, EXTRA_SYSTEM_ID),
                value(intent, EXTRA_GAME_ID),
                value(intent, EXTRA_GAME_TITLE),
                rawUri.isEmpty() ? intent.getData() : Uri.parse(rawUri),
                SessionReturnState.from(intent),
                value(intent, EXTRA_QUALIFICATION_SESSION),
                FrameGenerationSettings.Mode.parse(
                        value(intent, EXTRA_FRAME_GENERATION_MODE)));
    }

    private static String value(Intent intent, String key) {
        return clean(intent.getStringExtra(key));
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
