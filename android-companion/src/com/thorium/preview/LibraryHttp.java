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
    static void noteIndefiniteFailure() { INDEFINITE.get()[0]++; }

    static boolean reusable(File file) {
        Scope scope = CURRENT.get();
        return file.isFile() && file.length() > 512 &&
                (scope == null || scope.refreshAfter <= 0 || file.lastModified() >= scope.refreshAfter);
    }
    static byte[] fetch(String url, long maximum) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        transfer(url, output, maximum, 30_000L, false);
        return output.toByteArray();
    }
    static boolean download(String url, File target, long maximum) throws IOException {
        if (reusable(target)) return true;
        target.getParentFile().mkdirs();
        File part = new File(target.getPath() + ".part");
        try {
            try (FileOutputStream output = new FileOutputStream(part)) {
                transfer(url, output, maximum, 120_000L, true);
                output.getFD().sync();
            }
            if (part.length() <= 512) throw new IOException("Media response was empty or too short");
            // Never delete a working asset before its replacement is complete.
            try {
                Files.move(part.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException unsupported) {
                Files.move(part.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING);
            }
            return true;
        } catch (IOException localFailure) {
            // A full or unwritable library volume is not a missing asset.
            if (!(localFailure instanceof HttpAnswer)) noteIndefiniteFailure();
            throw localFailure;
        } finally { if (part.exists()) part.delete(); }
    }

    private static void transfer(String address, OutputStream output, long maximum,
                                 long requestLimit, boolean media) throws IOException {
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
        int code = -1;
        try {
            if (scope != null && scope.progress != null) scope.progress.update(host, 0, -1);
            code = connection.getResponseCode();
            if (code < 200 || code >= 300) {
                transientFailure = code == 403 || code == 429 || code >= 500;
                throw new IOException(host + " HTTP " + code);
            }
            String type = connection.getContentType();
            if (media && type != null && (type.startsWith("text/") || type.contains("json")))
                throw new IOException(host + " returned a page instead of media");
            long expected = connection.getContentLengthLong();
            if (expected > maximum) throw new IOException("Response too large");
            long total = 0, lastProgress = 0;
            try (InputStream input = new BufferedInputStream(connection.getInputStream())) {
                active.set(input);
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (Thread.currentThread().isInterrupted() || System.nanoTime() >= end)
                        throw new IOException("Transfer time limit reached");
                    total += count;
                    if (total > maximum) throw new IOException("Response too large");
                    output.write(buffer, 0, count);
                    if (scope != null && scope.progress != null &&
                            System.nanoTime() - lastProgress >= 500_000_000L) {
                        scope.progress.update(host, total, expected);
                        lastProgress = System.nanoTime();
                    }
                }
            }
            if (System.nanoTime() >= end) throw new IOException("Transfer time limit reached");
            if (expected >= 0 && total != expected) throw new IOException("Incomplete response");
            if (scope != null && scope.progress != null) scope.progress.update(host, total, expected);
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
            deadline.cancel(false);
            active.set(null);
            connection.disconnect();
        }
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
