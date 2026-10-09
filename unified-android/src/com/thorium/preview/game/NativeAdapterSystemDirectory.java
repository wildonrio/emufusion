package com.thorium.preview.game;

import android.content.Context;
import android.os.Environment;
import android.os.Build;
import android.system.Os;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Resolves the validated per-engine system directory a Phase 3 native adapter
 * is handed as {@code lucent_native_load_request.system_directory}.
 *
 * This mirrors {@link LibretroEngineSpec}'s {@code installSystem}/
 * {@code installRuntime} contract: the engine root is always the app-private
 * {@code engine-system/<engineId>} directory, and any user-supplied runtime
 * input is copied INTO that private root before the engine reads it. Nothing
 * here is ever bundled in the APK.
 *
 * Each engine that declares user-supplied inputs gets its own {@link Layout},
 * because the two consoles EmuFusion runs in-process store them nothing alike:
 *
 * <ul>
 * <li><b>eden / switch</b> calls {@code Common::FS::SetAppDirectory(root)} and
 *     then reads {@code keys/prod.keys} (plus an optional {@code keys/title.keys})
 *     and, for titles that need it, a system firmware set under
 *     {@code nand/system/Contents/registered} that EmuFusion can extract from
 *     the user's {@code Firmware*.zip}. Firmware is game-specific and optional
 *     at the routing boundary; {@code prod.keys} is the baseline prerequisite.</li>
 * <li><b>cemu / wiiu</b> has NO firmware archive at all and exactly one input:
 *     {@code keys.txt}, the list of AES-128 disc keys. It goes at the ROOT of
 *     the engine directory, because that is literally where Cemu's KeyCache
 *     reads it from -- {@code ActiveSettings::GetUserDataPath("keys.txt")}, and
 *     the adapter points every Cemu root at this directory. One blob, so the
 *     adapter reports {@code required_firmware = 1}.</li>
 * </ul>
 *
 * The user's files live outside the app (the reference layouts are
 * {@code /storage/emulated/0/Games/switch/Keys/} plus a {@code Firmware*.zip}
 * beside it, and {@code /storage/emulated/0/Games/wiiu/Keys/keys.txt}) and are
 * discovered by a bounded, case-insensitive scan of the same volume roots
 * Phase 2 uses for BIOS files. Missing or invalid prerequisites fail closed
 * behind one generic launch error rather than letting the engine boot into an
 * undecryptable state that would look like a hang.
 */
final class NativeAdapterSystemDirectory {
    private static final String TAG = "LucentPhase3System";

    /* Layout Eden derives from the app directory (Common::FS::GetYuzuPath). */
    private static final String KEYS_DIRECTORY = "keys";
    private static final String FIRMWARE_DIRECTORY = "nand/system/Contents/registered";
    private static final String REQUIRED_KEY = "prod.keys";
    private static final String OPTIONAL_KEY = "title.keys";
    private static final String FIRMWARE_MARKER = ".lucent-firmware-source";
    /* Layout Cemu derives from its user-data path (KeyCache_Prepare). */
    private static final String WIIU_KEY = "keys.txt";
    /* Official Sony system software supplied by the device owner. */
    private static final String PS3_UPDATE = "PS3UPDAT.PUP";
    private static final String SOURCE_MARKER_PREFIX = ".lucent-source-";
    private static final int MAX_SCAN_DEPTH = 8;

    /**
     * One user-supplied file: what it is called on the user's storage, where the
     * engine reads it back from inside the private root, and whether the engine
     * can boot without it.
     */
    private static final class RuntimeFile {
        final String sourceName;
        final String destination;
        final boolean required;
        final String placementHint;

        RuntimeFile(String sourceName, String destination, boolean required,
                    String placementHint) {
            this.sourceName = sourceName;
            this.destination = destination;
            this.required = required;
            this.placementHint = placementHint;
        }
    }

    /**
     * One engine's complete runtime-input profile.
     *
     * Everything that differs between consoles is data on this object: which
     * volume-relative directories to scan, which files to install and where the
     * engine expects them, and whether a firmware archive exists at all. Adding
     * a console means adding a Layout, not another engine-id comparison inside
     * the install path.
     */
    private static final class Layout {
        final String engineId;
        /**
         * Every id this console is known by. Wii U reaches EmuFusion as both
         * "wiiu" and the "wii-u" slug, and the rest of the app accepts both
         * (SecondaryGameplaySurfaceRouter, NativeAdapterEngineSession), so a
         * key layout that only knew one of them would fail closed on a launch
         * that is perfectly valid.
         */
        final String[] systemIds;
        /** Volume-relative directories to scan, most specific first. */
        final String[] searchDirectories;
        final RuntimeFile[] files;
        /** Only the Switch accepts an optional firmware archive to unpack. */
        final boolean installsFirmwareArchive;
        /** Reported when installation finishes but the root is still short. */
        final String incompleteMessage;

        Layout(String engineId, String[] systemIds, String[] searchDirectories,
               RuntimeFile[] files, boolean installsFirmwareArchive,
               String incompleteMessage) {
            this.engineId = engineId;
            this.systemIds = systemIds;
            this.searchDirectories = searchDirectories;
            this.files = files;
            this.installsFirmwareArchive = installsFirmwareArchive;
            this.incompleteMessage = incompleteMessage;
        }

        boolean matches(String engine, String system) {
            if (!engineId.equals(engine)) return false;
            for (String candidate : systemIds)
                if (candidate.equals(system)) return true;
            return false;
        }
    }

    private static final Layout SWITCH_LAYOUT = new Layout(
            "eden", new String[] {"switch"},
            new String[] {"Games/switch", "ROMs/switch", "BIOS/switch", "Games", "ROMs"},
            new RuntimeFile[] {
                new RuntimeFile(REQUIRED_KEY, KEYS_DIRECTORY + "/" + REQUIRED_KEY,
                        true, "Games/switch/Keys"),
                // title.keys is optional: many titles decrypt from prod.keys
                // alone, so a missing one must not block a launch that would
                // otherwise work.
                new RuntimeFile(OPTIONAL_KEY, KEYS_DIRECTORY + "/" + OPTIONAL_KEY,
                        false, "Games/switch/Keys"),
            },
            true,
            "Switch production keys were not installed");

    private static final Layout WIIU_LAYOUT = new Layout(
            "cemu", new String[] {"wiiu", "wii-u"},
            new String[] {"Games/wiiu", "ROMs/wiiu", "BIOS/wiiu", "Games", "ROMs"},
            // Destination is the bare root name on purpose: Cemu's
            // KeyCache_Prepare() opens ActiveSettings::GetUserDataPath("keys.txt")
            // and the adapter sets every Cemu root to this directory, so
            // <root>/keys.txt is the one path the engine will ever look at.
            new RuntimeFile[] {
                new RuntimeFile(WIIU_KEY, WIIU_KEY, true, "Games/wiiu/Keys"),
            },
            false,
            "Wii U disc keys are required but were not installed");

    private static final Layout PS3_LAYOUT = new Layout(
            "aps3e", new String[] {"ps3"},
            new String[] {"Games/ps3", "ROMs/ps3", "BIOS/ps3", "Games", "ROMs",
                    "Download", "Downloads"},
            new RuntimeFile[] {
                new RuntimeFile(PS3_UPDATE, PS3_UPDATE, true, "Games/ps3/Firmware"),
            },
            false,
            "PlayStation 3 system software was not installed");

    private static final Layout[] LAYOUTS = {SWITCH_LAYOUT, WIIU_LAYOUT, PS3_LAYOUT};

    private NativeAdapterSystemDirectory() {}

    /**
     * Seeds the environment aPS3e reads from native static initialization.
     *
     * <p>The pinned aPS3e tree implements {@code rp3_get_config_dir()} as a
     * direct {@code std::string(getenv("APS3E_DATA_DIR"))}. RPCS3 can call that
     * function while {@code dlopen()} is still running, before Lucent can call
     * the adapter's {@code load} entry point. A missing variable therefore
     * dereferences null inside the dynamic loader instead of returning a Java
     * error. Create the exact private root that {@link #resolve} will return and
     * publish every path needed by early native initialization before the host
     * constructs {@code NativeAdapterHost}.
     *
     * <p>This hook is deliberately aPS3e-only. Eden and Cemu retain their
     * existing initialization and environment ownership.
     */
    static File prepareForOpen(Context context, String engineId, String systemId)
            throws Exception {
        return prepareForOpen(context, engineId, systemId, "");
    }

    static File prepareForOpen(Context context, String engineId, String systemId,
                               String qualificationSession) throws Exception {
        if (context == null) throw new IllegalArgumentException("context is required");
        String engine = normalize(engineId);
        if (!"aps3e".equals(engine)) return null;
        if (!PS3_LAYOUT.matches(engine, normalize(systemId)))
            throw unavailable(context, systemId);
        File root = engineRoot(context, engine, qualificationSession);
        File logs = requireDirectory(new File(root, "logs"));
        File config = requireDirectory(new File(root, "config"));
        requireDirectory(new File(root, "cache"));
        // overwrite=true is intentional: a prior Phase 3 session may have set
        // process-global values for another root, while this exact app-private
        // root is the only directory the current launch is allowed to use.
        Os.setenv("APS3E_DATA_DIR", root.getCanonicalPath(), true);
        Os.setenv("APS3E_LOG_DIR", logs.getCanonicalPath(), true);
        Os.setenv("APS3E_GLOBAL_CONFIG_YAML_PATH",
                new File(config, "config.yml").getCanonicalPath(), true);
        Os.setenv("APS3E_ENABLE_LOG", "true", true);
        Os.setenv("APS3E_ANDROID_API_VERSION",
                Integer.toString(Build.VERSION.SDK_INT), true);
        return root;
    }

    private static File engineRoot(Context context, String engine) {
        return engineRoot(context, engine, "");
    }

    private static File engineRoot(Context context, String engine, String qualificationSession) {
        return new File(context.getDir(systemDirectoryName(qualificationSession),
                Context.MODE_PRIVATE), engine);
    }

    // PS3 and Switch store guest saves under the system root as well as wrapper
    // files under engine-saves. Both must be separated for an explicit QA run.
    static String systemDirectoryName(String session) {
        String namespace = validatedQualificationSession(session);
        return namespace.isEmpty() ? "engine-system" : "engine-system-qa-" + namespace;
    }

    static String saveDirectoryName(String session) {
        String namespace = validatedQualificationSession(session);
        return namespace.isEmpty() ? "engine-saves" : "engine-saves-qa/" + namespace;
    }

    private static String validatedQualificationSession(String session) {
        if (session == null || session.isEmpty()) return "";
        if (!session.matches("qa-[0-9a-f]{32}"))
            throw new IllegalArgumentException("Invalid native qualification session");
        return session;
    }

    private static File requireDirectory(File directory) throws Exception {
        if (!directory.isDirectory() && !directory.mkdirs())
            throw new IllegalStateException("Cannot create adapter system directory");
        return directory.getCanonicalFile();
    }

    /**
     * Creates (and, where a profile requires it, populates) the engine's
     * private system root.
     *
     * @param requiredFirmware the adapter's own {@code required_firmware} count.
     *        Zero means the engine declares no user-supplied inputs and only the
     *        empty private root is needed.
     * @throws IllegalStateException when the root cannot be created, or when an
     *         engine that requires user-supplied keys/firmware has none.
     */
    static File resolve(Context context, String engineId, String systemId,
                        int requiredFirmware) throws Exception {
        return resolve(context, engineId, systemId, requiredFirmware, "");
    }

    static File resolve(Context context, String engineId, String systemId,
                        int requiredFirmware, String qualificationSession) throws Exception {
        return resolve(context, engineId, systemId, requiredFirmware, qualificationSession, null);
    }

    static File resolve(Context context, String engineId, String systemId,
                        int requiredFirmware, String qualificationSession, File content) throws Exception {
        if (context == null) throw new IllegalArgumentException("context is required");
        String engine = normalize(engineId);
        if (engine.isEmpty()) throw new IllegalArgumentException("engine id is required");
        File root = requireDirectory(engineRoot(context, engine, qualificationSession));
        if (requiredFirmware <= 0) return root;
        Layout layout = layoutFor(engine, normalize(systemId));
        if (layout == null)
            // Fail closed: an adapter that declares user-supplied firmware but
            // has no audited resolution profile must not boot with an empty root.
            throw unavailable(context, systemId, qualificationSession);
        try {
            // Launch is a validation boundary, not another library audit.  The
            // update/import scan already searches every Android-readable
            // shared-storage root (including arbitrary nested folders), and a
            // first launch still performs that same fail-closed installation
            // below when no private baseline exists.  Once the validated
            // required files are installed, however, searching all of shared
            // storage to depth eight on every A press is both unnecessary and
            // catastrophically expensive: the measured Switch e3f run spent
            // 15,061 ms in this method without installing a single file.
            //
            // Optional Switch firmware cannot decide baseline eligibility --
            // Eden requires it only for particular titles -- so its absence or
            // a newly-added archive must not turn every otherwise-ready launch
            // back into a full-volume audit.  A later update/import scan can
            // refresh readiness; the engine always receives the last validated
            // app-private installation here.
            if (hasRuntimeInputs(root, layout)) {
                if (qualificationSession == null || qualificationSession.isEmpty())
                    NativeAdapterPrerequisites.record(context, systemId, true);
                return root;
            }
            // Cemu's legacy capability count describes disc-key installation,
            // not a requirement for decrypted content. Keep importing valid
            // owner-supplied keys when available, but do not block WUA/RPX/ELF
            // or WUHB on a fresh device merely because it has no disc keys.
            // Cemu still validates the actual file and all title dependencies.
            if (layout == WIIU_LAYOUT && isDecryptedWiiUContent(content)) {
                for (RuntimeFile file : layout.files) installFile(root, layout, file, false);
                if (qualificationSession == null || qualificationSession.isEmpty())
                    NativeAdapterPrerequisites.record(context, systemId, hasRuntimeInputs(root, layout));
                return root;
            }
            installRuntimeInputs(root, layout);
            if (qualificationSession == null || qualificationSession.isEmpty())
                NativeAdapterPrerequisites.record(context, systemId, true);
            return root;
        } catch (Exception failure) {
            // The UI gets one generic error. Exact user filenames and storage
            // paths remain implementation details of the scanner and are never
            // persisted or surfaced from the launch boundary.
            throw unavailable(context, systemId, qualificationSession);
        }
    }

    private static boolean isDecryptedWiiUContent(File content) {
        if (!isReadableFile(content)) return false;
        String name = content.getName().toLowerCase(Locale.US);
        return name.endsWith(".wua") || name.endsWith(".rpx") ||
                name.endsWith(".elf") || name.endsWith(".wuhb");
    }

    private static IllegalStateException unavailable(Context context, String systemId) {
        return unavailable(context, systemId, "");
    }

    private static IllegalStateException unavailable(Context context, String systemId,
                                                     String qualificationSession) {
        // A failed isolated prerequisite installation says nothing about the
        // normal root. Preserve its readiness on failure as well as success.
        if (qualificationSession == null || qualificationSession.isEmpty())
            NativeAdapterPrerequisites.record(context, systemId, false);
        Log.w(TAG, "Internal emulator prerequisites unavailable system=" +
                normalize(systemId));
        return new IllegalStateException("Internal emulator prerequisites are unavailable");
    }

    /**
     * True only when Eden itself or this validated-directory boundary identifies
     * a missing key/firmware prerequisite. Unsupported content and unrelated
     * crashes must remain internal failures rather than being mislabeled as a
     * reason to leave the app.
     */
    static boolean isPrerequisiteFailure(String engineId, Throwable failure) {
        String engine = normalize(engineId);
        if (!"eden".equals(engine) && !"aps3e".equals(engine)) return false;
        Throwable cursor = failure;
        for (int depth = 0; cursor != null && depth < 8; depth++, cursor = cursor.getCause()) {
            String message = cursor.getMessage();
            String value = message == null ? "" : message.toLowerCase(Locale.US);
            if (value.contains("internal emulator prerequisites are unavailable") ||
                    value.contains("missing firmware") ||
                    value.contains("required firmware") ||
                    value.contains("firmware is missing") ||
                    value.contains("missing production key") ||
                    value.contains("prod.keys") ||
                    value.contains("ps3 system update") ||
                    value.contains("ps3 firmware") ||
                    value.contains("ps3updat.pup") ||
                    value.contains("key/firmware directory") ||
                    value.contains("system archive is missing")) return true;
        }
        return false;
    }

    /** Actionable setup text; never includes key contents or a user's paths. */
    static String prerequisiteHelp(String engineId, String systemId, Throwable failure) {
        Layout layout = layoutFor(normalize(engineId), normalize(systemId));
        if (layout == null) return "";
        boolean missing = isPrerequisiteFailure(engineId, failure);
        // Cemu's directory boundary uses the same generic failure, but its
        // unrelated engine failures must not be labeled as missing disc keys.
        Throwable cursor = failure;
        for (int depth = 0; !missing && cursor != null && depth < 8;
                depth++, cursor = cursor.getCause()) {
            missing = "Internal emulator prerequisites are unavailable".equals(
                    cursor.getMessage());
        }
        if (!missing) return "";
        if (layout == SWITCH_LAYOUT)
            return "Switch setup is incomplete. Copy your own prod.keys to " +
                    "ROMs/switch/Keys and any firmware required by this game to " +
                    "ROMs/switch, then refresh the library and try again.";
        if (layout == WIIU_LAYOUT)
            return "Wii U setup is incomplete. Copy your disc keys.txt to " +
                    "ROMs/wiiu/Keys, then refresh the library and try again.";
        return "PlayStation 3 setup is incomplete. Copy your PS3UPDAT.PUP system " +
                "software to ROMs/ps3/Firmware, then refresh the library and try again.";
    }

    private static Layout layoutFor(String engineId, String systemId) {
        for (Layout layout : LAYOUTS)
            if (layout.matches(engineId, systemId)) return layout;
        return null;
    }

    /** True when the private root already holds everything the engine needs. */
    private static boolean hasRuntimeInputs(File root, Layout layout) {
        if (root == null) return false;
        for (RuntimeFile file : layout.files)
            if (file.required && !validRuntimeFile(
                    layout, file, new File(root, file.destination)))
                return false;
        return true;
    }

    /**
     * Read-only update-scan probe. It accepts either a previously validated
     * private installation or a complete set on the explicitly supplied,
     * readable storage roots. It copies and extracts nothing.
     */
    static boolean prerequisitesPresent(Context context, String engineId, String systemId,
                                        List<File> permittedVolumeRoots) {
        if (context == null) return false;
        Layout layout = layoutFor(normalize(engineId), normalize(systemId));
        if (layout == null) return false;
        File privateRoot = new File(context.getDir("engine-system", Context.MODE_PRIVATE),
                layout.engineId);
        if (installedPrerequisitesPresent(privateRoot, engineId, systemId)) return true;
        return prerequisiteSourcesPresent(engineId, systemId, permittedVolumeRoots);
    }

    /** Pure helper used by host QA to verify an already-installed private root. */
    static boolean installedPrerequisitesPresent(File privateRoot, String engineId,
                                                 String systemId) {
        Layout layout = layoutFor(normalize(engineId), normalize(systemId));
        return layout != null && hasRuntimeInputs(privateRoot, layout);
    }

    /**
     * Pure, read-only source probe over caller-supplied permitted roots. This
     * deliberately performs no Android storage discovery, copy, or extraction.
     */
    static boolean prerequisiteSourcesPresent(String engineId, String systemId,
                                              List<File> permittedVolumeRoots) {
        Layout layout = layoutFor(normalize(engineId), normalize(systemId));
        if (layout == null) return false;
        try {
            for (RuntimeFile file : layout.files) {
                if (!file.required) continue;
                File source = findValidUserFile(layout, file,
                        layout.searchDirectories, permittedVolumeRoots);
                if (source == null) return false;
            }
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    private static boolean validRuntimeFile(Layout layout, RuntimeFile runtime,
                                            File file) {
        if (!isReadableFile(file)) return false;
        if (WIIU_KEY.equals(runtime.sourceName)) return hasWiiUDiscKey(file);
        if (REQUIRED_KEY.equals(runtime.sourceName) && "eden".equals(layout.engineId))
            return hasSwitchProductionKey(file);
        if (PS3_UPDATE.equals(runtime.sourceName) && "aps3e".equals(layout.engineId))
            return hasPs3Update(file);
        return true;
    }

    private static boolean hasPs3Update(File file) {
        // RPCS3 validates the complete signed PUP during installation.  This
        // read-only routing probe only establishes a plausible, bounded source
        // and the exact SCE update-container magic; the adapter remains the
        // authoritative parser before any internal route starts.
        if (!isReadableFile(file) || file.length() < 10L * 1024L * 1024L ||
                file.length() > 1024L * 1024L * 1024L) return false;
        try {
            InputStream input = new java.io.FileInputStream(file);
            try {
                byte[] magic = new byte[8];
                int offset = 0;
                while (offset < magic.length) {
                    int count = input.read(magic, offset, magic.length - offset);
                    if (count < 0) return false;
                    offset += count;
                }
                byte[] expected = {'S', 'C', 'E', 'U', 'F', 0, 0, 0};
                return java.util.Arrays.equals(magic, expected);
            } finally { input.close(); }
        } catch (Exception ignored) { return false; }
    }

    private static boolean hasWiiUDiscKey(File file) {
        // Mirror Cemu's KeyCache_Prepare parser: comments begin at '#' or ';'
        // and formatting whitespace, '-' and '_' is ignored.  Do not accept
        // the example value Cemu itself writes when keys.txt is absent; that
        // placeholder proves only that Cemu ran once, not that the owner
        // supplied a usable disc key.
        if (!isReadableFile(file) || file.length() > 4L * 1024L * 1024L) return false;
        try {
            BufferedReader reader = new BufferedReader(new FileReader(file));
            try {
                String line;
                while ((line = reader.readLine()) != null) {
                    int comment = line.length();
                    int hash = line.indexOf('#');
                    int semicolon = line.indexOf(';');
                    if (hash >= 0) comment = Math.min(comment, hash);
                    if (semicolon >= 0) comment = Math.min(comment, semicolon);
                    String value = line.substring(0, comment)
                            .replace(" ", "").replace("\t", "")
                            .replace("-", "").replace("_", "")
                            .toLowerCase(Locale.US);
                    if (value.matches("[0-9a-f]{32}") &&
                            !"541b9889519b27d363cd21604b97c67a".equals(value))
                        return true;
                }
            } finally { reader.close(); }
        } catch (Exception ignored) {}
        return false;
    }

    private static boolean hasSwitchProductionKey(File file) {
        return hasMatchingLine(file,
                "(?i)[a-z0-9_]+\\s*=\\s*[0-9a-f]{16,128}");
    }

    private static boolean hasMatchingLine(File file, String expression) {
        // Key files are small text manifests. Refuse an unexpected large file
        // instead of reading arbitrary user content during an update scan.
        if (!isReadableFile(file) || file.length() > 4L * 1024L * 1024L) return false;
        try {
            BufferedReader reader = new BufferedReader(new FileReader(file));
            try {
                String line;
                while ((line = reader.readLine()) != null) {
                    String value = line.trim();
                    if (value.isEmpty() || value.startsWith("#") || value.startsWith(";"))
                        continue;
                    if (value.matches(expression)) return true;
                }
            } finally { reader.close(); }
        } catch (Exception ignored) {}
        return false;
    }

    private static void installRuntimeInputs(File root, Layout layout) throws Exception {
        for (RuntimeFile file : layout.files) installFile(root, layout, file);
        if (layout.installsFirmwareArchive) installFirmware(root, layout);
        if (!hasRuntimeInputs(root, layout))
            throw new IllegalStateException(layout.incompleteMessage);
    }

    /**
     * Copies one user-supplied file into the private root.
     *
     * The user's copy wins whenever it is present and differs from whatever was
     * installed last time. "Install only when the destination is absent" cannot
     * be used here: Cemu's own {@code KeyCache_Prepare()} WRITES a placeholder
     * keys.txt holding a single example key when it finds none, so one launch
     * without a key would otherwise leave a file that looks installed forever.
     * An already-installed copy is still kept when the user's source has gone
     * away, so deleting it from external storage after a successful install does
     * not break an engine that was working.
     */
    private static void installFile(File root, Layout layout, RuntimeFile file)
            throws Exception {
        installFile(root, layout, file, file.required);
    }

    private static void installFile(File root, Layout layout, RuntimeFile file, boolean required)
            throws Exception {
        File destination = new File(root, file.destination);
        File source = findValidUserFile(layout, file, layout.searchDirectories,
                storageVolumes());
        if (source == null) {
            if (isReadableFile(destination) || !required) return;
            throw new IllegalStateException("A user-supplied " + file.sourceName +
                    " is required; place it in " + file.placementHint +
                    " on device storage");
        }
        // The marker name and content are hashes. Persist neither the source
        // filename/path nor the destination's identifying filename.
        File marker = new File(root, SOURCE_MARKER_PREFIX +
                digestText(file.destination).substring(0, 16));
        String identity = sourceIdentity(source);
        String installed = isReadableFile(marker) ? readAscii(marker).trim() : "";
        if (isReadableFile(destination) && identity.equals(installed)) return;
        File parent = destination.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs())
            throw new IllegalStateException("Cannot create adapter key directory");
        copyFile(source, destination);
        writeAscii(marker, identity);
        Log.i(TAG, "Installed validated user key data engine=" + layout.engineId +
                " bytes=" + destination.length());
    }

    private static void installFirmware(File root, Layout layout) throws Exception {
        File registered = new File(root, FIRMWARE_DIRECTORY);
        File archive = findFirmwareArchive(layout.searchDirectories);
        String identity = archive == null ? "" : sourceIdentity(archive);
        File marker = new File(root, FIRMWARE_MARKER);
        String installed = isReadableFile(marker) ? readAscii(marker).trim() : "";
        if (countFirmware(registered) > 0 &&
                (identity.isEmpty() || identity.equals(installed))) return;
        // Eden firmware is title-specific. A valid archive is installed when
        // supplied, but its absence (or an unrelated/invalid zip) must not
        // disable the many games that boot with production keys alone.
        if (archive == null) return;
        if (!registered.isDirectory() && !registered.mkdirs())
            throw new IllegalStateException("Cannot create adapter firmware directory");
        int extracted = extractFirmware(archive, registered);
        if (extracted <= 0) throw new IllegalStateException(
                "The Switch firmware archive contained no installable content");
        writeAscii(marker, identity);
        Log.i(TAG, "Installed validated user Switch firmware files=" + extracted);
    }

    /**
     * Copies every NCA out of a user firmware archive into the private
     * registered directory. Only the entry's BASE name is ever used, so a
     * hostile archive cannot traverse out of the destination.
     *
     * A NAND-derived archive may store one NCA as a directory of numbered
     * fragments ({@code <id>.nca/00}, {@code /01}, ...). Those are concatenated
     * in name order into the single file Eden expects, so a split title is not
     * silently truncated to its last fragment.
     */
    private static int extractFirmware(File archive, File registered) throws Exception {
        int extracted = 0;
        ZipFile zip = new ZipFile(archive);
        try {
            java.util.LinkedHashMap<String, List<ZipEntry>> grouped =
                    new java.util.LinkedHashMap<>();
            java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                String target = firmwareEntryName(entry);
                if (target == null) continue;
                List<ZipEntry> fragments = grouped.get(target);
                if (fragments == null) {
                    fragments = new ArrayList<>();
                    grouped.put(target, fragments);
                }
                fragments.add(entry);
            }
            for (java.util.Map.Entry<String, List<ZipEntry>> group : grouped.entrySet()) {
                File destination = new File(registered, group.getKey());
                if (!registered.equals(destination.getParentFile())) continue;
                List<ZipEntry> fragments = group.getValue();
                java.util.Collections.sort(fragments, (left, right) ->
                        left.getName().compareTo(right.getName()));
                long total = 0;
                for (ZipEntry fragment : fragments) total += Math.max(0, fragment.getSize());
                if (destination.isFile() && total > 0 && destination.length() == total) {
                    extracted++;
                    continue;
                }
                writeFragments(zip, fragments, destination);
                extracted++;
            }
        } finally { zip.close(); }
        return extracted;
    }

    /**
     * A firmware archive stores each title either as a flat {@code <id>.nca} or
     * as a directory {@code <id>.nca/00}. Both land under the single registered
     * name Eden scans for.
     */
    private static String firmwareEntryName(ZipEntry entry) {
        if (entry == null || entry.isDirectory()) return null;
        String name = entry.getName().replace('\\', '/');
        String base = name.substring(name.lastIndexOf('/') + 1);
        if (base.toLowerCase(Locale.US).endsWith(".nca")) return base;
        String parent = name.lastIndexOf('/') <= 0 ? "" :
                name.substring(0, name.lastIndexOf('/'));
        String parentBase = parent.substring(parent.lastIndexOf('/') + 1);
        if (parentBase.toLowerCase(Locale.US).endsWith(".nca")) return parentBase;
        return null;
    }

    private static int countFirmware(File registered) {
        if (registered == null || !registered.isDirectory()) return 0;
        File[] entries = registered.listFiles();
        if (entries == null) return 0;
        int count = 0;
        for (File entry : entries)
            if (entry.isFile() && entry.length() > 0 &&
                    entry.getName().toLowerCase(Locale.US).endsWith(".nca")) count++;
        return count;
    }

    /** Non-identifying content identity; no source name or path is persisted. */
    private static String sourceIdentity(File source) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        InputStream input = new java.io.FileInputStream(source);
        try {
            byte[] buffer = new byte[256 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) digest.update(buffer, 0, count);
        } finally { input.close(); }
        return hex(digest.digest());
    }

    private static String digestText(String value) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        return hex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
    }

    private static String hex(byte[] bytes) {
        StringBuilder value = new StringBuilder(bytes.length * 2);
        for (byte item : bytes)
            value.append(String.format(Locale.US, "%02x", item & 0xff));
        return value.toString();
    }

    private static File findValidUserFile(Layout layout, RuntimeFile runtime,
                                          String[] directories, List<File> volumes) {
        for (File root : searchRoots(directories, volumes)) {
            File match = findValidByName(root, layout, runtime, 0);
            if (match != null) return match;
        }
        return null;
    }

    private static File findFirmwareArchive(String[] directories) {
        return findFirmwareArchive(directories, storageVolumes());
    }

    private static File findFirmwareArchive(String[] directories, List<File> volumes) {
        File best = null;
        for (File root : searchRoots(directories, volumes)) {
            File match = findFirmwareArchive(root, 0);
            // Prefer the largest candidate: a complete firmware set is far
            // larger than a partial or single-title archive.
            if (match != null && (best == null || match.length() > best.length()))
                best = match;
        }
        return best;
    }

    private static File findValidByName(File root, Layout layout, RuntimeFile runtime,
                                        int depth) {
        if (root == null || depth > MAX_SCAN_DEPTH || !root.isDirectory()) return null;
        File[] entries = sorted(root.listFiles());
        if (entries == null) return null;
        for (File entry : entries)
            if (entry.isFile() && entry.getName().equalsIgnoreCase(runtime.sourceName) &&
                    validRuntimeFile(layout, runtime, entry)) return entry;
        for (File entry : entries) if (entry.isDirectory() && !skipDirectory(entry)) {
            File match = findValidByName(entry, layout, runtime, depth + 1);
            if (match != null) return match;
        }
        return null;
    }

    private static File findFirmwareArchive(File root, int depth) {
        if (root == null || depth > MAX_SCAN_DEPTH || !root.isDirectory()) return null;
        File[] entries = sorted(root.listFiles());
        if (entries == null) return null;
        File best = null;
        for (File entry : entries) {
            if (!entry.isFile() || !entry.canRead()) continue;
            String name = entry.getName().toLowerCase(Locale.US);
            if (!name.startsWith("firmware") || !name.endsWith(".zip")) continue;
            if (!firmwareArchiveHasContent(entry)) continue;
            if (best == null || entry.length() > best.length()) best = entry;
        }
        if (best != null) return best;
        for (File entry : entries) if (entry.isDirectory() && !skipDirectory(entry)) {
            File match = findFirmwareArchive(entry, depth + 1);
            if (match != null && (best == null || match.length() > best.length()))
                best = match;
        }
        return best;
    }

    private static boolean firmwareArchiveHasContent(File archive) {
        if (!isReadableFile(archive)) return false;
        try {
            ZipFile zip = new ZipFile(archive);
            try {
                java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
                while (entries.hasMoreElements())
                    if (firmwareEntryName(entries.nextElement()) != null) return true;
            } finally { zip.close(); }
        } catch (Exception ignored) {}
        return false;
    }

    /**
     * The volume roots a given console's keys/firmware realistically live under,
     * in the layout's own order: the console-specific directories first, the
     * generic library roots last, so {@code Games/wiiu/Keys/keys.txt} beats a
     * stray {@code keys.txt} sitting elsewhere under {@code Games}.
     *
     * This deliberately mirrors Phase 2's BIOS search, so one documented shape
     * serves every engine and only the directory NAMES vary per console.
     */
    private static List<File> storageVolumes() {
        ArrayList<File> volumes = new ArrayList<>();
        volumes.add(Environment.getExternalStorageDirectory());
        File storage = new File("/storage");
        File[] children = storage.listFiles(File::isDirectory);
        if (children != null) for (File child : children) {
            String name = child.getName();
            if (!"emulated".equals(name) && !"self".equals(name) &&
                    child.canRead() && !volumes.contains(child)) volumes.add(child);
        }
        return volumes;
    }

    private static List<File> searchRoots(String[] directories, List<File> volumes) {
        ArrayList<File> result = new ArrayList<>();
        if (volumes == null) return result;
        for (File volume : volumes) {
            if (volume == null || !volume.isDirectory() || !volume.canRead()) continue;
            for (String relative : directories) addDirectory(result, volume, relative);
            // The documented console locations win, but a user-owned file in
            // Downloads, Documents, or a custom folder must still be found.
            addDirectory(result, volume, "");
        }
        return result;
    }

    /**
     * Resolves a relative path case-insensitively. External volumes are not
     * reliably case-folding, so "Games/switch" must also find "games/Switch".
     */
    private static void addDirectory(List<File> result, File volume, String relative) {
        if (relative == null || relative.isEmpty()) {
            if (volume.isDirectory() && volume.canRead() && !result.contains(volume))
                result.add(volume);
            return;
        }
        File current = volume;
        for (String segment : relative.split("/")) {
            File match = new File(current, segment);
            if (!match.isDirectory()) {
                match = null;
                File[] entries = sorted(current.listFiles());
                if (entries != null) for (File entry : entries)
                    if (entry.isDirectory() && entry.getName().equalsIgnoreCase(segment)) {
                        match = entry;
                        break;
                    }
            }
            if (match == null) return;
            current = match;
        }
        if (current.isDirectory() && !result.contains(current)) result.add(current);
    }

    private static boolean skipDirectory(File directory) {
        String name = directory.getName().toLowerCase(Locale.US);
        if (name.startsWith(".") || "cache".equals(name) || "caches".equals(name))
            return true;
        File parent = directory.getParentFile();
        return parent != null && "android".equalsIgnoreCase(parent.getName()) &&
                ("data".equals(name) || "obb".equals(name));
    }

    private static File[] sorted(File[] entries) {
        if (entries == null) return null;
        Arrays.sort(entries, (left, right) ->
                left.getName().compareToIgnoreCase(right.getName()));
        return entries;
    }

    private static boolean isReadableFile(File file) {
        return file != null && file.isFile() && file.length() > 0 && file.canRead();
    }

    private static void copyFile(File source, File destination) throws Exception {
        InputStream input = new java.io.FileInputStream(source);
        try {
            writeStream(input, destination);
        } finally { input.close(); }
    }

    private static void writeStream(InputStream input, File destination) throws Exception {
        List<InputStream> single = new ArrayList<>();
        single.add(input);
        writeAll(single, destination);
    }

    private static void writeFragments(ZipFile zip, List<ZipEntry> fragments,
                                       File destination) throws Exception {
        List<InputStream> streams = new ArrayList<>();
        try {
            for (ZipEntry fragment : fragments) streams.add(zip.getInputStream(fragment));
            writeAll(streams, destination);
        } finally {
            for (InputStream stream : streams)
                try { stream.close(); } catch (Exception ignored) {}
        }
    }

    /** Writes through a temporary file so an interrupted copy is never read back. */
    private static void writeAll(List<InputStream> inputs, File destination)
            throws Exception {
        File pending = new File(destination.getParentFile(),
                destination.getName() + ".pending");
        FileOutputStream output = new FileOutputStream(pending);
        try {
            byte[] buffer = new byte[256 * 1024];
            for (InputStream input : inputs) {
                int count;
                while ((count = input.read(buffer)) >= 0)
                    if (count > 0) output.write(buffer, 0, count);
            }
            output.flush();
            output.getFD().sync();
        } finally { output.close(); }
        if (destination.exists() && !destination.delete()) {
            pending.delete();
            throw new IllegalStateException("Cannot replace " + destination.getName());
        }
        if (!pending.renameTo(destination)) {
            pending.delete();
            throw new IllegalStateException("Cannot install " + destination.getName());
        }
    }

    private static String readAscii(File file) throws Exception {
        InputStream input = new java.io.FileInputStream(file);
        try {
            java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            return new String(output.toByteArray(), StandardCharsets.US_ASCII);
        } finally { input.close(); }
    }

    private static void writeAscii(File file, String value) throws Exception {
        FileOutputStream output = new FileOutputStream(file);
        try {
            output.write(value.getBytes(StandardCharsets.US_ASCII));
            output.flush();
            output.getFD().sync();
        } finally { output.close(); }
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US);
    }
}
