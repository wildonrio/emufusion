package com.thorium.preview.game;

import android.view.MotionEvent;

/** One stylus on the 16:9 GamePad picture, never on letterbox bars. */
final class WiiUPhoneTouch {
    static final class State {
        final float x, y;
        final boolean pressed;
        State(float x, float y, boolean pressed) {
            this.x = x;
            this.y = y;
            this.pressed = pressed;
        }
    }
    private int pointerId = -1;
    private State state = new State(0f, 0f, false);

    State release() {
        pointerId = -1;
        state = new State(state.x, state.y, false);
        return state;
    }

    State update(MotionEvent event, int width, int height) {
        if (width <= 0 || height <= 0) return release();
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) {
            release();
            if (inside(event.getX(0), event.getY(0), width, height))
                pointerId = event.getPointerId(0);
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL ||
                (action == MotionEvent.ACTION_POINTER_UP &&
                 event.getPointerId(event.getActionIndex()) == pointerId)) return release();
        int index = event.findPointerIndex(pointerId);
        if (index < 0) return release();
        float x = event.getX(index), y = event.getY(index);
        if (!Float.isFinite(x) || !Float.isFinite(y)) return release();
        // These are full-canvas coordinates. Cemu itself subtracts the
        // native 16:9 image rectangle before converting to VPAD touch units.
        state = new State(Math.max(0f, Math.min(1f, x / width)),
                Math.max(0f, Math.min(1f, y / height)), inside(x, y, width, height));
        return state;
    }

    private static boolean inside(float x, float y, int width, int height) {
        float imageWidth = Math.min(width, height * (16f / 9f));
        float imageHeight = imageWidth * (9f / 16f);
        float left = (width - imageWidth) * .5f, top = (height - imageHeight) * .5f;
        return Float.isFinite(x) && Float.isFinite(y) &&
                x >= left && x < left + imageWidth && y >= top && y < top + imageHeight;
    }
}
