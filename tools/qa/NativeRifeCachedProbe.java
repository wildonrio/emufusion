package com.emufusion.rifebenchmark;

import android.graphics.PixelFormat;
import android.hardware.HardwareBuffer;
import android.media.Image;
import android.media.ImageReader;
import android.media.ImageWriter;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.Duration;

/** Retains exact endpoint buffers offscreen; no display or application install. */
public final class NativeRifeCachedProbe {
    static Image upload(ImageReader reader, ImageWriter writer, byte[] rgba) throws Exception {
        try (Image input = writer.dequeueInputImage()) {
            Image.Plane plane = input.getPlanes()[0];
            ByteBuffer pixels = plane.getBuffer();
            if (plane.getPixelStride()!=4 || rgba.length!=256*192*4)
                throw new IllegalStateException("unexpected input layout");
            for(int y=0; y<192; ++y) {
                pixels.position(y*plane.getRowStride());
                pixels.put(rgba,(191-y)*256*4,256*4);
            }
            writer.queueInputImage(input);
        }
        long deadline=System.nanoTime()+2_000_000_000L;
        Image image;
        while ((image=reader.acquireNextImage())==null && System.nanoTime()<deadline)
            Thread.sleep(1);
        if(image==null) throw new IllegalStateException("input acquisition timeout");
        try(android.hardware.SyncFence fence=image.getFence()) {
            if(fence.isValid() && !fence.await(Duration.ofSeconds(2)))
                throw new IllegalStateException("producer fence timeout");
        }
        return image;
    }
    public static void main(String[] args) throws Exception {
        String root=args[0];
        long usage=HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE | HardwareBuffer.USAGE_CPU_WRITE_OFTEN;
        try(ImageReader reader=ImageReader.newInstance(256,192,PixelFormat.RGBA_8888,3,usage);
            ImageWriter writer=ImageWriter.newInstance(reader.getSurface(),3);
            Image left=upload(reader,writer,Files.readAllBytes(Paths.get(root,"left.rgba")));
            Image right=upload(reader,writer,Files.readAllBytes(Paths.get(root,"right.rgba")));
            HardwareBuffer a=left.getHardwareBuffer();
            HardwareBuffer b=right.getHardwareBuffer();
            NativeRifeBridge bridge=new NativeRifeBridge(root,0,1)) {
            System.out.println("BUILD_ID="+NativeRifeBridge.libraryBuildId());
            System.out.println("CAPABILITIES="+bridge.capabilitiesJson());
            System.out.println("PRIME="+bridge.benchmarkCachedHardwareBufferRife(a,b,256,192,.5f,1,5));
            System.out.println("CACHED="+bridge.benchmarkCachedHardwareBufferRife(a,b,256,192,.5f,16,120));
        }
    }
}
