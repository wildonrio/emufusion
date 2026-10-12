package com.thorium.emufusion;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;

public final class TestSupport {
    private TestSupport() {}

    public static void equal(Object expected, Object actual, String message) {
        if (expected == null ? actual != null : !expected.equals(actual))
            throw new AssertionError(message + " expected=" + expected + " actual=" + actual);
    }

    public static void truth(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static File temporaryDirectory(String name) throws IOException {
        return Files.createTempDirectory("emufusion-" + name + "-").toFile();
    }

    public static void deleteTree(File file) {
        if (file == null || !file.exists()) return;
        File[] children = file.listFiles();
        if (children != null) for (File child : children) deleteTree(child);
        if (!file.delete()) throw new AssertionError("Could not delete " + file);
    }
}
