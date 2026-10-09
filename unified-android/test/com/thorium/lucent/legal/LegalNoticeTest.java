package com.thorium.lucent.legal;

import com.thorium.lucent.TestSupport;

/**
 * Host tests for the first-launch legal notice.
 *
 * <p>The two behaviours worth pinning are the ones a user can be locked out by,
 * or can silently escape: Confirm must not unlock before the text has been
 * scrolled to its end, and it must not stay locked when there is nothing to
 * scroll.
 */
public final class LegalNoticeTest {

    public static void main(String[] args) {
        confirmIsLockedUntilScrolledToTheEnd();
        confirmUnlocksWhenNothingCanScroll();
        confirmToleratesStoppingJustShortOfTheBottom();
        suppressionIsWhatSilencesTheNotice();
        bodyKeepsEveryParagraphAndSeparatesThem();
        System.out.println("LegalNoticeTest passed");
    }

    private static void confirmIsLockedUntilScrolledToTheEnd() {
        // 900px of text in a 300px window: the top and middle must not unlock.
        TestSupport.truth(!LegalNotice.canConfirm(0, 300, 900),
                "unscrolled notice must not be confirmable");
        TestSupport.truth(!LegalNotice.canConfirm(300, 300, 900),
                "half-read notice must not be confirmable");
        TestSupport.truth(LegalNotice.canConfirm(600, 300, 900),
                "notice scrolled to the end must be confirmable");
    }

    private static void confirmUnlocksWhenNothingCanScroll() {
        // A short notice on a tall screen has no scrolling to do; requiring it
        // would make the notice permanently undismissable.
        TestSupport.truth(LegalNotice.canConfirm(0, 900, 400),
                "notice that fits must be confirmable immediately");
        TestSupport.truth(LegalNotice.canConfirm(0, 900, 900),
                "notice exactly filling the viewport must be confirmable");
    }

    private static void confirmToleratesStoppingJustShortOfTheBottom() {
        // Fling scrolling and fractional densities routinely stop a pixel or
        // two early; that must not read as "unread".
        TestSupport.truth(LegalNotice.canConfirm(599, 300, 900),
                "a pixel short of the bottom must still confirm");
        TestSupport.truth(!LegalNotice.canConfirm(560, 300, 900),
                "well short of the bottom must not confirm");
    }

    private static void suppressionIsWhatSilencesTheNotice() {
        TestSupport.truth(LegalNotice.shouldShow(false),
                "an unacknowledged notice must be shown");
        TestSupport.truth(!LegalNotice.shouldShow(true),
                "acknowledging with suppression must silence the notice");
    }

    private static void bodyKeepsEveryParagraphAndSeparatesThem() {
        String body = LegalNotice.body();
        for (String paragraph : LegalNotice.PARAGRAPHS) {
            TestSupport.truth(body.contains(paragraph),
                    "body dropped a paragraph: " + paragraph);
        }
        TestSupport.truth(body.contains("\n\n"),
                "paragraphs must be separated by a blank line");
        TestSupport.truth(!body.contains("\n\n\n"),
                "paragraphs must not be separated by more than one blank line");
        // The disclaimer of affiliation is the load-bearing sentence; a future
        // edit that drops it should fail loudly rather than quietly ship.
        TestSupport.truth(body.contains("not affiliated with"),
                "notice must state the lack of affiliation");
    }
}
