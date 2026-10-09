package com.lsfg.android.session;

import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;

/** Headless private-asset preparation only; never launches an Android Activity. */
final class NativeBridge {
    native int extractShaders(String dllPath, String dllSha256, String cacheDir);
}

public final class LsfgPrivateExtractor {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            throw new IllegalArgumentException("Expected native library, owner DLL, new output directory");
        }
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(
                Files.readAllBytes(new File(args[1]).toPath()));
        StringBuilder hash = new StringBuilder();
        for (byte value : digest) hash.append(String.format("%02x", value & 255));
        if (!hash.toString().equals("fe0faeb147accab84539ac2bdcaa4eb3dec850752a336e710b85fc87477004e4"))
            throw new IllegalArgumentException("Owner DLL identity mismatch");
        File output = new File(args[2]);
        if (output.exists() || !output.mkdirs()) {
            throw new IllegalArgumentException("Output must be a new directory");
        }
        System.load(new File(args[0]).getAbsolutePath());
        // This native method parses shader resources; it does not execute the DLL.
        int result = new NativeBridge().extractShaders(args[1], "", output.getAbsolutePath());
        System.out.println("EXTRACTION_RESULT=" + result);
        if (result != 0) throw new IllegalStateException("Private extraction failed: " + result);
    }
}
