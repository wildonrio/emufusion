package com.thorium.lucent.input;

/** One finger owns a stick until release; independent of Android pointer indices. */
public final class TouchAnalogStick {
    private int pointerId = -1;
    private float x, y;

    public int pointerId() { return pointerId; }
    public float x() { return x; }
    public float y() { return y; }
    public boolean owns(int id) { return pointerId >= 0 && pointerId == id; }

    public boolean begin(int id, float dx, float dy, float radius) {
        if (id < 0 || pointerId >= 0 || !Float.isFinite(radius) || radius <= 0f ||
                !Float.isFinite(dx) || !Float.isFinite(dy) ||
                Math.hypot(dx, dy) > radius) return false;
        pointerId = id;
        move(id, dx, dy, radius);
        return true;
    }

    public void move(int id, float dx, float dy, float radius) {
        if (!owns(id)) return;
        if (!Float.isFinite(dx) || !Float.isFinite(dy) ||
                !Float.isFinite(radius) || radius <= 0f) {
            x = y = 0f;
            return;
        }
        double distance = Math.hypot(dx, dy);
        double fraction = distance / radius;
        // Radial dead zone, preserving direction and gradual movement speed.
        double magnitude = Math.max(0.0, Math.min(1.0, (fraction - 0.12) / 0.88));
        x = distance == 0.0 ? 0f : (float)(dx / distance * magnitude);
        y = distance == 0.0 ? 0f : (float)(dy / distance * magnitude);
    }

    public void release(int id) { if (owns(id)) reset(); }
    public void reset() { pointerId = -1; x = y = 0f; }
}
