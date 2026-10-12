package com.thorium.emufusion.input;

import java.util.Collections;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.Map;

public final class InMemoryRemapStore implements RemapStore {
    private final Map<String, Map<CanonicalControl, InputSignal>> values = new HashMap<>();

    @Override public synchronized Map<CanonicalControl, InputSignal> load(
            MappingScope scope, String deviceKey) {
        Map<CanonicalControl, InputSignal> value = values.get(key(scope, deviceKey));
        return value == null ? Collections.<CanonicalControl, InputSignal>emptyMap()
                : new EnumMap<>(value);
    }

    @Override public synchronized void save(MappingScope scope, String deviceKey,
            Map<CanonicalControl, InputSignal> mapping) {
        values.put(key(scope, deviceKey), new EnumMap<>(mapping));
    }

    @Override public synchronized void clear(MappingScope scope, String deviceKey) {
        values.remove(key(scope, deviceKey));
    }

    private static String key(MappingScope scope, String deviceKey) {
        return scope.systemId + "\n" + scope.gameId + "\n" + deviceKey;
    }
}
