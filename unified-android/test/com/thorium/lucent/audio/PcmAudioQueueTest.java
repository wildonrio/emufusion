package com.thorium.lucent.audio;

import com.thorium.lucent.TestSupport;

public final class PcmAudioQueueTest {
    public static void main(String[] args) {
        partialConsumptionPreservesEverySample();
        overflowIsRejectedAndCountable();
        clearReportsDiscardedSamples();
        malformedStereoFailsClosed();
        System.out.println("PcmAudioQueueTest passed");
    }

    private static void partialConsumptionPreservesEverySample() {
        PcmAudioQueue queue = new PcmAudioQueue(16);
        short[] first = {1, 2, 3, 4, 5, 6};
        short[] second = {7, 8, 9, 10};
        TestSupport.equal(0, queue.offer(first), "first PCM block accepted");
        queue.consume(2);
        TestSupport.equal(2, queue.headOffset(), "partial write offset retained");
        TestSupport.truth(queue.head() == first, "partial block remains the head");
        TestSupport.equal(0, queue.offer(second), "new PCM queues behind partial head");
        TestSupport.equal(8, queue.queuedSamples(), "no sample silently disappears");
        queue.consume(4);
        TestSupport.truth(queue.head() == second, "second block follows first in order");
        queue.consume(4);
        TestSupport.equal(0, queue.queuedSamples(), "all accepted PCM drains exactly");
    }

    private static void overflowIsRejectedAndCountable() {
        PcmAudioQueue queue = new PcmAudioQueue(8);
        TestSupport.equal(0, queue.offer(new short[] {1, 2, 3, 4, 5, 6}),
                "block below capacity accepted");
        TestSupport.equal(4, queue.offer(new short[] {7, 8, 9, 10}),
                "overflow reports every rejected sample");
        TestSupport.equal(6, queue.queuedSamples(), "overflow cannot mutate accepted PCM");
    }

    private static void clearReportsDiscardedSamples() {
        PcmAudioQueue queue = new PcmAudioQueue(8);
        queue.offer(new short[] {1, 2, 3, 4});
        queue.consume(2);
        TestSupport.equal(2, queue.clear(), "clear reports only still-pending samples");
        TestSupport.equal(0, queue.queuedSamples(), "clear empties the FIFO");
    }

    private static void malformedStereoFailsClosed() {
        PcmAudioQueue queue = new PcmAudioQueue(8);
        boolean rejected = false;
        try { queue.offer(new short[] {1, 2, 3}); }
        catch (IllegalArgumentException expected) { rejected = true; }
        TestSupport.truth(rejected, "half a stereo frame is rejected");
    }
}
