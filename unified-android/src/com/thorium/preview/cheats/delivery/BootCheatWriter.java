package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.List;

/**
 * Writes a game's cheats into the files one engine reads at boot.
 *
 * <p>Every implementation is idempotent (the same request always produces
 * the same bytes), atomic (a temporary file renamed into place), bounded
 * (no output beyond {@link OwnedFiles#MAX_BYTES}), and touches only files
 * it created itself: an EmuFusion-prefixed directory, or a file whose
 * ownership sidecar proves EmuFusion wrote it. A file the user or the
 * engine wrote is left alone and reported rather than overwritten.
 */
public interface BootCheatWriter {
    /** Files written or removed; empty when the request carried nothing to deliver. */
    List<File> write(BootCheatRequest request) throws IOException;
}
