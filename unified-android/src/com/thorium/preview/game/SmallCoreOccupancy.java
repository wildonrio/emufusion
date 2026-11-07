package com.thorium.preview.game;

import android.util.Log;
import java.util.concurrent.locks.LockSupport;

/**
 * While Cemu's held output runs, keeps a thread on every small core, so the scheduler counts those
 * cores as full and the display composer's commit thread runs on a medium core.
 *
 * <p>A real image's compositor pass follows an empty scan, and its main-display commit has to end at
 * about the slot with 0.1-0.3 ms to spare. On a small core the commit takes 0.28 ms; on a medium
 * core, 0.14 ms. The commit thread takes the smallest core that fits, and a small core only stops
 * fitting when its load is near 100%: threads that ran just for the pass, 1.5 ms in 16.7, left the
 * commit where it was. All three cores have to be full; one or two did not move it. Wind Waker HD,
 * 1,000 real images: 108 and 190 a scan late with nothing, 49 and 39 with the short threads, 26 and
 * 44 with one or two full cores, 2 with three. Thor, 2026-11-07; see the goal document.</p>
 *
 * <p>The threads run at the lowest priority, so anything else that wants the core takes it at once,
 * and wait in the CPU's low-power wait for an event instead of executing. QA
 * {@code emufusion_framegen_small_cores=0}.</p>
 */
final class SmallCoreOccupancy implements AutoCloseable {
    private static final String TAG = "EmuFusionSmallCores";
    /** No frame for this long (pause, menu, another kind of output): the threads sleep. */
    private static final long STALE_NS = 100_000_000L;
    private static final long IDLE_LOOK_NS = 25_000_000L;
    private static final long OCCUPIED_SLICE_NS = 10_000_000L;
    static final SmallCoreOccupancy NONE = new SmallCoreOccupancy(0L);

    private volatile boolean closed;
    private volatile long lastFrameNs = System.nanoTime() - STALE_NS;
    private final Thread[] threads;

    private SmallCoreOccupancy(long mask) {
        threads = new Thread[Long.bitCount(mask)];
        int next = 0;
        for (int cpu = 0; cpu < Long.SIZE; ++cpu) {
            if ((mask & (1L << cpu)) == 0L) continue;
            final long one = 1L << cpu;
            Thread thread = new Thread(() -> run(one), "EmuFusionSmallCore" + cpu);
            thread.setDaemon(true);
            threads[next++] = thread;
        }
        for (Thread thread : threads) thread.start();
    }

    /** Started on the frame thread; {@link #NONE} when the CPUs are uniform or the switch is off. */
    static SmallCoreOccupancy start() {
        if (!TimelineSchedulerSwitch.smallCores()) return NONE;
        try {
            long mask = DenseGpuTimer.smallCoreMask();
            if (mask == 0L) return NONE;
            Log.i(TAG, "Small cores ready mask=0x" + Long.toHexString(mask));
            return new SmallCoreOccupancy(mask);
        } catch (UnsatisfiedLinkError | RuntimeException failure) {
            Log.w(TAG, "Small cores unavailable", failure);
            return NONE;
        }
    }

    /** A frame of the kind of output that wants the cores occupied. */
    void frame() {
        if (threads.length != 0) lastFrameNs = System.nanoTime();
    }

    private void run(long one) {
        boolean pinned = false;
        try {
            while (!closed) {
                if (System.nanoTime() - lastFrameNs > STALE_NS) {
                    // Android resets the mask when the app's CPU set changes (background and back).
                    pinned = false;
                    LockSupport.parkNanos(IDLE_LOOK_NS);
                    continue;
                }
                if (!pinned) {
                    if (DenseGpuTimer.occupyCurrentThread(one) <= 0L) return;
                    pinned = true;
                }
                DenseGpuTimer.waitOccupied(OCCUPIED_SLICE_NS);
            }
        } catch (UnsatisfiedLinkError | RuntimeException failure) {
            Log.w(TAG, "Small core thread stopped", failure);
        }
    }

    @Override
    public void close() {
        closed = true;
        for (Thread thread : threads) LockSupport.unpark(thread);
    }
}
