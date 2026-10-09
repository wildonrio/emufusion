package com.thorium.lucent.emulators;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * One standalone Android emulator as the Settings route picker presents it:
 * a display name, the package ids it may be installed under, and the single
 * place the user is sent when it is missing.
 *
 * Deliberately free of any parser and of every Android type: this is the model,
 * and loading it from engines/external-emulators.json lives in the Android
 * layer (com.thorium.preview.ExternalEmulatorDirectoryLoader), which is what
 * keeps the picker's data rules testable on the host with no SDK.
 *
 * It carries no launch recipe on purpose. EmulatorCatalog owns how a ROM is
 * handed to an emulator; a name in this directory can therefore never make an
 * unlaunchable emulator selectable.
 */
public final class ExternalEmulator {
    /** Opens the Play listing (market:// on device, https:// off it). */
    public static final String INSTALL_PLAY = "play";
    /** Opens a release page or the project's own site in a browser. */
    public static final String INSTALL_WEB = "web";

    private final String id;
    private final String name;
    private final List<String> packages;
    private final String installKind;
    private final String installUrl;
    private final boolean verified;

    public ExternalEmulator(String id, String name, List<String> packages,
                            String installKind, String installUrl, boolean verified) {
        this.id = id == null ? "" : id;
        this.name = name == null ? "" : name;
        this.packages = Collections.unmodifiableList(
                new ArrayList<>(packages == null ? Collections.<String>emptyList() : packages));
        this.installKind = INSTALL_WEB.equals(installKind) ? INSTALL_WEB : INSTALL_PLAY;
        this.installUrl = installUrl == null ? "" : installUrl;
        this.verified = verified;
    }

    public String id() { return id; }
    public String name() { return name; }
    public List<String> packages() { return packages; }
    public String installKind() { return installKind; }
    public String installUrl() { return installUrl; }

    /**
     * False until a human has confirmed the package ids resolve to this
     * emulator. The picker surfaces it so an unverified entry can be shown
     * without the UI claiming it is known-good.
     */
    public boolean verified() { return verified; }

    /** The id an install intent should target, or "" when none is recorded. */
    public String primaryPackage() {
        return packages.isEmpty() ? "" : packages.get(0);
    }

    /** True once the entry is complete enough to be offered at all. */
    public boolean usable() {
        return !id.isEmpty() && !name.isEmpty() && !packages.isEmpty()
                && !installUrl.isEmpty();
    }
}
