package com.thorium.nxnative;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.PixelFormat;
import android.os.Bundle;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.util.Locale;

/**
 * One game, one process: the Activity runs in a process of its own and leaving the game ends that process.
 * The game comes in the intent's "nxpack" extra, the path of the .nxpack file in its pack folder, or its "pack" extra, the folder itself (dm/android/README.md).
 */
public final class NxActivity extends Activity implements SurfaceHolder.Callback {
    // nn::hid::NpadButton bits (dm/host/dm_input.h)
    private static final long A = 1, B = 1 << 1, X = 1 << 2, Y = 1 << 3, LS = 1 << 4, RS = 1 << 5, L = 1 << 6, R = 1 << 7, ZL = 1 << 8, ZR = 1 << 9,
            PLUS = 1 << 10, MINUS = 1 << 11, LEFT = 1 << 12, UP = 1 << 13, RIGHT = 1 << 14, DOWN = 1 << 15;
    private static final int STICK = 32767;

    private String pack;
    private String language;   // the game's language: null until it is known (asked once when the game has several)
    private SurfaceHolder holder;
    private int surfaceWidth, surfaceHeight;
    private long keys, hat, triggers;
    private int lx, ly, rx, ry;

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        Intent intent = getIntent();
        String file = intent.getStringExtra("nxpack");
        pack = file != null ? new File(file).getParent() : intent.getStringExtra("pack");
        if (pack == null) pack = "/sdcard/Games/switchnative/010015100B514000";
        String env = intent.getStringExtra("env");
        if (env != null) for (String kv : env.split(";")) { int eq = kv.indexOf('='); if (eq > 0) NxNative.nativeSetEnv(kv.substring(0, eq), kv.substring(eq + 1)); }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().setFormat(PixelFormat.RGBA_8888);
        SurfaceView view = new SurfaceView(this);
        view.getHolder().addCallback(this);
        view.setFocusable(true);
        view.setFocusableInTouchMode(true);
        setContentView(view);
        view.requestFocus();
        view.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        chooseLanguage(intent.getStringExtra("lang"));
    }

    /** The language the pack was built with, the one chosen before, or the player's choice among the game's when it has several and none was chosen yet. */
    private void chooseLanguage(String asked) {
        if (asked != null) { language = asked; return; }
        String packed = "en-US", title = new File(pack).getName(); String[] codes = new String[0];
        try (FileInputStream in = new FileInputStream(new File(pack, "manifest.json"))) {
            byte[] raw = new byte[(int) new File(pack, "manifest.json").length()];
            int got = 0, n; while (got < raw.length && (n = in.read(raw, got, raw.length - got)) > 0) got += n;
            JSONObject m = new JSONObject(new String(raw, 0, got, "UTF-8"));
            packed = m.optString("language", packed);
            JSONArray list = m.optJSONArray("languages");
            if (list != null) { codes = new String[list.length()]; for (int i = 0; i < codes.length; i++) codes[i] = list.getString(i); }
        } catch (Exception unreadable) { /* a pack without a manifest plays in the default language */ }
        final SharedPreferences prefs = getSharedPreferences("nxnative", MODE_PRIVATE);
        final String key = "language." + title;
        String kept = prefs.getString(key, null);
        if (kept != null) { language = kept; return; }
        if (codes.length < 2) { language = packed; return; }
        final String[] choices = codes; final String fallback = packed;
        String[] names = new String[choices.length];
        for (int i = 0; i < names.length; i++) names[i] = Locale.forLanguageTag(choices[i]).getDisplayName();
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle("Game language")
                .setItems(names, (dialog, which) -> { prefs.edit().putString(key, choices[which]).apply(); language = choices[which]; start(); })
                .setOnCancelListener(dialog -> { language = fallback; start(); })
                .show();
    }

    private void start() {
        if (language == null || holder == null) return;
        File data = new File(getFilesDir(), "nx/" + new File(pack).getName());
        new File(data, "save").mkdirs();
        new File(data, "temp").mkdirs();
        NxNative.nativeStart(holder.getSurface(), pack, data.getPath(), language, surfaceWidth, surfaceHeight);
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {}

    @Override public void surfaceChanged(SurfaceHolder surface, int format, int width, int height) {
        holder = surface; surfaceWidth = width; surfaceHeight = height;
        start();
    }

    @Override public void surfaceDestroyed(SurfaceHolder holder) {}

    @Override protected void onPause() { super.onPause(); NxNative.nativePause(true); }

    @Override protected void onResume() { super.onResume(); NxNative.nativePause(false); }

    private static long button(int code) {
        switch (code) {
            // By position on the pad, as Nintendo's layout has them: the bottom button is B, the right one A
            case KeyEvent.KEYCODE_BUTTON_A: return B;
            case KeyEvent.KEYCODE_BUTTON_B: return A;
            case KeyEvent.KEYCODE_BUTTON_X: return Y;
            case KeyEvent.KEYCODE_BUTTON_Y: return X;
            case KeyEvent.KEYCODE_BUTTON_L1: return L;
            case KeyEvent.KEYCODE_BUTTON_R1: return R;
            case KeyEvent.KEYCODE_BUTTON_L2: return ZL;
            case KeyEvent.KEYCODE_BUTTON_R2: return ZR;
            case KeyEvent.KEYCODE_BUTTON_THUMBL: return LS;
            case KeyEvent.KEYCODE_BUTTON_THUMBR: return RS;
            case KeyEvent.KEYCODE_BUTTON_START: return PLUS;
            case KeyEvent.KEYCODE_BUTTON_SELECT: return MINUS;
            case KeyEvent.KEYCODE_DPAD_LEFT: return LEFT;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return RIGHT;
            case KeyEvent.KEYCODE_DPAD_UP: return UP;
            case KeyEvent.KEYCODE_DPAD_DOWN: return DOWN;
            default: return 0;
        }
    }

    private void sendPad() { NxNative.nativePad(keys | hat | triggers, lx, ly, rx, ry); }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (event.getKeyCode() == KeyEvent.KEYCODE_BACK) {
            if (event.getAction() == KeyEvent.ACTION_UP) quit();
            return true;
        }
        long b = button(event.getKeyCode());
        if (b == 0) return super.dispatchKeyEvent(event);
        if (event.getAction() == KeyEvent.ACTION_DOWN) keys |= b; else if (event.getAction() == KeyEvent.ACTION_UP) keys &= ~b;
        sendPad();
        return true;
    }

    @Override public boolean dispatchGenericMotionEvent(MotionEvent e) {
        if ((e.getSource() & InputDevice.SOURCE_JOYSTICK) == 0 || e.getAction() != MotionEvent.ACTION_MOVE) return super.dispatchGenericMotionEvent(e);
        lx = (int) (e.getAxisValue(MotionEvent.AXIS_X) * STICK);
        ly = (int) (-e.getAxisValue(MotionEvent.AXIS_Y) * STICK);
        rx = (int) (e.getAxisValue(MotionEvent.AXIS_Z) * STICK);
        ry = (int) (-e.getAxisValue(MotionEvent.AXIS_RZ) * STICK);
        float hx = e.getAxisValue(MotionEvent.AXIS_HAT_X), hy = e.getAxisValue(MotionEvent.AXIS_HAT_Y);
        hat = (hx < -0.5f ? LEFT : 0) | (hx > 0.5f ? RIGHT : 0) | (hy < -0.5f ? UP : 0) | (hy > 0.5f ? DOWN : 0);
        triggers = (e.getAxisValue(MotionEvent.AXIS_LTRIGGER) > 0.3f ? ZL : 0) | (e.getAxisValue(MotionEvent.AXIS_RTRIGGER) > 0.3f ? ZR : 0);
        sendPad();
        return true;
    }

    @Override public boolean onTouchEvent(MotionEvent e) {
        int n = e.getPointerCount(), up = -1;
        if (e.getActionMasked() == MotionEvent.ACTION_UP || e.getActionMasked() == MotionEvent.ACTION_POINTER_UP) up = e.getActionIndex();
        if (e.getActionMasked() == MotionEvent.ACTION_CANCEL) n = 0;
        int[] ids = new int[16]; float[] xs = new float[16], ys = new float[16]; int m = 0;
        View v = getWindow().getDecorView();
        for (int i = 0; i < n && m < 16; i++) {
            if (i == up) continue;
            ids[m] = e.getPointerId(i) & 15; xs[m] = e.getX(i) / v.getWidth(); ys[m] = e.getY(i) / v.getHeight(); m++;
        }
        NxNative.nativeTouch(ids, xs, ys, m);
        return true;
    }

    private void quit() { NxNative.nativeQuit(); finishAndRemoveTask(); }
}
