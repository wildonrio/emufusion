package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Eden's per-build cheat files:
 * {@code <root>/load/<TITLEID>/EmuFusionCheats/cheats/<BUILDID>.txt}.
 *
 * <p>Eden reads every {@code <mod>/cheats/<build id>.txt} under the title's
 * load directory (file_sys/patch_manager.cpp), trying the upper-case build
 * id first and the lower-case one second; only the upper-case file is
 * written so no code is loaded twice. Every entry in a file is enabled by
 * the parser, so the file holds exactly the enabled rows, and the whole
 * {@code EmuFusionCheats} mod directory is EmuFusion's to create and remove.
 */
public final class EdenCheatWriter implements BootCheatWriter {
    static final String MOD_DIRECTORY = "EmuFusionCheats";

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        String titleId = titleId(request);
        List<String> buildIds = buildIds(request);
        if (titleId.isEmpty() || buildIds.isEmpty()) return touched;
        File directory = new File(request.engineRoot,
                "load/" + titleId + "/" + MOD_DIRECTORY + "/cheats");
        if (!OwnedFiles.inside(request.engineRoot, directory)) return touched;
        Map<String, String> texts = new LinkedHashMap<>();
        for (String buildId : buildIds) {
            String text = render(request, buildId);
            if (text != null) texts.put(buildId + ".txt", text);
        }
        Set<String> targets = texts.keySet();
        File[] existing = directory.listFiles();
        if (existing != null) {
            for (File file : existing) {
                if (targets.contains(file.getName())) continue;
                if (file.isFile() && file.getName().endsWith(".txt")
                        && OwnedFiles.remove(file, OwnedFiles.Ownership.CREATED))
                    touched.add(file);
            }
        }
        for (Map.Entry<String, String> target : texts.entrySet()) {
            File file = new File(directory, target.getKey());
            if (OwnedFiles.write(file, target.getValue(), OwnedFiles.Ownership.CREATED)) touched.add(file);
        }
        if (texts.isEmpty()) {
            // Leave no empty mod behind: Eden lists every load sub-directory.
            File[] remaining = directory.listFiles();
            if (remaining != null && remaining.length == 0 && directory.delete())
                directory.getParentFile().delete();
        }
        return touched;
    }

    static String titleId(BootCheatRequest request) {
        String id = CheatCodeText.titleId16(request.identity("titleId"));
        return id.isEmpty() ? CheatCodeText.titleId16(request.contentStem) : id;
    }

    /** Upper-case 16-hex build ids; a longer id is truncated the way Eden does it. */
    static List<String> buildIds(BootCheatRequest request) {
        List<String> ids = new ArrayList<>();
        for (String raw : CheatCodeText.csv(request.identity("buildIds"))) {
            String value = raw.toUpperCase(Locale.US);
            if (value.startsWith("0X")) value = value.substring(2);
            if (value.length() > 16) value = value.substring(0, 16);
            if (value.matches("[0-9A-F]{16}") && !ids.contains(value)) ids.add(value);
        }
        return ids;
    }

    /**
     * The file for one build id: rows the downloader tagged with a
     * {@code buildid:} land only in their own build's file, untagged rows in
     * every file. Null when nothing applies to the build.
     */
    static String render(BootCheatRequest request, String buildId) {
        StringBuilder out = new StringBuilder();
        Set<String> used = new HashSet<>();
        int written = 0;
        for (DeliveryCheat row : request.enabled()) {
            if (!appliesTo(row, buildId)) continue;
            List<String> body = body(row);
            if (body == null) continue;
            String name = CheatCodeText.uniqueName(CheatCodeText.safeName(row.cheat.name, 96), used);
            out.append('[').append(name).append("]\n");
            for (String line : body) out.append(line).append('\n');
            out.append('\n');
            written++;
        }
        return written == 0 ? null : out.toString();
    }

    static boolean appliesTo(DeliveryCheat row, String buildId) {
        boolean tagged = false;
        for (String tag : row.tags) {
            if (!tag.startsWith("buildid:") && !tag.startsWith("buildid=")) continue;
            tagged = true;
            String value = tag.substring(8).trim().toUpperCase(Locale.US);
            if (value.startsWith("0X")) value = value.substring(2);
            if (value.length() > 16) value = value.substring(0, 16);
            if (value.equals(buildId)) return true;
        }
        return !tagged;
    }

    /** Lines of 8-hex opcode words, or null when any token is not one. */
    static List<String> body(DeliveryCheat row) {
        List<String> body = new ArrayList<>();
        for (String line : CheatCodeText.lines(row.cheat.code)) {
            List<String> words = CheatCodeText.hexWords(line);
            if (words == null) return null;
            StringBuilder joined = new StringBuilder();
            for (String word : words) {
                if (joined.length() > 0) joined.append(' ');
                joined.append(word);
            }
            body.add(joined.toString());
        }
        return body.isEmpty() ? null : body;
    }
}
