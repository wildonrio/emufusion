package com.thorium.preview.game;

import java.nio.ByteBuffer;

/** GL-thread-owned, explicitly armed one-triplet diagnostic. Caller supplies
 * G, A, B framebuffers. GLES2 fallback is synchronous and invalidates timing
 * qualification for its capture window; it never runs in unarmed gameplay. */
final class FullResolutionFrameReadback implements AutoCloseable {
    interface Backend extends AutoCloseable {
        int configure(int width, int height, int bytes);
        int enqueue(long sequence, long present);
        long[] poll(long present, ByteBuffer output);
        void close();
    }

    static Backend backendForContext(int major) {
        if (major >= 3) return nativeBackend();
        if (major == 2) return new SynchronousDiagnosticBackend();
        throw new IllegalArgumentException("unsupported capture context");
    }

    static String readbackName(int major) {
        return major >= 3 ? "async-pbo" : "synchronous-diagnostic";
    }

    /** Same identity protocol as the PBO backend, not native GPU timing data. */
    static final class SynchronousDiagnosticBackend implements Backend {
        private final ByteBuffer[] rows = new ByteBuffer[3];
        private final long[] sequences = new long[3], presents = new long[3];
        private int width,height,bytes,queued,read;
        private boolean closed;

        public int configure(int w,int h,int count) {
            if(closed || bytes!=0 || w<=0 || h<=0 || (long)w*h*4!=count) return 0;
            width=w;height=h;bytes=count;
            // Backend-ready mask consumed by this class only. No native
            // capability or asynchronous completion claim is made here.
            return 15;
        }
        public int enqueue(long sequence,long present) {
            if(closed || bytes==0 || queued>=3 || sequence<=0 || present<=0) return -1;
            ByteBuffer data=ByteBuffer.allocateDirect(bytes);
            if(android.opengl.GLES20.glGetError()!=android.opengl.GLES20.GL_NO_ERROR) return -1;
            int[] alignment=new int[1];
            android.opengl.GLES20.glGetIntegerv(android.opengl.GLES20.GL_PACK_ALIGNMENT,alignment,0);
            try {
                android.opengl.GLES20.glPixelStorei(android.opengl.GLES20.GL_PACK_ALIGNMENT,1);
                android.opengl.GLES20.glReadPixels(0,0,width,height,android.opengl.GLES20.GL_RGBA,
                        android.opengl.GLES20.GL_UNSIGNED_BYTE,data);
            } finally {
                android.opengl.GLES20.glPixelStorei(android.opengl.GLES20.GL_PACK_ALIGNMENT,alignment[0]);
            }
            if(android.opengl.GLES20.glGetError()!=android.opengl.GLES20.GL_NO_ERROR) return -1;
            data.position(0);rows[queued]=data;sequences[queued]=sequence;presents[queued]=present;
            queued++;return 0;
        }
        public long[] poll(long present,ByteBuffer output) {
            if(closed || read>=queued) return new long[0];
            if(output.remaining()<bytes) throw new IllegalArgumentException("capture output too small");
            output.put(rows[read].duplicate());
            long[] row=new long[15];row[3]=sequences[read];row[4]=presents[read];
            row[5]=bytes;row[6]=present-presents[read];
            rows[read++]=null;return row;
        }
        public void close(){closed=true;for(int i=0;i<rows.length;i++)rows[i]=null;}
    }

    static Backend nativeBackend() {
        final DenseGpuTimer timer = DenseGpuTimer.create();
        return new Backend() {
            public int configure(int w, int h, int bytes) {
                return timer.configureProofAtlas(w, h, bytes, 4);
            }
            public int enqueue(long sequence, long present) {
                return timer.enqueueProofAtlas(sequence, present);
            }
            public long[] poll(long present, ByteBuffer output) {
                return timer.pollProofAtlas(present, output);
            }
            public void close() { timer.close(); }
        };
    }

    private final Backend backend;
    private final ByteBuffer pixels;
    private final byte[][] images = new byte[3][];
    private final long epoch, physicalFrameId;
    private long queuedPresent;
    private int enqueued, completed;
    private boolean closed;

    FullResolutionFrameReadback(Backend backend, int width, int height,
            long epoch, long physicalFrameId) {
        if (backend == null) throw new IllegalArgumentException("missing backend");
        this.backend = backend;
        long pixelCount = (long) width * height;
        long bytes = pixelCount > 0 && pixelCount <= (128L << 20) / 32
                ? pixelCount * 4 : 0;
        // Four native PBOs + destination + three exported planes, <=128MiB.
        if (width <= 0 || height <= 0 || bytes <= 0 ||
                bytes > (128L << 20) / 8 || epoch <= 0 || physicalFrameId <= 0) {
            backend.close();
            throw new IllegalArgumentException("invalid capture geometry or identity");
        }
        this.epoch = epoch;
        this.physicalFrameId = physicalFrameId;
        try {
            if ((backend.configure(width, height, (int) bytes) & 15) != 15)
                throw new IllegalStateException("full-resolution readback unavailable");
            pixels = ByteBuffer.allocateDirect((int) bytes);
        } catch (RuntimeException failure) {
            backend.close();
            throw failure;
        }
    }

    /** Queue currently bound G, then A, then B, before the source pair advances. */
    void enqueue(long present) {
        if (closed || enqueued >= 3 || present <= 0)
            throw new IllegalStateException("capture not accepting images");
        if (enqueued > 0 && present != queuedPresent) {
            close();
            throw new IllegalStateException("triplet spans different presentations");
        }
        if (backend.enqueue(enqueued + 1L, present) != 0) {
            close();
            throw new IllegalStateException("capture enqueue failed");
        }
        ++enqueued;
        queuedPresent = present;
    }

    /** Returns G/A/B once, only after all three tagged transfers complete.
     * This is image evidence, NOT proof that physicalFrameId was displayed. */
    byte[][] poll(long present, long currentEpoch, long expectedPhysicalFrameId) {
        if (closed) return null;
        if (currentEpoch != epoch || expectedPhysicalFrameId != physicalFrameId) {
            close();
            return null;
        }
        if (enqueued > 0 && (present < queuedPresent || present - queuedPresent > 8)) {
            close();
            return null;
        }
        // Drain already-ready transfers in this callback. Waiting a display
        // frame between each plane needlessly exposes an immutable triplet to
        // a later epoch reset. Never wait for the GPU: an empty poll yields.
        while (completed < enqueued) {
            pixels.clear();
            long[] row = backend.poll(present, pixels);
            if (row.length == 0) return null;
            if (row.length != 15 || row[0] != 0 || row[3] != completed + 1L ||
                    row[4] != queuedPresent ||
                    row[5] != pixels.capacity() || completed >= enqueued ||
                    row[6] < 0 || row[6] > 8) {
                close();
                throw new IllegalStateException("capture completion identity/size/age mismatch");
            }
            pixels.position(0);
            images[completed] = new byte[pixels.capacity()];
            pixels.get(images[completed++]);
        }
        if (completed != 3) return null;
        byte[][] result = images.clone();
        close();
        return result;
    }

    boolean isClosed() { return closed; }

    public void close() {
        if (!closed) {
            closed = true;
            backend.close();
            for (int i = 0; i < images.length; ++i) images[i] = null;
        }
    }
}
