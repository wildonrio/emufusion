package com.thorium.preview;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/** Read-only, exact-file provider used only for Android's package installer. */
public final class UpdateFileProvider extends ContentProvider {
    static final String FILE_NAME = "pegasus-lucent-update.apk";

    private File updateFile() {
        File folder = getContext().getExternalFilesDir("updates");
        if (folder == null) folder = new File(getContext().getCacheDir(), "updates");
        return new File(folder, FILE_NAME);
    }

    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection,
                                  String[] selectionArgs, String sortOrder) {
        File file = updateFile();
        MatrixCursor cursor = new MatrixCursor(new String[]{
                OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE});
        cursor.addRow(new Object[]{"EmuFusion.apk", file.length()});
        return cursor;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode)
            throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read only");
        File file = updateFile();
        if (!file.isFile()) throw new FileNotFoundException("No downloaded update");
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] selectionArgs) { return 0; }
    @Override public int update(Uri uri, ContentValues values, String selection,
                                String[] selectionArgs) { return 0; }
}
