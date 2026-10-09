package com.thorium.preview.game;

import android.graphics.PixelFormat;
import android.media.ImageReader;
import android.view.Surface;

/** Offscreen pixel experiment; primed one-shot time is not gameplay throughput. */
public final class LsfgPixelProbe {
    private static native long generate(Surface output, String shaders,
            String left, String right, String result, int width, int height,
            String previous);

    public static void main(String[] args) {
        if (args.length != 7 && args.length != 8) throw new IllegalArgumentException(
                "Expected library shaders left right output width height [previous]");
        int width = Integer.parseInt(args[5]);
        int height = Integer.parseInt(args[6]);
        if (width < 1 || height < 1 || width > 1920 || height > 1080)
            throw new IllegalArgumentException("Unsupported geometry");
        System.load(args[0]);
        try (ImageReader reader = ImageReader.newInstance(width, height,
                PixelFormat.RGBA_8888, 3)) {
            long elapsed = generate(reader.getSurface(), args[1], args[2],
                    args[3], args[4], width, height, args.length == 8 ? args[7] : null);
            System.out.println("PRIMED_COMPLETION_NS=" + elapsed);
            System.out.println(args.length == 8 ?
                    "HISTORY=previous,previous,previous,left,right" :
                    "HISTORY=left,left,left,right");
            System.out.println("PRESENTATION_QUALIFIED=false");
        }
    }
}
