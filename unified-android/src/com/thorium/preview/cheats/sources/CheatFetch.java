package com.thorium.preview.cheats.sources;

import java.io.File;

/** How the slicer obtains a source's bytes; abstracted so tests use local files. */
public interface CheatFetch {
    /** @return the cached file, or null when the source cannot be fetched */
    File fetch(CheatSource source, String url);
}
