package com.thorium.preview;

import android.content.SharedPreferences;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Executes production reporting code against synthetic stores/transports, never device data. */
public final class PrivateDiagnosticsTest {
    static final URI URL_VALUE = URI.create("https://receiver.example.invalid/v1/report");
    static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static PrivateDiagnosticReport report(int build) {
        return PrivateDiagnosticReport.create(build, "n64", "engine_ready", "ok");
    }
    static class Store {
        final Map<String, Object> data = new HashMap<>();
        SharedPreferences preferences() {
            return (SharedPreferences) Proxy.newProxyInstance(getClass().getClassLoader(),
                    new Class<?>[]{SharedPreferences.class}, (proxy, method, args) -> {
                switch (method.getName()) {
                    case "getBoolean": case "getString":
                        synchronized (data) { return data.getOrDefault(args[0], args[1]); }
                    case "edit":
                        Map<String, Object> changes = new HashMap<>();
                        return Proxy.newProxyInstance(getClass().getClassLoader(),
                                new Class<?>[]{SharedPreferences.Editor.class}, (editor, edit, values) -> {
                            switch (edit.getName()) {
                                case "putBoolean": case "putString":
                                    changes.put((String) values[0], values[1]);
                                    return editor;
                                case "remove": changes.put((String) values[0], null); return editor;
                                case "commit": case "apply":
                                    synchronized (data) {
                                        for (Map.Entry<String, Object> entry : changes.entrySet()) {
                                            if (entry.getValue() == null) data.remove(entry.getKey());
                                            else data.put(entry.getKey(), entry.getValue());
                                        }
                                    }
                                    return edit.getName().equals("commit") ? true : null;
                                default: throw new AssertionError("Unexpected preference operation");
                            }
                        });
                    default: throw new AssertionError("Unexpected preference read");
                }
            });
        }
        String pending() { synchronized (data) { return (String) data.getOrDefault("pending", ""); } }
    }
    static PrivateDiagnostics owner(Store store, PrivateDiagnostics.Sender sender, long[] clock) {
        return new PrivateDiagnostics(store.preferences(), 90, URL_VALUE, sender, () -> clock[0]);
    }
    static void idle(PrivateDiagnostics owner) throws Exception {
        Field field = PrivateDiagnostics.class.getDeclaredField("worker");
        field.setAccessible(true);
        ((ExecutorService) field.get(owner)).submit(() -> {}).get(10, TimeUnit.SECONDS);
    }
    static void payloads() {
        String[] systems = {"switch", "wiiu", "ps3", "wii", "gamecube", "ps2", "psp",
                "dreamcast", "3ds", "psx", "nds", "n64", "snes", "nes", "gb", "gbc",
                "gba", "megadrive", "gamegear", "pcenginecd"};
        for (String system : systems) {
            PrivateDiagnosticReport report = PrivateDiagnosticReport.create(90, system, "engine_ready", "ok");
            require(report != null, "supported route absent");
            require(Arrays.equals(report.body(), PrivateDiagnosticReport.fromKey(report.key()).body()), "round trip");
            System.out.println(new String(report.body(), StandardCharsets.UTF_8));
        }
        for (String bad : new String[]{null, "PRIVATE@example.invalid", "/storage/owner/game.iso",
                "device-123", "192.0.2.1", "native\"\n", "", "gc"}) {
            require(PrivateDiagnosticReport.create(90, bad, "engine_ready", "ok") == null, "unsafe system");
            require(PrivateDiagnosticReport.create(90, "n64", bad, "ok") == null, "unsafe event");
            require(PrivateDiagnosticReport.create(90, "n64", "engine_ready", bad) == null, "unsafe bucket");
            require(PrivateDiagnosticReport.fromKey(bad) == null, "unsafe stored row");
        }
        require(PrivateDiagnosticReport.create(0, "n64", "engine_ready", "ok") == null, "invalid build");
        for (String bad : new String[]{"090|n64|engine_ready|ok", "90|n64|engine_ready|ok|PRIVATE",
                "9999999999|n64|engine_ready|ok", "90|n64|engine_ready|unknown"})
            require(PrivateDiagnosticReport.fromKey(bad) == null, "invalid persisted row");
    }
    static void lifecycle() {
        List<String> events = new ArrayList<>();
        PrivateDiagnosticsSession one = new PrivateDiagnosticsSession((event, bucket) -> events.add(event + ":" + bucket));
        one.failed(false); one.ready(); one.failed(true); one.close(); one.ready();
        require(events.equals(Arrays.asList("launch_failed:unknown")), "cold failure deduplication");
        events.clear();
        PrivateDiagnosticsSession two = new PrivateDiagnosticsSession((event, bucket) -> events.add(event + ":" + bucket));
        two.ready(); two.ready(); two.failed(true); two.failed(false); two.close();
        require(events.equals(Arrays.asList("engine_ready:ok", "runtime_failed:out_of_memory")), "ready/runtime distinction");
        events.clear();
        PrivateDiagnosticsSession three = new PrivateDiagnosticsSession((event, bucket) -> events.add(event));
        three.close(); three.ready(); three.failed(false);
        require(events.isEmpty(), "late retired callbacks");
        // Current production config is blank. This must not dereference Android Context.
        PrivateDiagnostics.session(null, "n64").ready();
        PrivateDiagnostics.gameplay(null, false);
    }

    static void recoveredExits() throws Exception {
        for (String bucket : new String[]{"java", "native", "anr", "out_of_memory", null,
                "process_death", "user_stop", "PRIVATE_ADDRESS"}) {
            Store store = new Store(); store.data.put("enabled", true);
            store.data.put("active", "89|ps3|123|1000");
            List<PrivateDiagnosticReport> sent = new ArrayList<>();
            AtomicInteger calls = new AtomicInteger();
            PrivateDiagnostics owner = new PrivateDiagnostics(store.preferences(), 90, URL_VALUE,
                    (uri, report) -> { sent.add(report); return PrivateDiagnosticsTransport.Result.ACCEPTED; },
                    () -> 0, () -> 3000, 456, (pid, start, end) -> {
                        require(pid == 123 && start == 1000 && end == 3000, "exact local exit match");
                        calls.incrementAndGet(); return bucket;
                    });
            idle(owner);
            require(calls.get() == 1 && !store.data.containsKey("active") && sent.isEmpty(),
                    "consume marker once; no upload on recovery");
            owner.setGameplay(false); idle(owner);
            boolean accepted = Arrays.asList("java", "native", "anr", "out_of_memory").contains(bucket);
            require(sent.size() == (accepted ? 1 : 0), "only confirmed reasons report");
            if (accepted) {
                require(sent.get(0).key().equals("89|ps3|unexpected_exit|" + bucket), "original build/route");
                String body = new String(sent.get(0).body(), StandardCharsets.UTF_8);
                require(!body.contains("123") && !body.contains("1000") && !body.contains("3000"),
                        "local PID and wall times never leave device");
            }
            PrivateDiagnostics reopened = new PrivateDiagnostics(store.preferences(), 90, URL_VALUE,
                    (uri, report) -> { throw new AssertionError("duplicate recovered report"); },
                    () -> 0, () -> 4000, 789, (pid, start, end) -> {
                        throw new AssertionError("already consumed marker queried again");
                    });
            reopened.setGameplay(false); idle(reopened);
        }
        for (String invalid : new String[]{"", "89|ps3|123|0", "89|ps3|0|1000", "89|ps3|123|-1",
                "89|ps3|123|9999999999999999999", "89|private-name|123|1000",
                "089|ps3|123|1000", "89|ps3|123|1000|extra"})
            require(PrivateDiagnosticsExitRecovery.Marker.parse(invalid) == null, "reject malformed marker");
        PrivateDiagnosticsExitRecovery.Marker valid = PrivateDiagnosticsExitRecovery.Marker.parse("89|ps3|123|1000");
        require(valid.recover((pid, start, end) -> { throw new AssertionError("reversed clock read"); }, 999) == null,
                "no backwards clock attribution");
        require(valid.recover((pid, start, end) -> { throw new IllegalStateException("OS unavailable"); }, 2000) == null,
                "unavailable history is not crash evidence");

        Store disabled = new Store(); disabled.data.put("active", "89|ps3|123|1000");
        PrivateDiagnostics off = new PrivateDiagnostics(disabled.preferences(), 90, URL_VALUE,
                (uri, report) -> { throw new AssertionError("disabled upload"); },
                () -> 0, () -> 3000, 456, (pid, start, end) -> { throw new AssertionError("disabled history read"); });
        PrivateDiagnosticsSession whileOff = off.beginSession("n64");
        off.setConsent(true); idle(off); whileOff.ready(); whileOff.close(); idle(off);
        require(disabled.pending().isEmpty() && !disabled.data.containsKey("active"), "no pre-consent session data");

        // Delayed retirement cannot erase a replacement session, even when both
        // begin at the same millisecond. There are no serialized session IDs.
        Store store = new Store(); store.data.put("enabled", true);
        PrivateDiagnostics current = new PrivateDiagnostics(store.preferences(), 90, URL_VALUE,
                (uri, report) -> PrivateDiagnosticsTransport.Result.ACCEPTED,
                () -> 0, () -> 3000, 456, (pid, start, end) -> null);
        PrivateDiagnosticsSession first = current.beginSession("ps3"), second = current.beginSession("ps3");
        idle(current); first.close(); first.close(); idle(current);
        require("90|ps3|456|3000".equals(store.data.get("active")), "late close retains new marker");
        second.close(); idle(current);
        require(!store.data.containsKey("active"), "normal close removes marker");
        PrivateDiagnosticsSession oldConsent = current.beginSession("ps3"); idle(current);
        current.setConsent(false); idle(current);
        require(!store.data.containsKey("active") && store.pending().isEmpty(), "opt out clears journal and outbox");
        current.setConsent(true); idle(current); oldConsent.ready(); oldConsent.close(); idle(current);
        require(store.pending().isEmpty(), "old session cannot inherit fresh consent");
    }
    static void outbox() throws Exception {
        Store store = new Store(); List<PrivateDiagnosticReport> sent = new ArrayList<>(); long[] clock = {1};
        PrivateDiagnostics owner = owner(store, (url, report) -> {
            sent.add(report); return PrivateDiagnosticsTransport.Result.ACCEPTED;
        }, clock);
        owner.record(report(90)); owner.setGameplay(false); idle(owner);
        require(store.pending().isEmpty() && sent.isEmpty(), "off by default");
        owner.setConsent(true); idle(owner);
        owner.setGameplay(true);
        for (int n = 0; n < 70; n++) owner.record(report(90));
        idle(owner);
        require(store.pending().split("\n").length == 64 && sent.isEmpty(), "bounded and no gameplay sends");
        owner.setGameplay(false); idle(owner);
        require(sent.size() == 8 && store.pending().split("\n").length == 56, "bounded flush");
        owner.setConsent(false); idle(owner);
        owner.setGameplay(false); idle(owner);
        require(store.pending().isEmpty() && sent.size() == 8, "opt-out erases and stops");
        owner.setConsent(true); idle(owner); owner.setGameplay(false); idle(owner);
        require(sent.size() == 8, "re-opt-in must not resurrect reports");

        Store old = new Store(); old.data.put("enabled", true);
        old.data.put("pending", "89|n64|engine_ready|ok\nPRIVATE_DEVICE\n90|nes|launch_failed|unknown\n");
        List<Integer> builds = new ArrayList<>();
        PrivateDiagnostics restored = owner(old, (url, report) -> {
            builds.add(report.build); return PrivateDiagnosticsTransport.Result.ACCEPTED;
        }, clock);
        restored.setGameplay(false); idle(restored);
        require(builds.equals(Arrays.asList(89, 90)) && old.pending().isEmpty(), "validate persistence; retain original release");

        Store retry = new Store(); retry.data.put("enabled", true); AtomicInteger attempts = new AtomicInteger();
        PrivateDiagnostics retryOwner = owner(retry, (url, report) -> {
            return attempts.incrementAndGet() == 1 ? PrivateDiagnosticsTransport.Result.RETRY
                    : PrivateDiagnosticsTransport.Result.ACCEPTED;
        }, clock);
        retryOwner.record(report(90)); idle(retryOwner); retryOwner.setGameplay(false); idle(retryOwner);
        retryOwner.setGameplay(false); idle(retryOwner);
        require(attempts.get() == 1 && !retry.pending().isEmpty(), "no retry spin");
        clock[0] += 120001;
        retryOwner.setGameplay(false); idle(retryOwner);
        require(attempts.get() == 2 && retry.pending().isEmpty(), "retained retry");

        Store disabled = new Store(); disabled.data.put("enabled", true);
        PrivateDiagnostics unavailable = new PrivateDiagnostics(disabled.preferences(), 90, null,
                (url, report) -> { throw new AssertionError("unconfigured sender called"); }, () -> 0);
        unavailable.setConsent(true); unavailable.record(report(90)); unavailable.setGameplay(false); idle(unavailable);
        require(disabled.pending().isEmpty(), "unconfigured must not collect");
    }
    static void disableDuringSend() throws Exception {
        Store store = new Store(); store.data.put("enabled", true);
        CountDownLatch sending = new CountDownLatch(1), finish = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        PrivateDiagnostics owner = owner(store, (uri, report) -> {
            calls.incrementAndGet(); sending.countDown();
            require(finish.await(5, TimeUnit.SECONDS), "test release timeout");
            return PrivateDiagnosticsTransport.Result.RETRY;
        }, new long[]{1});
        owner.record(report(90)); owner.record(report(90)); idle(owner);
        owner.setGameplay(false);
        require(sending.await(5, TimeUnit.SECONDS), "sender not entered");
        owner.setConsent(false); owner.record(report(90)); finish.countDown(); idle(owner);
        require(calls.get() == 1 && store.pending().isEmpty(), "in-flight opt-out must stop next report and erase queue");
    }
    static void transport() throws Exception {
        for (String bad : new String[]{"", "http://receiver.example.invalid/v1/report",
                "https://user:pass@receiver.example.invalid/v1/report", "https://receiver.example.invalid/v1/report?id=abc",
                "https://receiver.example.invalid/v1/report#id", "https://receiver.example.invalid:8443/v1/report",
                "https://receiver.example.invalid/log", "https://receiver.example.invalid/v1/%72eport"})
            require(PrivateDiagnosticsTransport.endpoint(bad) == null, "unsafe endpoint");
        require(PrivateDiagnosticsTransport.endpoint(URL_VALUE.toString()).equals(URL_VALUE), "valid endpoint");
        for (int status : new int[]{204, 200, 301, 302, 307, 400, 401, 403, 407, 429, 500, 503}) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            ByteArrayInputStream input = new ByteArrayInputStream(("HTTP/1.1 " + status +
                    " Test\r\nPrivate text must remain unread").getBytes(StandardCharsets.US_ASCII));
            PrivateDiagnosticsTransport.Result result = PrivateDiagnosticsTransport.exchange(
                    input, output, URL_VALUE.getHost(), report(90));
            require(result == (status == 204 ? PrivateDiagnosticsTransport.Result.ACCEPTED :
                    status == 429 || status >= 500 ? PrivateDiagnosticsTransport.Result.RETRY :
                    PrivateDiagnosticsTransport.Result.REJECTED), "response classification");
            String expected = "POST /v1/report HTTP/1.1\r\nHost: receiver.example.invalid\r\n" +
                    "Content-Type: application/json\r\nUser-Agent: EmuFusion-Diagnostics/1\r\n" +
                    "Cache-Control: no-store\r\nConnection: close\r\nContent-Length: " +
                    report(90).body().length + "\r\n\r\n" + new String(report(90).body(), StandardCharsets.UTF_8);
            require(output.toString("UTF-8").equals(expected), "only exact fixed headers and allowlisted body");
            require(input.available() == "Private text must remain unread".length(), "no response text read");
        }
        for (String malformed : new String[]{"", "HTTP/1.1 204 OK\n", "HTTP/2 204 OK\r\n",
                "HTTP/1.1 204 OK\r", "HTTP/1.1 204 OK\r\n".replace("204", "2040"),
                "HTTP/1.1 204 " + new String(new char[256]).replace('\0', 'x') + "\r\n"}) {
            try {
                PrivateDiagnosticsTransport.exchange(new ByteArrayInputStream(malformed.getBytes(StandardCharsets.US_ASCII)),
                        new ByteArrayOutputStream(), URL_VALUE.getHost(), report(90));
                throw new AssertionError("malformed response accepted");
            } catch (IOException expected) { }
        }
    }
    public static void main(String[] args) throws Exception {
        payloads(); lifecycle(); recoveredExits(); outbox(); disableDuringSend(); transport();
        System.err.println("Private diagnostics production-code checks passed; synthetic only.");
    }
}
