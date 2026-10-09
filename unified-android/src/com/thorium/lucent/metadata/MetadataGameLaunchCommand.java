package com.thorium.lucent.metadata;

/** Pure builder for the one same-window EmuFusion metadata command. */
public final class MetadataGameLaunchCommand {
    private static final String ACTION = "com.thorium.preview.LAUNCH_INTERNAL_GAME";
    private static final String COMPONENT =
            "com.thorium.preview/org.pegasus_frontend.android.MainActivity";

    private MetadataGameLaunchCommand() {}

    public static String build(String metadataSystem, String engineId) {
        return build(metadataSystem, engineId, ACTION);
    }

    public static String build(String metadataSystem, String engineId,
                               String action) {
        String system = EngineSystemIdResolver.canonical(metadataSystem);
        String engine = normalize(engineId);
        String launchAction = action == null ? "" : action.trim();
        if (system.isEmpty() || engine.isEmpty() || launchAction.isEmpty()) return "";
        // Pegasus's Android frontend accepts only `am start` syntax. EmuFusion's
        // patched MainActivity.launchAmCommand intercepts this exact internal
        // action before startActivity, validates it, and attaches the host to
        // the already-live Activity. The command therefore remains compatible
        // with Pegasus while producing no Activity lifecycle transition.
        return "am start -a " + launchAction + " -n " + COMPONENT +
                " --es path \"{file.path}\" --es system " + system +
                " --es engine_id " + engine;
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(java.util.Locale.US)
                .replaceAll("[^a-z0-9-]+", "");
    }
}
