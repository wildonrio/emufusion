package com.thorium.preview;

import android.content.Context;

import com.thorium.lucent.emulators.ExternalEmulatorDelivery;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Curated Android external-emulator catalog.
 *
 * Each canonical system maps to an ORDERED list of candidate emulators. The
 * first entry is the default external choice; every entry carries a direct
 * launch recipe so a game boots straight into gameplay (never the emulator's
 * own menu). External emulation is only ever selected as a per-system user
 * choice (EngineRouteStore), or automatically for a system that has no bundled
 * internal engine.
 *
 * Installation stays separate from discovery. Android only lets a regular app
 * silently install another APK when it is a device/profile owner, so EmuFusion can
 * detect a missing emulator and open its official source, but a normal retail
 * device must still confirm Android's package installer.
 */
final class EmulatorCatalog {

    // ROM delivery mechanisms an emulator accepts. Aliased to the platform-
    // neutral constants rather than re-spelled, so a custom entry validated by
    // CustomEmulatorSpec can never be well-formed there and unrecognised here.
    static final String DELIVERY_FILE_PATH = ExternalEmulatorDelivery.FILE_PATH;
    static final String DELIVERY_ACTION_VIEW = ExternalEmulatorDelivery.ACTION_VIEW;
    static final String DELIVERY_CONTENT_URI = ExternalEmulatorDelivery.CONTENT_URI;
    static final String DELIVERY_UNSUPPORTED = "unsupported";

    /** A single direct-launch option for a system. */
    static final class Option {
        final String id;
        final String name;
        final List<String> packages;   // aliases: paid/free, stable/nightly forks
        final String source;           // official source URL
        final String sourceType;       // store | github | official | official-api | external
        final String delivery;         // one of the DELIVERY_* constants
        final String action;           // intent action for the target component
        final String component;        // "<activity>" appended to installed package, or fully-qualified
        final String romExtraKey;      // string-extra key that carries the ROM path (FILE_PATH)
        final Map<String, String> extras; // additional fixed --es extras (e.g. RetroArch LIBRETRO)
        final String coreLibrary;      // libretro core file name for RetroArch-style hosts, or ""

        Option(String id, String name, String packages, String source, String sourceType,
               String delivery, String action, String component, String romExtraKey,
               Map<String, String> extras, String coreLibrary) {
            this.id = id;
            this.name = name;
            this.packages = words(packages);
            this.source = source == null ? "" : source;
            this.sourceType = sourceType == null ? "" : sourceType;
            this.delivery = delivery;
            this.action = action == null ? "" : action;
            this.component = component == null ? "" : component;
            this.romExtraKey = romExtraKey == null ? "" : romExtraKey;
            this.extras = extras == null ? Collections.<String, String>emptyMap() :
                    Collections.unmodifiableMap(new LinkedHashMap<>(extras));
            this.coreLibrary = coreLibrary == null ? "" : coreLibrary;
        }

        boolean supported() { return !DELIVERY_UNSUPPORTED.equals(delivery); }

        /**
         * The first of this option's package ids that is installed, or "".
         * Routed through InstalledPackages because a bare getPackageInfo is
         * silently wrong under Android 11+ package-visibility filtering — see
         * that class for why, and for what the manifest must declare.
         */
        String installedPackage(Context context) {
            return InstalledPackages.firstInstalled(context, packages);
        }
    }

    // system -> ordered candidate options
    private static final Map<String, List<Option>> BY_SYSTEM = new LinkedHashMap<>();

    static {
        // ----- Nintendo home/handheld -----
        put("nes", emuEx("nesemu", "NES.emu", "com.explusalpha.NesEmu"),
                retroArch("nes", "fceumm_libretro_android.so"));
        put("snes", emuEx("snes9x", "Snes9x EX+", "com.explusalpha.Snes9xPlus"),
                retroArch("snes", "snes9x_libretro_android.so"));
        put("gb", emuEx("gbcemu", "GBC.emu", "com.explusalpha.GbcEmu"),
                retroArch("gb", "gambatte_libretro_android.so"));
        put("gbc", emuEx("gbcemu", "GBC.emu", "com.explusalpha.GbcEmu"),
                retroArch("gbc", "gambatte_libretro_android.so"));
        put("gba", emuEx("gbaemu", "GBA.emu", "com.explusalpha.GbaEmu"),
                pathApp("myboy", "My Boy!", "com.fastemulator.gba com.fastemulator.gbafree",
                        "https://play.google.com/store/apps/details?id=com.fastemulator.gba",
                        "store", "com.fastemulator.emulator.EmulatorActivity", "ROM"),
                retroArch("gba", "mgba_libretro_android.so"));
        put("n64", pathApp("m64plus-fz", "M64Plus FZ",
                        "org.mupen64plusae.v3.fzurita.pro org.mupen64plusae.v3.fzurita " +
                        "org.mupen64plusae.v3.fzurita.amazon",
                        "https://github.com/mupen64plus-ae/mupen64plus-ae", "store",
                        "paulscode.android.mupen64plusae.SplashActivity", "ROM"),
                retroArch("n64", "mupen64plus_next_libretro_android.so"));
        put("nds", pathApp("melonds", "melonDS",
                        "me.magnum.melonds.nightly me.magnum.melonds me.magnum.melondualds",
                        "https://github.com/rafaelvcaetano/melonDS-android/releases", "github",
                        "me.magnum.melonds.ui.emulator.EmulatorActivity", "PATH"),
                pathApp("drastic", "DraStic", "com.dsemu.drastic",
                        "https://play.google.com/store/apps/details?id=com.dsemu.drastic",
                        "store", "com.dsemu.drastic.DraSticActivity", "GAME_PATH"),
                retroArch("nds", "melondsds_libretro_android.so"));
        // Keys are canonical system ids (EngineSystemIdResolver.canonical): the
        // catalog is looked up post-canonicalization, so GameCube is "gamecube"
        // (not "gc") and the 3DS is "3ds" (not "n3ds"). Keying on the raw alias
        // would leave those systems with no reachable external option.
        put("gamecube", contentUri("dolphin", "Dolphin", "org.dolphinemu.dolphinemu",
                        "https://dolphin-emu.org/download/", "official-api",
                        "org.dolphinemu.dolphinemu.ui.main.MainActivity"));
        put("wii", contentUri("dolphin", "Dolphin", "org.dolphinemu.dolphinemu",
                        "https://dolphin-emu.org/download/", "official-api",
                        "org.dolphinemu.dolphinemu.ui.main.MainActivity"));
        put("3ds", pathApp("azahar", "Azahar",
                        "org.azahar_emu.azahar io.github.lime3ds.android org.citra.emu",
                        "https://github.com/azahar-emu/azahar/releases", "github",
                        "org.citra.citra_emu.activities.EmulationActivity", "GamePath"),
                retroArch("n3ds", ""));
        put("switch", contentUri("eden", "Eden",
                        "dev.eden.eden_emulator dev.legacy.eden_emulator org.citron.citron_emu",
                        "https://eden-emu.dev/downloads/", "official",
                        "org.yuzu.yuzu_emu.activities.EmulationActivity"));
        put("wiiu", contentUri("cemu", "Cemu", "info.cemu.cemu",
                        "https://github.com/cemu-project/Cemu/releases", "github",
                        "info.cemu.cemu.emulation.EmulationActivity"));
        put("virtualboy", retroArch("virtualboy", "mednafen_vb_libretro_android.so"));

        // ----- Sega -----
        put("sg1000", mdEmu(), retroArch("sg1000", "genesis_plus_gx_libretro_android.so"));
        put("mastersystem", mdEmu(), retroArch("mastersystem", "genesis_plus_gx_libretro_android.so"));
        put("megadrive", mdEmu(), retroArch("megadrive", "genesis_plus_gx_libretro_android.so"));
        put("gamegear", mdEmu(), retroArch("gamegear", "genesis_plus_gx_libretro_android.so"));
        put("segacd", mdEmu(), retroArch("segacd", "genesis_plus_gx_libretro_android.so"));
        put("sega32x", mdEmu(), retroArch("sega32x", "picodrive_libretro_android.so"));
        put("saturn", emuEx("saturnemu", "Saturn.emu", "com.explusalpha.SaturnEmu"),
                retroArch("saturn", "mednafen_saturn_libretro_android.so"));
        put("dreamcast", pathApp("flycast", "Flycast",
                        "com.flycast.emulator com.reicast.emulator",
                        "https://github.com/flyinghead/flycast/releases", "github",
                        "com.flycast.emulator.MainActivity", "GAME_PATH"),
                pathApp("redream", "Redream", "io.recompiled.redream",
                        "https://play.google.com/store/apps/details?id=io.recompiled.redream",
                        "store", "io.recompiled.redream.MainActivity", "GAME"),
                retroArch("dreamcast", "flycast_libretro_android.so"));

        // ----- Sony -----
        put("psx", pathApp("duckstation", "DuckStation", "com.github.stenzek.duckstation",
                        "https://github.com/stenzek/duckstation/releases", "store",
                        "com.github.stenzek.duckstation.EmulationActivity", "bootPath"),
                pathApp("epsxe", "ePSXe", "com.epsxe.ePSXe",
                        "https://play.google.com/store/apps/details?id=com.epsxe.ePSXe",
                        "store", "com.epsxe.ePSXe.ePSXe", "com.epsxe.ePSXe.isoName"),
                retroArch("psx", "pcsx_rearmed_libretro_android.so"));
        put("ps2", pathApp("armsx2", "ARMSX2 / AetherSX2",
                        "com.armsx2 xyz.aethersx2.android",
                        "https://github.com/ARMSX2/ARMSX2", "external",
                        "xyz.aethersx2.android.EmulationActivity", "bootPath"),
                retroArch("ps2", "play_libretro_android.so"));
        put("psp", pathApp("ppsspp", "PPSSPP",
                        "org.ppsspp.ppssppgold org.ppsspp.ppsspp",
                        "https://dev.ppsspp.org/download/", "official-api",
                        "org.ppsspp.ppsspp.PpssppActivity", "ShortcutFile"),
                retroArch("psp", "ppsspp_libretro_android.so"));
        put("psvita", pathApp("vita3k", "Vita3K",
                        "org.vita3k.emulator org.vita3k.emulator.ikhoeyZX",
                        "https://github.com/Vita3K/Vita3K-Android/releases", "github",
                        "org.vita3k.emulator.Emulator", "AppPath"));

        // ----- NEC / SNK / Bandai -----
        put("pcengine", emuEx("pceemu", "PCE.emu", "com.PceEmu"),
                retroArch("pcengine", "mednafen_pce_fast_libretro_android.so"));
        put("pcenginecd", emuEx("pceemu", "PCE.emu", "com.PceEmu"),
                retroArch("pcenginecd", "mednafen_pce_fast_libretro_android.so"));
        put("neogeo", emuEx("neoemu", "NEO.emu", "com.explusalpha.NeoEmu"),
                retroArch("neogeo", "fbneo_libretro_android.so"));
        put("neogeocd", emuEx("neoemu", "NEO.emu", "com.explusalpha.NeoEmu"),
                retroArch("neogeocd", "fbneo_libretro_android.so"));
        put("ngp", emuEx("ngpemu", "NGP.emu", "com.explusalpha.NgpEmu"),
                retroArch("ngp", "mednafen_ngp_libretro_android.so"));
        put("wonderswan", emuEx("swanemu", "Swan.emu", "com.explusalpha.SwanEmu"),
                retroArch("wonderswan", "mednafen_wswan_libretro_android.so"));
        put("wonderswancolor", emuEx("swanemu", "Swan.emu", "com.explusalpha.SwanEmu"),
                retroArch("wonderswancolor", "mednafen_wswan_libretro_android.so"));

        // ----- Home computers / arcade / misc -----
        put("arcade", pathApp("mame4droid", "MAME4droid 2024", "com.seleuco.mame4d2024",
                        "https://github.com/seleuco/MAME4droid-2024/releases", "github",
                        "com.seleuco.mame4d2024.MAME4droid", "MAME4all_path"),
                retroArch("arcade", "fbneo_libretro_android.so"));
        put("c64", emuEx("c64emu", "C64.emu", "com.explusalpha.C64Emu"),
                retroArch("c64", "vice_x64_libretro_android.so"));
        put("msx", emuEx("msxemu", "MSX.emu", "com.explusalpha.MsxEmu"),
                retroArch("msx", "bluemsx_libretro_android.so"));
        put("colecovision", pathApp("colem", "ColEm",
                        "com.fms.colem.deluxe com.fms.colem", "https://fms.komkon.org/ColEm/",
                        "store", "com.fms.emulib.EmulatorActivity", "path"),
                retroArch("colecovision", "bluemsx_libretro_android.so"));
        put("atari2600", emuEx("2600emu", "2600.emu", "com.explusalpha.A2600Emu"),
                retroArch("atari2600", "stella2014_libretro_android.so"));
        put("atari5200", pathApp("colleen", "Colleen", "name.nick.jubanka.colleen",
                        "https://github.com/romjacket/Colleen", "external",
                        "name.nick.jubanka.colleen.MainActivity", "ROM"),
                retroArch("atari5200", "a5200_libretro_android.so"));
        put("atari800", pathApp("colleen", "Colleen", "name.nick.jubanka.colleen",
                        "https://github.com/romjacket/Colleen", "external",
                        "name.nick.jubanka.colleen.MainActivity", "ROM"),
                retroArch("atari800", "atari800_libretro_android.so"));
        put("atari7800", retroArch("atari7800", "prosystem_libretro_android.so"));
        put("intellivision", retroArch("intellivision", "freeintv_libretro_android.so"));
        put("odyssey2", retroArch("odyssey2", "o2em_libretro_android.so"));
        put("amiga", retroArch("amiga", "puae_libretro_android.so"));
        put("amigacd32", retroArch("amigacd32", "puae_libretro_android.so"));
        put("atarist", retroArch("atarist", "hatari_libretro_android.so"));
        put("jaguar", retroArch("jaguar", "virtualjaguar_libretro_android.so"));
        put("3do", retroArch("3do", "opera_libretro_android.so"));
        put("zxspectrum", pathApp("speccy", "Speccy",
                        "com.fms.speccy.deluxe com.fms.speccy", "https://fms.komkon.org/Speccy/",
                        "store", "com.fms.emulib.EmulatorActivity", "path"),
                retroArch("zxspectrum", "fuse_libretro_android.so"));
        put("amstradcpc", retroArch("amstradcpc", "cap32_libretro_android.so"));
        put("windows", pathApp("winlator", "Winlator",
                        "com.winlator.vanilla com.winlator.cmod com.winlator",
                        "https://github.com/brunodev85/winlator/releases", "github",
                        "com.winlator.XServerDisplayActivity", "exe_path"));
        put("dos", pathApp("dosbox", "Magic DOSBox",
                        "bruenor.magicbox.free bruenor.magicbox", "https://magicbox.imejl.sk/",
                        "store", "bruenor.magicbox.MainActivity", "path"),
                retroArch("dos", "dosbox_pure_libretro_android.so"));
        put("scummvm", pathApp("scummvm", "ScummVM", "org.scummvm.scummvm",
                        "https://www.scummvm.org/downloads/", "official",
                        "org.scummvm.scummvm.SplashActivity", "path"));

        // Systems with no maintained direct-launch Android emulator at all.
        // These stay explicit so EmuFusion never pretends an abandoned or
        // nonexistent build can be installed or launched: Xenia (xbox/xbox360)
        // has no Android port, and no maintained Apple II emulator ships an
        // Android launch surface. (PS3 now routes to aPS3e above.)
        unsupported("apple2 xbox xbox360");
    }

    // ---- Option builders -----------------------------------------------------

    /** emu-ex-plus-alpha family: boots directly through ACTION_VIEW on the ROM. */
    private static Option emuEx(String id, String name, String packages) {
        return new Option(id, name, packages,
                "https://www.explusalpha.com/contents/emuex", "store",
                DELIVERY_ACTION_VIEW, "android.intent.action.VIEW",
                "com.imagine.BaseActivity", "", null, "");
    }

    private static Option mdEmu() {
        return emuEx("mdemu", "MD.emu", "com.explusalpha.MdEmu");
    }

    /** A path-accepting standalone emulator: --es <romExtraKey> "{file.path}". */
    private static Option pathApp(String id, String name, String packages, String source,
                                  String sourceType, String activity, String romExtraKey) {
        return new Option(id, name, packages, source, sourceType,
                DELIVERY_FILE_PATH, "android.intent.action.MAIN", activity, romExtraKey, null, "");
    }

    /** Scoped-storage emulator that needs a content URI, routed via the trampoline. */
    private static Option contentUri(String id, String name, String packages, String source,
                                     String sourceType, String activity) {
        return new Option(id, name, packages, source, sourceType,
                DELIVERY_CONTENT_URI, "android.intent.action.VIEW", activity, "", null, "");
    }

    /**
     * RetroArch is a valid EXTERNAL option (the historical ban was only on
     * building EmuFusion's own UI on top of RetroArch). It boots straight into the
     * ROM when both ROM and LIBRETRO core path are supplied, so it is only
     * listed for a system with a known libretro core.
     */
    private static Option retroArch(String system, String coreLibrary) {
        Map<String, String> extras = new LinkedHashMap<>();
        // LIBRETRO is completed at command-build time with the installed package
        // so the core path resolves against the correct RetroArch flavour.
        return new Option("retroarch-" + system, "RetroArch",
                "com.retroarch.aarch64 com.retroarch",
                "https://play.google.com/store/apps/details?id=com.retroarch", "store",
                DELIVERY_FILE_PATH, "android.intent.action.MAIN",
                "com.retroarch.browser.retroactivity.RetroActivityFuture", "ROM", extras,
                coreLibrary);
    }

    private static void put(String system, Option... options) {
        BY_SYSTEM.put(system, Collections.unmodifiableList(new ArrayList<>(Arrays.asList(options))));
    }

    private static void unsupported(String systems) {
        for (String system : words(systems))
            BY_SYSTEM.put(system, Collections.singletonList(new Option(
                    "no-standalone", "No maintained standalone Android emulator", "",
                    "", "", DELIVERY_UNSUPPORTED, "", "", "", null, "")));
    }

    // ---- Public lookups ------------------------------------------------------

    /** Ordered candidate options for a canonical system, or empty when unknown. */
    static List<Option> optionsForSystem(String system) {
        List<Option> options = BY_SYSTEM.get(canonical(system));
        return options == null ? Collections.<Option>emptyList() : options;
    }

    /** True when at least one supported (launchable) external option exists. */
    static boolean hasExternalOption(String system) {
        for (Option option : optionsForSystem(system))
            if (option.supported()) return true;
        return false;
    }

    static Option optionForId(String system, String id) {
        if (id == null) return null;
        for (Option option : optionsForSystem(system))
            if (option.id.equalsIgnoreCase(id)) return option;
        return null;
    }

    /**
     * {@link #optionForId} plus the system's user-defined "Custom" target,
     * which by definition is not compiled into the catalog and needs a Context
     * to be read back and re-checked against the device.
     *
     * A custom id whose app has since been uninstalled resolves to null and so
     * falls back to the catalog order rather than leaving the system
     * unlaunchable; the picker separately reports it as needing setup again.
     */
    static Option resolvedOptionForId(Context context, String system, String id) {
        if (CustomEmulatorStore.ID.equalsIgnoreCase(id == null ? "" : id.trim()))
            return CustomEmulatorStore.option(context, system);
        return optionForId(system, id);
    }

    /**
     * Chooses the effective external option for a launch: the user's choice when
     * it is still a valid catalog entry, otherwise the first installed option,
     * otherwise the first supported option (so the install flow can begin).
     */
    static Option effectiveOption(Context context, String system, String chosenId) {
        Option chosen = resolvedOptionForId(context, system, chosenId);
        if (chosen != null && chosen.supported()) return chosen;
        Option firstSupported = null;
        for (Option option : optionsForSystem(system)) {
            if (!option.supported()) continue;
            if (firstSupported == null) firstSupported = option;
            if (!option.installedPackage(context).isEmpty()) return option;
        }
        return firstSupported;
    }

    /**
     * Builds the metadata {@code launch:} command Pegasus executes for an
     * external route. When the chosen emulator is installed the command boots
     * the ROM directly into gameplay; when it is missing the command opens the
     * emulator's official install source instead of failing. Returns "" only
     * when the system has no supported external option (fail closed).
     */
    static String externalLaunchCommand(Context context, String system, String chosenId) {
        Option option = effectiveOption(context, system, chosenId);
        if (option == null || !option.supported()) return "";
        String installed = option.installedPackage(context);
        if (installed.isEmpty()) return installCommand(option);
        return directLaunchCommand(option, installed);
    }

    /** The direct-into-gameplay recipe for an installed emulator. */
    static String directLaunchCommand(Option option, String installedPackage) {
        if (DELIVERY_CONTENT_URI.equals(option.delivery)) {
            // Route through EmuFusion's own trampoline, which grants a one-time
            // content URI to the scoped-storage target and forwards it.
            return "am start -a " + RomLaunchActivity.ACTION_LAUNCH_FILE +
                    " -n com.thorium.preview/com.thorium.preview.RomLaunchActivity" +
                    " --es path \"{file.path}\"" +
                    " --es target_package " + installedPackage +
                    " --es target_activity " + option.component +
                    " --es target_action " + option.action +
                    ("dolphin".equals(option.id)
                            ? " --es launch_profile dolphin" : "");
        }
        StringBuilder command = new StringBuilder("am start");
        if (!option.action.isEmpty()) command.append(" -a ").append(option.action);
        command.append(" -n ").append(installedPackage).append('/').append(option.component);
        if (DELIVERY_ACTION_VIEW.equals(option.delivery)) {
            command.append(" -d \"file://{file.path}\" -t application/octet-stream");
        } else { // FILE_PATH
            String key = option.romExtraKey.isEmpty() ? "ROM" : option.romExtraKey;
            command.append(" --es ").append(key).append(" \"{file.path}\"");
            if (!option.coreLibrary.isEmpty())
                command.append(" --es LIBRETRO ")
                        .append("/data/data/").append(installedPackage)
                        .append("/cores/").append(option.coreLibrary);
            for (Map.Entry<String, String> extra : option.extras.entrySet())
                command.append(" --es ").append(extra.getKey()).append(' ').append(extra.getValue());
        }
        command.append(" --activity-clear-task");
        return command.toString();
    }

    /**
     * A launch that opens the emulator's official source so the user can install
     * it. Play/store sources open the Play page; github/official sources open
     * the release page in a browser. Never a silent install.
     */
    static String installCommand(Option option) {
        String uri = installUri(option);
        if (uri.isEmpty()) return "";
        return "am start -a android.intent.action.VIEW -d " + uri;
    }

    static String installUri(Option option) {
        String primaryPackage = option.packages.isEmpty() ? "" : option.packages.get(0);
        if ("store".equals(option.sourceType) && !primaryPackage.isEmpty())
            return "market://details?id=" + primaryPackage;
        return option.source == null ? "" : option.source;
    }

    // ---- Install / status surfaces ------------------------------------------

    /** Distinct supported emulators that are not installed for the active systems. */
    static List<Option> missingFor(Context context, Set<String> activeSystems) {
        List<Option> missing = new ArrayList<>();
        Set<String> seen = new java.util.LinkedHashSet<>();
        for (String folder : activeSystems) {
            for (Option option : optionsForSystem(folder)) {
                if (!option.supported() || !option.installedPackage(context).isEmpty()) continue;
                if (seen.add(option.id)) missing.add(option);
            }
        }
        return missing;
    }

    static String statusJson(Context context, Set<String> activeSystems) {
        JSONObject response = new JSONObject();
        JSONArray systems = new JSONArray();
        int ready = 0;
        int missing = 0;
        try {
            for (String folder : activeSystems) {
                GameSystems.SystemDef system = GameSystems.byFolder(folder);
                if (system == null) continue;
                String canonical = canonical(folder);
                List<Option> options = optionsForSystem(canonical);
                JSONObject row = new JSONObject();
                row.put("system", folder);
                row.put("collection", system.collection);
                boolean anySupported = hasExternalOption(canonical);
                boolean anyInstalled = false;
                JSONArray optionsJson = new JSONArray();
                for (Option option : options) {
                    if (!option.supported()) continue;
                    String installed = option.installedPackage(context);
                    boolean present = !installed.isEmpty();
                    anyInstalled |= present;
                    JSONObject entry = new JSONObject();
                    entry.put("id", option.id);
                    entry.put("name", option.name);
                    entry.put("installed", present);
                    entry.put("installedPackage", installed);
                    entry.put("source", option.source);
                    entry.put("sourceType", option.sourceType);
                    entry.put("delivery", option.delivery);
                    optionsJson.put(entry);
                }
                row.put("state", !anySupported ? "unsupported" :
                        anyInstalled ? "ready" : "missing");
                row.put("options", optionsJson);
                if (anySupported) {
                    if (anyInstalled) ready++;
                    else missing++;
                }
                systems.put(row);
            }
            response.put("active", systems.length());
            response.put("ready", ready);
            response.put("missing", missing);
            response.put("systems", systems);
            response.put("silentInstallAvailable", false);
            response.put("installPolicy", "Android confirmation required unless device owner");
        } catch (Exception ignored) {}
        return response.toString();
    }

    // ---- helpers -------------------------------------------------------------

    private static String canonical(String value) {
        return com.thorium.lucent.metadata.EngineSystemIdResolver.canonical(value);
    }

    private static List<String> words(String value) {
        String trimmed = value == null ? "" : value.trim();
        return trimmed.isEmpty() ? Collections.<String>emptyList() :
                Collections.unmodifiableList(Arrays.asList(trimmed.split("\\s+")));
    }

    private EmulatorCatalog() {}
}
