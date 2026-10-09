package org.yuzu.yuzu_emu.applets.keyboard;

import android.util.Log;

/**
 * Switch software-keyboard applet bridge.
 *
 * <p>Eden's {@code JNI_OnLoad} calls
 * {@code Common::Android::SoftwareKeyboard::InitJNI}, which resolves this class,
 * both nested types, and the two static entry points below. A missing one
 * leaves a pending exception and aborts the process at load, so all three
 * classes must exist before the adapter is opened.
 *
 * <p>The two nested types are read field-by-field by
 * common/android/applets/software_keyboard.cpp when a title actually opens a
 * text field, so every field it names is declared here with its exact type.
 *
 * <p>Lucent has no on-screen keyboard yet -- the planned one lives on the
 * second screen -- so {@link #executeNormal} reports Cancel rather than
 * inventing input. A title that demands text will see the user having dismissed
 * the keyboard, which is a state games already handle, instead of receiving a
 * fabricated string.
 */
public final class SoftwareKeyboard {
    private static final String TAG = "LucentEdenBridge";

    private SoftwareKeyboard() {}

    /** Mirrors Service::AM::Frontend::SwkbdResult: Ok = 0, Cancel = 1. */
    private static final int RESULT_CANCEL = 1;

    /**
     * Inline mode: the game draws its own text and expects incremental edits.
     * Lucent sends none, which leaves the game's field untouched.
     */
    public static void executeInline(KeyboardConfig config) {
        Log.i(TAG, "eden requested the inline software keyboard; Lucent has no "
                + "keyboard surface yet, so no text is delivered");
    }

    /** Normal mode: a modal keyboard. Reported as dismissed by the user. */
    public static KeyboardData executeNormal(KeyboardConfig config) {
        Log.i(TAG, "eden requested the modal software keyboard; reporting Cancel");
        return new KeyboardData(RESULT_CANCEL, "");
    }

    /**
     * Resolved as {@code SoftwareKeyboard$KeyboardConfig}. Field names and types
     * are copied from software_keyboard.cpp and must match it exactly; the
     * snake_case is Eden's, not Lucent's style.
     */
    public static final class KeyboardConfig {
        public int type;
        public String ok_text;
        public String header_text;
        public String sub_text;
        public String guide_text;
        public String initial_text;
        public short left_optional_symbol_key;
        public short right_optional_symbol_key;
        public int max_text_length;
        public int min_text_length;
        public int initial_cursor_position;
        public int password_mode;
        public int text_draw_type;
        public int key_disable_flags;
        public boolean use_blur_background;
        public boolean enable_backspace_button;
        public boolean enable_return_button;
        public boolean disable_cancel_button;

        public KeyboardConfig() {}
    }

    /** Resolved as {@code SoftwareKeyboard$KeyboardData}. */
    public static final class KeyboardData {
        public int result;
        public String text;

        public KeyboardData(int result, String text) {
            this.result = result;
            this.text = text;
        }
    }
}
