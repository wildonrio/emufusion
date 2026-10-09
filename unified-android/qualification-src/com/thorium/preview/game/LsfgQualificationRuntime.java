package com.thorium.preview.game;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.HashSet;

/** Validates the owner's private, temporary LSFG shader import before JNI. */
final class LsfgQualificationRuntime {
    private static final String WRAPPER_COMMIT =
            "3e89e5439a98f55d5acb003d20039426ab24e69c";
    private static final String DLL_SHA256 =
            "fe0faeb147accab84539ac2bdcaa4eb3dec850752a336e710b85fc87477004e4";
    private static final String NATIVE_BUILD_ID =
            "emufusion-lsfg-live-surface-control-v8-" + WRAPPER_COMMIT;
    private static final int SHADER_COUNT = 48;

    static synchronized Prepared open(Context context) throws Exception {
        if (context == null) throw new IllegalArgumentException("Context is required");
        File root = context.getDir("lsfg-private-qualification", Context.MODE_PRIVATE);
        File manifestFile = new File(root, "qualification-manifest.json");
        if (!manifestFile.isFile()) {
            File source = context.getExternalFilesDir("lsfg-private-import");
            if (source != null) importPrivatePayload(source, root);
        }
        File shaders = validatePayload(root, manifestFile);
        String buildId = NativeLsfgBridge.libraryBuildId();
        if (!NATIVE_BUILD_ID.equals(buildId))
            throw new IllegalStateException("LSFG qualification native build ID is invalid");
        return new Prepared(shaders, buildId);
    }

    // Qualification-only, invoked only when the owner selects LSFG. Never
    // overwrite an installed payload or import a DLL into runtime storage.
    static synchronized void importPrivatePayload(File source, File root) throws Exception {
        File targetManifest = new File(root, "qualification-manifest.json");
        if (targetManifest.isFile()) return;
        File sourceManifest = new File(source, "qualification-manifest.json");
        validatePayload(source, sourceManifest);
        if (!root.isDirectory() && !root.mkdirs())
            throw new IllegalStateException("cannot create private LSFG import directory");
        File stage = Files.createTempDirectory(root.toPath(), ".shader-import-").toFile();
        File stagedShaders = new File(stage, "shaders");
        File stagedManifest = new File(stage, "qualification-manifest.json");
        try {
            Files.createDirectory(stagedShaders.toPath());
            for (int resource = 353; resource <= 400; ++resource) {
                String name = resource + ".spv";
                Files.copy(new File(source, "shaders/" + name).toPath(),
                        new File(stagedShaders, name).toPath());
            }
            Files.copy(sourceManifest.toPath(), stagedManifest.toPath());
            validatePayload(stage, stagedManifest);
            File targetShaders = new File(root, "shaders");
            if (targetShaders.exists()) {
                // Recover an interrupted manifest-last commit only when every
                // already-copied shader matches. Never replace unknown content.
                validatePayload(root, stagedManifest);
            } else {
                Files.move(stagedShaders.toPath(), targetShaders.toPath());
            }
            Files.move(stagedManifest.toPath(), targetManifest.toPath());
        } finally {
            // Only the unique staging directory created above is disposable.
            for (int resource = 353; resource <= 400; ++resource)
                Files.deleteIfExists(new File(stagedShaders, resource + ".spv").toPath());
            Files.deleteIfExists(stagedShaders.toPath());
            Files.deleteIfExists(stagedManifest.toPath());
            Files.deleteIfExists(stage.toPath());
        }
    }

    private static File validatePayload(File root, File manifestFile) throws Exception {
        if (!manifestFile.isFile())
            throw new IllegalStateException("private LSFG qualification manifest is absent");
        if (new File(root, "Lossless.dll").exists())
            throw new IllegalStateException("Lossless.dll must not remain in runtime storage");
        JSONObject manifest = new JSONObject(new String(
                Files.readAllBytes(manifestFile.toPath()), StandardCharsets.UTF_8));
        if (manifest.getInt("schemaVersion") != 1 ||
                !WRAPPER_COMMIT.equals(manifest.getString("wrapperCommit")) ||
                !DLL_SHA256.equals(manifest.getString("sourceDllSha256")) ||
                manifest.getBoolean("dllPackaged") ||
                manifest.getBoolean("dllExecuted") ||
                manifest.getInt("generationCount") != 1 ||
                Double.compare(manifest.getDouble("fixedPhase"), 0.5) != 0)
            throw new IllegalStateException("private LSFG manifest identity is invalid");
        File shaders = new File(root, "shaders");
        JSONArray files = manifest.getJSONArray("shaders");
        if (!shaders.isDirectory() || files.length() != SHADER_COUNT)
            throw new IllegalStateException("private LSFG shader set is incomplete");
        HashSet<String> names = new HashSet<>();
        for (int index = 0; index < files.length(); ++index) {
            JSONObject entry = files.getJSONObject(index);
            String name = entry.getString("name");
            if (name.isEmpty() || name.contains("/") || name.contains("\\") ||
                    !name.endsWith(".spv") || !names.add(name))
                throw new IllegalStateException("private LSFG shader name is unsafe");
            File shader = new File(shaders, name);
            long bytes = entry.getLong("bytes");
            if (!shader.isFile() || bytes <= 0L || shader.length() != bytes ||
                    !entry.getString("sha256").equals(sha256(shader)))
                throw new IllegalStateException("private LSFG shader identity mismatch");
        }
        for (int resource = 353; resource <= 400; ++resource) {
            if (!names.contains(resource + ".spv"))
                throw new IllegalStateException(
                        "private LSFG FP32 shader resource set is incomplete");
        }
        return shaders;
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                if (count > 0) digest.update(buffer, 0, count);
            }
        }
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest())
            result.append(String.format(java.util.Locale.US, "%02x", value & 0xff));
        return result.toString();
    }

    static final class Prepared {
        final File shaderDirectory;
        final String nativeBuildId;
        Prepared(File shaderDirectory, String nativeBuildId) {
            this.shaderDirectory = shaderDirectory;
            this.nativeBuildId = nativeBuildId;
        }
    }
}
