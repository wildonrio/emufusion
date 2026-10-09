package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Cemu cheats as graphic packs: {@code <root>/graphicPacks/EmuFusion_<id>/}
 * holding a {@code rules.txt} and a {@code patch_EmuFusion.asm}, plus the
 * {@code <GraphicPack><Entry filename=.../></GraphicPack>} list in
 * {@code <root>/settings.xml} that Cemu consults to activate a pack.
 *
 * <p>Only {@code EmuFusion_*} directories and {@code Entry} elements whose
 * filename starts with {@code graphicPacks/EmuFusion_} are ever created,
 * replaced or removed; the rest of settings.xml is copied through byte for
 * byte. The rules also set {@code default = true}, which activates the pack
 * even before Cemu has written its first settings.xml.
 *
 * <p>A patch group needs a {@code moduleMatches} CRC or Cemu rejects it, so
 * a row must either carry its own {@code [group]} header lines or the game
 * identity must supply {@code moduleMatches}; otherwise the row is skipped.
 */
public final class CemuGraphicPackWriter implements BootCheatWriter {
    static final String PREFIX = "EmuFusion_";
    static final String PATCH_FILE = "patch_EmuFusion.asm";
    private static final Pattern ENTRY = Pattern.compile(
            "[ \\t]*<Entry\\s+filename=\"graphicPacks/EmuFusion_[^\"]*\"[^>]*?(?:/>|>.*?</Entry>)[ \\t]*\\r?\\n?",
            Pattern.DOTALL);
    private static final Pattern GRAPHIC_PACK = Pattern.compile(
            "(<GraphicPack\\b[^>]*>)(.*?)(</GraphicPack>)", Pattern.DOTALL);
    private static final Pattern MODULE_CRC = Pattern.compile("^(?:0[xX])?([0-9A-Fa-f]{8})$");

    /** The downloader's separator between a pack's files inside one code. */
    static final String FILE_MARKER = "#### file: ";
    private static final int MAX_PACK_FILES = 32;

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        List<String> titleIds = titleIds(request);
        File packs = new File(request.engineRoot, "graphicPacks");
        Map<String, Map<String, String>> wanted = new LinkedHashMap<>();
        for (DeliveryCheat row : request.enabled()) {
            Map<String, String> files = packFiles(row, titleIds, request);
            if (files == null) continue;
            wanted.put(packId(row), files);
        }
        File[] existing = packs.listFiles();
        if (existing != null) {
            for (File directory : existing) {
                if (!directory.isDirectory() || !directory.getName().startsWith(PREFIX)) continue;
                if (wanted.containsKey(directory.getName())) continue;
                if (removePack(directory)) touched.add(directory);
            }
        }
        for (Map.Entry<String, Map<String, String>> pack : wanted.entrySet()) {
            File directory = new File(packs, pack.getKey());
            if (!OwnedFiles.inside(request.engineRoot, directory)) continue;
            // Files EmuFusion wrote for this pack earlier that the row no longer carries.
            File[] stale = directory.listFiles();
            if (stale != null)
                for (File file : stale)
                    if (file.isFile() && !file.getName().startsWith(".EmuFusion-")
                            && !pack.getValue().containsKey(file.getName())
                            && OwnedFiles.remove(file, OwnedFiles.Ownership.CREATED))
                        touched.add(file);
            for (Map.Entry<String, String> file : pack.getValue().entrySet()) {
                File target = new File(directory, file.getKey());
                if (OwnedFiles.write(target, file.getValue(), OwnedFiles.Ownership.CREATED)) touched.add(target);
            }
        }
        File settings = new File(request.engineRoot, "settings.xml");
        if (updateSettings(settings, new ArrayList<>(wanted.keySet()))) touched.add(settings);
        return touched;
    }

    static List<String> titleIds(BootCheatRequest request) {
        List<String> ids = new ArrayList<>();
        for (String key : new String[] {"titleIds", "titleId"})
            for (String raw : CheatCodeText.csv(request.identity(key))) {
                String id = CheatCodeText.titleId16(raw);
                if (!id.isEmpty() && !ids.contains(id)) ids.add(id);
            }
        if (ids.isEmpty()) {
            String fromStem = CheatCodeText.titleId16(request.contentStem);
            if (!fromStem.isEmpty()) ids.add(fromStem);
        }
        return ids;
    }

    static String packId(DeliveryCheat row) {
        StringBuilder out = new StringBuilder(PREFIX);
        for (char ch : row.cheat.id.toCharArray()) {
            if (out.length() >= 80) break;
            out.append(Character.isLetterOrDigit(ch) ? ch : '_');
        }
        return out.toString();
    }

    /**
     * The pack directory's files. A downloaded pack (code carrying
     * {@code #### file:} separators) is laid down verbatim, rules.txt
     * included, because its own [Definition] already names the title ids;
     * a bare code is wrapped in a synthesized rules.txt and patch file.
     * Null when the row cannot become a valid pack.
     */
    static Map<String, String> packFiles(DeliveryCheat row, List<String> titleIds,
                                         BootCheatRequest request) {
        Map<String, String> files = new LinkedHashMap<>();
        if (row.cheat.code.contains(FILE_MARKER)) {
            String name = null;
            StringBuilder body = new StringBuilder();
            for (String line : row.cheat.code.split("\\r?\\n")) {
                if (line.startsWith(FILE_MARKER)) {
                    if (name != null) files.put(name, body.toString().trim() + "\n");
                    name = safePackFileName(line.substring(FILE_MARKER.length()).trim());
                    if (name == null || files.size() >= MAX_PACK_FILES) return null;
                    body.setLength(0);
                    continue;
                }
                if (name != null) body.append(line).append('\n');
            }
            if (name != null) files.put(name, body.toString().trim() + "\n");
            String rules = files.get("rules.txt");
            if (rules == null || !rules.toLowerCase(Locale.US).contains("[definition]")) return null;
            boolean hasPatch = false;
            for (String file : files.keySet())
                if (file.equals("patches.txt") || (file.startsWith("patch_") && file.endsWith(".asm")))
                    hasPatch = true;
            if (!hasPatch) return null;
            return files;
        }
        if (titleIds.isEmpty()) return null;
        String patch = patchText(row, request);
        if (patch == null) return null;
        files.put("rules.txt", rules(row, titleIds, request));
        files.put(PATCH_FILE, patch);
        return files;
    }

    /** rules.txt, patches.txt, patch_*.asm or a plain text/shader file name; null otherwise. */
    static String safePackFileName(String name) {
        if (name == null || name.isEmpty() || name.length() > 80) return null;
        if (name.contains("/") || name.contains("\\") || name.startsWith(".")) return null;
        if (!name.matches("[A-Za-z0-9._ -]+")) return null;
        String lower = name.toLowerCase(Locale.US);
        if (lower.equals("rules.txt") || lower.equals("patches.txt")) return name;
        if (lower.startsWith("patch_") && lower.endsWith(".asm")) return name;
        if (lower.endsWith(".txt") || lower.endsWith(".asm")) return name;
        return null;
    }

    static String rules(DeliveryCheat row, List<String> titleIds, BootCheatRequest request) {
        String name = CheatCodeText.singleLine(row.cheat.name, 96).replace("\"", "'");
        String game = CheatCodeText.singleLine(
                request.gameTitle.isEmpty() ? "Wii U" : request.gameTitle, 96).replace("\"", "'").replace("/", "-");
        StringBuilder ids = new StringBuilder();
        for (String id : titleIds) {
            if (ids.length() > 0) ids.append(',');
            ids.append(id);
        }
        StringBuilder out = new StringBuilder();
        out.append("[Definition]\n");
        out.append("titleIds = ").append(ids).append('\n');
        out.append("name = ").append(name).append('\n');
        out.append("path = \"EmuFusion/").append(game).append("/Cheats/").append(name.replace("/", "-")).append("\"\n");
        String description = CheatCodeText.singleLine(row.cheat.description, 300);
        out.append("description = ").append(description.isEmpty() ? "Written by EmuFusion cheat delivery." : description)
                .append('\n');
        out.append("version = 6\n");
        out.append("default = true\n");
        return out.toString();
    }

    /** The patch file body, or null when the row cannot name a module. */
    static String patchText(DeliveryCheat row, BootCheatRequest request) {
        List<String> lines = CheatCodeText.lines(row.cheat.code);
        if (lines.isEmpty()) return null;
        boolean hasHeader = false;
        boolean hasModule = false;
        for (String line : lines) {
            String trimmed = line.trim();
            if (trimmed.startsWith("[") && trimmed.endsWith("]")) hasHeader = true;
            if (trimmed.toLowerCase(Locale.US).startsWith("modulematches")) hasModule = true;
        }
        StringBuilder out = new StringBuilder();
        if (!hasHeader || !hasModule) {
            if (hasHeader && !hasModule) return null;
            List<String> crcs = new ArrayList<>();
            List<String> sources = CheatCodeText.csv(CheatCodeText.tagValue(row, "moduleMatches"));
            if (sources.isEmpty()) sources = CheatCodeText.csv(request.identity("moduleMatches"));
            for (String raw : sources) {
                Matcher matcher = MODULE_CRC.matcher(raw);
                if (matcher.matches()) crcs.add("0x" + matcher.group(1).toUpperCase(Locale.US));
            }
            if (crcs.isEmpty()) return null;
            out.append("[EmuFusion]\n");
            out.append("moduleMatches = ");
            for (int i = 0; i < crcs.size(); i++) out.append(i == 0 ? "" : ", ").append(crcs.get(i));
            out.append('\n');
        }
        for (String line : lines) out.append(line).append('\n');
        return out.toString();
    }

    private static boolean removePack(File directory) {
        boolean removed = false;
        File[] files = directory.listFiles();
        if (files != null) {
            for (File file : files) {
                if (!file.isFile()) continue;
                String name = file.getName();
                if (safePackFileName(name) != null || name.equals(PATCH_FILE)
                        || name.startsWith(".EmuFusion-") || name.endsWith(".part"))
                    removed |= file.delete();
            }
        }
        return directory.delete() || removed;
    }

    /** Rewrites only the EmuFusion entries of Cemu's settings.xml. */
    static boolean updateSettings(File settings, List<String> packIds) throws IOException {
        String existing = settings.isFile() ? OwnedFiles.readText(settings, OwnedFiles.MAX_BYTES) : "";
        StringBuilder entries = new StringBuilder();
        for (String id : packIds)
            entries.append("\t\t<Entry filename=\"graphicPacks/").append(id).append("/rules.txt\"/>\n");
        String updated;
        if (existing.isEmpty()) {
            if (packIds.isEmpty()) return false;
            updated = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<content>\n\t<GraphicPack>\n"
                    + entries + "\t</GraphicPack>\n</content>\n";
        } else {
            String stripped = ENTRY.matcher(existing).replaceAll("");
            Matcher section = GRAPHIC_PACK.matcher(stripped);
            if (section.find()) {
                // Foreign entries are copied line for line; only whitespace-only
                // lines (what removing an EmuFusion entry leaves behind) are dropped.
                StringBuilder inner = new StringBuilder("\n");
                for (String line : section.group(2).split("\r?\n"))
                    if (!line.trim().isEmpty()) inner.append(line).append('\n');
                updated = stripped.substring(0, section.start())
                        + section.group(1) + inner + entries + "\t" + section.group(3)
                        + stripped.substring(section.end());
            } else if (packIds.isEmpty()) {
                updated = stripped;
            } else {
                int close = stripped.lastIndexOf("</content>");
                if (close < 0) return false;
                updated = stripped.substring(0, close) + "\t<GraphicPack>\n" + entries
                        + "\t</GraphicPack>\n" + stripped.substring(close);
            }
        }
        if (updated.equals(existing)) return false;
        byte[] bytes = updated.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        if (bytes.length > OwnedFiles.MAX_BYTES) throw new IOException("settings.xml too large");
        File part = new File(settings.getPath() + ".part");
        File parent = settings.getParentFile();
        if (parent != null && !parent.isDirectory()) parent.mkdirs();
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(part)) {
            out.write(bytes);
            out.flush();
            out.getFD().sync();
        }
        if (settings.exists() && !settings.delete()) { part.delete(); throw new IOException("cannot replace " + settings); }
        if (!part.renameTo(settings)) { part.delete(); throw new IOException("cannot rename " + part); }
        return true;
    }
}
