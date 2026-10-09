package com.thorium.preview;

import android.view.Surface;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class ExperimentalGlesRenderLoopTest {
    private static class FakeHost implements ExperimentalGlesRenderLoop.Host {
        final List<String> calls = Collections.synchronizedList(new ArrayList<>());
        Thread owner;
        int frames;
        int generation;
        byte[] state = new byte[] {1, 2, 3};
        byte[] saveRam = new byte[] {4, 5};

        protected void call(String value) {
            if (owner == null) owner = Thread.currentThread();
            if (owner != Thread.currentThread())
                throw new AssertionError("GLES call escaped dedicated render thread");
            calls.add(value);
        }

        @Override public void attach(Surface surface) { call("attach"); }
        @Override public void recreate(Surface surface) {
            call("recreate"); generation++;
        }
        @Override public void resize(Surface surface) { call("resize"); }
        @Override public boolean runAndPresent() {
            call("run-present");
            frames++;
            if (generation == 0 && frames == 2)
                throw new IllegalStateException("Android EGL context lost during swap");
            return true;
        }
        @Override public void detach() { call("detach"); }
        @Override public void attachSecondary(Surface surface) {
            call("attach-secondary");
        }
        @Override public void detachSecondary() { call("detach-secondary"); }
        @Override public void pause() { call("pause"); }
        @Override public void resume() { call("resume"); }
        @Override public void setJoypadButton(int port, int button, boolean pressed) {
            call("button");
        }
        @Override public void setAnalogAxis(int port, int index, int id, float value) {
            call("axis");
        }
        @Override public void setPointer(int port, short x, short y, boolean pressed) {
            call("pointer");
        }
        @Override public void setControllerPortDevice(int port, int device) {
            call("port-device:" + port + ":0x" + Integer.toHexString(device));
        }
        @Override public void reset() { call("reset"); }
        @Override public void applyCheats(java.util.List<String> codes) {
            call("cheats:" + codes.size());
        }
        @Override public short[] drainAudio(int maxFrames) {
            call("audio"); return new short[] {7, -7};
        }
        @Override public ExperimentalGlesLibretroHost.AvInfo avInfo() {
            call("av");
            return new ExperimentalGlesLibretroHost.AvInfo(
                    new double[] {60.0, 48000.0, 1.0, 480.0, 272.0});
        }
        @Override public void setPresentationAspect(float aspect) {
            call("aspect:" + aspect);
        }
        @Override public void setSecondaryPresentationRotation(int clockwiseDegrees) {
            call("secondary-rotation:" + clockwiseDegrees);
        }
        @Override public boolean stateReady() { call("state-ready"); return true; }
        @Override public byte[] serialize() {
            call("serialize"); return java.util.Arrays.copyOf(state, state.length);
        }
        @Override public void unserialize(byte[] value) {
            call("unserialize"); state = java.util.Arrays.copyOf(value, value.length);
        }
        @Override public byte[] readSaveRam() {
            call("read-save"); return java.util.Arrays.copyOf(saveRam, saveRam.length);
        }
        @Override public void writeSaveRam(byte[] value) {
            call("write-save"); saveRam = java.util.Arrays.copyOf(value, value.length);
        }
        @Override public void close() { call("close"); }
    }

    private static final class SlowHost extends FakeHost {
        final CountDownLatch fourFrames = new CountDownLatch(1);
        final List<Long> completions = Collections.synchronizedList(new ArrayList<>());

        @Override public boolean runAndPresent() {
            call("slow-run-present");
            try { Thread.sleep(50L); }
            catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(interrupted);
            }
            frames++;
            completions.add(System.nanoTime());
            if (frames >= 4) fourFrames.countDown();
            return true;
        }
    }

    private static void checkTransientStallPreservesClock() throws Exception {
        long deadline = 1_000_000_000L;
        check(!ExperimentalGlesRenderLoop.shouldRebaseFrameClock(
                deadline + 250_000_000L, deadline, 16_666_667L), "bounded debt discarded");
        check(ExperimentalGlesRenderLoop.shouldRebaseFrameClock(
                deadline + 250_000_001L, deadline, 16_666_667L), "long freeze retained stale debt");
        check(ExperimentalGlesRenderLoop.shouldRebaseFrameClock(deadline, 0L, 16_666_667L),
                "uninitialized clock did not start");
        check(!ExperimentalGlesRenderLoop.shouldRebaseFrameClock(deadline - 1L, deadline, 16_666_667L),
                "future deadline discarded");
        check(!ExperimentalGlesRenderLoop.shouldRebaseFrameClock(
                deadline + 400_000_000L, deadline, 100_000_000L), "slow-core four-frame allowance changed");
        CountDownLatch ready = new CountDownLatch(1);
        CountDownLatch complete = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        List<Long> completions = Collections.synchronizedList(new ArrayList<>());
        FakeHost host = new FakeHost() {
            @Override public boolean supportsPresentationRecovery() { return true; }
            @Override public void runWithoutPresent() { runAndPresent(); }
            @Override public boolean runAndPresent() {
                call("transient-stall");
                try { Thread.sleep(++frames == 2 ? 140L : 1L); }
                catch (InterruptedException failure) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException(failure);
                }
                completions.add(System.nanoTime());
                if (frames == 16) complete.countDown();
                return true;
            }
        };
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(() -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {}
                    @Override public void onContextLost() { error.set(new AssertionError("context lost")); }
                    @Override public void onError(Throwable failure) { error.set(failure); }
                }, 20_000_000L);
        try {
            check(ready.await(2, TimeUnit.SECONDS), "transient-stall host not ready");
            loop.attachSurface(new Surface(true));
            loop.resume();
            check(complete.await(2, TimeUnit.SECONDS), "transient-stall run did not finish");
        } finally { loop.close(); }
        check(error.get() == null, "transient-stall run failed: " + error.get());
        long elapsedMs = TimeUnit.NANOSECONDS.toMillis(completions.get(15) - completions.get(0));
        // 15 intervals should still occupy about300ms. The old four-frame
        // rebase permanently discards120ms after the isolated140ms call.
        check(elapsedMs < 370L, "transient work stall permanently lost guest time: " + elapsedMs);
    }

    private static void checkClockDebtWithoutSkippingPresentation() throws Exception {
        check(ExperimentalGlesRenderLoop.retainsVulkanFrameDebt("liblucent_core_armsx2.so"),
                "4K PS2 clock recovery missing");
        check(ExperimentalGlesRenderLoop.retainsVulkanFrameDebt("liblucent_core_armsx2_16k.so"),
                "16K PS2 clock recovery missing");
        for (String name : new String[] {null, "", "liblucent_core_dolphin.so",
                "liblucent_core_play.so", "liblucent_core_armsx2_other.so"})
            check(!ExperimentalGlesRenderLoop.retainsVulkanFrameDebt(name),
                    "clock recovery escaped PS2 qualification: " + name);
        CountDownLatch ready = new CountDownLatch(1), complete = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        List<Long> completions = Collections.synchronizedList(new ArrayList<>());
        int[] callbacks = {0};
        FakeHost host = new FakeHost() {
            @Override public boolean retainsFrameDebt() { return true; }
            @Override public void runWithoutPresent() {
                throw new AssertionError("Vulkan clock recovery must not skip presentation");
            }
            @Override public boolean runAndPresent() {
                call("present-with-clock-debt");
                try { Thread.sleep(++frames == 2 ? 140L : 1L); }
                catch (InterruptedException failure) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException(failure);
                }
                completions.add(System.nanoTime());
                return true;
            }
        };
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(() -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {
                        if (++callbacks[0] == 16) complete.countDown();
                    }
                    @Override public void onFrameExecutedWithoutPresentation() {
                        error.set(new AssertionError("audio-only step without Vulkan ownership"));
                    }
                    @Override public void onContextLost() { error.set(new AssertionError("context lost")); }
                    @Override public void onError(Throwable failure) { error.set(failure); }
                }, 20_000_000L);
        try {
            check(ready.await(2, TimeUnit.SECONDS), "clock-debt host not ready");
            loop.attachSurface(new Surface(true));
            loop.resume();
            check(complete.await(2, TimeUnit.SECONDS), "clock-debt run did not finish");
        } finally { loop.close(); }
        check(error.get() == null, "clock-debt run failed: " + error.get());
        check(callbacks[0] == host.frames, "presented-frame/audio callback lost or duplicated");
        long elapsedMs = TimeUnit.NANOSECONDS.toMillis(completions.get(15) - completions.get(0));
        check(elapsedMs < 370L, "clock debt discarded without offscreen recovery: " + elapsedMs);
    }

    private static void checkRecoveryDoesNotWaitForEveryStaleSwap() throws Exception {
        long[] elapsed = new long[3];
        for (int mode = 0; mode < 3; mode++) {
            final boolean recovery = mode != 0;
            final boolean frameGenerationInput = mode == 2;
            CountDownLatch ready = new CountDownLatch(1), complete = new CountDownLatch(1);
            AtomicReference<Throwable> error = new AtomicReference<>();
            List<Long> completions = Collections.synchronizedList(new ArrayList<>());
            int[] presented = {0}, audioOnly = {0}, skipped = {0}, streak = {0}, maxStreak = {0};
            FakeHost host = new FakeHost() {
                @Override public boolean supportsPresentationRecovery() { return recovery; }
                private void step(boolean swap) {
                    call(swap ? "swap" : "offscreen");
                    frames++;
                    if (swap) streak[0] = 0;
                    else { skipped[0]++; maxStreak[0] = Math.max(maxStreak[0], ++streak[0]); }
                    try { Thread.sleep(frames == 2 ? 140L : swap ? 20L : 1L); }
                    catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new RuntimeException(e); }
                    completions.add(System.nanoTime());
                    if (frames == 16) complete.countDown();
                }
                @Override public boolean runAndPresent() { step(true); return true; }
                @Override public void runWithoutPresent() { step(false); }
            };
            ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(() -> host,
                    new ExperimentalGlesRenderLoop.Listener() {
                        @Override public void onReady() { ready.countDown(); }
                        @Override public void onFramePresented() { presented[0]++; }
                        @Override public void onFrameExecutedWithoutPresentation() { audioOnly[0]++; }
                        @Override public void onContextLost() { error.set(new AssertionError("context lost")); }
                        @Override public void onError(Throwable t) { error.set(t); }
                    }, 20_000_000L);
            Surface gameSurface = new Surface(true);
            com.thorium.preview.game.FrameGenerationRenderer renderer =
                    (com.thorium.preview.game.FrameGenerationRenderer) java.lang.reflect.Proxy.newProxyInstance(
                            ExperimentalGlesRenderLoopTest.class.getClassLoader(),
                            new Class<?>[] {com.thorium.preview.game.FrameGenerationRenderer.class},
                            (proxy, method, arguments) -> method.getName().equals("inputSurface") ? gameSurface : null);
            java.lang.reflect.Method register = com.thorium.preview.game.FrameGenerationRendererRegistry.class
                    .getDeclaredMethod("register", com.thorium.preview.game.FrameGenerationRenderer.class);
            java.lang.reflect.Method unregister = com.thorium.preview.game.FrameGenerationRendererRegistry.class
                    .getDeclaredMethod("unregister", Surface.class, com.thorium.preview.game.FrameGenerationRenderer.class);
            register.setAccessible(true);
            unregister.setAccessible(true);
            if (frameGenerationInput) register.invoke(null, renderer);
            try {
                check(ready.await(2, TimeUnit.SECONDS), "recovery host not ready");
                loop.attachSurface(gameSurface);
                loop.resume();
                check(complete.await(2, TimeUnit.SECONDS), "recovery host did not complete");
            } finally {
                loop.close();
                if (frameGenerationInput) unregister.invoke(null, gameSurface, renderer);
            }
            check(error.get() == null, "recovery failure: " + error.get());
            check(presented[0] + audioOnly[0] == host.frames, "guest audio callback lost or duplicated");
            check(audioOnly[0] == skipped[0], "offscreen frame falsely counted as displayed");
            check(maxStreak[0] <= 4, "unbounded catchup starved presentation");
            check(recovery && !frameGenerationInput ? skipped[0] > 0 : skipped[0] == 0,
                    "recovery escaped opt-in or discarded FG inputs");
            elapsed[mode] = TimeUnit.NANOSECONDS.toMillis(completions.get(15) - completions.get(0));
        }
        check(elapsed[1] + 60L < elapsed[0], "recovery still blocked by stale swaps: " + elapsed[0] + "/" + elapsed[1]);
    }

    private static void checkWarmupIsNotWorkThroughput() throws Exception {
        boolean[] executed = {true};
        FakeHost host = new FakeHost() {
            @Override public boolean didRunFrame() { return executed[0]; }
        };
        CountDownLatch ready = new CountDownLatch(1);
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(() -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() { throw new AssertionError("unexpected swap"); }
                    @Override public void onContextLost() { throw new AssertionError("unexpected loss"); }
                    @Override public void onError(Throwable failure) { throw new AssertionError(failure); }
                }, 0L);
        check(ready.await(2, TimeUnit.SECONDS), "work metric host not ready");
        // No attached surface/resume, hence no concurrent frame execution.
        java.lang.reflect.Method record = ExperimentalGlesRenderLoop.class.getDeclaredMethod(
                "recordFrameWork", long.class, long.class);
        java.lang.reflect.Field count = ExperimentalGlesRenderLoop.class.getDeclaredField("workSecondFrames");
        record.setAccessible(true);
        count.setAccessible(true);
        try {
            record.invoke(loop, 1_000_000_000L, 1_001_000_000L);
            check(count.getInt(loop) == 1, "guest work was not counted");
            executed[0] = false;
            record.invoke(loop, 2_000_000_000L, 2_250_000_000L);
            check(count.getInt(loop) == 0 && loop.achievedCoreHz() == 0,
                    "warmup contaminated guest throughput");
            executed[0] = true;
            record.invoke(loop, 3_000_000_000L, 3_001_000_000L);
            check(count.getInt(loop) == 1, "guest measurement did not restart after warmup");
        } finally { loop.close(); }
    }

    private static int count(List<String> calls, String value) {
        int total = 0;
        synchronized (calls) {
            for (String entry : calls) {
                if (entry.equals(value)) total++;
            }
        }
        return total;
    }

    /**
     * The r23/r24 F-Zero crash: a duplicate attach notification for the same
     * live Surface (the deferred engine-ready attach racing the ordinary
     * surface callback) reached host.recreate and double-reset Mupen64Plus-
     * Next into a SIGSEGV before gameplay. The loop must absorb the duplicate
     * without any destructive host transition.
     */
    private static void checkDuplicateAttachIsAbsorbed() throws Exception {
        FakeHost host = new FakeHost();
        CountDownLatch ready = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(
                () -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {}
                    @Override public void onContextLost() {}
                    @Override public void onError(Throwable failure) {
                        error.compareAndSet(null, failure);
                    }
                }, 1_000_000L);
        check(ready.await(2, TimeUnit.SECONDS), "duplicate-attach loop did not initialize");
        Surface live = new Surface(true);
        loop.attachSurface(live);
        loop.pauseAndWait();
        check(count(host.calls, "attach") == 1 && count(host.calls, "recreate") == 0,
                "first attach did not take the plain attach path: " + host.calls);
        loop.attachSurface(live);
        loop.pauseAndWait();
        check(count(host.calls, "attach") == 1 && count(host.calls, "recreate") == 0,
                "duplicate same-surface attach recreated the context: " + host.calls);
        loop.detachSurface();
        loop.close();
        check(error.get() == null, "duplicate-attach loop errored: " + error.get());
    }

    /** A different Surface object is a genuine replacement: exactly one
     *  ordered destroy/recreate transition may run. */
    private static void checkDistinctReplacementRecreatesOnce() throws Exception {
        FakeHost host = new FakeHost();
        CountDownLatch ready = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(
                () -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {}
                    @Override public void onContextLost() {}
                    @Override public void onError(Throwable failure) {
                        error.compareAndSet(null, failure);
                    }
                }, 1_000_000L);
        check(ready.await(2, TimeUnit.SECONDS), "replacement loop did not initialize");
        Surface first = new Surface(true);
        Surface second = new Surface(true);
        loop.attachSurface(first);
        loop.pauseAndWait();
        loop.attachSurface(second);
        loop.pauseAndWait();
        check(count(host.calls, "attach") == 1 && count(host.calls, "recreate") == 1,
                "surface replacement did not recreate exactly once: " + host.calls);
        check(host.calls.indexOf("recreate") > host.calls.indexOf("attach"),
                "replacement recreate preceded the original attach");
        loop.detachSurface();
        loop.close();
        check(error.get() == null, "replacement loop errored: " + error.get());
    }

    /** A resize of the live Surface must never pay the destructive price;
     *  a resize carrying new identity is a replacement instead. The Vulkan
     *  dual-screen route additionally requires the secondary surface to be
     *  torn down and rebuilt around any primary refresh. */
    private static void checkResizeNeverDestroysTheLiveSurface() throws Exception {
        FakeHost host = new FakeHost();
        CountDownLatch ready = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(
                () -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {}
                    @Override public void onContextLost() {}
                    @Override public void onError(Throwable failure) {
                        error.compareAndSet(null, failure);
                    }
                }, 1_000_000L);
        check(ready.await(2, TimeUnit.SECONDS), "resize loop did not initialize");
        Surface live = new Surface(true);
        loop.resizeSurface(live);
        loop.pauseAndWait();
        check(count(host.calls, "resize") == 0 && count(host.calls, "attach") == 0 &&
                count(host.calls, "recreate") == 0,
                "resize before any attach touched the host: " + host.calls);
        loop.attachSurface(live);
        loop.pauseAndWait();
        Surface lower = new Surface(true);
        loop.attachSecondarySurface(lower);
        loop.pauseAndWait();
        loop.resizeSurface(live);
        loop.pauseAndWait();
        check(count(host.calls, "resize") == 1 && count(host.calls, "recreate") == 0 &&
                count(host.calls, "detach") == 0,
                "same-surface resize performed a destructive transition: " + host.calls);
        check(count(host.calls, "detach-secondary") == 1 &&
                count(host.calls, "attach-secondary") == 2 &&
                host.calls.lastIndexOf("detach-secondary") <
                        host.calls.indexOf("resize") &&
                host.calls.lastIndexOf("attach-secondary") >
                        host.calls.lastIndexOf("detach-secondary"),
                "in-place resize stranded or duplicated the secondary surface: "
                        + host.calls);
        Surface replacement = new Surface(true);
        loop.resizeSurface(replacement);
        loop.pauseAndWait();
        check(count(host.calls, "resize") == 1 && count(host.calls, "recreate") == 1,
                "resize under new Surface identity did not recreate: " + host.calls);
        loop.detachSurface();
        loop.close();
        check(error.get() == null, "resize loop errored: " + error.get());
    }

    private static void checkClockRequestsCannotSlowTheGuest() throws Exception {
        List<Double> appliedClocks = Collections.synchronizedList(new ArrayList<>());
        FakeHost host = new FakeHost() {
            @Override public void setSynchronizedVideoRate(double declared, double target) {
                call("clock");
                check(declared == 60.0, "clock correction lost original AV timing");
                appliedClocks.add(target);
            }
        };
        CountDownLatch ready = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(
                () -> host, new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {}
                    @Override public void onContextLost() {}
                    @Override public void onError(Throwable failure) { error.set(failure); }
                }, 16_666_667L, true);
        try {
            check(ready.await(2, TimeUnit.SECONDS), "clock test loop did not initialize");
            check(loop.setPacedVideoHz(60.2), "small declared-clock trim was rejected");
            loop.pauseAndWait();
            for (double invalid : new double[] {20, 30, 40, 50, 59, 61,
                    -1, 0.8, Double.NaN, Double.POSITIVE_INFINITY}) {
                check(!loop.setPacedVideoHz(invalid), "unsafe clock accepted: " + invalid);
                check(loop.pacedVideoHz() == 60.2, "rejected clock mutated the active trim");
            }
            loop.pauseAndWait();
            check(appliedClocks.size() == 2, "invalid requests reached the native audio/clock hook");
            check(loop.setPacedVideoHz(0), "explicit synchronized-clock restore was rejected");
            loop.pauseAndWait();
            check(loop.pacedVideoHz() == 0, "restore retained an explicit trim");
            check(appliedClocks.size() == 3 && appliedClocks.get(0) == 60.0 &&
                    appliedClocks.get(1) == 60.2 && appliedClocks.get(2) == 60.0,
                    "wrong synchronized clock sequence: " + appliedClocks);
            check(error.get() == null, "clock test render failure: " + error.get());
        } finally {
            loop.close();
        }
    }

    private static ExperimentalGlesRenderLoop checkpointLoop(
            FakeHost host, AtomicReference<Throwable> error) throws Exception {
        CountDownLatch ready = new CountDownLatch(1);
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(
                () -> host, new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {}
                    @Override public void onContextLost() {}
                    @Override public void onError(Throwable failure) {
                        error.compareAndSet(null, failure);
                    }
                }, 1_000_000L);
        check(ready.await(2, TimeUnit.SECONDS), "checkpoint loop did not initialize");
        return loop;
    }

    /** The disk worker cannot delay capture until after onPause's direct detach. */
    private static void checkBackgroundCapturePrecedesDetach() throws Exception {
        FakeHost host = new FakeHost();
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = checkpointLoop(host, error);
        ExecutorService lifecycle = Executors.newSingleThreadExecutor();
        CountDownLatch releaseDiskWorker = new CountDownLatch(1);
        try {
            lifecycle.execute(() -> {
                try { releaseDiskWorker.await(); }
                catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
            });
            loop.attachSurface(new Surface(true));
            Future<ExperimentalGlesRenderLoop.PausedState> capture =
                    loop.pauseAndCaptureState(true);
            Future<ExperimentalGlesRenderLoop.PausedState> publication =
                    lifecycle.submit(() -> capture.get(2, TimeUnit.SECONDS));
            check(loop.detachSurfaceAndWait(), "ordinary checkpoint detach timed out");
            check(!publication.isDone(), "disk worker was not delayed");
            check(count(host.calls, "serialize") == 1 &&
                            host.calls.indexOf("serialize") < host.calls.indexOf("detach"),
                    "deferred disk work allowed context destruction before capture: " + host.calls);
            check(loop.detachSurfaceAndWait() && count(host.calls, "detach") == 1,
                    "duplicate destroy callback repeated native detach");
            int nativeCallsBeforeCommit = host.calls.size();
            releaseDiskWorker.countDown();
            ExperimentalGlesRenderLoop.PausedState snapshot = publication.get(2, TimeUnit.SECONDS);
            check(java.util.Arrays.equals(snapshot.state, host.state) &&
                            java.util.Arrays.equals(snapshot.saveRam, host.saveRam) &&
                            snapshot.stateFailure == null,
                    "background capture lost state or ordinary save RAM");
            check(host.calls.size() == nativeCallsBeforeCommit,
                    "publication called the detached core");
            // A wake creates a new context; the captured state is still usable.
            loop.attachSurface(new Surface(true));
            loop.unserialize(snapshot.state);
            check(loop.pauseAndCaptureState(true).get(2, TimeUnit.SECONDS).state != null,
                    "wake did not permit a fresh checkpoint");
        } finally {
            releaseDiskWorker.countDown();
            lifecycle.shutdownNow();
            loop.close();
        }
        check(error.get() == null, "background capture raised renderer error: " + error.get());
    }

    private static void checkSlowBackgroundCaptureKeepsDetachBound() throws Exception {
        CountDownLatch captureStarted = new CountDownLatch(1);
        CountDownLatch releaseCapture = new CountDownLatch(1);
        FakeHost host = new FakeHost() {
            @Override public byte[] serialize() {
                call("serialize-start");
                captureStarted.countDown();
                try {
                    if (!releaseCapture.await(2, TimeUnit.SECONDS))
                        throw new AssertionError("slow capture was not released");
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException(interrupted);
                }
                call("serialize-end");
                return state;
            }
        };
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = checkpointLoop(host, error);
        try {
            loop.attachSurface(new Surface(true));
            Future<ExperimentalGlesRenderLoop.PausedState> capture =
                    loop.pauseAndCaptureState(true);
            check(captureStarted.await(2, TimeUnit.SECONDS), "capture was not queued immediately");
            long started = System.nanoTime();
            check(!loop.detachSurfaceAndWait(), "blocked capture bypassed the UI detach bound");
            long elapsedMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
            check(elapsedMillis < 1000L, "checkpoint extended the UI wait: " + elapsedMillis);
            check(!capture.isDone() && !host.calls.contains("detach"),
                    "detach overtook an in-flight capture");
            releaseCapture.countDown();
            check(capture.get(2, TimeUnit.SECONDS).state != null, "slow capture lost its bytes");
            loop.pauseAndWait(); // Drain the already-queued asynchronous detach.
            check(host.calls.indexOf("serialize-end") < host.calls.indexOf("detach"),
                    "bounded detach did not retain render-owner ordering");
        } finally {
            releaseCapture.countDown();
            loop.close();
        }
        check(error.get() == null, "slow capture raised renderer error: " + error.get());
    }

    private static void checkUnavailableAndFailedBackgroundCapture() throws Exception {
        FakeHost host = new FakeHost() {
            @Override public byte[] serialize() {
                call("serialize-failed");
                throw new IllegalStateException("checkpoint rejected by core");
            }
        };
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = checkpointLoop(host, error);
        try {
            check(loop.pauseAndCaptureState(true).get(2, TimeUnit.SECONDS) == null &&
                            !host.calls.contains("read-save") && !host.calls.contains("serialize-failed"),
                    "unattached checkpoint accessed core state");
            loop.attachSurface(new Surface(true));
            ExperimentalGlesRenderLoop.PausedState ordinary =
                    loop.pauseAndCaptureState(false).get(2, TimeUnit.SECONDS);
            check(ordinary.state == null && ordinary.stateFailure == null &&
                            java.util.Arrays.equals(ordinary.saveRam, host.saveRam) &&
                            !host.calls.contains("serialize-failed"),
                    "quarantined runtime state prevented SRAM or invoked serialization");
            ExperimentalGlesRenderLoop.PausedState failed =
                    loop.pauseAndCaptureState(true).get(2, TimeUnit.SECONDS);
            check(failed.state == null && failed.stateFailure instanceof IllegalStateException &&
                            java.util.Arrays.equals(failed.saveRam, host.saveRam),
                    "failed runtime capture discarded ordinary SRAM or supplied bogus state");
            loop.detachSurfaceAndWait();
            check(loop.pauseAndCaptureState(true).get(2, TimeUnit.SECONDS) == null &&
                            count(host.calls, "serialize-failed") == 1,
                    "late background callback serialized after context destruction");
        } finally {
            loop.close();
        }
        check(error.get() == null, "benign checkpoint failure stopped renderer: " + error.get());
    }

    private static void checkCloseAcknowledgementSurvivesTimeoutAndInterruption() throws Exception {
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch allowClose = new CountDownLatch(1);
        CountDownLatch callbacks = new CountDownLatch(2);
        AtomicReference<Throwable> error = new AtomicReference<>();
        AtomicReference<Throwable> ownerInterrupted = new AtomicReference<>();
        FakeHost host = new FakeHost() {
            @Override public void close() {
                call("close-enter");
                entered.countDown();
                try { allowClose.await(); }
                catch (InterruptedException failure) {
                    ownerInterrupted.set(failure);
                    throw new IllegalStateException(failure);
                }
                call("close-return");
            }
        };
        ExperimentalGlesRenderLoop loop = checkpointLoop(host, error);
        try {
            loop.closeWhenComplete(callbacks::countDown);
            check(entered.await(2, TimeUnit.SECONDS), "native close did not begin");
            for (int attempt = 0; attempt < 2; attempt++) {
                boolean timedOut = false;
                try { loop.close(20, TimeUnit.MILLISECONDS); }
                catch (IllegalStateException expected) {
                    timedOut = expected.getCause() instanceof java.util.concurrent.TimeoutException;
                }
                check(timedOut, "repeated close treated request as teardown completion");
            }
            loop.closeWhenComplete(callbacks::countDown);
            check(callbacks.getCount() == 2 && ownerInterrupted.get() == null,
                    "timeout acknowledged or interrupted native close");
            CountDownLatch waiterStarted = new CountDownLatch(1);
            AtomicReference<Throwable> waiterFailure = new AtomicReference<>();
            Thread waiter = new Thread(() -> {
                waiterStarted.countDown();
                try { loop.close(); }
                catch (IllegalStateException expected) {
                    if (!(expected.getCause() instanceof InterruptedException) ||
                            !Thread.currentThread().isInterrupted()) waiterFailure.set(expected);
                }
            });
            waiter.start();
            check(waiterStarted.await(2, TimeUnit.SECONDS), "close waiter did not start");
            waiter.interrupt();
            waiter.join(2000);
            check(!waiter.isAlive() && waiterFailure.get() == null &&
                            ownerInterrupted.get() == null && callbacks.getCount() == 2,
                    "interrupted waiter completed or interrupted native teardown");
            allowClose.countDown();
            check(callbacks.await(2, TimeUnit.SECONDS), "actual native return did not acknowledge close");
            loop.close();
            CountDownLatch late = new CountDownLatch(1);
            loop.closeWhenComplete(late::countDown);
            check(late.getCount() == 0 && count(host.calls, "close-enter") == 1 &&
                            count(host.calls, "close-return") == 1,
                    "close was duplicated or late acknowledgement was lost");
        } finally {
            allowClose.countDown();
            loop.close();
        }
        check(error.get() == null, "close wait damaged renderer: " + error.get());
    }

    private static void checkFailedNativeCloseNeverAcknowledgesSuccess() throws Exception {
        AtomicReference<Throwable> error = new AtomicReference<>();
        FakeHost host = new FakeHost() {
            @Override public void close() {
                call("close-failed");
                throw new IllegalStateException("native close rejected");
            }
        };
        ExperimentalGlesRenderLoop loop = checkpointLoop(host, error);
        CountDownLatch callbacks = new CountDownLatch(2);
        loop.closeWhenComplete(callbacks::countDown);
        for (int attempt = 0; attempt < 2; attempt++) {
            boolean failed = false;
            try { loop.close(); }
            catch (IllegalStateException expected) { failed = true; }
            check(failed, "failed native close returned success");
        }
        loop.closeWhenComplete(callbacks::countDown);
        check(callbacks.getCount() == 2 && count(host.calls, "close-failed") == 1,
                "failed close acknowledged success or retried native destruction");
    }

    private static void checkRestoreMigrationIsOneAcknowledgedOperation() throws Exception {
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch allowMigration = new CountDownLatch(1);
        FakeHost host = new FakeHost() {
            @Override public void recreate(Surface surface) {
                call("migration-enter");
                entered.countDown();
                try { check(allowMigration.await(2, TimeUnit.SECONDS), "migration gate timed out"); }
                catch (InterruptedException failure) { throw new IllegalStateException(failure); }
                super.recreate(surface);
                call("migration-return");
            }
        };
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = checkpointLoop(host, error);
        ExecutorService caller = Executors.newSingleThreadExecutor();
        try {
            boolean rejected = false;
            try { loop.unserialize(new byte[] {9}, true); }
            catch (IllegalStateException expected) { rejected = true; }
            check(rejected && !host.calls.contains("unserialize"),
                    "restore mutated guest without an attached surface");
            loop.attachSurface(new Surface(true));
            loop.attachSecondarySurface(new Surface(true));
            loop.pauseAndWait();
            Future<?> restore = caller.submit(() -> loop.unserialize(new byte[] {9}, true));
            check(entered.await(2, TimeUnit.SECONDS), "restore did not reach migration");
            check(!restore.isDone(), "restore claimed success before migration returned");
            check(host.calls.indexOf("unserialize") < host.calls.indexOf("detach-secondary") &&
                    host.calls.indexOf("detach-secondary") < host.calls.indexOf("migration-enter"),
                    "restore/migration ordering is wrong: " + host.calls);
            allowMigration.countDown();
            restore.get(2, TimeUnit.SECONDS);
            check(host.calls.indexOf("migration-return") < host.calls.lastIndexOf("attach-secondary"),
                    "secondary surface was not reattached after migration");
            check(!host.calls.contains("run-present"), "paused restore ran a guest frame");
            int migrations = count(host.calls, "recreate");
            loop.unserialize(new byte[] {8}, false);
            check(count(host.calls, "recreate") == migrations && host.state[0] == 8,
                    "non-migrating core was recreated or not restored");
        } finally {
            allowMigration.countDown();
            caller.shutdownNow();
            loop.close();
        }
        check(error.get() == null, "restore raised asynchronous error: " + error.get());
    }

    private static void checkRestoreMigrationFailureStopsStaleFrames() throws Exception {
        FakeHost host = new FakeHost() {
            @Override public void recreate(Surface surface) {
                call("migration-failed");
                throw new IllegalStateException("injected context migration failure");
            }
        };
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = checkpointLoop(host, error);
        try {
            loop.attachSurface(new Surface(true));
            loop.pauseAndWait();
            boolean rejected = false;
            try { loop.unserialize(new byte[] {9}, true); }
            catch (IllegalStateException expected) {
                rejected = expected.getMessage().contains("injected context migration failure");
            }
            check(rejected, "migration failure was swallowed or acknowledged as success");
            loop.resume();
            loop.avInfo(); // Drain the queued resume; a pending frame still must not run.
            Thread.sleep(40L);
            loop.pauseAndWait();
            check(!host.calls.contains("run-present"), "failed migration presented a stale frame");
        } finally { loop.close(); }
        check(error.get() == null, "synchronous failure leaked into async error: " + error.get());
    }

    private static void checkRestoreInsideFrameCallbackIsAtomic() throws Exception {
        FakeHost host = new FakeHost() {
            @Override public boolean runAndPresent() {
                call("run-present");
                return true;
            }
        };
        CountDownLatch restored = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        AtomicReference<ExperimentalGlesRenderLoop> owner = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(() -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() {}
                    @Override public void onContextLost() {}
                    @Override public void onError(Throwable failure) { error.set(failure); }
                    @Override public void onFramePresented() {
                        if (restored.getCount() == 0) return;
                        owner.get().unserialize(new byte[] {9}, true);
                        host.call("restore-acknowledged");
                        restored.countDown();
                    }
                }, 1_000_000L);
        owner.set(loop);
        try {
            loop.attachSurface(new Surface(true));
            loop.resume();
            check(restored.await(2, TimeUnit.SECONDS), "first-frame restore deadlocked or failed");
            loop.pauseAndWait();
            int restoreAt = host.calls.indexOf("unserialize");
            int recreateAt = host.calls.indexOf("recreate");
            int ackAt = host.calls.indexOf("restore-acknowledged");
            check(restoreAt < recreateAt && recreateAt < ackAt,
                    "first-frame restore acknowledged a queued migration: " + host.calls);
            check(!host.calls.subList(restoreAt, ackAt).contains("run-present"),
                    "guest frame escaped between restore and migration");
        } finally { loop.close(); }
        check(error.get() == null, "first-frame restore error: " + error.get());
    }

    private static void checkDirectDisplayClockLifecycle() throws Exception {
        List<Double> rates = Collections.synchronizedList(new ArrayList<>());
        FakeHost host = new FakeHost() {
            @Override public void setSynchronizedVideoRate(double declared, double target) {
                call("clock-rate");
                check(declared == 60.0, "display correction changed declared guest clock");
                rates.add(target);
            }
        };
        host.generation = 1;
        class Clock implements ExperimentalGlesRenderLoop.DisplayClock {
            boolean enabled, unavailable, fail;
            int suspends, closes, waits;
            double measured = 60.02;
            long lastReturn, waitingGap;
            @Override public void configure(double declared, double source, boolean enabled) {
                host.call("clock-configure");
                check(Math.abs(source - 60) < 0.001, "display clock lost nominal cadence");
                this.enabled = enabled;
            }
            @Override public long awaitDueTimeNs() throws InterruptedException {
                host.call("clock-wait");
                if (fail) throw new IllegalStateException("timing service lost");
                if (!enabled || unavailable) return 0;
                long now = System.nanoTime();
                if (lastReturn != 0) waitingGap += now - lastReturn;
                ++waits;
                // Deliberately accelerated fake ticks detect a second nominal
                // sleep. This is a scheduler test, not physical cadence evidence.
                Thread.sleep(5);
                lastReturn = System.nanoTime();
                return lastReturn;
            }
            @Override public double measuredSourceHz() { return measured; }
            @Override public void suspend() { host.call("clock-suspend"); ++suspends; }
            @Override public void close() { host.call("clock-close"); ++closes; }
        }
        Clock clock = new Clock();
        CountDownLatch ready = new CountDownLatch(1);
        AtomicReference<CountDownLatch> presented = new AtomicReference<>(new CountDownLatch(20));
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(() -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() { presented.get().countDown(); }
                    @Override public void onContextLost() { error.set(new AssertionError("context lost")); }
                    @Override public void onError(Throwable failure) { error.set(failure); }
                }, 16_666_667L, true);
        Surface surface = new Surface(true);
        try {
            check(ready.await(2, TimeUnit.SECONDS), "display-clock host not ready");
            loop.setDisplayClock(clock);
            loop.attachSurface(surface);
            loop.resume();
            check(presented.get().await(2, TimeUnit.SECONDS), "display ticks did not drive guest");
            loop.pauseAndWait();
            check(clock.waits >= 20 && clock.waitingGap < 150_000_000L,
                    "nominal sleep was added between display ticks: " + clock.waitingGap);
            check(rates.contains(60.02), "audio did not follow measured display clock");
            int frames = host.frames;
            int suspends = clock.suspends;
            Thread.sleep(40);
            check(host.frames == frames && suspends > 0, "pause did not stop ticker/guest");

            clock.unavailable = true;
            presented.set(new CountDownLatch(3));
            loop.resume();
            check(presented.get().await(2, TimeUnit.SECONDS), "missing ticks stopped gameplay");
            loop.pauseAndWait();
            check(Math.abs(rates.get(rates.size() - 1) - 60) < 0.001,
                    "absolute fallback left audio on the measured clock");

            // Register the actual input identity; a saved setting or backend
            // label is not enough to distinguish FG from a physical surface.
            Class<?> rendererType = com.thorium.preview.game.FrameGenerationRenderer.class;
            Object renderer = java.lang.reflect.Proxy.newProxyInstance(
                    rendererType.getClassLoader(), new Class<?>[] {rendererType},
                    (proxy, method, args) -> method.getName().equals("inputSurface") ? surface : null);
            java.lang.reflect.Method register =
                    com.thorium.preview.game.FrameGenerationRendererRegistry.class
                            .getDeclaredMethod("register", rendererType);
            java.lang.reflect.Method unregister =
                    com.thorium.preview.game.FrameGenerationRendererRegistry.class
                            .getDeclaredMethod("unregister", Surface.class, rendererType);
            register.setAccessible(true);
            unregister.setAccessible(true);
            register.invoke(null, renderer);
            try {
                clock.unavailable = false;
                clock.lastReturn = 0;
                int waits = clock.waits;
                presented.set(new CountDownLatch(3));
                loop.resume();
                check(presented.get().await(2, TimeUnit.SECONDS), "FG surface stopped guest");
                loop.pauseAndWait();
                check(!clock.enabled && clock.waits == waits,
                        "physical display clock consumed ticks for FG input surface");
            } finally { unregister.invoke(null, surface, renderer); }

            // A live direct path can reacquire ticks after FG removal. Reject
            // invalid/out-of-budget measured rates before touching native audio.
            clock.measured = 40;
            presented.set(new CountDownLatch(3));
            loop.resume();
            check(presented.get().await(2, TimeUnit.SECONDS), "invalid tick fallback stopped guest");
            loop.pauseAndWait();
            check(!rates.contains(40.0), "display clock underclocked the guest");
            clock.measured = 60.02;
            clock.lastReturn = 0;
            presented.set(new CountDownLatch(3));
            loop.resume();
            check(presented.get().await(2, TimeUnit.SECONDS), "direct clock did not recover");
            loop.pauseAndWait();
            check(rates.get(rates.size() - 1) == 60.02, "recovered audio stayed nominal");

            clock.fail = true;
            presented.set(new CountDownLatch(3));
            loop.resume();
            check(presented.get().await(2, TimeUnit.SECONDS), "optional ticker failure stopped guest");
            loop.pauseAndWait();
            check(clock.closes == 1, "failed ticker was not retired exactly once");
            check(Math.abs(rates.get(rates.size() - 1) - 60) < 0.001,
                    "failed ticker left stale audio correction");
        } finally { loop.close(); }
        check(clock.closes == 1 && host.calls.contains("close"), "ticker/native cleanup incomplete");
        check(error.get() == null, "optional display clock caused gameplay error: " + error.get());
    }

    private static void checkAudioPacedRenderSteps() throws Exception {
        check(ExperimentalGlesRenderLoop.guestStepDurationNanos(true, 33_333_333L,
                16_666_667L) == 33_333_333L, "30 Hz audio step forced to 60 Hz");
        check(ExperimentalGlesRenderLoop.guestStepDurationNanos(true, 50_000_000L,
                16_666_667L) == 50_000_000L, "20 Hz audio step forced to 60 Hz");
        check(ExperimentalGlesRenderLoop.guestStepDurationNanos(true, 0L,
                16_666_667L) == 16_666_667L, "loading/no-PCM busy spin");
        check(ExperimentalGlesRenderLoop.guestStepDurationNanos(false, 50_000_000L,
                16_666_667L) == 16_666_667L, "unrelated core pacing changed");
        List<Long> starts = Collections.synchronizedList(new ArrayList<>());
        final long[] durations = {50_000_000L, 16_666_667L, 33_333_333L,
                50_000_000L, 16_666_667L, 33_333_333L, 16_666_667L};
        FakeHost host = new FakeHost() {
            @Override public boolean usesAudioPacing() { return true; }
            @Override public boolean runAndPresent() {
                call("run-present"); starts.add(System.nanoTime()); ++frames;
                try { Thread.sleep(3); } catch (InterruptedException failure) {
                    throw new IllegalStateException(failure);
                }
                return true;
            }
            @Override public long lastRunAudioDurationNanos() {
                call("audio-step-time");
                return durations[Math.min(frames - 1, durations.length - 1)];
            }
        };
        CountDownLatch ready = new CountDownLatch(1), done = new CountDownLatch(7);
        AtomicReference<Throwable> error = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(() -> host,
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() { done.countDown(); }
                    @Override public void onContextLost() { error.set(new AssertionError("lost")); }
                    @Override public void onError(Throwable failure) { error.set(failure); }
                }, 16_666_667L, true);
        try {
            check(ready.await(2, TimeUnit.SECONDS), "audio-paced host not ready");
            loop.setDisplayClock(new ExperimentalGlesRenderLoop.DisplayClock() {
                @Override public void configure(double a, double b, boolean enabled) {
                    throw new AssertionError("fixed display clock used for render-driven core");
                }
                @Override public long awaitDueTimeNs() { throw new AssertionError("display wait"); }
                @Override public double measuredSourceHz() { return 60.0; }
                @Override public void suspend() {}
                @Override public void close() {}
            });
            loop.attachSurface(new Surface(true)); loop.resume();
            check(done.await(2, TimeUnit.SECONDS), "audio-paced steps stopped");
            loop.pauseAndWait();
            // Six variable steps total 200 ms. Nominal-only pacing would take
            // 100 ms. Generous OS-jitter bound; exact durations checked above.
            long elapsed = starts.get(6) - starts.get(0);
            check(elapsed >= 185_000_000L && elapsed < 700_000_000L,
                    "generated media time did not own deadlines: " + elapsed);
            int pausedFrames = host.frames;
            Thread.sleep(30);
            check(host.frames == pausedFrames, "audio-paced guest advanced while paused");
            loop.resume(); Thread.sleep(50); loop.pauseAndWait();
            check(host.frames > pausedFrames, "audio-paced resume stalled");
        } finally { loop.close(); }
        check(error.get() == null, "audio-paced render error: " + error.get());
    }

    public static void main(String[] args) throws Exception {
        checkAudioPacedRenderSteps();
        checkDirectDisplayClockLifecycle();
        checkRestoreMigrationIsOneAcknowledgedOperation();
        checkRestoreMigrationFailureStopsStaleFrames();
        checkRestoreInsideFrameCallbackIsAtomic();
        checkCloseAcknowledgementSurvivesTimeoutAndInterruption();
        checkFailedNativeCloseNeverAcknowledgesSuccess();
        checkClockRequestsCannotSlowTheGuest();
        check(ExperimentalGlesRenderLoop.frameDelayNanos(50.0) == 20_000_000L,
                "PAL cadence was not derived from core AV timing");
        check(ExperimentalGlesRenderLoop.frameDelayNanos(59.94) == 16_683_350L,
                "fractional NTSC cadence was rounded incorrectly");
        check(ExperimentalGlesRenderLoop.frameDelayNanos(Double.NaN) ==
                        1_000_000_000L / 60L,
                "invalid core cadence did not fall back safely");
        FakeHost host = new FakeHost();
        CountDownLatch ready = new CountDownLatch(1);
        CountDownLatch firstPresented = new CountDownLatch(1);
        CountDownLatch contextLost = new CountDownLatch(1);
        CountDownLatch recreatedPresented = new CountDownLatch(1);
        AtomicReference<Throwable> error = new AtomicReference<>();
        AtomicReference<ExperimentalGlesRenderLoop> activeLoop = new AtomicReference<>();
        ExperimentalGlesRenderLoop loop = new ExperimentalGlesRenderLoop(
                () -> { host.call("create-load"); return host; },
                new ExperimentalGlesRenderLoop.Listener() {
                    int presented;
                    @Override public void onReady() { ready.countDown(); }
                    @Override public void onFramePresented() {
                        short[] callbackAudio = activeLoop.get().drainAudio(8);
                        if (!java.util.Arrays.equals(callbackAudio, new short[] {7, -7}))
                            throw new AssertionError("same-thread audio drain failed");
                        presented++;
                        if (presented == 1) firstPresented.countDown();
                        else recreatedPresented.countDown();
                    }
                    @Override public void onContextLost() { contextLost.countDown(); }
                    @Override public void onError(Throwable failure) {
                        error.compareAndSet(null, failure);
                    }
                }, 1_000_000L);
        activeLoop.set(loop);
        check(ready.await(2, TimeUnit.SECONDS), "render loop did not initialize");
        // Wii/GameCube run on this path: the Nunchuk device and the power
        // cycle must both be marshalled onto the render-owning thread, which
        // FakeHost.call() asserts for every entry point.
        loop.setControllerPortDevice(0, (3 << 8) | 1);
        loop.reset();
        check(loop.avInfo().sampleRate == 48000.0, "render-thread AV query failed");
        loop.setPresentationAspect(4f / 3f);
        check(java.util.Arrays.equals(loop.drainAudio(8), new short[] {7, -7}),
                "render-thread audio drain failed");
        check(java.util.Arrays.equals(loop.serialize(), new byte[] {1, 2, 3}),
                "render-thread serialize failed");
        loop.unserialize(new byte[] {9, 8});
        check(java.util.Arrays.equals(loop.serialize(), new byte[] {9, 8}),
                "render-thread restore failed");
        check(java.util.Arrays.equals(loop.readSaveRam(), new byte[] {4, 5}),
                "render-thread save RAM read failed");
        loop.writeSaveRam(new byte[] {6, 7});
        check(java.util.Arrays.equals(loop.readSaveRam(), new byte[] {6, 7}),
                "render-thread save RAM write failed");
        Surface surface = new Surface(true);
        loop.attachSurface(surface);
        loop.resume();
        loop.setJoypadButton(0, 0, true);
        loop.setAnalogAxis(0, 0, 0, 0.5f);
        check(firstPresented.await(2, TimeUnit.SECONDS), "first GLES frame did not present");
        check(contextLost.await(2, TimeUnit.SECONDS), "context loss was not surfaced");
        loop.recreateSurface(surface);
        check(recreatedPresented.await(2, TimeUnit.SECONDS),
              "recreated GLES surface did not resume presentation");
        int callsBeforeExitBarrier = host.calls.size();
        loop.pauseAndWait();
        check(host.calls.size() > callsBeforeExitBarrier &&
                        "pause".equals(host.calls.get(host.calls.size() - 1)),
                "exit pause did not synchronously drain the render thread");
        int framesAfterExitBarrier = host.frames;
        Thread.sleep(40L);
        check(host.frames == framesAfterExitBarrier,
                "frame presented after synchronous exit barrier");
        loop.detachSurface();
        loop.close();
        loop.close();
        check(error.get() == null, "unexpected render-loop error: " + error.get());
        check(host.calls.contains("create-load") && host.calls.contains("attach") &&
              host.calls.contains("resume") && host.calls.contains("run-present") &&
              host.calls.contains("button") && host.calls.contains("axis") &&
              host.calls.contains("av") && host.calls.contains("audio") &&
              host.calls.contains("aspect:" + (4f / 3f)) &&
              host.calls.contains("serialize") && host.calls.contains("unserialize") &&
              host.calls.contains("read-save") && host.calls.contains("write-save") &&
              host.calls.contains("recreate") && host.calls.contains("pause") &&
              host.calls.contains("detach") && host.calls.contains("close") &&
              host.calls.contains("port-device:0:0x301") &&
              host.calls.contains("reset"),
              "incomplete render lifecycle: " + host.calls);
        check(host.owner != Thread.currentThread(), "GLES work ran on caller thread");
        boolean closedRejected = false;
        try { loop.resume(); }
        catch (IllegalStateException expected) { closedRejected = true; }
        check(closedRejected, "closed render loop accepted new work");

        // Emulation/render work must consume the frame budget, not be followed
        // by another complete frame delay. With 50 ms work and a 50 ms target,
        // four old-style frames take about 350 ms including the first delay;
        // absolute deadlines complete the measured three intervals near 150 ms.
        SlowHost slow = new SlowHost();
        CountDownLatch pacingReady = new CountDownLatch(1);
        AtomicReference<Throwable> pacingError = new AtomicReference<>();
        ExperimentalGlesRenderLoop pacing = new ExperimentalGlesRenderLoop(
                () -> { slow.call("create-load"); return slow; },
                new ExperimentalGlesRenderLoop.Listener() {
                    @Override public void onReady() { pacingReady.countDown(); }
                    @Override public void onFramePresented() {}
                    @Override public void onContextLost() {
                        pacingError.compareAndSet(null,
                                new AssertionError("unexpected pacing context loss"));
                    }
                    @Override public void onError(Throwable failure) {
                        pacingError.compareAndSet(null, failure);
                    }
                }, 50_000_000L);
        check(pacingReady.await(2, TimeUnit.SECONDS), "pacing loop did not initialize");
        pacing.attachSurface(new Surface(true));
        pacing.resume();
        check(slow.fourFrames.await(2, TimeUnit.SECONDS), "pacing loop did not run four frames");
        pacing.pause();
        pacing.close();
        check(pacingError.get() == null, "unexpected pacing error: " + pacingError.get());
        long pacedMillis = TimeUnit.NANOSECONDS.toMillis(
                slow.completions.get(3) - slow.completions.get(0));
        check(pacedMillis < 240L,
                "frame work was added after, not included in, deadlines: " + pacedMillis + " ms");
        checkDuplicateAttachIsAbsorbed();
        checkDistinctReplacementRecreatesOnce();
        checkResizeNeverDestroysTheLiveSurface();
        checkBackgroundCapturePrecedesDetach();
        checkSlowBackgroundCaptureKeepsDetachBound();
        checkUnavailableAndFailedBackgroundCapture();
        checkWarmupIsNotWorkThroughput();
        checkTransientStallPreservesClock();
        checkClockDebtWithoutSkippingPresentation();
        checkRecoveryDoesNotWaitForEveryStaleSwap();
        System.out.println("Experimental GLES dedicated render-loop probe passed");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
