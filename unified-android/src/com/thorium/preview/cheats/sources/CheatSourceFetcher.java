package com.thorium.preview.cheats.sources;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Bounded HTTPS downloads with a seven-day on-disk cache.
 *
 * <p>Each URL is stored under {@code <cacheRoot>/cheats/<source id>/<sha256(url)>.bin}
 * with a {@code .meta} sidecar (ETag, Last-Modified, fetch time). A fresh copy
 * is returned without touching the network; a stale copy is revalidated with
 * {@code If-None-Match}/{@code If-Modified-Since} and kept when the server
 * says 304 or the network fails. A miss is memoised for seven days so a scan
 * of 300 games does not ask 300 times -- but only a definitive "this does
 * not exist" answer (404/410) counts as a miss; a transient failure (DNS
 * blip, timeout, connection reset, TLS error) must not be, or one bad packet
 * silently starves every game for a week. Within one process a URL is
 * attempted at most once; a host that keeps timing out has its per-game
 * requests (one URL each, so the per-URL memo does not help) short-circuited
 * for the rest of the session after a few consecutive failures, rather than
 * paying a full connect timeout per game.
 *
 * <p>Nothing here throws to the caller: a failed fetch yields {@code null}.
 */
public final class CheatSourceFetcher implements CheatFetch {
    public static final String USER_AGENT = "Lucent-Cheats/1.0 (+https://github.com/wildonrio/emufusion)";
    public static final long REFRESH_MS = 7L * 24L * 60L * 60L * 1000L;
    public static final long MISS_MS = REFRESH_MS;
    static final int CONNECT_TIMEOUT_MS = 15_000;
    static final int READ_TIMEOUT_MS = 45_000;
    private static final long DEFAULT_MAX_BYTES = 64L * 1024L * 1024L;

    // Collections.newSetFromMap: ConcurrentHashMap.newKeySet() needs API 24 (minSdk 21).
    private static final Set<String> ATTEMPTED_THIS_PROCESS =
            Collections.newSetFromMap(new ConcurrentHashMap<String, Boolean>());

    /** Consecutive network-level failures (timeout, reset, DNS) before a host is skipped for the session. */
    static final int HOST_FAILURE_THRESHOLD = 3;
    // Declared as ConcurrentHashMap, not Map: putIfAbsent() on a Map-typed
    // reference resolves to Map's default method (API 24); ConcurrentHashMap
    // has always implemented it directly (API 1), which is what minSdk 21 needs.
    private static final ConcurrentHashMap<String, AtomicInteger> HOST_FAILURES =
            new ConcurrentHashMap<>();

    private final File root;
    private final long now;

    /** API-21-safe Content-Length: parses the header manually (negative when absent/invalid). */
    static long declaredContentLength(HttpURLConnection connection) {
        String header = connection.getHeaderField("Content-Length");
        if (header == null) return -1L;
        try {
            return Long.parseLong(header.trim());
        } catch (NumberFormatException e) {
            return -1L;
        }
    }

    public CheatSourceFetcher(File cacheRoot) {
        this(cacheRoot, System.currentTimeMillis());
    }

    CheatSourceFetcher(File cacheRoot, long now) {
        this.root = new File(cacheRoot, "cheats");
        this.now = now;
    }

    public File cacheRoot() { return root; }

    public File cachedFile(CheatSource source, String url) {
        return new File(new File(root, source == null ? "unknown" : source.id),
                CheatIdFactory.shortHash(url == null ? "" : url) + ".bin");
    }

    @Override public File fetch(CheatSource source, String url) {
        if (source == null || url == null || !url.toLowerCase(Locale.US).startsWith("https://"))
            return null;
        File target = cachedFile(source, url);
        File meta = new File(target.getAbsolutePath() + ".meta");
        File miss = new File(target.getAbsolutePath() + ".miss");
        Map<String, Object> state = readMeta(meta);
        long fetchedAt = JsonLite.number(state.get("fetchedAt"), 0L);
        if (target.isFile() && target.length() > 0 && isFresh(fetchedAt, now)) return target;
        if (!target.isFile() && miss.isFile() && isMissFresh(miss.lastModified(), now)) return null;
        if (!ATTEMPTED_THIS_PROCESS.add(url)) return target.isFile() ? target : null;

        String host = hostOf(url);
        if (hostCircuitOpen(host)) return target.isFile() ? target : null;

        long cap = source.maxBytes > 0 ? source.maxBytes : DEFAULT_MAX_BYTES;
        HttpURLConnection connection = null;
        try {
            connection = open(url);
            if (target.isFile()) {
                String etag = JsonLite.string(state.get("etag"));
                String lastModified = JsonLite.string(state.get("lastModified"));
                if (!etag.isEmpty()) connection.setRequestProperty("If-None-Match", etag);
                if (!lastModified.isEmpty())
                    connection.setRequestProperty("If-Modified-Since", lastModified);
            }
            int status = connection.getResponseCode();
            // The host answered at all, however it answered, so it is not down.
            resetHostFailures(host);
            if (status == HttpURLConnection.HTTP_NOT_MODIFIED && target.isFile()) {
                state.put("fetchedAt", now);
                writeMeta(meta, state);
                return target;
            }
            if (status < 200 || status >= 300) {
                if (target.isFile()) return target; // stale beats nothing
                // Only a definitive "does not exist" is memoised for a week;
                // a server hiccup (5xx, 429, ...) should be retried next scan.
                if (status == HttpURLConnection.HTTP_NOT_FOUND || status == HttpURLConnection.HTTP_GONE)
                    touch(miss);
                return null;
            }
            long declared = declaredContentLength(connection); // getContentLengthLong() needs API 24
            if (declared > cap) {
                if (target.isFile()) return target;
                touch(miss); // a definitive fact about this response, unlike a transient failure
                return null;
            }
            File parent = target.getParentFile();
            if (parent != null && !parent.isDirectory()) parent.mkdirs();
            File part = new File(target.getAbsolutePath() + ".part");
            long written;
            try {
                try (InputStream input = connection.getInputStream();
                     OutputStream output = new FileOutputStream(part)) {
                    written = copy(input, output, cap);
                }
            } catch (IOException copyFailed) {
                // A dropped connection mid-download must not leave a partial
                // file sitting on shared storage for the life of the cache.
                part.delete();
                throw copyFailed;
            }
            if (written <= 0) {
                part.delete();
                if (target.isFile()) return target;
                touch(miss); // a definitive empty 200 OK, unlike a transient failure
                return null;
            }
            byte[] head = peek(part, SNIFF_BYTES);
            if (!isPlausiblePayload(url, head)) {
                // A captive portal (or any wrong-shaped 2xx body) must never
                // be cached as if it were the real archive/feed. It is not a
                // definitive miss either -- the same URL may answer for real
                // once off that network -- so it is not memoised as one.
                part.delete();
                return target.isFile() ? target : null;
            }
            if (target.exists()) target.delete();
            if (!part.renameTo(target)) {
                part.delete();
                return null;
            }
            Map<String, Object> fresh = new LinkedHashMap<>();
            fresh.put("url", url);
            fresh.put("fetchedAt", now);
            fresh.put("bytes", written);
            String etag = connection.getHeaderField("ETag");
            String lastModified = connection.getHeaderField("Last-Modified");
            if (etag != null) fresh.put("etag", etag);
            if (lastModified != null) fresh.put("lastModified", lastModified);
            writeMeta(meta, fresh);
            miss.delete();
            return target;
        } catch (IOException | RuntimeException failed) {
            // Keep whatever we had; a scan must never stall on one source.
            // Transient (timeout/reset/DNS) is not the same as "does not
            // exist": never memoise it as a miss, only count it against the
            // host so a dead host stops costing a full timeout per game.
            recordHostFailure(host);
            return target.isFile() ? target : null;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    /** Convenience for small text resources; null when unavailable or over the cap. */
    public String fetchText(CheatSource source, String url, long cap) {
        File file = fetch(source, url);
        return file == null ? null : readText(file, cap);
    }

    public static String readText(File file, long cap) {
        if (file == null || !file.isFile() || file.length() > cap) return null;
        try (InputStream input = new FileInputStream(file)) {
            return DownloadedCheatCodec.readAll(input, cap);
        } catch (IOException unreadable) {
            return null;
        }
    }

    public static boolean isFresh(long fetchedAt, long now) {
        return fetchedAt > 0 && now - fetchedAt >= 0 && now - fetchedAt < REFRESH_MS;
    }

    public static boolean isMissFresh(long missedAt, long now) {
        return missedAt > 0 && now - missedAt >= 0 && now - missedAt < MISS_MS;
    }

    /** Test seam: forget the per-process attempt memo and host failure counts. */
    static void resetSessionMemo() {
        ATTEMPTED_THIS_PROCESS.clear();
        HOST_FAILURES.clear();
    }

    /** The lower-cased host of an https URL, or "" if it cannot be parsed. */
    static String hostOf(String url) {
        try {
            String host = new URL(url).getHost();
            return host == null ? "" : host.toLowerCase(Locale.US);
        } catch (java.net.MalformedURLException malformed) {
            return "";
        }
    }

    static boolean hostCircuitOpen(String host) {
        if (host.isEmpty()) return false;
        AtomicInteger failures = HOST_FAILURES.get(host);
        return failures != null && failures.get() >= HOST_FAILURE_THRESHOLD;
    }

    private static void recordHostFailure(String host) {
        if (host.isEmpty()) return;
        AtomicInteger failures = HOST_FAILURES.get(host);
        if (failures == null) {
            failures = new AtomicInteger();
            AtomicInteger existing = HOST_FAILURES.putIfAbsent(host, failures);
            if (existing != null) failures = existing;
        }
        failures.incrementAndGet();
    }

    private static void resetHostFailures(String host) {
        if (!host.isEmpty()) HOST_FAILURES.remove(host);
    }

    private static final int SNIFF_BYTES = 512;

    /** The first up-to-{@code max} bytes of {@code file}; empty on any read failure. */
    private static byte[] peek(File file, int max) {
        byte[] buffer = new byte[max];
        try (InputStream input = new FileInputStream(file)) {
            int total = 0;
            int read;
            while (total < max && (read = input.read(buffer, total, max - total)) >= 0) total += read;
            if (total == buffer.length) return buffer;
            byte[] trimmed = new byte[total];
            System.arraycopy(buffer, 0, trimmed, 0, total);
            return trimmed;
        } catch (IOException unreadable) {
            return new byte[0];
        }
    }

    /**
     * Rejects a captive-portal (or any other wrong-shaped) 2xx body before it
     * is cached as if it were the real payload: no legitimate source here
     * ever answers with an HTML page, and a URL that names a container
     * ({@code .zip}/zipball, {@code .json}) must start with that container's
     * magic bytes.
     */
    static boolean isPlausiblePayload(String url, byte[] head) {
        int i = 0;
        while (i < head.length && Character.isWhitespace(head[i] & 0xFF)) i++;
        int remaining = head.length - i;
        if (remaining >= 3 && (head[i] & 0xFF) == 0xEF && (head[i + 1] & 0xFF) == 0xBB
                && (head[i + 2] & 0xFF) == 0xBF) i += 3; // UTF-8 BOM
        remaining = head.length - i;
        if (remaining <= 0) return false;
        String prefix = new String(head, i, Math.min(remaining, 32), StandardCharsets.US_ASCII)
                .toLowerCase(Locale.US);
        if (prefix.startsWith("<!doctype html") || prefix.startsWith("<html")) return false;
        String lower = url == null ? "" : url.toLowerCase(Locale.US);
        if (lower.endsWith(".zip") || lower.contains("zipball"))
            return remaining >= 2 && (head[i] & 0xFF) == 0x50 && (head[i + 1] & 0xFF) == 0x4B;
        if (lower.endsWith(".json"))
            return head[i] == '{' || head[i] == '[';
        return true; // unknown container shape (raw text/db/txt/yml): only the HTML check applies
    }

    private static HttpURLConnection open(String url) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("User-Agent", USER_AGENT);
        connection.setRequestProperty("Accept-Encoding", "identity");
        if (url.startsWith("https://api.github.com/") && url.contains("/contents/"))
            connection.setRequestProperty("Accept", "application/vnd.github.raw");
        else if (url.startsWith("https://api.github.com/"))
            connection.setRequestProperty("Accept", "application/vnd.github+json");
        return connection;
    }

    private static long copy(InputStream input, OutputStream output, long cap) throws IOException {
        byte[] buffer = new byte[64 * 1024];
        long total = 0;
        int read;
        while ((read = input.read(buffer)) >= 0) {
            total += read;
            if (total > cap) throw new IOException("download exceeds " + cap + " bytes");
            output.write(buffer, 0, read);
        }
        output.flush();
        return total;
    }

    private static Map<String, Object> readMeta(File meta) {
        String text = readText(meta, 64L * 1024L);
        return text == null ? new LinkedHashMap<String, Object>() : JsonLite.parseObject(text);
    }

    private static void writeMeta(File meta, Map<String, Object> state) {
        try {
            File part = new File(meta.getAbsolutePath() + ".part");
            try (OutputStream output = new FileOutputStream(part)) {
                output.write(JsonLite.write(state).getBytes(StandardCharsets.UTF_8));
            }
            if (meta.exists()) meta.delete();
            part.renameTo(meta);
        } catch (IOException ignored) {
            // Metadata is an optimisation; the payload file is what matters.
        }
    }

    private void touch(File marker) {
        try {
            File parent = marker.getParentFile();
            if (parent != null && !parent.isDirectory()) parent.mkdirs();
            try (OutputStream output = new FileOutputStream(marker)) {
                output.write(String.valueOf(now).getBytes(StandardCharsets.UTF_8));
            }
            marker.setLastModified(now);
        } catch (IOException ignored) {
            // A miss we cannot record is simply retried next time.
        }
    }
}
