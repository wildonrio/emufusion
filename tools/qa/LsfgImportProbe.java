package com.thorium.preview.game;

import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;

/** Headless test of the actual qualification importer; uses disposable paths. */
public final class LsfgImportProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("source fresh-test-root");
        File source = new File(args[0]);
        File tests = new File(args[1]);
        Files.createDirectory(tests.toPath());
        File valid = new File(tests, "valid");
        LsfgQualificationRuntime.importPrivatePayload(source, valid);
        for (int i = 353; i <= 400; ++i)
            check(Arrays.equals(Files.readAllBytes(new File(source, "shaders/" + i + ".spv").toPath()),
                    Files.readAllBytes(new File(valid, "shaders/" + i + ".spv").toPath())), "copy differs");
        // Existing successful import is not overwritten from a missing source.
        LsfgQualificationRuntime.importPrivatePayload(new File(tests, "absent"), valid);
        Files.delete(new File(valid, "qualification-manifest.json").toPath());
        LsfgQualificationRuntime.importPrivatePayload(source, valid);
        check(new File(valid, "qualification-manifest.json").isFile(), "commit recovery failed");

        File bad = new File(tests, "bad-source");
        Files.createDirectories(new File(bad, "shaders").toPath());
        Files.copy(new File(source, "qualification-manifest.json").toPath(),
                new File(bad, "qualification-manifest.json").toPath());
        for (int i = 353; i <= 400; ++i)
            Files.copy(new File(source, "shaders/" + i + ".spv").toPath(),
                    new File(bad, "shaders/" + i + ".spv").toPath());
        Files.write(new File(bad, "shaders/353.spv").toPath(), new byte[]{1});
        File rejected = new File(tests, "rejected");
        expectRejected(bad, rejected);
        check(!new File(rejected, "qualification-manifest.json").exists(), "published corrupt import");

        File conflict = new File(tests, "conflict");
        Files.createDirectories(new File(conflict, "shaders").toPath());
        File existing = new File(conflict, "shaders/353.spv");
        Files.write(existing.toPath(), new byte[]{42});
        expectRejected(source, conflict);
        check(Arrays.equals(Files.readAllBytes(existing.toPath()), new byte[]{42}), "overwrote existing data");
        check(!new File(conflict, "qualification-manifest.json").exists(), "published conflicting import");
        for (File child : conflict.listFiles())
            check(!child.getName().startsWith(".shader-import-"), "leaked failed staging directory");
        System.out.println("LSFG_IMPORT_PASS copy=48 idempotent=true recovery=true corruptRejected=true existingPreserved=true");
    }
    private static void expectRejected(File source, File target) throws Exception {
        try {
            LsfgQualificationRuntime.importPrivatePayload(source, target);
        } catch (IllegalStateException expected) { return; }
        throw new AssertionError("invalid import accepted");
    }
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
