import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The lower panel as `dumpsys SurfaceFlinger` reports it (same reading as
 * tools/thor_lower_display_repair.py). Plain Java so a host test can run it:
 * `main` prints the parse of a dump on stdin.
 */
final class LowerDisplayState {
    static final long LAYER_STACK_ASLEEP = 0xFFFFFFFFL;

    private static final Pattern HEADER =
            Pattern.compile("^Display (\\d+) \\((internal|physical)([^)]*)\\)", Pattern.MULTILINE);
    private static final Pattern ACTIVE_MODE = Pattern.compile("activeModeId=(\\d+)");
    private static final Pattern MODE = Pattern.compile("\\{id=(\\d+), hwcId=\\d+, resolution=(\\d+x\\d+)");
    private static final Pattern STACK = Pattern.compile("layerFilter=\\{layerStack=(\\d+)");
    private static final Pattern SIZE =
            Pattern.compile("^\\s+size=\\[(\\d+) (\\d+)\\]", Pattern.MULTILINE);
    private static final Pattern ACQUIRED = Pattern.compile("state=ACQUIRED[^\\[\\n]*\\[(\\d+)x(\\d+):");
    private static final Pattern POWER = Pattern.compile("powerMode=(\\w+)");

    String id;
    String mode;
    String framebuffer;
    String clientTarget;
    String power;
    Long layerStack;

    /** The non-primary internal display in a dump, or null. */
    static LowerDisplayState parse(String dump) {
        List<int[]> spans = new ArrayList<>();
        List<String[]> heads = new ArrayList<>();
        Matcher header = HEADER.matcher(dump);
        while (header.find()) {
            spans.add(new int[] {header.end()});
            heads.add(new String[] {header.group(1), header.group(2), header.group(3)});
        }
        Map<String, String> sections = new HashMap<>();
        LowerDisplayState lower = null;
        for (int i = 0; i < heads.size(); i++) {
            int start = spans.get(i)[0];
            int end = i + 1 < heads.size() ? dumpStart(dump, spans.get(i + 1)[0]) : dump.length();
            String body = sectionBody(dump.substring(start, Math.max(start, end)));
            String[] head = heads.get(i);
            sections.put(head[0] + " " + head[1], body);
            if (head[1].equals("internal") && !head[2].contains("primary") && lower == null) {
                lower = new LowerDisplayState();
                lower.id = head[0];
            }
        }
        if (lower == null) return null;
        String internal = sections.get(lower.id + " internal");
        Matcher active = ACTIVE_MODE.matcher(internal);
        String activeId = active.find() ? active.group(1) : null;
        Map<String, String> modes = new HashMap<>();
        String firstMode = null;
        Matcher mode = MODE.matcher(internal);
        while (mode.find()) {
            modes.put(mode.group(1), mode.group(2));
            if (firstMode == null) firstMode = mode.group(2);
        }
        lower.mode = activeId != null && modes.containsKey(activeId) ? modes.get(activeId) : firstMode;
        Matcher power = POWER.matcher(internal);
        lower.power = power.find() ? power.group(1) : null;
        String physical = sections.get(lower.id + " physical");
        if (physical != null) {
            Matcher stack = STACK.matcher(physical);
            if (stack.find()) lower.layerStack = Long.parseLong(stack.group(1));
            Matcher size = SIZE.matcher(physical);
            if (size.find()) lower.framebuffer = size.group(1) + "x" + size.group(2);
            Matcher acquired = ACQUIRED.matcher(physical);
            if (acquired.find()) lower.clientTarget = acquired.group(1) + "x" + acquired.group(2);
        }
        return lower;
    }

    /** Start of the header line whose match ended at headerEnd. */
    private static int dumpStart(String dump, int headerEnd) {
        int newline = dump.lastIndexOf('\n', headerEnd - 1);
        return newline < 0 ? 0 : newline;
    }

    /** A section ends at the first unindented line after its header. */
    private static String sectionBody(String text) {
        int offset = text.indexOf('\n');
        while (offset >= 0 && offset + 1 < text.length()) {
            char next = text.charAt(offset + 1);
            if (next != ' ' && next != '\t' && next != '\n' && next != '\r') {
                return text.substring(0, offset);
            }
            offset = text.indexOf('\n', offset + 1);
        }
        return text;
    }

    /** The panel's mismatches, empty when it is healthy. */
    List<String> problems() {
        List<String> found = new ArrayList<>();
        if (mode == null) {
            found.add("lower display mode not found");
            return found;
        }
        if (framebuffer != null && !framebuffer.equals(mode)) {
            found.add("framebuffer " + framebuffer + " != panel mode " + mode);
        }
        if (clientTarget != null && !clientTarget.equals(mode)) {
            found.add("HWC client target " + clientTarget + " != panel mode " + mode);
        }
        return found;
    }

    boolean asleep() {
        return layerStack == null || layerStack == LAYER_STACK_ASLEEP;
    }

    @Override
    public String toString() {
        return "lower " + id + ": mode " + mode + " framebuffer " + framebuffer + " client target "
                + clientTarget + " layerStack " + layerStack + " power " + power;
    }

    public static void main(String[] args) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] chunk = new byte[65536];
        InputStream in = System.in;
        for (int n; (n = in.read(chunk)) > 0; ) bytes.write(chunk, 0, n);
        LowerDisplayState state = parse(bytes.toString("UTF-8"));
        if (state == null) {
            System.out.println("none");
            return;
        }
        System.out.println(state.id + "|" + state.mode + "|" + state.framebuffer + "|"
                + state.clientTarget + "|" + state.layerStack + "|" + state.asleep() + "|"
                + String.join("; ", state.problems()));
    }
}
