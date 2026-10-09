package com.thorium.lucent.netplay;

/**
 * Where a remote player's input goes for the Phase 3 native-adapter engine
 * family (Eden/Switch, Cemu/Wii U, aPS3e/PS3) -- implemented by
 * {@code NativeAdapterEngineSession.applyRemoteControl} in
 * com.thorium.preview.game, referenced here only via method reference so
 * this package stays independent of the engine-session classes.
 *
 * <p>This is the native-adapter analogue of {@link RemoteJoypadSink}: kept
 * as its own, separate interface rather than folded into it because the
 * two families genuinely disagree on shape. A libretro/PPSSPP session
 * takes a boolean-pressed retro joypad ID on a port; a native-adapter
 * session takes a float value (buttons arrive as 0f/1f, but sticks and the
 * Wii U GamePad touch controls are genuinely analog) against the
 * {@code lucent_native_control} ordinal space on a controller_index. Forcing
 * both through one method would mean lying about one side's actual value
 * type.
 */
public interface NativeControlSink {
    void applyRemoteControl(int controllerIndex, int control, float value);
}
