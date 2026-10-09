package com.thorium.preview.game;

import android.view.MotionEvent;
import com.thorium.lucent.video.DualScreenLayout;

/** One finger owns the emulated stylus; unrelated fingers cannot release it. */
final class ThreeDsPhoneStylus {
    static final class State {
        final short x, y;
        final boolean pressed;
        State(short x, short y, boolean pressed) {
            this.x = x;
            this.y = y;
            this.pressed = pressed;
        }
    }

    private int pointerId = -1;
    private State state = new State((short) 0, (short) 0, false);

    State release() {
        pointerId = -1;
        state = new State(state.x, state.y, false);
        return state;
    }

    State update(MotionEvent event, int width, int height) {
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) {
            release();
            DualScreenLayout.TouchPoint start = DualScreenLayout.threeDsPhoneTouchPoint(
                    event.getX(0), event.getY(0), width, height);
            if (start.inside) pointerId = event.getPointerId(0);
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL ||
                (action == MotionEvent.ACTION_POINTER_UP &&
                 event.getPointerId(event.getActionIndex()) == pointerId)) return release();
        int index = event.findPointerIndex(pointerId);
        if (index < 0) return release();
        DualScreenLayout.TouchPoint point = DualScreenLayout.threeDsPhoneTouchPoint(
                event.getX(index), event.getY(index), width, height);
        state = new State(DualScreenLayout.threeDsSideBySidePointerX(point.x),
                DualScreenLayout.threeDsSideBySidePointerY(point.y), point.inside);
        return state;
    }
}
