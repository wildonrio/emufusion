package com.thorium.preview.qa;

import java.io.Closeable;
import java.io.File;
import java.lang.reflect.InvocationTargetException;

/** Run in a disposable Android app_process with the exact installed APK on its
 * classpath. No Surface or emulated frame is created. Uses a separate QA save
 * directory, never the normal library's saves. */
public final class DolphinEarlyCloseProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 4)
            throw new IllegalArgumentException("core system qa-save-directory owned-rom");
        File core = new File(args[0]);
        File system = new File(args[1]);
        File saveRoot = new File(args[2]);
        File game = new File(args[3]);
        if (!saveRoot.getName().startsWith("qa-early-close-"))
            throw new IllegalArgumentException("a separate qa-early-close- directory is required");
        Class<?> hostType = Class.forName("com.thorium.preview.ExperimentalVulkanLibretroHost");
        for (int cycle = 0; cycle < 2; ++cycle) {
            Object host = hostType.getConstructor(File.class, File.class, File.class, File.class)
                    .newInstance(core, core.getParentFile(), system,
                            new File(saveRoot, "cycle-" + cycle));
            System.out.println("EARLY_CLOSE created cycle=" + cycle);
            try {
                hostType.getMethod("loadGame", File.class).invoke(host, game);
            } catch (InvocationTargetException failure) {
                throw new IllegalStateException("owned game did not load", failure.getCause());
            }
            System.out.println("EARLY_CLOSE loaded without Surface/frame cycle=" + cycle);
            ((Closeable) host).close();
            ((Closeable) host).close();
            System.out.println("EARLY_CLOSE closed twice cycle=" + cycle);
        }
        System.out.println("EARLY_CLOSE PASS two load/close cycles, zero emulated frames");
    }
}
