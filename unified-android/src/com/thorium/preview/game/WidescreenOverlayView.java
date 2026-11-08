package com.thorium.preview.game;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.os.Build;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;

import java.util.ArrayList;
import java.util.List;

/**
 * The Widescreen Hack's touch controls: a glowing "tap here for widescreen" on each side
 * bar that fades as the game starts, a brief hint once it is on, and a swipe in from
 * either edge to turn it off. It sits over the game but draws nothing and claims no touch
 * outside those moments and places, so it never costs a frame during play.
 *
 * It redraws only when what it shows changes: a few steps of fade in and out, nothing while
 * it holds still. Each redraw is a frame of this window beside the game, and redrawing every
 * frame kept the compositor on its slow path for the prompt's whole seven seconds.
 */
final class WidescreenOverlayView extends View {
    private static final long PROMPT_MS = 7000L;
    private static final long HINT_MS = 3500L;
    private static final long FADE_IN_MS = 250L;
    private static final long FADE_MS = 700L;
    private static final int FADE_IN_STEPS = 2;
    private static final int FADE_OUT_STEPS = 4;
    // The prompt's glow, held still: the halo's share of the text size and its strength.
    private static final float GLOW = 0.6f;
    private static final String[] PROMPT_LINES = {"Tap here", "for", "widescreen"};
    private static final String HINT = "Swipe in from the edge to disable widescreen";

    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF pillBox = new RectF();
    private final int edgePixels;
    private final int swipePixels;
    private final int tapSlopPixels;
    private final int barMinimumPixels;
    private WidescreenSession session;
    private Runnable relaunch;
    private boolean touchControlsShown;
    private long promptStartMs;
    private long hintStartMs;
    // The touch being followed.
    private boolean following;
    private float downX;
    private float downY;

    WidescreenOverlayView(Context context) {
        super(context);
        float density = context.getResources().getDisplayMetrics().density;
        edgePixels = Math.round(24f * density);
        swipePixels = Math.round(56f * density);
        tapSlopPixels = Math.round(16f * density);
        barMinimumPixels = Math.round(40f * density);
        text.setTextAlign(Paint.Align.CENTER);
        text.setFakeBoldText(true);
        pill.setColor(Color.argb(0xB0, 0x10, 0x14, 0x20));
    }

    /** The game is on screen: invite the tap, or remind how to turn it off. */
    void gameStarted(WidescreenSession widescreen, boolean touchControls) {
        session = widescreen;
        touchControlsShown = touchControls;
        if (session == null) return;
        if (session.isEnabled()) showHint();
        else showPrompt();
    }

    void setTouchControlsShown(boolean shown) { touchControlsShown = shown; }

    /** Restarts the game, for recipes whose engine reads widescreen only at startup. */
    void setRelaunch(Runnable restart) { relaunch = restart; }

    private boolean relaunchNow() {
        if (session == null || !session.recipe.relaunch || relaunch == null) return false;
        relaunch.run();
        return true;
    }

    private void showPrompt() {
        hintStartMs = 0L;
        if (barWidth() < barMinimumPixels) return;
        promptStartMs = SystemClock.uptimeMillis();
        invalidate();
    }

    private void showHint() {
        promptStartMs = 0L;
        hintStartMs = SystemClock.uptimeMillis();
        invalidate();
    }

    /** Side bar width with the original picture. */
    private float barWidth() {
        if (session == null || getHeight() <= 0) return 0f;
        return (getWidth() - getHeight() * session.recipe.originalAspect()) / 2f;
    }

    private boolean inBar(float x) {
        float bar = barWidth();
        return bar >= barMinimumPixels && (x < bar || x > getWidth() - bar);
    }

    private boolean promptShowing() {
        return promptStartMs != 0L &&
                SystemClock.uptimeMillis() - promptStartMs < PROMPT_MS + FADE_MS;
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        if (session == null) return false;
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                downX = event.getX();
                downY = event.getY();
                // A swipe starts at an edge; a tap lands on a bar. On-screen controls
                // keep the bars except while the prompt is asking for the tap.
                boolean atEdge = downX < edgePixels || downX > getWidth() - edgePixels;
                following = session.isEnabled() ? atEdge :
                        inBar(downX) && (!touchControlsShown || promptShowing());
                return following;
            case MotionEvent.ACTION_MOVE:
                if (following && session.isEnabled() && swipedInward(event)) {
                    following = false;
                    session.setEnabled(false);
                    if (!relaunchNow()) showPrompt();
                }
                return following;
            case MotionEvent.ACTION_UP:
                if (following && !session.isEnabled() &&
                        Math.hypot(event.getX() - downX, event.getY() - downY) < tapSlopPixels) {
                    session.setEnabled(true);
                    if (!relaunchNow()) showHint();
                }
                following = false;
                return true;
            case MotionEvent.ACTION_CANCEL:
                following = false;
                return true;
            default:
                return following;
        }
    }

    private boolean swipedInward(MotionEvent event) {
        float travel = event.getX() - downX;
        return downX < getWidth() / 2f ? travel > swipePixels : -travel > swipePixels;
    }

    @Override protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
        super.onLayout(changed, left, top, right, bottom);
        if (Build.VERSION.SDK_INT >= 29) {
            // Keep the system's back gesture from taking the swipe.
            int height = bottom - top;
            int band = Math.min(height, Math.round(200f * getResources().getDisplayMetrics().density));
            int top1 = (height - band) / 2;
            List<Rect> edges = new ArrayList<>(2);
            edges.add(new Rect(0, top1, edgePixels, top1 + band));
            edges.add(new Rect(right - left - edgePixels, top1, right - left, top1 + band));
            setSystemGestureExclusionRects(edges);
        }
    }

    @Override protected void onDraw(Canvas canvas) {
        long now = SystemClock.uptimeMillis();
        long next = Long.MAX_VALUE;
        if (promptStartMs != 0L) {
            long age = now - promptStartMs;
            if (age < PROMPT_MS + FADE_MS) {
                drawPrompt(canvas, age);
                next = Math.min(next, untilNextStep(age, PROMPT_MS));
            } else {
                promptStartMs = 0L;
            }
        }
        if (hintStartMs != 0L) {
            long age = now - hintStartMs;
            if (age < HINT_MS + FADE_MS) {
                drawHint(canvas, age);
                next = Math.min(next, untilNextStep(age, HINT_MS));
            } else {
                hintStartMs = 0L;
            }
        }
        if (next != Long.MAX_VALUE) postInvalidateDelayed(Math.max(1L, next));
    }

    /** Opacity in a few steps, so a fade costs a handful of redraws, not one every frame. */
    private static float fade(long age, long shownMs) {
        if (age < FADE_IN_MS) return (age * FADE_IN_STEPS / FADE_IN_MS + 1) / (float) FADE_IN_STEPS;
        if (age < shownMs) return 1f;
        long step = (age - shownMs) * FADE_OUT_STEPS / FADE_MS + 1;
        return Math.max(0f, 1f - step / (float) FADE_OUT_STEPS);
    }

    /** How long until fade() next gives a different opacity, the last time being when it is gone. */
    private static long untilNextStep(long age, long shownMs) {
        if (age < FADE_IN_MS) {
            long step = FADE_IN_MS / FADE_IN_STEPS;
            long boundary = (age / step + 1) * step;
            // Fully faded in at the last step: the next change is the fade out.
            return (boundary < FADE_IN_MS ? boundary : shownMs) - age;
        }
        if (age < shownMs) return shownMs - age;
        long step = FADE_MS / FADE_OUT_STEPS;
        long boundary = shownMs + ((age - shownMs) / step + 1) * step;
        // The last step would show nothing: go straight to the redraw that clears it.
        return (boundary < shownMs + FADE_MS - step ? boundary : shownMs + FADE_MS) - age;
    }

    private void drawPrompt(Canvas canvas, long age) {
        float bar = barWidth();
        if (bar < barMinimumPixels) return;
        float alpha = fade(age, PROMPT_MS) * (0.75f + 0.25f * GLOW);
        float size = getResources().getDisplayMetrics().scaledDensity * 20f;
        text.setShadowLayer(0f, 0f, 0f, 0);
        text.setTextSize(size);
        float widest = 0f;
        for (String line : PROMPT_LINES) widest = Math.max(widest, text.measureText(line));
        float room = bar * 0.86f;
        if (widest > room) size *= room / widest;
        text.setTextSize(size);
        text.setColor(Color.argb(Math.round(255f * alpha), 0xE8, 0xF6, 0xFF));
        float radius = size * (0.35f + 0.55f * GLOW);
        text.setShadowLayer(radius, 0f, 0f, Color.argb(Math.round(240f * alpha), 0x5C, 0xC8, 0xFF));
        float lineHeight = size * 1.3f;
        float top = (getHeight() - lineHeight * PROMPT_LINES.length) / 2f + size;
        for (int index = 0; index < PROMPT_LINES.length; index++) {
            float y = top + index * lineHeight;
            canvas.drawText(PROMPT_LINES[index], bar / 2f, y, text);
            canvas.drawText(PROMPT_LINES[index], getWidth() - bar / 2f, y, text);
        }
    }

    private void drawHint(Canvas canvas, long age) {
        float alpha = fade(age, HINT_MS);
        float size = getResources().getDisplayMetrics().scaledDensity * 15f;
        text.setShadowLayer(0f, 0f, 0f, 0);
        text.setTextSize(size);
        text.setColor(Color.argb(Math.round(255f * alpha), 0xFF, 0xFF, 0xFF));
        float halfWidth = text.measureText(HINT) / 2f + size;
        float centerY = getHeight() - size * 3f;
        pillBox.set(getWidth() / 2f - halfWidth, centerY - size * 1.2f,
                getWidth() / 2f + halfWidth, centerY + size * 1.2f);
        pill.setAlpha(Math.round(0xB0 * alpha));
        canvas.drawRoundRect(pillBox, size * 1.2f, size * 1.2f, pill);
        canvas.drawText(HINT, getWidth() / 2f, centerY + size * 0.36f, text);
    }
}
