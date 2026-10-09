package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Dolphin's per-game local INI: {@code <User>/GameSettings/<GAMEID>.ini}.
 *
 * <p>Under the libretro build the user directory is {@code <save dir>/User}
 * whenever the frontend supplies a save directory (DolphinLibretro/Boot.cpp),
 * which EmuFusion always does, so the file lands in the per-game save tree.
 *
 * <p>Every catalogue row is written into {@code [Gecko]} / {@code [ActionReplay]}
 * so the core's {@code retro_cheat_set} (enable_cheat_by_code) has a body to
 * match against. The {@code [Gecko_Enabled]} / {@code [ActionReplay]_Enabled}
 * sections are deliberately left empty: Dolphin's {@code GeckoCode}/{@code
 * ARCode} default to {@code enabled = false} on load, and {@code
 * ReadEnabledOrDisabled} only ever flips a code named there -- it never
 * clears one that is absent. If this writer named the currently-enabled
 * codes there instead, a later in-session disable would go stale: the pinned
 * {@code retro_cheat_reset} re-reads this INI (reloading every code back to
 * whatever the {@code _Enabled} section says) and {@code retro_cheat_set}
 * only calls {@code enable_cheat_by_code(true, ...)} for the codes still on,
 * never {@code false} for the one just turned off, so a code named in a
 * stale {@code _Enabled} section keeps activating even after its switch
 * shows off. Loading every code disabled and letting the live session's own
 * {@code retro_cheat_set} calls re-enable exactly the current selection
 * after each reset keeps a disable real for the rest of the session; the
 * selection still survives a relaunch because this file is regenerated with
 * the current selection before every boot.
 */
public final class DolphinGameSettingsWriter implements BootCheatWriter {
    private static final Pattern GAME_ID = Pattern.compile("^([A-Z0-9]{6})");
    private static final Pattern ENCRYPTED_AR =
            Pattern.compile("^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{5}$");

    enum Kind { GECKO, ACTION_REPLAY }

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        String gameId = gameId(request);
        if (gameId.isEmpty() || request.gameSaveDirectory == null) return touched;
        File directory = new File(request.gameSaveDirectory, "User/GameSettings");
        File file = new File(directory, gameId + ".ini");
        if (request.cheats.isEmpty()) {
            if (OwnedFiles.remove(file, OwnedFiles.Ownership.EXACT)) touched.add(file);
            return touched;
        }
        String text = render(request);
        if (OwnedFiles.write(file, text, OwnedFiles.Ownership.EXACT)) touched.add(file);
        return touched;
    }

    static String gameId(BootCheatRequest request) {
        for (String key : new String[] {"gameId", "discIdentity", "discId"}) {
            Matcher matcher = GAME_ID.matcher(request.identity(key).toUpperCase(Locale.US));
            if (matcher.find()) return matcher.group(1);
        }
        return "";
    }

    static String render(BootCheatRequest request) {
        StringBuilder ar = new StringBuilder();
        StringBuilder gecko = new StringBuilder();
        Set<String> used = new HashSet<>();
        for (DeliveryCheat row : request.cheats) {
            Kind kind = kindOf(row, request.systemId);
            List<String> body = body(row, kind);
            if (body == null) continue;
            String name = CheatCodeText.uniqueName(
                    CheatCodeText.safeName(row.cheat.name, 96), used);
            StringBuilder section = kind == Kind.GECKO ? gecko : ar;
            section.append('$').append(name).append('\n');
            for (String line : body) section.append(line).append('\n');
        }
        StringBuilder out = new StringBuilder();
        out.append("# Written by EmuFusion cheat delivery for ").append(gameId(request))
                .append(". Regenerated before every launch; change the selection in EmuFusion.\n");
        // [*_Enabled] sections are intentionally omitted -- see the class
        // comment. Every code loads disabled; the live session's own
        // retro_cheat_set calls turn on exactly the current selection.
        out.append("[ActionReplay]\n").append(ar);
        out.append("[Gecko]\n").append(gecko);
        return out.toString();
    }

    /** Which handler Dolphin should feed the code; wrong guesses are refused by Dolphin. */
    static Kind kindOf(DeliveryCheat row, String systemId) {
        String format = row.engineFormat;
        String description = row.cheat.description.toLowerCase(Locale.US);
        if (format.contains("gecko") || row.hasTag("gecko") || description.contains("gecko"))
            return Kind.GECKO;
        if (format.contains("actionreplay") || format.equals("ar") || row.hasTag("actionreplay")
                || row.hasTag("ar") || description.contains("actionreplay")
                || description.contains("action replay"))
            return Kind.ACTION_REPLAY;
        for (String line : CheatCodeText.lines(row.cheat.code))
            if (ENCRYPTED_AR.matcher(line.toUpperCase(Locale.US)).matches()) return Kind.ACTION_REPLAY;
        return "gamecube".equalsIgnoreCase(systemId) ? Kind.ACTION_REPLAY : Kind.GECKO;
    }

    /** Lines Dolphin will parse without a panic alert, or null to skip the row. */
    static List<String> body(DeliveryCheat row, Kind kind) {
        List<String> lines = CheatCodeText.lines(row.cheat.code);
        if (lines.isEmpty()) return null;
        List<String> body = new ArrayList<>();
        for (String line : lines) {
            String pair = CheatCodeText.hexPair(line);
            if (pair != null) { body.add(pair); continue; }
            String upper = line.toUpperCase(Locale.US);
            if (kind == Kind.ACTION_REPLAY && ENCRYPTED_AR.matcher(upper).matches()) {
                body.add(upper);
                continue;
            }
            return null;
        }
        return body;
    }
}
