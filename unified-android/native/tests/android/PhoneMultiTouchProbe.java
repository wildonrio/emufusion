package com.thorium.preview.qa;

import android.os.Build;
import android.os.Process;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.MotionEvent;

import java.lang.reflect.Method;

/** Bounded two-finger input through Android's real input dispatcher. Run as
 * shell only on a disposable AVD, after visually locating the phone controls.
 * This is a QA command, not a second APK or a production input back door. */
public final class PhoneMultiTouchProbe {
    private final Object manager;
    private final Method inject;
    private final long downTime = SystemClock.uptimeMillis();
    private final MotionEvent.PointerProperties[] properties = {
            new MotionEvent.PointerProperties(), new MotionEvent.PointerProperties()};
    private final MotionEvent.PointerCoords[] coordinates = {
            new MotionEvent.PointerCoords(), new MotionEvent.PointerCoords()};
    private int activePointers;

    private PhoneMultiTouchProbe() throws Exception {
        // Android 16's InputManager facade requires an ActivityThread context.
        // app_process shell tools use the process-global dispatcher instead.
        Class<?> type = Class.forName("android.hardware.input.InputManagerGlobal");
        manager = type.getMethod("getInstance").invoke(null);
        inject = type.getMethod("injectInputEvent", InputEvent.class, int.class);
        for (int index = 0; index < 2; index++) {
            properties[index].id = index;
            properties[index].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coordinates[index].pressure = 1f;
            coordinates[index].size = 1f;
        }
    }

    private void send(int action, int count) throws Exception {
        MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(),
                action, count, properties, coordinates, 0, 0, 1f, 1f,
                0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        try {
            // WAIT_FOR_FINISH: accepted by the system dispatcher, not just
            // placed in a local queue. Guest response still needs visual proof.
            if (!Boolean.TRUE.equals(inject.invoke(manager, event, 2)))
                throw new IllegalStateException("Android rejected touch action " + action);
        } finally { event.recycle(); }
    }

    public static void main(String[] args) throws Exception {
        if (Process.myUid() != 2000 || !"ranchu".equals(Build.HARDWARE))
            throw new IllegalStateException("Disposable Android emulator shell only");
        if (args.length != 7)
            throw new IllegalArgumentException("startX startY endX endY buttonX buttonY durationMs");
        float[] values = new float[6];
        for (int i = 0; i < values.length; i++) {
            values[i] = Float.parseFloat(args[i]);
            if (!Float.isFinite(values[i]) || values[i] < 0 || values[i] > 8192)
                throw new IllegalArgumentException("invalid screen coordinate");
        }
        int duration = Integer.parseInt(args[6]);
        if (duration < 50 || duration > 5000)
            throw new IllegalArgumentException("duration must be 50..5000 ms");
        PhoneMultiTouchProbe probe = new PhoneMultiTouchProbe();
        probe.coordinates[0].x = values[0]; probe.coordinates[0].y = values[1];
        probe.coordinates[1].x = values[4]; probe.coordinates[1].y = values[5];
        try {
            probe.activePointers = 1;
            probe.send(MotionEvent.ACTION_DOWN, 1);
            SystemClock.sleep(32);
            probe.activePointers = 2;
            probe.send(MotionEvent.ACTION_POINTER_DOWN | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2);
            probe.coordinates[0].x = values[2]; probe.coordinates[0].y = values[3];
            long end = SystemClock.uptimeMillis() + duration;
            do {
                probe.send(MotionEvent.ACTION_MOVE, 2);
                SystemClock.sleep(16);
            } while (SystemClock.uptimeMillis() < end);
            probe.send(MotionEvent.ACTION_POINTER_UP | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2);
            probe.activePointers = 1;
            probe.send(MotionEvent.ACTION_UP, 1);
            probe.activePointers = 0;
            System.out.println("MULTITOUCH dispatched hold-and-release durationMs=" + duration);
        } finally {
            if (probe.activePointers != 0)
                probe.send(MotionEvent.ACTION_CANCEL, probe.activePointers);
        }
    }
}
