package com.thorium.lucent.netplay;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Which libretro port a peer's input lands on, computed identically by
 * every device with no extra message needed. Every device places its own
 * local player on port 0 (unconditionally, per the existing joypadSink
 * wiring in LibretroEngineSession/PpssppGlesEngineSession) and needs a
 * port for every OTHER participant; this assigns 1..N by sorting every
 * other participant's device ID and taking their index.
 *
 * <p>This mapping is deliberately device-relative, not global: on device
 * A, device B might land on port 1, while on device B's own core, device
 * A also lands on port 1 (B excludes itself from the same sorted list
 * that included A). That is correct and sufficient -- nothing requires
 * one peer to occupy the same numeric port on every participant's local
 * core, only that each device's own mapping stays internally consistent
 * for the life of the match, which a deterministic sort guarantees.
 */
public final class NetplayPortAssignment {
    private NetplayPortAssignment() {}

    public static int portFor(String myDeviceId, String peerDeviceId, List<String> participants) {
        List<String> others = new ArrayList<>();
        for (String id : participants) if (!id.equals(myDeviceId)) others.add(id);
        Collections.sort(others);
        int index = others.indexOf(peerDeviceId);
        if (index < 0)
            throw new IllegalArgumentException(peerDeviceId + " is not in participants " + participants);
        return 1 + index;
    }
}
