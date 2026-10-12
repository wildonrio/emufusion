package com.thorium.emufusion.input;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;

/** Selects an active pad, merges system/game remaps, and exposes canonical input only. */
public final class InputRouter {
    private final DeviceCatalog catalog;
    private final RemapStore remaps;
    private final boolean hostIsKnownGamingHandheld;
    private final List<GamepadDescriptor> connected = new ArrayList<>();
    private GamepadDescriptor active;
    private MappingScope scope;

    public InputRouter(DeviceCatalog catalog, RemapStore remaps,
            boolean hostIsKnownGamingHandheld) {
        if (catalog == null || remaps == null) throw new IllegalArgumentException("Dependencies required");
        this.catalog = catalog;
        this.remaps = remaps;
        this.hostIsKnownGamingHandheld = hostIsKnownGamingHandheld;
    }

    public synchronized void setGame(String systemId, String gameId) {
        scope = new MappingScope(systemId, gameId);
    }

    public synchronized void updateDevices(List<GamepadDescriptor> devices) {
        String previous = active == null ? null : active.persistentKey();
        connected.clear();
        for (GamepadDescriptor device : devices) if (device.isPhysicalGamepad()) connected.add(device);
        active = null;
        if (previous != null) for (GamepadDescriptor device : connected)
            if (previous.equals(device.persistentKey())) { active = device; break; }
        if (active == null) for (GamepadDescriptor device : connected)
            if (device.isCompleteGamepad()) { active = device; break; }
        if (active == null && !connected.isEmpty()) active = connected.get(0);
    }

    public synchronized GamepadDescriptor activeDevice() { return active; }
    public synchronized List<GamepadDescriptor> connectedDevices() {
        return Collections.unmodifiableList(new ArrayList<>(connected));
    }

    public synchronized boolean shouldShowOnScreenControls() {
        return TouchVisibilityPolicy.shouldShow(hostIsKnownGamingHandheld, connected, catalog);
    }

    public synchronized CanonicalControl resolve(GamepadDescriptor device, InputSignal signal)
            throws IOException {
        if (device == null || signal == null || scope == null) return null;
        Map<CanonicalControl, InputSignal> mapping = effectiveMapping(device);
        for (Map.Entry<CanonicalControl, InputSignal> entry : mapping.entrySet())
            if (signal.equals(entry.getValue())) return entry.getKey();
        CanonicalControl alternative = standardAxisAlternative(signal);
        if (alternative == null) return null;
        InputSignal configured = mapping.get(alternative);
        InputSignal standard = catalog.match(device).mapping().get(alternative);
        return standard != null && standard.equals(configured) ? alternative : null;
    }

    public synchronized Map<CanonicalControl, InputSignal> effectiveMapping(GamepadDescriptor device)
            throws IOException {
        return effectiveMapping(device, true);
    }

    /** Mapping used by the editor without leaking this game's overrides system-wide. */
    public synchronized Map<CanonicalControl, InputSignal> effectiveSystemMapping(
            GamepadDescriptor device) throws IOException {
        return effectiveMapping(device, false);
    }

    private Map<CanonicalControl, InputSignal> effectiveMapping(GamepadDescriptor device,
            boolean includeGame) throws IOException {
        if (scope == null) throw new IllegalStateException("No game selected");
        EnumMap<CanonicalControl, InputSignal> mapping = new EnumMap<>(CanonicalControl.class);
        mapping.putAll(catalog.match(device).mapping());
        mergeOverrides(mapping,
                remaps.load(new MappingScope(scope.systemId, ""), device.persistentKey()));
        if (includeGame && scope.isGameSpecific()) mergeOverrides(mapping,
                remaps.load(scope, device.persistentKey()));
        return Collections.unmodifiableMap(mapping);
    }

    public synchronized void saveRemap(GamepadDescriptor device, boolean forThisGame,
            Map<CanonicalControl, InputSignal> mapping) throws IOException {
        if (scope == null) throw new IllegalStateException("No game selected");
        MappingScope target = forThisGame ? scope : new MappingScope(scope.systemId, "");
        remaps.save(target, device.persistentKey(), mapping);
    }

    public synchronized void resetRemap(GamepadDescriptor device, boolean forThisGame)
            throws IOException {
        if (scope == null) throw new IllegalStateException("No game selected");
        MappingScope target = forThisGame ? scope : new MappingScope(scope.systemId, "");
        remaps.clear(target, device.persistentKey());
    }

    private static void mergeOverrides(EnumMap<CanonicalControl, InputSignal> target,
            Map<CanonicalControl, InputSignal> overrides) {
        for (Map.Entry<CanonicalControl, InputSignal> override : overrides.entrySet()) {
            CanonicalControl conflict = null;
            for (Map.Entry<CanonicalControl, InputSignal> existing : target.entrySet())
                if (existing.getValue().equals(override.getValue()) &&
                        existing.getKey() != override.getKey()) {
                    conflict = existing.getKey();
                    break;
                }
            if (conflict != null) target.remove(conflict);
            target.put(override.getKey(), override.getValue());
        }
    }

    private static CanonicalControl standardAxisAlternative(InputSignal signal) {
        if (signal.type != InputSignal.Type.AXIS) return null;
        if (signal.code == AndroidInputCodes.AXIS_HAT_X)
            return signal.direction < 0 ? CanonicalControl.DPAD_LEFT : CanonicalControl.DPAD_RIGHT;
        if (signal.code == AndroidInputCodes.AXIS_HAT_Y)
            return signal.direction < 0 ? CanonicalControl.DPAD_UP : CanonicalControl.DPAD_DOWN;
        if (signal.direction > 0 && (signal.code == AndroidInputCodes.AXIS_LTRIGGER ||
                signal.code == AndroidInputCodes.AXIS_BRAKE)) return CanonicalControl.L2;
        if (signal.direction > 0 && (signal.code == AndroidInputCodes.AXIS_RTRIGGER ||
                signal.code == AndroidInputCodes.AXIS_GAS)) return CanonicalControl.R2;
        return null;
    }
}
