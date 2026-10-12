package com.thorium.emufusion.navigation;

import android.app.Activity;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;

import java.util.WeakHashMap;

/** Routes the right joystick to private Qt key commands without replacing QtActivity. */
public final class RightStickMotionBridge {
    private static final WeakHashMap<Activity, RightStickViewRouter> ROUTERS =
            new WeakHashMap<>();

    private RightStickMotionBridge() {}

    public static boolean dispatch(Activity activity, MotionEvent event) {
        if (activity == null || event == null ||
                event.getActionMasked() != MotionEvent.ACTION_MOVE ||
                (event.getSource() & InputDevice.SOURCE_JOYSTICK) !=
                        InputDevice.SOURCE_JOYSTICK) {
            return false;
        }

        RightStickViewRouter router;
        synchronized (ROUTERS) {
            router = ROUTERS.get(activity);
            if (router == null) {
                router = new RightStickViewRouter();
                ROUTERS.put(activity, router);
            }
        }

        float horizontal = axis(event, MotionEvent.AXIS_Z, MotionEvent.AXIS_RX);
        float vertical = axis(event, MotionEvent.AXIS_RZ, MotionEvent.AXIS_RY);
        RightStickViewRouter.Direction previous = router.direction();
        RightStickViewRouter.Direction current = router.update(horizontal, vertical);
        if (previous != current) {
            if (previous != RightStickViewRouter.Direction.NONE)
                dispatchDirection(activity, previous, KeyEvent.ACTION_UP);
            if (current != RightStickViewRouter.Direction.NONE)
                dispatchDirection(activity, current, KeyEvent.ACTION_DOWN);
        }
        return current != RightStickViewRouter.Direction.NONE ||
                previous != RightStickViewRouter.Direction.NONE;
    }

    private static float axis(MotionEvent event, int primary, int fallback) {
        InputDevice device = event.getDevice();
        if (device != null && device.getMotionRange(primary, event.getSource()) != null)
            return event.getAxisValue(primary);
        return event.getAxisValue(fallback);
    }

    private static void dispatchDirection(Activity activity,
            RightStickViewRouter.Direction direction, int action) {
        int keyCode;
        switch (direction) {
            case UP: keyCode = KeyEvent.KEYCODE_F1; break;
            case DOWN: keyCode = KeyEvent.KEYCODE_F2; break;
            case LEFT: keyCode = KeyEvent.KEYCODE_F3; break;
            case RIGHT: keyCode = KeyEvent.KEYCODE_F4; break;
            default: return;
        }
        long now = SystemClock.uptimeMillis();
        activity.dispatchKeyEvent(new KeyEvent(now, now, action, keyCode, 0, 0,
                0, 0, KeyEvent.FLAG_FROM_SYSTEM, InputDevice.SOURCE_JOYSTICK));
    }
}
