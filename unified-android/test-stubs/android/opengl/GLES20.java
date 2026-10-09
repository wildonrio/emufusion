package android.opengl;

import java.nio.Buffer;

/**
 * Host-only stand-in for the few GLES20 entry points FullResolutionFrameReadback
 * names, so test.sh can compile it without android.jar. The unit test drives
 * the class through its injected Backend; these are never called.
 */
public final class GLES20 {
    public static final int GL_NO_ERROR = 0;
    public static final int GL_PACK_ALIGNMENT = 0x0D05;
    public static final int GL_RGBA = 0x1908;
    public static final int GL_UNSIGNED_BYTE = 0x1401;

    private GLES20() {}

    public static int glGetError() { throw new UnsupportedOperationException("host stub"); }
    public static void glGetIntegerv(int pname, int[] params, int offset) { throw new UnsupportedOperationException("host stub"); }
    public static void glPixelStorei(int pname, int param) { throw new UnsupportedOperationException("host stub"); }
    public static void glReadPixels(int x, int y, int width, int height, int format, int type, Buffer pixels) { throw new UnsupportedOperationException("host stub"); }
}
