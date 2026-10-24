package com.thorium.preview;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.util.Log;

import java.io.File;

/**
 * Drops Qt's compiled-QML cache once per installed build.
 *
 * <p>Qt keeps compiled QML in {@code cache/qmlcache} and trusts an entry while
 * its source timestamp matches. For the frontend's embedded (qrc) QML that is
 * the timestamp stored in the library's resources, which in-place frontend
 * patches do not change, so the Thor ran its September 13 compilations of
 * Pegasus's own QML through every later update: a splash animation the
 * frontend patch stops kept running, and the library redrew every refresh
 * (2026-10-24). The theme recompiles once on the first launch after an
 * update.</p>
 */
final class QmlCacheReset {
    private static final String TAG = "EmuFusionQml";
    private static final String PREFS = "emufusion-qml-cache";
    private static final String KEY = "installed";

    private QmlCacheReset() {}

    /** Call before Qt starts (Application.onCreate). */
    static void discardIfUpdated(Context context) {
        long installed;
        try {
            installed = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).lastUpdateTime;
        } catch (PackageManager.NameNotFoundException impossible) {
            return;
        }
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (prefs.getLong(KEY, -1L) == installed) return;
        int removed = 0;
        File[] files = new File(context.getCacheDir(), "qmlcache").listFiles();
        if (files != null) {
            for (File file : files) if (file.isFile() && file.delete()) removed++;
        }
        prefs.edit().putLong(KEY, installed).commit();
        Log.i(TAG, "Compiled QML cache cleared for this install files=" + removed);
    }
}
