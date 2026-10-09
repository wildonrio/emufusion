package com.thorium.preview.cheats.delivery;

import com.thorium.preview.cheats.sources.MiniYaml;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * RPCS3 (aPS3e) patches: {@code <root>/config/patches/imported_patch.yml}
 * carrying every enabled row and {@code <root>/config/patch_config.yml}
 * switching those entries on for the game's serial.
 *
 * <p>RPCS3 keys a patch by the executable hash it targets, so every row
 * must say which: the downloader's {@code ppu:<hash>} tag, a {@code hash=}
 * tag, the first code segment ({@code PPU-<sha1>}), or the game's
 * {@code ppuHash} identity. The code is either the patch re-emitted as YAML
 * (the downloader's form: the {@code - [ type, address, value ]} entries
 * under {@code Patch:} are taken) or those entries joined with '+'. The
 * output YAML is emitted with quoted scalars so a title or name cannot
 * change its structure.
 *
 * <p>{@code patch_config.yml} is aPS3e/RPCS3's own file: it rewrites it
 * whenever the owner toggles a patch in its own manager, for hashes that
 * have nothing to do with EmuFusion. Regenerating the whole file from just
 * this launch's rows would erase that unrelated state the moment any game
 * with EmuFusion-delivered cheats next launches, so every top-level hash key
 * this writer does not itself own is read back with {@link MiniYaml} and
 * carried over verbatim.
 */
public final class Aps3ePatchWriter implements BootCheatWriter {
    private static final Pattern HASH_KEY = Pattern.compile(
            "^(?:[A-Z0-9]{9}-)?(?:PPU|SPU|OVL|PRX)-[0-9A-Fa-f]{40}$");
    private static final Pattern PATCH_TYPE = Pattern.compile("^[a-z][a-z0-9_]{1,15}$");
    private static final Pattern PATCH_VALUE = Pattern.compile(
            "^(?:0[xX][0-9A-Fa-f]{1,16}|-?[0-9]+(?:\\.[0-9]+)?|\"[^\"\\\\]{0,200}\")$");
    private static final Pattern SERIAL = Pattern.compile("^[A-Z0-9]{9}$");
    private static final Pattern APP_VERSION = Pattern.compile("^[0-9]{2}\\.[0-9]{2}$");

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        String serial = serial(request);
        if (serial.isEmpty()) return touched;
        File patches = new File(request.engineRoot, "config/patches/imported_patch.yml");
        File config = new File(request.engineRoot, "config/patch_config.yml");
        Map<String, List<Entry>> byHash = entries(request);
        // Every hash this game's catalogue could ever target, not only the
        // hashes with something enabled right now: turning everything off
        // must still clear this game's own (now-empty) entry rather than
        // mistake it for a foreign one just because nothing survived the
        // enabled filter this launch.
        Map<String, Object> foreign = foreignConfigEntries(config, possibleHashes(request));
        if (byHash.isEmpty()) {
            if (OwnedFiles.remove(patches, OwnedFiles.Ownership.EXACT)) touched.add(patches);
            if (foreign.isEmpty()) {
                if (OwnedFiles.remove(config, OwnedFiles.Ownership.CREATED)) touched.add(config);
            } else if (OwnedFiles.write(config,
                    renderConfig(Collections.<String, List<Entry>>emptyMap(), "", "", "", foreign),
                    OwnedFiles.Ownership.CREATED)) {
                touched.add(config);
            }
            return touched;
        }
        String title = yaml(request.gameTitle.isEmpty() ? "EmuFusion" : request.gameTitle);
        String appVersion = appVersion(request);
        if (OwnedFiles.write(patches, renderPatches(byHash, title, serial, appVersion),
                OwnedFiles.Ownership.EXACT))
            touched.add(patches);
        if (OwnedFiles.write(config, renderConfig(byHash, title, serial, appVersion, foreign),
                OwnedFiles.Ownership.CREATED))
            touched.add(config);
        return touched;
    }

    /**
     * The config file's existing top-level hash entries that {@code ownHashes}
     * does not claim -- another game's patches, or a patch on the same
     * hash this writer never produced. Unreadable or unparsable content is
     * treated as none, never guessed at or reformatted.
     */
    static Map<String, Object> foreignConfigEntries(File config, Set<String> ownHashes) {
        Map<String, Object> foreign = new LinkedHashMap<>();
        try {
            String text = OwnedFiles.readText(config, OwnedFiles.MAX_BYTES);
            if (text.trim().isEmpty()) return foreign;
            Object parsed = MiniYaml.parse(text);
            if (!(parsed instanceof Map)) return foreign;
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) parsed).entrySet()) {
                String key = String.valueOf(entry.getKey());
                if (!ownHashes.contains(key)) foreign.put(key, entry.getValue());
            }
        } catch (IOException | RuntimeException unreadable) {
            return new LinkedHashMap<>();
        }
        return foreign;
    }

    static final class Entry {
        final String name;
        final String author;
        final String notes;
        final List<String> lines;
        Entry(String name, String author, String notes, List<String> lines) {
            this.name = name; this.author = author; this.notes = notes; this.lines = lines;
        }
    }

    static String serial(BootCheatRequest request) {
        String serial = request.identity("serial").toUpperCase(Locale.US).replace("-", "").trim();
        if (SERIAL.matcher(serial).matches()) return serial;
        Matcher inStem = Pattern.compile("([A-Z]{4}[0-9]{5})")
                .matcher(request.contentStem.toUpperCase(Locale.US).replace("-", ""));
        return inStem.find() ? inStem.group(1) : "";
    }

    static String appVersion(BootCheatRequest request) {
        String version = request.identity("appVersion").trim();
        return APP_VERSION.matcher(version).matches() ? version : "All";
    }

    /**
     * Every hash the game's full catalogue (not just the enabled rows) could
     * resolve to -- what makes an entry "ours" for merge purposes even on a
     * launch where the owner has turned every one of this game's rows off.
     */
    static Set<String> possibleHashes(BootCheatRequest request) {
        Set<String> hashes = new java.util.LinkedHashSet<>();
        String fallbackHash = canonicalHash(request.identity("ppuHash"));
        for (DeliveryCheat row : request.cheats) {
            List<String> segments = patchSegments(row.cheat.code);
            if (segments.isEmpty()) continue;
            String hash = canonicalHash(CheatCodeText.tagValue(row, "ppu"));
            if (hash.isEmpty()) hash = canonicalHash(CheatCodeText.tagValue(row, "hash"));
            if (hash.isEmpty()) {
                String leading = canonicalHash(segments.get(0));
                if (HASH_KEY.matcher(leading).matches()) hash = leading;
            }
            if (hash.isEmpty()) hash = fallbackHash;
            if (HASH_KEY.matcher(hash).matches()) hashes.add(hash);
        }
        return hashes;
    }

    static Map<String, List<Entry>> entries(BootCheatRequest request) {
        Map<String, List<Entry>> byHash = new LinkedHashMap<>();
        Set<String> used = new HashSet<>();
        String fallbackHash = request.identity("ppuHash");
        for (DeliveryCheat row : request.enabled()) {
            List<String> segments = patchSegments(row.cheat.code);
            if (segments.isEmpty()) continue;
            String hash = canonicalHash(CheatCodeText.tagValue(row, "ppu"));
            if (hash.isEmpty()) hash = canonicalHash(CheatCodeText.tagValue(row, "hash"));
            String leading = canonicalHash(segments.get(0));
            if (HASH_KEY.matcher(leading).matches()) {
                segments.remove(0);
                if (hash.isEmpty()) hash = leading;
            }
            if (hash.isEmpty()) hash = canonicalHash(fallbackHash);
            if (!HASH_KEY.matcher(hash).matches()) continue;
            List<String> lines = new ArrayList<>();
            boolean valid = !segments.isEmpty();
            for (String segment : segments) {
                String line = patchLine(segment);
                if (line == null) { valid = false; break; }
                lines.add(line);
            }
            if (!valid) continue;
            String name = CheatCodeText.uniqueName(CheatCodeText.safeName(row.cheat.name, 96), used);
            List<Entry> list = byHash.get(hash);
            if (list == null) byHash.put(hash, list = new ArrayList<>());
            list.add(new Entry(name, row.source.isEmpty() ? "EmuFusion" : row.source,
                    CheatCodeText.singleLine(row.cheat.description, 200), lines));
        }
        return byHash;
    }

    /**
     * "PPU-<sha1>" with the prefix upper case and the digest lower case, the
     * way RPCS3 spells its keys; tags arrive lower-cased, so the prefix is
     * repaired and a bare digest gets the PPU prefix.
     */
    static String canonicalHash(String value) {
        String text = value == null ? "" : value.trim();
        if (text.isEmpty()) return "";
        if (text.matches("[0-9A-Fa-f]{40}")) return "PPU-" + text.toLowerCase(Locale.US);
        int dash = text.lastIndexOf('-');
        if (dash < 0) return text;
        return text.substring(0, dash).toUpperCase(Locale.US) + "-" + text.substring(dash + 1).toLowerCase(Locale.US);
    }

    /**
     * The patch entries of a code: for the downloader's YAML form, the
     * sequence items under {@code Patch:}; otherwise every '+'-joined segment.
     */
    static List<String> patchSegments(String code) {
        List<String> lines = CheatCodeText.lines(code);
        List<String> entries = new ArrayList<>();
        boolean yaml = false;
        boolean inPatch = false;
        for (String line : lines) {
            String trimmed = line.trim();
            if (trimmed.matches("(?i)^Patch\\s*:\\s*$")) { yaml = true; inPatch = true; continue; }
            if (inPatch) {
                if (trimmed.startsWith("-")) { entries.add(trimmed); continue; }
                inPatch = false;
            }
        }
        return yaml ? entries : lines;
    }

    /** "[ be32, 0x00123456, 0x00000001 ]" from any of the spellings a source uses, or null. */
    static String patchLine(String segment) {
        String text = segment.trim();
        if (text.startsWith("-")) text = text.substring(1).trim();
        if (text.startsWith("[") && text.endsWith("]")) text = text.substring(1, text.length() - 1);
        List<String> tokens = new ArrayList<>();
        for (String token : text.trim().split("[\\s,]+")) if (!token.isEmpty()) tokens.add(token);
        if (tokens.size() < 2 || tokens.size() > 4) return null;
        String type = tokens.get(0).toLowerCase(Locale.US);
        if (!PATCH_TYPE.matcher(type).matches()) return null;
        StringBuilder out = new StringBuilder("[ ").append(type);
        for (int i = 1; i < tokens.size(); i++) {
            if (!PATCH_VALUE.matcher(tokens.get(i)).matches()) return null;
            out.append(", ").append(tokens.get(i));
        }
        return out.append(" ]").toString();
    }

    static String renderPatches(Map<String, List<Entry>> byHash, String title, String serial,
                                String appVersion) {
        StringBuilder out = new StringBuilder();
        out.append("# Written by EmuFusion cheat delivery. Regenerated before every launch; ")
                .append("change the selection in EmuFusion.\n");
        out.append("Version: 1.2\n\n");
        for (Map.Entry<String, List<Entry>> hash : byHash.entrySet()) {
            out.append(hash.getKey()).append(":\n");
            for (Entry entry : hash.getValue()) {
                out.append("  ").append(yaml(entry.name)).append(":\n");
                out.append("    Games:\n");
                out.append("      ").append(title).append(":\n");
                out.append("        ").append(serial).append(": [ ").append(yaml(appVersion)).append(" ]\n");
                out.append("    Author: ").append(yaml(entry.author)).append('\n');
                if (!entry.notes.isEmpty()) out.append("    Notes: ").append(yaml(entry.notes)).append('\n');
                out.append("    Patch Version: \"1.0\"\n");
                out.append("    Patch:\n");
                for (String line : entry.lines) out.append("      - ").append(line).append('\n');
            }
        }
        return out.toString();
    }

    static String renderConfig(Map<String, List<Entry>> byHash, String title, String serial,
                               String appVersion, Map<String, Object> foreign) {
        StringBuilder out = new StringBuilder();
        out.append("# Written by EmuFusion cheat delivery.\n");
        for (Map.Entry<String, List<Entry>> hash : byHash.entrySet()) {
            out.append(hash.getKey()).append(":\n");
            for (Entry entry : hash.getValue()) {
                out.append("  ").append(yaml(entry.name)).append(":\n");
                out.append("    ").append(title).append(":\n");
                out.append("      ").append(serial).append(":\n");
                out.append("        ").append(yaml(appVersion)).append(":\n");
                out.append("          Enabled: true\n");
            }
        }
        if (foreign != null && !foreign.isEmpty()) {
            out.append("# Preserved: hashes this device's own aPS3e/RPCS3 patch manager wrote.\n");
            for (Map.Entry<String, Object> entry : foreign.entrySet())
                out.append(MiniYaml.write(Collections.singletonMap(entry.getKey(), entry.getValue())));
        }
        return out.toString();
    }

    /** A double-quoted YAML scalar. */
    static String yaml(String value) {
        StringBuilder out = new StringBuilder("\"");
        for (char ch : (value == null ? "" : value).toCharArray()) {
            if (ch == '"' || ch == '\\') out.append('\\').append(ch);
            else if (ch < 0x20) out.append(' ');
            else out.append(ch);
        }
        return out.append('"').toString();
    }
}
