package com.thorium.preview.game;

import android.content.Context;
import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.util.Map;

/**
 * Per-system widescreen hack policy (design section 7) and the launch-time
 * core-option override channel.
 *
 * <p><b>Preference resolution.</b> {@link WidescreenSettings#hackMode} gives
 * {@code on|off|auto} per system; {@code auto} follows
 * {@link WidescreenSettings#isHackEnabled} (default false). The hack is
 * reported enabled only when the system actually has a mechanism
 * ({@link WidescreenHackTable#availability}: {@code hack} or {@code cheats});
 * natively-16:9 consoles and 2D systems never report it on.</p>
 *
 * <p><b>Engine roots.</b> {@link #prepareLaunch} writes
 * {@code <engine root>/}{@link CoreOptionOverrideFile#NAME} where
 * {@code <engine root>} is the directory every in-process engine already
 * receives as its libretro/adapter system directory. The derivation below
 * replicates, read-only, what the sessions do:</p>
 * <ul>
 * <li>Phase 1 libretro cores ({@code LibretroEngineSession.prepare} via
 *     {@code LibretroEngineSpec.installRuntime}):
 *     {@code context.getDir("engine-system", MODE_PRIVATE)/<engineId>}.</li>
 * <li>Phase 2 cores ({@code PpssppGlesEngineSession.prepare} via
 *     {@code Phase2QualificationCatalog.Entry.installRuntimeAssets}): the same
 *     {@code engine-system/<engineId>} directory, with runtime assets and
 *     firmware copied inside it.</li>
 * <li>Phase 3 native adapters ({@code NativeAdapterSystemDirectory.engineRoot}):
 *     again {@code engine-system/<engineId>}.</li>
 * </ul>
 * <p>Both libretro sessions pass that directory to the native host as
 * {@code system_directory}; {@code register_core_variable_defaults()} in
 * {@code lucent_libretro_host.c} reads the override file from it after its
 * own reviewed defaults. Native adapters have no core-option channel, so for
 * them the file is informational only. The cheat launch hooks (owner B)
 * reuse {@link #engineRoot} for their boot-delivered patch files.</p>
 *
 * <p>Failures here never block a game: every filesystem error is logged and
 * swallowed, and a stale file from a previous launch is always replaced or
 * removed before the engine starts.</p>
 */
public final class WidescreenHackPolicy {
    private static final String TAG = "WidescreenHackPolicy";

    private WidescreenHackPolicy() {}

    /** Contract 4: is the hack in effect for this system on this launch? */
    public static boolean isHackEnabledFor(Context context, String systemId) {
        if (!WidescreenHackTable.isHackApplicable(systemId)) return false;
        String mode = WidescreenSettings.hackMode(context, systemId);
        if (WidescreenSettings.HACK_MODE_ON.equals(mode)) return true;
        if (WidescreenSettings.HACK_MODE_OFF.equals(mode)) return false;
        return WidescreenSettings.isHackEnabled(context);
    }

    /** Contract 4: {@code native | hack | cheats | unavailable}. */
    public static String availability(String systemId) {
        return WidescreenHackTable.availability(systemId);
    }

    /** Contract 4: the override table (design section 7). */
    public static Map<String, String> coreOptionOverrides(
            String systemId, String engineId, boolean hackOn) {
        return WidescreenHackTable.coreOptionOverrides(systemId, engineId, hackOn);
    }

    /** The engine's system root; see the class comment for the derivation. */
    public static File engineRoot(Context context, String engineId) {
        String engine = WidescreenHackTable.normaliseEngine(engineId);
        if (context == null || engine.isEmpty()) return null;
        return new File(context.getApplicationContext()
                .getDir("engine-system", Context.MODE_PRIVATE), engine);
    }

    /** Contract 4: write or remove the override file before the engine opens. */
    public static void prepareLaunch(Context context, GameLaunchRequest request,
                                     String engineId) {
        prepareLaunch(context, request, engineId, false);
    }

    /**
     * As {@link #prepareLaunch(Context, GameLaunchRequest, String)}; the cheat
     * launch hooks pass {@code true} once they have enabled a per-game 16:9
     * code so Dolphin's generic projection hack is left off for that title.
     */
    public static void prepareLaunch(Context context, GameLaunchRequest request,
                                     String engineId,
                                     boolean perGameWidescreenCodeSelected) {
        if (context == null || request == null) return;
        String engine = engineId != null && !engineId.isEmpty() ?
                engineId : request.engineId;
        String system = request.systemId;
        File root = engineRoot(context, engine);
        if (root == null) return;
        boolean hackOn = isHackEnabledFor(context, system);
        Map<String, String> overrides = WidescreenHackTable.coreOptionOverrides(
                system, engine, hackOn, perGameWidescreenCodeSelected);
        File file = CoreOptionOverrideFile.in(root);
        try {
            if (overrides.isEmpty()) {
                if (!CoreOptionOverrideFile.delete(file))
                    Log.w(TAG, "Could not remove stale override file " + file);
            } else {
                CoreOptionOverrideFile.write(file, overrides);
            }
            Log.i(TAG, "Widescreen hack engine=" + engine + " system=" + system +
                    " availability=" + availability(system) + " on=" + hackOn +
                    " overrides=" + overrides);
        } catch (IOException | RuntimeException e) {
            // Never block a launch on the override channel.
            Log.w(TAG, "Could not write core-option overrides for " + engine, e);
        }
    }
}
