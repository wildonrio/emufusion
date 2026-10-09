package com.thorium.preview;

import android.content.Context;

import com.thorium.preview.game.WidescreenHackPolicy;
import com.thorium.preview.game.WidescreenHackTable;
import com.thorium.preview.game.WidescreenSettings;

import org.json.JSONObject;

import java.net.URLDecoder;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * {@code GET /settings/widescreen-hack}: the per-system widescreen hack
 * (design section 7), separate from the historic {@code /settings/widescreen}
 * native Wii 16:9 flag.
 *
 * <ul>
 * <li>No query: returns the state.</li>
 * <li>{@code ?enabled=0|1|true|false}: sets the global hack flag.</li>
 * <li>{@code ?system=<id>&mode=on|off|auto}: sets one system's override
 *     ({@code auto} clears it).</li>
 * </ul>
 * Response: {@code {"ok":true,"hackEnabled":bool,"systems":{"n64":{"mode":
 * "auto","availability":"hack","effective":bool},...}}}. Every write is
 * persisted through {@link WidescreenSettings} before the response is
 * written, because the HTTP response is the launch boundary.
 */
public final class WidescreenHackEndpoint {
    /** HTTP status line and JSON body for {@code PreviewService.respond}. */
    public static final class Result {
        public final String status;
        public final String body;

        Result(String status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private WidescreenHackEndpoint() {}

    public static Result handle(Context context, String query) {
        Map<String, String> values = parseQuery(query);
        if (values.containsKey("enabled")) {
            String requested = values.get("enabled");
            WidescreenSettings.setHackEnabled(context,
                    !"0".equals(requested) && !"false".equalsIgnoreCase(requested));
        }
        if (values.containsKey("system") || values.containsKey("mode")) {
            String system = WidescreenHackTable.normaliseSystem(values.get("system"));
            String mode = values.get("mode");
            if (system.isEmpty() || !WidescreenHackTable.SYSTEMS.contains(system))
                return new Result("400 Bad Request",
                        "{\"ok\":false,\"error\":\"system must be one of " +
                        joined(WidescreenHackTable.SYSTEMS) + "\"}");
            if (!WidescreenSettings.isValidHackMode(mode))
                return new Result("400 Bad Request",
                        "{\"ok\":false,\"error\":\"mode must be on, off, or auto\"}");
            WidescreenSettings.setHackMode(context, system, mode);
        }
        return new Result("200 OK", stateJson(context));
    }

    /** The current state as JSON (also used by the theme's boot refresh). */
    public static String stateJson(Context context) {
        try {
            JSONObject root = new JSONObject();
            root.put("ok", true);
            root.put("hackEnabled", WidescreenSettings.isHackEnabled(context));
            JSONObject systems = new JSONObject();
            for (String system : WidescreenHackTable.SYSTEMS) {
                JSONObject entry = new JSONObject();
                entry.put("mode", WidescreenSettings.hackMode(context, system));
                entry.put("availability", WidescreenHackPolicy.availability(system));
                entry.put("effective", WidescreenHackPolicy.isHackEnabledFor(context, system));
                systems.put(system, entry);
            }
            root.put("systems", systems);
            return root.toString();
        } catch (Exception e) {
            return "{\"ok\":false,\"error\":\"cannot serialise widescreen hack state\"}";
        }
    }

    private static String joined(Iterable<String> items) {
        StringBuilder builder = new StringBuilder();
        for (String item : items) {
            if (builder.length() > 0) builder.append(", ");
            builder.append(item);
        }
        return builder.toString();
    }

    private static Map<String, String> parseQuery(String query) {
        Map<String, String> values = new HashMap<>();
        if (query == null || query.isEmpty()) return values;
        for (String pair : query.split("&")) {
            if (pair.isEmpty()) continue;
            String[] item = pair.split("=", 2);
            try {
                String key = URLDecoder.decode(item[0], "UTF-8").trim().toLowerCase(Locale.US);
                String value = item.length > 1 ? URLDecoder.decode(item[1], "UTF-8") : "";
                values.put(key, value);
            } catch (Exception ignored) {
                // A malformed pair is dropped; the remaining pairs still apply.
            }
        }
        return values;
    }
}
