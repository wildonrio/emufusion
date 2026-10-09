package com.thorium.lucent.video;

import java.nio.ByteBuffer;

/**
 * Value-only, nonblocking diagnostics for one exact native adapter host.
 *
 * <p>Callers allocate direct output buffers during setup and query only the
 * positive raw timestamp of an actually consumed image. Implementations must
 * not redirect an existing provider to a replacement host, wait for a row, or
 * select a neighboring timestamp. Missing, pending, busy and closed results
 * remain explicit evidence gaps. A successful query grants no image-cadence,
 * guest-clock, generated-frame or physical-presentation authority.</p>
 */
public interface NativeSourceImageProvider {
    int sourceImageBinding(ByteBuffer output);

    int querySourceImage(long sessionEpoch, long surfaceEpoch,
                         long rawTimestampNs, ByteBuffer output);
}
