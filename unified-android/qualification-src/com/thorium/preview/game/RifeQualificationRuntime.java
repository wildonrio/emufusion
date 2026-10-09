package com.thorium.preview.game;

import android.content.Context;
import android.content.res.AssetManager;
import android.os.Build;

import com.emufusion.rifebenchmark.ModelIntegrity;
import com.emufusion.rifebenchmark.NativeRifeBridge;
import com.thorium.lucent.video.FrameGenerationBackendPolicy;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;

/**
 * Qualification-APK-only RIFE payload verifier and cold initialization gate.
 *
 * <p>This class is not compiled into a normal EmuFusion APK. Passing this gate
 * proves the exact lawful payload can initialize on this device; it does not
 * prove output correctness or live deadline performance and therefore never
 * returns a usable product assessment by itself.</p>
 */
public final class RifeQualificationRuntime {
    private static final String ASSET_ROOT = "framegen/rife-v4.6/";
    private static final String MANIFEST_ASSET =
            ASSET_ROOT + "qualification-manifest.json";
    private static final String EXPECTED_KIND =
            "rife-v4.6-framegen-qualification-only";
    private static final String EXPECTED_RIFE_COMMIT =
            "a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7";
    private static final String EXPECTED_PRACTICAL_COMMIT =
            "f6b5132517695127bdb5d5a8c3727e719f0fda22";
    private static final String EXPECTED_NCNN_COMMIT =
            "e54f7b1f88434e1d844ea0551b880a1cfb079ce1";

    private RifeQualificationRuntime() {}

    /** Background-safe package/ABI/model/Vulkan initialization assessment. */
    public static FrameGenerationBackendPolicy.Assessment assessPackage(Context context) {
        try (Prepared prepared = open(context)) {
            return new FrameGenerationBackendPolicy.Assessment(
                    true, true, true, false, false,
                    "RIFE package and Vulkan initialization passed; " +
                            "live output/deadline self-test pending");
        } catch (Throwable failure) {
            return FrameGenerationBackendPolicy.Assessment.unavailable(
                    "RIFE qualification preflight failed: " +
                            failure.getClass().getSimpleName());
        }
    }

    /** Opens an exact verified native/model instance for the later output self-test. */
    public static Prepared open(Context context) throws Exception {
        if (context == null) throw new IllegalArgumentException("Context is required");
        if (Build.VERSION.SDK_INT < 33)
            throw new UnsupportedOperationException("RIFE Image fence ownership requires API 33+");
        boolean arm64 = false;
        for (String abi : Build.SUPPORTED_64_BIT_ABIS) {
            if ("arm64-v8a".equals(abi)) arm64 = true;
        }
        if (!arm64) throw new UnsupportedOperationException("RIFE payload is arm64-v8a only");

        Context app = context.getApplicationContext();
        AssetManager assets = app.getAssets();
        JSONObject manifest = new JSONObject(readUtf8(assets, MANIFEST_ASSET));
        validateManifest(manifest);
        File modelDirectory = prepareModels(app, assets, manifest);
        ModelIntegrity.verify(modelDirectory);

        String expectedBuildId = manifest.getJSONObject("nativeLibrary")
                .getString("buildId");
        String actualBuildId = NativeRifeBridge.libraryBuildId();
        if (!expectedBuildId.equals(actualBuildId))
            throw new SecurityException("RIFE native GNU Build ID mismatch");

        NativeRifeBridge bridge = new NativeRifeBridge(
                modelDirectory.getAbsolutePath(), 0, 2);
        boolean success = false;
        try {
            JSONObject capabilities = new JSONObject(bridge.capabilitiesJson());
            validateCapabilities(capabilities, expectedBuildId);
            Prepared prepared = new Prepared(
                    bridge, modelDirectory, manifest, capabilities);
            success = true;
            return prepared;
        } finally {
            if (!success) bridge.close();
        }
    }

    private static void validateManifest(JSONObject manifest) throws Exception {
        if (manifest.getInt("schemaVersion") != 1 ||
                !EXPECTED_KIND.equals(manifest.getString("kind")) ||
                manifest.getBoolean("productIntegrationAllowed") ||
                manifest.getBoolean("routeProductFramesToProvider") ||
                !EXPECTED_RIFE_COMMIT.equals(manifest.getString("rifeCommit")) ||
                !EXPECTED_PRACTICAL_COMMIT.equals(
                        manifest.getString("practicalRifeCommit")) ||
                !EXPECTED_NCNN_COMMIT.equals(manifest.getString("ncnnCommit")))
            throw new SecurityException("RIFE qualification manifest identity changed");
        JSONObject models = manifest.getJSONObject("models");
        validateModelManifest(models.getJSONObject("flownet.param"),
                ModelIntegrity.PARAM_BYTES, ModelIntegrity.PARAM_SHA256);
        validateModelManifest(models.getJSONObject("flownet.bin"),
                ModelIntegrity.MODEL_BYTES, ModelIntegrity.MODEL_SHA256);
        JSONObject nativeLibrary = manifest.getJSONObject("nativeLibrary");
        if (!"lib/arm64-v8a/librife_benchmark.so".equals(
                    nativeLibrary.getString("path")) ||
                !nativeLibrary.getString("sha256").matches("[0-9a-f]{64}") ||
                !nativeLibrary.getString("buildId").matches("[0-9a-f]{40}"))
            throw new SecurityException("RIFE native manifest identity is invalid");
    }

    private static void validateModelManifest(
            JSONObject model, long bytes, String sha256) throws Exception {
        if (model.getLong("bytes") != bytes || !sha256.equals(model.getString("sha256")))
            throw new SecurityException("RIFE model manifest identity changed");
    }

    private static void validateCapabilities(
            JSONObject capabilities, String buildId) throws Exception {
        if (!"vulkan".equals(capabilities.getString("actualBackend")) ||
                !capabilities.getBoolean("vulkanBackendVerified") ||
                capabilities.getBoolean("cpuFallbackAllowed") ||
                !capabilities.getBoolean("ahardwareBufferImportSupported") ||
                !capabilities.getBoolean("gpuResidentRecordApiCompiled") ||
                !capabilities.getBoolean(
                        "highDetailPresentedImageProofCompiled") ||
                !capabilities.getBoolean("nonBlockingSubmissionApiCompiled") ||
                !capabilities.getBoolean("nonBlockingSubmissionSupported") ||
                !capabilities.getBoolean("androidSurfaceExtensionSupported") ||
                !capabilities.getBoolean("swapchainExtensionSupported") ||
                capabilities.getInt("gpuCount") < 1 ||
                !buildId.equals(capabilities.getString("nativeBuildId")))
            throw new UnsupportedOperationException(
                    "RIFE Vulkan/AHardwareBuffer capability contract failed");
    }

    private static File prepareModels(
            Context context, AssetManager assets, JSONObject manifest) throws Exception {
        File parent = new File(context.getNoBackupFilesDir(), "framegen");
        File directory = new File(parent, "rife-v4.6");
        if ((!directory.isDirectory() && !directory.mkdirs()) ||
                !directory.getCanonicalFile().getParentFile().equals(
                        parent.getCanonicalFile()))
            throw new IOException("Unable to create private RIFE model directory");
        JSONObject models = manifest.getJSONObject("models");
        prepareModel(assets, directory, "flownet.param",
                models.getJSONObject("flownet.param"));
        prepareModel(assets, directory, "flownet.bin",
                models.getJSONObject("flownet.bin"));
        return directory;
    }

    private static void prepareModel(
            AssetManager assets, File directory, String name, JSONObject identity)
            throws Exception {
        File target = new File(directory, name);
        long bytes = identity.getLong("bytes");
        String sha256 = identity.getString("sha256");
        if (target.isFile() && target.length() == bytes &&
                sha256.equals(ModelIntegrity.sha256(target))) return;

        File temporary = new File(directory, name + ".tmp");
        if (temporary.exists() && !temporary.delete())
            throw new IOException("Unable to replace stale RIFE model temporary file");
        try (InputStream input = assets.open(ASSET_ROOT + name,
                    AssetManager.ACCESS_STREAMING);
             FileOutputStream output = new FileOutputStream(temporary)) {
            byte[] buffer = new byte[256 * 1024];
            long copied = 0L;
            while (true) {
                int count = input.read(buffer);
                if (count < 0) break;
                output.write(buffer, 0, count);
                copied += count;
            }
            output.getFD().sync();
            if (copied != bytes || temporary.length() != bytes ||
                    !sha256.equals(ModelIntegrity.sha256(temporary)))
                throw new SecurityException("Extracted RIFE model identity mismatch: " + name);
        } catch (Throwable failure) {
            temporary.delete();
            throw failure;
        }
        if (target.exists() && !target.delete()) {
            temporary.delete();
            throw new IOException("Unable to replace prior RIFE model: " + name);
        }
        if (!temporary.renameTo(target)) {
            temporary.delete();
            throw new IOException("Unable to atomically install RIFE model: " + name);
        }
    }

    private static String readUtf8(AssetManager assets, String name) throws IOException {
        try (InputStream input = assets.open(name, AssetManager.ACCESS_STREAMING)) {
            java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            while (true) {
                int count = input.read(buffer);
                if (count < 0) break;
                output.write(buffer, 0, count);
            }
            return output.toString("UTF-8");
        }
    }

    public static final class Prepared implements AutoCloseable {
        public final NativeRifeBridge bridge;
        public final File modelDirectory;
        public final JSONObject manifest;
        public final JSONObject capabilities;

        private Prepared(NativeRifeBridge bridge, File modelDirectory,
                         JSONObject manifest, JSONObject capabilities) {
            this.bridge = bridge;
            this.modelDirectory = modelDirectory;
            this.manifest = manifest;
            this.capabilities = capabilities;
        }

        @Override public void close() { bridge.close(); }
    }
}
