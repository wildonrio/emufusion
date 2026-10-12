package com.thorium.emufusion.state;

import java.io.File;

public final class StateSnapshot {
    public final SnapshotMetadata metadata;
    public final File directory;

    StateSnapshot(SnapshotMetadata metadata, File directory) {
        this.metadata = metadata;
        this.directory = directory;
    }

    public File screenshotFile() {
        return new File(directory, "preview.webp");
    }
}
