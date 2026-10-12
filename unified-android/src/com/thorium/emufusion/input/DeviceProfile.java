package com.thorium.emufusion.input;

import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;
import java.util.regex.Pattern;

public final class DeviceProfile {
    public final String id;
    public final int vendorId;
    public final int productId;
    public final boolean builtInGamingDevice;
    private final Pattern namePattern;
    private final Map<CanonicalControl, InputSignal> mapping;

    public DeviceProfile(String id, int vendorId, int productId, String nameRegex,
            boolean builtInGamingDevice, Map<CanonicalControl, InputSignal> mapping) {
        this.id = id;
        this.vendorId = vendorId;
        this.productId = productId;
        this.namePattern = Pattern.compile(nameRegex == null ? ".*" : nameRegex,
                Pattern.CASE_INSENSITIVE);
        this.builtInGamingDevice = builtInGamingDevice;
        this.mapping = Collections.unmodifiableMap(new EnumMap<>(mapping));
    }

    public boolean matches(GamepadDescriptor device) {
        if (vendorId >= 0 && vendorId != device.vendorId) return false;
        if (productId >= 0 && productId != device.productId) return false;
        return namePattern.matcher(device.name).find() || namePattern.matcher(device.descriptor).find();
    }

    public Map<CanonicalControl, InputSignal> mapping() { return mapping; }
}
