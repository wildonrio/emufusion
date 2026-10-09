package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * RPCS3 {@code patch.yml} / {@code imported_patch.yml} (format 1.2).
 *
 * <p>Patch names sit directly under the hash key (see the vendored aPS3e
 * {@code rpcs3/Utilities/bin_patch.cpp}, {@code load()}: it iterates
 * {@code pair.second} — the hash's value — as the map of patch entries;
 * there is no intermediate {@code Patches:} map):
 *
 * <pre>
 * PPU-&lt;sha1&gt;:
 *   "Name":
 *     Games:
 *       "Title":
 *         SERIAL: [ 01.00, All ]
 *     Author: ..
 *     Notes: ..
 *     Group: ..
 *     Patch:
 *       - [ be32, 0x..., 0x... ]
 * </pre>
 *
 * Each patch becomes one switch whose code is the patch re-emitted as YAML
 * under its name, and whose tags carry {@code ppu:<hash>},
 * {@code serial:<SERIAL>} and {@code version:<v>} so a boot writer can
 * rebuild an {@code imported_patch.yml} entry and a {@code patch_config.yml}
 * line without re-parsing anything.
 */
public final class Rpcs3PatchYamlParser {
    private static final Pattern SERIAL = Pattern.compile("(?i)^[A-Z]{4}[0-9]{5}$");

    public static final class Patch {
        public final String hash;
        public final String name;
        public final String author;
        public final String notes;
        public final String group;
        public final Map<String, List<String>> serials = new LinkedHashMap<>();
        public final String yaml;
        Patch(String hash, String name, String author, String notes, String group, String yaml) {
            this.hash = hash; this.name = name; this.author = author; this.notes = notes;
            this.group = group; this.yaml = yaml;
        }
    }

    private Rpcs3PatchYamlParser() {}

    /** Every patch that names the serial (case-insensitive). */
    public static List<Patch> forSerial(String text, String serial) {
        List<Patch> result = new ArrayList<>();
        String wanted = normaliseSerial(serial);
        if (wanted.isEmpty()) return result;
        for (Patch patch : parse(text))
            if (patch.serials.containsKey(wanted)) result.add(patch);
        return result;
    }

    @SuppressWarnings("unchecked")
    public static List<Patch> parse(String text) {
        List<Patch> result = new ArrayList<>();
        Object root = MiniYaml.parse(text);
        if (!(root instanceof Map)) return result;
        for (Map.Entry<String, Object> entry : ((Map<String, Object>) root).entrySet()) {
            String hash = entry.getKey();
            if (!hash.toUpperCase(Locale.US).startsWith("PPU-") || !(entry.getValue() instanceof Map)) continue;
            Map<String, Object> block = (Map<String, Object>) entry.getValue();
            for (Map.Entry<String, Object> patchEntry : block.entrySet()) {
                if (!(patchEntry.getValue() instanceof Map)) continue;
                Map<String, Object> body = (Map<String, Object>) patchEntry.getValue();
                if (!(body.get("Patch") instanceof List) || ((List<?>) body.get("Patch")).isEmpty()) continue;
                Map<String, List<String>> serials = new LinkedHashMap<>();
                Object games = body.get("Games");
                if (games instanceof Map)
                    for (Object title : ((Map<String, Object>) games).values())
                        if (title instanceof Map) collectSerials((Map<String, Object>) title, serials);
                Map<String, Object> single = new LinkedHashMap<>();
                single.put(patchEntry.getKey(), body);
                Object group = body.containsKey("Group") ? body.get("Group") : body.get("Patch Group");
                Patch patch = new Patch(hash, patchEntry.getKey(),
                        JsonLite.string(body.get("Author")), JsonLite.string(body.get("Notes")),
                        JsonLite.string(group), MiniYaml.write(single).trim());
                patch.serials.putAll(serials);
                result.add(patch);
                if (result.size() >= CodeText.MAX_CHEATS_PER_GAME) return result;
            }
        }
        return result;
    }

    private static void collectSerials(Map<String, Object> map, Map<String, List<String>> into) {
        for (Map.Entry<String, Object> entry : map.entrySet()) {
            String serial = normaliseSerial(entry.getKey());
            if (serial.isEmpty()) continue;
            List<String> versions = into.get(serial);
            if (versions == null) { versions = new ArrayList<>(); into.put(serial, versions); }
            for (Object version : JsonLite.array(entry.getValue())) {
                String value = JsonLite.string(version).trim();
                if (!value.isEmpty() && !versions.contains(value)) versions.add(value);
            }
        }
    }

    public static String normaliseSerial(String value) {
        if (value == null) return "";
        String clean = value.trim().toUpperCase(Locale.US).replace("-", "").replace("_", "");
        return SERIAL.matcher(clean).matches() ? clean : "";
    }

    public static ParsedCheat toParsed(Patch patch, String serial) {
        List<String> tags = ParsedCheat.impliedTags(patch.name, patch.group);
        tags.add("ppu:" + patch.hash);
        String wanted = normaliseSerial(serial);
        if (!wanted.isEmpty()) {
            tags.add("serial:" + wanted);
            List<String> versions = patch.serials.get(wanted);
            if (versions != null) for (String version : versions) tags.add("version:" + version);
        }
        if (!patch.group.isEmpty()) tags.add(ParsedCheat.groupTag(patch.group));
        String description = patch.notes;
        if (!patch.author.isEmpty()) description = description.isEmpty() ? "by " + patch.author
                : description + " (by " + patch.author + ")";
        return new ParsedCheat(patch.name, description, patch.yaml, tags);
    }
}
