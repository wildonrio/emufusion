package com.thorium.preview.game;

import android.graphics.SurfaceTexture;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.EGLExt;
import android.opengl.GLES11Ext;
import android.opengl.GLES20;
import android.opengl.GLES30;
import android.opengl.GLUtils;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import android.view.Choreographer;
import android.view.Surface;

import com.thorium.lucent.video.AdaptiveFrameRateController;
import com.thorium.lucent.video.EndpointFrameSelector;
import com.thorium.lucent.video.FrameGenerationCadence;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.lang.ref.WeakReference;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.zip.CRC32;

/**
 * Engine-neutral display-vsync frame generator.
 *
 * <p>An internal emulator renders into {@link #inputSurface()} exactly as it
 * would render into the display. That Surface is backed by a SurfaceTexture,
 * so this class receives complete producer frames without knowing whether the
 * producer is Canvas, OpenGL ES, Vulkan, or a native adapter. The two newest
 * real images are retained on the GPU. A two-stage block-matching pass derives
 * a motion field from each promoted pair, and the display pass warps both real
 * images toward the requested presentation time before combining them at the
 * real display's Choreographer cadence into the actual window Surface.
 *
 * <p>Simulation and audio clocks are intentionally outside this class. A
 * 60 fps core still runs exactly 60 times per second on a 120 Hz panel; only
 * the presentation layer creates the in-between image. At matched source and
 * display rates the latest frame is passed through, avoiding interpolation
 * latency. A long producer pause settles on the newest real frame.
 */
public final class DisplayFrameGenerator implements AutoCloseable,
        SurfaceTexture.OnFrameAvailableListener, Choreographer.FrameCallback {
    public interface QualificationProofSwitch {
        boolean enabled();
    }
    public interface DensePyramidSwitch {
        boolean enabled();
    }
    public interface DenseV27ReducedAnalysisSwitch {
        boolean enabled();
    }
    public interface DenseV28ReducedAnalysisSwitch {
        boolean enabled();
    }
    public interface StatsListener {
        void onFrameRate(int lockedSourceFps, int outputFps);
    }
    private static final String TAG = "EmuFusionFrameGen";
    // Evidence is deliberately schema-versioned. Qualification artifacts are
    // immutable: a verifier must never reinterpret counters emitted by an
    // older implementation as proof of the current vector-prediction path.
    private static final String PROOF_CONTRACT =
            "native-pixel-refined-regional-flow-v22-x2-presented";
    private static final int PROOF_SCHEMA_VERSION = 22;
    private static final String DENSE_PROOF_CONTRACT =
            "dense-pyramid-timer-v26-raw-ns-qualification-x2-presented";
    private static final int DENSE_PROOF_SCHEMA_VERSION = 26;
    private static final String DENSE_V27_PROOF_CONTRACT =
            "dense-fragment-192x108-v27-qualification-x2-presented";
    private static final int DENSE_V27_PROOF_SCHEMA_VERSION = 27;
    private static final String DENSE_V28_PROOF_CONTRACT =
            "dense-fragment-128x72-v39-present-timed-vector-trajectory-qualification-x2-presented";
    private static final int DENSE_V28_PROOF_SCHEMA_VERSION = 39;
    private static final String PRESENTATION_TIMING_MODE =
            "egl-android-next-vsync";
    private static final int DENSE_CADENCE_REJECT_CONSECUTIVE_WINDOWS = 3;
    private static final int DENSE_V26_ANALYSIS_MAX_WIDTH = 256;
    private static final int DENSE_V26_ANALYSIS_MAX_HEIGHT = 144;
    private static final int DENSE_V27_ANALYSIS_MAX_WIDTH = 192;
    private static final int DENSE_V27_ANALYSIS_MAX_HEIGHT = 108;
    private static final int DENSE_V28_ANALYSIS_MAX_WIDTH = 128;
    private static final int DENSE_V28_ANALYSIS_MAX_HEIGHT = 72;
    private static final int DENSE_LEVELS = 3;
    private static final int[] DENSE_LEVEL_ITERATIONS = {4, 4, 8};
    private static final int DENSE_PASSES_PER_PROMOTION = 38;
    private static final float DENSE_MAX_FLOW_PIXELS = 47f;
    private static final long DENSE_GPU_BUDGET_US = 7333L;
    private static final int DENSE_PERFORMANCE_MIN_SAMPLES = 30;
    private static final int DENSE_WALL_PROMOTION = 0;
    private static final int DENSE_WALL_SIGNATURE = 1;
    private static final int DENSE_WALL_PROOF = 2;
    private static final int DENSE_WALL_PRESENT = 3;
    private static final int DENSE_WALL_SWAP = 4;
    private static final int DENSE_WALL_PROOF_ENQUEUE = 5;
    private static final int DENSE_WALL_PROOF_POLL = 6;
    private static final int GL_RGBA8_OES = 0x8058;
    private static final int DENSE_SIGNATURE_CAP_RGBA8 = 32;
    private static final int DENSE_SIGNATURE_CAP_READY =
            DenseGpuTimer.SIGNATURE_CAP_READY | DENSE_SIGNATURE_CAP_RGBA8;
    private static final long START_TIMEOUT_MS = 2500L;
    private static final long STOP_TIMEOUT_MS = 1500L;
    private static final int EGL_OPENGL_ES2_BIT = 4;
    private static final int EGL_OPENGL_ES3_BIT_KHR = 0x40;
    private static final int GL_MAJOR_VERSION = 0x821B;
    private static final int GL_MINOR_VERSION = 0x821C;
    private static final int FLOAT_BYTES = 4;
    // Keep the search dense enough to track console-scale motion while leaving
    // enough GPU time for the compositor to meet every 120 Hz presentation
    // deadline on the Thor. The vectors are bilinearly interpolated by the
    // synthesis shader, so these are field-sampling rates, not output pixels.
    private static final int LOW_RES_COARSE_FLOW_DIVISOR = 24;
    private static final int HIGH_RES_COARSE_FLOW_DIVISOR = 54;
    // Native-resolution handheld sources retain one vector per 16x16 block.
    // At 720p and above, a robust nine-tap bidirectional search at that density
    // backpressured GameCube to 35-53 visible Hz. One vector per 36x36 block is
    // still bilinearly interpolated and spatially regularized at full output
    // resolution, while cutting matcher fragments by four. The empirical
    // vector/crossfade and SurfaceFlinger gates reject insufficient density.
    private static final int LOW_RES_FINE_FLOW_DIVISOR = 16;
    private static final int HIGH_RES_FINE_FLOW_DIVISOR = 36;
    private static final int HIGH_RES_FLOW_THRESHOLD = 720;
    private static final float MAX_FLOW_PIXELS = 80f;
    // A fixed 80-pixel search is appropriate for a 1080p source, but it is
    // almost half the height of one 256x192 DS screen.  At that scale an
    // ambiguous match can pull a character or background across the whole
    // picture and turn interpolation into a visibly melted frame.  Preserve
    // the reviewed full-resolution bound while limiting low-resolution cores
    // to ten percent of their shorter source dimension.
    private static final float MAX_FLOW_SOURCE_FRACTION = 0.10f;
    private static final float MIN_FLOW_PIXELS = 4f;
    private static final int PROOF_WIDTH = 48;
    private static final int PROOF_HEIGHT = 27;
    private static final int PROOF_ATLAS_WIDTH = 192;
    private static final int PROOF_ATLAS_HEIGHT = 64;
    private static final int PROOF_ATLAS_BYTES =
            PROOF_ATLAS_WIDTH * PROOF_ATLAS_HEIGHT * 4;
    private static final int PROOF_ATLAS_RING_SIZE = 4;
    // Layout 5 preserves every schema-36 image tile and additionally binds the
    // sample to its producer-clock target. Older nominal-tier evidence cannot
    // be reinterpreted as timestamp-resampled output.
    private static final int PROOF_ATLAS_LAYOUT_VERSION = 5;
    private static final int DENSE_DIAGNOSTIC_TILES_X = 6;
    private static final int DENSE_DIAGNOSTIC_TILES_Y = 3;
    private static final int HEALTH_LOG_MAX_UTF8_BYTES = 3900;
    private static final int DENSE_DIAG_ACTIVE = 1;
    private static final int DENSE_DIAG_IN_BOUNDS = 2;
    private static final int DENSE_DIAG_CYCLE_VALID = 4;
    private static final int DENSE_DIAG_PHOTOMETRIC_VALID = 8;
    private static final int DENSE_DIAG_TEXTURE_VALID = 16;
    private static final int DENSE_DIAG_SATURATED = 32;
    private static final int DENSE_DIAG_OUT_OF_BOUNDS = 64;
    private static final int DENSE_DIAGNOSTIC_PACK_X = 48;
    private static final int DENSE_DIAGNOSTIC_PACK_Y = 55;
    private static final int DENSE_DIAGNOSTIC_PACK_WIDTH = 144;
    private static final int DENSE_DIAGNOSTIC_PACK_HEIGHT = 9;
    private static final int PROOF_ATLAS_HEADER_X = 48;
    private static final int PROOF_ATLAS_HEADER_Y = 54;
    private static final int PROOF_ATLAS_HEADER_BYTES = 104;
    private static final int PROOF_ATLAS_CAP_READY = 63;
    private static final int SIGNATURE_WIDTH = 16;
    private static final int SIGNATURE_HEIGHT = 9;
    // The asynchronous occlusion result may trail the producer by as many as
    // four callbacks. Retain the exact full-resolution image tagged by each
    // query until that query completes; applying an old result to the newest
    // overwriteable texture phase-shifts the source clock and can manufacture
    // both duplicates and missing endpoints. Two additional ready textures
    // provide the active scheduler with a bounded one-frame lookahead while a
    // third coalesces producer bursts without touching either active endpoint.
    private static final int SIGNATURE_CANDIDATE_SLOTS = 4;
    // Two textures own the active interpolation pair. Four additional queued
    // endpoints absorb bounded producer jitter without adding deliberate
    // latency: presentation consumes the head as soon as its source position
    // advances. Overflow rebases to the newest endpoint and waits for its
    // exact successor instead of ever interpolating across a dropped frame.
    private static final int ENDPOINT_FIFO_CAPACITY = 4;
    // The active left/right pair consumes two retained images. Keep one exact
    // successor behind it before starting the presentation clock so a REAL
    // right endpoint can rotate immediately into the next ready pair. Starting
    // from only two images made 50-to-100 repeatedly reach a selected panel
    // slot before its next right endpoint existed, despite a healthy producer.
    private static final int ENDPOINT_FIFO_PRIME_DEPTH = ENDPOINT_FIFO_CAPACITY;
    // Keep a tiny future-endpoint reserve for a proven 60-Hz source. Android
    // may deliver several SurfaceTexture callbacks close together after a
    // short producer scheduling delay. The fixed selector intentionally never
    // catches up, but discarding all of those callbacks left the next 120-Hz
    // slots empty. At most two otherwise-unscheduled callbacks may refill this
    // queue; output remains controller-paced and never exceeds 2x.
    private static final int ENDPOINT_FIFO_JITTER_RESERVE = 2;
    // A screen-wide translation failed closed on perspective/parallax scenes:
    // no one vector improved enough of the image. These overlapping regional
    // controls retain bounded fixed work while allowing a coherent spatially
    // varying camera field. Linear texture sampling feathers adjacent cells.
    private static final int REGIONAL_FLOW_WIDTH = 12;
    private static final int REGIONAL_FLOW_HEIGHT = 8;
    private static final int REGIONAL_FLOW_CELLS =
            REGIONAL_FLOW_WIDTH * REGIONAL_FLOW_HEIGHT;
    private static final int REGIONAL_CANDIDATES_X = 5;
    private static final int REGIONAL_CANDIDATES_Y = 5;
    private static final int REGIONAL_CANDIDATE_WIDTH =
            REGIONAL_FLOW_WIDTH * REGIONAL_CANDIDATES_X;
    private static final int REGIONAL_CANDIDATE_HEIGHT =
            REGIONAL_FLOW_HEIGHT * REGIONAL_CANDIDATES_Y;
    // Proof readback is deliberately sparse. glReadPixels is synchronous on
    // the presentation thread; sampling twelve times per second can itself
    // create the missed-vsync pattern this class is meant to remove.
    // 59 is coprime to every supported 120-Hz source cadence (2, 3, 4 and
    // the 12-tick 50-FPS pattern), so proof samples rotate through real and
    // generated phases instead of repeatedly landing on the same endpoint.
    // Two-screen systems run two generators; ~2 samples/sec per display and a
    // 48x27 audit buffer avoid making synchronous qualification readback—not
    // interpolation—the reason a heavy 3DS title misses panel deadlines.
    private static final int PROOF_SAMPLE_INTERVAL = 59;
    // The runtime collector may establish a fresh clean baseline late in an
    // otherwise unchanged presentation epoch after a transient source gap.
    // Sixty samples were exhausted before that baseline in r68, making the
    // mandatory 30 post-baseline proofs mathematically impossible even though
    // cadence immediately returned to exact 60/120. At the existing roughly
    // two-samples/second cadence, 120 remains a hard bounded reservoir while
    // exceeding the collector's 52-second evidence window.
    private static final int MAX_QUALIFICATION_PROOF_SAMPLES = 120;
    // One second at 120 Hz fits in SurfaceFlinger's 128-entry latency history,
    // letting QA join this exact monotonic window to the exact gameplay layer.
    private static final int HEALTH_INTERVAL = 120;
    private static final Map<Surface, WeakReference<DisplayFrameGenerator>> INPUTS =
            new IdentityHashMap<>();
    private static final AtomicInteger NEXT_GENERATOR_ID = new AtomicInteger(1);

    private static final float[] QUAD = {
            -1f, -1f, 0f, 0f,
             1f, -1f, 1f, 0f,
            -1f,  1f, 0f, 1f,
             1f,  1f, 1f, 1f
    };

    private static final String VERTEX_SHADER =
            "attribute vec2 aPosition;\n" +
            "attribute vec2 aTexCoord;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main(){ gl_Position=vec4(aPosition,0.0,1.0); vTexCoord=aTexCoord; }\n";

    private static final String COPY_SHADER =
            "#extension GL_OES_EGL_image_external : require\n" +
            "precision mediump float;\n" +
            "uniform samplerExternalOES uTexture;\n" +
            "uniform mat4 uTransform;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main(){ vec2 uv=(uTransform*vec4(vTexCoord,0.0,1.0)).xy;" +
            " gl_FragColor=texture2D(uTexture,uv); }\n";

    // Exact sampler2D copy used for source signatures and latest-frame
    // presentation. It is intentionally separate from both the external-OES
    // producer copy and the transformed effective-flow proof shader.
    private static final String TEXTURE_COPY_SHADER =
            "precision mediump float;\n" +
            "uniform sampler2D uTexture;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main(){ gl_FragColor=texture2D(uTexture,vTexCoord); }\n";

    // The Adreno driver accepted a client-memory glTexSubImage2D header upload
    // but produced an all-zero atlas row. Render the immutable 104-byte tag
    // through the same GPU command stream as the proof tiles instead. Each
    // uniform component is one exact RGBA8 byte normalized by 255.
    private static final String PROOF_ATLAS_HEADER_SHADER =
            "precision highp float;\n" +
            "uniform vec4 uWords[26]; varying vec2 vTexCoord;\n" +
            "void main(){int i=int(clamp(floor(vTexCoord.x*26.0),0.0,25.0));" +
            "gl_FragColor=uWords[i];}\n";

    // v34 sampled the validated alpha mask through the persistent LINEAR
    // filters used by RG/B proof, corrupting its bitfield during 160x90 to
    // 48x27 reduction. Layout 5 keeps those linear tiles byte-for-byte, binds
    // presentation/source-time evidence in the in-band header, and
    // separately flattens the same 1296 logical cells into a 144x9 tile.
    // The caller temporarily selects NEAREST for this draw only.
    private static final String DENSE_DIAGNOSTIC_PACK_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uBackwardMask,uForwardMask; varying vec2 vTexCoord;\n" +
            "void main(){float ix=floor(clamp(vTexCoord.x,0.0,.999999)*144.0);" +
            "float iy=floor(clamp(vTexCoord.y,0.0,.999999)*9.0);" +
            "float cell=iy*144.0+ix;float x=mod(cell,48.0);float y=floor(cell/48.0);" +
            "vec2 uv=(vec2(x,y)+.5)/vec2(48.0,27.0);" +
            "float b=texture2D(uBackwardMask,uv).a;" +
            "float f=texture2D(uForwardMask,uv).a;" +
            "gl_FragColor=vec4(b,f,0.0,0.0);}\n";

    // ES2-compatible asynchronous uniqueness classifier. Exact repeated
    // RGBA8 signature texels discard every fragment, so
    // GL_ANY_SAMPLES_PASSED_EXT is false. Any changed texel survives and
    // yields true without copying pixels back to the CPU.
    private static final String SIGNATURE_COMPARE_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform sampler2D uPrevious;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main(){vec4 a=texture2D(uCurrent,vTexCoord);" +
            "vec4 b=texture2D(uPrevious,vTexCoord);" +
            "if(all(equal(a,b)))discard;gl_FragColor=vec4(1.0);}\n";

    private static final String FLOW_PROOF_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uBackwardMotion;\n" +
            "uniform sampler2D uForwardMotion;\n" +
            "uniform sampler2D uGlobalBackwardMotion;\n" +
            "uniform sampler2D uGlobalForwardMotion;\n" +
            "uniform vec2 uFlowRange;\n" +
            "uniform float uDenseEncoding;\n" +
            "varying vec2 vTexCoord;\n" +
            "vec2 decodeFlow(vec4 field){vec2 legacy=field.rg*2.0-1.0;vec2 dense=(field.rg*255.0-128.0)/127.0;return mix(legacy,dense,uDenseEncoding)*uFlowRange;}\n" +
            "void main(){\n" +
            " vec4 backwardField=texture2D(uBackwardMotion,vTexCoord);\n" +
            " vec4 forwardField=texture2D(uForwardMotion,vTexCoord);\n" +
            " vec2 backward=decodeFlow(backwardField);\n" +
            " vec2 forward=decodeFlow(forwardField);\n" +
            " vec4 forwardPeer=texture2D(uForwardMotion,clamp(vTexCoord+backward,vec2(0.0),vec2(1.0)));\n" +
            " vec2 safeRange=max(uFlowRange,vec2(0.00001));\n" +
            " float localCycle=length((backward+decodeFlow(forwardPeer))/safeRange);\n" +
            " float localReliability=sqrt(clamp(backwardField.b,0.0,1.0)*clamp(forwardPeer.b,0.0,1.0))*clamp(1.0-4.0*localCycle,0.0,1.0);\n" +
            " vec4 gbField=texture2D(uGlobalBackwardMotion,vTexCoord);\n" +
            " vec2 globalBackward=decodeFlow(gbField);\n" +
            " vec4 gfField=texture2D(uGlobalForwardMotion,clamp(vTexCoord+globalBackward,vec2(0.0),vec2(1.0)));\n" +
            " vec2 globalForward=decodeFlow(gfField);\n" +
            " float globalCycle=length((globalBackward+globalForward)/safeRange);\n" +
            " float globalReliability=sqrt(clamp(gbField.b,0.0,1.0)*clamp(gfField.b,0.0,1.0))*clamp(1.0-5.0*globalCycle,0.0,1.0);\n" +
            " float globalUse=smoothstep(0.10,0.24,globalReliability)*(1.0-smoothstep(0.04,0.18,localReliability));\n" +
            " vec2 selected=mix(backward,globalBackward,globalUse);\n" +
            " float confidence=max(localReliability,globalReliability*globalUse);\n" +
            " gl_FragColor=vec4(clamp(selected/safeRange*0.5+0.5,0.0,1.0),confidence,1.0);\n" +
            "}\n";

    // Qualification-only classical coarse-to-fine flow. Vectors are signed
    // Q8.8 source pixels (X in RG, Y in BA), avoiding the zero drift and byte
    // carry artifacts of normalized RG flow. The final cycle pass converts to
    // the v22 synthesis field format only after independent forward/reverse
    // agreement and photometric validation.
    private static final String DENSE_PYRAMID_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uTexture; uniform vec2 uInputTexel;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main(){vec2 h=uInputTexel*0.5;vec4 v=texture2D(uTexture,clamp(vTexCoord-h,0.0,1.0));\n" +
            "v+=texture2D(uTexture,clamp(vTexCoord+vec2(h.x,-h.y),0.0,1.0));\n" +
            "v+=texture2D(uTexture,clamp(vTexCoord+vec2(-h.x,h.y),0.0,1.0));\n" +
            "v+=texture2D(uTexture,clamp(vTexCoord+h,0.0,1.0));gl_FragColor=v*0.25;}\n";

    private static final String DENSE_SOLVE_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uReference,uTarget,uPriorFlow,uGuideFlow; uniform float uHasPrior,uUseReciprocalGuide,uGuideLimit,uUseWidePatch,uFinalConsensus,uBypassSearch;\n" +
            "uniform vec2 uAnalysisTexel,uPriorTexel,uGuideTexel,uSourceSize,uUpdateStep; varying vec2 vTexCoord;\n" +
            "float lum(vec3 c){return dot(c,vec3(.299,.587,.114));}\n" +
            "vec2 chroma(vec3 c){return vec2(.5*(c.r-c.b),.5*c.g-.25*(c.r+c.b));}\n" +
            "float unp(vec2 p){float r=floor(p.x*255.0+.5)*256.0+floor(p.y*255.0+.5);return r>=32768.0?r-65536.0:r;}\n" +
            "vec2 dec(vec4 f){return vec2(unp(f.rg),unp(f.ba))/256.0;}\n" +
            // Packed bytes use NEAREST. Decode each corner first, then blend
            // numeric vectors manually so interpolation never crosses a byte
            // carry as if packed RGBA were ordinary color.
            "vec2 decLinear(vec2 uv){vec2 p=uv/uPriorTexel-.5;vec2 b=floor(p);vec2 f=fract(p);\n" +
            "vec2 a=(b+.5)*uPriorTexel;vec2 x=vec2(uPriorTexel.x,0.0),y=vec2(0.0,uPriorTexel.y);\n" +
            "vec2 v00=dec(texture2D(uPriorFlow,clamp(a,0.0,1.0))),v10=dec(texture2D(uPriorFlow,clamp(a+x,0.0,1.0)));\n" +
            "vec2 v01=dec(texture2D(uPriorFlow,clamp(a+y,0.0,1.0))),v11=dec(texture2D(uPriorFlow,clamp(a+x+y,0.0,1.0)));\n" +
            "return mix(mix(v00,v10,f.x),mix(v01,v11,f.x),f.y);}\n" +
            "vec2 decGuideLinear(vec2 uv){vec2 p=uv/uGuideTexel-.5;vec2 b=floor(p);vec2 f=fract(p);\n" +
            "vec2 a=(b+.5)*uGuideTexel;vec2 x=vec2(uGuideTexel.x,0.0),y=vec2(0.0,uGuideTexel.y);\n" +
            "vec2 v00=dec(texture2D(uGuideFlow,clamp(a,0.0,1.0))),v10=dec(texture2D(uGuideFlow,clamp(a+x,0.0,1.0)));\n" +
            "vec2 v01=dec(texture2D(uGuideFlow,clamp(a+y,0.0,1.0))),v11=dec(texture2D(uGuideFlow,clamp(a+x+y,0.0,1.0)));\n" +
            "return mix(mix(v00,v10,f.x),mix(v01,v11,f.x),f.y);}\n" +
            "vec2 p16(float v){float r=mod(floor(v*256.0+.5)+65536.0,65536.0);return vec2(floor(r/256.0),mod(r,256.0))/255.0;}\n" +
            "vec4 enc(vec2 v){return vec4(p16(v.x),p16(v.y));}\n" +
            "float med4(float a,float b,float c,float d){float lo=min(min(a,b),min(c,d)),hi=max(max(a,b),max(c,d));return .5*(a+b+c+d-lo-hi);}\n" +
            "float rb(float x){return min(abs(x),.16);}\n" +
            "float cc(vec3 a,vec3 b){vec2 d=abs(chroma(a)-chroma(b));return rb(d.x)+rb(d.y);}\n" +
            "float cost(vec2 f){vec2 q=vTexCoord+f/uSourceSize;if(any(lessThan(q,vec2(0.0)))||any(greaterThan(q,vec2(1.0))))return 50.0;\n" +
            "vec2 dx=vec2(uAnalysisTexel.x,0.0),dy=vec2(0.0,uAnalysisTexel.y);\n" +
            "vec3 tv=texture2D(uTarget,vTexCoord).rgb,rv=texture2D(uReference,q).rgb;\n" +
            "vec3 txpv=texture2D(uTarget,clamp(vTexCoord+dx,0.0,1.0)).rgb,txmv=texture2D(uTarget,clamp(vTexCoord-dx,0.0,1.0)).rgb;\n" +
            "vec3 typv=texture2D(uTarget,clamp(vTexCoord+dy,0.0,1.0)).rgb,tymv=texture2D(uTarget,clamp(vTexCoord-dy,0.0,1.0)).rgb;\n" +
            "vec3 rxpv=texture2D(uReference,clamp(q+dx,0.0,1.0)).rgb,rxmv=texture2D(uReference,clamp(q-dx,0.0,1.0)).rgb;\n" +
            "vec3 rypv=texture2D(uReference,clamp(q+dy,0.0,1.0)).rgb,rymv=texture2D(uReference,clamp(q-dy,0.0,1.0)).rgb;\n" +
            "float t=lum(tv),r=lum(rv),txp=lum(txpv),txm=lum(txmv),typ=lum(typv),tym=lum(tymv);\n" +
            "float rxp=lum(rxpv),rxm=lum(rxmv),ryp=lum(rypv),rym=lum(rymv);\n" +
            "float z=rb(t-r)+.18*cc(tv,rv)+.35*(rb(txp-rxp)+rb(txm-rxm)+rb(typ-ryp)+rb(tym-rym))+.07*(cc(txpv,rxpv)+cc(txmv,rxmv)+cc(typv,rypv)+cc(tymv,rymv))+.55*(rb((txp-txm)-(rxp-rxm))+rb((typ-tym)-(ryp-rym)));\n" +
            // The 32x18 coarse level can afford the full 3x3+census support;
            // r33/r34 proved that extending descriptor work past this level
            // moves otherwise bounded GPU work into blocking swap pressure.
            "if(uUseWidePatch>.5){vec2 d1=dx+dy,d2=dx-dy;\n" +
            "float td1=lum(texture2D(uTarget,clamp(vTexCoord+d1,0.0,1.0)).rgb),td2=lum(texture2D(uTarget,clamp(vTexCoord-d1,0.0,1.0)).rgb);\n" +
            "float td3=lum(texture2D(uTarget,clamp(vTexCoord+d2,0.0,1.0)).rgb),td4=lum(texture2D(uTarget,clamp(vTexCoord-d2,0.0,1.0)).rgb);\n" +
            "float rd1=lum(texture2D(uReference,clamp(q+d1,0.0,1.0)).rgb),rd2=lum(texture2D(uReference,clamp(q-d1,0.0,1.0)).rgb);\n" +
            "float rd3=lum(texture2D(uReference,clamp(q+d2,0.0,1.0)).rgb),rd4=lum(texture2D(uReference,clamp(q-d2,0.0,1.0)).rgb);\n" +
            "float cs=abs(step(t,txp)-step(r,rxp))+abs(step(t,txm)-step(r,rxm))+abs(step(t,typ)-step(r,ryp))+abs(step(t,tym)-step(r,rym));\n" +
            "cs+=abs(step(t,td1)-step(r,rd1))+abs(step(t,td2)-step(r,rd2))+abs(step(t,td3)-step(r,rd3))+abs(step(t,td4)-step(r,rd4));\n" +
            "z+=.22*(rb(td1-rd1)+rb(td2-rd2)+rb(td3-rd3)+rb(td4-rd4))+.025*cs;}return z;}\n" +
            "void main(){vec2 c=mix(vec2(0.0),decLinear(vTexCoord),uHasPrior);if(uBypassSearch>.5&&uUseReciprocalGuide<.5){gl_FragColor=enc(c);return;}vec2 b=c;float bc=cost(c);\n" +
            // Inverting a spatially varying field requires solving
            // q=p-f(q), not merely negating f at p. Three bounded fixed-point
            // steps materially improve the reciprocal proposal on camera
            // parallax while the reversed image cost remains authoritative.
            "if(uUseReciprocalGuide>.5){vec2 first=decGuideLinear(vTexCoord);vec2 q1=clamp(vTexCoord-first/uSourceSize,0.0,1.0);vec2 second=decGuideLinear(q1);\n" +
            "vec2 q2=clamp(vTexCoord-second/uSourceSize,0.0,1.0);vec2 third=decGuideLinear(q2);\n" +
            "vec2 q3=clamp(vTexCoord-third/uSourceSize,0.0,1.0);vec2 g=-decGuideLinear(q3);\n" +
            "g=clamp(g,vec2(-uGuideLimit),vec2(uGuideLimit));float gc=cost(g);if(gc<bc){bc=gc;c=g;b=g;}}\n" +
            // The expansion pass normally just preserves the upsampled local
            // result. For reverse flow it may instead preserve the reciprocal
            // proposal when that proposal independently wins the reverse
            // image cost. The three subsequent 1px searches still own local
            // convergence; this adds no pass and no forced inverse field.
            "if(uBypassSearch>.5){gl_FragColor=enc(c);return;}\n" +
            "for(int y=-1;y<=1;y++){for(int x=-1;x<=1;x++){if(x!=0||y!=0){vec2 f=c+vec2(float(x),float(y))*uUpdateStep;float z=cost(f);if(z<bc){bc=z;b=f;}}}}\n" +
            "vec2 l=decLinear(clamp(vTexCoord-vec2(uAnalysisTexel.x,0.0),0.0,1.0));\n" +
            "vec2 r=decLinear(clamp(vTexCoord+vec2(uAnalysisTexel.x,0.0),0.0,1.0));\n" +
            "vec2 d=decLinear(clamp(vTexCoord-vec2(0.0,uAnalysisTexel.y),0.0,1.0));\n" +
            "vec2 u=decLinear(clamp(vTexCoord+vec2(0.0,uAnalysisTexel.y),0.0,1.0));\n" +
            "float lc=lum(texture2D(uTarget,vTexCoord).rgb);float e=0.0;\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord-vec2(uAnalysisTexel.x,0.0),0.0,1.0)).rgb)));\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord+vec2(uAnalysisTexel.x,0.0),0.0,1.0)).rgb)));\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord-vec2(0.0,uAnalysisTexel.y),0.0,1.0)).rgb)));\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord+vec2(0.0,uAnalysisTexel.y),0.0,1.0)).rgb)));\n" +
            "float edge=clamp(e*.25,0.0,1.0),w=.18*edge;vec2 smooth=(l+r+d+u)*.25;\n" +
            // On the final 128x72 iteration, replace an isolated vector
            // with the robust median of three or more mutually agreeing
            // neighbours. Each direction remains independent and the
            // unchanged cycle/photometric gates stay authoritative.
            "if(uFinalConsensus>.5){vec2 m=vec2(med4(l.x,r.x,d.x,u.x),med4(l.y,r.y,d.y,u.y));\n" +
            "float s=step(distance(l,m),2.5)+step(distance(r,m),2.5)+step(distance(d,m),2.5)+step(distance(u,m),2.5);\n" +
            "float g=step(2.5,s)*edge;smooth=m;w=max(w,.65*g);}b=mix(b,smooth,w);gl_FragColor=enc(b);}\n";

    private static final String DENSE_CYCLE_SHADER =
            "precision highp float; uniform sampler2D uFlow,uReverseFlow,uReference,uTarget;\n" +
            "uniform float uValidityBase;\n" +
            "uniform vec2 uSourceSize,uFlowRange,uAnalysisTexel,uReverseTexel; uniform vec4 uActiveRect; varying vec2 vTexCoord;\n" +
            "float lum(vec3 c){return dot(c,vec3(.299,.587,.114));}\n" +
            "float unp(vec2 p){float r=floor(p.x*255.0+.5)*256.0+floor(p.y*255.0+.5);return r>=32768.0?r-65536.0:r;}\n" +
            "vec2 dec(vec4 f){return vec2(unp(f.rg),unp(f.ba))/256.0;}\n" +
            "float med4(float a,float b,float c,float d){float lo=min(min(a,b),min(c,d)),hi=max(max(a,b),max(c,d));return .5*(a+b+c+d-lo-hi);}\n" +
            "vec2 decReverse(vec2 uv){vec2 p=uv/uReverseTexel-.5;vec2 base=floor(p);vec2 f=fract(p);vec2 a=(base+.5)*uReverseTexel;vec2 x=vec2(uReverseTexel.x,0.0),y=vec2(0.0,uReverseTexel.y);vec2 v00=dec(texture2D(uReverseFlow,clamp(a,0.0,1.0))),v10=dec(texture2D(uReverseFlow,clamp(a+x,0.0,1.0))),v01=dec(texture2D(uReverseFlow,clamp(a+y,0.0,1.0))),v11=dec(texture2D(uReverseFlow,clamp(a+x+y,0.0,1.0)));return mix(mix(v00,v10,f.x),mix(v01,v11,f.x),f.y);}\n" +
            "void main(){vec2 f=dec(texture2D(uFlow,vTexCoord));vec2 q=vTexCoord+f/uSourceSize;\n" +
            "float inb=step(uActiveRect.x,q.x)*step(q.x,uActiveRect.z)*step(uActiveRect.y,q.y)*step(q.y,uActiveRect.w);\n" +
            "vec2 b=decReverse(clamp(q,0.0,1.0));float ce=length(f+b);\n" +
            // The reciprocal-agreement tolerance reflects SOLVER resolution:
            // its base was calibrated for the 4.5px coarsest step. The
            // <=30-FPS tier doubles that step for 83px reach, so two correct
            // independent solves may disagree by the coarser quantization;
            // uValidityBase carries the calibrated base per mode (2.0 or
            // 4.0). The 0.75 inner edge, 4% magnitude slope, and every
            // downstream validity/photometric gate are unchanged.
            "float cg=1.0-smoothstep(.75,uValidityBase+.04*length(f),ce);\n" +
            "float pe=abs(lum(texture2D(uTarget,vTexCoord).rgb)-lum(texture2D(uReference,clamp(q,0.0,1.0)).rgb));\n" +
            // Flat pillar/letterbox regions have no identifiable motion and
            // must not inherit a neighbor vector. Static textured HUD remains
            // valid at exactly zero displacement, so it is not warped.
            "vec2 dx=vec2(uAnalysisTexel.x,0.0),dy=vec2(0.0,uAnalysisTexel.y);\n" +
            "float tc=lum(texture2D(uTarget,vTexCoord).rgb);\n" +
            "float textureEnergy=max(max(abs(tc-lum(texture2D(uTarget,clamp(vTexCoord+dx,0.0,1.0)).rgb)),abs(tc-lum(texture2D(uTarget,clamp(vTexCoord-dx,0.0,1.0)).rgb))),max(abs(tc-lum(texture2D(uTarget,clamp(vTexCoord+dy,0.0,1.0)).rgb)),abs(tc-lum(texture2D(uTarget,clamp(vTexCoord-dy,0.0,1.0)).rgb))));\n" +
            // r53 proved independent cycle agreement above 56% while final
            // confidence remained near 44% because flat interiors failed the
            // same-cell texture test. Admit such a cell only when three of
            // four raw-flow neighbours mutually agree, the center agrees with
            // their robust median, the guide is locally edge-free, and the
            // unchanged reverse-cycle and photometric gates also pass below.
            // This cannot spread a vector across a visible edge or rescue an
            // independently inconsistent/photometrically wrong match.
            "vec2 fl=dec(texture2D(uFlow,clamp(vTexCoord-dx,0.0,1.0))),fr=dec(texture2D(uFlow,clamp(vTexCoord+dx,0.0,1.0)));\n" +
            "vec2 fd=dec(texture2D(uFlow,clamp(vTexCoord-dy,0.0,1.0))),fu=dec(texture2D(uFlow,clamp(vTexCoord+dy,0.0,1.0)));\n" +
            "vec2 fm=vec2(med4(fl.x,fr.x,fd.x,fu.x),med4(fl.y,fr.y,fd.y,fu.y));\n" +
            "float ns=step(distance(fl,fm),2.0)+step(distance(fr,fm),2.0)+step(distance(fd,fm),2.0)+step(distance(fu,fm),2.0);\n" +
            "float coherentFlat=step(2.5,ns)*step(distance(f,fm),1.5)*(1.0-smoothstep(.018,.045,textureEnergy));\n" +
            "float activeGate=step(uActiveRect.x+uAnalysisTexel.x,vTexCoord.x)*step(vTexCoord.x,uActiveRect.z-uAnalysisTexel.x)*step(uActiveRect.y+uAnalysisTexel.y,vTexCoord.y)*step(vTexCoord.y,uActiveRect.w-uAnalysisTexel.y);\n" +
            "float photoGate=1.0-smoothstep(.10,.22,pe),textureGate=max(smoothstep(.008,.030,textureEnergy),coherentFlat);\n" +
            "float conf=activeGate*inb*cg*photoGate*textureGate;\n" +
            // Alpha is not consumed by synthesis. Schema35 transports it in
            // a separate nearest-sampled tile without changing linear RG flow
            // or B confidence: active, in-bounds, cycle, photometric,
            // textured, saturated, and OOB.
            "vec2 sourceLimit=max(uFlowRange*uSourceSize,vec2(.00001));\n" +
            "float saturated=step(.995,max(abs(f.x)/sourceLimit.x,abs(f.y)/sourceLimit.y));\n" +
            // RGBA8 conversion can round confidence in [47.5,48)/255 to B=48.
            // Encode factor bits at the conservative preceding UNORM code so
            // every returned B>=48 cell is a subset of each prerequisite bit;
            // the bits are necessary coverage, not duplicate validity flags.
            "float prerequisiteThreshold=47.0/255.0;float mask=activeGate+2.0*inb+4.0*step(prerequisiteThreshold,cg)+8.0*step(prerequisiteThreshold,photoGate)+16.0*step(prerequisiteThreshold,textureGate)+32.0*saturated+64.0*(1.0-inb);\n" +
            "vec2 outv=clamp((f/uSourceSize)/max(uFlowRange,vec2(.00001))*127.0/255.0+128.0/255.0,0.0,1.0);\n" +
            "gl_FragColor=vec4(outv,conf,mask/255.0);}\n";

    private static final String DENSE_Q8_PROBE_SHADER =
            "precision highp float; varying vec2 vTexCoord;\n" +
            "vec2 p16(float v){float r=mod(floor(v*256.0+.5)+65536.0,65536.0);return vec2(floor(r/256.0),mod(r,256.0))/255.0;}\n" +
            "float unp(vec2 p){float r=floor(p.x*255.0+.5)*256.0+floor(p.y*255.0+.5);return r>=32768.0?r-65536.0:r;}\n" +
            "void main(){float x=floor(gl_FragCoord.x);float v=x<1.0?-47.0:(x<2.0?-1.0:(x<3.0?0.0:(x<4.0?1.0:47.0)));vec2 p=p16(v);float ok=step(abs(unp(p)/256.0-v),.00001);gl_FragColor=vec4(p,ok,1.0);}\n";

    private static final String COARSE_MOTION_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uPrevious;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform vec2 uTexel;\n" +
            "uniform vec2 uSearchStep;\n" +
            "uniform vec2 uFlowRange;\n" +
            "varying vec2 vTexCoord;\n" +
            "float pixelCost(vec3 a,vec3 b){return dot(abs(a-b),vec3(0.299,0.587,0.114));}\n" +
            "float costAt(vec2 motion){\n" +
            " vec2 p=clamp(vTexCoord+motion,vec2(0.0),vec2(1.0));\n" +
            // Sample a real 13x13 source patch. The former five-pixel cross
            // covered only +/-2 pixels inside each 16-pixel flow cell, so a
            // single highlight or glyph edge could send the whole cell to an
            // unrelated wall/floor feature and visibly fragment the image.
            " vec2 dx=vec2(uTexel.x*6.0,0.0);\n" +
            " vec2 dy=vec2(0.0,uTexel.y*6.0);\n" +
            " vec3 cc=texture2D(uCurrent,vTexCoord).rgb;\n" +
            " float e=1.4*pixelCost(cc,texture2D(uPrevious,p).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dx,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dx,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dx,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dx,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dx+dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dx+dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dx-dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dx-dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dx+dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dx+dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dx-dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dx-dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            // Prefer zero motion when two patches are visually equivalent and
            // reject candidates that manufacture matches by clamping outside
            // the source. Real displacement wins only by improving the patch.
            " vec2 normalized=motion/max(uFlowRange,vec2(0.00001));\n" +
            " e+=0.035*dot(normalized,normalized);\n" +
            " e+=4.0*length((vTexCoord+motion)-p);\n" +
            " return e;\n" +
            "}\n" +
            "void main(){\n" +
            " vec2 best=vec2(0.0); float base=costAt(best); float score=base; float second=1000.0;\n" +
            " for(int y=-3;y<=3;y++){for(int x=-3;x<=3;x++){\n" +
            "  if(x==0&&y==0){continue;}\n" +
            "  vec2 candidate=vec2(float(x),float(y))*uSearchStep;\n" +
            "  float e=costAt(candidate); if(e<score){second=score;score=e;best=candidate;}else if(e<second){second=e;}\n" +
            " }}\n" +
            " float gain=clamp((base-score)/(base+0.025),0.0,1.0);\n" +
            " float unique=clamp(8.0*(second-score)/(second+0.025),0.0,1.0);\n" +
            " float confidence=sqrt(gain*unique);\n" +
            " gl_FragColor=vec4(clamp(best/uFlowRange*0.5+0.5,0.0,1.0),confidence,1.0);\n" +
            "}\n";

    private static final String REFINE_MOTION_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uPrevious;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform sampler2D uCoarseFlow;\n" +
            "uniform vec2 uTexel;\n" +
            "uniform vec2 uRefineStep;\n" +
            "uniform vec2 uPixelStep;\n" +
            "uniform vec2 uFlowRange;\n" +
            "varying vec2 vTexCoord;\n" +
            "float pixelCost(vec3 a,vec3 b){return dot(abs(a-b),vec3(0.299,0.587,0.114));}\n" +
            "float costAt(vec2 motion){\n" +
            " vec2 p=clamp(vTexCoord+motion,vec2(0.0),vec2(1.0));\n" +
            " vec2 dx=vec2(uTexel.x*6.0,0.0);\n" +
            " vec2 dy=vec2(0.0,uTexel.y*6.0);\n" +
            " vec3 cc=texture2D(uCurrent,vTexCoord).rgb;\n" +
            " float e=1.4*pixelCost(cc,texture2D(uPrevious,p).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dx,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dx,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dx,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dx,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.55*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dx+dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dx+dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord+dx-dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p+dx-dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dx+dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dx+dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " e+=0.4*pixelCost(texture2D(uCurrent,clamp(vTexCoord-dx-dy,vec2(0.0),vec2(1.0))).rgb,texture2D(uPrevious,clamp(p-dx-dy,vec2(0.0),vec2(1.0))).rgb);\n" +
            " vec2 normalized=motion/max(uFlowRange,vec2(0.00001));\n" +
            " e+=0.035*dot(normalized,normalized);\n" +
            " e+=4.0*length((vTexCoord+motion)-p);\n" +
            " return e;\n" +
            "}\n" +
            "void main(){\n" +
            " vec4 coarse=texture2D(uCoarseFlow,vTexCoord);\n" +
            " vec2 center=(coarse.rg*2.0-1.0)*uFlowRange;\n" +
            " vec2 best=center; float base=costAt(vec2(0.0)); float score=costAt(center);\n" +
            " for(int y=-2;y<=2;y++){for(int x=-2;x<=2;x++){\n" +
            "  vec2 candidate=clamp(center+vec2(float(x),float(y))*uRefineStep,-uFlowRange,uFlowRange);\n" +
            "  float e=costAt(candidate); if(e<score){score=e;best=candidate;}\n" +
            " }}\n" +
            " center=best; score=costAt(center);\n" +
            // The bounded wide refinement closes the seven-point coarse-grid
            // gaps. Searching +/-2 at one-pixel increments around its winner
            // avoids the old sub-grid holes while keeping the robust patch
            // matcher inside its compositor budget.
            " for(int y=-2;y<=2;y++){for(int x=-2;x<=2;x++){\n" +
            "  if(x==0&&y==0){continue;}\n" +
            "  vec2 candidate=clamp(center+vec2(float(x),float(y))*uPixelStep,-uFlowRange,uFlowRange);\n" +
            "  float e=costAt(candidate); if(e<score){score=e;best=candidate;}\n" +
            " }}\n" +
            " float gain=clamp((base-score)/(base+0.02),0.0,1.0);\n" +
            // Adjacent one-pixel candidates intentionally have nearly equal
            // cost around a smooth subpixel minimum. Treating that as distant
            // ambiguity disabled almost all valid v8 motion. The coarse pass
            // still requires a separated second-best over widely spaced
            // candidates; fine confidence measures improvement and inherits
            // that coarse trust, then the spatial/cycle stages below reject
            // incoherent local choices.
            " float confidence=sqrt(gain)*(0.55+0.45*coarse.b);\n" +
            " gl_FragColor=vec4(clamp(best/uFlowRange*0.5+0.5,0.0,1.0),confidence,1.0);\n" +
            "}\n";

    private static final String REGULARIZE_MOTION_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uFlow;\n" +
            "uniform vec2 uFlowTexel;\n" +
            "varying vec2 vTexCoord;\n" +
            "vec2 vectorOf(vec4 field){return field.rg*2.0-1.0;}\n" +
            "float trustedWeight(vec4 field){return field.b*step(0.10,field.b);}\n" +
            "void main(){\n" +
            " vec4 c=texture2D(uFlow,vTexCoord);\n" +
            " vec4 l=texture2D(uFlow,clamp(vTexCoord-vec2(uFlowTexel.x,0.0),vec2(0.0),vec2(1.0)));\n" +
            " vec4 r=texture2D(uFlow,clamp(vTexCoord+vec2(uFlowTexel.x,0.0),vec2(0.0),vec2(1.0)));\n" +
            " vec4 u=texture2D(uFlow,clamp(vTexCoord+vec2(0.0,uFlowTexel.y),vec2(0.0),vec2(1.0)));\n" +
            " vec4 d=texture2D(uFlow,clamp(vTexCoord-vec2(0.0,uFlowTexel.y),vec2(0.0),vec2(1.0)));\n" +
            " vec4 l2=texture2D(uFlow,clamp(vTexCoord-vec2(uFlowTexel.x*2.0,0.0),vec2(0.0),vec2(1.0)));\n" +
            " vec4 r2=texture2D(uFlow,clamp(vTexCoord+vec2(uFlowTexel.x*2.0,0.0),vec2(0.0),vec2(1.0)));\n" +
            " vec4 u2=texture2D(uFlow,clamp(vTexCoord+vec2(0.0,uFlowTexel.y*2.0),vec2(0.0),vec2(1.0)));\n" +
            " vec4 d2=texture2D(uFlow,clamp(vTexCoord-vec2(0.0,uFlowTexel.y*2.0),vec2(0.0),vec2(1.0)));\n" +
            " vec2 cv=vectorOf(c);\n" +
            " float seedCount=step(0.10,l.b)+step(0.10,r.b)+step(0.10,u.b)+step(0.10,d.b)+step(0.10,l2.b)+step(0.10,r2.b)+step(0.10,u2.b)+step(0.10,d2.b);\n" +
            " float seedWeight=trustedWeight(l)+trustedWeight(r)+trustedWeight(u)+trustedWeight(d)+trustedWeight(l2)+trustedWeight(r2)+trustedWeight(u2)+trustedWeight(d2);\n" +
            " vec2 mean=(vectorOf(l)*trustedWeight(l)+vectorOf(r)*trustedWeight(r)+vectorOf(u)*trustedWeight(u)+vectorOf(d)*trustedWeight(d)+vectorOf(l2)*trustedWeight(l2)+vectorOf(r2)*trustedWeight(r2)+vectorOf(u2)*trustedWeight(u2)+vectorOf(d2)*trustedWeight(d2))/max(seedWeight,0.00001);\n" +
            " float deviation=distance(cv,mean)*step(0.10,c.b);\n" +
            " deviation=max(deviation,distance(mean,vectorOf(l))*step(0.10,l.b));\n" +
            " deviation=max(deviation,distance(mean,vectorOf(r))*step(0.10,r.b));\n" +
            " deviation=max(deviation,distance(mean,vectorOf(u))*step(0.10,u.b));\n" +
            " deviation=max(deviation,distance(mean,vectorOf(d))*step(0.10,d.b));\n" +
            " deviation=max(deviation,distance(mean,vectorOf(l2))*step(0.10,l2.b));\n" +
            " deviation=max(deviation,distance(mean,vectorOf(r2))*step(0.10,r2.b));\n" +
            " deviation=max(deviation,distance(mean,vectorOf(u2))*step(0.10,u2.b));\n" +
            " deviation=max(deviation,distance(mean,vectorOf(d2))*step(0.10,d2.b));\n" +
            // A vector that disagrees with every adjacent block is exactly the
            // cell-shaped fragmentation seen in the rejected GameCube frame.
            // Preserve its encoded direction for diagnostics, but drive its
            // confidence to zero so presentation falls back instead of warp.
            " float coherence=clamp(1.0-2.5*deviation,0.0,1.0);\n" +
            // At least three independently matched cells must agree before
            // their motion may enter a textureless center. One stray seed or
            // two edge samples cannot dilate a false vector across the scene.
            " float seedGate=smoothstep(2.0,3.0,seedCount);\n" +
            " float neighborConfidence=(seedWeight/max(seedCount,1.0))*seedGate;\n" +
            " float support=clamp(seedWeight*0.25,0.0,1.0)*seedGate;\n" +
            " float centerTrust=smoothstep(0.08,0.25,c.b);\n" +
            " vec2 filtered=mix(mean,mix(cv,mean,0.35),centerTrust);\n" +
            // Coherent neighbors are independent evidence for a shallow slow-
            // motion minimum. Use a square-root confidence lift after the hard
            // disagreement gate instead of multiplying two small confidences
            // and erasing the field. Fragmented cells still get exactly zero.
            " float sourceConfidence=max(c.b,neighborConfidence*0.90);\n" +
            " float confidence=sqrt(sourceConfidence)*coherence*clamp(1.35*sqrt(support),0.0,1.0);\n" +
            " gl_FragColor=vec4(clamp(filtered*0.5+0.5,0.0,1.0),confidence,1.0);\n" +
            "}\n";

    // v17 aligned candidate scoring and validation, proving that aggregate
    // cost improvement was still driven by too few coherent sites. v18 made
    // coherent 10/16 support part of candidate selection itself and increased
    // spatial granularity without weakening any final acceptance gate. v19
    // proved range was not the bottleneck; v20 restores v18's range and adds
    // bounded affine-gradient neighbor consistency for perspective motion.
    private static final String REGIONAL_COARSE_CANDIDATE_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uPrevious;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform vec2 uFlowRange;\n" +
            "uniform vec2 uCoarseStep;\n" +
            "varying vec2 vTexCoord;\n" +
            "float pixelCost(vec3 a,vec3 b){return dot(abs(a-b),vec3(0.299,0.587,0.114));}\n" +
            "vec2 sampleUv(vec2 region,float x,float y){\n" +
            " vec2 center=(region+0.5)/vec2(12.0,8.0);\n" +
            " vec2 local=(vec2(x,y)+0.5)/4.0-0.5;\n" +
            " return clamp(center+local*vec2(1.5/12.0,1.5/8.0),vec2(0.0),vec2(1.0));\n" +
            "}\n" +
            "void main(){\n" +
            " vec2 cell=floor(gl_FragCoord.xy-0.5);\n" +
            " vec2 region=floor(cell/vec2(5.0,5.0));\n" +
            " vec2 candidateCell=cell-region*vec2(5.0,5.0);\n" +
            " vec2 motion=(candidateCell-vec2(2.0))*uCoarseStep;\n" +
            " vec2 candidate=motion/max(uFlowRange,vec2(0.00001));\n" +
            " float cost=0.0; float support=0.0;\n" +
            " for(int y=0;y<4;y++){for(int x=0;x<4;x++){\n" +
            "  vec2 uv=sampleUv(region,float(x),float(y));\n" +
            "  vec2 peer=clamp(uv+motion,vec2(0.0),vec2(1.0));\n" +
            "  vec3 current=texture2D(uCurrent,uv).rgb;\n" +
            "  float error=pixelCost(current,texture2D(uPrevious,peer).rgb);\n" +
            "  error+=3.0*length((uv+motion)-peer); cost+=min(error,0.30);\n" +
            "  float base=pixelCost(current,texture2D(uPrevious,uv).rgb);\n" +
            "  support+=step(0.008,base-error)*step(error,0.18);\n" +
            " }}\n" +
            " gl_FragColor=vec4(clamp(candidate*0.5+0.5,0.0,1.0),clamp((cost/16.0)/0.30,0.0,1.0),clamp(support/16.0,0.0,1.0));\n" +
            "}\n";

    // Fine candidates are centered on the independently selected coarse
    // winner at one quarter of its source-pixel spacing. This retains bounded
    // residual precision without consulting the local matcher.
    private static final String REGIONAL_FINE_CANDIDATE_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uPrevious;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform sampler2D uCoarseWinner;\n" +
            "uniform vec2 uFlowRange;\n" +
            "uniform vec2 uFineStep;\n" +
            "varying vec2 vTexCoord;\n" +
            "float pixelCost(vec3 a,vec3 b){return dot(abs(a-b),vec3(0.299,0.587,0.114));}\n" +
            "vec2 sampleUv(vec2 region,float x,float y){\n" +
            " vec2 center=(region+0.5)/vec2(12.0,8.0);\n" +
            " vec2 local=(vec2(x,y)+0.5)/4.0-0.5;\n" +
            " return clamp(center+local*vec2(1.5/12.0,1.5/8.0),vec2(0.0),vec2(1.0));\n" +
            "}\n" +
            "void main(){\n" +
            " vec2 cell=floor(gl_FragCoord.xy-0.5);\n" +
            " vec2 region=floor(cell/vec2(5.0,5.0));\n" +
            " vec2 candidateCell=cell-region*vec2(5.0,5.0);\n" +
            " vec2 center=(texture2D(uCoarseWinner,(region+0.5)/vec2(12.0,8.0)).rg*2.0-1.0)*uFlowRange;\n" +
            " vec2 motion=clamp(center+(candidateCell-vec2(2.0))*uFineStep,-uFlowRange,uFlowRange);\n" +
            " vec2 candidate=motion/max(uFlowRange,vec2(0.00001));\n" +
            " float cost=0.0; float support=0.0;\n" +
            " for(int y=0;y<4;y++){for(int x=0;x<4;x++){\n" +
            "  vec2 uv=sampleUv(region,float(x),float(y));\n" +
            "  vec2 peer=clamp(uv+motion,vec2(0.0),vec2(1.0));\n" +
            "  vec3 current=texture2D(uCurrent,uv).rgb;\n" +
            "  float error=pixelCost(current,texture2D(uPrevious,peer).rgb);\n" +
            "  error+=3.0*length((uv+motion)-peer); cost+=min(error,0.30);\n" +
            "  float base=pixelCost(current,texture2D(uPrevious,uv).rgb);\n" +
            "  support+=step(0.008,base-error)*step(error,0.18);\n" +
            " }}\n" +
            " gl_FragColor=vec4(clamp(candidate*0.5+0.5,0.0,1.0),clamp((cost/16.0)/0.30,0.0,1.0),clamp(support/16.0,0.0,1.0));\n" +
            "}\n";

    // Converts the 60x40 candidate atlas into one ungated best hypothesis per
    // 12x8 region. RG is vector, B is cost and A is coherent-site support.
    private static final String REGIONAL_CANDIDATE_WINNER_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uCandidates;\n" +
            "varying vec2 vTexCoord;\n" +
            "vec4 candidateAt(vec2 region,float x,float y){\n" +
            " vec2 cell=region*vec2(5.0,5.0)+vec2(x,y);\n" +
            " return texture2D(uCandidates,(cell+0.5)/vec2(60.0,40.0));\n" +
            "}\n" +
            "void main(){\n" +
            " vec2 region=floor(gl_FragCoord.xy-0.5);\n" +
            " vec4 best=candidateAt(region,0.0,0.0); float bestCoherent=step(9.5/16.0,best.a);\n" +
            " for(int y=0;y<5;y++){for(int x=0;x<5;x++){\n" +
            "  vec4 candidate=candidateAt(region,float(x),float(y));\n" +
            "  float coherent=step(9.5/16.0,candidate.a);\n" +
            "  if(coherent>bestCoherent||(coherent==bestCoherent&&candidate.b<best.b)){best=candidate;bestCoherent=coherent;}\n" +
            " }} gl_FragColor=best;\n" +
            "}\n";

    /**
     * Selects one conservative source-backed vector for each overlapping
     * regional control. Every winner must improve roughly two thirds of its
     * 4x4 window, cover all four sub-quadrants, beat zero motion, and agree
     * with at least two adjacent regions. The presentation shader additionally
     * requires an independently measured reverse vector at the displaced
     * coordinate. Thus perspective camera motion may vary smoothly across the
     * image while isolated objects, split motion, and bad seams fail closed.
     */
    private static final String GLOBAL_MOTION_REDUCTION_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uWinners;\n" +
            "uniform sampler2D uPrevious;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform vec2 uFlowRange;\n" +
            "varying vec2 vTexCoord;\n" +
            "vec2 vectorOf(vec4 field){return field.rg*2.0-1.0;}\n" +
            "float pixelCost(vec3 a,vec3 b){return dot(abs(a-b),vec3(0.299,0.587,0.114));}\n" +
            "vec2 sampleUv(vec2 region,float x,float y){\n" +
            " vec2 center=(region+0.5)/vec2(12.0,8.0);\n" +
            " vec2 local=(vec2(x,y)+0.5)/4.0-0.5;\n" +
            " return clamp(center+local*vec2(1.5/12.0,1.5/8.0),vec2(0.0),vec2(1.0));\n" +
            "}\n" +
            "vec4 bestAt(vec2 region){\n" +
            " return texture2D(uWinners,(region+0.5)/vec2(12.0,8.0));\n" +
            "}\n" +
            "void main(){\n" +
            " vec2 region=floor(gl_FragCoord.xy-0.5);\n" +
            " vec4 selected=bestAt(region); vec2 best=vectorOf(selected);\n" +
            " float bestCost=0.0; float zeroMotionCost=0.0;\n" +
            " vec2 motion=best*uFlowRange; float support=0.0; vec4 quadrantSupport=vec4(0.0);\n" +
            " for(int y=0;y<4;y++){for(int x=0;x<4;x++){\n" +
            "  vec2 uv=sampleUv(region,float(x),float(y));\n" +
            "  float base=pixelCost(texture2D(uCurrent,uv).rgb,texture2D(uPrevious,uv).rgb);\n" +
            "  vec2 peer=clamp(uv+motion,vec2(0.0),vec2(1.0));\n" +
            "  float moved=pixelCost(texture2D(uCurrent,uv).rgb,texture2D(uPrevious,peer).rgb);\n" +
            "  bestCost+=min(moved,0.30); zeroMotionCost+=min(base,0.30);\n" +
            "  float improves=step(0.008,base-moved)*step(moved,0.18); support+=improves;\n" +
            "  if(x<2&&y<2)quadrantSupport.x+=improves; else if(x>=2&&y<2)quadrantSupport.y+=improves;\n" +
            "  else if(x<2)quadrantSupport.z+=improves; else quadrantSupport.w+=improves;\n" +
            " }}\n" +
            " bestCost/=16.0; zeroMotionCost/=16.0;\n" +
            " float quadrants=step(2.0,quadrantSupport.x)+step(2.0,quadrantSupport.y)+step(2.0,quadrantSupport.z)+step(2.0,quadrantSupport.w);\n" +
            " float neighbors=0.0; float available=0.0;\n" +
            " vec4 left=vec4(0.5,0.5,1.0,0.0),right=left,down=left,up=left;\n" +
            " float leftOk=0.0,rightOk=0.0,downOk=0.0,upOk=0.0;\n" +
            " if(region.x>0.0){left=bestAt(region-vec2(1.0,0.0));leftOk=step(9.5/16.0,left.a);neighbors+=leftOk*step(distance(best,vectorOf(left)),0.18);available+=1.0;}\n" +
            " if(region.x<11.0){right=bestAt(region+vec2(1.0,0.0));rightOk=step(9.5/16.0,right.a);neighbors+=rightOk*step(distance(best,vectorOf(right)),0.18);available+=1.0;}\n" +
            " if(region.y>0.0){down=bestAt(region-vec2(0.0,1.0));downOk=step(9.5/16.0,down.a);neighbors+=downOk*step(distance(best,vectorOf(down)),0.18);available+=1.0;}\n" +
            " if(region.y<7.0){up=bestAt(region+vec2(0.0,1.0));upOk=step(9.5/16.0,up.a);neighbors+=upOk*step(distance(best,vectorOf(up)),0.18);available+=1.0;}\n" +
            " float horizontalGradient=leftOk*rightOk*step(distance(best,(vectorOf(left)+vectorOf(right))*0.5),0.18)*step(distance(vectorOf(left),vectorOf(right)),0.45);\n" +
            " float verticalGradient=downOk*upOk*step(distance(best,(vectorOf(down)+vectorOf(up))*0.5),0.18)*step(distance(vectorOf(down),vectorOf(up)),0.45);\n" +
            " float gain=clamp((zeroMotionCost-bestCost)/(zeroMotionCost+0.02),0.0,1.0);\n" +
            // The same roughly-two-thirds rule is applied within every
            // overlapping region. An exact 50/50 split remains zero.
            " float supportGate=smoothstep(9.0,11.0,support);\n" +
            " float coverageGate=smoothstep(3.5,4.0,quadrants);\n" +
            " float constantNeighborGate=step(min(2.0,available)-0.5,neighbors);\n" +
            " float gradientNeighborGate=step(0.5,horizontalGradient+verticalGradient);\n" +
            " float neighborGate=max(constantNeighborGate,gradientNeighborGate);\n" +
            " float fitGate=1.0-smoothstep(0.10,0.20,bestCost);\n" +
            " float motionGate=smoothstep(0.006,0.018,length(best));\n" +
            " float confidence=sqrt(gain)*supportGate*coverageGate*neighborGate*fitGate*motionGate;\n" +
            " gl_FragColor=vec4(clamp(best*0.5+0.5,0.0,1.0),clamp(confidence,0.0,1.0),clamp(support/16.0,0.0,1.0));\n" +
            "}\n";

    private static final String MOTION_INTERPOLATE_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uPrevious;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform sampler2D uBackwardMotion;\n" +
            "uniform sampler2D uForwardMotion;\n" +
            "uniform sampler2D uGlobalBackwardMotion;\n" +
            "uniform sampler2D uGlobalForwardMotion;\n" +
            "uniform vec2 uFlowRange;\n" +
            "uniform float uPhase;\n" +
            "uniform float uDenseEncoding;\n" +
            "varying vec2 vTexCoord;\n" +
            "vec2 decodeFlow(vec4 field){vec2 legacy=field.rg*2.0-1.0;vec2 dense=(field.rg*255.0-128.0)/127.0;return mix(legacy,dense,uDenseEncoding)*uFlowRange;}\n" +
            "void main(){\n" +
            // Backward maps current -> previous; forward maps previous ->
            // current. A single backward field cannot identify disocclusion
            // and caused the former shader to blend unrelated objects into a
            // blurred double image. Check each vector by following it through
            // the opposite field before trusting its spatial displacement.
            " vec4 backwardField=texture2D(uBackwardMotion,vTexCoord);\n" +
            " vec4 forwardField=texture2D(uForwardMotion,vTexCoord);\n" +
            " vec2 backward=decodeFlow(backwardField);\n" +
            " vec2 forward=decodeFlow(forwardField);\n" +
            " vec2 backwardAtForward=decodeFlow(texture2D(uBackwardMotion," +
                    "clamp(vTexCoord+forward,vec2(0.0),vec2(1.0))));\n" +
            " vec2 forwardAtBackward=decodeFlow(texture2D(uForwardMotion," +
                    "clamp(vTexCoord+backward,vec2(0.0),vec2(1.0))));\n" +
            " vec2 safeRange=max(uFlowRange,vec2(0.00001));\n" +
            " float previousCycle=length((forward+backwardAtForward)/safeRange);\n" +
            " float currentCycle=length((backward+forwardAtBackward)/safeRange);\n" +
            " float previousReliability=sqrt(clamp(forwardField.b,0.0,1.0)*" +
                    "clamp(texture2D(uBackwardMotion,clamp(vTexCoord+forward," +
                    "vec2(0.0),vec2(1.0))).b,0.0,1.0))*" +
                    "clamp(1.0-4.0*previousCycle,0.0,1.0);\n" +
            " float currentReliability=sqrt(clamp(backwardField.b,0.0,1.0)*" +
                    "clamp(texture2D(uForwardMotion,clamp(vTexCoord+backward," +
                    "vec2(0.0),vec2(1.0))).b,0.0,1.0))*" +
                    "clamp(1.0-4.0*currentCycle,0.0,1.0);\n" +
            // Use regional camera flow only where local source-backed flow is
            // weak. Each direction follows its displacement into the other
            // independently measured field; disagreement has zero influence.
            " vec4 globalBackwardField=texture2D(uGlobalBackwardMotion,vTexCoord);\n" +
            " vec4 globalForwardField=texture2D(uGlobalForwardMotion,vTexCoord);\n" +
            " vec2 globalBackward=decodeFlow(globalBackwardField);\n" +
            " vec2 globalForward=decodeFlow(globalForwardField);\n" +
            " vec4 globalBackwardPeer=texture2D(uGlobalBackwardMotion,clamp(vTexCoord+globalForward,vec2(0.0),vec2(1.0)));\n" +
            " vec4 globalForwardPeer=texture2D(uGlobalForwardMotion,clamp(vTexCoord+globalBackward,vec2(0.0),vec2(1.0)));\n" +
            " float previousGlobalCycle=length((globalForward+decodeFlow(globalBackwardPeer))/safeRange);\n" +
            " float currentGlobalCycle=length((globalBackward+decodeFlow(globalForwardPeer))/safeRange);\n" +
            " float previousGlobalReliability=sqrt(clamp(globalForwardField.b,0.0,1.0)*clamp(globalBackwardPeer.b,0.0,1.0))*clamp(1.0-5.0*previousGlobalCycle,0.0,1.0);\n" +
            " float currentGlobalReliability=sqrt(clamp(globalBackwardField.b,0.0,1.0)*clamp(globalForwardPeer.b,0.0,1.0))*clamp(1.0-5.0*currentGlobalCycle,0.0,1.0);\n" +
            " float previousGlobalUse=smoothstep(0.10,0.24,previousGlobalReliability)*(1.0-smoothstep(0.04,0.18,previousReliability));\n" +
            " float currentGlobalUse=smoothstep(0.10,0.24,currentGlobalReliability)*(1.0-smoothstep(0.04,0.18,currentReliability));\n" +
            " forward=mix(forward,globalForward,previousGlobalUse);\n" +
            " backward=mix(backward,globalBackward,currentGlobalUse);\n" +
            " previousReliability=max(previousReliability,previousGlobalReliability*previousGlobalUse);\n" +
            " currentReliability=max(currentReliability,currentGlobalReliability*currentGlobalUse);\n" +
            // The vector itself is no longer shortened merely because the
            // photometric match is imperfect (motion blur makes that common).
            // Cycle consistency gates the full measured displacement instead.
            // Confidence decides whether a correspondence is usable; it must
            // not shorten a source-pixel displacement after that decision.
            // Partial vectors systematically under-warped moderate-confidence
            // motion and then failed the independent full-resolution check.
            " float previousGate=step(0.02,previousReliability);\n" +
            " float currentGate=step(0.02,currentReliability);\n" +
            " vec2 previousUv=clamp(vTexCoord-forward*uPhase*previousGate," +
                    "vec2(0.0),vec2(1.0));\n" +
            " vec2 currentUv=clamp(vTexCoord-backward*(1.0-uPhase)*currentGate," +
                    "vec2(0.0),vec2(1.0));\n" +
            " vec4 a=texture2D(uPrevious,previousUv);\n" +
            " vec4 b=texture2D(uCurrent,currentUv);\n" +
            " vec3 rawPrevious=texture2D(uPrevious,vTexCoord).rgb;\n" +
            " vec3 rawCurrent=texture2D(uCurrent,vTexCoord).rgb;\n" +
            // In mutually visible regions both reliabilities are similar and
            // this is the ordinary temporal blend of aligned samples. At a
            // disocclusion, prefer the endpoint that owns the visible pixel
            // instead of making a transparent foreground/background smear.
            " float previousWeight=(1.0-uPhase)*(0.02+previousReliability);\n" +
            " float currentWeight=uPhase*(0.02+currentReliability);\n" +
            " float blend=currentWeight/(previousWeight+currentWeight);\n" +
            // A weighted blend is still a double exposure if the two warped
            // samples disagree.  That used to fade the prediction back to an
            // unwarped endpoint, which mixed two coordinate systems and made
            // camera pans visibly transparent.  In an occlusion, select the
            // supported warped owner instead.  Only fall back to an exact
            // endpoint when neither independently validated direction exists.
            " float alignmentError=max(max(abs(a.r-b.r),abs(a.g-b.g)),abs(a.b-b.b));\n" +
            " float appearanceAdmission=1.0-smoothstep(24.0/255.0,96.0/255.0,alignmentError);\n" +
            " float nearestEndpoint=step(0.5,uPhase);\n" +
            " vec3 exactEndpoint=mix(rawPrevious,rawCurrent,nearestEndpoint);\n" +
            " vec3 alignedPrediction=mix(a.rgb,b.rgb,blend);\n" +
            " float previousSupported=step(0.02,previousReliability);\n" +
            " float currentSupported=step(0.02,currentReliability);\n" +
            " float bothSupported=previousSupported*currentSupported;\n" +
            " float anySupported=max(previousSupported,currentSupported);\n" +
            // Per-pixel confidence ownership split rigid objects down the
            // middle when both directions were plausible but slightly
            // asymmetric.  Temporal ownership is coherent across the frame;
            // support still chooses the sole available direction.
            " float ownerByPhase=step(0.5,uPhase);\n" +
            " float chooseCurrent=max((1.0-previousSupported)*currentSupported,bothSupported*ownerByPhase);\n" +
            " vec3 ownedPrediction=mix(a.rgb,b.rgb,chooseCurrent);\n" +
            " vec3 mutuallyVisiblePrediction=mix(ownedPrediction,alignedPrediction,appearanceAdmission);\n" +
            " vec3 densePrediction=mix(ownedPrediction,mutuallyVisiblePrediction,bothSupported);\n" +
            " vec3 selectedPrediction=mix(alignedPrediction,densePrediction,uDenseEncoding);\n" +
            " float predictionAdmission=mix(1.0,anySupported,uDenseEncoding);\n" +
            // Screen-space HUD, radar chrome, and status text do not move
            // between endpoints. Warping them with the camera/body flow is
            // the smear watched on Hunters (2026-08-16). Hold the exact
            // endpoint wherever previous and current already agree.
            " float endpointDelta=max(max(abs(rawPrevious.r-rawCurrent.r)," +
                    "abs(rawPrevious.g-rawCurrent.g))," +
                    "abs(rawPrevious.b-rawCurrent.b));\n" +
            " float staticHud=1.0-smoothstep(6.0/255.0,20.0/255.0,endpointDelta);\n" +
            " gl_FragColor=vec4(mix(exactEndpoint,selectedPrediction," +
                    "predictionAdmission*(1.0-staticHud)),1.0);\n" +
            "}\n";

    // Independent qualification reference. This intentionally does not call
    // or reuse the production interpolation program: its output is compared
    // with the frame produced above, and uInvert supplies a directional
    // negative control using the opposite decoded vector.
    private static final String MOTION_PREDICTION_PROOF_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uPrevious;\n" +
            "uniform sampler2D uCurrent;\n" +
            "uniform sampler2D uBackwardMotion;\n" +
            "uniform sampler2D uForwardMotion;\n" +
            "uniform sampler2D uGlobalBackwardMotion;\n" +
            "uniform sampler2D uGlobalForwardMotion;\n" +
            "uniform vec2 uFlowRange;\n" +
            "uniform float uPhase;\n" +
            "uniform float uInvert;\n" +
            "uniform float uDenseEncoding;\n" +
            "varying vec2 vTexCoord;\n" +
            "vec2 decodeFlow(vec4 field){vec2 legacy=field.rg*2.0-1.0;vec2 dense=(field.rg*255.0-128.0)/127.0;return mix(legacy,dense,uDenseEncoding)*uFlowRange*uInvert;}\n" +
            "void main(){\n" +
            " vec4 backwardField=texture2D(uBackwardMotion,vTexCoord);\n" +
            " vec4 forwardField=texture2D(uForwardMotion,vTexCoord);\n" +
            " vec2 backward=decodeFlow(backwardField);\n" +
            " vec2 forward=decodeFlow(forwardField);\n" +
            " vec4 backwardPeer=texture2D(uBackwardMotion,clamp(vTexCoord+forward,vec2(0.0),vec2(1.0)));\n" +
            " vec4 forwardPeer=texture2D(uForwardMotion,clamp(vTexCoord+backward,vec2(0.0),vec2(1.0)));\n" +
            " vec2 safeRange=max(uFlowRange,vec2(0.00001));\n" +
            " float previousCycle=length((forward+decodeFlow(backwardPeer))/safeRange);\n" +
            " float currentCycle=length((backward+decodeFlow(forwardPeer))/safeRange);\n" +
            " float previousReliability=sqrt(clamp(forwardField.b,0.0,1.0)*clamp(backwardPeer.b,0.0,1.0))*clamp(1.0-4.0*previousCycle,0.0,1.0);\n" +
            " float currentReliability=sqrt(clamp(backwardField.b,0.0,1.0)*clamp(forwardPeer.b,0.0,1.0))*clamp(1.0-4.0*currentCycle,0.0,1.0);\n" +
            " vec4 globalBackwardField=texture2D(uGlobalBackwardMotion,vTexCoord);\n" +
            " vec4 globalForwardField=texture2D(uGlobalForwardMotion,vTexCoord);\n" +
            " vec2 globalBackward=decodeFlow(globalBackwardField);\n" +
            " vec2 globalForward=decodeFlow(globalForwardField);\n" +
            " vec4 globalBackwardPeer=texture2D(uGlobalBackwardMotion,clamp(vTexCoord+globalForward,vec2(0.0),vec2(1.0)));\n" +
            " vec4 globalForwardPeer=texture2D(uGlobalForwardMotion,clamp(vTexCoord+globalBackward,vec2(0.0),vec2(1.0)));\n" +
            " float previousGlobalCycle=length((globalForward+decodeFlow(globalBackwardPeer))/safeRange);\n" +
            " float currentGlobalCycle=length((globalBackward+decodeFlow(globalForwardPeer))/safeRange);\n" +
            " float previousGlobalReliability=sqrt(clamp(globalForwardField.b,0.0,1.0)*clamp(globalBackwardPeer.b,0.0,1.0))*clamp(1.0-5.0*previousGlobalCycle,0.0,1.0);\n" +
            " float currentGlobalReliability=sqrt(clamp(globalBackwardField.b,0.0,1.0)*clamp(globalForwardPeer.b,0.0,1.0))*clamp(1.0-5.0*currentGlobalCycle,0.0,1.0);\n" +
            " float previousGlobalUse=smoothstep(0.10,0.24,previousGlobalReliability)*(1.0-smoothstep(0.04,0.18,previousReliability));\n" +
            " float currentGlobalUse=smoothstep(0.10,0.24,currentGlobalReliability)*(1.0-smoothstep(0.04,0.18,currentReliability));\n" +
            " forward=mix(forward,globalForward,previousGlobalUse);\n" +
            " backward=mix(backward,globalBackward,currentGlobalUse);\n" +
            " previousReliability=max(previousReliability,previousGlobalReliability*previousGlobalUse);\n" +
            " currentReliability=max(currentReliability,currentGlobalReliability*currentGlobalUse);\n" +
            " float previousGate=step(0.02,previousReliability);\n" +
            " float currentGate=step(0.02,currentReliability);\n" +
            " vec3 a=texture2D(uPrevious,clamp(vTexCoord-forward*uPhase*previousGate,vec2(0.0),vec2(1.0))).rgb;\n" +
            " vec3 b=texture2D(uCurrent,clamp(vTexCoord-backward*(1.0-uPhase)*currentGate,vec2(0.0),vec2(1.0))).rgb;\n" +
            " vec3 rawPrevious=texture2D(uPrevious,vTexCoord).rgb;\n" +
            " vec3 rawCurrent=texture2D(uCurrent,vTexCoord).rgb;\n" +
            " float previousWeight=(1.0-uPhase)*(0.02+previousReliability);\n" +
            " float currentWeight=uPhase*(0.02+currentReliability);\n" +
            " float alignmentError=max(max(abs(a.r-b.r),abs(a.g-b.g)),abs(a.b-b.b));\n" +
            " float appearanceAdmission=1.0-smoothstep(24.0/255.0,96.0/255.0,alignmentError);\n" +
            " float nearestEndpoint=step(0.5,uPhase);\n" +
            " vec3 exactEndpoint=mix(rawPrevious,rawCurrent,nearestEndpoint);\n" +
            " vec3 alignedPrediction=mix(a,b,currentWeight/(previousWeight+currentWeight));\n" +
            " float previousSupported=step(0.02,previousReliability);\n" +
            " float currentSupported=step(0.02,currentReliability);\n" +
            " float bothSupported=previousSupported*currentSupported;\n" +
            " float anySupported=max(previousSupported,currentSupported);\n" +
            " float ownerByPhase=step(0.5,uPhase);\n" +
            " float chooseCurrent=max((1.0-previousSupported)*currentSupported,bothSupported*ownerByPhase);\n" +
            " vec3 ownedPrediction=mix(a,b,chooseCurrent);\n" +
            " vec3 mutuallyVisiblePrediction=mix(ownedPrediction,alignedPrediction,appearanceAdmission);\n" +
            " vec3 densePrediction=mix(ownedPrediction,mutuallyVisiblePrediction,bothSupported);\n" +
            " vec3 selectedPrediction=mix(alignedPrediction,densePrediction,uDenseEncoding);\n" +
            " float predictionAdmission=mix(1.0,anySupported,uDenseEncoding);\n" +
            " float endpointDelta=max(max(abs(rawPrevious.r-rawCurrent.r)," +
                    "abs(rawPrevious.g-rawCurrent.g))," +
                    "abs(rawPrevious.b-rawCurrent.b));\n" +
            " float staticHud=1.0-smoothstep(6.0/255.0,20.0/255.0,endpointDelta);\n" +
            " gl_FragColor=vec4(mix(exactEndpoint,selectedPrediction," +
                    "predictionAdmission*(1.0-staticHud)),1.0);\n" +
            "}\n";

    private final Surface outputSurface;
    private final int generatorId;
    private final String displayRole;
    private final int displayId;
    private final QualificationProofSwitch qualificationProofSwitch;
    private final DensePyramidSwitch densePyramidSwitch;
    private final DenseV27ReducedAnalysisSwitch denseV27ReducedAnalysisSwitch;
    private final DenseV28ReducedAnalysisSwitch denseV28ReducedAnalysisSwitch;
    private boolean qualificationProofEnabled;
    private boolean densePyramidEnabled;
    private boolean denseV27ReducedAnalysisRequested;
    private boolean denseV28ReducedAnalysisRequested;
    private final int requestedEglContextMajor;
    private boolean densePyramidUnavailable;
    private final HandlerThread thread;
    private final Handler handler;
    private final CountDownLatch started = new CountDownLatch(1);
    private final AtomicBoolean closed = new AtomicBoolean(false);
    private final AdaptiveFrameRateController frameRate;
    private volatile StatsListener statsListener;
    private final java.util.concurrent.atomic.AtomicReference<Runnable>
            firstSubmittedFrameListener = new java.util.concurrent.atomic.AtomicReference<>();

    private volatile Surface inputSurface;
    private volatile Throwable startupFailure;
    private int inputWidth;
    private int inputHeight;
    private int outputWidth;
    private int outputHeight;
    private float refreshHz;

    // GL-thread only below.
    private EGLDisplay eglDisplay = EGL14.EGL_NO_DISPLAY;
    private EGLContext eglContext = EGL14.EGL_NO_CONTEXT;
    private EGLSurface eglSurface = EGL14.EGL_NO_SURFACE;
    private SurfaceTexture inputTexture;
    private Choreographer choreographer;
    private int externalTexture;
    private final int[] historyTextures = new int[2];
    private int latestTexture;
    private final int[] signatureCandidateTextures =
            new int[SIGNATURE_CANDIDATE_SLOTS];
    private final long[] signatureCandidateSequence =
            new long[SIGNATURE_CANDIDATE_SLOTS];
    private final long[] signatureCandidateTimestampNs =
            new long[SIGNATURE_CANDIDATE_SLOTS];
    private final int[] signatureCandidateSubmission =
            new int[SIGNATURE_CANDIDATE_SLOTS];
    private final int[] endpointFifoTextures = new int[ENDPOINT_FIFO_CAPACITY];
    private final long[] endpointFifoSequence = new long[ENDPOINT_FIFO_CAPACITY];
    private final long[] endpointFifoTimestampNs = new long[ENDPOINT_FIFO_CAPACITY];
    private int endpointFifoHead;
    private int endpointFifoCount;
    private long endpointSequence;
    private long endpointFifoCoalesced;
    private long endpointCandidateUnavailable;
    private long endpointTimestampCorrections;
    private long lastProducerTimestampNs;
    private long lastPresentationEndpointTimestampNs;
    private final EndpointFrameSelector presentationEndpointSelector =
            new EndpointFrameSelector();
    private long uniqueFrameCount;
    private int classifiedUniqueTexture;
    private long classifiedUniqueTimestampNs;
    private long activeLeftSequence;
    private long activeRightSequence;
    private long activeLeftTimestampNs;
    private long activeRightTimestampNs;
    private boolean activePairReady;
    private boolean activePairSyntheticCommitted;
    private long lastPromotedEndpointSequence;
    private long bufferedPairCreatedCount;
    private long bufferedSyntheticSelectedCount;
    private long bufferedSyntheticQuotaSkippedCount;
    private long bufferedSyntheticNotReadyCount;
    private long bufferedPresentationCallbackCount;
    private long bufferedLastSelectedSyntheticPair;
    private int frameBuffer;
    private int copyProgram;
    private int textureCopyProgram;
    private int signatureCompareProgram;
    private int interpolateProgram;
    private int predictionProofProgram;
    private int flowProofProgram;
    private int coarseMotionProgram;
    private int refineMotionProgram;
    private int regularizeMotionProgram;
    private int regionalCoarseCandidateProgram;
    private int regionalFineCandidateProgram;
    private int regionalCandidateWinnerProgram;
    private int globalMotionProgram;
    private int densePyramidProgram;
    private int denseSolveProgram;
    private int denseCycleProgram;
    private int denseQ8ProbeProgram;
    private int proofAtlasHeaderProgram;
    private int denseDiagnosticPackProgram;
    private final int[] flowTextures = new int[3];
    private final int[] reverseFlowTextures = new int[3];
    private final int[] globalCandidateTextures = new int[2];
    private final int[] globalCandidateWinnerTextures = new int[2];
    // Independently reduced, overlapping source-backed regional controls for
    // each direction. GL_LINEAR sampling feathers them into a smooth field.
    private final int[] globalFlowTextures = new int[2];
    private final int[][][] denseFlowTextures = new int[2][DENSE_LEVELS][2];
    private final int[][] densePyramidTextures = new int[2][2];
    private final int[] denseFinalTextures = new int[2];
    private final int[] denseValidatedTextures = new int[2];
    private final int[] denseLevelWidths = new int[DENSE_LEVELS];
    private final int[] denseLevelHeights = new int[DENSE_LEVELS];
    private int denseAnalysisWidth;
    private int denseAnalysisHeight;
    private boolean denseResourcesReady;
    private long densePromotions;
    private long densePasses;
    private long denseCpuSubmitTotalUs;
    private long denseCpuSubmitMaxUs;
    private long denseCpuSubmitLastUs;
    private long denseGpuCompleteTotalUs;
    private long denseGpuCompleteMaxUs;
    private long denseGpuCompleteLastUs;
    private DenseGpuTimer denseGpuTimer;
    private final long[] denseStageTotalUs = new long[7];
    private final long[] denseStageMaxUs = new long[7];
    private final long[] denseStageSamples = new long[7];
    private final long[][] denseStageObservedUs = new long[7][256];
    private final long[] densePairSequence = new long[128];
    private final long[] densePairTotalUs = new long[128];
    private final int[] densePairMask = new int[128];
    private long denseWarpSequence;
    private long denseWarpMaxCompletedSequence;
    private final long[] denseWarpCompletedSequence = new long[128];
    private long denseTimedPairs;
    private long denseTimedPairTotalUs;
    private long denseTimedPairMaxUs;
    private long denseTimerUnavailable;
    private long denseTimerDisjoint;
    private long denseTimerStale;
    private long denseTimerMaxQueueAge;
    private boolean densePerformanceRejected;
    private final long[] densePromotionWallObservedUs = new long[256];
    private long densePromotionWallSamples;
    private long densePromotionWallTotalUs;
    private long densePromotionWallMaxUs;
    private final long[] denseSignatureWallObservedUs = new long[256];
    private long denseSignatureWallSamples;
    private long denseSignatureWallTotalUs;
    private long denseSignatureWallMaxUs;
    private final long[] denseProofWallObservedUs = new long[256];
    private long denseProofWallSamples;
    private long denseProofWallTotalUs;
    private long denseProofWallMaxUs;
    private long denseSignatureSequence;
    private long denseSignatureReady;
    private long denseSignatureUnavailable;
    private long denseSignatureMaxQueueAge;
    private int actualEglContextMajor;
    private int actualEglContextMinor;
    private boolean motionEstimateReady;
    private long denseCalibrationRuns;
    private long denseCalibrationUs;
    private long denseProofCells;
    private long denseBackwardValidCells;
    private long denseForwardValidCells;
    private long denseDiagnosticCells;
    private long denseDiagnosticTiles;
    private final long[] denseDiagnosticActiveCells = new long[2];
    private final long[] denseDiagnosticInBoundsCells = new long[2];
    private final long[] denseDiagnosticCycleValidCells = new long[2];
    private final long[] denseDiagnosticPhotometricValidCells = new long[2];
    private final long[] denseDiagnosticTextureValidCells = new long[2];
    private final long[] denseDiagnosticSaturatedCells = new long[2];
    private final long[] denseDiagnosticOutOfBoundsCells = new long[2];
    private final long[] denseDiagnosticCoveredTiles = new long[2];
    private final int[] denseDiagnosticCoveredTileMask = new int[2];
    private long denseDiagnosticMaskErrors;
    private long denseDiagnosticPackedCells;
    private long denseDiagnosticPartitionErrors;
    private long denseDiagnosticReservedBitErrors;
    private long denseDiagnosticLastAtlasSequence;
    private long denseDiagnosticLastPairSequence;
    private long denseDiagnosticLastPreviousEndpoint;
    private long denseDiagnosticLastCurrentEndpoint;
    private long denseDiagnosticLastTargetSourceNs;
    private float densePairMeanDifference;
    private java.nio.ByteBuffer denseProofPixels;
    private int coarseFlowWidth;
    private int coarseFlowHeight;
    private int fineFlowWidth;
    private int fineFlowHeight;
    private int activeMotionVectors;
    private int confidentMotionVectors;
    private int proofTexture;
    private int proofAtlasTexture;
    private int signatureTexture;
    private int signaturePreviousTexture;
    private int signatureQueryTexture;
    private boolean denseSignatureBaselineReady;
    private java.nio.ByteBuffer proofPixels;
    private java.nio.ByteBuffer signaturePixels;
    private java.nio.ByteBuffer regionalFlowPixels;
    private java.nio.ByteBuffer proofAtlasPixels;
    private java.nio.ByteBuffer proofAtlasHeader;
    private long proofAtlasEpoch = 1;
    private long proofAtlasEnqueued;
    private long proofAtlasCompleted;
    private long proofEvidencePresentationEpoch;
    private long proofEvidenceEnqueuedInEpoch;
    private long proofEvidenceAccepted;
    private long proofEvidenceExcluded;
    private long proofEvidenceLastAcceptedAtlasSequence;
    private long proofAtlasSequence;
    private long proofAtlasMaxQueueAge;
    private long proofAtlasTimeoutPolls;
    private long proofAtlasRingFull;
    private long proofAtlasErrors;
    private long proofAtlasTagErrors;
    private long proofAtlasDiscarded;
    private long proofAtlasSynchronousFallback;
    private long healthSequence;
    private long lastCallbackFrameTimeNs;
    private long callbackDeltaSamples;
    private long callbackDeltaTotalUs;
    private long callbackDeltaMaxUs;
    private long callbackLateCount;
    private final long[] densePresentWallObservedUs = new long[256];
    private long densePresentWallSamples;
    private long densePresentWallTotalUs;
    private long densePresentWallMaxUs;
    private final long[] denseSwapWallObservedUs = new long[256];
    private long denseSwapWallSamples;
    private long denseSwapWallTotalUs;
    private long denseSwapWallMaxUs;
    private final long[] denseProofEnqueueWallObservedUs = new long[256];
    private long denseProofEnqueueWallSamples;
    private long denseProofEnqueueWallTotalUs;
    private long denseProofEnqueueWallMaxUs;
    private final long[] denseProofPollWallObservedUs = new long[256];
    private long denseProofPollWallSamples;
    private long denseProofPollWallTotalUs;
    private long denseProofPollWallMaxUs;
    private final byte[] lastSourceSignature =
            new byte[SIGNATURE_WIDTH * SIGNATURE_HEIGHT * 4];
    private final byte[] currentSourceSignature =
            new byte[SIGNATURE_WIDTH * SIGNATURE_HEIGHT * 4];
    private boolean sourceSignatureReady;
    private long proofSamples;
    private long lastProofPresent = Long.MIN_VALUE;
    private long syntheticProofSamples;
    private long syntheticDistinctFromEndpoints;
    private long changingProofOutputs;
    private long eligibleSyntheticPixels;
    private long substantiveSyntheticPixels;
    private long nonCrossfadeSyntheticPixels;
    private long motionEligibleProofSamples;
    private long motionCorrelatedProofSamples;
    private long motionEligibleSyntheticPixels;
    private long motionSynthesizedSyntheticPixels;
    private long latticeRegionSamples;
    private long latticeBackwardCoherentRegions;
    private long latticeForwardCoherentRegions;
    private long latticeBackwardBoundaryRegions;
    private long latticeForwardBoundaryRegions;
    private long latticeBackwardCoherentBoundaryRegions;
    private long latticeForwardCoherentBoundaryRegions;
    private int latticeBackwardCoherentRegionCount;
    private int latticeForwardCoherentRegionCount;
    private int latticeBackwardBoundaryRegionCount;
    private int latticeForwardBoundaryRegionCount;
    private int latticeBackwardCoherentBoundaryRegionCount;
    private int latticeForwardCoherentBoundaryRegionCount;
    private int latticeBackwardPeakSupport;
    private int latticeForwardPeakSupport;
    private long regionalFlowRegionSamples;
    private long regionalBackwardSupportedRegions;
    private long regionalForwardSupportedRegions;
    private long regionalBackwardNeighborRegions;
    private long regionalForwardNeighborRegions;
    private long regionalBackwardConstantNeighborRegions;
    private long regionalForwardConstantNeighborRegions;
    private long regionalBackwardGradientNeighborRegions;
    private long regionalForwardGradientNeighborRegions;
    private long regionalBackwardAcceptedRegions;
    private long regionalForwardAcceptedRegions;
    private long regionalBackwardAcceptedBoundaryRegions;
    private long regionalForwardAcceptedBoundaryRegions;
    private long regionalBackwardCycleAcceptedRegions;
    private long regionalForwardCycleAcceptedRegions;
    private int regionalBackwardAcceptedRegionCount;
    private int regionalForwardAcceptedRegionCount;
    private int regionalBackwardAcceptedBoundaryRegionCount;
    private int regionalForwardAcceptedBoundaryRegionCount;
    private int regionalBackwardSupportedRegionCount;
    private int regionalForwardSupportedRegionCount;
    private int regionalBackwardNeighborRegionCount;
    private int regionalForwardNeighborRegionCount;
    private int regionalBackwardConstantNeighborRegionCount;
    private int regionalForwardConstantNeighborRegionCount;
    private int regionalBackwardGradientNeighborRegionCount;
    private int regionalForwardGradientNeighborRegionCount;
    private int regionalBackwardCycleAcceptedRegionCount;
    private int regionalForwardCycleAcceptedRegionCount;
    private int regionalBackwardPeakSupport;
    private int regionalForwardPeakSupport;
    private int regionalBackwardPeakConfidence;
    private int regionalForwardPeakConfidence;
    private long lastProofHash;
    private final byte[] proofPrevious = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
    private final byte[] proofCurrent = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
    private final byte[] proofOutput = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
    private final byte[] proofPredicted = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
    private final byte[] proofInverse = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
    private final byte[] proofFlow = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
    private int previousIndex;
    private int currentIndex = 1;
    private int realFrameCount;
    private int submittedFrameCount;
    private int lastUniqueSubmissionCount;
    private int promotedFrameCount;
    private int historyWidth;
    private int historyHeight;
    private float presentationAspect;
    private android.graphics.Bitmap softwareUploadBitmap;
    private long presents;
    private long generatedPresents;
    private long healthWindowStartNanos;
    private long lastHealthPresents;
    private long lastHealthGenerated;
    private long lastHealthPromoted;
    private long lastHealthDueSelected;
    private long lastHealthDueNoEndpoint;
    private long lastHealthDuePhaseClamped;
    private long lastHealthRealPriority;
    private long lastHealthSyntheticQuotaSkipped;
    private long lastHealthSyntheticSelected;
    private long lastHealthSyntheticPairCreated;
    private long lastHealthSyntheticNotReady;
    private long lastHealthDuplicatePairSelection;
    private long lastHealthPresentationCallbacks;
    private long lastHealthSyntheticQuotaPending;
    private long lastHealthPresentationEpoch;
    private boolean pendingDenseCadenceReject;
    private int denseCadenceFailureWindows;
    private long pendingDenseHealthPresents;
    private long pendingDenseHealthGenerated;
    private long pendingDenseHealthPromoted;
    private boolean generationLogged;
    private boolean outputFrameRateReassertedAfterSwap;
    private int reportedSourceFps = -1;
    private int reportedOutputFps = -1;
    private int statsTargetSourceFps = -1;
    private int statsTargetOutputFps = -1;
    private long statsWindowStartNanos;
    private long statsWindowStartPresents;
    // Midpoint-undershoot diagnostic (2026-08-15): decoded recordings showed
    // generated frames advancing only 9-28% of the source motion step. These
    // accumulators publish the scheduler-selected synthetic phase and the
    // retained endpoint spacing once per stats window on an independent log
    // line, so the defect can be split between scheduler phase and flow
    // underestimation without touching any evidence schema.
    private double phaseDiagSum;
    private float phaseDiagMin = Float.MAX_VALUE;
    private float phaseDiagMax;
    private int phaseDiagCount;
    private double phaseDiagSpanSumNs;
    private long stallObservedPresents = -1L;
    private long stallStartFrameNs;
    private long stallLastLogNs;
    private final float[] textureTransform = new float[16];
    private java.nio.FloatBuffer quad;

    public DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz) {
        this(output, inputWidth, inputHeight, outputWidth, outputHeight,
                refreshHz, "unspecified", -1, () -> false);
    }

    public DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz,
                                 String displayRole) {
        this(output, inputWidth, inputHeight, outputWidth, outputHeight,
                refreshHz, displayRole, -1, () -> false);
    }

    public DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz,
                                 String displayRole, int displayId) {
        this(output, inputWidth, inputHeight, outputWidth, outputHeight,
                refreshHz, displayRole, displayId, () -> false);
    }

    public DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz,
                                 String displayRole, int displayId,
                                 QualificationProofSwitch qualificationProofSwitch) {
        this(output, inputWidth, inputHeight, outputWidth, outputHeight, refreshHz,
                displayRole, displayId, qualificationProofSwitch, () -> false);
    }

    public DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz,
                                 String displayRole, int displayId,
                                 QualificationProofSwitch qualificationProofSwitch,
                                 DensePyramidSwitch densePyramidSwitch) {
        this(output, inputWidth, inputHeight, outputWidth, outputHeight, refreshHz,
                displayRole, displayId, qualificationProofSwitch, densePyramidSwitch,
                () -> false, () -> false);
    }

    public DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz,
                                 String displayRole, int displayId,
                                 QualificationProofSwitch qualificationProofSwitch,
                                 DensePyramidSwitch densePyramidSwitch,
                                 DenseV27ReducedAnalysisSwitch denseV27ReducedAnalysisSwitch) {
        this(output, inputWidth, inputHeight, outputWidth, outputHeight, refreshHz,
                displayRole, displayId, qualificationProofSwitch, densePyramidSwitch,
                denseV27ReducedAnalysisSwitch, () -> false);
    }

    public DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz,
                                 String displayRole, int displayId,
                                 QualificationProofSwitch qualificationProofSwitch,
                                 DensePyramidSwitch densePyramidSwitch,
                                 DenseV27ReducedAnalysisSwitch denseV27ReducedAnalysisSwitch,
                                 DenseV28ReducedAnalysisSwitch denseV28ReducedAnalysisSwitch) {
        if (output == null || !output.isValid())
            throw new IllegalArgumentException("a valid output Surface is required");
        this.outputSurface = output;
        this.generatorId = NEXT_GENERATOR_ID.getAndIncrement();
        this.displayRole = sanitizeRole(displayRole);
        this.displayId = displayId;
        this.qualificationProofSwitch = qualificationProofSwitch == null
                ? () -> false : qualificationProofSwitch;
        this.densePyramidSwitch = densePyramidSwitch == null
                ? () -> false : densePyramidSwitch;
        this.denseV27ReducedAnalysisSwitch = denseV27ReducedAnalysisSwitch == null
                ? () -> false : denseV27ReducedAnalysisSwitch;
        this.denseV28ReducedAnalysisSwitch = denseV28ReducedAnalysisSwitch == null
                ? () -> false : denseV28ReducedAnalysisSwitch;
        // Analysis dimensions allocate once with the EGL resources. Capture
        // this shell-only experiment before startup; a live settings toggle
        // must not reinterpret an existing v26 allocation as v27 evidence.
        try {
            this.denseV27ReducedAnalysisRequested =
                    this.denseV27ReducedAnalysisSwitch.enabled();
            this.denseV28ReducedAnalysisRequested =
                    this.denseV28ReducedAnalysisSwitch.enabled();
        } catch (RuntimeException ignored) {
            this.denseV27ReducedAnalysisRequested = false;
            this.denseV28ReducedAnalysisRequested = false;
        }
        if (denseV27ReducedAnalysisRequested && denseV28ReducedAnalysisRequested)
            throw new IllegalArgumentException("dense v27 and v28 variants are mutually exclusive");
        // v31's asynchronous uniqueness proof uses core ES3 occlusion queries.
        // The immutable raw dense+v28 preselection is the only path allowed to
        // request this context; default/v22 and every older experiment remain
        // byte-for-byte on the established ES2 context path.
        this.requestedEglContextMajor = denseV28ReducedAnalysisRequested ? 3 : 2;
        this.qualificationProofEnabled = false;
        this.inputWidth = positive(inputWidth);
        this.inputHeight = positive(inputHeight);
        this.outputWidth = positive(outputWidth);
        this.outputHeight = positive(outputHeight);
        this.refreshHz = sanitizeRefresh(refreshHz);
        frameRate = new AdaptiveFrameRateController(this.refreshHz);
        thread = new HandlerThread("emufusion-frame-generator");
        thread.start();
        handler = new Handler(thread.getLooper());
        handler.post(this::initialize);
        try {
            if (!started.await(START_TIMEOUT_MS, TimeUnit.MILLISECONDS))
                throw new IllegalStateException("frame generator startup timed out");
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            close();
            throw new IllegalStateException("interrupted starting frame generator", interrupted);
        }
        if (startupFailure != null) {
            close();
            throw new IllegalStateException("frame generator startup failed", startupFailure);
        }
        if (inputSurface == null || !inputSurface.isValid()) {
            close();
            throw new IllegalStateException("frame generator produced no input Surface");
        }
        synchronized (INPUTS) {
            INPUTS.put(inputSurface, new WeakReference<>(this));
        }
    }

    /** The only Surface an emulator receives. The actual display Surface remains private. */
    public Surface inputSurface() { return inputSurface; }

    public void setStatsListener(StatsListener value) {
        statsListener = value;
        if (value != null) handler.post(() -> {
            if (statsListener != value) return;
            // A newly attached overlay has not observed any of this Surface's
            // prior swaps. Start from an explicit unknown output instead of
            // replaying a target or a stale listener's last value.
            reportedSourceFps = -1;
            reportedOutputFps = -1;
            publishReportedFrameRate(frameRate.lockedSourceFps(), 0,
                    frameRate.outputFps());
        });
    }

    /** Uses the fixed cadence declared by a deterministic legacy core. */
    public void setAuthoritativeSourceHz(double sourceHz) {
        if (closed.get()) return;
        handler.post(() -> {
            // A live source-mode change invalidates any delayed uniqueness
            // query and its retained texture as one ownership epoch. Tear the
            // native ring down before resetEndpointFifo clears the Java side;
            // qualification may create a fresh timer after the new fixed-rate
            // presentation epoch is established.
            if (densePyramidEnabled || denseGpuTimer != null) {
                densePyramidEnabled = false;
                teardownDenseEpoch("authoritative-source-change");
            }
            frameRate.setAuthoritativeSourceHz(sourceHz);
            resetEndpointFifo();
            sourceSignatureReady = false;
            generationLogged = false;
            resetHealthWindowAfterStreamChange();
            Log.i(TAG, "Authoritative source cadence generator=" + generatorId +
                    " sourceHz=" + sourceHz +
                    " enabled=" + frameRate.usesAuthoritativeSourceRate());
        });
    }

    /** Runs once after the producer's first complete buffer is consumed. */
    public void setFirstSubmittedFrameListener(Runnable value) {
        firstSubmittedFrameListener.set(value);
    }

    private void notifyFirstSubmittedFrame() {
        Runnable callback = firstSubmittedFrameListener.getAndSet(null);
        if (callback != null) callback.run();
    }

    /** Returns the generator owning an engine Surface, or null for a direct Surface. */
    public static DisplayFrameGenerator forInputSurface(Surface surface) {
        if (surface == null) return null;
        synchronized (INPUTS) {
            WeakReference<DisplayFrameGenerator> reference = INPUTS.get(surface);
            DisplayFrameGenerator value = reference == null ? null : reference.get();
            if (value == null && reference != null) INPUTS.remove(surface);
            return value;
        }
    }

    /**
     * Fast path for software libretro frames.
     *
     * <p>Uploading the source-sized image avoids asking Android Canvas to
     * rewrite a 1440x1080 CPU buffer 60 times per second merely so this GPU
     * compositor can read it back. The immutable copy is intentional: the
     * emulation render thread immediately reuses its decode array.
     */
    public boolean submitSoftwareFrame(int[] colors, int frameWidth, int frameHeight,
                                       int left, int top, int right, int bottom,
                                       float contentAspect) {
        if (closed.get() || colors == null || frameWidth < 1 || frameHeight < 1 ||
                left < 0 || top < 0 || right <= left || bottom <= top ||
                right > frameWidth || bottom > frameHeight ||
                colors.length < (long) frameWidth * frameHeight) return false;
        final long producerTimestampNs = System.nanoTime();
        final int width = right - left;
        final int height = bottom - top;
        final int[] snapshot = new int[width * height];
        // Libretro software buffers and Android Bitmap rows are top-first, but
        // the sampler2D presentation quad has OpenGL's bottom-left origin.
        // Reverse rows while making the immutable crop snapshot. Doing this
        // inside the requested crop is essential for dual-screen composites:
        // top and bottom are corrected independently instead of being swapped.
        for (int row = 0; row < height; ++row)
            System.arraycopy(colors, (bottom - 1 - row) * frameWidth + left,
                    snapshot, row * width, width);
        final float aspect = Float.isFinite(contentAspect) && contentAspect > 0f
                ? contentAspect : (float) width / height;
        handler.post(() -> uploadSoftwareFrame(snapshot, width, height, aspect,
                producerTimestampNs));
        return true;
    }

    /** Resizes without replacing the producer Surface or restarting an emulator. */
    public void resize(int newInputWidth, int newInputHeight,
                       int newOutputWidth, int newOutputHeight, float newRefreshHz) {
        if (closed.get()) return;
        final int iw = positive(newInputWidth);
        final int ih = positive(newInputHeight);
        final int ow = positive(newOutputWidth);
        final int oh = positive(newOutputHeight);
        final float hz = sanitizeRefresh(newRefreshHz);
        handler.post(() -> {
            if (densePyramidEnabled || denseGpuTimer != null) {
                densePyramidEnabled = false;
                teardownDenseEpoch("stream-resize");
            }
            inputWidth = iw;
            inputHeight = ih;
            outputWidth = ow;
            outputHeight = oh;
            refreshHz = hz;
            frameRate.setDisplayRefreshHz(hz);
            outputFrameRateReassertedAfterSwap = false;
            requestOutputFrameRate("resize");
            if (inputTexture != null) inputTexture.setDefaultBufferSize(iw, ih);
            allocateHistoryTextures(iw, ih);
            sourceSignatureReady = false;
            frameRate.resetPresentation();
            resetHealthWindowAfterStreamChange();
            // The offline verifier binds workload identity to the CURRENT
            // input dimensions. Engines report their true frame size after
            // the initial attach (a DS stream attaches at panel size and
            // resizes to native 256x192 — physically hit 2026-08-16), so
            // every resize logs a parseable record; the verifier uses the
            // latest one before the evidence segment.
            Log.i(TAG, "Frame generator resized generator=" + generatorId +
                    " role=" + displayRole +
                    " displayId=" + displayId +
                    " input=" + iw + "x" + ih);
        });
    }

    @Override public void onFrameAvailable(SurfaceTexture ignored) {
        // Listener is registered on our Handler, so this already owns EGL.
        if (closed.get() || inputTexture == null) return;
        try {
            // Presentation throughput is a wall-clock property. SurfaceTexture
            // timestamps are media/emulation timestamps and may lag, jump or
            // be repeated when Android coalesces queued producer buffers. Using
            // them to pace the endpoint FIFO made a healthy 60-callback stream
            // look like 45-50 endpoints/second during r67 even though the GL
            // handler received every callback. Capture one monotonic arrival
            // time before consuming this exact buffer and use it consistently
            // for signature evidence, tier measurement and FIFO scheduling.
            long producerArrivalNs = System.nanoTime();
            inputTexture.updateTexImage();
            inputTexture.getTransformMatrix(textureTransform);
            copyExternalTo(latestTexture);
            ++submittedFrameCount;
            notifyFirstSubmittedFrame();
            if (frameRate.usesAuthoritativeSourceRate()) {
                observeUniqueFrame(producerArrivalNs, submittedFrameCount);
            } else if (latestImageIsUnique(producerArrivalNs)) {
                observeUniqueFrame(classifiedUniqueTimestampNs,
                        submittedFrameCount);
            }
            if (selectPresentationEndpoint(producerArrivalNs))
                acceptPresentationEndpoint(latestTexture,
                        presentationEndpointSelector.selectedTimestampNs());
        } catch (RuntimeException failure) {
            Log.e(TAG, "Unable to consume emulator frame", failure);
        }
    }

    @Override public void doFrame(long frameTimeNanos) {
        if (closed.get()) return;
        // Register the following physical-vsync callback before any rendering
        // or eglSwapBuffers work.  Some Android EGL drivers block swap until
        // the next scan. Registering only after that wait loses the callback
        // that just occurred and deterministically halves a 120-Hz generated
        // stream even though the GPU work itself is within budget.
        if (choreographer != null) choreographer.postFrameCallback(this);
        try {
            if (lastCallbackFrameTimeNs != 0L) {
                long deltaUs = Math.max(1L,
                        (frameTimeNanos - lastCallbackFrameTimeNs + 999L) / 1000L);
                ++callbackDeltaSamples;
                callbackDeltaTotalUs += deltaUs;
                callbackDeltaMaxUs = Math.max(callbackDeltaMaxUs, deltaUs);
                if (deltaUs > 12500L) ++callbackLateCount;
            }
            lastCallbackFrameTimeNs = frameTimeNanos;
            if (densePyramidEnabled) {
                try {
                    refreshProofEvidencePresentationEpoch();
                    pollProofAtlas();
                } catch (RuntimeException proofFailure) {
                    ++proofAtlasErrors;
                    rejectDense("async-proof-atlas-poll-failure", proofFailure);
                }
            }
            reportStats();
            reportPresentationStall(frameTimeNanos);
            // Choreographer follows the physical panel. The callback-slot
            // accumulator selects the exact panel-capped x2 content target:
            // divisors use invariant slots, while 80/100 use explicit 2:3/5:6
            // physical-slot patterns. Timestamp interpolation remains tied to
            // retained producer endpoints and only successful swaps are counted.
            prepareBufferedPairIfPossible();
            ++bufferedPresentationCallbackCount;
            long underrunsBefore = frameRate.bufferedUnderrunCount();
            int presentation = frameRate.selectBufferedPresentation(
                    frameTimeNanos, activeLeftSequence, activeLeftTimestampNs,
                    activeRightSequence, activeRightTimestampNs,
                    activePairReady && motionEstimateReady);
            if (frameRate.bufferedUnderrunCount() != underrunsBefore) {
                ++bufferedSyntheticNotReadyCount;
                // The controller deliberately advances its output lattice on
                // an underrun. Drop the incomplete active pair and wait for
                // two strictly newer retained endpoints; never catch up with
                // adjacent REAL swaps or interpolate across a missing frame.
                invalidateBufferedPairForReprime(false);
            }
            if (presentation != AdaptiveFrameRateController.PRESENT_NONE) {
                long denseWallStart = densePyramidEnabled ? System.nanoTime() : 0L;
                long presentStarted = densePyramidEnabled ? System.nanoTime() : 0L;
                try {
                    presentBuffered(frameTimeNanos, presentation,
                            frameRate.bufferedSelectedPhase());
                } catch (RuntimeException failure) {
                    frameRate.abortBufferedPresentation();
                    invalidateBufferedPairForReprime(false);
                    throw failure;
                }
                if (presentStarted != 0L)
                    recordDenseWall(DENSE_WALL_PRESENT,
                            System.nanoTime() - presentStarted);
                if (presentation == AdaptiveFrameRateController.PRESENT_REAL &&
                        denseWallStart != 0L)
                    recordDenseWall(DENSE_WALL_PROMOTION,
                            System.nanoTime() - denseWallStart);
                if (pendingDenseCadenceReject)
                    finalizeDenseCadenceReject();
            }
        } catch (RuntimeException failure) {
            Log.e(TAG, "Display-vsync presentation failed", failure);
        }
    }

    @Override public void close() {
        if (!closed.compareAndSet(false, true)) return;
        Surface registered = inputSurface;
        synchronized (INPUTS) {
            if (registered != null) INPUTS.remove(registered);
        }
        CountDownLatch finished = new CountDownLatch(1);
        handler.post(() -> {
            try { releaseGl(); }
            finally { finished.countDown(); }
        });
        try { finished.await(STOP_TIMEOUT_MS, TimeUnit.MILLISECONDS); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
        thread.quitSafely();
    }

    private void initialize() {
        try {
            initializeEgl();
            initializeGl();
            inputTexture = new SurfaceTexture(externalTexture);
            inputTexture.setDefaultBufferSize(inputWidth, inputHeight);
            inputTexture.setOnFrameAvailableListener(this, handler);
            inputSurface = new Surface(inputTexture);
            requestOutputFrameRate("initialize");
            choreographer = Choreographer.getInstance();
            healthWindowStartNanos = System.nanoTime();
            updateSchedulerHealthBaseline();
            choreographer.postFrameCallback(this);
            Log.i(TAG, "Frame generator attached generator=" + generatorId +
                    " role=" + displayRole + " displayId=" + displayId +
                    " proofContract=" + activeProofContract() +
                    " proofSchemaVersion=" + activeProofSchemaVersion() +
                    " output=" + outputWidth + "x" +
                    outputHeight + " input=" + inputWidth + "x" + inputHeight +
                    " requestedGles=" + requestedEglContextMajor +
                    " actualGles=" + actualEglContextMajor + "." +
                    actualEglContextMinor +
                    " displayHz=" + refreshHz +
                    " qualificationProof=" + qualificationProofEnabled);
        } catch (Throwable failure) {
            startupFailure = failure;
            Log.e(TAG, "Frame generator initialization failed", failure);
            releaseGl();
        } finally {
            started.countDown();
        }
    }

    /**
     * Votes for the physical callback cadence of this game compositor.
     *
     * <p>FIXED_SOURCE is a video/pulldown hint.  It is incorrect here because
     * this renderer adapts its output to the selected display cadence.  The
     * explicit API-31 strategy documents that only a seamless mode transition
     * is acceptable during gameplay; API 30 receives the equivalent two-arg
     * vote.  A post-swap reassertion covers a newly relaunched Surface whose
     * first pre-buffer vote was not yet associated with a visible layer.</p>
     */
    private void requestOutputFrameRate(String reason) {
        if (Build.VERSION.SDK_INT < 30) return;
        try {
            if (Build.VERSION.SDK_INT >= 31) {
                outputSurface.setFrameRate(refreshHz,
                        Surface.FRAME_RATE_COMPATIBILITY_DEFAULT,
                        Surface.CHANGE_FRAME_RATE_ONLY_IF_SEAMLESS);
            } else {
                outputSurface.setFrameRate(refreshHz,
                        Surface.FRAME_RATE_COMPATIBILITY_DEFAULT);
            }
            Log.i(TAG, "Requested game display cadence generator=" + generatorId +
                    " reason=" + reason + " frameRate=" + refreshHz +
                    " compatibility=default strategy=seamless");
        } catch (RuntimeException failure) {
            Log.e(TAG, "Unable to request game display cadence generator=" +
                    generatorId + " reason=" + reason +
                    " frameRate=" + refreshHz, failure);
        }
    }

    private void initializeEgl() {
        eglDisplay = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        if (eglDisplay == EGL14.EGL_NO_DISPLAY) fail("eglGetDisplay");
        int[] version = new int[2];
        if (!EGL14.eglInitialize(eglDisplay, version, 0, version, 1)) fail("eglInitialize");
        int[] attributes = {
                EGL14.EGL_RENDERABLE_TYPE, requestedEglContextMajor >= 3 ?
                        EGL_OPENGL_ES3_BIT_KHR : EGL_OPENGL_ES2_BIT,
                EGL14.EGL_SURFACE_TYPE, EGL14.EGL_WINDOW_BIT,
                EGL14.EGL_RED_SIZE, 8, EGL14.EGL_GREEN_SIZE, 8,
                EGL14.EGL_BLUE_SIZE, 8, EGL14.EGL_ALPHA_SIZE, 8,
                EGL14.EGL_NONE
        };
        EGLConfig[] configs = new EGLConfig[1];
        int[] count = new int[1];
        if (!EGL14.eglChooseConfig(eglDisplay, attributes, 0, configs, 0, 1, count, 0) ||
                count[0] < 1) fail("eglChooseConfig");
        int[] contextAttributes = {EGL14.EGL_CONTEXT_CLIENT_VERSION,
                requestedEglContextMajor, EGL14.EGL_NONE};
        eglContext = EGL14.eglCreateContext(eglDisplay, configs[0], EGL14.EGL_NO_CONTEXT,
                contextAttributes, 0);
        if (eglContext == EGL14.EGL_NO_CONTEXT) fail("eglCreateContext");
        int[] surfaceAttributes = {EGL14.EGL_NONE};
        eglSurface = EGL14.eglCreateWindowSurface(eglDisplay, configs[0], outputSurface,
                surfaceAttributes, 0);
        if (eglSurface == EGL14.EGL_NO_SURFACE) fail("eglCreateWindowSurface");
        if (!EGL14.eglMakeCurrent(eglDisplay, eglSurface, eglSurface, eglContext))
            fail("eglMakeCurrent");
        // The qualification compositor is already paced by Choreographer.
        // A second implicit EGL-vsync wait makes endpoint swap plus the
        // emulator's own GL context serialize on Adreno: the physical r1 run
        // measured 9.4-ms swap p95 and received only ~76 of 120 callbacks/s
        // even though the isolated motion pair was 4.2 ms. Interval zero does
        // not tear an Android SurfaceFlinger layer; it removes only the
        // producer-side duplicate wait while the buffer queue and compositor
        // remain vsync-owned. Default/non-qualified generators retain EGL's
        // normal interval.
        if (denseV28ReducedAnalysisRequested &&
                !EGL14.eglSwapInterval(eglDisplay, 0))
            throw new IllegalStateException(
                    "qualified dense compositor requires nonblocking EGL swap");
        if (requestedEglContextMajor >= 3) {
            int[] actual = new int[1];
            GLES20.glGetIntegerv(GL_MAJOR_VERSION, actual, 0);
            actualEglContextMajor = actual[0];
            GLES20.glGetIntegerv(GL_MINOR_VERSION, actual, 0);
            actualEglContextMinor = actual[0];
            checkGl("query v31 GLES context version");
            if (actualEglContextMajor < 3)
                throw new IllegalStateException("v31 requires an actual GLES3 context");
        } else {
            actualEglContextMajor = 2;
            actualEglContextMinor = 0;
        }
    }

    private void initializeGl() {
        quad = java.nio.ByteBuffer.allocateDirect(QUAD.length * FLOAT_BYTES)
                .order(java.nio.ByteOrder.nativeOrder()).asFloatBuffer();
        quad.put(QUAD).position(0);
        copyProgram = createProgram(VERTEX_SHADER, COPY_SHADER);
        textureCopyProgram = createProgram(VERTEX_SHADER, TEXTURE_COPY_SHADER);
        signatureCompareProgram = createProgram(VERTEX_SHADER, SIGNATURE_COMPARE_SHADER);
        coarseMotionProgram = createProgram(VERTEX_SHADER, COARSE_MOTION_SHADER);
        refineMotionProgram = createProgram(VERTEX_SHADER, REFINE_MOTION_SHADER);
        regularizeMotionProgram = createProgram(VERTEX_SHADER, REGULARIZE_MOTION_SHADER);
        regionalCoarseCandidateProgram = createProgram(
                VERTEX_SHADER, REGIONAL_COARSE_CANDIDATE_SHADER);
        regionalFineCandidateProgram = createProgram(
                VERTEX_SHADER, REGIONAL_FINE_CANDIDATE_SHADER);
        regionalCandidateWinnerProgram = createProgram(
                VERTEX_SHADER, REGIONAL_CANDIDATE_WINNER_SHADER);
        globalMotionProgram = createProgram(VERTEX_SHADER, GLOBAL_MOTION_REDUCTION_SHADER);
        interpolateProgram = createProgram(VERTEX_SHADER, MOTION_INTERPOLATE_SHADER);
        predictionProofProgram = createProgram(
                VERTEX_SHADER, MOTION_PREDICTION_PROOF_SHADER);
        flowProofProgram = createProgram(VERTEX_SHADER, FLOW_PROOF_SHADER);
        int[] id = new int[1];
        GLES20.glGenTextures(1, id, 0);
        externalTexture = id[0];
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, externalTexture);
        textureParameters(GLES11Ext.GL_TEXTURE_EXTERNAL_OES);
        GLES20.glGenTextures(2, historyTextures, 0);
        GLES20.glGenTextures(SIGNATURE_CANDIDATE_SLOTS,
                signatureCandidateTextures, 0);
        GLES20.glGenTextures(ENDPOINT_FIFO_CAPACITY, endpointFifoTextures, 0);
        GLES20.glGenTextures(3, flowTextures, 0);
        GLES20.glGenTextures(3, reverseFlowTextures, 0);
        GLES20.glGenTextures(2, globalCandidateTextures, 0);
        GLES20.glGenTextures(2, globalCandidateWinnerTextures, 0);
        GLES20.glGenTextures(2, globalFlowTextures, 0);
        GLES20.glGenTextures(1, id, 0);
        latestTexture = id[0];
        GLES20.glGenTextures(1, id, 0);
        proofTexture = id[0];
        GLES20.glGenTextures(1, id, 0);
        proofAtlasTexture = id[0];
        GLES20.glGenTextures(1, id, 0);
        signatureTexture = id[0];
        GLES20.glGenTextures(1, id, 0);
        signaturePreviousTexture = id[0];
        GLES20.glGenTextures(1, id, 0);
        signatureQueryTexture = id[0];
        GLES20.glGenFramebuffers(1, id, 0);
        frameBuffer = id[0];
        allocateHistoryTextures(inputWidth, inputHeight);
        checkGl("initialize");
    }

    private void allocateHistoryTextures(int width, int height) {
        historyWidth = width;
        historyHeight = height;
        float flowLimit = flowLimitPixels(width, height);
        Log.i(TAG, "Motion bounds generator=" + generatorId +
                " role=" + displayRole + " displayId=" + displayId +
                " source=" + width + "x" + height +
                " maxFlowPixels=" + flowLimit +
                " maxFlowFraction=" +
                (flowLimit / Math.max(1f, Math.min(width, height))));
        int[] coreTextures = {historyTextures[0], historyTextures[1], latestTexture};
        for (int texture : coreTextures) {
            if (texture == 0) continue;
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
            textureParameters(GLES20.GL_TEXTURE_2D);
            GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D, 0, GLES20.GL_RGBA,
                    width, height, 0, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, null);
        }
        for (int texture : signatureCandidateTextures)
            allocateEndpointTexture(texture, width, height);
        for (int texture : endpointFifoTextures)
            allocateEndpointTexture(texture, width, height);
        resetEndpointFifo();
        int shorterSide = Math.min(width, height);
        int coarseDivisor = shorterSide >= HIGH_RES_FLOW_THRESHOLD ?
                HIGH_RES_COARSE_FLOW_DIVISOR : LOW_RES_COARSE_FLOW_DIVISOR;
        int fineDivisor = shorterSide >= HIGH_RES_FLOW_THRESHOLD ?
                HIGH_RES_FINE_FLOW_DIVISOR : LOW_RES_FINE_FLOW_DIVISOR;
        coarseFlowWidth = Math.max(1, width / coarseDivisor);
        coarseFlowHeight = Math.max(1, height / coarseDivisor);
        fineFlowWidth = Math.max(1, width / fineDivisor);
        fineFlowHeight = Math.max(1, height / fineDivisor);
        Log.i(TAG, "Motion grid generator=" + generatorId +
                " source=" + width + "x" + height +
                " coarse=" + coarseFlowWidth + "x" + coarseFlowHeight +
                " fine=" + fineFlowWidth + "x" + fineFlowHeight +
                " coarseDivisor=" + coarseDivisor +
                " fineDivisor=" + fineDivisor);
        allocateTexture(flowTextures[0], coarseFlowWidth, coarseFlowHeight);
        allocateTexture(flowTextures[1], fineFlowWidth, fineFlowHeight);
        allocateTexture(flowTextures[2], fineFlowWidth, fineFlowHeight);
        allocateTexture(reverseFlowTextures[0], coarseFlowWidth, coarseFlowHeight);
        allocateTexture(reverseFlowTextures[1], fineFlowWidth, fineFlowHeight);
        allocateTexture(reverseFlowTextures[2], fineFlowWidth, fineFlowHeight);
        allocateTexture(globalCandidateTextures[0],
                REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
        allocateTexture(globalCandidateTextures[1],
                REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
        allocateTexture(globalCandidateWinnerTextures[0],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        allocateTexture(globalCandidateWinnerTextures[1],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        allocateTexture(globalFlowTextures[0],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        allocateTexture(globalFlowTextures[1],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        allocateTexture(proofTexture, PROOF_WIDTH, PROOF_HEIGHT);
        // Qualification signatures have fixed 16x9 storage. Once the dense
        // arm has replaced these with explicit RGBA8_OES, a source resize
        // must not silently downgrade them through the generic ES2 allocator.
        if (!denseResourcesReady) {
            allocateTexture(signatureTexture, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
            allocateTexture(signaturePreviousTexture, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
            allocateTexture(signatureQueryTexture, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
            setSignatureTextureSampling(signatureTexture);
            setSignatureTextureSampling(signaturePreviousTexture);
            setSignatureTextureSampling(signatureQueryTexture);
        }
        proofPixels = java.nio.ByteBuffer.allocateDirect(PROOF_WIDTH * PROOF_HEIGHT * 4)
                .order(java.nio.ByteOrder.nativeOrder());
        signaturePixels = java.nio.ByteBuffer.allocateDirect(
                SIGNATURE_WIDTH * SIGNATURE_HEIGHT * 4)
                .order(java.nio.ByteOrder.nativeOrder());
        regionalFlowPixels = java.nio.ByteBuffer.allocateDirect(
                REGIONAL_FLOW_CELLS * 4)
                .order(java.nio.ByteOrder.nativeOrder());
        sourceSignatureReady = false;
        denseSignatureBaselineReady = false;
        denseSignatureSequence = 0;
        denseSignatureReady = 0;
        denseSignatureUnavailable = 0;
        denseSignatureMaxQueueAge = 0;
        clearMotionField(flowTextures[0], coarseFlowWidth, coarseFlowHeight);
        clearMotionField(flowTextures[1], fineFlowWidth, fineFlowHeight);
        clearMotionField(flowTextures[2], fineFlowWidth, fineFlowHeight);
        clearMotionField(reverseFlowTextures[0], coarseFlowWidth, coarseFlowHeight);
        clearMotionField(reverseFlowTextures[1], fineFlowWidth, fineFlowHeight);
        clearMotionField(reverseFlowTextures[2], fineFlowWidth, fineFlowHeight);
        clearMotionField(globalCandidateTextures[0],
                REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
        clearMotionField(globalCandidateTextures[1],
                REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
        clearMotionField(globalCandidateWinnerTextures[0],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        clearMotionField(globalCandidateWinnerTextures[1],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        clearMotionField(globalFlowTextures[0],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        clearMotionField(globalFlowTextures[1],
                REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        if (denseResourcesReady) allocateDenseResources();
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, 0);
    }

    private void allocateTexture(int texture, int width, int height) {
        if (texture == 0) return;
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
        textureParameters(GLES20.GL_TEXTURE_2D);
        GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D, 0, GLES20.GL_RGBA,
                width, height, 0, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, null);
    }

    private void allocateEndpointTexture(int texture, int width, int height) {
        allocateTexture(texture, width, height);
    }

    private void setSignatureTextureSampling(int texture) {
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER,
                GLES20.GL_NEAREST);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER,
                GLES20.GL_NEAREST);
    }

    private void clearMotionField(int texture, int width, int height) {
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, texture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE) fail("motion framebuffer incomplete");
        GLES20.glViewport(0, 0, width, height);
        // RG=0.5 decodes to zero displacement; B=0 is no confidence.
        GLES20.glClearColor(0.5f, 0.5f, 0f, 1f);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
    }

    private void uploadSoftwareFrame(int[] colors, int width, int height, float aspect,
                                     long producerTimestampNs) {
        if (closed.get()) return;
        if (historyWidth != width || historyHeight != height) {
            if (densePyramidEnabled || denseGpuTimer != null)
                teardownDenseEpoch("software-stream-resize");
            densePyramidEnabled = false;
            denseResourcesReady = false;
            allocateHistoryTextures(width, height);
            sourceSignatureReady = false;
            frameRate.resetPresentation();
            resetHealthWindowAfterStreamChange();
        }
        if (softwareUploadBitmap == null || softwareUploadBitmap.getWidth() != width ||
                softwareUploadBitmap.getHeight() != height) {
            if (softwareUploadBitmap != null) softwareUploadBitmap.recycle();
            softwareUploadBitmap = android.graphics.Bitmap.createBitmap(
                    width, height, android.graphics.Bitmap.Config.ARGB_8888);
        }
        softwareUploadBitmap.setPixels(colors, 0, width, 0, 0, width, height);
        uploadBitmap(latestTexture);
        presentationAspect = aspect;
        ++submittedFrameCount;
        if (frameRate.usesAuthoritativeSourceRate() ||
                softwareImageIsUnique(colors, width, height))
            observeUniqueFrame(producerTimestampNs, submittedFrameCount);
        if (selectPresentationEndpoint(producerTimestampNs))
            acceptPresentationEndpoint(latestTexture,
                    presentationEndpointSelector.selectedTimestampNs());
    }

    private void uploadBitmap(int texture) {
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
        GLUtils.texSubImage2D(GLES20.GL_TEXTURE_2D, 0, 0, 0, softwareUploadBitmap);
        checkGl("upload software frame");
    }

    /**
     * Fingerprints the actual rendered image, not the producer callback.
     * Several emulators submit the same 30-FPS image twice on a 60-Hz video
     * interface; counting both makes the source badge and interpolation ratio
     * fictitious. A tiny 16x9 GPU signature is enough to reject exact repeats
     * without reading the full framebuffer back to the CPU.
     */
    private boolean latestImageIsUnique(long currentTimestampNs) {
        classifiedUniqueTexture = 0;
        classifiedUniqueTimestampNs = 0L;
        long denseWallStart = densePyramidEnabled ? System.nanoTime() : 0L;
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                signatureTexture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("source signature framebuffer incomplete");
        GLES20.glViewport(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
        drawTexture2d(latestTexture);
        if (densePyramidEnabled && denseV28ReducedAnalysisRequested) {
            try {
                int capability = denseSignatureCapability();
                if (denseGpuTimer == null || !denseGpuTimer.signatureSupported() ||
                        capability != DENSE_SIGNATURE_CAP_READY)
                    throw new IllegalStateException("asynchronous signature unavailable" +
                            " capability=0x" + Integer.toHexString(capability));
                if (!denseSignatureBaselineReady) {
                    copyCurrentSignatureToPrevious();
                    denseSignatureBaselineReady = true;
                    classifiedUniqueTexture = latestTexture;
                    classifiedUniqueTimestampNs = currentTimestampNs;
                    GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
                    GLES20.glViewport(0, 0, outputWidth, outputHeight);
                    return true;
                }
                long[] row = denseGpuTimer.pollSignature(denseSignatureSequence);
                if (row.length != 0 && row.length != DenseGpuTimer.SIGNATURE_RESULT_FIELDS)
                    throw new IllegalStateException("malformed asynchronous signature row");
                boolean unique = false;
                if (row.length != 0) {
                    if (row[0] != DenseGpuTimer.STATUS_OK || row[7] != 1L ||
                            row[6] < 0L || row[6] > 4L)
                        throw new IllegalStateException("invalid asynchronous signature" +
                                " status=" + row[0] + " slot=" + row[3] +
                                " query=" + row[4] + " age=" + row[6]);
                    long readySequence = row[1];
                    if (readySequence > denseSignatureSequence)
                        throw new IllegalStateException("future asynchronous signature");
                    denseSignatureMaxQueueAge = Math.max(denseSignatureMaxQueueAge,
                            denseSignatureSequence - readySequence);
                    ++denseSignatureReady;
                    unique = row[2] == 1L;
                    int candidate = findSignatureCandidate(readySequence);
                    if (candidate < 0)
                        throw new IllegalStateException(
                                "signature result has no retained endpoint sequence=" +
                                        readySequence);
                    if (unique)
                        observeUniqueFrame(signatureCandidateTimestampNs[candidate],
                                signatureCandidateSubmission[candidate]);
                    signatureCandidateSequence[candidate] = 0L;
                    signatureCandidateTimestampNs[candidate] = 0L;
                    signatureCandidateSubmission[candidate] = 0;
                }
                long sequence = ++denseSignatureSequence;
                retainSignatureCandidate(sequence, currentTimestampNs);
                GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
                GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                        GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                        signatureQueryTexture, 0);
                if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                        GLES20.GL_FRAMEBUFFER_COMPLETE)
                    throw new IllegalStateException("signature query framebuffer incomplete");
                GLES20.glViewport(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
                drawSignatureDifferenceQuery(sequence);
                copyCurrentSignatureToPrevious();
                GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
                GLES20.glViewport(0, 0, outputWidth, outputHeight);
                checkGl("asynchronous source signature");
                if (denseWallStart != 0L)
                    recordDenseWall(DENSE_WALL_SIGNATURE,
                            System.nanoTime() - denseWallStart);
                // A delayed unique result was committed above while its exact
                // retained texture was still intact. The current image is only
                // a query candidate and must never be accepted by that old bit.
                return false;
            } catch (RuntimeException failure) {
                ++denseSignatureUnavailable;
                rejectDense("async-signature-failure", failure);
                clearSignatureCandidates();
                // Fall through to the exact synchronous v22 signature for
                // this same producer image. A failed qualification arm may
                // never invent or discard a real source frame.
                GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
                GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                        GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                        signatureTexture, 0);
                if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                        GLES20.GL_FRAMEBUFFER_COMPLETE)
                    fail("source signature fallback framebuffer incomplete");
                GLES20.glViewport(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
                drawTexture2d(latestTexture);
            }
        }
        signaturePixels.position(0);
        GLES20.glReadPixels(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT,
                GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, signaturePixels);
        for (int index = 0; index < currentSourceSignature.length; ++index)
            currentSourceSignature[index] = signaturePixels.get(index);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        GLES20.glViewport(0, 0, outputWidth, outputHeight);
        checkGl("source signature");
        if (denseWallStart != 0L)
            recordDenseWall(DENSE_WALL_SIGNATURE,
                    System.nanoTime() - denseWallStart);
        boolean unique = sourceSignatureIsUnique();
        if (unique) {
            classifiedUniqueTexture = latestTexture;
            classifiedUniqueTimestampNs = currentTimestampNs;
        }
        return unique;
    }

    private void copyCurrentSignatureToPrevious() {
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                signaturePreviousTexture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("previous signature framebuffer incomplete");
        GLES20.glViewport(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
        drawTexture2d(signatureTexture);
    }

    private void drawSignatureDifferenceQuery(long sequence) {
        boolean scissor = GLES20.glIsEnabled(GLES20.GL_SCISSOR_TEST);
        boolean depth = GLES20.glIsEnabled(GLES20.GL_DEPTH_TEST);
        boolean stencil = GLES20.glIsEnabled(GLES20.GL_STENCIL_TEST);
        boolean cull = GLES20.glIsEnabled(GLES20.GL_CULL_FACE);
        GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
        GLES20.glDisable(GLES20.GL_DEPTH_TEST);
        GLES20.glDisable(GLES20.GL_STENCIL_TEST);
        GLES20.glDisable(GLES20.GL_CULL_FACE);
        boolean begun = false;
        try {
            if (!denseGpuTimer.beginSignature(sequence))
                throw new IllegalStateException("asynchronous signature ring full");
            begun = true;
            GLES20.glUseProgram(signatureCompareProgram);
            bindQuad(signatureCompareProgram);
            bindTexture(signatureCompareProgram, "uCurrent", signatureTexture, 0);
            bindTexture(signatureCompareProgram, "uPrevious", signaturePreviousTexture, 1);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        } finally {
            try {
                if (begun) denseGpuTimer.endSignature();
            } finally {
                if (scissor) GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
                if (depth) GLES20.glEnable(GLES20.GL_DEPTH_TEST);
                if (stencil) GLES20.glEnable(GLES20.GL_STENCIL_TEST);
                if (cull) GLES20.glEnable(GLES20.GL_CULL_FACE);
            }
        }
    }

    private boolean softwareImageIsUnique(int[] colors, int width, int height) {
        int offset = 0;
        for (int y = 0; y < SIGNATURE_HEIGHT; ++y) {
            int sourceY = Math.min(height - 1,
                    (2 * y + 1) * height / (2 * SIGNATURE_HEIGHT));
            for (int x = 0; x < SIGNATURE_WIDTH; ++x) {
                int sourceX = Math.min(width - 1,
                        (2 * x + 1) * width / (2 * SIGNATURE_WIDTH));
                int color = colors[sourceY * width + sourceX];
                currentSourceSignature[offset++] = (byte) ((color >>> 16) & 0xff);
                currentSourceSignature[offset++] = (byte) ((color >>> 8) & 0xff);
                currentSourceSignature[offset++] = (byte) (color & 0xff);
                currentSourceSignature[offset++] = (byte) ((color >>> 24) & 0xff);
            }
        }
        return sourceSignatureIsUnique();
    }

    private boolean sourceSignatureIsUnique() {
        int changedPixels = 0;
        int totalDifference = 0;
        for (int offset = 0; offset < currentSourceSignature.length; offset += 4) {
            int difference = 0;
            for (int channel = 0; channel < 3; ++channel)
                difference += Math.abs((currentSourceSignature[offset + channel] & 0xff) -
                        (lastSourceSignature[offset + channel] & 0xff));
            totalDifference += difference;
            if (difference >= 3) ++changedPixels;
        }
        boolean unique = !sourceSignatureReady || changedPixels >= 1 ||
                totalDifference >= 16;
        if (unique) {
            System.arraycopy(currentSourceSignature, 0, lastSourceSignature, 0,
                    currentSourceSignature.length);
            sourceSignatureReady = true;
        }
        return unique;
    }

    private int findSignatureCandidate(long sequence) {
        for (int slot = 0; slot < SIGNATURE_CANDIDATE_SLOTS; ++slot)
            if (signatureCandidateSequence[slot] == sequence) return slot;
        return -1;
    }

    private void retainSignatureCandidate(long sequence, long timestampNs) {
        int slot = -1;
        for (int index = 0; index < SIGNATURE_CANDIDATE_SLOTS; ++index) {
            if (signatureCandidateSequence[index] == 0L) {
                slot = index;
                break;
            }
        }
        if (slot < 0) {
            ++endpointCandidateUnavailable;
            throw new IllegalStateException("signature endpoint texture ring full");
        }
        copyTexture(latestTexture, signatureCandidateTextures[slot]);
        signatureCandidateSequence[slot] = sequence;
        signatureCandidateTimestampNs[slot] = timestampNs;
        signatureCandidateSubmission[slot] = submittedFrameCount;
    }

    private void clearSignatureCandidates() {
        java.util.Arrays.fill(signatureCandidateSequence, 0L);
        java.util.Arrays.fill(signatureCandidateTimestampNs, 0L);
        java.util.Arrays.fill(signatureCandidateSubmission, 0);
    }

    /** Records a pixel-distinct image solely as source-rate evidence. */
    private void observeUniqueFrame(long timestampNs, int submissionOrdinal) {
        long normalizedTimestamp = timestampNs;
        if (normalizedTimestamp <= lastProducerTimestampNs) {
            // Arrival timestamps are captured from System.nanoTime on the
            // owning Handler. Retain a fail-closed correction in case a future
            // producer path supplies a broken/non-monotonic value.
            normalizedTimestamp = Math.max(lastProducerTimestampNs + 1L,
                    System.nanoTime());
            ++endpointCandidateUnavailable;
            ++endpointTimestampCorrections;
        }
        lastProducerTimestampNs = normalizedTimestamp;
        ++uniqueFrameCount;
        lastUniqueSubmissionCount = Math.max(lastUniqueSubmissionCount,
                submissionOrdinal);
        frameRate.onProducerFrame(normalizedTimestamp, submissionOrdinal);
    }

    /**
     * Samples the emulator callback clock at the measured source tier. Exact
     * repeated pixels are valid timing endpoints once the tier has been
     * measured: retaining them keeps a static or lightly animated scene from
     * destroying the FIFO, while observeUniqueFrame remains the only input to
     * source-tier decisions. The scheduled deadline never catches up after a
     * pause; at most one endpoint is retained per producer callback.
     */
    private boolean selectPresentationEndpoint(long timestampNs) {
        int sourceFps = frameRate.presentationSourceFps();
        boolean scheduled = presentationEndpointSelector.select(timestampNs,
                sourceFps);
        if (scheduled) return true;
        // Only a proven top-tier callback stream can refill from an otherwise
        // discarded callback. Lower tiers deliberately decimate a 60-Hz core
        // interface to their measured unique cadence and must not be promoted
        // by this jitter buffer.
        return sourceFps == 60 &&
                endpointFifoCount < ENDPOINT_FIFO_JITTER_RESERVE;
    }

    /** Enqueues one selected temporal endpoint for visible presentation. */
    private void acceptPresentationEndpoint(int sourceTexture, long timestampNs) {
        if (sourceTexture == 0) return;
        long normalizedTimestamp = timestampNs;
        if (normalizedTimestamp <= lastPresentationEndpointTimestampNs) {
            normalizedTimestamp = Math.max(
                    lastPresentationEndpointTimestampNs + 1L,
                    System.nanoTime());
            ++endpointCandidateUnavailable;
            ++endpointTimestampCorrections;
        }
        lastPresentationEndpointTimestampNs = normalizedTimestamp;
        ++endpointSequence;
        ++realFrameCount;

        int slot;
        if (endpointFifoCount < ENDPOINT_FIFO_CAPACITY) {
            slot = (endpointFifoHead + endpointFifoCount) % ENDPOINT_FIFO_CAPACITY;
            ++endpointFifoCount;
        } else {
            // The producer has outrun the committed presentation timeline.
            // None of these queued textures is active, so discard the stale
            // backlog and retain only the newest endpoint. Its global source
            // sequence intentionally exposes the discontinuity; preparation
            // waits for sequence+1 and re-primes from that exact adjacent pair.
            // Replacing just the prior tail would leave a permanent hole that
            // repeatedly tears down otherwise healthy pairs.
            ++endpointFifoCoalesced;
            endpointFifoHead = 0;
            endpointFifoCount = 1;
            java.util.Arrays.fill(endpointFifoSequence, 0L);
            java.util.Arrays.fill(endpointFifoTimestampNs, 0L);
            slot = 0;
        }
        copyTexture(sourceTexture, endpointFifoTextures[slot]);
        endpointFifoSequence[slot] = endpointSequence;
        endpointFifoTimestampNs[slot] = normalizedTimestamp;
    }

    private void resetEndpointFifo() {
        endpointFifoHead = 0;
        endpointFifoCount = 0;
        activeLeftSequence = 0L;
        activeRightSequence = 0L;
        activeLeftTimestampNs = 0L;
        activeRightTimestampNs = 0L;
        activePairReady = false;
        activePairSyntheticCommitted = false;
        lastPromotedEndpointSequence = 0L;
        bufferedPairCreatedCount = 0L;
        bufferedSyntheticSelectedCount = 0L;
        bufferedSyntheticQuotaSkippedCount = 0L;
        bufferedSyntheticNotReadyCount = 0L;
        bufferedPresentationCallbackCount = 0L;
        bufferedLastSelectedSyntheticPair = 0L;
        lastPresentationEndpointTimestampNs = 0L;
        presentationEndpointSelector.reset();
        java.util.Arrays.fill(endpointFifoSequence, 0L);
        java.util.Arrays.fill(endpointFifoTimestampNs, 0L);
        clearSignatureCandidates();
    }

    private int endpointFifoSlot(int offset) {
        return (endpointFifoHead + offset) % ENDPOINT_FIFO_CAPACITY;
    }

    private void discardEndpointFifoHead() {
        if (endpointFifoCount <= 0) return;
        int slot = endpointFifoHead;
        endpointFifoSequence[slot] = 0L;
        endpointFifoTimestampNs[slot] = 0L;
        endpointFifoHead = (endpointFifoHead + 1) % ENDPOINT_FIFO_CAPACITY;
        --endpointFifoCount;
    }

    private void consumeEndpointIntoHistory(int historyIndex, boolean left) {
        if (endpointFifoCount <= 0)
            throw new IllegalStateException("endpoint FIFO underflow");
        int slot = endpointFifoHead;
        long sequence = endpointFifoSequence[slot];
        long timestampNs = endpointFifoTimestampNs[slot];
        if (sequence <= 0L)
            throw new IllegalStateException("endpoint FIFO sequence missing");
        if (timestampNs <= 0L)
            throw new IllegalStateException("endpoint FIFO timestamp missing");
        copyTexture(endpointFifoTextures[slot], historyTextures[historyIndex]);
        endpointFifoSequence[slot] = 0L;
        endpointFifoTimestampNs[slot] = 0L;
        endpointFifoHead = (endpointFifoHead + 1) % ENDPOINT_FIFO_CAPACITY;
        --endpointFifoCount;
        if (left) {
            activeLeftSequence = sequence;
            activeLeftTimestampNs = timestampNs;
        } else {
            activeRightSequence = sequence;
            activeRightTimestampNs = timestampNs;
        }
    }

    /**
     * Materializes the exact adjacent endpoint pair consumed by the buffered
     * scheduler. Producer callbacks only append retained textures; they never
     * overwrite either history texture while it owns a visible timeline.
     */
    private void prepareBufferedPairIfPossible() {
        if (activeLeftSequence == 0L) {
            // A prior overflow or source discontinuity may leave one orphan at
            // the head. Drop only endpoints that provably cannot form an exact
            // adjacent pair with their successor; never estimate across them.
            while (endpointFifoCount >= 2) {
                int leftSlot = endpointFifoSlot(0);
                int rightSlot = endpointFifoSlot(1);
                long left = endpointFifoSequence[leftSlot];
                long right = endpointFifoSequence[rightSlot];
                if (left > 0L && right == left + 1L &&
                        AdaptiveFrameRateController.endpointSpanContinuous(
                                endpointFifoTimestampNs[leftSlot],
                                endpointFifoTimestampNs[rightSlot],
                                frameRate.lockedSourceFps())) break;
                discardEndpointFifoHead();
            }
            // Prime only after three complete source intervals are retained.
            // Presentation endpoints are sampled from the emulator callback
            // clock, not only pixel changes, so a static/menu image still
            // supplies these timestamped endpoints. Two queued successors
            // absorb one full interval of delayed asynchronous classification
            // without exposing a scheduled REAL or SYNTHETIC slot.
            if (endpointFifoCount < ENDPOINT_FIFO_PRIME_DEPTH) return;
            previousIndex = 0;
            currentIndex = 1;
            copyBufferedEndpoints(true);
            return;
        }
        if (activeRightSequence == 0L && endpointFifoCount > 0) {
            long next = endpointFifoSequence[endpointFifoHead];
            long nextTimestampNs = endpointFifoTimestampNs[endpointFifoHead];
            if (next != activeLeftSequence + 1L ||
                    !AdaptiveFrameRateController.endpointSpanContinuous(
                            activeLeftTimestampNs, nextTimestampNs,
                            frameRate.lockedSourceFps())) {
                // The queued timeline skipped at least one accepted source
                // image. Keep those newer textures intact, abandon the old
                // active endpoint, and re-prime from the first adjacent pair.
                // resetPresentation prevents an arrival-driven catch-up swap.
                invalidateBufferedPairForReprime();
                prepareBufferedPairIfPossible();
                return;
            }
            copyBufferedEndpoints(false);
        }
    }

    private void copyBufferedEndpoints(boolean initialPair) {
        motionEstimateReady = false;
        activePairReady = false;
        boolean dense = densePyramidEnabled;
        boolean denseCopyStageOpen = false;
        try {
            if (dense) {
                beginDenseStage(DenseGpuTimer.ENDPOINT_COPY);
                denseCopyStageOpen = true;
            }
            if (initialPair) {
                consumeEndpointIntoHistory(previousIndex, true);
                consumeEndpointIntoHistory(currentIndex, false);
            } else {
                consumeEndpointIntoHistory(currentIndex, false);
            }
            if (dense) {
                endDenseStage();
                denseCopyStageOpen = false;
            }
            if (activeRightSequence != activeLeftSequence + 1L)
                throw new IllegalStateException(
                        "endpoint FIFO lost adjacent sequence continuity");
            if (activeLeftTimestampNs <= 0L ||
                    !AdaptiveFrameRateController.endpointSpanContinuous(
                            activeLeftTimestampNs, activeRightTimestampNs,
                            frameRate.lockedSourceFps()))
                throw new IllegalStateException(
                        "endpoint FIFO lost timestamp continuity");
        } catch (RuntimeException copyFailure) {
            if (denseCopyStageOpen) {
                try { endDenseStage(); }
                catch (RuntimeException cleanupFailure) {
                    copyFailure.addSuppressed(cleanupFailure);
                }
            }
            if (dense) rejectDense("buffered-endpoint-copy-failure", copyFailure);
            invalidateBufferedPairForReprime();
            throw copyFailure;
        }
        try {
            if (dense) {
                try {
                    estimateDenseMotion();
                } catch (RuntimeException denseFailure) {
                    rejectDense("buffered-pair-estimator-failure", denseFailure);
                    motionEstimateReady = false;
                }
            } else if (!frameRate.generationAvailable()) {
                // A qualified dense failure has no authorized legacy visual
                // fallback. Keep the exact endpoints available for direct
                // presentation without computing or exposing old motion.
                motionEstimateReady = false;
            } else {
                estimateMotion();
            }
        } catch (RuntimeException estimateFailure) {
            invalidateBufferedPairForReprime();
            throw estimateFailure;
        }
        activePairReady = motionEstimateReady;
        activePairSyntheticCommitted = false;
        ++bufferedPairCreatedCount;
    }

    private void invalidateBufferedPairForReprime() {
        invalidateBufferedPairForReprime(true);
    }

    private void invalidateBufferedPairForReprime(boolean resetController) {
        if (activePairReady && !activePairSyntheticCommitted)
            ++bufferedSyntheticQuotaSkippedCount;
        activeLeftSequence = 0L;
        activeRightSequence = 0L;
        activeLeftTimestampNs = 0L;
        activeRightTimestampNs = 0L;
        activePairReady = false;
        activePairSyntheticCommitted = false;
        motionEstimateReady = false;
        if (resetController) frameRate.resetPresentation();
    }

    private void recordPromotedEndpoint(long sequence) {
        if (sequence <= lastPromotedEndpointSequence) return;
        lastPromotedEndpointSequence = sequence;
        ++promotedFrameCount;
    }

    private boolean bufferedAdvanceWouldCrossGap(int advance) {
        if (advance != 1 || activeRightSequence != activeLeftSequence + 1L ||
                endpointFifoCount <= 0) return false;
        return endpointFifoSequence[endpointFifoHead] !=
                activeRightSequence + 1L;
    }

    /** Applies the source-position advance committed by a successful swap. */
    private void commitBufferedEndpointAdvance(int presentation, int advance) {
        if (presentation == AdaptiveFrameRateController.PRESENT_REAL)
            recordPromotedEndpoint(activeLeftSequence);
        if (advance == 0) return;
        if (advance != 1 || activeRightSequence != activeLeftSequence + 1L)
            throw new IllegalStateException("invalid buffered endpoint advance");
        recordPromotedEndpoint(activeRightSequence);
        int reuse = previousIndex;
        previousIndex = currentIndex;
        currentIndex = reuse;
        activeLeftSequence = activeRightSequence;
        activeLeftTimestampNs = activeRightTimestampNs;
        activeRightSequence = 0L;
        activeRightTimestampNs = 0L;
        activePairReady = false;
        activePairSyntheticCommitted = false;
        motionEstimateReady = false;
        prepareBufferedPairIfPossible();
    }

    private void promoteLatestTexture() {
        if (promotedFrameCount == 0) {
            copyTexture(latestTexture, historyTextures[0]);
            copyTexture(latestTexture, historyTextures[1]);
            previousIndex = 0;
            currentIndex = 1;
            clearMotionField(flowTextures[0], coarseFlowWidth, coarseFlowHeight);
            clearMotionField(flowTextures[1], fineFlowWidth, fineFlowHeight);
            clearMotionField(flowTextures[2], fineFlowWidth, fineFlowHeight);
            clearMotionField(reverseFlowTextures[0], coarseFlowWidth, coarseFlowHeight);
            clearMotionField(reverseFlowTextures[1], fineFlowWidth, fineFlowHeight);
            clearMotionField(reverseFlowTextures[2], fineFlowWidth, fineFlowHeight);
            clearMotionField(globalCandidateTextures[0],
                    REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
            clearMotionField(globalCandidateTextures[1],
                    REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
            clearMotionField(globalCandidateWinnerTextures[0],
                    REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
            clearMotionField(globalCandidateWinnerTextures[1],
                    REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
            clearMotionField(globalFlowTextures[0],
                    REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
            clearMotionField(globalFlowTextures[1],
                    REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        } else {
            int reuse = previousIndex;
            previousIndex = currentIndex;
            currentIndex = reuse;
            motionEstimateReady = false;
            if (densePyramidEnabled) {
                boolean endpointCopied = false;
                try {
                    beginDenseStage(DenseGpuTimer.ENDPOINT_COPY);
                    copyTexture(latestTexture, historyTextures[currentIndex]);
                    endDenseStage();
                    endpointCopied = true;
                    estimateDenseMotion();
                } catch (RuntimeException failure) {
                    rejectDense("timer-or-estimator-failure", failure);
                    if (!endpointCopied)
                        copyTexture(latestTexture, historyTextures[currentIndex]);
                    estimateMotion();
                }
            } else {
                copyTexture(latestTexture, historyTextures[currentIndex]);
                estimateMotion();
            }
        }
        ++promotedFrameCount;
    }

    /** Builds independently measured current-to-previous and previous-to-current fields. */
    private void estimateMotion() {
        estimateMotionPass(historyTextures[previousIndex],
                historyTextures[currentIndex], flowTextures,
                globalCandidateTextures[0], globalCandidateWinnerTextures[0],
                globalFlowTextures[0]);
        estimateMotionPass(historyTextures[currentIndex],
                historyTextures[previousIndex], reverseFlowTextures,
                globalCandidateTextures[1], globalCandidateWinnerTextures[1],
                globalFlowTextures[1]);
        checkGl("estimate bidirectional motion");
        motionEstimateReady = true;
    }

    /**
     * Binds the persistent Java/GL atlas resources to the current native timer
     * epoch.  Dense textures and shaders survive a qualification toggle, but
     * teardownDenseEpoch() deliberately destroys the native timer and its PBO
     * ring.  A newly-created timer therefore needs its own atlas configuration
     * even when denseResourcesReady is already true.
     */
    private void ensureProofAtlasTimerConfigured() {
        if (denseGpuTimer == null)
            throw new IllegalStateException("proof atlas requires a live dense timer");
        int capability = denseGpuTimer.proofAtlasCapability();
        if ((capability & 15) == 15) return;
        capability = denseGpuTimer.configureProofAtlas(
                PROOF_ATLAS_WIDTH, PROOF_ATLAS_HEIGHT, PROOF_ATLAS_BYTES,
                PROOF_ATLAS_RING_SIZE);
        if ((capability & 15) != 15)
            throw new IllegalStateException(
                    "v32 proof atlas PBO/fence configuration unavailable cap=" +
                    capability);
    }

    private void ensureDenseResources() {
        if (denseResourcesReady) {
            ensureProofAtlasTimerConfigured();
            return;
        }
        try {
            if (denseV28ReducedAnalysisRequested &&
                    (requestedEglContextMajor != 3 || actualEglContextMajor < 3))
                throw new IllegalStateException(
                        "v31 dense qualification requires the immutable GLES3 context");
            String extensions = GLES20.glGetString(GLES20.GL_EXTENSIONS);
            int[] range = new int[2];
            int[] precision = new int[1];
            GLES20.glGetShaderPrecisionFormat(GLES20.GL_FRAGMENT_SHADER,
                    GLES20.GL_HIGH_FLOAT, range, 0, precision, 0);
            if (extensions == null || !extensions.contains("GL_OES_rgb8_rgba8") ||
                    precision[0] < 16)
                throw new IllegalStateException("dense qualification requires RGBA8_OES and fragment highp");
            allocateSignatureQualificationTexture(signatureTexture);
            allocateSignatureQualificationTexture(signaturePreviousTexture);
            allocateSignatureQualificationTexture(signatureQueryTexture);
            densePyramidProgram = createProgram(VERTEX_SHADER, DENSE_PYRAMID_SHADER);
            denseSolveProgram = createProgram(VERTEX_SHADER, DENSE_SOLVE_SHADER);
            denseCycleProgram = createProgram(VERTEX_SHADER, DENSE_CYCLE_SHADER);
            denseQ8ProbeProgram = createProgram(VERTEX_SHADER, DENSE_Q8_PROBE_SHADER);
            proofAtlasHeaderProgram = createProgram(VERTEX_SHADER,
                    PROOF_ATLAS_HEADER_SHADER);
            denseDiagnosticPackProgram = createProgram(VERTEX_SHADER,
                    DENSE_DIAGNOSTIC_PACK_SHADER);
            for (int direction = 0; direction < 2; ++direction) {
                for (int level = 0; level < DENSE_LEVELS; ++level)
                    GLES20.glGenTextures(2, denseFlowTextures[direction][level], 0);
                GLES20.glGenTextures(2, densePyramidTextures[direction], 0);
            }
            GLES20.glGenTextures(2, denseValidatedTextures, 0);
            allocateDenseResources();
            validateDenseByteContract();
            validateDenseQ8ShaderContract();
            denseProofPixels = java.nio.ByteBuffer.allocateDirect(PROOF_WIDTH * PROOF_HEIGHT * 4)
                    .order(java.nio.ByteOrder.nativeOrder());
            allocateDenseTexture(proofAtlasTexture, PROOF_ATLAS_WIDTH,
                    PROOF_ATLAS_HEIGHT, true);
            proofAtlasPixels = java.nio.ByteBuffer.allocateDirect(PROOF_ATLAS_BYTES)
                    .order(java.nio.ByteOrder.LITTLE_ENDIAN);
            proofAtlasHeader = java.nio.ByteBuffer.allocateDirect(PROOF_ATLAS_HEADER_BYTES)
                    .order(java.nio.ByteOrder.LITTLE_ENDIAN);
            ensureProofAtlasTimerConfigured();
            denseResourcesReady = true;
            Log.i(TAG, "Dense pyramid resources ready generator=" + generatorId +
                    " variant=" + denseVariant() +
                    " analysis=" + denseAnalysisWidth + "x" + denseAnalysisHeight +
                    " passesPerPromotion=" + DENSE_PASSES_PER_PROMOTION +
                    " solveTexelsPerPromotion=" + denseSolveTexelsPerPromotion() +
                    " totalTexelsPerPromotion=" + denseTotalTexelsPerPromotion() +
                    " maxFlowPixels=" + DENSE_MAX_FLOW_PIXELS +
                    " requestedGles=" + requestedEglContextMajor +
                    " actualGles=" + actualEglContextMajor + "." +
                    actualEglContextMinor +
                    " proofContract=" + denseProofContract());
        } finally {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
        }
    }

    private void allocateDenseResources() {
        int maxWidth = denseV28ReducedAnalysisRequested ?
                DENSE_V28_ANALYSIS_MAX_WIDTH : denseV27ReducedAnalysisRequested ?
                DENSE_V27_ANALYSIS_MAX_WIDTH : DENSE_V26_ANALYSIS_MAX_WIDTH;
        int maxHeight = denseV28ReducedAnalysisRequested ?
                DENSE_V28_ANALYSIS_MAX_HEIGHT : denseV27ReducedAnalysisRequested ?
                DENSE_V27_ANALYSIS_MAX_HEIGHT : DENSE_V26_ANALYSIS_MAX_HEIGHT;
        float scale = Math.min(1f, Math.min(
                maxWidth / Math.max(1f, historyWidth),
                maxHeight / Math.max(1f, historyHeight)));
        denseAnalysisWidth = Math.max(4, Math.round(historyWidth * scale));
        denseAnalysisHeight = Math.max(4, Math.round(historyHeight * scale));
        // The offline verifier validates the analysis grid against the exact
        // history dimensions it derived from. Streams whose surfaces resize
        // after attach (DS lower screen) made attach-record-based expectation
        // impossible, so the allocation identity is logged verbatim.
        Log.i(TAG, "Frame generator dense-allocated generator=" + generatorId +
                " role=" + displayRole +
                " displayId=" + displayId +
                " history=" + historyWidth + "x" + historyHeight +
                " analysis=" + denseAnalysisWidth + "x" + denseAnalysisHeight);
        denseLevelWidths[0] = denseAnalysisWidth;
        denseLevelHeights[0] = denseAnalysisHeight;
        for (int level = 1; level < DENSE_LEVELS; ++level) {
            denseLevelWidths[level] = Math.max(1, denseLevelWidths[level - 1] / 2);
            denseLevelHeights[level] = Math.max(1, denseLevelHeights[level - 1] / 2);
        }
        for (int direction = 0; direction < 2; ++direction) {
            for (int level = 0; level < DENSE_LEVELS; ++level) {
                allocateDenseTexture(denseFlowTextures[direction][level][0],
                        denseLevelWidths[level], denseLevelHeights[level], true);
                allocateDenseTexture(denseFlowTextures[direction][level][1],
                        denseLevelWidths[level], denseLevelHeights[level], true);
            }
            allocateDenseTexture(densePyramidTextures[direction][0],
                    denseLevelWidths[1], denseLevelHeights[1], false);
            allocateDenseTexture(densePyramidTextures[direction][1],
                    denseLevelWidths[2], denseLevelHeights[2], false);
            allocateDenseTexture(denseValidatedTextures[direction],
                    denseAnalysisWidth, denseAnalysisHeight, false);
        }
        clearDenseFields();
    }

    private void allocateSignatureQualificationTexture(int texture) {
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER,
                GLES20.GL_NEAREST);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER,
                GLES20.GL_NEAREST);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S,
                GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T,
                GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D, 0, GL_RGBA8_OES,
                SIGNATURE_WIDTH, SIGNATURE_HEIGHT, 0, GLES20.GL_RGBA,
                GLES20.GL_UNSIGNED_BYTE, null);
        checkGl("allocate RGBA8 signature qualification texture");
    }

    private int denseSignatureCapability() {
        int nativeCapability = denseGpuTimer == null ? 0 :
                denseGpuTimer.signatureCapability();
        return nativeCapability | (denseResourcesReady ? DENSE_SIGNATURE_CAP_RGBA8 : 0);
    }

    private void allocateDenseTexture(int texture, int width, int height, boolean nearest) {
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER,
                nearest ? GLES20.GL_NEAREST : GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER,
                nearest ? GLES20.GL_NEAREST : GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S,
                GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T,
                GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D, 0, GL_RGBA8_OES, width, height, 0,
                GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, null);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, texture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            throw new IllegalStateException("dense RGBA8 framebuffer incomplete");
    }

    private void clearDenseFields() {
        boolean dither = GLES20.glIsEnabled(GLES20.GL_DITHER);
        GLES20.glDisable(GLES20.GL_DITHER);
        try {
            for (int direction = 0; direction < 2; ++direction) {
                for (int level = 0; level < DENSE_LEVELS; ++level)
                    for (int ping = 0; ping < 2; ++ping)
                        clearTexture(denseFlowTextures[direction][level][ping],
                                denseLevelWidths[level], denseLevelHeights[level], 0f, 0f, 0f, 0f);
                clearTexture(denseValidatedTextures[direction], denseAnalysisWidth,
                        denseAnalysisHeight, 128f / 255f, 128f / 255f, 0f, 0f);
            }
        } finally {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
            if (dither) GLES20.glEnable(GLES20.GL_DITHER);
        }
    }

    private void validateDenseQ8ShaderContract() {
        boolean dither = GLES20.glIsEnabled(GLES20.GL_DITHER);
        GLES20.glDisable(GLES20.GL_DITHER);
        RuntimeException primaryFailure = null;
        try {
            int texture = denseFlowTextures[0][0][0];
            attachDenseTarget(texture, denseLevelWidths[0], denseLevelHeights[0]);
            GLES20.glUseProgram(denseQ8ProbeProgram);
            bindQuad(denseQ8ProbeProgram);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
            java.nio.ByteBuffer bytes = java.nio.ByteBuffer.allocateDirect(5 * 4);
            GLES20.glReadPixels(0, 0, 5, 1, GLES20.GL_RGBA,
                    GLES20.GL_UNSIGNED_BYTE, bytes);
            int[] signed = {-47 * 256, -256, 0, 256, 47 * 256};
            for (int pixel = 0; pixel < signed.length; ++pixel) {
                int expected = signed[pixel] & 0xffff;
                int actual = ((bytes.get(pixel * 4) & 0xff) << 8) |
                        (bytes.get(pixel * 4 + 1) & 0xff);
                if (actual != expected || (bytes.get(pixel * 4 + 2) & 0xff) != 255)
                    throw new IllegalStateException("dense Q8.8 shader round-trip mismatch");
            }
        } catch (RuntimeException failure) {
            primaryFailure = failure;
            throw failure;
        } finally {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
            if (dither) GLES20.glEnable(GLES20.GL_DITHER);
            try {
                clearDenseFields();
            } catch (RuntimeException cleanupFailure) {
                if (primaryFailure != null) primaryFailure.addSuppressed(cleanupFailure);
                else throw cleanupFailure;
            }
        }
        checkGl("validate dense Q8.8 shader contract");
    }

    private void validateDenseByteContract() {
        boolean dither = GLES20.glIsEnabled(GLES20.GL_DITHER);
        GLES20.glDisable(GLES20.GL_DITHER);
        RuntimeException primaryFailure = null;
        try {
            int texture = denseFlowTextures[0][0][0];
            attachDenseTarget(texture, denseLevelWidths[0], denseLevelHeights[0]);
            GLES20.glClearColor(0f, 127f / 255f, 128f / 255f, 1f);
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
            java.nio.ByteBuffer bytes = java.nio.ByteBuffer.allocateDirect(4);
            GLES20.glReadPixels(0, 0, 1, 1, GLES20.GL_RGBA,
                    GLES20.GL_UNSIGNED_BYTE, bytes);
            int[] expected = {0, 127, 128, 255};
            for (int channel = 0; channel < 4; ++channel) {
                if ((bytes.get(channel) & 0xff) != expected[channel])
                    throw new IllegalStateException("dense RGBA8 byte round-trip mismatch");
            }
        } catch (RuntimeException failure) {
            primaryFailure = failure;
            throw failure;
        } finally {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
            if (dither) GLES20.glEnable(GLES20.GL_DITHER);
            try {
                clearDenseFields();
            } catch (RuntimeException cleanupFailure) {
                if (primaryFailure != null) primaryFailure.addSuppressed(cleanupFailure);
                else throw cleanupFailure;
            }
        }
        checkGl("validate dense RGBA8 byte contract");
    }

    private void clearTexture(int texture, int width, int height,
                              float r, float g, float b, float a) {
        attachDenseTarget(texture, width, height);
        GLES20.glClearColor(r, g, b, a);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
    }

    private void estimateDenseMotion() {
        long start = System.nanoTime();
        boolean dither = GLES20.glIsEnabled(GLES20.GL_DITHER);
        boolean blend = GLES20.glIsEnabled(GLES20.GL_BLEND);
        boolean scissor = GLES20.glIsEnabled(GLES20.GL_SCISSOR_TEST);
        GLES20.glDisable(GLES20.GL_DITHER);
        GLES20.glDisable(GLES20.GL_BLEND);
        GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
        try {
            // Scene-cut confidence is already computed by the bidirectional
            // validation shader. Avoid the former synchronous 48x27 proof
            // readbacks in the cadence path; offline content gates still
            // reject a cut/crossfade and the visible shader falls back where
            // both directions are invalid.
            densePairMeanDifference = 0f;
            beginDenseStage(DenseGpuTimer.PYRAMID);
            buildDensePyramid(historyTextures[previousIndex], 0);
            buildDensePyramid(historyTextures[currentIndex], 1);
            endDenseStage();
            beginDenseStage(DenseGpuTimer.FORWARD_SOLVE);
            solveDenseDirection(0, historyTextures[previousIndex],
                    historyTextures[currentIndex]);
            endDenseStage();
            beginDenseStage(DenseGpuTimer.REVERSE_SOLVE);
            solveDenseDirection(1, historyTextures[currentIndex],
                    historyTextures[previousIndex]);
            // Reuse direction zero's former copy-only fine expansion draw as
            // a post-reverse closure proposal. The reverse field was solved in
            // its own image domain; this draw merely lets the forward field
            // retain a lower-cost reciprocal candidate. Pass count, search
            // reach and the independent cycle validation remain unchanged.
            refineDenseForwardFromReverse(historyTextures[previousIndex],
                    historyTextures[currentIndex]);
            endDenseStage();
            beginDenseStage(DenseGpuTimer.VALIDATION);
            validateDenseDirection(0, historyTextures[previousIndex],
                    historyTextures[currentIndex]);
            validateDenseDirection(1, historyTextures[currentIndex],
                    historyTextures[previousIndex]);
            endDenseStage();
            checkGl("estimate dense bidirectional motion");
            motionEstimateReady = true;
        } finally {
            if (dither) GLES20.glEnable(GLES20.GL_DITHER);
            if (blend) GLES20.glEnable(GLES20.GL_BLEND);
            if (scissor) GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
        }
        long submitted = System.nanoTime();
        long submitUs = Math.max(0L, (submitted - start) / 1000L);
        ++densePromotions;
        densePasses += DENSE_PASSES_PER_PROMOTION;
        denseCpuSubmitLastUs = submitUs;
        denseCpuSubmitTotalUs += submitUs;
        denseCpuSubmitMaxUs = Math.max(denseCpuSubmitMaxUs, submitUs);
        pollDenseTimers();
    }

    private void beginDenseStage(int stage) {
        long sequence = stage == DenseGpuTimer.VISIBLE_WARP ?
                denseWarpSequence + 1L : densePromotions + 1L;
        if (denseGpuTimer == null || !denseGpuTimer.begin(stage, sequence)) {
            ++denseTimerUnavailable;
            throw new IllegalStateException("dense GPU timer ring unavailable");
        }
        if (stage == DenseGpuTimer.VISIBLE_WARP) denseWarpSequence = sequence;
    }

    /**
     * One bounded intrusive startup cross-check, deliberately outside cadence
     * counters. It drains before and after a 48x27 texture-copy draw, so it
     * validates that completion is finite without contaminating per-promotion
     * timer evidence or claiming to measure the dense solver.
     */
    private void runDenseIntrusiveCalibration() {
        GLES20.glFinish();
        long start = System.nanoTime();
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D, proofTexture, 0);
        GLES20.glViewport(0, 0, PROOF_WIDTH, PROOF_HEIGHT);
        drawTexture2d(historyTextures[currentIndex]);
        GLES20.glFinish();
        checkGl("dense intrusive calibration");
        denseCalibrationUs = Math.max(1L, (System.nanoTime() - start) / 1000L);
        denseCalibrationRuns = 1;
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        GLES20.glViewport(0, 0, outputWidth, outputHeight);
    }

    private void endDenseStage() {
        if (denseGpuTimer == null)
            throw new IllegalStateException("dense GPU timer is absent");
        denseGpuTimer.end();
    }

    private void pollDenseTimers() {
        if (denseGpuTimer == null) return;
        int disjointBefore = denseGpuTimer.takeDisjointCount();
        denseTimerDisjoint += disjointBefore;
        if (disjointBefore > 0) {
            rejectDense("gpu-timer-disjoint", null);
            return;
        }
        long[] rows = denseGpuTimer.poll(densePromotions, denseWarpSequence);
        if (rows.length % DenseGpuTimer.RESULT_FIELDS != 0) {
            ++denseTimerUnavailable;
            rejectDense("malformed-timer-result", null);
            return;
        }
        for (int offset = 0; offset < rows.length;
                offset += DenseGpuTimer.RESULT_FIELDS) {
            int status = (int) rows[offset];
            long slot = rows[offset + 1];
            long queryId = rows[offset + 2];
            int stage = (int) rows[offset + 3];
            long sequence = rows[offset + 4];
            long currentPair = rows[offset + 5];
            long currentWarp = rows[offset + 6];
            long available = rows[offset + 7];
            long rawElapsedNs = rows[offset + 8];
            long queueAge = Math.max(0L, rows[offset + 9]);
            long contextOk = rows[offset + 10];
            long disjoint = rows[offset + 11];
            if (status != DenseGpuTimer.STATUS_OK || rawElapsedNs <= 0L) {
                ++denseTimerUnavailable;
                Log.e(TAG, "Dense GPU timer diagnostic generator=" + generatorId +
                        " status=" + status + " slot=" + slot +
                        " queryId=" + queryId + " stage=" + stage +
                        " sequence=" + sequence + " currentPair=" + currentPair +
                        " currentWarp=" + currentWarp + " available=" + available +
                        " rawElapsedNs=" + rawElapsedNs + " queueAge=" + queueAge +
                        " contextOk=" + contextOk + " disjoint=" + disjoint);
                rejectDense(status == DenseGpuTimer.STATUS_OK ?
                        "zero-timer-result" : "native-timer-status-" + status, null);
                return;
            }
            long elapsedUs = DenseGpuTimer.nanosecondsToMicroseconds(rawElapsedNs);
            long currentSequence = stage == DenseGpuTimer.VISIBLE_WARP ?
                    denseWarpSequence : densePromotions;
            if (stage < DenseGpuTimer.ENDPOINT_COPY || stage > DenseGpuTimer.VISIBLE_WARP ||
                    sequence <= 0L || sequence > currentSequence || elapsedUs <= 0L) {
                ++denseTimerUnavailable;
                rejectDense("invalid-timer-result", null);
                return;
            }
            denseTimerMaxQueueAge = Math.max(denseTimerMaxQueueAge, queueAge);
            if (queueAge > 64L) {
                ++denseTimerStale;
                rejectDense("stale-timer-result", null);
                return;
            }
            denseStageTotalUs[stage] += elapsedUs;
            denseStageMaxUs[stage] = Math.max(denseStageMaxUs[stage], elapsedUs);
            int sample = (int) (denseStageSamples[stage]++ & 255L);
            denseStageObservedUs[stage][sample] = elapsedUs;
            if (elapsedUs > DENSE_GPU_BUDGET_US) {
                rejectDense("async-gpu-stage-over-budget", null);
                return;
            }
            // Visible presentation is not part of one endpoint estimator. It
            // has an independent monotonic sequence because zero, one, or
            // multiple generated warps can consume the same endpoint pair.
            if (stage == DenseGpuTimer.VISIBLE_WARP) {
                int warpSlot = (int) (sequence & 127L);
                if (denseWarpCompletedSequence[warpSlot] == sequence) {
                    ++denseTimerStale;
                    rejectDense("duplicate-warp-timer", null);
                    return;
                }
                denseWarpCompletedSequence[warpSlot] = sequence;
                denseWarpMaxCompletedSequence = Math.max(
                        denseWarpMaxCompletedSequence, sequence);
                continue;
            }
            int pair = (int) (sequence & 127L);
            if (densePairSequence[pair] != 0L && densePairSequence[pair] != sequence) {
                ++denseTimerStale;
                rejectDense("wrapped-incomplete-timer-pair", null);
                return;
            }
            densePairSequence[pair] = sequence;
            if ((densePairMask[pair] & (1 << stage)) != 0) {
                ++denseTimerStale;
                rejectDense("duplicate-timer-stage", null);
                return;
            }
            densePairTotalUs[pair] += elapsedUs;
            densePairMask[pair] |= 1 << stage;
            int expectedMask = (1 << DenseGpuTimer.ENDPOINT_COPY) |
                    (1 << DenseGpuTimer.PYRAMID) |
                    (1 << DenseGpuTimer.FORWARD_SOLVE) |
                    (1 << DenseGpuTimer.REVERSE_SOLVE) |
                    (1 << DenseGpuTimer.VALIDATION);
            if ((densePairMask[pair] & expectedMask) == expectedMask) {
                long total = densePairTotalUs[pair];
                ++denseTimedPairs;
                denseTimedPairTotalUs += total;
                denseTimedPairMaxUs = Math.max(denseTimedPairMaxUs, total);
                denseGpuCompleteLastUs = total;
                denseGpuCompleteTotalUs = denseTimedPairTotalUs;
                denseGpuCompleteMaxUs = denseTimedPairMaxUs;
                densePairSequence[pair] = 0L;
                densePairTotalUs[pair] = 0L;
                densePairMask[pair] = 0;
                if (total > DENSE_GPU_BUDGET_US) {
                    rejectDense("async-gpu-pair-over-budget", null);
                    return;
                }
            }
            if (denseTimedPairs >= DENSE_PERFORMANCE_MIN_SAMPLES &&
                    denseStageSamples[DenseGpuTimer.VISIBLE_WARP] >=
                            DENSE_PERFORMANCE_MIN_SAMPLES &&
                    denseTimedPairMaxUs +
                            denseStageP95(DenseGpuTimer.VISIBLE_WARP) >
                            DENSE_GPU_BUDGET_US) {
                rejectDense("combined-pair-warp-over-budget", null);
                return;
            }
        }
        int disjointAfter = denseGpuTimer.takeDisjointCount();
        if (disjointAfter > 0) {
            denseTimerDisjoint += disjointAfter;
            rejectDense("gpu-timer-disjoint", null);
        }
    }

    private long denseStageP95(int stage) {
        int count = (int) Math.min(256L, denseStageSamples[stage]);
        if (count == 0) return 0L;
        long[] values = java.util.Arrays.copyOf(denseStageObservedUs[stage], count);
        java.util.Arrays.sort(values);
        return values[Math.min(count - 1, (int) Math.ceil(count * .95) - 1)];
    }

    private void recordDenseWall(int kind, long elapsedNs) {
        long elapsedUs = Math.max(1L, (elapsedNs + 999L) / 1000L);
        long[] observed;
        if (kind == DENSE_WALL_PROMOTION) {
            observed = densePromotionWallObservedUs;
            densePromotionWallTotalUs += elapsedUs;
            densePromotionWallMaxUs = Math.max(densePromotionWallMaxUs, elapsedUs);
            observed[(int) (densePromotionWallSamples++ & 255L)] = elapsedUs;
        } else if (kind == DENSE_WALL_SIGNATURE) {
            observed = denseSignatureWallObservedUs;
            denseSignatureWallTotalUs += elapsedUs;
            denseSignatureWallMaxUs = Math.max(denseSignatureWallMaxUs, elapsedUs);
            observed[(int) (denseSignatureWallSamples++ & 255L)] = elapsedUs;
        } else if (kind == DENSE_WALL_PROOF) {
            observed = denseProofWallObservedUs;
            denseProofWallTotalUs += elapsedUs;
            denseProofWallMaxUs = Math.max(denseProofWallMaxUs, elapsedUs);
            observed[(int) (denseProofWallSamples++ & 255L)] = elapsedUs;
        } else if (kind == DENSE_WALL_PRESENT) {
            observed = densePresentWallObservedUs;
            densePresentWallTotalUs += elapsedUs;
            densePresentWallMaxUs = Math.max(densePresentWallMaxUs, elapsedUs);
            observed[(int) (densePresentWallSamples++ & 255L)] = elapsedUs;
        } else if (kind == DENSE_WALL_SWAP) {
            observed = denseSwapWallObservedUs;
            denseSwapWallTotalUs += elapsedUs;
            denseSwapWallMaxUs = Math.max(denseSwapWallMaxUs, elapsedUs);
            observed[(int) (denseSwapWallSamples++ & 255L)] = elapsedUs;
        } else if (kind == DENSE_WALL_PROOF_ENQUEUE) {
            observed = denseProofEnqueueWallObservedUs;
            denseProofEnqueueWallTotalUs += elapsedUs;
            denseProofEnqueueWallMaxUs = Math.max(
                    denseProofEnqueueWallMaxUs, elapsedUs);
            observed[(int) (denseProofEnqueueWallSamples++ & 255L)] = elapsedUs;
        } else {
            observed = denseProofPollWallObservedUs;
            denseProofPollWallTotalUs += elapsedUs;
            denseProofPollWallMaxUs = Math.max(denseProofPollWallMaxUs, elapsedUs);
            observed[(int) (denseProofPollWallSamples++ & 255L)] = elapsedUs;
        }
    }

    private long denseWallP95(long[] observed, long samples) {
        int count = (int) Math.min(256L, samples);
        if (count == 0) return 0L;
        long[] values = java.util.Arrays.copyOf(observed, count);
        java.util.Arrays.sort(values);
        return values[Math.min(count - 1, (int) Math.ceil(count * .95) - 1)];
    }

    private String denseStageTelemetry() {
        StringBuilder value = new StringBuilder();
        String[] names = {"", "Copy", "Pyramid", "Forward", "Reverse",
                "Validation", "Warp"};
        for (int stage = 1; stage <= DenseGpuTimer.VISIBLE_WARP; ++stage) {
            value.append(" dense").append(names[stage]).append("Samples=")
                    .append(denseStageSamples[stage]);
            value.append(" dense").append(names[stage]).append("TotalUs=")
                    .append(denseStageTotalUs[stage]);
            value.append(" dense").append(names[stage]).append("P95Us=")
                    .append(denseStageP95(stage));
            value.append(" dense").append(names[stage]).append("MaxUs=")
                    .append(denseStageMaxUs[stage]);
        }
        return value.toString();
    }

    /** Session cap on automatic dense re-arms after transient timer anomalies. */
    private static final int DENSE_TRANSIENT_REJECT_REARM_LIMIT = 8;
    private int denseTransientRejections;

    /** True only for driver measurement anomalies that invalidate the current
     * timing evidence without implying a broken GL pipeline: a disjoint
     * interval is EXT_disjoint_timer_query's defined discard event, and an
     * elapsed overflow is an observed Adreno all-ones result while Cemu's
     * Vulkan queue shared the GPU. Every other reason (context, GL error,
     * malformed/stale results, budget overruns) stays a permanent reject. */
    private static boolean isTransientDenseRejection(String reason) {
        return "gpu-timer-disjoint".equals(reason) ||
                ("native-timer-status-" + DenseGpuTimer.STATUS_DISJOINT)
                        .equals(reason) ||
                ("native-timer-status-" + DenseGpuTimer.STATUS_ELAPSED_OVERFLOW)
                        .equals(reason);
    }

    private void rejectDense(String reason, Throwable failure) {
        densePyramidEnabled = false;
        // A transient measurement anomaly still ends this qualification epoch
        // and collapses to truthful endpoint-only output below, exactly like
        // a permanent reject. Not latching densePyramidUnavailable lets the
        // periodic switch refresh re-arm a fresh timer and epoch on a later
        // HEALTH boundary, bounded per session so a persistently glitching
        // driver converges to the permanent fail-closed state.
        boolean recoverable = isTransientDenseRejection(reason) &&
                ++denseTransientRejections <= DENSE_TRANSIENT_REJECT_REARM_LIMIT;
        if (!recoverable) densePyramidUnavailable = true;
        densePerformanceRejected = true;
        // A rejected qualified renderer has no authorized generation path.
        // The legacy v22 estimator remains useful as diagnostic code, but it
        // must never become a silent visual fallback: that exact transition
        // produced doubled/ghosted PS2 imagery while the badge still claimed
        // 50/100.  Collapse the controller to truthful endpoint-only output.
        frameRate.setGenerationAvailable(false);
        invalidateBufferedPairForReprime(false);
        teardownDenseEpoch("runtime-reject");
        if (failure == null)
            Log.e(TAG, "Dense pyramid rejected generator=" + generatorId +
                    " reason=" + reason + " recoverable=" + (recoverable ? 1 : 0) +
                    " transientRejections=" + denseTransientRejections);
        else
            Log.e(TAG, "Dense pyramid rejected generator=" + generatorId +
                    " reason=" + reason + " recoverable=" + (recoverable ? 1 : 0) +
                    " transientRejections=" + denseTransientRejections, failure);
        reportedSourceFps = -1;
        reportedOutputFps = -1;
        reportStats();
    }

    /** Ends one qualification epoch without allowing its queries or vectors
     * to survive a settings toggle. Cleanup is best-effort and non-throwing:
     * endpoint-only presentation is established before timer teardown, and a
     * native close failure cannot strand generated rendering in the default
     * path. A later enable must create a new native timer and sequence epoch. */
    private void teardownDenseEpoch(String reason) {
        motionEstimateReady = false;
        // Native discard below destroys every pending signature-query owner.
        // Drop the matching retained Java textures before the query sequence
        // can be rebased for a later qualification epoch; otherwise a reused
        // sequence could classify an old texture or leave the four-slot ring
        // permanently full after disable/re-enable.
        clearSignatureCandidates();
        denseSignatureBaselineReady = false;
        denseSignatureSequence = 0L;
        denseSignatureReady = 0;
        proofAtlasDiscarded += denseGpuTimer == null ? 0 :
                denseGpuTimer.pendingProofAtlases();
        ++proofAtlasEpoch;
        RuntimeException cleanupFailure = null;
        try {
            clearAllMotionFieldsAfterDenseReject();
        } catch (RuntimeException failure) {
            cleanupFailure = failure;
        } finally {
            DenseGpuTimer timer = denseGpuTimer;
            denseGpuTimer = null;
            if (timer != null) {
                try {
                    timer.discardPending();
                } catch (RuntimeException failure) {
                    if (cleanupFailure == null) cleanupFailure = failure;
                    else cleanupFailure.addSuppressed(failure);
                }
                try {
                    timer.close();
                } catch (RuntimeException failure) {
                    if (cleanupFailure == null) cleanupFailure = failure;
                    else cleanupFailure.addSuppressed(failure);
                }
            }
        }
        denseCalibrationRuns = 0;
        denseCalibrationUs = 0;
        if (cleanupFailure != null)
            Log.e(TAG, "Dense epoch cleanup failed generator=" + generatorId +
                    " reason=" + reason, cleanupFailure);
    }

    private void clearAllMotionFieldsAfterDenseReject() {
        clearMotionField(flowTextures[0], coarseFlowWidth, coarseFlowHeight);
        clearMotionField(flowTextures[1], fineFlowWidth, fineFlowHeight);
        clearMotionField(flowTextures[2], fineFlowWidth, fineFlowHeight);
        clearMotionField(reverseFlowTextures[0], coarseFlowWidth, coarseFlowHeight);
        clearMotionField(reverseFlowTextures[1], fineFlowWidth, fineFlowHeight);
        clearMotionField(reverseFlowTextures[2], fineFlowWidth, fineFlowHeight);
        clearMotionField(globalCandidateTextures[0], REGIONAL_CANDIDATE_WIDTH,
                REGIONAL_CANDIDATE_HEIGHT);
        clearMotionField(globalCandidateTextures[1], REGIONAL_CANDIDATE_WIDTH,
                REGIONAL_CANDIDATE_HEIGHT);
        clearMotionField(globalCandidateWinnerTextures[0], REGIONAL_FLOW_WIDTH,
                REGIONAL_FLOW_HEIGHT);
        clearMotionField(globalCandidateWinnerTextures[1], REGIONAL_FLOW_WIDTH,
                REGIONAL_FLOW_HEIGHT);
        clearMotionField(globalFlowTextures[0], REGIONAL_FLOW_WIDTH,
                REGIONAL_FLOW_HEIGHT);
        clearMotionField(globalFlowTextures[1], REGIONAL_FLOW_WIDTH,
                REGIONAL_FLOW_HEIGHT);
        if (denseResourcesReady) clearDenseFields();
    }

    private float measureEndpointDifference() {
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D, proofTexture, 0);
        GLES20.glViewport(0, 0, PROOF_WIDTH, PROOF_HEIGHT);
        drawTexture2d(historyTextures[previousIndex]);
        readProofHash(proofPrevious);
        drawTexture2d(historyTextures[currentIndex]);
        readProofHash(proofCurrent);
        long difference = 0;
        int channels = PROOF_WIDTH * PROOF_HEIGHT * 3;
        for (int offset = 0; offset < proofPrevious.length; offset += 4)
            for (int channel = 0; channel < 3; ++channel)
                difference += Math.abs((proofPrevious[offset + channel] & 0xff) -
                        (proofCurrent[offset + channel] & 0xff));
        return difference / (255f * channels);
    }

    private void buildDensePyramid(int source, int endpoint) {
        drawDensePyramid(source, historyWidth, historyHeight,
                densePyramidTextures[endpoint][0], denseLevelWidths[1], denseLevelHeights[1]);
        drawDensePyramid(densePyramidTextures[endpoint][0],
                denseLevelWidths[1], denseLevelHeights[1],
                densePyramidTextures[endpoint][1], denseLevelWidths[2], denseLevelHeights[2]);
    }

    private void drawDensePyramid(int source, int sourceWidth, int sourceHeight,
                                  int destination, int width, int height) {
        attachDenseTarget(destination, width, height);
        GLES20.glUseProgram(densePyramidProgram);
        bindQuad(densePyramidProgram);
        bindTexture(densePyramidProgram, "uTexture", source, 0);
        uniform2(densePyramidProgram, "uInputTexel",
                1f / Math.max(1, sourceWidth), 1f / Math.max(1, sourceHeight));
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private void solveDenseDirection(int direction, int reference, int target) {
        int prior = 0;
        for (int level = DENSE_LEVELS - 1; level >= 0; --level) {
            int ref = level == 0 ? reference :
                    densePyramidTextures[direction == 0 ? 0 : 1][level - 1];
            int dst = level == 0 ? target :
                    densePyramidTextures[direction == 0 ? 1 : 0][level - 1];
            int width = denseLevelWidths[level];
            int height = denseLevelHeights[level];
            // Direction zero defers its former copy-only full-resolution draw
            // until direction one exists, then spends that same draw on the
            // independently scored reciprocal closure below.
            int iterations = DENSE_LEVEL_ITERATIONS[level] -
                    (direction == 0 && level == 0 ? 1 : 0);
            for (int iteration = 0; iteration < iterations; ++iteration) {
                int output = denseFlowTextures[direction][level][iteration & 1];
                attachDenseTarget(output, width, height);
                GLES20.glUseProgram(denseSolveProgram);
                bindQuad(denseSolveProgram);
                bindTexture(denseSolveProgram, "uReference", ref, 0);
                bindTexture(denseSolveProgram, "uTarget", dst, 1);
                bindTexture(denseSolveProgram, "uPriorFlow", prior == 0 ?
                        denseFlowTextures[direction][level][1] : prior, 2);
                // Direction zero remains an independent image-cost solve.
                // The first coarse reverse iteration gets a forward-derived
                // basin proposal. The fine expansion may cheaply retain that
                // proposal before its three local searches. The last fine
                // pass and the post-reverse forward closure also score the
                // bounded fixed-point inverse. Every use is independently
                // scored in its image domain; no pass forces agreement and
                // bidirectional validation remains authoritative.
                boolean coarsestFirst = level == DENSE_LEVELS - 1 &&
                        iteration == 0;
                boolean finestBootstrap = level == 0 && iteration == 0;
                boolean finestLast = level == 0 && iteration == iterations - 1;
                boolean reciprocalGuide = direction == 1 &&
                        (coarsestFirst || finestBootstrap || finestLast) &&
                        denseFinalTextures[0] != 0;
                bindTexture(denseSolveProgram, "uGuideFlow", reciprocalGuide ?
                        denseFinalTextures[0] : denseFlowTextures[0][0][0], 3);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uHasPrior"), prior == 0 ? 0f : 1f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uUseReciprocalGuide"), reciprocalGuide ? 1f : 0f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uGuideLimit"), DENSE_MAX_FLOW_PIXELS);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uUseWidePatch"), level == DENSE_LEVELS - 1 ? 1f : 0f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uFinalConsensus"), level == 0 &&
                        iteration == iterations - 1 ? 1f : 0f);
                // The first fine pass is the required 64x36 -> 128x72 field
                // expansion. Keep the draw/workload identity, but do not run
                // a redundant nine-candidate search until the full-resolution
                // field exists. Three later 1px searches preserve the former
                // 3px fine-level reach with substantially less shared-GPU ALU.
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uBypassSearch"), direction == 1 && level == 0 &&
                        iteration == 0 ? 1f : 0f);
                uniform2(denseSolveProgram, "uAnalysisTexel",
                        1f / width, 1f / height);
                uniform2(denseSolveProgram, "uGuideTexel",
                        1f / denseLevelWidths[0], 1f / denseLevelHeights[0]);
                int priorWidth = level == DENSE_LEVELS - 1 ? width :
                        denseLevelWidths[level + 1];
                int priorHeight = level == DENSE_LEVELS - 1 ? height :
                        denseLevelHeights[level + 1];
                if (iteration > 0) {
                    priorWidth = width;
                    priorHeight = height;
                }
                uniform2(denseSolveProgram, "uPriorTexel",
                        1f / priorWidth, 1f / priorHeight);
                uniform2(denseSolveProgram, "uSourceSize", historyWidth, historyHeight);
                // Exact per-component reach: 8*4.5 + 4*2 + 3*1 = 47px for
                // 40+ FPS sources. A 30-or-lower tier doubles the per-frame
                // displacement for the same scene speed, and 47px physically
                // starved the vector-confidence gate on every ARMSX2 tier-30
                // scene (block-matched real displacements reached 72px on
                // 2026-08-15). Doubling only the coarsest step yields
                // 8*9 + 4*2 + 3*1 = 83px reach at identical iteration count
                // and tap cost; the finer levels' 11px correction capacity
                // absorbs the coarser quantization. The coarsest half-pixel
                // step remains Q8.8-exact in both modes.
                float coarsestStep =
                        frameRate.lockedSourceFps() <= 30 ? 9.0f : 4.5f;
                float step = level == 2 ? coarsestStep :
                        level == 1 ? 2f : 1f;
                uniform2(denseSolveProgram, "uUpdateStep", step, step);
                GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
                prior = output;
            }
        }
        denseFinalTextures[direction] = prior;
    }

    private void refineDenseForwardFromReverse(int reference, int target) {
        int prior = denseFinalTextures[0];
        int output = prior == denseFlowTextures[0][0][0] ?
                denseFlowTextures[0][0][1] : denseFlowTextures[0][0][0];
        attachDenseTarget(output, denseAnalysisWidth, denseAnalysisHeight);
        GLES20.glUseProgram(denseSolveProgram);
        bindQuad(denseSolveProgram);
        bindTexture(denseSolveProgram, "uReference", reference, 0);
        bindTexture(denseSolveProgram, "uTarget", target, 1);
        bindTexture(denseSolveProgram, "uPriorFlow", prior, 2);
        bindTexture(denseSolveProgram, "uGuideFlow", denseFinalTextures[1], 3);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uHasPrior"), 1f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uUseReciprocalGuide"), 1f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uGuideLimit"), DENSE_MAX_FLOW_PIXELS);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uUseWidePatch"), 0f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uFinalConsensus"), 0f);
        // With a guide present, bypass scores current versus reciprocal and
        // returns before the 3x3 local search. Thus this draw cannot extend the
        // exact 47px reach or add the ALU of another fine search iteration.
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uBypassSearch"), 1f);
        uniform2(denseSolveProgram, "uAnalysisTexel",
                1f / denseAnalysisWidth, 1f / denseAnalysisHeight);
        uniform2(denseSolveProgram, "uPriorTexel",
                1f / denseAnalysisWidth, 1f / denseAnalysisHeight);
        uniform2(denseSolveProgram, "uGuideTexel",
                1f / denseAnalysisWidth, 1f / denseAnalysisHeight);
        uniform2(denseSolveProgram, "uSourceSize", historyWidth, historyHeight);
        uniform2(denseSolveProgram, "uUpdateStep", 0f, 0f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        denseFinalTextures[0] = output;
    }

    private void validateDenseDirection(int direction, int reference, int target) {
        attachDenseTarget(denseValidatedTextures[direction], denseAnalysisWidth,
                denseAnalysisHeight);
        GLES20.glUseProgram(denseCycleProgram);
        bindQuad(denseCycleProgram);
        bindTexture(denseCycleProgram, "uFlow", denseFinalTextures[direction], 0);
        bindTexture(denseCycleProgram, "uReverseFlow", denseFinalTextures[1-direction], 1);
        bindTexture(denseCycleProgram, "uReference", reference, 2);
        bindTexture(denseCycleProgram, "uTarget", target, 3);
        uniform2(denseCycleProgram, "uSourceSize", historyWidth, historyHeight);
        uniform2(denseCycleProgram, "uAnalysisTexel", 1f / denseAnalysisWidth,
                1f / denseAnalysisHeight);
        uniform2(denseCycleProgram, "uReverseTexel", 1f / denseAnalysisWidth,
                1f / denseAnalysisHeight);
        float[] rect = denseActiveRect();
        GLES20.glUniform4f(GLES20.glGetUniformLocation(denseCycleProgram, "uActiveRect"),
                rect[0], rect[1], rect[2], rect[3]);
        float limit = Math.min(DENSE_MAX_FLOW_PIXELS,
                flowLimitPixels(historyWidth, historyHeight));
        uniform2(denseCycleProgram, "uFlowRange", limit / historyWidth,
                limit / historyHeight);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseCycleProgram,
                "uValidityBase"),
                frameRate.lockedSourceFps() <= 30 ? 4f : 2f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private float[] denseActiveRect() {
        // The generator's history texture is the engine's game-only surface.
        // GameSurfaceView shapes the Surface layer itself; black pillars live
        // in the parent window and are never present in these textures.
        return new float[]{0f, 0f, 1f, 1f};
    }

    private void attachDenseTarget(int texture, int width, int height) {
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, texture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            throw new IllegalStateException("dense framebuffer incomplete");
        GLES20.glViewport(0, 0, width, height);
    }

    /**
     * Builds a coarse then refined field mapping {@code currentTexture} back
     * to {@code previousTexture}. The reverse pass is measured independently;
     * negating one field would hide occlusions and provide no consistency
     * check against a bad block match.
     */
    private void estimateMotionPass(int previousTexture, int currentTexture,
                                    int[] destinationFlow,
                                    int destinationGlobalCandidates,
                                    int destinationGlobalWinner,
                                    int destinationGlobalFlow) {
        float flowLimit = activeFlowLimitPixels();
        float coarseStep = Math.min(28f, flowLimit / 3f);
        float refineStep = Math.min(8f, Math.max(1f, flowLimit / 12f));
        float regionalCoarsePixels = Math.min(8f, Math.max(2f, flowLimit / 2f));
        float regionalFinePixels = Math.min(2f,
                Math.max(0.5f, regionalCoarsePixels / 4f));
        float rangeX = flowLimit / Math.max(1f, historyWidth);
        float rangeY = flowLimit / Math.max(1f, historyHeight);

        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationFlow[0], 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE) fail("coarse motion framebuffer incomplete");
        GLES20.glViewport(0, 0, coarseFlowWidth, coarseFlowHeight);
        GLES20.glUseProgram(coarseMotionProgram);
        bindQuad(coarseMotionProgram);
        bindTexture(coarseMotionProgram, "uPrevious", previousTexture, 0);
        bindTexture(coarseMotionProgram, "uCurrent", currentTexture, 1);
        uniform2(coarseMotionProgram, "uTexel",
                1f / Math.max(1, historyWidth), 1f / Math.max(1, historyHeight));
        uniform2(coarseMotionProgram, "uSearchStep",
                coarseStep / Math.max(1, historyWidth),
                coarseStep / Math.max(1, historyHeight));
        uniform2(coarseMotionProgram, "uFlowRange", rangeX, rangeY);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationFlow[1], 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE) fail("refined motion framebuffer incomplete");
        GLES20.glViewport(0, 0, fineFlowWidth, fineFlowHeight);
        GLES20.glUseProgram(refineMotionProgram);
        bindQuad(refineMotionProgram);
        bindTexture(refineMotionProgram, "uPrevious", previousTexture, 0);
        bindTexture(refineMotionProgram, "uCurrent", currentTexture, 1);
        bindTexture(refineMotionProgram, "uCoarseFlow", destinationFlow[0], 2);
        uniform2(refineMotionProgram, "uTexel",
                1f / Math.max(1, historyWidth), 1f / Math.max(1, historyHeight));
        uniform2(refineMotionProgram, "uRefineStep",
                refineStep / Math.max(1, historyWidth),
                refineStep / Math.max(1, historyHeight));
        uniform2(refineMotionProgram, "uPixelStep",
                1f / Math.max(1, historyWidth), 1f / Math.max(1, historyHeight));
        uniform2(refineMotionProgram, "uFlowRange", rangeX, rangeY);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationFlow[2], 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("regularized motion framebuffer incomplete");
        GLES20.glViewport(0, 0, fineFlowWidth, fineFlowHeight);
        GLES20.glUseProgram(regularizeMotionProgram);
        bindQuad(regularizeMotionProgram);
        bindTexture(regularizeMotionProgram, "uFlow", destinationFlow[1], 0);
        uniform2(regularizeMotionProgram, "uFlowTexel",
                1f / Math.max(1, fineFlowWidth),
                1f / Math.max(1, fineFlowHeight));
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        // Coarse fixed lattice: 25 source-photometric translations per
        // overlapping region, independent of the ambiguous local-flow field.
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationGlobalCandidates, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("global candidate framebuffer incomplete");
        GLES20.glViewport(0, 0,
                REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
        GLES20.glUseProgram(regionalCoarseCandidateProgram);
        bindQuad(regionalCoarseCandidateProgram);
        bindTexture(regionalCoarseCandidateProgram, "uPrevious", previousTexture, 0);
        bindTexture(regionalCoarseCandidateProgram, "uCurrent", currentTexture, 1);
        uniform2(regionalCoarseCandidateProgram, "uFlowRange", rangeX, rangeY);
        uniform2(regionalCoarseCandidateProgram, "uCoarseStep",
                regionalCoarsePixels / Math.max(1f, historyWidth),
                regionalCoarsePixels / Math.max(1f, historyHeight));
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        // Collapse the coarse atlas to one ungated winner per region.
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationGlobalWinner, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("regional coarse winner framebuffer incomplete");
        GLES20.glViewport(0, 0, REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        GLES20.glUseProgram(regionalCandidateWinnerProgram);
        bindQuad(regionalCandidateWinnerProgram);
        bindTexture(regionalCandidateWinnerProgram, "uCandidates",
                destinationGlobalCandidates, 0);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        // Refine +/-2 fine steps around that winner. At full GameCube flow
        // range this is +/-4 pixels at two-pixel spacing, reaching +/-20.
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationGlobalCandidates, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("regional fine candidate framebuffer incomplete");
        GLES20.glViewport(0, 0,
                REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
        GLES20.glUseProgram(regionalFineCandidateProgram);
        bindQuad(regionalFineCandidateProgram);
        bindTexture(regionalFineCandidateProgram, "uPrevious", previousTexture, 0);
        bindTexture(regionalFineCandidateProgram, "uCurrent", currentTexture, 1);
        bindTexture(regionalFineCandidateProgram, "uCoarseWinner",
                destinationGlobalWinner, 2);
        uniform2(regionalFineCandidateProgram, "uFlowRange", rangeX, rangeY);
        uniform2(regionalFineCandidateProgram, "uFineStep",
                regionalFinePixels / Math.max(1f, historyWidth),
                regionalFinePixels / Math.max(1f, historyHeight));
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        // Replace the coarse winner with the final ungated fine winner. It is
        // retained for proof telemetry before regional gates are applied.
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationGlobalWinner, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("regional fine winner framebuffer incomplete");
        GLES20.glViewport(0, 0, REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        GLES20.glUseProgram(regionalCandidateWinnerProgram);
        bindQuad(regionalCandidateWinnerProgram);
        bindTexture(regionalCandidateWinnerProgram, "uCandidates",
                destinationGlobalCandidates, 0);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

        // Native-resolution consoles commonly scroll by one source pixel per
        // unique frame. The coarse and first fine regional lattices above use
        // even source-pixel steps at these resolutions, so their winners
        // cannot represent odd displacements such as +1 or -7. Refine the
        // selected winner once more at exactly one native source pixel. This
        // bounded pass is deliberately excluded from 720p-and-higher sources:
        // it fixes low-resolution quantization without adding any work to the
        // already qualified high-resolution GameCube cadence path.
        if (Math.min(historyWidth, historyHeight) < HIGH_RES_FLOW_THRESHOLD) {
            GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                    GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                    destinationGlobalCandidates, 0);
            if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                    GLES20.GL_FRAMEBUFFER_COMPLETE)
                fail("regional native-pixel candidate framebuffer incomplete");
            GLES20.glViewport(0, 0,
                    REGIONAL_CANDIDATE_WIDTH, REGIONAL_CANDIDATE_HEIGHT);
            GLES20.glUseProgram(regionalFineCandidateProgram);
            bindQuad(regionalFineCandidateProgram);
            bindTexture(regionalFineCandidateProgram, "uPrevious", previousTexture, 0);
            bindTexture(regionalFineCandidateProgram, "uCurrent", currentTexture, 1);
            bindTexture(regionalFineCandidateProgram, "uCoarseWinner",
                    destinationGlobalWinner, 2);
            uniform2(regionalFineCandidateProgram, "uFlowRange", rangeX, rangeY);
            uniform2(regionalFineCandidateProgram, "uFineStep",
                    1f / Math.max(1f, historyWidth),
                    1f / Math.max(1f, historyHeight));
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

            GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                    GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                    destinationGlobalWinner, 0);
            if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                    GLES20.GL_FRAMEBUFFER_COMPLETE)
                fail("regional native-pixel winner framebuffer incomplete");
            GLES20.glViewport(0, 0, REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
            GLES20.glUseProgram(regionalCandidateWinnerProgram);
            bindQuad(regionalCandidateWinnerProgram);
            bindTexture(regionalCandidateWinnerProgram, "uCandidates",
                    destinationGlobalCandidates, 0);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        }

        // Apply the unchanged support/quadrant/neighbor gates.
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationGlobalFlow, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("global motion framebuffer incomplete");
        GLES20.glViewport(0, 0, REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        GLES20.glUseProgram(globalMotionProgram);
        bindQuad(globalMotionProgram);
        bindTexture(globalMotionProgram, "uWinners", destinationGlobalWinner, 0);
        bindTexture(globalMotionProgram, "uPrevious", previousTexture, 1);
        bindTexture(globalMotionProgram, "uCurrent", currentTexture, 2);
        uniform2(globalMotionProgram, "uFlowRange", rangeX, rangeY);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
    }

    private void copyTexture(int source, int destination) {
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, source, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE) fail("latest framebuffer incomplete");
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, destination);
        GLES20.glCopyTexSubImage2D(GLES20.GL_TEXTURE_2D, 0, 0, 0,
                0, 0, historyWidth, historyHeight);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        checkGl("promote source frame");
    }

    /** Draws an RGBA sampler2D without motion decoding or color transforms. */
    private void drawTexture2d(int sourceTexture) {
        GLES20.glUseProgram(textureCopyProgram);
        bindQuad(textureCopyProgram);
        bindTexture(textureCopyProgram, "uTexture", sourceTexture, 0);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    /** Applies the same maximize-height, aspect-preserving viewport to every visible path. */
    private void setPresentationViewport() {
        float aspect = presentationAspect > 0f ? presentationAspect :
                (float) outputWidth / outputHeight;
        int contentWidth = Math.max(1, Math.round(outputHeight * aspect));
        GLES20.glViewport((outputWidth - contentWidth) / 2, 0,
                contentWidth, outputHeight);
    }

    private void copyExternalTo(int destinationTexture) {
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, destinationTexture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE) fail("history framebuffer incomplete");
        GLES20.glViewport(0, 0, inputWidth, inputHeight);
        GLES20.glUseProgram(copyProgram);
        bindQuad(copyProgram);
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, externalTexture);
        GLES20.glUniform1i(GLES20.glGetUniformLocation(copyProgram, "uTexture"), 0);
        GLES20.glUniformMatrix4fv(GLES20.glGetUniformLocation(copyProgram, "uTransform"),
                1, false, textureTransform, 0);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        checkGl("copy producer frame");
    }

    private long schedulerDueSelectedCount() { return presents; }
    private long schedulerDueNoEndpointCount() {
        // Unavailable is the exact count of selected physical slots that had
        // no usable retained endpoint pair. An unavailable slot also resets
        // the scheduler epoch (and therefore increments the broader underrun
        // counter), so summing both would double-count the same cadence miss.
        return frameRate.bufferedUnavailableSlotCount();
    }
    private long schedulerDuePhaseClampedCount() { return 0L; }
    private long schedulerRealPriorityCount() {
        return frameRate.bufferedRealCount();
    }
    private long schedulerSyntheticQuotaSkippedCount() {
        return bufferedSyntheticQuotaSkippedCount;
    }
    private long schedulerSyntheticSelectedCount() {
        return bufferedSyntheticSelectedCount;
    }
    private long schedulerSyntheticPairCreatedCount() {
        return bufferedPairCreatedCount;
    }
    private long schedulerSyntheticNotReadyCount() {
        return bufferedSyntheticNotReadyCount;
    }
    private long schedulerDuplicatePairSelectionCount() {
        return frameRate.bufferedDuplicateTargetCount();
    }
    private long schedulerPresentationCallbackCount() {
        return bufferedPresentationCallbackCount;
    }
    private long schedulerPresentationEpoch() {
        return frameRate.bufferedPresentationEpoch();
    }
    private int schedulerSyntheticQuotaPending() {
        return activePairReady && !activePairSyntheticCommitted ? 1 : 0;
    }
    private long schedulerLastSelectedSyntheticPair() {
        return bufferedLastSelectedSyntheticPair;
    }

    /** Starts a fresh bounded evidence reservoir whenever presentation state
     * changes, without relabelling or erasing any already-enqueued atlas. */
    private void refreshProofEvidencePresentationEpoch() {
        if (!qualificationProofEnabled || !densePyramidEnabled ||
                activeProofSchemaVersion() != DENSE_V28_PROOF_SCHEMA_VERSION)
            return;
        long presentationEpoch = schedulerPresentationEpoch();
        if (presentationEpoch <= 0L)
            throw new IllegalStateException("invalid proof presentation epoch");
        if (presentationEpoch == proofEvidencePresentationEpoch) return;
        proofEvidencePresentationEpoch = presentationEpoch;
        proofEvidenceEnqueuedInEpoch = 0L;
        // Let the first eligible synthetic present establish this epoch's
        // evidence instead of inheriting the preceding epoch's sample phase.
        lastProofPresent = Long.MIN_VALUE;
    }

    private void presentBuffered(long frameTimeNanos, int presentation,
                                 float selectedPhase) {
        // selectBufferedPresentation may change the scheduler epoch in this
        // callback. Rebind before deciding whether this presented frame can
        // consume the new epoch's bounded proof budget.
        refreshProofEvidencePresentationEpoch();
        boolean realThisTick = presentation ==
                AdaptiveFrameRateController.PRESENT_REAL;
        boolean captureProof = false;
        float proofPhase = 0f;
        boolean renderedSynthetic = false;
        // Consume completed queries before choosing this frame's pixels. Any
        // async rejection therefore draws the current endpoint in this very
        // swap instead of leaking one last stale/generated frame.
        boolean denseEnabledAtSelection = densePyramidEnabled;
        if (densePyramidEnabled) {
            try {
                pollDenseTimers();
            } catch (RuntimeException timerFailure) {
                ++denseTimerUnavailable;
                rejectDense("gpu-timer-poll-failure", timerFailure);
            }
        }
        // The buffered selection for this callback was made before the poll
        // above could reject; a rejection here already invalidated the pair.
        boolean rejectedAfterSelection =
                denseEnabledAtSelection && !densePyramidEnabled;
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        GLES20.glViewport(0, 0, outputWidth, outputHeight);
        GLES20.glClearColor(0f, 0f, 0f, 1f);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
        boolean denseSceneCut = densePyramidEnabled && densePairMeanDifference > .18f;
        if (realThisTick) {
            // A timestamp boundary may select either exact endpoint: phase0 is
            // the retained left, while a late physical callback may land on
            // phase1 and consume the retained right. Neither path reads the
            // producer's overwriteable latest texture.
            setPresentationViewport();
            drawTexture2d(historyTextures[selectedPhase >= 1f ?
                    currentIndex : previousIndex]);
        } else if (denseSceneCut) {
            // There is no physical intermediate across a hard scene cut.
            // Hold the left endpoint until the rational source timeline
            // advances; never turn the cut into a crossfade or show it early.
            setPresentationViewport();
            drawTexture2d(historyTextures[previousIndex]);
        } else if (rejectedAfterSelection) {
            // The poll above rejected dense after this callback's synthetic
            // was already selected. Realize the documented rejection contract
            // for this exact swap: hold the retained left endpoint through
            // the still-mandatory swap (mirroring the warp-timer-failure
            // path), and let the post-swap accounting abort the uncommitted
            // buffered decision. Throwing here instead skipped the present
            // and misreported the race as an impossible scheduler state.
            setPresentationViewport();
            drawTexture2d(historyTextures[previousIndex]);
        } else if (!activePairReady || !motionEstimateReady ||
                !(selectedPhase > 0f && selectedPhase < 1f)) {
            throw new IllegalStateException(
                    "buffered synthetic selected without an adjacent ready pair");
        } else {
            // Always maximize height and preserve the source display aspect.
            // A width larger than the Surface is intentionally clipped equally
            // on both sides; a narrower picture is pillarboxed by the clear.
            setPresentationViewport();
            float phase = selectedPhase;
            phaseDiagSum += phase;
            phaseDiagMin = Math.min(phaseDiagMin, phase);
            phaseDiagMax = Math.max(phaseDiagMax, phase);
            ++phaseDiagCount;
            phaseDiagSpanSumNs +=
                    activeRightTimestampNs - activeLeftTimestampNs;
            boolean sustainable = frameRate.hasSustainableGenerationRate();
            if (sustainable) {
                if (densePyramidEnabled) {
                    try {
                        beginDenseStage(DenseGpuTimer.VISIBLE_WARP);
                        drawMotionFrame(phase);
                        endDenseStage();
                        renderedSynthetic = true;
                    } catch (RuntimeException timerFailure) {
                        ++denseTimerUnavailable;
                        rejectDense("gpu-warp-timer-failure", timerFailure);
                        // The failed timer may occur after the generated draw.
                        // Replace it with the exact left endpoint before the
                        // still-mandatory swap; never bubble to doFrame.
                        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
                        GLES20.glViewport(0, 0, outputWidth, outputHeight);
                        GLES20.glClearColor(0f, 0f, 0f, 1f);
                        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
                        setPresentationViewport();
                        drawTexture2d(historyTextures[previousIndex]);
                    }
                } else {
                    drawMotionFrame(phase);
                    renderedSynthetic = true;
                }
            }
            else drawTexture2d(historyTextures[previousIndex]);
            proofPhase = phase;
            // Every selected output tick between retained decoded images is
            // generated. Timestamp resampling may choose several distinct
            // fractions from one longer interval, but never extrapolates past
            // the exact adjacent endpoints or repeats a source-clock target.
            boolean synthetic = renderedSynthetic &&
                    presentation == AdaptiveFrameRateController.PRESENT_SYNTHETIC &&
                    sustainable &&
                    frameRate.generatesIntermediateFrames() &&
                    phase > 0f && phase < 1f;
            // Qualification must inspect frames that the generator actually
            // synthesized, not endpoint presents that contain no interpolation
            // to prove. Keep readback bounded to roughly four samples/second
            // and require a materially intermediate phase so every accepted
            // sample can be compared against both real endpoints.
            captureProof = synthetic && qualificationProofEnabled &&
                    (densePyramidEnabled ? proofEvidenceEnqueuedInEpoch :
                            proofSamples) <
                            MAX_QUALIFICATION_PROOF_SAMPLES &&
                    phase > 0.15f && phase < 0.85f &&
                    (lastProofPresent == Long.MIN_VALUE ||
                            presents - lastProofPresent >= PROOF_SAMPLE_INTERVAL);
            if (captureProof) lastProofPresent = presents;
            if (!generationLogged && frameRate.generatesIntermediateFrames() &&
                    frameRate.measuredProducerHz() > 0.0) {
                generationLogged = true;
                Log.i(TAG, "Intermediate frames active producerHz=" +
                        String.format(java.util.Locale.US, "%.2f",
                                frameRate.measuredProducerHz()) +
                        " lockedFps=" + frameRate.lockedSourceFps() +
                        " outputFps=" + frameRate.outputFps());
            }
        }
        if (Build.VERSION.SDK_INT >= 18) {
            long desiredPresentNs = FrameGenerationCadence.nextPresentationTimeNs(
                    frameTimeNanos, Math.max(1L, Math.round(
                            1_000_000_000.0 / Math.max(1f, refreshHz))),
                    System.nanoTime());
            if (desiredPresentNs <= 0L ||
                    !EGLExt.eglPresentationTimeANDROID(
                            eglDisplay, eglSurface, desiredPresentNs))
                fail("eglPresentationTimeANDROID");
        }
        long swapStarted = densePyramidEnabled ? System.nanoTime() : 0L;
        if (!EGL14.eglSwapBuffers(eglDisplay, eglSurface)) fail("eglSwapBuffers");
        if (!outputFrameRateReassertedAfterSwap) {
            outputFrameRateReassertedAfterSwap = true;
            requestOutputFrameRate("first-successful-swap");
        }
        if (swapStarted != 0L)
            recordDenseWall(DENSE_WALL_SWAP, System.nanoTime() - swapStarted);
        int endpointAdvance = frameRate.bufferedEndpointAdvanceAfterPresentation();
        boolean advanceCrossesGap = bufferedAdvanceWouldCrossGap(endpointAdvance);
        long presentationEpochBeforeAdvance = schedulerPresentationEpoch();
        if (renderedSynthetic || realThisTick)
            frameRate.commitBufferedPresentation(true);
        else {
            frameRate.abortBufferedPresentation();
            endpointAdvance = 0;
            invalidateBufferedPairForReprime(false);
        }
        // A failed/aborted decision advances the controller epoch. Keep the
        // emitted HEALTH identity and any post-swap atlas on that exact epoch.
        refreshProofEvidencePresentationEpoch();
        // Advancing into a coalesced source gap will reset the scheduler below.
        // Never enqueue an atlas for an epoch that is already known to end in
        // this callback; its delayed completion would make the new epoch's
        // first HEALTH baseline non-empty/pending and impossible to qualify.
        if (advanceCrossesGap) captureProof = false;
        // Never put synchronous evidence readback in front of the visible
        // swap. The proof samples the exact same endpoint textures, motion
        // field and phase immediately after submission, using otherwise-idle
        // time before the next display callback. This keeps qualification
        // instrumentation from manufacturing the missed presents it audits.
        if (captureProof) {
            if (densePyramidEnabled) {
                try {
                    enqueueProofAtlas(proofPhase);
                } catch (RuntimeException proofFailure) {
                    ++proofAtlasErrors;
                    rejectDense("async-proof-atlas-enqueue-failure", proofFailure);
                }
            } else sampleFrameProof(proofPhase);
        }
        if (renderedSynthetic) {
            ++generatedPresents;
            ++bufferedSyntheticSelectedCount;
            activePairSyntheticCommitted = true;
            bufferedLastSelectedSyntheticPair = activeLeftSequence;
        }
        ++presents;
        if (renderedSynthetic || realThisTick) {
            try {
                commitBufferedEndpointAdvance(presentation, endpointAdvance);
            } catch (RuntimeException pairFailure) {
                Log.e(TAG, "Unable to prepare next buffered endpoint pair",
                        pairFailure);
                invalidateBufferedPairForReprime();
            }
        }
        long presentationEpochAfterAdvance = schedulerPresentationEpoch();
        refreshProofEvidencePresentationEpoch();
        if (presentationEpochAfterAdvance != presentationEpochBeforeAdvance) {
            // The completed swap belongs to the ending scheduler epoch. Start
            // the next HEALTH window only after the reset/re-prime boundary;
            // by its first emission every excluded old-epoch atlas has had a
            // full 120 presents to drain without poisoning the baseline.
            resetHealthWindowAfterStreamChange();
            return;
        }
        if (presents % HEALTH_INTERVAL == 0L) {
            refreshQualificationProofState();
            long now = System.nanoTime();
            long windowElapsedMs = Math.max(1L,
                    (now - healthWindowStartNanos) / 1_000_000L);
            long windowPresents = presents - lastHealthPresents;
            long windowGenerated = generatedPresents - lastHealthGenerated;
            long windowPromoted = promotedFrameCount - lastHealthPromoted;
            long windowDueSelected = schedulerDueSelectedCount() -
                    lastHealthDueSelected;
            long windowDueNoEndpoint = schedulerDueNoEndpointCount() -
                    lastHealthDueNoEndpoint;
            long windowDuePhaseClamped = schedulerDuePhaseClampedCount() -
                    lastHealthDuePhaseClamped;
            long windowRealPriority = schedulerRealPriorityCount() -
                    lastHealthRealPriority;
            long windowSyntheticQuotaSkipped =
                    schedulerSyntheticQuotaSkippedCount() -
                            lastHealthSyntheticQuotaSkipped;
            long windowSyntheticSelected = schedulerSyntheticSelectedCount() -
                    lastHealthSyntheticSelected;
            long windowSyntheticPairCreated =
                    schedulerSyntheticPairCreatedCount() -
                            lastHealthSyntheticPairCreated;
            long windowSyntheticNotReady = schedulerSyntheticNotReadyCount() -
                    lastHealthSyntheticNotReady;
            long windowDuplicatePairSelection =
                    schedulerDuplicatePairSelectionCount() -
                            lastHealthDuplicatePairSelection;
            long windowPresentationCallbacks =
                    schedulerPresentationCallbackCount() -
                            lastHealthPresentationCallbacks;
            long windowPresentationEpoch = schedulerPresentationEpoch();
            double actualPresentHz = windowPresents * 1000.0 / windowElapsedMs;
            boolean targetScheduleEligible = denseCadenceTargetEligible(
                    windowElapsedMs, windowPromoted, frameRate.lockedSourceFps(),
                    windowDueNoEndpoint, windowSyntheticQuotaSkipped,
                    windowDuePhaseClamped,
                    windowSyntheticNotReady, windowDuplicatePairSelection,
                    windowPresentationEpoch, lastHealthPresentationEpoch);
            boolean cadenceUnderTarget = densePyramidEnabled &&
                    targetScheduleEligible && windowPresents >= HEALTH_INTERVAL &&
                    actualPresentHz < Math.max(1.0, frameRate.outputFps() * .96);
            denseCadenceFailureWindows =
                    FrameGenerationCadence.advanceCadenceFailureWindows(
                            denseCadenceFailureWindows, targetScheduleEligible,
                            cadenceUnderTarget);
            // One overloaded scene transition is not a durable renderer
            // failure. Public LSFG-style pacing likewise distinguishes a
            // transient outlier from a persistent timing regime. Three full
            // consecutive HEALTH windows still fail closed with the original
            // 96% presented-output threshold unchanged.
            boolean cadenceReject = cadenceUnderTarget &&
                    denseCadenceFailureWindows >=
                            DENSE_CADENCE_REJECT_CONSECUTIVE_WINDOWS;
            // Preserve the exact failing dense epoch before rejection tears
            // down its timer and switches activeProofContract() back to v22.
            // The split extension is intentionally negative evidence:
            // denseEnabled=1 and densePerformanceRejected=1 describe the
            // implementation that actually produced this cadence window.
            if (cadenceReject) {
                densePerformanceRejected = true;
                pendingDenseCadenceReject = true;
                pendingDenseHealthPresents = windowPresents;
                pendingDenseHealthGenerated = windowGenerated;
                pendingDenseHealthPromoted = windowPromoted;
            } else if (activeProofSchemaVersion() == DENSE_V28_PROOF_SCHEMA_VERSION) {
                logSplitHealth(now, windowElapsedMs, windowPresents,
                        windowGenerated, windowPromoted, windowDueSelected,
                        windowDueNoEndpoint, windowDuePhaseClamped,
                        windowRealPriority, windowSyntheticQuotaSkipped,
                        windowPresentationEpoch, windowSyntheticSelected,
                        windowSyntheticPairCreated, windowSyntheticNotReady,
                        windowDuplicatePairSelection);
            } else Log.i(TAG, "Presentation health generator=" + generatorId +
                    " role=" + displayRole + " displayId=" + displayId +
                    " proofContract=" + activeProofContract() +
                    " proofSchemaVersion=" + activeProofSchemaVersion() +
                    " presents=" + presents +
                    " generated=" + generatedPresents + " real=" + realFrameCount +
                    " promoted=" + promotedFrameCount +
                    " submitted=" + submittedFrameCount +
                    " producerHz=" + String.format(java.util.Locale.US, "%.2f",
                            frameRate.measuredProducerHz()) +
                    " lockedFps=" + frameRate.lockedSourceFps() +
                    " outputFps=" + frameRate.outputFps() +
                    " panelFps=" + frameRate.panelFps() +
                    " latticeRegionSamples=" + latticeRegionSamples +
                    " latticeBackwardCoherentRegions=" +
                            latticeBackwardCoherentRegions +
                    " latticeForwardCoherentRegions=" +
                            latticeForwardCoherentRegions +
                    " latticeBackwardBoundaryRegions=" +
                            latticeBackwardBoundaryRegions +
                    " latticeForwardBoundaryRegions=" +
                            latticeForwardBoundaryRegions +
                    " latticeBackwardCoherentBoundaryRegions=" +
                            latticeBackwardCoherentBoundaryRegions +
                    " latticeForwardCoherentBoundaryRegions=" +
                            latticeForwardCoherentBoundaryRegions +
                    " latticeBackwardCoherentRegionCount=" +
                            latticeBackwardCoherentRegionCount +
                    " latticeForwardCoherentRegionCount=" +
                            latticeForwardCoherentRegionCount +
                    " latticeBackwardBoundaryRegionCount=" +
                            latticeBackwardBoundaryRegionCount +
                    " latticeForwardBoundaryRegionCount=" +
                            latticeForwardBoundaryRegionCount +
                    " latticeBackwardCoherentBoundaryRegionCount=" +
                            latticeBackwardCoherentBoundaryRegionCount +
                    " latticeForwardCoherentBoundaryRegionCount=" +
                            latticeForwardCoherentBoundaryRegionCount +
                    " latticeBackwardPeakSupport=" + latticeBackwardPeakSupport +
                    " latticeForwardPeakSupport=" + latticeForwardPeakSupport +
                    " regionalFlowRegionSamples=" + regionalFlowRegionSamples +
                    " regionalBackwardSupportedRegions=" +
                            regionalBackwardSupportedRegions +
                    " regionalForwardSupportedRegions=" +
                            regionalForwardSupportedRegions +
                    " regionalBackwardNeighborRegions=" +
                            regionalBackwardNeighborRegions +
                    " regionalForwardNeighborRegions=" +
                            regionalForwardNeighborRegions +
                    " regionalBackwardConstantNeighborRegions=" +
                            regionalBackwardConstantNeighborRegions +
                    " regionalForwardConstantNeighborRegions=" +
                            regionalForwardConstantNeighborRegions +
                    " regionalBackwardGradientNeighborRegions=" +
                            regionalBackwardGradientNeighborRegions +
                    " regionalForwardGradientNeighborRegions=" +
                            regionalForwardGradientNeighborRegions +
                    " regionalBackwardAcceptedRegions=" +
                            regionalBackwardAcceptedRegions +
                    " regionalForwardAcceptedRegions=" +
                            regionalForwardAcceptedRegions +
                    " regionalBackwardAcceptedBoundaryRegions=" +
                            regionalBackwardAcceptedBoundaryRegions +
                    " regionalForwardAcceptedBoundaryRegions=" +
                            regionalForwardAcceptedBoundaryRegions +
                    " regionalBackwardCycleAcceptedRegions=" +
                            regionalBackwardCycleAcceptedRegions +
                    " regionalForwardCycleAcceptedRegions=" +
                            regionalForwardCycleAcceptedRegions +
                    " regionalBackwardAcceptedRegionCount=" +
                            regionalBackwardAcceptedRegionCount +
                    " regionalForwardAcceptedRegionCount=" +
                            regionalForwardAcceptedRegionCount +
                    " regionalBackwardAcceptedBoundaryRegionCount=" +
                            regionalBackwardAcceptedBoundaryRegionCount +
                    " regionalForwardAcceptedBoundaryRegionCount=" +
                            regionalForwardAcceptedBoundaryRegionCount +
                    " regionalBackwardCycleAcceptedRegionCount=" +
                            regionalBackwardCycleAcceptedRegionCount +
                    " regionalForwardCycleAcceptedRegionCount=" +
                            regionalForwardCycleAcceptedRegionCount +
                    " regionalBackwardSupportedRegionCount=" +
                            regionalBackwardSupportedRegionCount +
                    " regionalForwardSupportedRegionCount=" +
                            regionalForwardSupportedRegionCount +
                    " regionalBackwardNeighborRegionCount=" +
                            regionalBackwardNeighborRegionCount +
                    " regionalForwardNeighborRegionCount=" +
                            regionalForwardNeighborRegionCount +
                    " regionalBackwardConstantNeighborRegionCount=" +
                            regionalBackwardConstantNeighborRegionCount +
                    " regionalForwardConstantNeighborRegionCount=" +
                            regionalForwardConstantNeighborRegionCount +
                    " regionalBackwardGradientNeighborRegionCount=" +
                            regionalBackwardGradientNeighborRegionCount +
                    " regionalForwardGradientNeighborRegionCount=" +
                            regionalForwardGradientNeighborRegionCount +
                    " regionalBackwardPeakSupport=" + regionalBackwardPeakSupport +
                    " regionalForwardPeakSupport=" + regionalForwardPeakSupport +
                    " regionalBackwardPeakConfidence=" +
                            regionalBackwardPeakConfidence +
                    " regionalForwardPeakConfidence=" +
                            regionalForwardPeakConfidence +
                    " activeMotionVectors=" + activeMotionVectors +
                    " confidentMotionVectors=" + confidentMotionVectors +
                    " motionVectorCells=" + (PROOF_WIDTH * PROOF_HEIGHT) +
                    " proofSamples=" + proofSamples +
                    " syntheticProofSamples=" + syntheticProofSamples +
                    " syntheticDistinctFromEndpoints=" +
                            syntheticDistinctFromEndpoints +
                    " changingProofOutputs=" + changingProofOutputs +
                    " eligibleSyntheticPixels=" + eligibleSyntheticPixels +
                    " substantiveSyntheticPixels=" + substantiveSyntheticPixels +
                    " nonCrossfadeSyntheticPixels=" + nonCrossfadeSyntheticPixels +
                    " motionEligibleProofSamples=" + motionEligibleProofSamples +
                    " motionCorrelatedProofSamples=" + motionCorrelatedProofSamples +
                    " v21DirectionallyEligibleSyntheticPixels=" +
                            motionEligibleSyntheticPixels +
                    " v21CorrectVectorPredictedSyntheticPixels=" +
                            motionSynthesizedSyntheticPixels +
                    " denseEnabled=" + (densePyramidEnabled ? 1 : 0) +
                    " densePromotions=" + densePromotions +
                    " densePasses=" + densePasses +
                    " denseCpuSubmitTotalUs=" + denseCpuSubmitTotalUs +
                    " denseCpuSubmitMaxUs=" + denseCpuSubmitMaxUs +
                    " denseCpuSubmitLastUs=" + denseCpuSubmitLastUs +
                    " denseGpuCompleteTotalUs=" + denseGpuCompleteTotalUs +
                    " denseGpuCompleteMaxUs=" + denseGpuCompleteMaxUs +
                    " denseGpuCompleteLastUs=" + denseGpuCompleteLastUs +
                    " denseGpuBudgetUs=" + DENSE_GPU_BUDGET_US +
                    " denseTimedPairs=" + denseTimedPairs +
                    " denseWarpSequence=" + denseWarpSequence +
                    " denseWarpMaxCompletedSequence=" +
                            denseWarpMaxCompletedSequence +
                    " denseTimerPending=" + (denseGpuTimer == null ? 0 :
                            denseGpuTimer.pendingCount()) +
                    " denseTimerDisjoint=" + denseTimerDisjoint +
                    " denseTimerUnavailable=" + denseTimerUnavailable +
                    " denseTimerStale=" + denseTimerStale +
                    " denseTimerMaxQueueAge=" + denseTimerMaxQueueAge +
                    " densePerformanceRejected=" +
                            (densePerformanceRejected ? 1 : 0) +
                    " denseCalibrationRuns=" + denseCalibrationRuns +
                    " denseCalibrationUs=" + denseCalibrationUs +
                    " denseCombinedPairMaxWarpP95Us=" +
                            (denseTimedPairMaxUs +
                                    denseStageP95(DenseGpuTimer.VISIBLE_WARP)) +
                    " densePromotionWallSamples=" + densePromotionWallSamples +
                    " densePromotionWallTotalUs=" + densePromotionWallTotalUs +
                    " densePromotionWallP95Us=" + denseWallP95(
                            densePromotionWallObservedUs, densePromotionWallSamples) +
                    " densePromotionWallMaxUs=" + densePromotionWallMaxUs +
                    " denseSignatureWallSamples=" + denseSignatureWallSamples +
                    " denseSignatureWallTotalUs=" + denseSignatureWallTotalUs +
                    " denseSignatureWallP95Us=" + denseWallP95(
                            denseSignatureWallObservedUs, denseSignatureWallSamples) +
                    " denseSignatureWallMaxUs=" + denseSignatureWallMaxUs +
                    " denseProofWallSamples=" + denseProofWallSamples +
                    " denseProofWallTotalUs=" + denseProofWallTotalUs +
                    " denseProofWallP95Us=" + denseWallP95(
                            denseProofWallObservedUs, denseProofWallSamples) +
                    " denseProofWallMaxUs=" + denseProofWallMaxUs +
                    " denseSignatureSequence=" + denseSignatureSequence +
                    " denseSignatureReady=" + denseSignatureReady +
                    " denseSignatureUnavailable=" + denseSignatureUnavailable +
                    " denseSignatureMaxQueueAge=" + denseSignatureMaxQueueAge +
                    " denseSignaturePending=" + (denseGpuTimer == null ? 0 :
                            denseGpuTimer.pendingSignatures()) +
                    " denseSignatureCapability=" + denseSignatureCapability() +
                    " denseSignatureRequestedGles=" + requestedEglContextMajor +
                    " denseSignatureActualGlesMajor=" + actualEglContextMajor +
                    " denseSignatureActualGlesMinor=" + actualEglContextMinor +
                    " denseSignatureSelfTests=" +
                            (denseSignatureCapability() == DENSE_SIGNATURE_CAP_READY ? 1 : 0) +
                    " denseRuntimeCadenceSource=app-present-window" +
                    " denseOfflineCadenceSource=surfaceflinger-layer-timestamps" +
                    denseStageTelemetry() +
                    " denseVariant=" + denseVariant() +
                    " denseAnalysisWidth=" + denseAnalysisWidth +
                    " denseAnalysisHeight=" + denseAnalysisHeight +
                    " denseSolveTexelsPerPromotion=" + denseSolveTexelsPerPromotion() +
                    " denseTotalTexelsPerPromotion=" + denseTotalTexelsPerPromotion() +
                    " denseMaxFlowPixels=" + (int) DENSE_MAX_FLOW_PIXELS +
                    " denseProofCells=" + denseProofCells +
                    " denseBackwardValidCells=" + denseBackwardValidCells +
                    " denseForwardValidCells=" + denseForwardValidCells +
                    " windowElapsedMs=" + windowElapsedMs +
                    " windowStartNs=" + healthWindowStartNanos +
                    " windowEndNs=" + now +
                    " windowPresents=" + windowPresents +
                    " windowGenerated=" + windowGenerated +
                    " windowPromoted=" + windowPromoted);
            if (!cadenceReject) {
                long completedWindowNs = now - healthWindowStartNanos;
                boolean cadenceTierChanged =
                        frameRate.observeAttainableCadenceWindow(
                                completedWindowNs, windowPromoted,
                                windowSyntheticSelected,
                                windowPresents,
                                windowSyntheticPairCreated,
                                windowSyntheticQuotaSkipped,
                                lastHealthSyntheticQuotaPending,
                                schedulerSyntheticQuotaPending(),
                                windowDueNoEndpoint, windowDuePhaseClamped,
                                windowSyntheticNotReady,
                                windowDuplicatePairSelection,
                                windowPresentationCallbacks,
                                windowPresentationEpoch);
                if (!cadenceTierChanged)
                    frameRate.observePromotionWindow(completedWindowNs,
                            windowPromoted);
                healthWindowStartNanos = now;
                lastHealthPresents = presents;
                lastHealthGenerated = generatedPresents;
                lastHealthPromoted = promotedFrameCount;
                updateSchedulerHealthBaseline();
            }
        }
        reportStats();
    }

    static boolean denseCadenceTargetEligible(long elapsedMs, long promoted,
                                               int lockedFps,
                                               long dueNoEndpoint,
                                               long syntheticQuotaSkipped,
                                               long phaseClamped,
                                               long syntheticNotReady,
                                               long duplicatePairSelection,
                                               long epoch, long openingEpoch) {
        if (elapsedMs < 800L || lockedFps <= 0 || epoch != openingEpoch ||
                syntheticQuotaSkipped != 0L || phaseClamped != 0L ||
                syntheticNotReady != 0L ||
                duplicatePairSelection != 0L) return false;
        double promotedHz = promoted * 1000.0 / elapsedMs;
        // A selected slot without a usable retained endpoint (including a
        // missing source-funded synthetic credit) is source/scheduler
        // unavailability, not evidence that dense rendering missed its
        // deadline.  Allowing even a small percentage here is algebraically
        // unsafe: the same missing slots can lower actualPresentHz beneath the
        // 96% cadence threshold and falsely blame the GPU.  Dense attribution
        // is valid only when every selected slot had its required source
        // evidence; a genuinely slow renderer still reaches this gate with
        // dueNoEndpoint == 0 and a low completed-present rate.
        return promotedHz >= lockedFps * .92 && dueNoEndpoint == 0L;
    }

    /** Completes the triggering callback's wall accounting before preserving
     * its negative v32 evidence, then rejects before another callback can use
     * dense motion. Logging is diagnostic and must never prevent teardown. */
    private void finalizeDenseCadenceReject() {
        pendingDenseCadenceReject = false;
        long now = System.nanoTime();
        long windowElapsedMs = Math.max(1L,
                (now - healthWindowStartNanos) / 1_000_000L);
        try {
            logSplitHealth(now, windowElapsedMs,
                    pendingDenseHealthPresents, pendingDenseHealthGenerated,
                    pendingDenseHealthPromoted,
                    schedulerDueSelectedCount() - lastHealthDueSelected,
                    schedulerDueNoEndpointCount() - lastHealthDueNoEndpoint,
                    schedulerDuePhaseClampedCount() - lastHealthDuePhaseClamped,
                    schedulerRealPriorityCount() - lastHealthRealPriority,
                    schedulerSyntheticQuotaSkippedCount() -
                            lastHealthSyntheticQuotaSkipped,
                    schedulerPresentationEpoch(),
                    schedulerSyntheticSelectedCount() -
                            lastHealthSyntheticSelected,
                    schedulerSyntheticPairCreatedCount() -
                            lastHealthSyntheticPairCreated,
                    schedulerSyntheticNotReadyCount() -
                            lastHealthSyntheticNotReady,
                    schedulerDuplicatePairSelectionCount() -
                            lastHealthDuplicatePairSelection);
        } catch (RuntimeException logFailure) {
            Log.e(TAG, "Unable to preserve rejected dense health window generator=" +
                    generatorId, logFailure);
        } finally {
            try {
                rejectDense("surface-cadence-below-reported-output", null);
            } finally {
                healthWindowStartNanos = now;
                lastHealthPresents = presents;
                lastHealthGenerated = generatedPresents;
                lastHealthPromoted = promotedFrameCount;
                updateSchedulerHealthBaseline();
                pendingDenseHealthPresents = 0L;
                pendingDenseHealthGenerated = 0L;
                pendingDenseHealthPromoted = 0L;
            }
        }
    }

    private String healthKey(long sequence, long start, long end) {
        return " generator=" + generatorId + " role=" + displayRole +
                " displayId=" + displayId + " proofContract=" +
                activeProofContract() + " proofSchemaVersion=" +
                activeProofSchemaVersion() + " healthSequence=" + sequence +
                " presents=" + presents + " windowStartNs=" + start +
                " windowEndNs=" + end;
    }

    private void updateSchedulerHealthBaseline() {
        lastHealthDueSelected = schedulerDueSelectedCount();
        lastHealthDueNoEndpoint = schedulerDueNoEndpointCount();
        lastHealthDuePhaseClamped = schedulerDuePhaseClampedCount();
        lastHealthRealPriority = schedulerRealPriorityCount();
        lastHealthSyntheticQuotaSkipped =
                schedulerSyntheticQuotaSkippedCount();
        lastHealthSyntheticSelected = schedulerSyntheticSelectedCount();
        lastHealthSyntheticPairCreated =
                schedulerSyntheticPairCreatedCount();
        lastHealthSyntheticNotReady = schedulerSyntheticNotReadyCount();
        lastHealthDuplicatePairSelection =
                schedulerDuplicatePairSelectionCount();
        lastHealthPresentationCallbacks = schedulerPresentationCallbackCount();
        lastHealthSyntheticQuotaPending = schedulerSyntheticQuotaPending();
        lastHealthPresentationEpoch = schedulerPresentationEpoch();
    }

    private void resetHealthWindowAfterStreamChange() {
        healthWindowStartNanos = System.nanoTime();
        lastHealthPresents = presents;
        lastHealthGenerated = generatedPresents;
        lastHealthPromoted = promotedFrameCount;
        updateSchedulerHealthBaseline();
    }

    private void logSplitHealth(long now, long windowElapsedMs,
                                long windowPresents, long windowGenerated,
                                long windowPromoted, long windowDueSelected,
                                long windowDueNoEndpoint,
                                long windowDuePhaseClamped,
                                long windowRealPriority,
                                long windowSyntheticQuotaSkipped,
                                long windowPresentationEpoch,
                                long windowSyntheticSelected,
                                long windowSyntheticPairCreated,
                                long windowSyntheticNotReady,
                                long windowDuplicatePairSelection) {
        long sequence = ++healthSequence;
        String key = healthKey(sequence, healthWindowStartNanos, now);
        String base = "Presentation health base" + key +
                " windowElapsedMs=" + windowElapsedMs +
                " windowPresents=" + windowPresents +
                " windowPresentationCallbacks=" +
                        (schedulerPresentationCallbackCount() -
                                lastHealthPresentationCallbacks) +
                " presentationTimingMode=" + PRESENTATION_TIMING_MODE +
                " cadenceRejectConsecutiveWindows=" +
                        DENSE_CADENCE_REJECT_CONSECUTIVE_WINDOWS +
                " windowDueNoEndpoint=" + windowDueNoEndpoint +
                " windowGenerated=" + windowGenerated +
                " windowPromoted=" + windowPromoted +
                " windowRealPriority=" + windowRealPriority +
                " windowPresentationEpoch=" + windowPresentationEpoch +
                " proofEvidencePresentationEpoch=" +
                        proofEvidencePresentationEpoch +
                " proofEvidenceEnqueuedInEpoch=" +
                        proofEvidenceEnqueuedInEpoch +
                " endpointFifoCoalesced=" + endpointFifoCoalesced +
                " endpointTimestampCorrections=" + endpointTimestampCorrections +
                " denseDiagnosticLastTargetSourceNs=" +
                        denseDiagnosticLastTargetSourceNs +
                " windowSyntheticSelected=" + windowSyntheticSelected +
                " windowDuplicatePairSelection=" + windowDuplicatePairSelection +
                " denseExtensionRequired=1 generated=" + generatedPresents +
                " real=" + realFrameCount + " promoted=" + promotedFrameCount +
                " submitted=" + submittedFrameCount + " producerHz=" +
                String.format(java.util.Locale.US, "%.2f",
                        frameRate.measuredProducerHz()) +
                " lockedFps=" + frameRate.lockedSourceFps() +
                " outputFps=" + frameRate.outputFps() +
                " panelFps=" + frameRate.panelFps() +
                " latticeRegionSamples=" + latticeRegionSamples +
                " latticeBackwardCoherentRegions=" + latticeBackwardCoherentRegions +
                " latticeForwardCoherentRegions=" + latticeForwardCoherentRegions +
                " latticeBackwardBoundaryRegions=" + latticeBackwardBoundaryRegions +
                " latticeForwardBoundaryRegions=" + latticeForwardBoundaryRegions +
                " latticeBackwardCoherentBoundaryRegions=" + latticeBackwardCoherentBoundaryRegions +
                " latticeForwardCoherentBoundaryRegions=" + latticeForwardCoherentBoundaryRegions +
                " latticeBackwardCoherentRegionCount=" + latticeBackwardCoherentRegionCount +
                " latticeForwardCoherentRegionCount=" + latticeForwardCoherentRegionCount +
                " latticeBackwardBoundaryRegionCount=" + latticeBackwardBoundaryRegionCount +
                " latticeForwardBoundaryRegionCount=" + latticeForwardBoundaryRegionCount +
                " latticeBackwardCoherentBoundaryRegionCount=" + latticeBackwardCoherentBoundaryRegionCount +
                " latticeForwardCoherentBoundaryRegionCount=" + latticeForwardCoherentBoundaryRegionCount +
                " latticeBackwardPeakSupport=" + latticeBackwardPeakSupport +
                " latticeForwardPeakSupport=" + latticeForwardPeakSupport +
                " regionalFlowRegionSamples=" + regionalFlowRegionSamples +
                " regionalBackwardSupportedRegions=" + regionalBackwardSupportedRegions +
                " regionalForwardSupportedRegions=" + regionalForwardSupportedRegions +
                " regionalBackwardNeighborRegions=" + regionalBackwardNeighborRegions +
                " regionalForwardNeighborRegions=" + regionalForwardNeighborRegions +
                " regionalBackwardConstantNeighborRegions=" + regionalBackwardConstantNeighborRegions +
                " regionalForwardConstantNeighborRegions=" + regionalForwardConstantNeighborRegions +
                " regionalBackwardGradientNeighborRegions=" + regionalBackwardGradientNeighborRegions +
                " regionalForwardGradientNeighborRegions=" + regionalForwardGradientNeighborRegions +
                " regionalBackwardAcceptedRegions=" + regionalBackwardAcceptedRegions +
                " regionalForwardAcceptedRegions=" + regionalForwardAcceptedRegions +
                " regionalBackwardAcceptedBoundaryRegions=" + regionalBackwardAcceptedBoundaryRegions +
                " regionalForwardAcceptedBoundaryRegions=" + regionalForwardAcceptedBoundaryRegions +
                " regionalBackwardCycleAcceptedRegions=" + regionalBackwardCycleAcceptedRegions +
                " regionalForwardCycleAcceptedRegions=" + regionalForwardCycleAcceptedRegions +
                " regionalBackwardAcceptedRegionCount=" + regionalBackwardAcceptedRegionCount +
                " regionalForwardAcceptedRegionCount=" + regionalForwardAcceptedRegionCount +
                " regionalBackwardAcceptedBoundaryRegionCount=" + regionalBackwardAcceptedBoundaryRegionCount +
                " regionalForwardAcceptedBoundaryRegionCount=" + regionalForwardAcceptedBoundaryRegionCount +
                " regionalBackwardCycleAcceptedRegionCount=" + regionalBackwardCycleAcceptedRegionCount +
                " regionalForwardCycleAcceptedRegionCount=" + regionalForwardCycleAcceptedRegionCount +
                " regionalBackwardSupportedRegionCount=" + regionalBackwardSupportedRegionCount +
                " regionalForwardSupportedRegionCount=" + regionalForwardSupportedRegionCount +
                " regionalBackwardNeighborRegionCount=" + regionalBackwardNeighborRegionCount +
                " regionalForwardNeighborRegionCount=" + regionalForwardNeighborRegionCount +
                " regionalBackwardConstantNeighborRegionCount=" + regionalBackwardConstantNeighborRegionCount +
                " regionalForwardConstantNeighborRegionCount=" + regionalForwardConstantNeighborRegionCount +
                " regionalBackwardGradientNeighborRegionCount=" + regionalBackwardGradientNeighborRegionCount +
                " regionalForwardGradientNeighborRegionCount=" + regionalForwardGradientNeighborRegionCount +
                " regionalBackwardPeakSupport=" + regionalBackwardPeakSupport +
                " regionalForwardPeakSupport=" + regionalForwardPeakSupport +
                " regionalBackwardPeakConfidence=" + regionalBackwardPeakConfidence +
                " regionalForwardPeakConfidence=" + regionalForwardPeakConfidence +
                " activeMotionVectors=" + activeMotionVectors +
                " confidentMotionVectors=" + confidentMotionVectors +
                " motionVectorCells=" + (PROOF_WIDTH * PROOF_HEIGHT) +
                " proofSamples=" + proofSamples +
                " syntheticProofSamples=" + syntheticProofSamples +
                " syntheticDistinctFromEndpoints=" + syntheticDistinctFromEndpoints +
                " changingProofOutputs=" + changingProofOutputs +
                " eligibleSyntheticPixels=" + eligibleSyntheticPixels +
                " substantiveSyntheticPixels=" + substantiveSyntheticPixels +
                " nonCrossfadeSyntheticPixels=" + nonCrossfadeSyntheticPixels +
                " motionEligibleProofSamples=" + motionEligibleProofSamples +
                " motionCorrelatedProofSamples=" + motionCorrelatedProofSamples +
                " v21DirectionallyEligibleSyntheticPixels=" + motionEligibleSyntheticPixels +
                " v21CorrectVectorPredictedSyntheticPixels=" + motionSynthesizedSyntheticPixels +
                denseDiagnosticDirectionTelemetry("Backward", 0) +
                denseDiagnosticDirectionTelemetry("Forward", 1);
        logBoundedHealth(base);
        String extension = "Presentation health dense-extension" + key +
                " proofEvidencePresentationEpoch=" +
                        proofEvidencePresentationEpoch +
                " denseEnabled=" + (densePyramidEnabled ? 1 : 0) +
                " densePromotions=" + densePromotions + " densePasses=" + densePasses +
                " denseCpuSubmitTotalUs=" + denseCpuSubmitTotalUs +
                " denseCpuSubmitMaxUs=" + denseCpuSubmitMaxUs +
                " denseCpuSubmitLastUs=" + denseCpuSubmitLastUs +
                " denseGpuCompleteTotalUs=" + denseGpuCompleteTotalUs +
                " denseGpuCompleteMaxUs=" + denseGpuCompleteMaxUs +
                " denseGpuCompleteLastUs=" + denseGpuCompleteLastUs +
                " denseGpuBudgetUs=" + DENSE_GPU_BUDGET_US +
                " denseTimedPairs=" + denseTimedPairs +
                " denseWarpSequence=" + denseWarpSequence +
                " denseWarpMaxCompletedSequence=" + denseWarpMaxCompletedSequence +
                " denseTimerPending=" + (denseGpuTimer == null ? 0 : denseGpuTimer.pendingCount()) +
                " denseTimerDisjoint=" + denseTimerDisjoint +
                " denseTimerUnavailable=" + denseTimerUnavailable +
                " denseTimerStale=" + denseTimerStale +
                " denseTimerMaxQueueAge=" + denseTimerMaxQueueAge +
                " densePerformanceRejected=" + (densePerformanceRejected ? 1 : 0) +
                " denseCalibrationRuns=" + denseCalibrationRuns +
                " denseCalibrationUs=" + denseCalibrationUs +
                " denseCombinedPairMaxWarpP95Us=" + (denseTimedPairMaxUs + denseStageP95(DenseGpuTimer.VISIBLE_WARP)) +
                " densePromotionWallSamples=" + densePromotionWallSamples +
                " densePromotionWallTotalUs=" + densePromotionWallTotalUs +
                " densePromotionWallP95Us=" + denseWallP95(densePromotionWallObservedUs, densePromotionWallSamples) +
                " densePromotionWallMaxUs=" + densePromotionWallMaxUs +
                " denseSignatureWallSamples=" + denseSignatureWallSamples +
                " denseSignatureWallTotalUs=" + denseSignatureWallTotalUs +
                " denseSignatureWallP95Us=" + denseWallP95(denseSignatureWallObservedUs, denseSignatureWallSamples) +
                " denseSignatureWallMaxUs=" + denseSignatureWallMaxUs +
                " denseProofWallSamples=" + denseProofWallSamples +
                " denseProofWallTotalUs=" + denseProofWallTotalUs +
                " denseProofWallP95Us=" + denseWallP95(denseProofWallObservedUs, denseProofWallSamples) +
                " denseProofWallMaxUs=" + denseProofWallMaxUs +
                " denseSignatureSequence=" + denseSignatureSequence +
                " denseSignatureReady=" + denseSignatureReady +
                " denseSignatureUnavailable=" + denseSignatureUnavailable +
                " denseSignatureMaxQueueAge=" + denseSignatureMaxQueueAge +
                " denseSignaturePending=" + (denseGpuTimer == null ? 0 : denseGpuTimer.pendingSignatures()) +
                " denseSignatureCapability=" + denseSignatureCapability() +
                " denseSignatureRequestedGles=" + requestedEglContextMajor +
                " denseSignatureActualGlesMajor=" + actualEglContextMajor +
                " denseSignatureActualGlesMinor=" + actualEglContextMinor +
                " denseSignatureSelfTests=" + (denseSignatureCapability() == DENSE_SIGNATURE_CAP_READY ? 1 : 0) +
                " denseRuntimeCadenceSource=app-present-window denseOfflineCadenceSource=surfaceflinger-layer-timestamps" +
                " denseVariant=" + denseVariant() +
                " denseAnalysisWidth=" + denseAnalysisWidth +
                " denseAnalysisHeight=" + denseAnalysisHeight +
                " denseSolveTexelsPerPromotion=" + denseSolveTexelsPerPromotion() +
                " denseTotalTexelsPerPromotion=" + denseTotalTexelsPerPromotion() +
                " denseMaxFlowPixels=" + (int) DENSE_MAX_FLOW_PIXELS +
                " denseProofCells=" + denseProofCells +
                " denseBackwardValidCells=" + denseBackwardValidCells +
                " denseForwardValidCells=" + denseForwardValidCells +
                " denseDiagnosticCells=" + denseDiagnosticCells +
                " denseDiagnosticTiles=" + denseDiagnosticTiles +
                " denseDiagnosticPackedCells=" + denseDiagnosticPackedCells +
                " denseDiagnosticMaskLayout=packed-nearest-bf-v1" +
                " denseDiagnosticPartitionErrors=" + denseDiagnosticPartitionErrors +
                " denseDiagnosticReservedBitErrors=" + denseDiagnosticReservedBitErrors +
                " denseDiagnosticMaskErrors=" + denseDiagnosticMaskErrors +
                " denseDiagnosticLastAtlasSequence=" + denseDiagnosticLastAtlasSequence +
                " denseDiagnosticLastPairSequence=" + denseDiagnosticLastPairSequence +
                " denseDiagnosticLastPreviousEndpoint=" +
                        denseDiagnosticLastPreviousEndpoint +
                " denseDiagnosticLastCurrentEndpoint=" +
                        denseDiagnosticLastCurrentEndpoint +
                denseStageTelemetry() +
                " denseProofAtlasCapability=" + (denseGpuTimer == null ? 0 : denseGpuTimer.proofAtlasCapability()) +
                " denseProofAtlasLayout=" + PROOF_ATLAS_LAYOUT_VERSION +
                " denseProofAtlasEnqueued=" + proofAtlasEnqueued +
                " denseProofAtlasCompleted=" + proofAtlasCompleted +
                " proofEvidenceAccepted=" + proofEvidenceAccepted +
                " proofEvidenceExcluded=" + proofEvidenceExcluded +
                " proofEvidenceLastAcceptedAtlasSequence=" +
                        proofEvidenceLastAcceptedAtlasSequence +
                " denseProofAtlasPending=" + (denseGpuTimer == null ? 0 : denseGpuTimer.pendingProofAtlases()) +
                " denseProofAtlasMaxQueueAge=" + proofAtlasMaxQueueAge +
                " denseProofAtlasTimeoutPolls=" + proofAtlasTimeoutPolls +
                " denseProofAtlasRingFull=" + proofAtlasRingFull +
                " denseProofAtlasErrors=" + proofAtlasErrors +
                " denseProofAtlasTagErrors=" + proofAtlasTagErrors +
                " denseProofAtlasDiscarded=" + proofAtlasDiscarded +
                " denseProofAtlasSyncFallback=" + proofAtlasSynchronousFallback +
                " denseCallbackDeltaSamples=" + callbackDeltaSamples +
                " denseCallbackDeltaTotalUs=" + callbackDeltaTotalUs +
                " denseCallbackDeltaMaxUs=" + callbackDeltaMaxUs +
                " denseCallbackLateCount=" + callbackLateCount +
                wallTelemetry("Present", densePresentWallObservedUs, densePresentWallSamples, densePresentWallTotalUs, densePresentWallMaxUs) +
                wallTelemetry("Swap", denseSwapWallObservedUs, denseSwapWallSamples, denseSwapWallTotalUs, denseSwapWallMaxUs) +
                wallTelemetry("ProofEnqueue", denseProofEnqueueWallObservedUs, denseProofEnqueueWallSamples, denseProofEnqueueWallTotalUs, denseProofEnqueueWallMaxUs) +
                wallTelemetry("ProofPoll", denseProofPollWallObservedUs, denseProofPollWallSamples, denseProofPollWallTotalUs, denseProofPollWallMaxUs);
        logBoundedHealth(extension);
    }

    private static void logBoundedHealth(String record) {
        int bytes = record.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
        if (bytes > HEALTH_LOG_MAX_UTF8_BYTES)
            throw new IllegalStateException("split health record exceeds " +
                    HEALTH_LOG_MAX_UTF8_BYTES + " UTF-8 bytes: " + bytes);
        Log.i(TAG, record);
    }

    private String wallTelemetry(String name, long[] values, long samples,
                                 long total, long max) {
        return " dense" + name + "WallSamples=" + samples +
                " dense" + name + "WallTotalUs=" + total +
                " dense" + name + "WallP95Us=" + denseWallP95(values, samples) +
                " dense" + name + "WallMaxUs=" + max;
    }

    private String denseDiagnosticDirectionTelemetry(String name, int direction) {
        return " dense" + name + "ActiveCells=" +
                denseDiagnosticActiveCells[direction] +
                " dense" + name + "InBoundsCells=" +
                denseDiagnosticInBoundsCells[direction] +
                " dense" + name + "CycleValidCells=" +
                denseDiagnosticCycleValidCells[direction] +
                " dense" + name + "PhotometricValidCells=" +
                denseDiagnosticPhotometricValidCells[direction] +
                " dense" + name + "TextureValidCells=" +
                denseDiagnosticTextureValidCells[direction] +
                " dense" + name + "SaturatedCells=" +
                denseDiagnosticSaturatedCells[direction] +
                " dense" + name + "OutOfBoundsCells=" +
                denseDiagnosticOutOfBoundsCells[direction] +
                " dense" + name + "CoveredTiles=" +
                denseDiagnosticCoveredTiles[direction] +
                " dense" + name + "CoveredTileMask=" +
                denseDiagnosticCoveredTileMask[direction];
    }

    private void refreshQualificationProofState() {
        boolean wasDense = densePyramidEnabled;
        boolean requested = false;
        boolean denseRequested = false;
        boolean v27Requested = false;
        boolean v28Requested = false;
        try {
            requested = qualificationProofSwitch.enabled();
        } catch (RuntimeException ignored) {}
        try {
            denseRequested = requested && densePyramidSwitch.enabled();
        } catch (RuntimeException ignored) {}
        if (denseRequested) {
            try {
                v27Requested = denseV27ReducedAnalysisSwitch.enabled();
            } catch (RuntimeException ignored) {}
            try {
                v28Requested = denseV28ReducedAnalysisSwitch.enabled();
            } catch (RuntimeException ignored) {}
        }
        if (denseRequested && ((v27Requested && v28Requested) ||
                v27Requested != denseV27ReducedAnalysisRequested ||
                v28Requested != denseV28ReducedAnalysisRequested)) {
            denseRequested = false;
            Log.e(TAG, "Dense pyramid variant change requires a new generator" +
                    " generator=" + generatorId + " startupV27=" +
                    denseV27ReducedAnalysisRequested + " requestedV27=" + v27Requested +
                    " startupV28=" + denseV28ReducedAnalysisRequested +
                    " requestedV28=" + v28Requested);
        }
        boolean nextDense = false;
        if (denseRequested && !densePyramidUnavailable) {
            try {
                if (denseGpuTimer == null) denseGpuTimer = DenseGpuTimer.create();
                ensureDenseResources();
                if (denseCalibrationRuns == 0) runDenseIntrusiveCalibration();
                nextDense = true;
            } catch (RuntimeException failure) {
                densePyramidUnavailable = true;
                Log.e(TAG, "Dense pyramid unavailable (fail closed) generator=" + generatorId,
                        failure);
            }
        }
        if (nextDense) frameRate.setGenerationAvailable(true);
        else if (denseRequested) frameRate.setGenerationAvailable(false);
        if (!nextDense && (wasDense || denseGpuTimer != null))
            teardownDenseEpoch("settings-disabled");
        if (requested == qualificationProofEnabled && nextDense == densePyramidEnabled)
            return;
        qualificationProofEnabled = requested;
        densePyramidEnabled = nextDense;
        if (nextDense) {
            healthWindowStartNanos = System.nanoTime();
            lastHealthPresents = presents;
            lastHealthGenerated = generatedPresents;
            lastHealthPromoted = promotedFrameCount;
            updateSchedulerHealthBaseline();
        }
        if (requested) {
            activeMotionVectors = 0;
            confidentMotionVectors = 0;
            proofSamples = 0;
            syntheticProofSamples = 0;
            syntheticDistinctFromEndpoints = 0;
            changingProofOutputs = 0;
            eligibleSyntheticPixels = 0;
            substantiveSyntheticPixels = 0;
            nonCrossfadeSyntheticPixels = 0;
            motionEligibleProofSamples = 0;
            motionCorrelatedProofSamples = 0;
            motionEligibleSyntheticPixels = 0;
            motionSynthesizedSyntheticPixels = 0;
            densePromotions = 0;
            densePasses = 0;
            denseCpuSubmitTotalUs = 0;
            denseCpuSubmitMaxUs = 0;
            denseCpuSubmitLastUs = 0;
            denseGpuCompleteTotalUs = 0;
            denseGpuCompleteMaxUs = 0;
            denseGpuCompleteLastUs = 0;
            for (int stage = 0; stage < denseStageTotalUs.length; ++stage) {
                denseStageTotalUs[stage] = 0;
                denseStageMaxUs[stage] = 0;
                denseStageSamples[stage] = 0;
                java.util.Arrays.fill(denseStageObservedUs[stage], 0L);
            }
            java.util.Arrays.fill(densePairSequence, 0L);
            java.util.Arrays.fill(densePairTotalUs, 0L);
            java.util.Arrays.fill(densePairMask, 0);
            denseTimedPairs = 0;
            denseTimedPairTotalUs = 0;
            denseTimedPairMaxUs = 0;
            denseWarpSequence = 0;
            denseWarpMaxCompletedSequence = 0;
            java.util.Arrays.fill(denseWarpCompletedSequence, 0L);
            denseTimerUnavailable = 0;
            denseTimerDisjoint = 0;
            denseTimerStale = 0;
            denseTimerMaxQueueAge = 0;
            densePerformanceRejected = false;
            pendingDenseCadenceReject = false;
            denseCadenceFailureWindows = 0;
            pendingDenseHealthPresents = 0L;
            pendingDenseHealthGenerated = 0L;
            pendingDenseHealthPromoted = 0L;
            densePromotionWallSamples = 0;
            densePromotionWallTotalUs = 0;
            densePromotionWallMaxUs = 0;
            denseSignatureWallSamples = 0;
            denseSignatureWallTotalUs = 0;
            denseSignatureWallMaxUs = 0;
            denseProofWallSamples = 0;
            denseProofWallTotalUs = 0;
            denseProofWallMaxUs = 0;
            denseSignatureSequence = 0;
            denseSignatureReady = 0;
            denseSignatureUnavailable = 0;
            denseSignatureMaxQueueAge = 0;
            denseSignatureBaselineReady = false;
            java.util.Arrays.fill(densePromotionWallObservedUs, 0L);
            java.util.Arrays.fill(denseSignatureWallObservedUs, 0L);
            java.util.Arrays.fill(denseProofWallObservedUs, 0L);
            callbackDeltaSamples = 0;
            callbackDeltaTotalUs = 0;
            callbackDeltaMaxUs = 0;
            callbackLateCount = 0;
            lastCallbackFrameTimeNs = 0L;
            densePresentWallSamples = 0;
            densePresentWallTotalUs = 0;
            densePresentWallMaxUs = 0;
            denseSwapWallSamples = 0;
            denseSwapWallTotalUs = 0;
            denseSwapWallMaxUs = 0;
            denseProofEnqueueWallSamples = 0;
            denseProofEnqueueWallTotalUs = 0;
            denseProofEnqueueWallMaxUs = 0;
            denseProofPollWallSamples = 0;
            denseProofPollWallTotalUs = 0;
            denseProofPollWallMaxUs = 0;
            java.util.Arrays.fill(densePresentWallObservedUs, 0L);
            java.util.Arrays.fill(denseSwapWallObservedUs, 0L);
            java.util.Arrays.fill(denseProofEnqueueWallObservedUs, 0L);
            java.util.Arrays.fill(denseProofPollWallObservedUs, 0L);
            denseProofCells = 0;
            denseBackwardValidCells = 0;
            denseForwardValidCells = 0;
            denseDiagnosticCells = 0;
            denseDiagnosticTiles = 0;
            java.util.Arrays.fill(denseDiagnosticActiveCells, 0L);
            java.util.Arrays.fill(denseDiagnosticInBoundsCells, 0L);
            java.util.Arrays.fill(denseDiagnosticCycleValidCells, 0L);
            java.util.Arrays.fill(denseDiagnosticPhotometricValidCells, 0L);
            java.util.Arrays.fill(denseDiagnosticTextureValidCells, 0L);
            java.util.Arrays.fill(denseDiagnosticSaturatedCells, 0L);
            java.util.Arrays.fill(denseDiagnosticOutOfBoundsCells, 0L);
            java.util.Arrays.fill(denseDiagnosticCoveredTiles, 0L);
            java.util.Arrays.fill(denseDiagnosticCoveredTileMask, 0);
            denseDiagnosticLastAtlasSequence = 0L;
            denseDiagnosticLastPairSequence = 0L;
            denseDiagnosticLastPreviousEndpoint = 0L;
            denseDiagnosticLastCurrentEndpoint = 0L;
            denseDiagnosticLastTargetSourceNs = 0L;
            denseDiagnosticMaskErrors = 0L;
            denseDiagnosticPackedCells = 0L;
            denseDiagnosticPartitionErrors = 0L;
            denseDiagnosticReservedBitErrors = 0L;
            proofAtlasEnqueued = 0;
            proofAtlasCompleted = 0;
            proofEvidencePresentationEpoch = schedulerPresentationEpoch();
            proofEvidenceEnqueuedInEpoch = 0;
            proofEvidenceAccepted = 0;
            proofEvidenceExcluded = 0;
            proofEvidenceLastAcceptedAtlasSequence = 0;
            proofAtlasSequence = 0;
            proofAtlasMaxQueueAge = 0;
            proofAtlasTimeoutPolls = 0;
            proofAtlasRingFull = 0;
            proofAtlasErrors = 0;
            proofAtlasTagErrors = 0;
            proofAtlasDiscarded = 0;
            proofAtlasSynchronousFallback = 0;
            lastProofHash = 0L;
            lastProofPresent = presents - PROOF_SAMPLE_INTERVAL +
                    (generatorId * 17L) % PROOF_SAMPLE_INTERVAL;
            if (nextDense) {
                // v22 regional globals are not part of the dense contract.
                // Clear them so synthesis cannot inherit a stale fallback.
                clearMotionField(globalFlowTextures[0], REGIONAL_FLOW_WIDTH,
                        REGIONAL_FLOW_HEIGHT);
                clearMotionField(globalFlowTextures[1], REGIONAL_FLOW_WIDTH,
                        REGIONAL_FLOW_HEIGHT);
                clearDenseFields();
            }
        }
        Log.i(TAG, "Qualification proof generator=" + generatorId +
                " enabled=" + requested +
                " proofContract=" + activeProofContract() +
                " proofSchemaVersion=" + activeProofSchemaVersion() +
                " denseRequested=" + denseRequested +
                " denseEnabled=" + densePyramidEnabled +
                " denseVariant=" + denseVariant());
    }

    private String activeProofContract() {
        if (!densePyramidEnabled) return PROOF_CONTRACT;
        return denseProofContract();
    }

    private int activeProofSchemaVersion() {
        if (!densePyramidEnabled) return PROOF_SCHEMA_VERSION;
        return denseProofSchemaVersion();
    }

    private String denseProofContract() {
        return denseV28ReducedAnalysisRequested ? DENSE_V28_PROOF_CONTRACT :
                denseV27ReducedAnalysisRequested ?
                DENSE_V27_PROOF_CONTRACT : DENSE_PROOF_CONTRACT;
    }

    private int denseProofSchemaVersion() {
        return denseV28ReducedAnalysisRequested ? DENSE_V28_PROOF_SCHEMA_VERSION :
                denseV27ReducedAnalysisRequested ?
                DENSE_V27_PROOF_SCHEMA_VERSION : DENSE_PROOF_SCHEMA_VERSION;
    }

    private String denseVariant() {
        return denseV28ReducedAnalysisRequested ?
                "fragment-128x72-v39-present-timed-vector-trajectory" :
                denseV27ReducedAnalysisRequested ? "fragment-192x108-v27" :
                "fragment-256x144-v26";
    }

    private long denseSolveTexelsPerPromotion() {
        long oneDirection = 0L;
        for (int level = 0; level < DENSE_LEVELS; ++level)
            oneDirection += (long) denseLevelWidths[level] * denseLevelHeights[level] *
                    DENSE_LEVEL_ITERATIONS[level];
        return oneDirection * 2L;
    }

    private long denseTotalTexelsPerPromotion() {
        long pyramid = 2L * ((long) denseLevelWidths[1] * denseLevelHeights[1] +
                (long) denseLevelWidths[2] * denseLevelHeights[2]);
        long validation = 2L * denseLevelWidths[0] * denseLevelHeights[0];
        return denseSolveTexelsPerPromotion() + pyramid + validation;
    }

    private int activeBackwardFlow() {
        return densePyramidEnabled ? denseValidatedTextures[0] : flowTextures[2];
    }

    private int activeForwardFlow() {
        return densePyramidEnabled ? denseValidatedTextures[1] : reverseFlowTextures[2];
    }

    private float activeFlowLimitPixels() {
        float limit = flowLimitPixels(historyWidth, historyHeight);
        return densePyramidEnabled ? Math.min(DENSE_MAX_FLOW_PIXELS, limit) : limit;
    }

    private void drawMotionFrame(float phase) {
        GLES20.glUseProgram(interpolateProgram);
        bindQuad(interpolateProgram);
        bindTexture(interpolateProgram, "uPrevious", historyTextures[previousIndex], 0);
        bindTexture(interpolateProgram, "uCurrent", historyTextures[currentIndex], 1);
        bindTexture(interpolateProgram, "uBackwardMotion", activeBackwardFlow(), 2);
        bindTexture(interpolateProgram, "uForwardMotion", activeForwardFlow(), 3);
        bindTexture(interpolateProgram, "uGlobalBackwardMotion", globalFlowTextures[0], 4);
        bindTexture(interpolateProgram, "uGlobalForwardMotion", globalFlowTextures[1], 5);
        float flowLimit = activeFlowLimitPixels();
        uniform2(interpolateProgram, "uFlowRange",
                flowLimit / Math.max(1f, historyWidth),
                flowLimit / Math.max(1f, historyHeight));
        GLES20.glUniform1f(GLES20.glGetUniformLocation(
                interpolateProgram, "uPhase"), phase);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(
                interpolateProgram, "uDenseEncoding"), densePyramidEnabled ? 1f : 0f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    /**
     * Samples actual shader output, plus both real endpoints, into a tiny FBO.
     * A synthesized frame is counted only when its pixel hash differs from
     * both endpoints. This makes a repeated-frame or nearest-endpoint
     * smokescreen fail even if its callback and SurfaceFlinger rates say 120.
     */
    private void sampleFrameProof(float phase) {
        if (proofPixels == null || promotedFrameCount < 2) return;
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                GLES20.GL_TEXTURE_2D, proofTexture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE) {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            return;
        }
        GLES20.glViewport(0, 0, PROOF_WIDTH, PROOF_HEIGHT);
        // Correlate the exact current motion field and shader output in this
        // presentation callback. The window buffer was drawn with these same
        // textures, program and phase immediately before this proof replay.
        drawMotionFrame(0f);
        long previousHash = readProofHash(proofPrevious);
        drawMotionFrame(1f);
        long currentHash = readProofHash(proofCurrent);
        drawMotionFrame(phase);
        long outputHash = readProofHash(proofOutput);
        drawPredictionProof(phase, false);
        readProofHash(proofPredicted);
        drawPredictionProof(phase, true);
        readProofHash(proofInverse);
        drawProofFlow();
        readProofHash(proofFlow);
        if (densePyramidEnabled) sampleDenseFlowTelemetry();
        // Keep the legacy regional accounting populated for cross-contract
        // evidence hierarchy checks. It is diagnostic only under v24; the
        // selected visible field and quality gates are dense.
        sampleRegionalFlowTelemetry();
        analyzeProofPayload(phase, previousHash, currentHash, outputHash);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        GLES20.glViewport(0, 0, outputWidth, outputHeight);
    }

    private void analyzeProofPayload(float phase, long previousHash,
                                     long currentHash, long outputHash) {
        ++proofSamples;
        if (lastProofHash != 0L && outputHash != lastProofHash) ++changingProofOutputs;
        lastProofHash = outputHash;
        if (phase > 0.15f && phase < 0.85f) {
            ++syntheticProofSamples;
            if (outputHash != previousHash && outputHash != currentHash)
                ++syntheticDistinctFromEndpoints;
            int eligible = 0;
            int substantive = 0;
            int nonCrossfade = 0;
            int motionEligible = 0;
            int motionSynthesized = 0;
            int sampledFlowActive = 0;
            int sampledFlowConfident = 0;
            int pixels = PROOF_WIDTH * PROOF_HEIGHT;
            for (int pixel = 0; pixel < pixels; ++pixel) {
                int offset = pixel * 4;
                int endpointSpan = 0;
                int outputFromPrevious = 0;
                int outputFromCurrent = 0;
                int outputFromCrossfade = 0;
                for (int channel = 0; channel < 3; ++channel) {
                    int a = proofPrevious[offset + channel] & 0xff;
                    int b = proofCurrent[offset + channel] & 0xff;
                    int value = proofOutput[offset + channel] & 0xff;
                    int fixedCrossfade = Math.round(a * (1f - phase) + b * phase);
                    endpointSpan += Math.abs(a - b);
                    outputFromPrevious += Math.abs(value - a);
                    outputFromCurrent += Math.abs(value - b);
                    outputFromCrossfade += Math.abs(value - fixedCrossfade);
                }
                int flowRed = proofFlow[offset] & 0xff;
                int flowGreen = proofFlow[offset + 1] & 0xff;
                int flowConfidence = proofFlow[offset + 2] & 0xff;
                boolean activeFlow = Math.abs(flowRed - 128) > 2 ||
                        Math.abs(flowGreen - 128) > 2;
                if (activeFlow) ++sampledFlowActive;
                if (flowConfidence >= 48) ++sampledFlowConfident;
                // Flat pixels carry no motion evidence. Changed pixels must
                // materially depart from both endpoints and, separately,
                // from the fixed-position alpha blend that creates ghosting.
                if (endpointSpan < 36) continue;
                ++eligible;
                if (outputFromPrevious >= Math.max(9, endpointSpan * 8 / 100) &&
                        outputFromCurrent >= Math.max(9, endpointSpan * 8 / 100))
                    ++substantive;
                if (outputFromCrossfade >= Math.max(9, endpointSpan * 6 / 100))
                    ++nonCrossfade;
                if (activeFlow && flowConfidence >= 48) {
                    int vectorPredictionError = 0;
                    int inverseVectorError = 0;
                    int predictionSeparation = 0;
                    for (int channel = 0; channel < 3; ++channel) {
                        int value = proofOutput[offset + channel] & 0xff;
                        int predicted = proofPredicted[offset + channel] & 0xff;
                        int inverse = proofInverse[offset + channel] & 0xff;
                        vectorPredictionError += Math.abs(value - predicted);
                        inverseVectorError += Math.abs(value - inverse);
                        predictionSeparation += Math.abs(predicted - inverse);
                    }
                    // Only vectors whose correct and inverted predictions are
                    // measurably distinguishable carry directional evidence.
                    if (predictionSeparation < 9) continue;
                    ++motionEligible;
                    // Empirically bind the output to this pixel's decoded
                    // vector. Merely differing from endpoints/crossfade is not
                    // enough: unrelated noise and arbitrary warps must lose to
                    // both the exact shader prediction and an inverse-vector
                    // negative control.
                    if (vectorPredictionError <= 12 &&
                            vectorPredictionError * 4 <= outputFromCrossfade * 3 &&
                            vectorPredictionError * 4 <= inverseVectorError)
                        ++motionSynthesized;
                }
            }
            eligibleSyntheticPixels += eligible;
            substantiveSyntheticPixels += substantive;
            nonCrossfadeSyntheticPixels += nonCrossfade;
            motionEligibleSyntheticPixels += motionEligible;
            motionSynthesizedSyntheticPixels += motionSynthesized;
            activeMotionVectors = sampledFlowActive;
            confidentMotionVectors = sampledFlowConfident;
            if (eligible >= 24 && motionEligible >= 12) {
                ++motionEligibleProofSamples;
                // A correctly translated opaque edge often equals one raw
                // endpoint at a fixed screen coordinate; requiring an
                // intermediate RGB value there mistakes spatial relocation
                // for endpoint copying. Schema 38 instead binds the visible
                // output to an independently re-rendered vector trajectory,
                // requires that it beat the inverted-vector negative control,
                // and still rejects fixed-position alpha blending. The
                // aggregate substantive count remains diagnostic.
                if (nonCrossfade * 2 >= eligible &&
                    motionSynthesized * 5 >= motionEligible * 4)
                    ++motionCorrelatedProofSamples;
            }
        }
    }

    /**
     * Reads the two 12x8 regional reducer fields only during an existing
     * bounded proof callback. Fine-winner A exposes coherent candidate support;
     * gated-flow B/A then expose final confidence and independently recomputed
     * overlapping-window support. Per-region counts distinguish absent coherent
     * candidates, support/neighbor rejection, and reverse-cycle rejection
     * without adding any per-frame CPU readback.
     */
    private void sampleRegionalFlowTelemetry() {
        if (regionalFlowPixels == null) return;
        byte[] backwardWinner = new byte[REGIONAL_FLOW_CELLS * 4];
        byte[] forwardWinner = new byte[REGIONAL_FLOW_CELLS * 4];
        byte[] backward = new byte[REGIONAL_FLOW_CELLS * 4];
        byte[] forward = new byte[REGIONAL_FLOW_CELLS * 4];
        readRegionalFlowPixels(globalCandidateWinnerTextures[0], backwardWinner);
        readRegionalFlowPixels(globalCandidateWinnerTextures[1], forwardWinner);
        readRegionalFlowPixels(globalFlowTextures[0], backward);
        readRegionalFlowPixels(globalFlowTextures[1], forward);
        analyzeRegionalFlowTelemetry(backwardWinner, forwardWinner,
                backward, forward);
    }

    private void analyzeRegionalFlowTelemetry(byte[] backwardWinner,
                                               byte[] forwardWinner,
                                               byte[] backward,
                                               byte[] forward) {
        analyzeRegionalFlowTelemetry(backwardWinner, forwardWinner, backward,
                forward, historyWidth, historyHeight, activeFlowLimitPixels());
    }

    private void analyzeRegionalFlowTelemetry(byte[] backwardWinner,
                                               byte[] forwardWinner,
                                               byte[] backward,
                                               byte[] forward,
                                               int taggedWidth,
                                               int taggedHeight,
                                               float taggedFlowLimit) {
        int backwardCoherent = 0;
        int forwardCoherent = 0;
        int backwardBoundary = 0;
        int forwardBoundary = 0;
        int backwardCoherentBoundary = 0;
        int forwardCoherentBoundary = 0;
        int backwardNeighbor = 0;
        int forwardNeighbor = 0;
        int backwardConstantNeighbor = 0;
        int forwardConstantNeighbor = 0;
        int backwardGradientNeighbor = 0;
        int forwardGradientNeighbor = 0;
        int backwardCandidatePeakSupport = 0;
        int forwardCandidatePeakSupport = 0;
        int backwardAccepted = 0;
        int forwardAccepted = 0;
        int backwardAcceptedBoundary = 0;
        int forwardAcceptedBoundary = 0;
        int backwardCycleAccepted = 0;
        int forwardCycleAccepted = 0;
        int backwardSupported = 0;
        int forwardSupported = 0;
        int backwardPeakSupport = 0;
        int forwardPeakSupport = 0;
        int backwardPeakConfidence = 0;
        int forwardPeakConfidence = 0;
        float flowLimit = taggedFlowLimit;
        double coarsePixels = Math.min(8.0, Math.max(2.0, flowLimit / 2.0));
        double finePixels = Math.min(2.0, Math.max(0.5, coarsePixels / 4.0));
        double boundaryThreshold = Math.max(0.0, Math.min(1.0,
                (2.0 * coarsePixels + 2.0 * finePixels) / flowLimit) -
                2.5 / 255.0);
        double rangeX = flowLimit / Math.max(1.0, taggedWidth);
        double rangeY = flowLimit / Math.max(1.0, taggedHeight);
        for (int region = 0; region < REGIONAL_FLOW_CELLS; ++region) {
            int offset = region * 4;
            int backwardCandidateSupport = backwardWinner[offset + 3] & 0xff;
            int forwardCandidateSupport = forwardWinner[offset + 3] & 0xff;
            backwardCandidatePeakSupport = Math.max(
                    backwardCandidatePeakSupport, backwardCandidateSupport);
            forwardCandidatePeakSupport = Math.max(
                    forwardCandidatePeakSupport, forwardCandidateSupport);
            boolean backwardIsCoherent = backwardCandidateSupport >= 159;
            boolean forwardIsCoherent = forwardCandidateSupport >= 159;
            boolean backwardIsBoundary = candidateTouchesBoundary(
                    backwardWinner, offset, boundaryThreshold);
            boolean forwardIsBoundary = candidateTouchesBoundary(
                    forwardWinner, offset, boundaryThreshold);
            if (backwardIsCoherent) ++backwardCoherent;
            if (forwardIsCoherent) ++forwardCoherent;
            if (backwardIsBoundary) ++backwardBoundary;
            if (forwardIsBoundary) ++forwardBoundary;
            if (backwardIsCoherent && backwardIsBoundary)
                ++backwardCoherentBoundary;
            if (forwardIsCoherent && forwardIsBoundary)
                ++forwardCoherentBoundary;
            int backwardNeighborClass = candidateNeighborClass(
                    backwardWinner, region);
            int forwardNeighborClass = candidateNeighborClass(
                    forwardWinner, region);
            if (backwardNeighborClass != 0) ++backwardNeighbor;
            if (forwardNeighborClass != 0) ++forwardNeighbor;
            if ((backwardNeighborClass & 1) != 0) ++backwardConstantNeighbor;
            if ((forwardNeighborClass & 1) != 0) ++forwardConstantNeighbor;
            if ((backwardNeighborClass & 2) != 0) ++backwardGradientNeighbor;
            if ((forwardNeighborClass & 2) != 0) ++forwardGradientNeighbor;
            int backwardConfidence = backward[offset + 2] & 0xff;
            int forwardConfidence = forward[offset + 2] & 0xff;
            int backwardSupport = backward[offset + 3] & 0xff;
            int forwardSupport = forward[offset + 3] & 0xff;
            backwardPeakConfidence = Math.max(backwardPeakConfidence,
                    backwardConfidence);
            forwardPeakConfidence = Math.max(forwardPeakConfidence,
                    forwardConfidence);
            backwardPeakSupport = Math.max(backwardPeakSupport, backwardSupport);
            forwardPeakSupport = Math.max(forwardPeakSupport, forwardSupport);
            // A=159 corresponds to 10/16 improving sites, the first nonzero
            // point of the 9->11 smooth support gate after RGBA8 quantization.
            if (backwardSupport >= 159) ++backwardSupported;
            if (forwardSupport >= 159) ++forwardSupported;
            if (backwardConfidence >= 26) {
                ++backwardAccepted;
                if (backwardIsBoundary) ++backwardAcceptedBoundary;
            }
            if (forwardConfidence >= 26) {
                ++forwardAccepted;
                if (forwardIsBoundary) ++forwardAcceptedBoundary;
            }
            double backwardX = (backward[offset] & 0xff) / 255.0 * 2.0 - 1.0;
            double backwardY = (backward[offset + 1] & 0xff) / 255.0 * 2.0 - 1.0;
            int regionX = region % REGIONAL_FLOW_WIDTH;
            int regionY = region / REGIONAL_FLOW_WIDTH;
            double peerU = clampUnit((regionX + 0.5) / REGIONAL_FLOW_WIDTH +
                    backwardX * rangeX);
            double peerV = clampUnit((regionY + 0.5) / REGIONAL_FLOW_HEIGHT +
                    backwardY * rangeY);
            double forwardX = sampleRegionalChannel(forward, peerU, peerV, 0) /
                    255.0 * 2.0 - 1.0;
            double forwardY = sampleRegionalChannel(forward, peerU, peerV, 1) /
                    255.0 * 2.0 - 1.0;
            double forwardPeerConfidence =
                    sampleRegionalChannel(forward, peerU, peerV, 2);
            double cycle = Math.hypot(backwardX + forwardX,
                    backwardY + forwardY);
            double reliability = Math.sqrt((backwardConfidence / 255.0) *
                    (forwardPeerConfidence / 255.0)) *
                    Math.max(0.0, 1.0 - 5.0 * cycle);
            if (backwardConfidence >= 26 && reliability > 0.10)
                ++backwardCycleAccepted;
            double sourceForwardX = (forward[offset] & 0xff) / 255.0 * 2.0 - 1.0;
            double sourceForwardY = (forward[offset + 1] & 0xff) / 255.0 * 2.0 - 1.0;
            double backwardPeerU = clampUnit(
                    (regionX + 0.5) / REGIONAL_FLOW_WIDTH + sourceForwardX * rangeX);
            double backwardPeerV = clampUnit(
                    (regionY + 0.5) / REGIONAL_FLOW_HEIGHT + sourceForwardY * rangeY);
            double backwardPeerX = sampleRegionalChannel(
                    backward, backwardPeerU, backwardPeerV, 0) / 255.0 * 2.0 - 1.0;
            double backwardPeerY = sampleRegionalChannel(
                    backward, backwardPeerU, backwardPeerV, 1) / 255.0 * 2.0 - 1.0;
            double backwardPeerConfidence = sampleRegionalChannel(
                    backward, backwardPeerU, backwardPeerV, 2);
            double forwardCycle = Math.hypot(sourceForwardX + backwardPeerX,
                    sourceForwardY + backwardPeerY);
            double forwardReliability = Math.sqrt((forwardConfidence / 255.0) *
                    (backwardPeerConfidence / 255.0)) *
                    Math.max(0.0, 1.0 - 5.0 * forwardCycle);
            if (forwardConfidence >= 26 && forwardReliability > 0.10)
                ++forwardCycleAccepted;
        }
        latticeRegionSamples += REGIONAL_FLOW_CELLS;
        latticeBackwardCoherentRegions += backwardCoherent;
        latticeForwardCoherentRegions += forwardCoherent;
        latticeBackwardBoundaryRegions += backwardBoundary;
        latticeForwardBoundaryRegions += forwardBoundary;
        latticeBackwardCoherentBoundaryRegions += backwardCoherentBoundary;
        latticeForwardCoherentBoundaryRegions += forwardCoherentBoundary;
        latticeBackwardCoherentRegionCount = backwardCoherent;
        latticeForwardCoherentRegionCount = forwardCoherent;
        latticeBackwardBoundaryRegionCount = backwardBoundary;
        latticeForwardBoundaryRegionCount = forwardBoundary;
        latticeBackwardCoherentBoundaryRegionCount = backwardCoherentBoundary;
        latticeForwardCoherentBoundaryRegionCount = forwardCoherentBoundary;
        latticeBackwardPeakSupport = backwardCandidatePeakSupport;
        latticeForwardPeakSupport = forwardCandidatePeakSupport;
        regionalFlowRegionSamples += REGIONAL_FLOW_CELLS;
        regionalBackwardSupportedRegions += backwardSupported;
        regionalForwardSupportedRegions += forwardSupported;
        regionalBackwardNeighborRegions += backwardNeighbor;
        regionalForwardNeighborRegions += forwardNeighbor;
        regionalBackwardConstantNeighborRegions += backwardConstantNeighbor;
        regionalForwardConstantNeighborRegions += forwardConstantNeighbor;
        regionalBackwardGradientNeighborRegions += backwardGradientNeighbor;
        regionalForwardGradientNeighborRegions += forwardGradientNeighbor;
        regionalBackwardAcceptedRegions += backwardAccepted;
        regionalForwardAcceptedRegions += forwardAccepted;
        regionalBackwardAcceptedBoundaryRegions += backwardAcceptedBoundary;
        regionalForwardAcceptedBoundaryRegions += forwardAcceptedBoundary;
        regionalBackwardCycleAcceptedRegions += backwardCycleAccepted;
        regionalForwardCycleAcceptedRegions += forwardCycleAccepted;
        regionalBackwardAcceptedRegionCount = backwardAccepted;
        regionalForwardAcceptedRegionCount = forwardAccepted;
        regionalBackwardAcceptedBoundaryRegionCount = backwardAcceptedBoundary;
        regionalForwardAcceptedBoundaryRegionCount = forwardAcceptedBoundary;
        regionalBackwardCycleAcceptedRegionCount = backwardCycleAccepted;
        regionalForwardCycleAcceptedRegionCount = forwardCycleAccepted;
        regionalBackwardSupportedRegionCount = backwardSupported;
        regionalForwardSupportedRegionCount = forwardSupported;
        regionalBackwardNeighborRegionCount = backwardNeighbor;
        regionalForwardNeighborRegionCount = forwardNeighbor;
        regionalBackwardConstantNeighborRegionCount = backwardConstantNeighbor;
        regionalForwardConstantNeighborRegionCount = forwardConstantNeighbor;
        regionalBackwardGradientNeighborRegionCount = backwardGradientNeighbor;
        regionalForwardGradientNeighborRegionCount = forwardGradientNeighbor;
        regionalBackwardPeakSupport = backwardPeakSupport;
        regionalForwardPeakSupport = forwardPeakSupport;
        regionalBackwardPeakConfidence = backwardPeakConfidence;
        regionalForwardPeakConfidence = forwardPeakConfidence;
    }

    private static boolean candidateTouchesBoundary(byte[] winner, int offset,
                                                     double threshold) {
        double x = Math.abs((winner[offset] & 0xff) / 255.0 * 2.0 - 1.0);
        double y = Math.abs((winner[offset + 1] & 0xff) / 255.0 * 2.0 - 1.0);
        return x >= threshold || y >= threshold;
    }

    /** Bit 0 is constant-neighbor consensus; bit 1 is affine-gradient consensus. */
    private static int candidateNeighborClass(byte[] winner, int region) {
        int x = region % REGIONAL_FLOW_WIDTH;
        int y = region / REGIONAL_FLOW_WIDTH;
        int available = 0;
        int compatible = 0;
        int[] peers = {region - 1, region + 1,
                region - REGIONAL_FLOW_WIDTH, region + REGIONAL_FLOW_WIDTH};
        boolean[] valid = {x > 0, x + 1 < REGIONAL_FLOW_WIDTH,
                y > 0, y + 1 < REGIONAL_FLOW_HEIGHT};
        boolean[] coherent = new boolean[4];
        double[] peerX = new double[4];
        double[] peerY = new double[4];
        int offset = region * 4;
        double centerX = (winner[offset] & 0xff) / 255.0 * 2.0 - 1.0;
        double centerY = (winner[offset + 1] & 0xff) / 255.0 * 2.0 - 1.0;
        for (int index = 0; index < peers.length; ++index) {
            if (!valid[index]) continue;
            ++available;
            int peerOffset = peers[index] * 4;
            coherent[index] = (winner[peerOffset + 3] & 0xff) >= 159;
            peerX[index] = (winner[peerOffset] & 0xff) / 255.0 * 2.0 - 1.0;
            peerY[index] = (winner[peerOffset + 1] & 0xff) / 255.0 * 2.0 - 1.0;
            if (coherent[index] && Math.hypot(centerX - peerX[index],
                    centerY - peerY[index]) <= 0.18)
                ++compatible;
        }
        boolean constant = compatible >= Math.min(2, available);
        boolean horizontalGradient = coherent[0] && coherent[1] &&
                Math.hypot(centerX - (peerX[0] + peerX[1]) * 0.5,
                        centerY - (peerY[0] + peerY[1]) * 0.5) <= 0.18 &&
                Math.hypot(peerX[0] - peerX[1], peerY[0] - peerY[1]) <= 0.45;
        boolean verticalGradient = coherent[2] && coherent[3] &&
                Math.hypot(centerX - (peerX[2] + peerX[3]) * 0.5,
                        centerY - (peerY[2] + peerY[3]) * 0.5) <= 0.18 &&
                Math.hypot(peerX[2] - peerX[3], peerY[2] - peerY[3]) <= 0.45;
        return (constant ? 1 : 0) |
                ((horizontalGradient || verticalGradient) ? 2 : 0);
    }

    private void readRegionalFlowPixels(int texture, byte[] destination) {
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D, texture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            fail("global consensus telemetry framebuffer incomplete");
        GLES20.glViewport(0, 0, REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        regionalFlowPixels.clear();
        GLES20.glReadPixels(0, 0, REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT,
                GLES20.GL_RGBA,
                GLES20.GL_UNSIGNED_BYTE, regionalFlowPixels);
        for (int index = 0; index < destination.length; ++index)
            destination[index] = regionalFlowPixels.get(index);
    }

    private long hashProofBytes(byte[] values) {
        long hash = 0xcbf29ce484222325L;
        for (byte value : values) {
            hash ^= value & 0xffL;
            hash *= 0x100000001b3L;
        }
        return hash;
    }

    private void copyAtlasTile(byte[] destination, int tileX, int tileY,
                               int width, int height) {
        int target = 0;
        for (int row = 0; row < height; ++row) {
            int source = ((tileY + row) * PROOF_ATLAS_WIDTH + tileX) * 4;
            for (int count = 0; count < width * 4; ++count)
                destination[target++] = proofAtlasPixels.get(source + count);
        }
    }

    private void drawProofAtlasTile(int texture, int x, int y,
                                    int width, int height) {
        GLES20.glViewport(x, y, width, height);
        drawTexture2d(texture);
    }

    private static void setDenseValidatedFilter(int texture, int filter) {
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,
                GLES20.GL_TEXTURE_MIN_FILTER, filter);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,
                GLES20.GL_TEXTURE_MAG_FILTER, filter);
    }

    /** Renders layout-3's exact nearest mask without changing linear RG/B. */
    private void renderDenseDiagnosticMaskTile() {
        boolean blend = GLES20.glIsEnabled(GLES20.GL_BLEND);
        boolean dither = GLES20.glIsEnabled(GLES20.GL_DITHER);
        boolean scissor = GLES20.glIsEnabled(GLES20.GL_SCISSOR_TEST);
        boolean depth = GLES20.glIsEnabled(GLES20.GL_DEPTH_TEST);
        boolean stencil = GLES20.glIsEnabled(GLES20.GL_STENCIL_TEST);
        boolean cull = GLES20.glIsEnabled(GLES20.GL_CULL_FACE);
        boolean[] colorMask = new boolean[4];
        GLES20.glGetBooleanv(GLES20.GL_COLOR_WRITEMASK, colorMask, 0);
        try {
            GLES20.glDisable(GLES20.GL_BLEND);
            GLES20.glDisable(GLES20.GL_DITHER);
            GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
            GLES20.glDisable(GLES20.GL_DEPTH_TEST);
            GLES20.glDisable(GLES20.GL_STENCIL_TEST);
            GLES20.glDisable(GLES20.GL_CULL_FACE);
            GLES20.glColorMask(true, true, true, true);
            setDenseValidatedFilter(denseValidatedTextures[0], GLES20.GL_NEAREST);
            setDenseValidatedFilter(denseValidatedTextures[1], GLES20.GL_NEAREST);
            GLES20.glViewport(DENSE_DIAGNOSTIC_PACK_X,
                    DENSE_DIAGNOSTIC_PACK_Y, DENSE_DIAGNOSTIC_PACK_WIDTH,
                    DENSE_DIAGNOSTIC_PACK_HEIGHT);
            GLES20.glUseProgram(denseDiagnosticPackProgram);
            bindQuad(denseDiagnosticPackProgram);
            bindTexture(denseDiagnosticPackProgram, "uBackwardMask",
                    denseValidatedTextures[0], 0);
            bindTexture(denseDiagnosticPackProgram, "uForwardMask",
                    denseValidatedTextures[1], 1);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
            checkGl("render packed nearest dense diagnostic mask");
        } finally {
            // Synthesis and the existing RG/B atlas tiles require persistent
            // LINEAR filtering. Restore it even when the qualification draw
            // or GL error check fails.
            setDenseValidatedFilter(denseValidatedTextures[0], GLES20.GL_LINEAR);
            setDenseValidatedFilter(denseValidatedTextures[1], GLES20.GL_LINEAR);
            if (blend) GLES20.glEnable(GLES20.GL_BLEND);
            if (dither) GLES20.glEnable(GLES20.GL_DITHER);
            if (scissor) GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
            if (depth) GLES20.glEnable(GLES20.GL_DEPTH_TEST);
            if (stencil) GLES20.glEnable(GLES20.GL_STENCIL_TEST);
            if (cull) GLES20.glEnable(GLES20.GL_CULL_FACE);
            GLES20.glColorMask(colorMask[0], colorMask[1], colorMask[2],
                    colorMask[3]);
            GLES20.glViewport(0, 0, PROOF_ATLAS_WIDTH, PROOF_ATLAS_HEIGHT);
        }
    }

    private void renderProofAtlasTile(int x, int y, int kind, float phase) {
        GLES20.glViewport(x, y, PROOF_WIDTH, PROOF_HEIGHT);
        if (kind == 0) drawMotionFrame(0f);
        else if (kind == 1) drawMotionFrame(1f);
        else if (kind == 2) drawMotionFrame(phase);
        else if (kind == 3) drawPredictionProof(phase, false);
        else if (kind == 4) drawPredictionProof(phase, true);
        else drawProofFlow();
    }

    private void enqueueProofAtlas(float phase) {
        long started = System.nanoTime();
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                proofAtlasTexture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            throw new IllegalStateException("proof atlas framebuffer incomplete");
        GLES20.glViewport(0, 0, PROOF_ATLAS_WIDTH, PROOF_ATLAS_HEIGHT);
        GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
        GLES20.glClearColor(0f, 0f, 0f, 0f);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
        for (int kind = 0; kind < 4; ++kind)
            renderProofAtlasTile(kind * PROOF_WIDTH, 0, kind, phase);
        renderProofAtlasTile(0, PROOF_HEIGHT, 4, phase);
        renderProofAtlasTile(PROOF_WIDTH, PROOF_HEIGHT, 5, phase);
        drawProofAtlasTile(denseValidatedTextures[0], PROOF_WIDTH * 2,
                PROOF_HEIGHT, PROOF_WIDTH, PROOF_HEIGHT);
        drawProofAtlasTile(denseValidatedTextures[1], PROOF_WIDTH * 3,
                PROOF_HEIGHT, PROOF_WIDTH, PROOF_HEIGHT);
        int[] regional = {globalCandidateWinnerTextures[0],
                globalCandidateWinnerTextures[1], globalFlowTextures[0],
                globalFlowTextures[1]};
        for (int index = 0; index < regional.length; ++index) {
            GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                    GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                    regional[index], 0);
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, proofAtlasTexture);
            GLES20.glCopyTexSubImage2D(GLES20.GL_TEXTURE_2D, 0,
                    index * REGIONAL_FLOW_WIDTH, 54, 0, 0,
                    REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        }
        long sequence = ++proofAtlasSequence;
        if (activeLeftSequence <= 0L ||
                activeRightSequence != activeLeftSequence + 1L ||
                activeRightSequence > 0xffffffffL)
            throw new IllegalStateException(
                    "proof atlas endpoint pair is not exact and adjacent");
        proofAtlasHeader.clear();
        for (int offset = 0; offset < PROOF_ATLAS_HEADER_BYTES; offset += 4)
            proofAtlasHeader.putInt(0);
        proofAtlasHeader.clear();
        proofAtlasHeader.putInt(0x32504645); // "EFP2" little-endian
        proofAtlasHeader.putInt(PROOF_ATLAS_LAYOUT_VERSION);
        proofAtlasHeader.putInt(PROOF_ATLAS_HEADER_BYTES);
        proofAtlasHeader.putInt((int) proofAtlasEpoch);
        proofAtlasHeader.putLong(sequence);
        proofAtlasHeader.putLong(presents + 1L);
        proofAtlasHeader.putInt((int) activeLeftSequence);
        proofAtlasHeader.putInt((int) activeRightSequence);
        proofAtlasHeader.putLong(densePromotions);
        proofAtlasHeader.putLong(denseWarpSequence);
        proofAtlasHeader.putInt(Float.floatToRawIntBits(phase));
        proofAtlasHeader.putInt(historyWidth);
        proofAtlasHeader.putInt(historyHeight);
        proofAtlasHeader.putInt(Float.floatToRawIntBits(activeFlowLimitPixels()));
        proofAtlasHeader.putInt(previousIndex);
        proofAtlasHeader.putInt(currentIndex);
        proofAtlasHeader.putInt(7); // synthetic + dense + motion-ready
        proofAtlasHeader.putLong(proofEvidencePresentationEpoch);
        long targetSourceNs = frameRate.bufferedSelectedTargetSourceNs();
        if (targetSourceNs <= 0L)
            throw new IllegalStateException(
                    "proof atlas target source timestamp unavailable");
        proofAtlasHeader.putLong(targetSourceNs);
        CRC32 crc = new CRC32();
        byte[] header = new byte[PROOF_ATLAS_HEADER_BYTES - 4];
        proofAtlasHeader.position(0);
        proofAtlasHeader.get(header);
        crc.update(header);
        proofAtlasHeader.position(PROOF_ATLAS_HEADER_BYTES - 4);
        proofAtlasHeader.putInt((int) crc.getValue());
        proofAtlasHeader.position(0);
        byte[] completeHeader = new byte[PROOF_ATLAS_HEADER_BYTES];
        proofAtlasHeader.get(completeHeader);
        float[] headerWords = new float[PROOF_ATLAS_HEADER_BYTES];
        for (int index = 0; index < completeHeader.length; ++index)
            headerWords[index] = (completeHeader[index] & 0xff) / 255f;
        // The regional CopyTexSubImage loop leaves this FBO attached to the
        // final 12x8 source texture. Reattach the atlas before rendering the
        // in-band tag row; its 48,54 viewport is outside every regional source.
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                proofAtlasTexture, 0);
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                GLES20.GL_FRAMEBUFFER_COMPLETE)
            throw new IllegalStateException("proof atlas header framebuffer incomplete");
        renderDenseDiagnosticMaskTile();
        boolean blend = GLES20.glIsEnabled(GLES20.GL_BLEND);
        boolean dither = GLES20.glIsEnabled(GLES20.GL_DITHER);
        boolean scissor = GLES20.glIsEnabled(GLES20.GL_SCISSOR_TEST);
        boolean depth = GLES20.glIsEnabled(GLES20.GL_DEPTH_TEST);
        boolean stencil = GLES20.glIsEnabled(GLES20.GL_STENCIL_TEST);
        boolean cull = GLES20.glIsEnabled(GLES20.GL_CULL_FACE);
        boolean[] colorMask = new boolean[4];
        GLES20.glGetBooleanv(GLES20.GL_COLOR_WRITEMASK, colorMask, 0);
        try {
            GLES20.glDisable(GLES20.GL_BLEND);
            GLES20.glDisable(GLES20.GL_DITHER);
            GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
            GLES20.glDisable(GLES20.GL_DEPTH_TEST);
            GLES20.glDisable(GLES20.GL_STENCIL_TEST);
            GLES20.glDisable(GLES20.GL_CULL_FACE);
            GLES20.glColorMask(true, true, true, true);
            GLES20.glViewport(PROOF_ATLAS_HEADER_X, PROOF_ATLAS_HEADER_Y, 26, 1);
            GLES20.glUseProgram(proofAtlasHeaderProgram);
            bindQuad(proofAtlasHeaderProgram);
            int words = GLES20.glGetUniformLocation(proofAtlasHeaderProgram,
                    "uWords[0]");
            if (words < 0)
                throw new IllegalStateException("proof atlas header uniform unavailable");
            GLES20.glUniform4fv(words, 26, headerWords, 0);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
            checkGl("render proof atlas header");
        } finally {
            if (blend) GLES20.glEnable(GLES20.GL_BLEND);
            if (dither) GLES20.glEnable(GLES20.GL_DITHER);
            if (scissor) GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
            if (depth) GLES20.glEnable(GLES20.GL_DEPTH_TEST);
            if (stencil) GLES20.glEnable(GLES20.GL_STENCIL_TEST);
            if (cull) GLES20.glEnable(GLES20.GL_CULL_FACE);
            GLES20.glColorMask(colorMask[0], colorMask[1], colorMask[2],
                    colorMask[3]);
        }
        GLES20.glViewport(0, 0, PROOF_ATLAS_WIDTH, PROOF_ATLAS_HEIGHT);
        int status = denseGpuTimer.enqueueProofAtlas(sequence, presents + 1L);
        if (status == 3) ++proofAtlasRingFull;
        if (status != 0) {
            ++proofAtlasErrors;
            throw new IllegalStateException("proof atlas enqueue status=" + status);
        }
        ++proofAtlasEnqueued;
        ++proofEvidenceEnqueuedInEpoch;
        recordDenseWall(DENSE_WALL_PROOF_ENQUEUE,
                System.nanoTime() - started);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        GLES20.glViewport(0, 0, outputWidth, outputHeight);
    }

    private void pollProofAtlas() {
        if (!densePyramidEnabled || proofAtlasPixels == null) return;
        long started = System.nanoTime();
        long[] row = denseGpuTimer.pollProofAtlas(presents + 1L,
                proofAtlasPixels);
        if (row.length == 0) {
            if (denseGpuTimer.pendingProofAtlases() > 0) ++proofAtlasTimeoutPolls;
            recordDenseWall(DENSE_WALL_PROOF_POLL,
                    System.nanoTime() - started);
            return;
        }
        if (row.length != 15 || row[0] != 0 || row[5] != PROOF_ATLAS_BYTES) {
            ++proofAtlasErrors;
            throw new IllegalStateException("proof atlas poll invalid result row=" +
                    java.util.Arrays.toString(row) + " bufferPosition=" +
                    proofAtlasPixels.position() + " bufferLimit=" +
                    proofAtlasPixels.limit() + " bufferCapacity=" +
                    proofAtlasPixels.capacity() + " nativePending=" +
                    denseGpuTimer.pendingProofAtlases() + " capability=" +
                    denseGpuTimer.proofAtlasCapability());
        }
        proofAtlasMaxQueueAge = Math.max(proofAtlasMaxQueueAge, row[6]);
        if (row[3] != proofAtlasCompleted + 1L || row[6] < 0 || row[6] > 8) {
            ++proofAtlasTagErrors;
            throw new IllegalStateException("proof atlas sequence/age mismatch");
        }
        proofAtlasPixels.order(java.nio.ByteOrder.LITTLE_ENDIAN);
        int header = (PROOF_ATLAS_HEADER_Y * PROOF_ATLAS_WIDTH +
                PROOF_ATLAS_HEADER_X) * 4;
        long[] expectedTag = {0x32504645L, PROOF_ATLAS_LAYOUT_VERSION,
                PROOF_ATLAS_HEADER_BYTES, proofAtlasEpoch, row[3], row[4],
                1L, 1L, 7L};
        long[] actualTag = {proofAtlasPixels.getInt(header) & 0xffffffffL,
                proofAtlasPixels.getInt(header + 4) & 0xffffffffL,
                proofAtlasPixels.getInt(header + 8) & 0xffffffffL,
                proofAtlasPixels.getInt(header + 12) & 0xffffffffL,
                proofAtlasPixels.getLong(header + 16),
                proofAtlasPixels.getLong(header + 24),
                proofAtlasPixels.getInt(header + 36) -
                        proofAtlasPixels.getInt(header + 32),
                proofAtlasPixels.getInt(header + 72) ==
                        proofAtlasPixels.getInt(header + 76) ? 0L : 1L,
                proofAtlasPixels.getInt(header + 80) & 0xffffffffL};
        int firstTagMismatch = -1;
        for (int index = 0; index < expectedTag.length; ++index)
            if (expectedTag[index] != actualTag[index]) {
                firstTagMismatch = index;
                break;
            }
        if (firstTagMismatch >= 0) {
            ++proofAtlasTagErrors;
            StringBuilder words = new StringBuilder();
            for (int offset = 0; offset < PROOF_ATLAS_HEADER_BYTES; offset += 4)
                words.append(offset == 0 ? "" : ",").append(
                        Integer.toUnsignedString(proofAtlasPixels.getInt(header + offset), 16));
            throw new IllegalStateException("proof atlas tag mismatch field=" +
                    firstTagMismatch + " expected=" + expectedTag[firstTagMismatch] +
                    " actual=" + actualTag[firstTagMismatch] + " nativeSeq=" +
                    row[3] + " nativePresent=" + row[4] + " words=" + words);
        }
        byte[] crcBytes = new byte[PROOF_ATLAS_HEADER_BYTES - 4];
        for (int index = 0; index < crcBytes.length; ++index)
            crcBytes[index] = proofAtlasPixels.get(header + index);
        CRC32 crc = new CRC32(); crc.update(crcBytes);
        if ((int) crc.getValue() != proofAtlasPixels.getInt(
                header + PROOF_ATLAS_HEADER_BYTES - 4)) {
            ++proofAtlasTagErrors;
            throw new IllegalStateException("proof atlas CRC mismatch");
        }
        long taggedPresentationEpoch = proofAtlasPixels.getLong(header + 84);
        if (taggedPresentationEpoch <= 0L) {
            ++proofAtlasTagErrors;
            throw new IllegalStateException(
                    "proof atlas presentation epoch mismatch");
        }
        if (taggedPresentationEpoch != proofEvidencePresentationEpoch) {
            ++proofAtlasCompleted;
            ++proofEvidenceExcluded;
            if (proofAtlasCompleted !=
                    proofEvidenceAccepted + proofEvidenceExcluded)
                throw new IllegalStateException(
                        "proof evidence completion conservation mismatch");
            recordDenseWall(DENSE_WALL_PROOF_POLL,
                    System.nanoTime() - started);
            return;
        }
        copyAtlasTile(proofPrevious, 0, 0, PROOF_WIDTH, PROOF_HEIGHT);
        copyAtlasTile(proofCurrent, 48, 0, PROOF_WIDTH, PROOF_HEIGHT);
        copyAtlasTile(proofOutput, 96, 0, PROOF_WIDTH, PROOF_HEIGHT);
        copyAtlasTile(proofPredicted, 144, 0, PROOF_WIDTH, PROOF_HEIGHT);
        copyAtlasTile(proofInverse, 0, 27, PROOF_WIDTH, PROOF_HEIGHT);
        copyAtlasTile(proofFlow, 48, 27, PROOF_WIDTH, PROOF_HEIGHT);
        byte[] denseBackward = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
        byte[] denseForward = new byte[PROOF_WIDTH * PROOF_HEIGHT * 4];
        byte[] densePackedMasks = new byte[
                DENSE_DIAGNOSTIC_PACK_WIDTH * DENSE_DIAGNOSTIC_PACK_HEIGHT * 4];
        copyAtlasTile(denseBackward, 96, 27, PROOF_WIDTH, PROOF_HEIGHT);
        copyAtlasTile(denseForward, 144, 27, PROOF_WIDTH, PROOF_HEIGHT);
        copyAtlasTile(densePackedMasks, DENSE_DIAGNOSTIC_PACK_X,
                DENSE_DIAGNOSTIC_PACK_Y, DENSE_DIAGNOSTIC_PACK_WIDTH,
                DENSE_DIAGNOSTIC_PACK_HEIGHT);
        denseProofCells += (long) PROOF_WIDTH * PROOF_HEIGHT;
        for (int pixel = 0; pixel < PROOF_WIDTH * PROOF_HEIGHT; ++pixel) {
            if ((denseBackward[pixel * 4 + 2] & 0xff) >= 48)
                ++denseBackwardValidCells;
            if ((denseForward[pixel * 4 + 2] & 0xff) >= 48)
                ++denseForwardValidCells;
        }
        accumulateDenseDiagnostic(denseBackward, densePackedMasks, 0, 0);
        accumulateDenseDiagnostic(denseForward, densePackedMasks, 1, 1);
        denseDiagnosticCells += (long) PROOF_WIDTH * PROOF_HEIGHT;
        denseDiagnosticPackedCells += (long) PROOF_WIDTH * PROOF_HEIGHT;
        denseDiagnosticTiles +=
                DENSE_DIAGNOSTIC_TILES_X * DENSE_DIAGNOSTIC_TILES_Y;
        denseDiagnosticLastAtlasSequence = row[3];
        denseDiagnosticLastPairSequence = proofAtlasPixels.getLong(header + 40);
        denseDiagnosticLastPreviousEndpoint =
                proofAtlasPixels.getInt(header + 32) & 0xffffffffL;
        denseDiagnosticLastCurrentEndpoint =
                proofAtlasPixels.getInt(header + 36) & 0xffffffffL;
        long taggedTargetSourceNs = proofAtlasPixels.getLong(header + 92);
        if (taggedTargetSourceNs <= 0L ||
                (denseDiagnosticLastTargetSourceNs > 0L &&
                        taggedTargetSourceNs <= denseDiagnosticLastTargetSourceNs))
            throw new IllegalStateException(
                    "proof atlas target source timestamp invalid");
        denseDiagnosticLastTargetSourceNs = taggedTargetSourceNs;
        byte[][] regional = new byte[4][REGIONAL_FLOW_CELLS * 4];
        for (int index = 0; index < 4; ++index)
            copyAtlasTile(regional[index], index * REGIONAL_FLOW_WIDTH, 54,
                    REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT);
        int taggedWidth = proofAtlasPixels.getInt(header + 60);
        int taggedHeight = proofAtlasPixels.getInt(header + 64);
        float taggedFlowLimit = Float.intBitsToFloat(
                proofAtlasPixels.getInt(header + 68));
        if (taggedWidth <= 0 || taggedHeight <= 0 ||
                !Float.isFinite(taggedFlowLimit) || taggedFlowLimit <= 0f) {
            ++proofAtlasTagErrors;
            throw new IllegalStateException("proof atlas geometry mismatch");
        }
        analyzeRegionalFlowTelemetry(regional[0], regional[1],
                regional[2], regional[3], taggedWidth, taggedHeight,
                taggedFlowLimit);
        float phase = Float.intBitsToFloat(proofAtlasPixels.getInt(header + 56));
        if (!Float.isFinite(phase) || phase <= .15f || phase >= .85f) {
            ++proofAtlasTagErrors;
            throw new IllegalStateException("proof atlas phase mismatch");
        }
        analyzeProofPayload(phase, hashProofBytes(proofPrevious),
                hashProofBytes(proofCurrent), hashProofBytes(proofOutput));
        ++proofAtlasCompleted;
        ++proofEvidenceAccepted;
        proofEvidenceLastAcceptedAtlasSequence = row[3];
        if (proofAtlasCompleted !=
                proofEvidenceAccepted + proofEvidenceExcluded ||
                proofEvidenceAccepted != proofSamples)
            throw new IllegalStateException(
                    "proof evidence acceptance conservation mismatch");
        recordDenseWall(DENSE_WALL_PROOF_POLL,
                System.nanoTime() - started);
    }

    /** Decodes schema36's separately nearest-sampled packed mask tile. */
    private void accumulateDenseDiagnostic(byte[] field, byte[] packedMasks,
                                           int packedChannel, int direction) {
        int[] activeByTile = new int[
                DENSE_DIAGNOSTIC_TILES_X * DENSE_DIAGNOSTIC_TILES_Y];
        int[] validByTile = new int[activeByTile.length];
        for (int y = 0; y < PROOF_HEIGHT; ++y) {
            int tileY = Math.min(DENSE_DIAGNOSTIC_TILES_Y - 1,
                    y * DENSE_DIAGNOSTIC_TILES_Y / PROOF_HEIGHT);
            for (int x = 0; x < PROOF_WIDTH; ++x) {
                int pixel = y * PROOF_WIDTH + x;
                int mask = packedMasks[pixel * 4 + packedChannel] & 0xff;
                boolean active = (mask & DENSE_DIAG_ACTIVE) != 0;
                boolean byteValid = (field[pixel * 4 + 2] & 0xff) >= 48;
                if (active) ++denseDiagnosticActiveCells[direction];
                if ((mask & DENSE_DIAG_IN_BOUNDS) != 0)
                    ++denseDiagnosticInBoundsCells[direction];
                if ((mask & DENSE_DIAG_CYCLE_VALID) != 0)
                    ++denseDiagnosticCycleValidCells[direction];
                if ((mask & DENSE_DIAG_PHOTOMETRIC_VALID) != 0)
                    ++denseDiagnosticPhotometricValidCells[direction];
                if ((mask & DENSE_DIAG_TEXTURE_VALID) != 0)
                    ++denseDiagnosticTextureValidCells[direction];
                if ((mask & DENSE_DIAG_SATURATED) != 0)
                    ++denseDiagnosticSaturatedCells[direction];
                if ((mask & DENSE_DIAG_OUT_OF_BOUNDS) != 0)
                    ++denseDiagnosticOutOfBoundsCells[direction];
                // Bit 7 is reserved. Final composite validity comes from the
                // actual returned B byte, avoiding a second prediction of the
                // implementation's RGBA8 half-LSB conversion.
                if ((mask & 128) != 0) {
                    ++denseDiagnosticReservedBitErrors;
                    ++denseDiagnosticMaskErrors;
                }
                boolean inBounds = (mask & DENSE_DIAG_IN_BOUNDS) != 0;
                boolean outOfBounds =
                        (mask & DENSE_DIAG_OUT_OF_BOUNDS) != 0;
                if (inBounds == outOfBounds) {
                    ++denseDiagnosticPartitionErrors;
                    ++denseDiagnosticMaskErrors;
                }
                int tileX = Math.min(DENSE_DIAGNOSTIC_TILES_X - 1,
                        x * DENSE_DIAGNOSTIC_TILES_X / PROOF_WIDTH);
                int tile = tileY * DENSE_DIAGNOSTIC_TILES_X + tileX;
                if (active) ++activeByTile[tile];
                if (byteValid) ++validByTile[tile];
            }
        }
        for (int tile = 0; tile < activeByTile.length; ++tile) {
            if (activeByTile[tile] > 0 &&
                    validByTile[tile] * 2 >= activeByTile[tile]) {
                ++denseDiagnosticCoveredTiles[direction];
                denseDiagnosticCoveredTileMask[direction] |= 1 << tile;
            }
        }
    }

    private static double sampleRegionalChannel(byte[] field, double u, double v,
                                                 int channel) {
        double x = Math.max(0.0, Math.min(REGIONAL_FLOW_WIDTH - 1.0,
                clampUnit(u) * REGIONAL_FLOW_WIDTH - 0.5));
        double y = Math.max(0.0, Math.min(REGIONAL_FLOW_HEIGHT - 1.0,
                clampUnit(v) * REGIONAL_FLOW_HEIGHT - 0.5));
        int x0 = (int) Math.floor(x);
        int y0 = (int) Math.floor(y);
        int x1 = Math.min(REGIONAL_FLOW_WIDTH - 1, x0 + 1);
        int y1 = Math.min(REGIONAL_FLOW_HEIGHT - 1, y0 + 1);
        double tx = x - x0;
        double ty = y - y0;
        double top = ((field[(y0 * REGIONAL_FLOW_WIDTH + x0) * 4 + channel] & 0xff) *
                (1.0 - tx)) +
                ((field[(y0 * REGIONAL_FLOW_WIDTH + x1) * 4 + channel] & 0xff) * tx);
        double bottom =
                ((field[(y1 * REGIONAL_FLOW_WIDTH + x0) * 4 + channel] & 0xff) *
                        (1.0 - tx)) +
                ((field[(y1 * REGIONAL_FLOW_WIDTH + x1) * 4 + channel] & 0xff) * tx);
        return top * (1.0 - ty) + bottom * ty;
    }

    private static double clampUnit(double value) {
        return Math.max(0.0, Math.min(1.0, value));
    }

    private void drawPredictionProof(float phase, boolean invertVector) {
        GLES20.glUseProgram(predictionProofProgram);
        bindQuad(predictionProofProgram);
        bindTexture(predictionProofProgram, "uPrevious",
                historyTextures[previousIndex], 0);
        bindTexture(predictionProofProgram, "uCurrent",
                historyTextures[currentIndex], 1);
        bindTexture(predictionProofProgram, "uBackwardMotion", activeBackwardFlow(), 2);
        bindTexture(predictionProofProgram, "uForwardMotion", activeForwardFlow(), 3);
        bindTexture(predictionProofProgram, "uGlobalBackwardMotion",
                globalFlowTextures[0], 4);
        bindTexture(predictionProofProgram, "uGlobalForwardMotion",
                globalFlowTextures[1], 5);
        float flowLimit = activeFlowLimitPixels();
        uniform2(predictionProofProgram, "uFlowRange",
                flowLimit / Math.max(1f, historyWidth),
                flowLimit / Math.max(1f, historyHeight));
        GLES20.glUniform1f(GLES20.glGetUniformLocation(
                predictionProofProgram, "uPhase"), phase);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(
                predictionProofProgram, "uInvert"), invertVector ? -1f : 1f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(
                predictionProofProgram, "uDenseEncoding"), densePyramidEnabled ? 1f : 0f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private void drawProofFlow() {
        GLES20.glUseProgram(flowProofProgram);
        bindQuad(flowProofProgram);
        bindTexture(flowProofProgram, "uBackwardMotion", activeBackwardFlow(), 0);
        bindTexture(flowProofProgram, "uForwardMotion", activeForwardFlow(), 1);
        bindTexture(flowProofProgram, "uGlobalBackwardMotion", globalFlowTextures[0], 2);
        bindTexture(flowProofProgram, "uGlobalForwardMotion", globalFlowTextures[1], 3);
        float flowLimit = flowLimitPixels(historyWidth, historyHeight);
        uniform2(flowProofProgram, "uFlowRange",
                flowLimit / Math.max(1f, historyWidth),
                flowLimit / Math.max(1f, historyHeight));
        GLES20.glUniform1f(GLES20.glGetUniformLocation(
                flowProofProgram, "uDenseEncoding"), densePyramidEnabled ? 1f : 0f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    /** Bounded post-swap readback of independently validated dense fields. */
    private void sampleDenseFlowTelemetry() {
        if (!denseResourcesReady || denseProofPixels == null) return;
        long backward = readDenseValidCells(denseValidatedTextures[0]);
        long forward = readDenseValidCells(denseValidatedTextures[1]);
        denseProofCells += (long) PROOF_WIDTH * PROOF_HEIGHT;
        denseBackwardValidCells += backward;
        denseForwardValidCells += forward;
    }

    private long readDenseValidCells(int texture) {
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D, proofTexture, 0);
        GLES20.glViewport(0, 0, PROOF_WIDTH, PROOF_HEIGHT);
        drawTexture2d(texture);
        denseProofPixels.clear();
        GLES20.glReadPixels(0, 0, PROOF_WIDTH, PROOF_HEIGHT,
                GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, denseProofPixels);
        long valid = 0;
        for (int pixel = 0; pixel < PROOF_WIDTH * PROOF_HEIGHT; ++pixel)
            if ((denseProofPixels.get(pixel * 4 + 2) & 0xff) >= 48) ++valid;
        return valid;
    }

    static float flowLimitPixels(int width, int height) {
        float shorterSide = Math.max(1f, Math.min(width, height));
        return Math.min(MAX_FLOW_PIXELS,
                Math.max(MIN_FLOW_PIXELS,
                        shorterSide * MAX_FLOW_SOURCE_FRACTION));
    }

    private long readProofHash(byte[] destination) {
        proofPixels.clear();
        GLES20.glReadPixels(0, 0, PROOF_WIDTH, PROOF_HEIGHT,
                GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, proofPixels);
        long hash = 0xcbf29ce484222325L;
        int bytes = PROOF_WIDTH * PROOF_HEIGHT * 4;
        for (int index = 0; index < bytes; ++index) {
            byte value = proofPixels.get(index);
            destination[index] = value;
            hash ^= value & 0xffL;
            hash *= 0x100000001b3L;
        }
        return hash;
    }

    private void reportStats() {
        int source = frameRate.lockedSourceFps();
        int targetOutput = frameRate.outputFps();
        long now = System.nanoTime();
        if (source != statsTargetSourceFps ||
                targetOutput != statsTargetOutputFps) {
            statsTargetSourceFps = source;
            statsTargetOutputFps = targetOutput;
            statsWindowStartNanos = now;
            statsWindowStartPresents = presents;
            publishReportedFrameRate(source, 0, targetOutput);
            return;
        }
        if (statsWindowStartNanos == 0L) {
            statsWindowStartNanos = now;
            statsWindowStartPresents = presents;
            publishReportedFrameRate(source, 0, targetOutput);
            return;
        }
        long elapsedNs = now - statsWindowStartNanos;
        if (elapsedNs < 1_000_000_000L) return;
        long committed = presents - statsWindowStartPresents;
        int actualOutput = committed <= 0L ? 0 : (int) Math.min(targetOutput,
                Math.max(1L, (long) Math.floor(
                        committed * 1_000_000_000.0 / elapsedNs)));
        statsWindowStartNanos = now;
        statsWindowStartPresents = presents;
        if (phaseDiagCount > 0) {
            Log.i(TAG, "Phase diagnostic" +
                    " generator=" + generatorId +
                    " syntheticCount=" + phaseDiagCount +
                    " phaseMean=" + String.format(java.util.Locale.US, "%.4f",
                            phaseDiagSum / phaseDiagCount) +
                    " phaseMin=" + String.format(java.util.Locale.US, "%.4f",
                            phaseDiagMin) +
                    " phaseMax=" + String.format(java.util.Locale.US, "%.4f",
                            phaseDiagMax) +
                    " endpointSpanMeanMs=" + String.format(java.util.Locale.US,
                            "%.3f",
                            phaseDiagSpanSumNs / phaseDiagCount / 1e6));
            phaseDiagSum = 0.0;
            phaseDiagMin = Float.MAX_VALUE;
            phaseDiagMax = 0f;
            phaseDiagCount = 0;
            phaseDiagSpanSumNs = 0.0;
        }
        publishReportedFrameRate(source, actualOutput, targetOutput);
    }

    private void reportPresentationStall(long frameTimeNs) {
        if (presents != stallObservedPresents) {
            stallObservedPresents = presents;
            stallStartFrameNs = frameTimeNs;
            stallLastLogNs = 0L;
            return;
        }
        if (stallStartFrameNs <= 0L || frameTimeNs - stallStartFrameNs <
                1_000_000_000L || (stallLastLogNs > 0L &&
                frameTimeNs - stallLastLogNs < 1_000_000_000L)) return;
        stallLastLogNs = frameTimeNs;
        long fifoHeadSequence = endpointFifoCount > 0 ?
                endpointFifoSequence[endpointFifoHead] : 0L;
        Log.w(TAG, "Presentation stalled" +
                " generator=" + generatorId +
                " presents=" + presents +
                " source=" + frameRate.lockedSourceFps() +
                " output=" + frameRate.outputFps() +
                " epoch=" + frameRate.bufferedPresentationEpoch() +
                " left=" + activeLeftSequence +
                " right=" + activeRightSequence +
                " pairReady=" + activePairReady +
                " motionReady=" + motionEstimateReady +
                " fifoCount=" + endpointFifoCount +
                " fifoHead=" + fifoHeadSequence +
                " targetSourceNs=" + frameRate.bufferedSelectedTargetSourceNs() +
                " unavailable=" + frameRate.bufferedUnavailableSlotCount() +
                " underruns=" + frameRate.bufferedUnderrunCount() +
                " coalesced=" + endpointFifoCoalesced);
    }

    private void publishReportedFrameRate(int source, int output,
                                          int targetOutput) {
        if (source == reportedSourceFps && output == reportedOutputFps) return;
        reportedSourceFps = source;
        reportedOutputFps = output;
        StatsListener callback = statsListener;
        if (callback != null) callback.onFrameRate(source, output);
        Log.i(TAG, "Frame rate committed " + source + " / " + output +
                " FPS target=" + targetOutput);
    }

    private void bindQuad(int program) {
        int position = GLES20.glGetAttribLocation(program, "aPosition");
        int texture = GLES20.glGetAttribLocation(program, "aTexCoord");
        // aPosition feeds gl_Position and is required for every quad program.
        // aTexCoord is optional: fixed-grid reducers sample gl_FragCoord, so
        // production Adreno correctly optimizes that attribute out
        // and returns -1. Passing -1 to glEnableVertexAttribArray or
        // glVertexAttribPointer is GL_INVALID_VALUE (0x501).
        if (position < 0)
            throw new IllegalStateException("quad shader has no aPosition attribute");
        quad.position(0);
        GLES20.glEnableVertexAttribArray(position);
        GLES20.glVertexAttribPointer(position, 2, GLES20.GL_FLOAT, false,
                4 * FLOAT_BYTES, quad);
        if (texture >= 0) {
            quad.position(2);
            GLES20.glEnableVertexAttribArray(texture);
            GLES20.glVertexAttribPointer(texture, 2, GLES20.GL_FLOAT, false,
                    4 * FLOAT_BYTES, quad);
        }
    }

    private void releaseGl() {
        if (choreographer != null) choreographer.removeFrameCallback(this);
        choreographer = null;
        Surface producer = inputSurface;
        inputSurface = null;
        if (producer != null) producer.release();
        if (inputTexture != null) {
            try { inputTexture.setOnFrameAvailableListener(null); }
            catch (RuntimeException ignored) {}
            inputTexture.release();
            inputTexture = null;
        }
        if (eglDisplay != EGL14.EGL_NO_DISPLAY && eglContext != EGL14.EGL_NO_CONTEXT &&
                eglSurface != EGL14.EGL_NO_SURFACE)
            EGL14.eglMakeCurrent(eglDisplay, eglSurface, eglSurface, eglContext);
        if (denseGpuTimer != null) {
            // PBO/fence/query objects belong to this EGL context. It is still
            // current on the owning handler here; never move this close below
            // eglMakeCurrent(NO_CONTEXT).
            denseGpuTimer.discardPending();
            denseGpuTimer.close();
            denseGpuTimer = null;
        }
        if (softwareUploadBitmap != null) {
            softwareUploadBitmap.recycle();
            softwareUploadBitmap = null;
        }
        if (frameBuffer != 0) GLES20.glDeleteFramebuffers(1, new int[]{frameBuffer}, 0);
        if (historyTextures[0] != 0 || historyTextures[1] != 0)
            GLES20.glDeleteTextures(2, historyTextures, 0);
        if (signatureCandidateTextures[0] != 0)
            GLES20.glDeleteTextures(SIGNATURE_CANDIDATE_SLOTS,
                    signatureCandidateTextures, 0);
        if (endpointFifoTextures[0] != 0)
            GLES20.glDeleteTextures(ENDPOINT_FIFO_CAPACITY,
                    endpointFifoTextures, 0);
        if (flowTextures[0] != 0 || flowTextures[1] != 0 || flowTextures[2] != 0)
            GLES20.glDeleteTextures(3, flowTextures, 0);
        if (reverseFlowTextures[0] != 0 || reverseFlowTextures[1] != 0 ||
                reverseFlowTextures[2] != 0)
            GLES20.glDeleteTextures(3, reverseFlowTextures, 0);
        if (globalCandidateTextures[0] != 0 || globalCandidateTextures[1] != 0)
            GLES20.glDeleteTextures(2, globalCandidateTextures, 0);
        if (globalCandidateWinnerTextures[0] != 0 ||
                globalCandidateWinnerTextures[1] != 0)
            GLES20.glDeleteTextures(2, globalCandidateWinnerTextures, 0);
        if (globalFlowTextures[0] != 0 || globalFlowTextures[1] != 0)
            GLES20.glDeleteTextures(2, globalFlowTextures, 0);
        if (latestTexture != 0) GLES20.glDeleteTextures(1, new int[]{latestTexture}, 0);
        if (proofTexture != 0) GLES20.glDeleteTextures(1, new int[]{proofTexture}, 0);
        if (proofAtlasTexture != 0)
            GLES20.glDeleteTextures(1, new int[]{proofAtlasTexture}, 0);
        if (signatureTexture != 0)
            GLES20.glDeleteTextures(1, new int[]{signatureTexture}, 0);
        if (signaturePreviousTexture != 0)
            GLES20.glDeleteTextures(1, new int[]{signaturePreviousTexture}, 0);
        if (signatureQueryTexture != 0)
            GLES20.glDeleteTextures(1, new int[]{signatureQueryTexture}, 0);
        if (externalTexture != 0) GLES20.glDeleteTextures(1, new int[]{externalTexture}, 0);
        if (copyProgram != 0) GLES20.glDeleteProgram(copyProgram);
        if (textureCopyProgram != 0) GLES20.glDeleteProgram(textureCopyProgram);
        if (signatureCompareProgram != 0) GLES20.glDeleteProgram(signatureCompareProgram);
        if (coarseMotionProgram != 0) GLES20.glDeleteProgram(coarseMotionProgram);
        if (refineMotionProgram != 0) GLES20.glDeleteProgram(refineMotionProgram);
        if (regularizeMotionProgram != 0) GLES20.glDeleteProgram(regularizeMotionProgram);
        if (regionalCoarseCandidateProgram != 0)
            GLES20.glDeleteProgram(regionalCoarseCandidateProgram);
        if (regionalFineCandidateProgram != 0)
            GLES20.glDeleteProgram(regionalFineCandidateProgram);
        if (regionalCandidateWinnerProgram != 0)
            GLES20.glDeleteProgram(regionalCandidateWinnerProgram);
        if (globalMotionProgram != 0) GLES20.glDeleteProgram(globalMotionProgram);
        if (interpolateProgram != 0) GLES20.glDeleteProgram(interpolateProgram);
        if (predictionProofProgram != 0) GLES20.glDeleteProgram(predictionProofProgram);
        if (flowProofProgram != 0) GLES20.glDeleteProgram(flowProofProgram);
        for (int direction = 0; direction < 2; ++direction) {
            for (int level = 0; level < DENSE_LEVELS; ++level)
                if (denseFlowTextures[direction][level][0] != 0)
                    GLES20.glDeleteTextures(2, denseFlowTextures[direction][level], 0);
            if (densePyramidTextures[direction][0] != 0)
                GLES20.glDeleteTextures(2, densePyramidTextures[direction], 0);
        }
        if (denseValidatedTextures[0] != 0)
            GLES20.glDeleteTextures(2, denseValidatedTextures, 0);
        if (densePyramidProgram != 0) GLES20.glDeleteProgram(densePyramidProgram);
        if (denseSolveProgram != 0) GLES20.glDeleteProgram(denseSolveProgram);
        if (denseCycleProgram != 0) GLES20.glDeleteProgram(denseCycleProgram);
        if (denseQ8ProbeProgram != 0) GLES20.glDeleteProgram(denseQ8ProbeProgram);
        if (proofAtlasHeaderProgram != 0)
            GLES20.glDeleteProgram(proofAtlasHeaderProgram);
        if (denseDiagnosticPackProgram != 0)
            GLES20.glDeleteProgram(denseDiagnosticPackProgram);
        if (eglDisplay != EGL14.EGL_NO_DISPLAY) {
            EGL14.eglMakeCurrent(eglDisplay, EGL14.EGL_NO_SURFACE,
                    EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
            if (eglSurface != EGL14.EGL_NO_SURFACE)
                EGL14.eglDestroySurface(eglDisplay, eglSurface);
            if (eglContext != EGL14.EGL_NO_CONTEXT)
                EGL14.eglDestroyContext(eglDisplay, eglContext);
            EGL14.eglTerminate(eglDisplay);
        }
        eglSurface = EGL14.EGL_NO_SURFACE;
        eglContext = EGL14.EGL_NO_CONTEXT;
        eglDisplay = EGL14.EGL_NO_DISPLAY;
        Log.i(TAG, "Frame generator detached presents=" + presents +
                " generated=" + generatedPresents + " real=" + realFrameCount +
                " submitted=" + submittedFrameCount);
    }

    private static void bindTexture(int program, String uniform, int texture, int unit) {
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0 + unit);
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
        GLES20.glUniform1i(GLES20.glGetUniformLocation(program, uniform), unit);
    }

    private static void uniform2(int program, String name, float x, float y) {
        GLES20.glUniform2f(GLES20.glGetUniformLocation(program, name), x, y);
    }

    private static int createProgram(String vertex, String fragment) {
        int vertexShader = compileShader(GLES20.GL_VERTEX_SHADER, vertex);
        int fragmentShader = compileShader(GLES20.GL_FRAGMENT_SHADER, fragment);
        int program = GLES20.glCreateProgram();
        GLES20.glAttachShader(program, vertexShader);
        GLES20.glAttachShader(program, fragmentShader);
        GLES20.glLinkProgram(program);
        int[] status = new int[1];
        GLES20.glGetProgramiv(program, GLES20.GL_LINK_STATUS, status, 0);
        String log = GLES20.glGetProgramInfoLog(program);
        GLES20.glDeleteShader(vertexShader);
        GLES20.glDeleteShader(fragmentShader);
        if (status[0] == 0) {
            GLES20.glDeleteProgram(program);
            throw new IllegalStateException("shader link failed: " + log);
        }
        return program;
    }

    private static int compileShader(int type, String source) {
        int shader = GLES20.glCreateShader(type);
        GLES20.glShaderSource(shader, source);
        GLES20.glCompileShader(shader);
        int[] status = new int[1];
        GLES20.glGetShaderiv(shader, GLES20.GL_COMPILE_STATUS, status, 0);
        if (status[0] == 0) {
            String log = GLES20.glGetShaderInfoLog(shader);
            GLES20.glDeleteShader(shader);
            throw new IllegalStateException("shader compile failed: " + log);
        }
        return shader;
    }

    private static void textureParameters(int target) {
        GLES20.glTexParameteri(target, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
        GLES20.glTexParameteri(target, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
        GLES20.glTexParameteri(target, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexParameteri(target, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE);
    }

    private static void checkGl(String operation) {
        int error = GLES20.glGetError();
        if (error != GLES20.GL_NO_ERROR)
            throw new IllegalStateException(operation + " GL error 0x" +
                    Integer.toHexString(error));
    }

    private static void fail(String operation) {
        throw new IllegalStateException(operation + " failed EGL=0x" +
                Integer.toHexString(EGL14.eglGetError()));
    }

    private static int positive(int value) { return Math.max(1, value); }

    private static String sanitizeRole(String value) {
        if (value == null) return "unspecified";
        String normalized = value.trim().toLowerCase(java.util.Locale.US);
        return normalized.matches("[a-z0-9_-]{1,24}") ? normalized : "unspecified";
    }

    private static float sanitizeRefresh(float value) {
        return Float.isFinite(value) && value >= 20f && value <= 1000f ? value : 60f;
    }
}
