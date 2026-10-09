package com.thorium.lucent.input;

import java.util.HashMap;
import java.util.Map;

/**
 * Aggregates every physical source that can assert the same libretro joypad ID.
 *
 * <p>EmuFusion deliberately routes more than one physical control to one console
 * direction: on an Xbox-style handheld the hat (ABS_HAT0X/ABS_HAT0Y) and the
 * left analog stick both mean "the D-pad" on a D-pad-only console, and a pad
 * that also reports BTN_DPAD_* keys adds a third source. Sending each source
 * straight to {@code setJoypadButton} makes the last writer win: one centred
 * stick clears a physically held hat direction, so a direction appears dead on
 * hardware even though its own source is asserted.
 *
 * <p>This ledger records which sources currently hold each ID and emits a
 * change only when the OR of those sources flips. A direction stays pressed
 * while any source holds it and is released exactly once, when the last one
 * lets go.
 *
 * <p>A source is any object with value equality: an {@link InputSignal} for
 * physical keys and axis directions, or a {@link CanonicalControl} for the
 * on-screen controls. Sources from different namespaces never collide.
 */
public final class JoypadPressLedger {
    /** Receives only real transitions of one joypad ID's aggregate state. */
    public interface Sink {
        void setJoypadButton(int retroId, boolean pressed);
    }

    private final Map<Object, Integer> heldBySource = new HashMap<>();
    private final Map<Integer, Integer> holdersById = new HashMap<>();

    /**
     * Applies one source's state for {@code retroId} and notifies the sink when
     * the aggregate changes. Repeating an unchanged state is a no-op, so key
     * auto-repeat and the per-event axis sweep cost nothing.
     */
    public synchronized void apply(Object source, int retroId, boolean pressed, Sink sink) {
        if (source == null || retroId < 0) return;
        Integer previous = heldBySource.get(source);
        if (pressed) {
            if (previous != null && previous == retroId) return;
            // A remap can move a live source to a different ID. Release the ID
            // it used to hold before it starts holding the new one, otherwise
            // the old direction stays stuck down for the rest of the session.
            if (previous != null) {
                heldBySource.remove(source);
                releaseHolder(previous, sink);
            }
            heldBySource.put(source, retroId);
            if (addHolder(retroId) == 1 && sink != null) sink.setJoypadButton(retroId, true);
            return;
        }
        // A release for a source that never pressed anything is common: the
        // motion sweep reports every axis on every event. Ignore it instead of
        // clearing an ID another source is holding.
        if (previous == null) return;
        heldBySource.remove(source);
        releaseHolder(previous, sink);
    }

    /** True while at least one source holds this joypad ID. */
    public synchronized boolean isPressed(int retroId) {
        return holdersById.containsKey(retroId);
    }

    /** Number of distinct sources currently holding this joypad ID. */
    public synchronized int holderCount(int retroId) {
        Integer count = holdersById.get(retroId);
        return count == null ? 0 : count;
    }

    /** Releases every held source, emitting one release per still-held ID. */
    public synchronized void releaseAll(Sink sink) {
        heldBySource.clear();
        if (sink != null) for (Integer id : holdersById.keySet()) sink.setJoypadButton(id, false);
        holdersById.clear();
    }

    private int addHolder(int retroId) {
        Integer count = holdersById.get(retroId);
        int next = count == null ? 1 : count + 1;
        holdersById.put(retroId, next);
        return next;
    }

    private void releaseHolder(int retroId, Sink sink) {
        Integer count = holdersById.get(retroId);
        if (count == null) return;
        if (count > 1) {
            holdersById.put(retroId, count - 1);
            return;
        }
        holdersById.remove(retroId);
        if (sink != null) sink.setJoypadButton(retroId, false);
    }
}
