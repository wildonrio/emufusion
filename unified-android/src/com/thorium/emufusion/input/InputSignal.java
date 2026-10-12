package com.thorium.emufusion.input;

import java.util.Objects;

/** A physical Android key or one direction of an Android motion axis. */
public final class InputSignal {
    public enum Type { KEY, AXIS }
    public final Type type;
    public final int code;
    public final int direction;

    private InputSignal(Type type, int code, int direction) {
        this.type = type;
        this.code = code;
        this.direction = direction;
    }

    public static InputSignal key(int keyCode) {
        return new InputSignal(Type.KEY, keyCode, 0);
    }

    public static InputSignal axis(int axisCode, int direction) {
        if (direction != -1 && direction != 1)
            throw new IllegalArgumentException("Axis direction must be -1 or 1");
        return new InputSignal(Type.AXIS, axisCode, direction);
    }

    public String encode() {
        return type == Type.KEY ? "k:" + code : "a:" + code + ":" + direction;
    }

    public static InputSignal decode(String encoded) {
        if (encoded == null) throw new IllegalArgumentException("Missing input signal");
        String[] parts = encoded.split(":");
        try {
            if (parts.length == 2 && "k".equals(parts[0])) return key(Integer.parseInt(parts[1]));
            if (parts.length == 3 && "a".equals(parts[0]))
                return axis(Integer.parseInt(parts[1]), Integer.parseInt(parts[2]));
        } catch (NumberFormatException invalid) {
            throw new IllegalArgumentException("Invalid input signal " + encoded, invalid);
        }
        throw new IllegalArgumentException("Invalid input signal " + encoded);
    }

    @Override public boolean equals(Object value) {
        if (!(value instanceof InputSignal)) return false;
        InputSignal other = (InputSignal) value;
        return type == other.type && code == other.code && direction == other.direction;
    }

    @Override public int hashCode() { return Objects.hash(type, code, direction); }
    @Override public String toString() { return encode(); }
}
