package com.thorium.preview;

import android.view.Surface;
import com.thorium.preview.game.FrameGenerationRenderer;
import com.thorium.preview.game.FrameGenerationRendererRegistry;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class ExperimentalGlesLibretroHostLifecycleTest {
    private static final class FakeBindings
            implements ExperimentalGlesLibretroHost.Bindings {
        final List<String> calls = new ArrayList<>();
        boolean loseNextFrame;
        int executionStatus = -1;
        int sourceTimelinePolicy = -1;
        byte[] state = new byte[] {4, 1};
        byte[] saveRam = new byte[] {7, 2};

        @Override public long create(String core, String root, String system, String save,
                                     int presentationPolicy) {
            return create(core, root, system, save, presentationPolicy,
                    ExperimentalGlesLibretroHost.SOURCE_TIMELINE_DEFAULT);
        }
        @Override public long create(String core, String root, String system, String save,
                                     int presentationPolicy, int sourcePolicy) {
            if (presentationPolicy != ExperimentalGlesLibretroHost.PRESENT_AUTO)
                throw new AssertionError("unexpected presentation policy");
            if (sourcePolicy < ExperimentalGlesLibretroHost.SOURCE_TIMELINE_DEFAULT ||
                    sourcePolicy > ExperimentalGlesLibretroHost
                            .SOURCE_TIMELINE_MUPEN_VI_ORIGIN)
                throw new AssertionError("unexpected source timeline policy");
            sourceTimelinePolicy = sourcePolicy;
            calls.add("create"); return 41L;
        }
        @Override public void loadGame(long handle, String game) { calls.add("load"); }
        @Override public void setControllerPortDevice(long handle, int port, int device) {
            calls.add("port-device:" + port + ":0x" + Integer.toHexString(device));
        }
        @Override public void reset(long handle) { calls.add("reset"); }
        @Override public void cheatReset(long handle) { calls.add("cheat-reset"); }
        @Override public void cheatSet(long handle, int index, boolean enabled, String code) {
            calls.add("cheat:" + index + ":" + enabled + ":" + code);
        }
        @Override public void setPresentationAspect(long handle, float aspect) {
            calls.add("aspect:" + aspect);
        }
        @Override public void attach(long handle, Surface surface) { calls.add("attach"); }
        @Override public void recreate(long handle, Surface surface) { calls.add("recreate"); }
        @Override public void setFgTimestamp(long handle, boolean enabled) {
            calls.add("fg-timestamp:" + enabled);
        }
        @Override public void resize(long handle) { calls.add("resize"); }
        @Override public boolean runAndPresent(long handle) {
            calls.add("run-present");
            if (loseNextFrame) {
                loseNextFrame = false;
                throw new IllegalStateException("EGL_CONTEXT_LOST");
            }
            return true;
        }
        @Override public int runAndPresentStatus(long handle) {
            return executionStatus >= 0 ? executionStatus : (runAndPresent(handle) ? 2 : 1);
        }
        @Override public int runWithoutPresentStatus(long handle) {
            calls.add("run-offscreen");
            return executionStatus;
        }
        @Override public void detach(long handle) { calls.add("detach"); }
        @Override public void setPaused(long handle, boolean paused) {
            calls.add(paused ? "pause" : "resume");
        }
        @Override public void setJoypadButton(long handle, int port, int button,
                                              boolean pressed) {
            calls.add("button:" + port + ":" + button + ":" + pressed);
        }
        @Override public void setAnalogAxis(long handle, int port, int index,
                                            int id, int value) {
            calls.add("axis:" + port + ":" + index + ":" + id + ":" + value);
        }
        @Override public void setPointer(long handle, int port, int x, int y,
                                         boolean pressed) {
            calls.add("pointer:" + port + ":" + x + ":" + y + ":" + pressed);
        }
        @Override public int[] hardwareInfo(long handle) {
            calls.add("info");
            return new int[] {1, 1, 5, 3, 2, 1, 7};
        }
        @Override public short[] drainAudio(long handle, int maxFrames) {
            calls.add("audio:" + maxFrames);
            return new short[] {11, -11};
        }
        @Override public double[] avInfo(long handle) {
            calls.add("av");
            return new double[] {60.0, 48000.0, 1.0, 480.0, 272.0};
        }
        @Override public boolean stateReady(long handle) { return true; }
        @Override public byte[] serialize(long handle) {
            calls.add("serialize");
            return Arrays.copyOf(state, state.length);
        }
        @Override public void unserialize(long handle, byte[] value) {
            calls.add("unserialize");
            state = Arrays.copyOf(value, value.length);
        }
        @Override public byte[] readSaveRam(long handle) {
            calls.add("read-save");
            return Arrays.copyOf(saveRam, saveRam.length);
        }
        @Override public void writeSaveRam(long handle, byte[] value) {
            calls.add("write-save");
            saveRam = Arrays.copyOf(value, value.length);
        }
        @Override public void destroy(long handle) { calls.add("close"); }
    }

    public static void main(String[] args) throws Exception {
        File root = Files.createTempDirectory("lucent-gles-java").toFile();
        File core = new File(root, "core.so");
        File game = new File(root, "game.iso");
        try (FileOutputStream output = new FileOutputStream(core)) { output.write(1); }
        try (FileOutputStream output = new FileOutputStream(game)) { output.write(2); }
        File system = new File(root, "system");
        File save = new File(root, "save");
        Surface surface = new Surface(true);
        FakeBindings bindings = new FakeBindings();
        ExperimentalGlesLibretroHost host = new ExperimentalGlesLibretroHost(
                core, root, system, save, bindings);
        host.loadGame(game);
        boolean invalidAspectRejected = false;
        try { host.setPresentationAspect(Float.NaN); }
        catch (IllegalArgumentException expected) { invalidAspectRejected = true; }
        check(invalidAspectRejected, "invalid display aspect was accepted");
        host.setPresentationAspect(4f / 3f);
        // Wii and GameCube run on this path; the Nunchuk device must reach the
        // core right after the load, before any frame is presented.
        host.setControllerPortDevice(0, (3 << 8) | 1);
        boolean invalidSurfaceRejected = false;
        try { host.attachSurface(new Surface(false)); }
        catch (IllegalArgumentException expected) { invalidSurfaceRejected = true; }
        check(invalidSurfaceRejected, "invalid Android Surface was accepted");
        host.attachSurface(surface);
        host.resume();
        host.setJoypadButton(0, 0, true);
        host.setAnalogAxis(0, 0, 0, 1f);
        host.setPointer(0, (short)-12345, (short)23456, true);
        check(host.runFrameAndPresent(), "initial frame did not present");
        host.surfaceResized();
        ExperimentalGlesLibretroHost.HardwareInfo info = host.hardwareInfo();
        check(info.negotiated && info.contextReady && info.majorVersion == 3 &&
                info.minorVersion == 2 && info.bottomLeftOrigin &&
                info.frameSequence == 7, "hardware info mapping mismatch");
        ExperimentalGlesLibretroHost.AvInfo av = host.avInfo();
        check(av.framesPerSecond == 60.0 && av.sampleRate == 48000.0 &&
                av.baseWidth == 480 && av.baseHeight == 272, "AV info mapping mismatch");
        check(Arrays.equals(host.drainAudio(8), new short[] {11, -11}),
                "audio drain mismatch");
        check(Arrays.equals(host.serialize(), new byte[] {4, 1}),
                "serialized state mismatch");
        host.unserialize(new byte[] {9, 3});
        check(Arrays.equals(host.serialize(), new byte[] {9, 3}),
                "state restore mismatch");
        check(Arrays.equals(host.readSaveRam(), new byte[] {7, 2}),
                "save RAM read mismatch");
        host.writeSaveRam(new byte[] {8, 5});
        check(Arrays.equals(host.readSaveRam(), new byte[] {8, 5}),
                "save RAM write mismatch");
        host.reset();
        host.applyCheats(java.util.Arrays.asList("AAAA-BBBB", "1111:22"));
        host.pause();
        bindings.loseNextFrame = true;
        boolean contextLost = false;
        try { host.runFrameAndPresent(); }
        catch (IllegalStateException expected) {
            contextLost = expected.getMessage().contains("EGL_CONTEXT_LOST");
        }
        check(contextLost, "context-loss signal was swallowed");
        host.recreateSurface(surface);
        host.resume();
        check(host.runFrameAndPresent(), "recreated context did not present");
        host.pause();
        host.detachSurface();
        host.close();
        host.close();
        check(bindings.calls.equals(Arrays.asList(
                "create", "load", "aspect:" + (4f / 3f),
                "port-device:0:0x301", "attach", "fg-timestamp:false", "resume",
                "button:0:0:true",
                "axis:0:0:0:32767", "pointer:0:-12345:23456:true",
                "run-present", "resize", "info",
                "av", "audio:8", "serialize", "unserialize", "serialize",
                "read-save", "write-save", "read-save", "reset",
                "cheat-reset", "cheat:0:true:AAAA-BBBB", "cheat:1:true:1111:22",
                "pause", "run-present", "recreate", "fg-timestamp:false", "resume", "run-present",
                "pause", "detach", "close")),
                "lifecycle order mismatch: " + bindings.calls);
        boolean rejectedAfterClose = false;
        try { host.resume(); }
        catch (IllegalStateException expected) { rejectedAfterClose = true; }
        check(rejectedAfterClose, "closed qualification host remained usable");
        boolean resetRejectedAfterClose = false;
        try { host.reset(); }
        catch (IllegalStateException expected) { resetRejectedAfterClose = true; }
        check(resetRejectedAfterClose, "closed host accepted a reset");
        boolean portRejectedAfterClose = false;
        try { host.setControllerPortDevice(0, 1); }
        catch (IllegalStateException expected) { portRejectedAfterClose = true; }
        check(portRejectedAfterClose, "closed host accepted a port device");
        FakeBindings sourceBindings = new FakeBindings();
        ExperimentalGlesLibretroHost sourceHost = new ExperimentalGlesLibretroHost(
                core, root, system, save,
                ExperimentalGlesLibretroHost.PRESENT_AUTO,
                ExperimentalGlesLibretroHost.SOURCE_TIMELINE_MUPEN_VI_ORIGIN,
                sourceBindings);
        check(sourceBindings.sourceTimelinePolicy ==
                        ExperimentalGlesLibretroHost.SOURCE_TIMELINE_MUPEN_VI_ORIGIN,
                "Mupen source timeline policy did not reach native bindings");
        // Exercise the real identity registry, not a stubbed ownership answer.
        FrameGenerationRenderer renderer = (FrameGenerationRenderer)
                java.lang.reflect.Proxy.newProxyInstance(
                        FrameGenerationRenderer.class.getClassLoader(),
                        new Class<?>[] {FrameGenerationRenderer.class},
                        (proxy, method, values) -> {
                            if (method.getName().equals("inputSurface")) return surface;
                            throw new AssertionError("unexpected renderer call " + method);
                        });
        java.lang.reflect.Method register = FrameGenerationRendererRegistry.class
                .getDeclaredMethod("register", FrameGenerationRenderer.class);
        java.lang.reflect.Method unregister = FrameGenerationRendererRegistry.class
                .getDeclaredMethod("unregister", Surface.class, FrameGenerationRenderer.class);
        register.setAccessible(true);
        unregister.setAccessible(true);
        register.invoke(null, renderer);
        try {
            sourceBindings.calls.clear();
            sourceHost.attachSurface(surface);
            sourceHost.recreateSurface(new Surface(true));
            sourceHost.recreateSurface(surface);
            check(sourceBindings.calls.equals(Arrays.asList(
                    "attach", "fg-timestamp:true", "recreate", "fg-timestamp:false",
                    "recreate", "fg-timestamp:true")),
                    "FG ownership/recreate ordering mismatch: " + sourceBindings.calls);
        } finally {
            unregister.invoke(null, surface, renderer);
        }
        sourceBindings.calls.clear();
        sourceHost.recreateSurface(surface);
        check(sourceBindings.calls.equals(Arrays.asList("recreate", "fg-timestamp:false")),
                "unregistered former FG input retained timestamp ownership");
        sourceBindings.executionStatus = 0;
        check(!sourceHost.runFrameAndPresent() && !sourceHost.didRunFrame(),
                "warmup was counted as a guest frame");
        sourceBindings.executionStatus = 1;
        check(!sourceHost.runFrameAndPresent() && sourceHost.didRunFrame(),
                "a guest step without new video was confused with warmup");
        sourceBindings.executionStatus = 2;
        check(sourceHost.runFrameAndPresent() && sourceHost.didRunFrame(),
                "real presentation lost its guest execution status");
        sourceBindings.executionStatus = 0;
        sourceHost.runFrameWithoutPresent();
        check(!sourceHost.didRunFrame(), "offscreen warmup counted as guest work");
        sourceBindings.executionStatus = 1;
        sourceHost.runFrameWithoutPresent();
        check(sourceHost.didRunFrame(), "offscreen guest work lost its audio eligibility");
        sourceBindings.executionStatus = 2;
        boolean invalidOffscreenStatus = false;
        try { sourceHost.runFrameWithoutPresent(); }
        catch (IllegalStateException expected) { invalidOffscreenStatus = true; }
        check(invalidOffscreenStatus && !sourceHost.didRunFrame(),
                "offscreen API accepted a presentation claim");
        sourceHost.close();
        boolean closedOffscreenRejected = false;
        try { sourceHost.runFrameWithoutPresent(); }
        catch (IllegalStateException expected) { closedOffscreenRejected = true; }
        check(closedOffscreenRejected, "offscreen step escaped closed-host guard");
        boolean invalidSourcePolicyRejected = false;
        try {
            new ExperimentalGlesLibretroHost(core, root, system, save,
                    ExperimentalGlesLibretroHost.PRESENT_AUTO, 4, sourceBindings);
        } catch (IllegalArgumentException expected) {
            invalidSourcePolicyRejected = true;
        }
        check(invalidSourcePolicyRejected, "unknown source timeline policy was accepted");
        deleteTree(root);
        System.out.println("ExperimentalGlesLibretroHost lifecycle probe passed");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void deleteTree(File file) {
        File[] children = file.listFiles();
        if (children != null) for (File child : children) deleteTree(child);
        if (!file.delete()) file.deleteOnExit();
    }
}
