package com.thorium.preview.game;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.view.MotionEvent;
import android.view.View;

import com.thorium.lucent.input.CanonicalControl;
import com.thorium.lucent.input.SystemControlLayouts;
import com.thorium.lucent.input.TouchAnalogStick;

import java.util.EnumSet;

/** EmuFusion-owned phone fallback; never shown when a physical pad exists. */
final class TouchControlsView extends View {
    interface Listener {
        void onControl(CanonicalControl control, boolean pressed);
        void onAnalog(int stick, float x, float y);
    }

    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint outline = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final EnumSet<CanonicalControl> pressed = EnumSet.noneOf(CanonicalControl.class);
    private static final CanonicalControl[] EXTRA_CONTROLS = {
            CanonicalControl.L2, CanonicalControl.L3,
            CanonicalControl.R3, CanonicalControl.R2};
    private static final float[] EXTRA_X = {0.18f, 0.28f, 0.72f, 0.82f};
    private final EnumSet<CanonicalControl> extras = EnumSet.noneOf(CanonicalControl.class);
    private String systemId = "";
    private Listener listener;
    private final TouchAnalogStick[] sticks = {new TouchAnalogStick(), new TouchAnalogStick()};
    private final float[] sentX = new float[2], sentY = new float[2];
    private int stickCount;

    TouchControlsView(Context context) {
        super(context);
        setFocusable(false);
        // A white plate and white label disappear on bright game frames.
        // Keep contrast independent of the underlying game while retaining
        // translucency; the outline defines the touch area on dark frames.
        fill.setColor(Color.argb(160, 0, 0, 0));
        outline.setColor(Color.argb(160, 255, 255, 255));
        outline.setStyle(Paint.Style.STROKE);
        text.setColor(Color.argb(240, 255, 255, 255));
        text.setTextAlign(Paint.Align.CENTER);
        text.setTypeface(Typeface.DEFAULT_BOLD);
    }

    void setListener(Listener listener) { this.listener = listener; }

    void setSystem(String systemId) {
        String id = systemId == null ? "" : systemId.toLowerCase(java.util.Locale.US)
                .replaceAll("[^a-z0-9]", "");
        if ("n3ds".equals(id)) id = "3ds";
        // Native adapters consume the canonical controller directly rather
        // than the libretro table. All four extra controls are real pad inputs.
        boolean nativePad = "switch".equals(id) || "nintendoswitch".equals(id) ||
                "wiiu".equals(id) || "ps3".equals(id);
        EnumSet<CanonicalControl> next = EnumSet.noneOf(CanonicalControl.class);
        for (CanonicalControl control : EXTRA_CONTROLS)
            if (nativePad || SystemControlLayouts.bindings(id).containsKey(control))
                next.add(control);
        if (this.systemId.equals(id) && extras.equals(next)) return;
        releaseTouches();
        this.systemId = id;
        extras.clear();
        extras.addAll(next);
        invalidate();
    }

    void setAnalogStickCount(int count) {
        count = Math.max(0, Math.min(2, count));
        if (stickCount == count) return;
        releaseTouches();
        stickCount = count;
        invalidate();
    }

    void releaseTouches() {
        // View lifecycle callbacks can occur before subclass initialization.
        if (pressed == null || sticks == null) return;
        if (listener != null) for (CanonicalControl control : pressed)
            if (!isN64CameraButton(control)) listener.onControl(control, false);
        pressed.clear();
        for (int index = 0; index < sticks.length; index++) {
            sticks[index].reset();
            sendAnalog(index);
        }
        invalidate();
    }

    @Override protected void onDetachedFromWindow() {
        releaseTouches();
        super.onDetachedFromWindow();
    }

    @Override protected void onVisibilityChanged(View changedView, int visibility) {
        super.onVisibilityChanged(changedView, visibility);
        if (visibility != View.VISIBLE) releaseTouches();
    }

    @Override public void onWindowFocusChanged(boolean hasWindowFocus) {
        super.onWindowFocusChanged(hasWindowFocus);
        if (!hasWindowFocus) releaseTouches();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float unit = Math.min(getWidth(), getHeight());
        float radius = unit * 0.052f;
        for (int index = 0; index < stickCount; index++) {
            float cx = stickX(index), cy = stickY(), r = stickRadius();
            canvas.drawCircle(cx, cy, r, fill);
            drawButton(canvas, cx + sticks[index].x() * r * 0.65f,
                    cy + sticks[index].y() * r * 0.65f, r * 0.35f,
                    index == 0 ? "LS" : "RS");
        }
        float leftX = getWidth() * 0.18f, centerY = getHeight() * 0.73f;
        drawButton(canvas, leftX, centerY - radius * 1.65f, radius, "▲");
        drawButton(canvas, leftX, centerY + radius * 1.65f, radius, "▼");
        drawButton(canvas, leftX - radius * 1.65f, centerY, radius, "◀");
        drawButton(canvas, leftX + radius * 1.65f, centerY, radius, "▶");

        float rightX = getWidth() * 0.82f;
        drawButton(canvas, rightX, centerY - radius * 1.65f, radius,
                faceLabel(CanonicalControl.NORTH, "X"));
        drawButton(canvas, rightX, centerY + radius * 1.65f, radius,
                faceLabel(CanonicalControl.SOUTH, "B"));
        drawButton(canvas, rightX - radius * 1.65f, centerY, radius,
                faceLabel(CanonicalControl.WEST, "Y"));
        drawButton(canvas, rightX + radius * 1.65f, centerY, radius,
                faceLabel(CanonicalControl.EAST, "A"));

        float small = radius * 0.72f;
        drawButton(canvas, getWidth() * 0.08f, getHeight() * 0.12f, small,
                menuLabel(CanonicalControl.L1, "L"));
        drawButton(canvas, getWidth() * 0.92f, getHeight() * 0.12f, small,
                menuLabel(CanonicalControl.R1, "R"));
        for (int index = 0; index < EXTRA_CONTROLS.length; index++)
            if (extras.contains(EXTRA_CONTROLS[index]))
                drawButton(canvas, getWidth() * EXTRA_X[index], getHeight() * 0.12f,
                        small, extraLabel(EXTRA_CONTROLS[index]));
        drawButton(canvas, getWidth() * 0.46f, getHeight() * 0.88f, small,
                menuLabel(CanonicalControl.SELECT, "−"));
        drawButton(canvas, getWidth() * 0.54f, getHeight() * 0.88f, small,
                menuLabel(CanonicalControl.START, "+"));
    }

    private String menuLabel(CanonicalControl control, String fallback) {
        // Keep guest labels consistent with dispatch: Wii's Minus/Plus and
        // 2/1, and PC Engine's V/VI and Run. Physical mappings do not change.
        SystemControlLayouts.Binding binding = SystemControlLayouts.bindings(systemId).get(control);
        if (binding == null) return fallback;
        switch (binding.control) {
            case "MINUS": return "−";
            case "PLUS": return "+";
            case "1": return "1";
            case "2": return "2";
            case "V": case "VI": case "RUN": return binding.control;
            default: return fallback;
        }
    }

    private String extraLabel(CanonicalControl control) {
        // A phone has no printed host-controller buttons. Describe the guest
        // trigger, so prompts such as N64 "Z" and 3DS "ZL" are actionable.
        // This changes only text; hit regions and canonical dispatch stay put.
        SystemControlLayouts.Binding binding = SystemControlLayouts.bindings(systemId).get(control);
        if (binding != null) {
            switch (binding.control) {
                case "Z": case "ZL": case "ZR": case "L": case "R":
                    return binding.control;
                case "C_MODE": return "C";
                case "MODE": return "Mode";
                default: break;
            }
        }
        return control.name();
    }

    private void drawButton(Canvas canvas, float x, float y, float radius, String label) {
        if (label == null) return;
        canvas.drawCircle(x, y, radius, fill);
        outline.setStrokeWidth(Math.max(1.5f, radius * 0.045f));
        canvas.drawCircle(x, y, radius, outline);
        text.setTextSize(radius * 0.72f);
        canvas.drawText(label, x, y - (text.ascent() + text.descent()) / 2f, text);
    }

    private String faceLabel(CanonicalControl control, String fallback) {
        // Virtual input sends canonical positions through this same table.
        // Fixed Thor labels described the wrong guest button on GBA, GC,
        // Sony and Sega, and advertised unused face buttons on Game Boy.
        // aPS3e bypasses the RetroPad table but uses the same Sony face
        // positions as PS2: south=Cross, east=Circle, west=Square, north=Triangle.
        // Reuse only the display names; keep native dispatch and pad mapping intact.
        java.util.Map<CanonicalControl, SystemControlLayouts.Binding> table =
                SystemControlLayouts.bindings("ps3".equals(systemId) ? "ps2" : systemId);
        if (table.isEmpty()) return fallback; // native adapters/generic layout
        SystemControlLayouts.Binding binding = table.get(control);
        if (binding == null) return null;
        switch (binding.control) {
            case "CROSS": return "×";
            case "CIRCLE": return "○";
            case "SQUARE": return "□";
            case "TRIANGLE": return "△";
            case "C_UP": return "C↑";
            case "C_DOWN": return "C↓";
            case "NUNCHUK_C": return "C";
            case "NUNCHUK_Z": return "Z";
            default: return binding.control;
        }
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        // This transparent full-window view must not swallow stylus touches
        // outside its controls. The gameplay root owns those gestures (DS/3DS
        // touch screens), while a gesture begun on a button stays here through
        // its release, including drags outside and cancellation.
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN &&
                stickAt(event.getX(0), event.getY(0)) < 0 &&
                controlAt(event.getX(0), event.getY(0)) == null) return false;
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) releaseTouches();
        if (action == MotionEvent.ACTION_CANCEL) {
            releaseTouches();
            return true;
        }
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            int index = event.getActionIndex();
            int stick = stickAt(event.getX(index), event.getY(index));
            if (stick >= 0) sticks[stick].begin(event.getPointerId(index),
                    event.getX(index) - stickX(stick), event.getY(index) - stickY(),
                    stickRadius());
        }
        EnumSet<CanonicalControl> next = EnumSet.noneOf(CanonicalControl.class);
        int lifted = event.getActionMasked() == MotionEvent.ACTION_UP ||
                event.getActionMasked() == MotionEvent.ACTION_POINTER_UP
                ? event.getActionIndex() : -1;
        for (int stick = 0; stick < stickCount; stick++) {
            TouchAnalogStick state = sticks[stick];
            int index = event.findPointerIndex(state.pointerId());
            if (index < 0 || index == lifted) state.reset();
            else state.move(event.getPointerId(index), event.getX(index) - stickX(stick),
                    event.getY(index) - stickY(), stickRadius());
        }
        if (event.getActionMasked() != MotionEvent.ACTION_CANCEL) {
            for (int index = 0; index < event.getPointerCount(); index++) {
                if (index == lifted) continue;
                if (sticks[0].owns(event.getPointerId(index)) ||
                        sticks[1].owns(event.getPointerId(index))) continue;
                CanonicalControl control = controlAt(event.getX(index), event.getY(index));
                if (control != null) next.add(control);
            }
        }
        for (CanonicalControl control : CanonicalControl.values()) {
            boolean was = pressed.contains(control), is = next.contains(control);
            if (was != is && listener != null && !isN64CameraButton(control))
                listener.onControl(control, is);
        }
        pressed.clear();
        pressed.addAll(next);
        // Resolve the complete multi-touch state before publishing axes. A
        // stick move must not briefly release a C arrow held by another finger.
        for (int stick = 0; stick < sticks.length; stick++) sendAnalog(stick);
        invalidate();
        return true;
    }

    private float stickX(int index) { return getWidth() * (index == 0 ? 0.18f : 0.82f); }
    private float stickY() { return getHeight() * 0.39f; }
    private float stickRadius() { return Math.min(getWidth(), getHeight()) * 0.095f; }
    private int stickAt(float x, float y) {
        for (int index = 0; index < stickCount; index++)
            if (distance(x, y, stickX(index), stickY()) <= stickRadius()) return index;
        return -1;
    }
    private void sendAnalog(int index) {
        float x = sticks[index].x(), y = sticks[index].y();
        if (index == 1 && isN64CameraButton(CanonicalControl.NORTH)) {
            boolean up = pressed.contains(CanonicalControl.NORTH);
            boolean down = pressed.contains(CanonicalControl.WEST);
            // Mupen's default mapping ignores RetroPad X/A without C mode.
            // Do not synthesize that modifier: it would also turn a simultaneous
            // jump/attack into a different C button. These labelled phone arrows
            // use the same independent right-stick axis as the core's C input.
            if (up || down) y = (down ? 1f : 0f) - (up ? 1f : 0f);
        }
        if (x == sentX[index] && y == sentY[index]) return;
        sentX[index] = x;
        sentY[index] = y;
        if (listener != null) listener.onAnalog(index, x, y);
    }

    private boolean isN64CameraButton(CanonicalControl control) {
        return ("n64".equals(systemId) || "nintendo64".equals(systemId)) &&
                (control == CanonicalControl.NORTH || control == CanonicalControl.WEST);
    }

    private CanonicalControl controlAt(float x, float y) {
        float unit = Math.min(getWidth(), getHeight());
        float radius = unit * 0.069f;
        float leftX = getWidth() * 0.18f, centerY = getHeight() * 0.73f;
        CanonicalControl found = nearest(x, y, radius,
                leftX, centerY - unit * 0.086f, CanonicalControl.DPAD_UP,
                leftX, centerY + unit * 0.086f, CanonicalControl.DPAD_DOWN,
                leftX - unit * 0.086f, centerY, CanonicalControl.DPAD_LEFT,
                leftX + unit * 0.086f, centerY, CanonicalControl.DPAD_RIGHT);
        if (found != null) return found;
        float rightX = getWidth() * 0.82f;
        found = nearest(x, y, radius,
                rightX, centerY - unit * 0.086f, CanonicalControl.NORTH,
                rightX, centerY + unit * 0.086f, CanonicalControl.SOUTH,
                rightX - unit * 0.086f, centerY, CanonicalControl.WEST,
                rightX + unit * 0.086f, centerY, CanonicalControl.EAST);
        if (found != null) return faceLabel(found, "") == null ? null : found;
        if (distance(x, y, getWidth() * 0.08f, getHeight() * 0.12f) < radius)
            return CanonicalControl.L1;
        if (distance(x, y, getWidth() * 0.92f, getHeight() * 0.12f) < radius)
            return CanonicalControl.R1;
        // Keep shoulder targets disjoint even on a 4:3 landscape display.
        // Stick clicks are separate buttons so clicking never steals the
        // analog finger, and a second finger can hold a click while steering.
        for (int index = 0; index < EXTRA_CONTROLS.length; index++)
            if (extras.contains(EXTRA_CONTROLS[index]) && distance(x, y,
                    getWidth() * EXTRA_X[index], getHeight() * 0.12f) < unit * 0.058f)
                return EXTRA_CONTROLS[index];
        if (distance(x, y, getWidth() * 0.46f, getHeight() * 0.88f) < radius)
            return CanonicalControl.SELECT;
        if (distance(x, y, getWidth() * 0.54f, getHeight() * 0.88f) < radius)
            return CanonicalControl.START;
        return null;
    }

    private static CanonicalControl nearest(float x, float y, float radius, Object... values) {
        for (int index = 0; index < values.length; index += 3)
            if (distance(x, y, (Float) values[index], (Float) values[index + 1]) < radius)
                return (CanonicalControl) values[index + 2];
        return null;
    }

    private static float distance(float x, float y, float cx, float cy) {
        return (float) Math.hypot(x - cx, y - cy);
    }
}
