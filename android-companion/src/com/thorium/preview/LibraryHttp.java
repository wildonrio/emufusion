package com.thorium.preview;

import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** Bounded transfers for the resumable library worker; independent of Android/UI. */
final class LibraryHttp {
    interface Progress { void update(String host, long bytes, long total); }
    static final class Scope implements AutoCloseable {
        final long deadline;
        final long refreshAfter;
        final Progress progress;
        String error = "";
        Scope(long milliseconds, long refreshAfter, Progress progress) {
            this.deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(milliseconds);
            this.refreshAfter = refreshAfter;
            this.progress = progress;
        }
        public void close() { CURRENT.remove(); }
    }
    private static final ThreadLocal<Scope> CURRENT = new ThreadLocal<>();
    /**
     * Failures on this thread that say nothing about whether an asset exists:
     * timeouts, network errors, throttling, server errors, a host in backoff.
     * A 404/410 is an answer and is not counted. Callers snapshot this around
     * a lookup; an unchanged count means every source really answered, so a
     * miss is definitive (owner, 2026-10-11: never re-search what cannot be
     * found, but never give up because of a network blip).
     */
    private static final ThreadLocal<int[]> INDEFINITE = new ThreadLocal<int[]>() {
        @Override protected int[] initialValue() { return new int[1]; }
    };
    /**
     * Downloads on this thread that continued a kept partial file and added
     * to it. A pass that only got further through a long file has not failed
     * to find anything, so the queue does not count it as an attempt.
     */
    private static final ThreadLocal<int[]> RESUMED = new ThreadLocal<int[]>() {
        @Override protected int[] initialValue() { return new int[1]; }
    };
    private static final ConcurrentHashMap<String, Long> BACKOFF = new ConcurrentHashMap<>();
    private static final ScheduledThreadPoolExecutor TIMER = new ScheduledThreadPoolExecutor(1, task -> {
        Thread thread = new Thread(task, "emufusion-transfer-deadlines");
        thread.setDaemon(true);
        return thread;
    });
    static { TIMER.setRemoveOnCancelPolicy(true); }

    static Scope begin(long milliseconds, long refreshAfter, Progress progress) {
        Scope scope = new Scope(milliseconds, refreshAfter, progress);
        CURRENT.set(scope);
        return scope;
    }
    static int indefiniteFailures() { return INDEFINITE.get()[0]; }
    static int resumedDownloads() { return RESUMED.get()[0]; }
    static void noteIndefiniteFailure() { INDEFINITE.get()[0]++; }

    static boolean reusable(File file) {
        Scope scope = CURRENT.get();
        return file.isFile() && file.length() > 512 &&
                (scope == null || scope.refreshAfter <= 0 || file.lastModified() >= scope.refreshAfter);
    }
    /** Where a response body goes, chosen once the response is known. */
    private interface Sink {
        /** {@code resumed}: the server is continuing the kept partial (206). */
        OutputStream open(boolean resumed, String version) throws IOException;
    }

    /** Set once a body with a stable version is streaming: worth keeping if cut off. */
    private static final class Partial { boolean keep; }

    static byte[] fetch(String url, long maximum) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        transfer(url, (resumed, version) -> output, maximum, 30_000L, false, 0L, "", null);
        return output.toByteArray();
    }

    /**
     * Downloads to {@code target}, replacing it only when complete. A download
     * cut off by its time limit keeps what arrived, with its URL and the
     * server's version of the file (strong ETag or Last-Modified), and the
     * next call asks for the rest (Range + If-Range; a changed file comes back
     * whole and starts over). Owner, 2026-10-24: over a slow link a preview
     * video never finished within one pass, started from zero every time and
     * kept the game queued on every launch.
     */
    static boolean download(String url, File target, long maximum) throws IOException {
        if (reusable(target)) return true;
        target.getParentFile().mkdirs();
        File part = new File(target.getPath() + ".part");
        File origin = new File(target.getPath() + ".part.origin");
        String[] kept = readOrigin(origin);
        long offset = 0L;
        String version = "";
        if (part.isFile() && part.length() > 0 && url.equals(kept[0]) && !kept[1].isEmpty()) {
            offset = part.length();
            version = kept[1];
        } else {
            part.delete();
            origin.delete();
        }
        Partial partial = new Partial();
        try {
            FileOutputStream[] opened = new FileOutputStream[1];
            try {
                transfer(url, (resumed, current) -> {
                    if (!resumed) writeOrigin(origin, url, current);
                    opened[0] = new FileOutputStream(part, resumed);
                    return opened[0];
                }, maximum, 120_000L, true, offset, version, partial);
                opened[0].getFD().sync();
            } finally {
                if (opened[0] != null) opened[0].close();
            }
            if (part.length() <= 512) throw new IOException("Media response was empty or too short");
            // Never delete a working asset before its replacement is complete.
            try {
                Files.move(part.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException unsupported) {
                Files.move(part.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING);
            }
            origin.delete();
            return true;
        } catch (IOException localFailure) {
            // A full or unwritable library volume is not a missing asset.
            if (!(localFailure instanceof HttpAnswer)) noteIndefiniteFailure();
            if (!partial.keep) {
                part.delete();
                origin.delete();
            }
            throw localFailure;
        }
    }

    /** The kept partial's URL and file version; empty strings when there is none. */
    private static String[] readOrigin(File origin) {
        try {
            String[] lines = new String(Files.readAllBytes(origin.toPath()),
                    java.nio.charset.StandardCharsets.UTF_8).split("\n", -1);
            if (lines.length >= 2) return new String[]{lines[0], lines[1]};
        } catch (IOException missing) {}
        return new String[]{"", ""};
    }

    private static void writeOrigin(File origin, String url, String version) throws IOException {
        if (version.isEmpty() || url.indexOf('\n') >= 0) {
            origin.delete();
            return;
        }
        Files.write(origin.toPath(), (url + "\n" + version + "\n")
                .getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    private static void transfer(String address, Sink sink, long maximum,
                                 long requestLimit, boolean media, long offset,
                                 String version, Partial partial) throws IOException {
        Scope scope = CURRENT.get();
        URL url = new URL(address);
        String host = url.getHost();
        long end = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(requestLimit);
        if (scope != null) end = Math.min(end, scope.deadline);
        long remaining = TimeUnit.NANOSECONDS.toMillis(end - System.nanoTime());
        if (remaining <= 0) {
            noteIndefiniteFailure();
            throw failed(scope, "Stage time limit reached");
        }
        if (BACKOFF.getOrDefault(host, 0L) > System.nanoTime()) {
            noteIndefiniteFailure();
            throw failed(scope, host + " temporarily unavailable; retry scheduled");
        }
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        int timeout = (int) Math.max(1, Math.min(10_000, remaining));
        connection.setConnectTimeout(timeout);
        connection.setReadTimeout(timeout);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("User-Agent", "EmuFusion-Library/1.0");
        if (media) connection.setRequestProperty("Accept-Encoding", "identity");
        if (offset > 0) {
            connection.setRequestProperty("Range", "bytes=" + offset + "-");
            connection.setRequestProperty("If-Range", version);
        }
        if (host.endsWith("metacritic.com")) {
            connection.setRequestProperty("Origin", "https://www.metacritic.com");
            connection.setRequestProperty("Referer", "https://www.metacritic.com/");
        }
        AtomicReference<InputStream> active = new AtomicReference<>();
        ScheduledFuture<?> deadline = TIMER.schedule(() -> {
            connection.disconnect();
            InputStream input = active.get();
            if (input != null) try { input.close(); } catch (IOException ignored) {}
        }, remaining, TimeUnit.MILLISECONDS);
        boolean transientFailure = true;
        boolean resumed = false;
        int code = -1;
        long total = 0;
        try {
            if (scope != null && scope.progress != null) scope.progress.update(host, 0, -1);
            code = connection.getResponseCode();
            if (code < 200 || code >= 300) {
                transientFailure = code == 403 || code == 429 || code >= 500;
                throw new IOException(host + " HTTP " + code);
            }
            // The host answered: a cut-off body is our time limit, not its outage.
            transientFailure = false;
            resumed = offset > 0 && code == 206;
            String range = connection.getHeaderField("Content-Range");
            if (code == 206 && !(resumed && range != null && range.startsWith("bytes " + offset + "-")))
                throw new IOException(host + " sent a different part of the file");
            String type = connection.getContentType();
            if (media && type != null && (type.startsWith("text/") || type.contains("json")))
                throw new IOException(host + " returned a page instead of media");
            long base = resumed ? offset : 0L;
            long expected = connection.getContentLengthLong();
            if (expected > maximum - base) throw new IOException("Response too large");
            String current = resumed ? version : stableVersion(connection);
            OutputStream output = sink.open(resumed, current);
            if (partial != null) partial.keep = !current.isEmpty();
            long lastProgress = 0;
            try (InputStream input = new BufferedInputStream(connection.getInputStream())) {
                active.set(input);
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (Thread.currentThread().isInterrupted() || System.nanoTime() >= end)
                        throw new IOException("Transfer time limit reached");
                    total += count;
                    if (base + total > maximum) {
                        if (partial != null) partial.keep = false;
                        throw new IOException("Response too large");
                    }
                    output.write(buffer, 0, count);
                    if (scope != null && scope.progress != null &&
                            System.nanoTime() - lastProgress >= 500_000_000L) {
                        scope.progress.update(host, base + total, expected < 0 ? -1 : base + expected);
                        lastProgress = System.nanoTime();
                    }
                }
            }
            if (System.nanoTime() >= end) throw new IOException("Transfer time limit reached");
            if (expected >= 0 && total != expected) throw new IOException("Incomplete response");
            if (scope != null && scope.progress != null)
                scope.progress.update(host, base + total, expected < 0 ? -1 : base + expected);
        } catch (IOException error) {
            if (transientFailure) BACKOFF.put(host, System.nanoTime() + TimeUnit.MINUTES.toNanos(2));
            String message = error.getMessage() == null ? "Transfer failed" : error.getMessage();
            if (code == 404 || code == 410) {
                if (scope != null) scope.error = message;
                throw new HttpAnswer(message);
            }
            noteIndefiniteFailure();
            throw failed(scope, message);
        } finally {
            if (resumed && total > 0) RESUMED.get()[0]++;
            deadline.cancel(false);
            active.set(null);
            connection.disconnect();
        }
    }

    /** A version If-Range can compare: a strong ETag, else Last-Modified; "" when neither. */
    private static String stableVersion(HttpURLConnection connection) {
        String tag = connection.getHeaderField("ETag");
        if (tag != null && !tag.isEmpty() && !tag.startsWith("W/")) return tag;
        String modified = connection.getHeaderField("Last-Modified");
        return modified == null ? "" : modified;
    }
    /** The server definitively answered "not here" (404/410). */
    static final class HttpAnswer extends IOException {
        HttpAnswer(String message) { super(message); }
    }

    private static IOException failed(Scope scope, String message) {
        if (scope != null) scope.error = message;
        return new IOException(message);
    }
}
