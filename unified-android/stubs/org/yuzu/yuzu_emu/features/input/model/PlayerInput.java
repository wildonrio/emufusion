package org.yuzu.yuzu_emu.features.input.model;

/**
 * Eden's per-player controller profile. Lucent routes input through its own
 * InputRouter and never builds one of these, but Eden's JNI cache resolves the
 * constructor and all twelve fields at load time, so the declared types must
 * match common/android/id_cache.cpp exactly.
 */
public final class PlayerInput {
    public boolean connected;
    public String[] buttons;
    public String[] analogs;
    public String[] motions;
    public boolean vibrationEnabled;
    public int vibrationStrength;
    public long bodyColorLeft;
    public long bodyColorRight;
    public long buttonColorLeft;
    public long buttonColorRight;
    public String profileName;
    public boolean useSystemVibrator;

    public PlayerInput(boolean connected, String[] buttons, String[] analogs,
                       String[] motions, boolean vibrationEnabled,
                       int vibrationStrength, long bodyColorLeft,
                       long bodyColorRight, long buttonColorLeft,
                       long buttonColorRight, String profileName,
                       boolean useSystemVibrator) {
        this.connected = connected;
        this.buttons = buttons;
        this.analogs = analogs;
        this.motions = motions;
        this.vibrationEnabled = vibrationEnabled;
        this.vibrationStrength = vibrationStrength;
        this.bodyColorLeft = bodyColorLeft;
        this.bodyColorRight = bodyColorRight;
        this.buttonColorLeft = buttonColorLeft;
        this.buttonColorRight = buttonColorRight;
        this.profileName = profileName;
        this.useSystemVibrator = useSystemVibrator;
    }
}
