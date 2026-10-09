package com.thorium.preview;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.SystemClock;
import android.widget.TextView;
import java.lang.reflect.Field;
import java.net.Authenticator;
import java.net.CookieManager;
import java.net.CookieHandler;
import java.net.URI;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.SSLException;
import org.json.JSONArray;
import org.json.JSONObject;

/** Disposable simulator fixture. Never included in an EmuFusion release. */
public final class ProbeActivity extends Activity {
    private static final String[] SYSTEMS = {"switch", "wiiu", "ps3", "wii", "gamecube", "ps2",
            "psp", "dreamcast", "3ds", "psx", "nds", "n64", "snes", "nes", "gb", "gbc",
            "gba", "megadrive", "gamegear", "pcenginecd"};
    private static final URI ENDPOINT = URI.create("https://localhost/v1/report");
    private PrivateDiagnostics owner;
    private SharedPreferences prefs;
    private TextView status;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        status = new TextView(this);
        status.setTextSize(20);
        status.setPadding(32, 32, 32, 32);
        setContentView(status);
        prefs = getSharedPreferences("probe", MODE_PRIVATE);
        owner = new PrivateDiagnostics(prefs, 90, ENDPOINT,
                PrivateDiagnosticsTransport::send, SystemClock::elapsedRealtime);
        execute(getIntent());
    }

    @Override public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        execute(intent);
    }

    private void idle() throws Exception {
        Field field = PrivateDiagnostics.class.getDeclaredField("worker");
        field.setAccessible(true);
        ((ExecutorService) field.get(owner)).submit(() -> {}).get(20, TimeUnit.SECONDS);
    }

    private void execute(Intent intent) {
        final String operation = intent.getStringExtra("operation");
        status.setText("Synthetic private-report test: " + operation);
        new Thread(() -> {
            JSONObject output = new JSONObject();
            try {
                idle();
                JSONArray results = new JSONArray();
                if ("queue".equals(operation)) {
                    owner.setConsent(true);
                    owner.setGameplay(true);
                    owner.beginSession("snes").ready();
                    idle();
                } else if ("flush".equals(operation)) {
                    owner.setGameplay(false);
                    idle();
                } else if ("opt-out".equals(operation)) {
                    owner.setConsent(false);
                    idle();
                    owner.setGameplay(false);
                    idle();
                } else {
                    CookieHandler cookies = CookieHandler.getDefault();
                    try {
                        if ("cookie".equals(operation)) CookieHandler.setDefault(new CookieManager());
                        if ("auth".equals(operation)) Authenticator.setDefault(new Authenticator() {
                            @Override protected java.net.PasswordAuthentication getPasswordAuthentication() {
                                throw new AssertionError("Account authenticator must never be invoked");
                            }
                        });
                        URI target = "wrong-host".equals(operation)
                                ? URI.create("https://127.0.0.1/v1/report") : ENDPOINT;
                        for (String system : "all".equals(operation) ? SYSTEMS : new String[]{"ps3"}) {
                            try {
                                results.put(PrivateDiagnosticsTransport.send(target,
                                        PrivateDiagnosticReport.create(90, system, "engine_ready", "ok")).name());
                            } catch (SSLException expected) {
                                results.put("TLS_REJECTED");
                            }
                        }
                    } finally {
                        CookieHandler.setDefault(cookies);
                        Authenticator.setDefault(null); // This standalone synthetic process owns the test callback.
                    }
                }
                output.put("operation", operation);
                output.put("results", results);
                output.put("pending", prefs.getString("pending", ""));
                output.put("enabled", prefs.getBoolean("enabled", false));
            } catch (Throwable failure) {
                try { output.put("failureClass", failure.getClass().getName()); }
                catch (Exception ignored) { }
            }
            try (java.io.FileOutputStream file = openFileOutput("result.json", MODE_PRIVATE)) {
                file.write(output.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            } catch (Exception ignored) { }
            final String display = output.toString();
            runOnUiThread(() -> status.setText("Synthetic private-report test\n" + display));
        }, "synthetic-probe").start();
    }
}
