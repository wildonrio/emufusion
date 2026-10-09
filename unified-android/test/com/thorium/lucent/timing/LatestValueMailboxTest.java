package com.thorium.lucent.timing;

import com.thorium.lucent.TestSupport;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicReference;

public final class LatestValueMailboxTest {
    public static void main(String[] ignored) throws Exception {
        replacesAnUnconsumedValue();
        returnsReplacedAndClosedValuesToTheirOwnerExactlyOnce();
        reportsReplacementAtTheLinearizedProducerConsumerBoundary();
        closeUnblocksAndRejectsOffers();
        System.out.println("LatestValueMailboxTest passed");
    }

    private static void returnsReplacedAndClosedValuesToTheirOwnerExactlyOnce() {
        LatestValueMailbox<String> mailbox = new LatestValueMailbox<>();
        java.util.ArrayList<String> discarded = new java.util.ArrayList<>();
        mailbox.offerLatest("first", discarded::add);
        TestSupport.equal(LatestValueMailbox.OfferResult.REPLACED,
                mailbox.offerLatest("second", discarded::add),
                "pooled replacement must be reported");
        mailbox.close(discarded::add);
        TestSupport.equal(2, discarded.size(),
                "replacement and close each return one owned value");
        TestSupport.equal("first", discarded.get(0),
                "replacement returns the overwritten value");
        TestSupport.equal("second", discarded.get(1),
                "close returns the unconsumed value");
    }

    private static void reportsReplacementAtTheLinearizedProducerConsumerBoundary()
            throws Exception {
        for (int iteration = 0; iteration < 200; iteration++) {
            LatestValueMailbox<String> mailbox = new LatestValueMailbox<>();
            mailbox.offerLatest("old");
            CountDownLatch start = new CountDownLatch(1);
            AtomicReference<String> consumed = new AtomicReference<>();
            AtomicReference<LatestValueMailbox.OfferResult> offered =
                    new AtomicReference<>();
            Thread consumer = new Thread(() -> {
                try {
                    start.await();
                    consumed.set(mailbox.take());
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                }
            });
            Thread producer = new Thread(() -> {
                try {
                    start.await();
                    offered.set(mailbox.offerLatest("new"));
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                }
            });
            consumer.start();
            producer.start();
            start.countDown();
            consumer.join();
            producer.join();

            if (offered.get() == LatestValueMailbox.OfferResult.ACCEPTED) {
                TestSupport.equal("old", consumed.get(),
                        "accepted means the consumer removed the old value first");
                TestSupport.equal("new", mailbox.take(),
                        "accepted concurrent offer remains available");
            } else {
                TestSupport.equal(LatestValueMailbox.OfferResult.REPLACED, offered.get(),
                        "open concurrent offer has one of the two valid outcomes");
                TestSupport.equal("new", consumed.get(),
                        "replaced means the consumer receives the new value");
                TestSupport.truth(mailbox.isEmpty(),
                        "consumer drains the replaced concurrent offer");
            }
        }
    }

    private static void replacesAnUnconsumedValue() throws Exception {
        LatestValueMailbox<String> mailbox = new LatestValueMailbox<>();
        TestSupport.truth(mailbox.isEmpty(), "new mailbox is empty");
        TestSupport.equal(LatestValueMailbox.OfferResult.ACCEPTED,
                mailbox.offerLatest("old"), "first offer accepted");
        TestSupport.equal(LatestValueMailbox.OfferResult.REPLACED,
                mailbox.offerLatest("latest"), "replacement is reported atomically");
        TestSupport.equal("latest", mailbox.take(),
                "a lagging renderer receives only the newest frame");
        TestSupport.truth(mailbox.isEmpty(), "take drains the one slot");
    }

    private static void closeUnblocksAndRejectsOffers() throws Exception {
        LatestValueMailbox<String> mailbox = new LatestValueMailbox<>();
        mailbox.offer("stale");
        mailbox.close();
        TestSupport.equal(null, mailbox.take(), "closed mailbox returns no stale value");
        TestSupport.equal(LatestValueMailbox.OfferResult.REJECTED,
                mailbox.offerLatest("late"), "closed mailbox rejects producers");
    }
}
