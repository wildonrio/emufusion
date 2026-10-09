package com.thorium.lucent.navigation;

/**
 * Converts a two-axis right-stick sample into a debounced, one-shot direction.
 * The press and release thresholds intentionally differ so stick noise cannot
 * repeatedly switch EmuFusion views while the user holds one direction.
 */
public final class RightStickViewRouter {
    public enum Direction { NONE, UP, DOWN, LEFT, RIGHT }

    static final float PRESS_THRESHOLD = 0.72f;
    static final float RELEASE_THRESHOLD = 0.34f;

    private Direction direction = Direction.NONE;

    public Direction direction() { return direction; }

    public Direction update(float x, float y) {
        float absoluteX = Math.abs(x);
        float absoluteY = Math.abs(y);
        float threshold = direction == Direction.NONE ?
                PRESS_THRESHOLD : RELEASE_THRESHOLD;
        if (absoluteX < threshold && absoluteY < threshold) {
            direction = Direction.NONE;
            return direction;
        }

        // Do not acquire a new direction from a half-released neutral sample.
        if (direction == Direction.NONE &&
                absoluteX < PRESS_THRESHOLD && absoluteY < PRESS_THRESHOLD)
            return direction;

        if (absoluteX >= absoluteY)
            direction = x < 0 ? Direction.LEFT : Direction.RIGHT;
        else
            direction = y < 0 ? Direction.UP : Direction.DOWN;
        return direction;
    }
}
