package com.thorium.emufusion.input;

import java.io.IOException;
import java.util.Map;

/** Persistence boundary for the only exposed emulator setting: Remap Controls. */
public interface RemapStore {
    Map<CanonicalControl, InputSignal> load(MappingScope scope, String deviceKey) throws IOException;
    void save(MappingScope scope, String deviceKey,
            Map<CanonicalControl, InputSignal> mapping) throws IOException;
    void clear(MappingScope scope, String deviceKey) throws IOException;
}
