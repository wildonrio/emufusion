package com.thorium.preview.game;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Host bridge executes the Android builder rather than duplicating it. */
public final class DenseMotionSynthesisShaderDump {
    public static void main(String[] args) throws Exception {
        try {
            DenseMotionSynthesisShader.build("");
            throw new AssertionError("Missing shader anchors must be rejected");
        } catch (IllegalArgumentException expected) {
            // Expected: a stale or mismatched base cannot silently build.
        }
        String base = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
        System.out.print(DenseMotionSynthesisShader.build(base));
    }
}
