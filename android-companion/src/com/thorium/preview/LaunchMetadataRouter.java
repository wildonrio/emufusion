package com.thorium.preview;

import android.content.Context;
import android.os.Environment;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import com.thorium.lucent.metadata.MetadataLaunchNormalizer;

/** Replaces stale launch commands with EmuFusion's sole in-window route. */
final class LaunchMetadataRouter {
    private static final String TAG = "LucentLaunchMetadata";
    static int normalize(Context context) {
        File storage = Environment.getExternalStorageDirectory();
        List<File> roots = Arrays.asList(
                new File(storage, "pegasus-frontend"),
                new File(storage, "Android/data/org.pegasus_frontend.android/files/pegasus-frontend"),
                new File(storage, "Android/data/com.thorium.preview/files/pegasus-frontend"));
        Set<String> visited = new LinkedHashSet<>();
        int changed = 0;
        for (File root : roots) {
            for (File directory : Arrays.asList(root, new File(root, "metadata"),
                    new File(root, "metafiles"), new File(root, "metadata-systems"))) {
                File[] files = directory.listFiles((parent, name) ->
                        // EmuFusion has historically emitted both
                        // <system>.metadata.pegasus.txt and aggregate names
                        // such as metadata.complete.pegasus.txt. Normalize all
                        // Pegasus metadata variants so a later copy/restore
                        // cannot resurrect a stale standalone-emulator route.
                        name.endsWith(".pegasus.txt"));
                if (files == null) continue;
                for (File file : files) try {
                    String canonical = file.getCanonicalPath();
                    if (visited.add(canonical) && rewrite(context, file)) changed++;
                } catch (Exception error) {
                    Log.w(TAG, "Could not inspect " + file, error);
                }
            }
        }
        return changed;
    }

    private static boolean rewrite(Context context, File file) throws Exception {
        String text = read(file);
        String updated = MetadataLaunchNormalizer.rewrite(text, system ->
                EngineRouteStore.launchCommand(context, system));
        if (updated.equals(text)) return false;
        writeAtomic(file, updated);
        return true;
    }

    private static String read(File file) throws Exception {
        StringBuilder out = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                new FileInputStream(file), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) out.append(line).append('\n');
        }
        return out.toString();
    }

    private static void writeAtomic(File target, String text) throws Exception {
        File temporary = new File(target.getParentFile(), "." + target.getName() + ".lucent-route.tmp");
        try (OutputStreamWriter writer = new OutputStreamWriter(
                new FileOutputStream(temporary, false), StandardCharsets.UTF_8)) {
            writer.write(text);
            writer.flush();
        }
        if (target.isFile() && !target.delete()) throw new java.io.IOException("replace failed");
        if (!temporary.renameTo(target)) throw new java.io.IOException("commit failed");
    }

    private LaunchMetadataRouter() {}
}
