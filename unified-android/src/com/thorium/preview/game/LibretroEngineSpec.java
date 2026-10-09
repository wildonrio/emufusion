package com.thorium.preview.game;

import android.content.Context;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Runtime-neutral identity consumed by EmuFusion's single software-core session. */
final class LibretroEngineSpec {
    interface Verifier { boolean isInstalled(Context context, LibretroEngineSpec spec); }
    interface SystemInstaller {
        SystemInstallation install(Context context, String systemId) throws Exception;
    }

    static final class SystemInstallation {
        final File directory;
        final String firmwareIdentity;

        SystemInstallation(File directory, String firmwareIdentity) {
            this.directory = directory;
            this.firmwareIdentity = firmwareIdentity;
        }
    }

    final String id;
    final List<String> systems;
    final String sourceCommit;
    final String coreArtifactSha256;
    final boolean phaseTwoQualification;
    final int stateCompatibilityVersion;
    final boolean firmwareRequired;
    final List<String> acceptedFirmwareHashes;
    final File coreFile;
    final String runtime;
    private final Verifier verifier;
    private final SystemInstaller systemInstaller;

    LibretroEngineSpec(String id, List<String> systems, String sourceCommit,
            String coreArtifactSha256, boolean phaseTwoQualification,
            int stateCompatibilityVersion, boolean firmwareRequired,
            List<String> acceptedFirmwareHashes, File coreFile, String runtime,
            Verifier verifier,
            SystemInstaller systemInstaller) {
        this.id = id;
        this.systems = Collections.unmodifiableList(new ArrayList<>(systems));
        this.sourceCommit = sourceCommit;
        this.coreArtifactSha256 = coreArtifactSha256;
        this.phaseTwoQualification = phaseTwoQualification;
        this.stateCompatibilityVersion = stateCompatibilityVersion;
        this.firmwareRequired = firmwareRequired;
        this.acceptedFirmwareHashes = Collections.unmodifiableList(
                new ArrayList<>(acceptedFirmwareHashes));
        this.coreFile = coreFile;
        this.runtime = runtime;
        this.verifier = verifier;
        this.systemInstaller = systemInstaller;
    }

    static LibretroEngineSpec phaseOne(InternalEngineCatalog.Entry entry) {
        return new LibretroEngineSpec(entry.id, entry.systems, entry.sourceCommit,
                entry.coreArtifactSha256, false,
                entry.stateCompatibilityVersion, entry.firmwareRequired,
                entry.acceptedFirmwareHashes, entry.coreFile,
                "opengl".equals(entry.renderer) ? "gles-libretro" : "software",
                (context, spec) -> {
                    InternalEngineCatalog.Entry installed =
                            InternalEngineCatalog.byId(context, spec.id);
                    return installed != null && installed.coreFile.equals(spec.coreFile) &&
                            installed.sourceCommit.equals(spec.sourceCommit) &&
                            installed.coreArtifactSha256.equals(spec.coreArtifactSha256);
                }, null);
    }

    static LibretroEngineSpec phaseTwo(Phase2QualificationCatalog.Entry entry) {
        return new LibretroEngineSpec(entry.id, entry.systems, entry.sourceCommit,
                entry.coreArtifactSha256, true,
                entry.stateCompatibilityVersion, false, Collections.emptyList(),
                entry.coreFile, entry.runtime,
                (context, spec) -> {
                    Phase2QualificationCatalog.Entry installed =
                            Phase2QualificationCatalog.byId(context, spec.id);
                    return installed != null && installed.coreFile.equals(spec.coreFile) &&
                            installed.sourceCommit.equals(spec.sourceCommit) &&
                            installed.coreArtifactSha256.equals(spec.coreArtifactSha256);
                },
                (context, systemId) -> {
                    Phase2QualificationCatalog.RuntimeInstallation installed =
                            entry.installRuntimeAssets(context, systemId);
                    return new SystemInstallation(installed.directory,
                            installed.firmwareIdentity);
                });
    }

    boolean supports(String systemId) { return systems.contains(systemId); }

    boolean isInstalled(Context context) {
        return verifier != null && verifier.isInstalled(context, this);
    }

    File installSystem(Context context, String systemId) throws Exception {
        return installRuntime(context, systemId).directory;
    }

    SystemInstallation installRuntime(Context context, String systemId) throws Exception {
        if (systemInstaller != null) return systemInstaller.install(context, systemId);
        File root = context.getDir("engine-system", Context.MODE_PRIVATE);
        File system = new File(root, id);
        if (!system.isDirectory() && !system.mkdirs())
            throw new IllegalStateException("Cannot create engine system directory");
        String firmware = "beetle-pce-fast".equals(id) && "pcenginecd".equals(systemId)
                ? PcEngineCdFirmware.install(system) : "firmware:none";
        return new SystemInstallation(system, firmware);
    }
}
