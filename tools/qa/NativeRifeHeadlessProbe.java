package com.emufusion.rifebenchmark;

import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Bounded endpoint-only probe. No Activity, Surface, or wakelock. */
public final class NativeRifeHeadlessProbe {
    public static void main(String[] args) throws Exception {
        String root = args[0];
        int width = 256, height = 192, bytes = width*height*4;
        ByteBuffer left = ByteBuffer.allocateDirect(bytes);
        ByteBuffer right = ByteBuffer.allocateDirect(bytes);
        ByteBuffer output = ByteBuffer.allocateDirect(bytes);
        byte[] a = Files.readAllBytes(Paths.get(root, "left.rgba"));
        byte[] b = Files.readAllBytes(Paths.get(root, "right.rgba"));
        if (a.length != bytes || b.length != bytes) throw new IllegalArgumentException("size");
        // The exported endpoints are bottom-up; RIFE expects top-down pixels.
        for (int y=height-1; y>=0; --y) {
            left.put(a, y*width*4, width*4);
            right.put(b, y*width*4, width*4);
        }
        left.rewind(); right.rewind();
        try (NativeRifeBridge bridge = new NativeRifeBridge(root, 0, 1)) {
            System.out.println("BUILD_ID=" + NativeRifeBridge.libraryBuildId());
            System.out.println("CAPABILITIES=" + bridge.capabilitiesJson());
            for (int iteration=0; iteration<150; ++iteration) {
                NativeRifeBridge.Timing t = bridge.interpolate(left, right, width, height,
                                                              width*4, 0.5f, output);
                System.out.println("TIMING,"+iteration+","+t.inputConvertNs+","+
                    t.processV4CompositeNs+","+t.outputConvertNs+","+t.endToEndNs);
            }
            byte[] result = new byte[bytes];
            for (int y=height-1; y>=0; --y) output.get(result, y*width*4, width*4);
            Files.write(Paths.get(root, "generated.rgba"), result);
            System.out.println("COMPLETED_CALLS=" + bridge.interpolationCallCount());
        }
    }
}
