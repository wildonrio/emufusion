package com.thorium.preview.game;

import android.opengl.GLES20;

/** Diagnostic readback protocol on a real GLES2 pbuffer; no gameplay claim. */
final class FullResolutionCaptureDeviceTest {
    static void run() {
        run(3,3);
        run(1920,1080);
    }
    private static void run(int width,int height) {
        GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
        GLES20.glColorMask(true,true,true,true);
        GLES20.glPixelStorei(GLES20.GL_PACK_ALIGNMENT,8);
        FullResolutionFrameReadback capture=new FullResolutionFrameReadback(
                FullResolutionFrameReadback.backendForContext(2),width,height,4,42);
        try {
            for(int channel=0;channel<3;channel++) {
                GLES20.glClearColor(channel==0?1:0,channel==1?1:0,channel==2?1:0,1);
                GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
                capture.enqueue(10);
                int[] alignment=new int[1];GLES20.glGetIntegerv(GLES20.GL_PACK_ALIGNMENT,alignment,0);
                if(alignment[0]!=8)throw new AssertionError("pack alignment not restored");
            }
            if(capture.poll(10,4,42)!=null || capture.poll(11,4,42)!=null)
                throw new AssertionError("partial triplet returned");
            byte[][] images=capture.poll(12,4,42);
            if(images==null || images.length!=3 || !capture.isClosed())throw new AssertionError("missing triplet");
            for(int image=0;image<3;image++)for(int pixel=0;pixel<width*height;pixel++)for(int c=0;c<4;c++) {
                int expected=(c==image || c==3)?255:0;
                if((images[image][pixel*4+c]&255)!=expected)throw new AssertionError("wrong image/pixel/channel");
            }
            if(GLES20.glGetError()!=GLES20.GL_NO_ERROR)throw new AssertionError("GL error");
            System.out.println("GLES2_CAPTURE_PASS images=3 pixels_per_image="+(width*height)+" rgba_exact=true pack_alignment_restored=true synchronous=true");
        } finally {capture.close();GLES20.glPixelStorei(GLES20.GL_PACK_ALIGNMENT,4);}
    }
}
