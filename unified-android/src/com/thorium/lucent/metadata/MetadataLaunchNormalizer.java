package com.thorium.lucent.metadata;

import java.util.ArrayList;
import java.util.List;

/** Pure metadata transformation shared by Android migration and host tests. */
public final class MetadataLaunchNormalizer {
    public interface Resolver {
        String commandForSystem(String systemId);
    }

    private MetadataLaunchNormalizer() {}

    /**
     * Replaces, removes, or restores the one authoritative collection route.
     * Aggregate files are handled one collection at a time. Stale per-game
     * launch overrides are removed so an old standalone-emulator recipe cannot
     * bypass the current per-system route for individual titles.
     */
    public static String rewrite(String text, Resolver resolver) {
        if (text == null || text.isEmpty() || resolver == null) return text;
        String[] lines = text.split("\\n", -1);
        ArrayList<String> output = new ArrayList<>(lines.length + 4);
        int cursor = 0;
        while (cursor < lines.length) {
            if (!lines[cursor].startsWith("collection:")) {
                output.add(lines[cursor++]);
                continue;
            }
            int end = cursor + 1;
            while (end < lines.length && !lines[end].startsWith("collection:")) end++;
            rewriteCollection(lines, cursor, end, resolver, output);
            cursor = end;
        }
        return join(output);
    }

    private static void rewriteCollection(String[] lines, int start, int end,
            Resolver resolver, List<String> output) {
        int headerEnd = end;
        int shortnameIndex = -1;
        int firstLaunchIndex = -1;
        String system = "";
        for (int index = start; index < end; index++) {
            if (lines[index].startsWith("game:")) {
                headerEnd = index;
                break;
            }
            if (lines[index].startsWith("shortname:")) {
                shortnameIndex = index;
                system = lines[index].substring("shortname:".length()).trim()
                        .toLowerCase(java.util.Locale.US);
            } else if (index < headerEnd && lines[index].startsWith("launch:") &&
                    firstLaunchIndex < 0) {
                firstLaunchIndex = index;
            }
        }
        String command = resolver.commandForSystem(system);
        String desired = command == null || command.trim().isEmpty() ? "" :
                "launch: " + command.trim();
        boolean wroteLaunch = false;
        for (int index = start; index < end; index++) {
            boolean launch = lines[index].startsWith("launch:");
            if (launch) {
                boolean collectionLaunch = index < headerEnd;
                if (!desired.isEmpty() && !wroteLaunch) {
                    // Preserve the collection-level position when it exists.
                    // Per-game routes are only removed; they never become the
                    // authority for the collection.
                    if (collectionLaunch) {
                        output.add(desired);
                        wroteLaunch = true;
                    }
                }
                continue;
            }
            output.add(lines[index]);
            if (index == shortnameIndex && firstLaunchIndex < 0 && !desired.isEmpty()) {
                output.add(desired);
                wroteLaunch = true;
            }
        }
    }

    private static String join(List<String> lines) {
        StringBuilder result = new StringBuilder();
        for (int index = 0; index < lines.size(); index++) {
            if (index > 0) result.append('\n');
            result.append(lines.get(index));
        }
        return result.toString();
    }
}
