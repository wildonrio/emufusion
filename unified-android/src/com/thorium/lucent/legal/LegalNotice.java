package com.thorium.lucent.legal;

/**
 * The notice EmuFusion shows once on first launch and keeps available from
 * Settings.
 *
 * <p>It lives here, with no {@code android.*} imports, for two reasons. It is
 * the single source of the wording -- the startup overlay and the Settings
 * entry must never drift apart, because a legal notice that says two different
 * things is worse than one that says nothing. And keeping it host-testable
 * means the acceptance rules around it (scroll-to-end, the checkbox default)
 * can be tested on the JVM rather than only by hand on a handheld.
 */
public final class LegalNotice {

    private LegalNotice() {}

    /** Shown as the heading above the body. */
    public static final String TITLE = "Legal Notice";

    /**
     * The paragraphs, in order. Stored split rather than as one blob so the
     * renderer can space them without parsing, and so a test can assert the
     * wording paragraph by paragraph.
     */
    public static final String[] PARAGRAPHS = {
        "EmuFusion is an independent software application for organizing and "
            + "launching games owned by its users.",

        "EmuFusion is not affiliated with, sponsored by, endorsed by, or "
            + "approved by any console manufacturer, game publisher, trademark "
            + "owner, copyright owner, or other rights holder.",

        "Console names, game titles, logos, trademarks, box art, screenshots, "
            + "wallpapers, videos, and other third-party content are the "
            + "property of their respective owners and are displayed solely to "
            + "identify compatible gaming platforms and user game libraries.",

        "EmuFusion does not include or bundle copyrighted games, firmware, "
            + "BIOS files, or third-party artwork as part of its installation. "
            + "Where configured by the user, EmuFusion may retrieve metadata "
            + "and media from third-party sources. Such content remains subject "
            + "to the rights and terms established by its respective owners and "
            + "providers.",

        "Users are solely responsible for obtaining, possessing, and using "
            + "games, firmware, artwork, and other content in compliance with "
            + "applicable law and the terms under which that content is made "
            + "available.",

        "The optional downloadable cheat catalog is adapted from the Libretro "
            + "Database (github.com/libretro/libretro-database), licensed under "
            + "Creative Commons Attribution-ShareAlike 4.0 "
            + "(creativecommons.org/licenses/by-sa/4.0/). Individual codes "
            + "may be region- or revision-specific and are provided without a "
            + "guarantee that they work with every game dump.",

        "All trademarks, service marks, logos, and copyrights are the property "
            + "of their respective owners. Their appearance within EmuFusion "
            + "does not imply any affiliation, sponsorship, endorsement, "
            + "approval, or partnership.",
    };

    /** Label on the checkbox, which starts CHECKED. */
    public static final String SUPPRESS_LABEL = "Don't show this again";

    /** Label on the button that dismisses the notice. */
    public static final String CONFIRM_LABEL = "Confirm";

    /** The whole notice as one string, paragraphs separated by a blank line. */
    public static String body() {
        StringBuilder text = new StringBuilder();
        for (int index = 0; index < PARAGRAPHS.length; ++index) {
            if (index > 0) text.append("\n\n");
            text.append(PARAGRAPHS[index]);
        }
        return text.toString();
    }

    /**
     * Whether the notice should appear on this launch.
     *
     * <p>Acceptance alone is not enough to suppress it: the user asked for the
     * checkbox to be the thing that decides. Confirming with it unchecked is a
     * deliberate "show me again", so only an acknowledgement that was made with
     * the box checked is remembered.
     */
    public static boolean shouldShow(boolean acknowledgedWithSuppression) {
        return !acknowledgedWithSuppression;
    }

    /**
     * Whether Confirm may be pressed yet.
     *
     * <p>The button stays dead until the body has been scrolled to its end.
     * {@code contentHeight <= viewportHeight} means the text already fits with
     * nothing to scroll, which counts as having reached the end -- otherwise a
     * large enough screen would leave the notice permanently undismissable.
     */
    public static boolean canConfirm(int scrollY, int viewportHeight, int contentHeight) {
        if (viewportHeight <= 0 || contentHeight <= viewportHeight) return true;
        // A couple of pixels of slack: fling scrolling and fractional device
        // densities routinely stop a hair short of the exact bottom, and a
        // notice that cannot be dismissed after being fully read is a lockout.
        final int slack = 2;
        return scrollY + viewportHeight + slack >= contentHeight;
    }
}
