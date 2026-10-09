package com.thorium.preview;

import android.content.Context;

import com.thorium.lucent.emulators.ExternalEmulator;
import com.thorium.lucent.emulators.ExternalEmulatorDirectory;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Loads engines/external-emulators.json (packaged as asset
 * {@code external-emulators.json}) into the platform-neutral
 * {@link ExternalEmulatorDirectory} the Settings picker reads.
 *
 * The parsing lives here, in the Android layer, and the model lives in
 * com.thorium.lucent.emulators — the same split CheatCatalog/CheatDatabase
 * already use, and what lets the picker's data rules be tested on the host.
 *
 * A missing or damaged asset yields an empty directory rather than an
 * exception. That is a deliberate asymmetry: presentation fails soft (the
 * picker falls back to EmulatorCatalog, which still has every name, source and
 * launch recipe compiled in), while launching still fails closed through
 * EngineRouteStore. The directory can make the picker prettier and more
 * accurate; it can never make something launchable that the catalog would
 * refuse.
 */
final class ExternalEmulatorDirectoryLoader {
    private static final String ASSET = "external-emulators.json";
    private static final int SUPPORTED_SCHEMA = 1;

    // The asset changes only with the APK, so one parse per process is enough.
    private static volatile ExternalEmulatorDirectory cached;

    private ExternalEmulatorDirectoryLoader() {}

    static ExternalEmulatorDirectory load(Context context) {
        ExternalEmulatorDirectory result = cached;
        if (result != null) return result;
        synchronized (ExternalEmulatorDirectoryLoader.class) {
            if (cached == null) cached = parse(context);
            return cached;
        }
    }

    /** Tests and package replacement can force the asset to be reread. */
    static void invalidate() { cached = null; }

    private static ExternalEmulatorDirectory parse(Context context) {
        try {
            JSONObject root = new JSONObject(readAsset(context.getApplicationContext()));
            // An unrecognised schema is treated as no directory at all: a newer
            // file read with older rules would silently drop or mis-key rows.
            if (root.optInt("schemaVersion", 0) != SUPPORTED_SCHEMA)
                return ExternalEmulatorDirectory.empty();

            Map<String, ExternalEmulator> emulators = new LinkedHashMap<>();
            JSONArray rows = root.optJSONArray("emulators");
            if (rows != null) for (int index = 0; index < rows.length(); index++) {
                JSONObject row = rows.optJSONObject(index);
                if (row == null) continue;
                String id = row.optString("id");
                JSONObject install = row.optJSONObject("install");
                if (id.isEmpty() || install == null) continue;
                List<String> packages = new ArrayList<>();
                JSONArray rawPackages = row.optJSONArray("packages");
                if (rawPackages != null)
                    for (int p = 0; p < rawPackages.length(); p++) {
                        String name = rawPackages.optString(p);
                        if (!name.isEmpty() && !packages.contains(name)) packages.add(name);
                    }
                emulators.put(id, new ExternalEmulator(id, row.optString("name"),
                        packages, install.optString("kind"), install.optString("url"),
                        row.optBoolean("verified", false)));
            }

            Map<String, List<String[]>> systems = new LinkedHashMap<>();
            JSONObject bySystem = root.optJSONObject("systems");
            if (bySystem != null) {
                JSONArray keys = bySystem.names();
                if (keys != null) for (int index = 0; index < keys.length(); index++) {
                    String system = keys.optString(index);
                    JSONArray choices = bySystem.optJSONArray(system);
                    if (system.isEmpty() || choices == null) continue;
                    List<String[]> pairs = new ArrayList<>();
                    for (int c = 0; c < choices.length(); c++) {
                        JSONObject choice = choices.optJSONObject(c);
                        if (choice == null) continue;
                        String option = choice.optString("option");
                        if (option.isEmpty()) continue;
                        pairs.add(new String[] {option, choice.optString("app", option)});
                    }
                    systems.put(system, pairs);
                }
            }

            Map<String, String> unsupported = new LinkedHashMap<>();
            JSONArray unsupportedRows = root.optJSONArray("unsupportedSystems");
            if (unsupportedRows != null)
                for (int index = 0; index < unsupportedRows.length(); index++) {
                    JSONObject row = unsupportedRows.optJSONObject(index);
                    if (row == null) continue;
                    String system = row.optString("system");
                    String reason = row.optString("reason");
                    if (!system.isEmpty() && !reason.isEmpty())
                        unsupported.put(system, reason);
                }

            return ExternalEmulatorDirectory.of(emulators, systems, unsupported);
        } catch (Exception unavailable) {
            return ExternalEmulatorDirectory.empty();
        }
    }

    private static String readAsset(Context context) throws Exception {
        InputStream input = context.getAssets().open(ASSET);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        } finally { input.close(); }
    }
}
