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
import com.thorium.lucent.video.AppOwnedExternalPresentationEvidence;
import com.thorium.lucent.video.CompositorFrameTimeline;
import com.thorium.lucent.video.CompositorPredictionLattice;
import com.thorium.lucent.video.DenseFlowTrajectoryDiagnostics;
import com.thorium.lucent.video.FrameGenerationCadence;
import com.thorium.lucent.video.FrameGenerationPreparationRequest;
import com.thorium.lucent.video.FrameGenerationPresentationRequest;
import com.thorium.lucent.video.MidpointPairBudget;
import com.thorium.lucent.video.NativeSourceImageObserver;
import com.thorium.lucent.video.NativeSourceImageLedger;
import com.thorium.lucent.video.NativeSourceImageProvider;
import com.thorium.lucent.video.GpuPairTimingLedger;
import com.thorium.lucent.video.GpuPhysicalHeadroomLedger;
import com.thorium.lucent.video.SubmissionTimingHistory;
import com.thorium.lucent.video.GpuWorkAdaptationPolicy;
import com.thorium.lucent.video.ExternalGeneratedContentEvidence;
import com.thorium.lucent.video.ExternalPresentationEvidence;
import com.thorium.lucent.video.ExternalPresentationLedger;
import com.thorium.lucent.video.ExternalPhysicalClockBootstrap;
import com.thorium.lucent.video.PhysicalPresentationDeadline;
import com.thorium.lucent.video.PhysicalPresentationCadence;
import com.thorium.lucent.video.PhysicalPresentationClock;
import com.thorium.lucent.video.PresentationClockDiagnostics;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.ArrayDeque;
import java.util.Locale;
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
public final class DisplayFrameGenerator implements FrameGenerationRenderer,
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
    /** Keeps API-31 frame-timeline types out of the min-21 outer class. */
    private static final class Api33VsyncCallback
            implements Choreographer.VsyncCallback {
        private final DisplayFrameGenerator owner;

        Api33VsyncCallback(DisplayFrameGenerator owner) {
            this.owner = owner;
        }

        @Override public void onVsync(Choreographer.FrameData frameData) {
            owner.onVsyncFrame(frameData);
        }

        static Object create(DisplayFrameGenerator owner) {
            return new Api33VsyncCallback(owner);
        }

        static void post(Choreographer choreographer, Object callback) {
            choreographer.postVsyncCallback((Api33VsyncCallback) callback);
        }
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
            "dense-v63-exact-midpoint-max2x-pair-owned-gpu-presented";
    private static final int DENSE_V28_PROOF_SCHEMA_VERSION = 63;
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
    private static final int DENSE_BASE_PASSES_PER_PROMOTION = 38;
    private static final int DENSE_RECIPROCAL_REFINEMENT_PASSES = 2;
    private static final int DENSE_GLOBAL_SEED_PASSES = 8;
    private static final float DENSE_MAX_FLOW_PIXELS = 47f;
    // Tier-scaled reach (2026-09-02, wiiu-b64 flow dumps): 47px was tuned for
    // 60-fps sources.  A 40-fps pace makes the same scene speed 1.5x the
    // per-frame displacement, and the dumps showed 8-13 percent of cells
    // saturating at 47px with the raw solver's 90th-percentile vector at
    // 46-56px; every saturated or inconsistent cell was rejected and the
    // presentation held the exact endpoint, i.e. duplicated frames.  The
    // reach, the coarsest search step and the reciprocal tolerance now scale
    // with the source period (60/fps), capped by the Q8.8 range and by the
    // harness's motion-bounds contract through flowLimitPixels().
    private static final float DENSE_MAX_FLOW_PIXELS_CAP = 120f;

    private float denseTierScale() {
        int fps = frameRate.lockedSourceFps();
        if (fps <= 0) return 1f;
        return Math.max(1f, Math.min(3f, 60f / Math.max(20, fps)));
    }

    private float denseMaxFlowPixels() {
        // wiiu-b65 dumps (2026-09-02): the scene pans ~50px per frame even at
        // 60 fps (raw solver median 44-54px, 90th percentile 63-69px), so the
        // per-tier scaling of 47px still starved the solver.  The reach is
        // now the motion-bounds contract limit itself (flowLimitPixels: ten
        // percent of the shorter side, capped), and the coarse search step
        // is derived from it so the search actually covers the reach.
        return Math.min(DENSE_MAX_FLOW_PIXELS_CAP,
                Math.max(DENSE_MAX_FLOW_PIXELS * denseTierScale(),
                        flowLimitPixels(historyWidth, historyHeight)));
    }

    /** Coarsest-level search step that reaches the active limit in 8 steps plus the 4*2 + 3*1 fine reach. */
    private float denseCoarsestStep() {
        return Math.max(4.5f, (activeFlowLimitPixels() - 11f) / 8f);
    }
    private static final long DENSE_GPU_BUDGET_US = 7333L;
    private static final long DENSE_GPU_BUDGET_WARP_RESERVE_US = 1000L;

    /**
     * Shader-only per-pair budget scaled to the qualified output lattice.
     * The existing conservative limit is retained, but now checks all five
     * estimator stages plus the pair's actual midpoint warp. The 1-ms reserve
     * remains spare margin; it is not substituted for a measured warp cost.
     * Neither this budget nor a fast shader sample proves emulator/compositor
     * physical headroom or permits quality recovery on its own.
     */
    private long denseGpuBudgetUs() {
        // Use the actual number of panel holds per output: on a 120-Hz panel,
        // 30 -> 60 uses two holds; 20 -> 40 uses three. No x3 generation.
        if (frameRate == null) return DENSE_GPU_BUDGET_US;
        int scans = frameRate.panelScansPerOutput();
        long panelPeriodUs = frameRate.panelPeriodNs() / 1000L;
        if (scans < 2 || panelPeriodUs <= 0L) return DENSE_GPU_BUDGET_US;
        long periodUs = panelPeriodUs * scans;
        return Math.max(DENSE_GPU_BUDGET_US,
                periodUs * 4L / 5L - DENSE_GPU_BUDGET_WARP_RESERVE_US);
    }
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
    // The shell-only external qualification performs bounded Vulkan setup,
    // physical phase calibration, and a 240-present SurfaceControl soak before
    // exposing its input Surface. Default and built-in startup remain unchanged.
    private static final long EXTERNAL_START_TIMEOUT_MS = 15000L;
    private static final long EXTERNAL_STOP_TIMEOUT_MS = 15000L;
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
    private static final float MAX_FLOW_PIXELS = 216f;
    // A fixed 80-pixel search is appropriate for a 1080p source, but it is
    // almost half the height of one 256x192 DS screen.  At that scale an
    // ambiguous match can pull a character or background across the whole
    // picture and turn interpolation into a visibly melted frame.  Preserve
    // the reviewed full-resolution bound while limiting low-resolution cores
    // to ten percent of their shorter source dimension.
    private static final float MAX_FLOW_SOURCE_FRACTION = 0.20f;
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
    // Android's per-entry log payload is 4068 bytes including priority/tag
    // overhead. Keep the UTF-8 message at or below 4000 bytes: this leaves a
    // bounded margin for EmuFusionFrameGen while accommodating the physically
    // observed schema-47 extension (3925 bytes late in a qualification run).
    private static final int HEALTH_LOG_MAX_UTF8_BYTES = 4000;
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
    // Four native queries may be pending.  A fifth texture keeps the just-
    // completed classified image immutable while the current callback is
    // retained into a different slot; reusing the completed slot before the
    // caller copies it into the endpoint FIFO breaks query/image ownership.
    private static final int SIGNATURE_CANDIDATE_SLOTS = 5;
    // Two textures own the active interpolation pair. Four additional queued
    // endpoints absorb bounded producer jitter without adding deliberate
    // latency: presentation consumes the head as soon as its source position
    // advances. Overflow rebases to the newest endpoint and waits for its
    // exact successor instead of ever interpolating across a dropped frame.
    // 6 (was 4): slot-lattice producers prime three endpoints deeper than
    // the libretro path (see requiredPrimeDepth); the external path keeps
    // its four-endpoint prime and every other user keeps its depth.
    private static final int ENDPOINT_FIFO_CAPACITY = 6;
    // The active left/right pair consumes two retained images. Keep one exact
    // successor behind it before starting the presentation clock so a REAL
    // right endpoint can rotate immediately into the next ready pair. Starting
    // from only two images made 50-to-100 repeatedly reach a selected panel
    // slot before its next right endpoint existed, despite a healthy producer.
    // Two adjacent endpoints bracket one generated timestamp, but a generated
    // presentation timeline also needs their exact successor retained before
    // it starts. Signature classification is asynchronous: priming from only
    // left/right lets the first midpoint rotate right->left before sequence+2
    // has completed classification, so the following uniform output slot is
    // lost. On a 20->40 path that deterministic miss repeats every interval and
    // collapses actual output back toward 20. Three retained endpoints add one
    // explicitly bounded source-frame of causal look-ahead; direct fallback
    // still presents a lone independently classified REAL without that delay.
    private static final int ENDPOINT_FIFO_PRIME_DEPTH = 3;
    // The private RIFE path needs one additional retained endpoint at prime.
    // Physical r124/r125 proved that a three-endpoint prime occasionally
    // reaches the next REAL with no queued successor: private output for that
    // new interval can then begin only after its midpoint slot has passed and
    // is discarded one pair stale.  Four retained endpoints consume two into
    // the active pair and leave two immutable successors, keeping the native
    // one-slot preparation pipeline a complete source interval ahead.  This
    // extra frame is qualification-backend latency only; the built-in path
    // retains its existing three-endpoint prime and Direct still shows a lone
    // classified endpoint immediately.
    private static final int ENDPOINT_FIFO_EXTERNAL_PRIME_DEPTH = 4;
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
    // Match highp UV arithmetic in both copies: mediump rounding of 1-y in
    // the Vulkan-origin path can shift sampling relative to a real endpoint
    // even when both textures contain the same stationary image.
    private static final String TEXTURE_COPY_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uTexture;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main(){ gl_FragColor=texture2D(uTexture,vTexCoord); }\n";

    // Vulkan image coordinates and GLES texture coordinates use opposite Y
    // origins for the app-owned AHardwareBuffer handoff.  Real endpoints are
    // ordinary GLES textures and must keep TEXTURE_COPY_SHADER unchanged;
    // only the imported generated image needs this presentation-time flip.
    private static final String EXTERNAL_GENERATED_TEXTURE_COPY_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uTexture;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main(){ gl_FragColor=texture2D(uTexture," +
            "vec2(vTexCoord.x,1.0-vTexCoord.y)); }\n";

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
            "vec2 decodeFlow(vec4 field){vec2 legacy=field.rg*2.0-1.0;vec2 dc=(field.rg*255.0-128.0)/127.0;vec2 dense=sign(dc)*dc*dc;return mix(legacy,dense,uDenseEncoding)*uFlowRange;}\n" +
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
            "uniform sampler2D uTexture; uniform vec2 uInputTexel; uniform float uTapScale;\n" +
            "varying vec2 vTexCoord;\n" +
            // uTapScale 0.5: four bilinear taps at +-0.5 input texel = an exact 2x2
            // box for a /2 stage.  uTapScale 1.0 on a /4 stage: taps at +-1 texel
            // straddle texel pairs, so each bilinear tap averages two texels and
            // the four taps cover the 4x4 block exactly (FSR 3 builds its
            // luminance pyramid with a proper box downsampler; the former direct
            // 1080p -> 64x36 draw kept only 2x2 of every 30x30 pixels and aliased
            // the coarse search).
            "void main(){vec2 h=uInputTexel*uTapScale;vec4 v=texture2D(uTexture,clamp(vTexCoord-h,0.0,1.0));\n" +
            "v+=texture2D(uTexture,clamp(vTexCoord+vec2(h.x,-h.y),0.0,1.0));\n" +
            "v+=texture2D(uTexture,clamp(vTexCoord+vec2(-h.x,h.y),0.0,1.0));\n" +
            "v+=texture2D(uTexture,clamp(vTexCoord+h,0.0,1.0));gl_FragColor=v*0.25;}\n";

    // Direction-specific global translation candidates are evaluated in
    // parallel: one output fragment owns one candidate over the fixed 12x8
    // robust sample grid. A tiny reduction pass then selects the best cost.
    // This preserves the schema60 proposal semantics without its physically
    // failed one-fragment serial search. The final seed is still only a basin
    // hint and must improve each dense cell's unchanged current-image objective.
    private static final String DENSE_GLOBAL_COST_SHADER =
            "precision highp float; uniform sampler2D uReference,uTarget,uCenterSeed;\n" +
            "uniform vec2 uSourceSize,uGridSize,uStep,uFlowLimit;uniform float uUseCenter; varying vec2 vTexCoord;\n" +
            "float lum(vec3 c){return dot(c,vec3(.299,.587,.114));}\n" +
            "vec2 chr(vec3 c){return vec2(.5*(c.r-c.b),.5*c.g-.25*(c.r+c.b));}\n" +
            "float rb(float x){return min(abs(x),.18);}\n" +
            "float sampleCost(vec2 uv,vec2 f){vec2 q=uv+f/uSourceSize;if(any(lessThan(q,vec2(0.0)))||any(greaterThan(q,vec2(1.0))))return .42;vec3 a=texture2D(uTarget,uv).rgb,b=texture2D(uReference,q).rgb;vec2 d=abs(chr(a)-chr(b));return rb(lum(a)-lum(b))+.22*(rb(d.x)+rb(d.y));}\n" +
            "float totalCost(vec2 f){float z=0.0;for(int y=0;y<8;y++){for(int x=0;x<12;x++){vec2 uv=vec2((float(x)+.5)/12.0,(float(y)+.5)/8.0);z+=sampleCost(uv,f);}}return z/96.0;}\n" +
            "float unp(vec2 p){float r=floor(p.x*255.0+.5)*256.0+floor(p.y*255.0+.5);return r>=32768.0?r-65536.0:r;}\n" +
            "vec2 dec(vec4 f){return vec2(unp(f.rg),unp(f.ba))/256.0;}\n" +
            "vec2 cost16(float v){float q=floor(clamp(v/.5,0.0,1.0)*65535.0+.5);return vec2(floor(q/256.0),mod(q,256.0))/255.0;}\n" +
            "void main(){vec2 cell=floor(vTexCoord*uGridSize),offset=cell-floor(uGridSize*.5);vec2 center=mix(vec2(0.0),dec(texture2D(uCenterSeed,vec2(.5))),uUseCenter);vec2 f=clamp(center+offset*uStep,-uFlowLimit,uFlowLimit);gl_FragColor=vec4(cost16(totalCost(f)),0.0,0.0);}\n";

    // Hard-cut signal (2026-09-03, gc-b90m title flash): with no physical
    // intermediate across a cut, weak/photometric matches between a black
    // frame and a logo frame still warped pieces of the logo into the
    // synthetic.  This 1x1 pass measures, at the zero shift and at the
    // global seed, the fraction of the same 12x8 sample grid whose luminance
    // differs by more than 0.12; the smaller fraction is the cut evidence the
    // presentation reads (see uDenseCutTex in the interpolate shader).
    private static final String DENSE_GLOBAL_CUT_SHADER =
            "precision highp float; uniform sampler2D uReference,uTarget,uCenterSeed; uniform vec2 uSourceSize; varying vec2 vTexCoord;\n" +
            "float lum(vec3 c){return dot(c,vec3(.299,.587,.114));}\n" +
            "float unp(vec2 p){float r=floor(p.x*255.0+.5)*256.0+floor(p.y*255.0+.5);return r>=32768.0?r-65536.0:r;}\n" +
            "vec2 dec(vec4 f){return vec2(unp(f.rg),unp(f.ba))/256.0;}\n" +
            "float mismatch(vec2 f){float n=0.0;for(int y=0;y<8;y++){for(int x=0;x<12;x++){vec2 uv=vec2((float(x)+.5)/12.0,(float(y)+.5)/8.0);vec2 q=uv+f/uSourceSize;if(any(lessThan(q,vec2(0.0)))||any(greaterThan(q,vec2(1.0)))){continue;}n+=step(.12,abs(lum(texture2D(uTarget,uv).rgb)-lum(texture2D(uReference,q).rgb)));}}return n/96.0;}\n" +
            "void main(){vec2 seed=dec(texture2D(uCenterSeed,vec2(.5)));float m=min(mismatch(vec2(0.0)),mismatch(seed));gl_FragColor=vec4(m,0.0,0.0,1.0);}\n";

    private static final String DENSE_GLOBAL_REDUCE_SHADER =
            "precision highp float;uniform sampler2D uCosts,uZeroCosts,uCenterSeed;\n" +
            "uniform vec2 uGridSize,uStep,uFlowLimit;uniform float uUseCenter;varying vec2 vTexCoord;\n" +
            "float unp(vec2 p){float r=floor(p.x*255.0+.5)*256.0+floor(p.y*255.0+.5);return r>=32768.0?r-65536.0:r;}\n" +
            "vec2 dec(vec4 f){return vec2(unp(f.rg),unp(f.ba))/256.0;}\n" +
            "float costOf(vec2 uv){vec2 v=floor(texture2D(uCosts,uv).rg*255.0+.5);return (v.x*256.0+v.y)/65535.0*.5;}\n" +
            "vec2 p16(float v){float r=mod(floor(v*256.0+.5)+65536.0,65536.0);return vec2(floor(r/256.0),mod(r,256.0))/255.0;}\n" +
            "vec4 enc(vec2 v){return vec4(p16(v.x),p16(v.y));}\n" +
            "void main(){vec2 center=mix(vec2(0.0),dec(texture2D(uCenterSeed,vec2(.5))),uUseCenter);vec2 middle=(floor(uGridSize*.5)+.5)/uGridSize;float bc=costOf(middle),zeroCost=costOf((vec2(4.0)+.5)/vec2(9.0));vec2 best=center;\n" +
            "for(int y=0;y<9;y++){for(int x=0;x<9;x++){if(float(x)<uGridSize.x&&float(y)<uGridSize.y){vec2 uv=(vec2(float(x),float(y))+.5)/uGridSize;float z=costOf(uv);if(z<bc){bc=z;best=clamp(center+(vec2(float(x),float(y))-floor(uGridSize*.5))*uStep,-uFlowLimit,uFlowLimit);}}}}\n" +
            "vec2 zv=floor(texture2D(uZeroCosts,(vec2(4.0)+.5)/vec2(9.0)).rg*255.0+.5);zeroCost=(zv.x*256.0+zv.y)/65535.0*.5;float gain=(zeroCost-bc)/max(zeroCost,.0001);if(gain<.008||length(best)<.25)best=vec2(0.0);gl_FragColor=enc(best);}\n";

    private static final String DENSE_SOLVE_SHADER =
            "precision highp float;\n" +
            "uniform sampler2D uReference,uTarget,uPriorFlow,uTemporalFlow,uReciprocalFlow,uGlobalSeed; uniform float uHasPrior,uUseTemporalGuide,uUseReciprocalGuide,uUseGlobalSeed,uUseNeighborProposal,uReciprocalMargin,uNeighborMargin,uCycleObjectiveWeight,uTemporalLimit,uUseWidePatch,uFinalConsensus,uBypassSearch;\n" +
            "uniform vec2 uAnalysisTexel,uPriorTexel,uReciprocalTexel,uSourceSize,uUpdateStep; uniform float uExhaustiveRadius; varying vec2 vTexCoord;\n" +
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
            "vec2 decReciprocalLinear(vec2 uv){vec2 p=uv/uReciprocalTexel-.5;vec2 b=floor(p);vec2 f=fract(p);\n" +
            "vec2 a=(b+.5)*uReciprocalTexel;vec2 x=vec2(uReciprocalTexel.x,0.0),y=vec2(0.0,uReciprocalTexel.y);\n" +
            "vec2 v00=dec(texture2D(uReciprocalFlow,clamp(a,0.0,1.0))),v10=dec(texture2D(uReciprocalFlow,clamp(a+x,0.0,1.0)));\n" +
            "vec2 v01=dec(texture2D(uReciprocalFlow,clamp(a+y,0.0,1.0))),v11=dec(texture2D(uReciprocalFlow,clamp(a+x+y,0.0,1.0)));\n" +
            "return mix(mix(v00,v10,f.x),mix(v01,v11,f.x),f.y);}\n" +
            // A validated temporal field is ordinary signed RGBA8 flow, not
            // the Q8.8 raw-solver packing above.  It is allocated LINEAR, so
            // decode after the hardware interpolation.  Its B channel is the
            // previous pair's independently validated confidence.
            "vec2 decTemporal(vec4 f){vec2 c=(f.rg*255.0-128.0)/127.0;return sign(c)*c*c*uTemporalLimit;}\n" +
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
            // Only the existing full-resolution reciprocal-refinement draws
            // enable this term. It resolves photometrically ambiguous local
            // candidates with a small symmetric consistency cost; it cannot
            // overcome a clearly better directional image match, and the
            // unchanged cycle/photo/spatial gates remain authoritative.
            "float objective(vec2 f){float z=cost(f);if(uCycleObjectiveWeight>.0){vec2 q=vTexCoord+f/uSourceSize;if(all(greaterThanEqual(q,vec2(0.0)))&&all(lessThanEqual(q,vec2(1.0))))z+=uCycleObjectiveWeight*min(length(f+decReciprocalLinear(q)),4.0);else z+=4.0*uCycleObjectiveWeight;}return z;}\n" +
            "float reg(vec2 f,vec2 m){return .0025*min(length(f-m),12.0);}\n" +
            // A copy-only expansion is safe only when no proposal is requested.
            // The first fine reverse pass supplies reciprocal guidance; the
            // former temporal-only check silently discarded that evidence.
            "void main(){vec2 c=mix(vec2(0.0),decLinear(vTexCoord),uHasPrior);if(uBypassSearch>.5&&uUseTemporalGuide<.5&&uUseReciprocalGuide<.5&&uUseGlobalSeed<.5&&uUseNeighborProposal<.5){gl_FragColor=enc(c);return;}vec2 b=c;float bc=objective(c);\n" +
            // A direction-specific global seed is only a search-basin hint.
            // The current cell's unchanged full objective must improve by a
            // strict margin before the proposal replaces zero/prior.
            "if(uUseGlobalSeed>.5){vec2 g=clamp(dec(texture2D(uGlobalSeed,vec2(.5))),vec2(-uTemporalLimit),vec2(uTemporalLimit));float gc=objective(g);if(length(g)>.25&&gc+.002<bc){bc=gc;c=g;b=g;}}\n" +
            // Successive emulator frames form one continuous video stream.
            // Compare the previous pair's independently validated flow under
            // the CURRENT pair's image cost before using it as a basin hint.
            // A temporal hint must beat the current pair's zero/prior basin
            // by a real margin.  Accepting a tie lets yesterday's camera
            // motion survive into a stopped craft or scene cut, which the
            // physical F-Zero r22 capture exposed as a doubled car and track.
            // This proposal never bypasses the current pair's local search
            // or later F/B checks.
            "if(uUseTemporalGuide>.5){vec4 tf=texture2D(uTemporalFlow,vTexCoord);vec2 t=clamp(decTemporal(tf),vec2(-uTemporalLimit),vec2(uTemporalLimit));float tc=objective(t);if(tf.b>=48.0/255.0&&tc+.002<bc){bc=tc;c=t;b=t;}}\n" +
            // The first reverse solve at each pyramid level receives the
            // finalized forward field at that same level only as an
            // inverse-basin proposal. Approximate the inverse with two
            // fixed-point corrections, then make the reversed image pair
            // beat its own prior/temporal seed by a strict margin. Every subsequent
            // local search remains directional, and unchanged cycle,
            // photometric, texture, and spatial gates remain authoritative.
            "if(uUseReciprocalGuide>.5){vec2 f=decReciprocalLinear(vTexCoord);vec2 q=vTexCoord-f/uSourceSize;\n" +
            "if(all(greaterThanEqual(q,vec2(0.0)))&&all(lessThanEqual(q,vec2(1.0)))){q=vTexCoord-decReciprocalLinear(q)/uSourceSize;\n" +
            "if(all(greaterThanEqual(q,vec2(0.0)))&&all(lessThanEqual(q,vec2(1.0)))){vec2 g=clamp(-decReciprocalLinear(q),vec2(-uTemporalLimit),vec2(uTemporalLimit));float gc=objective(g);if(gc+uReciprocalMargin<bc){bc=gc;c=g;b=g;}}}}\n" +
            "vec2 l=decLinear(clamp(vTexCoord-vec2(uAnalysisTexel.x,0.0),0.0,1.0));\n" +
            "vec2 r=decLinear(clamp(vTexCoord+vec2(uAnalysisTexel.x,0.0),0.0,1.0));\n" +
            "vec2 d=decLinear(clamp(vTexCoord-vec2(0.0,uAnalysisTexel.y),0.0,1.0));\n" +
            "vec2 u=decLinear(clamp(vTexCoord+vec2(0.0,uAnalysisTexel.y),0.0,1.0));\n" +
            "float lc=lum(texture2D(uTarget,vTexCoord).rgb);float e=0.0;\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord-vec2(uAnalysisTexel.x,0.0),0.0,1.0)).rgb)));\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord+vec2(uAnalysisTexel.x,0.0),0.0,1.0)).rgb)));\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord-vec2(0.0,uAnalysisTexel.y),0.0,1.0)).rgb)));\n" +
            "e+=exp(-18.0*abs(lc-lum(texture2D(uTarget,clamp(vTexCoord+vec2(0.0,uAnalysisTexel.y),0.0,1.0)).rgb)));\n" +
            "float edge=clamp(e*.25,0.0,1.0);vec2 m=vec2(med4(l.x,r.x,d.x,u.x),med4(l.y,r.y,d.y,u.y));\n" +
            "float support=step(distance(l,m),2.5)+step(distance(r,m),2.5)+step(distance(d,m),2.5)+step(distance(u,m),2.5);\n" +
            // Sparse changed-pixel ownership in physical F-Zero evidence is a
            // search-basin problem, not authority to fill or relax validity.
            // During the two existing full-resolution reciprocal refinements,
            // test one robust neighbouring basin. Three agreeing neighbours
            // and target-appearance continuity prevent crossing a hard edge;
            // the proposal still has to improve this pixel's current joint
            // image/cycle objective by a strict margin. All later independent
            // cycle, photo, texture, and spatial rejection remains unchanged.
            "if(uUseNeighborProposal>.5&&support>=3.0&&edge>=.55){float mc=objective(m);if(mc+uNeighborMargin<bc){bc=mc;c=m;b=m;}}\n" +
            // The first full-resolution pass is expansion-only. Both
            // directions then execute the same three local searches from
            // their own image pyramids. Reciprocal proposals are current-cost
            // tested above; cycle agreement remains a later rejection signal
            // rather than an asserted inverse constraint.
            "if(uBypassSearch>.5){gl_FragColor=enc(c);return;}\n" +
            // Aperture tie-break (2026-09-04, snes-q1 dumps): a horizontal
            // yard line matches itself under any horizontal shift, so the
            // scan-ordered exhaustive search and the greedy walk chose the
            // first of many equal-cost candidates (the most negative x),
            // shredding the field into differently displaced segments.  Add
            // a small penalty on the distance from the neighbourhood median
            // (zero at the coarsest level, FSR 3 keeps the centre candidate
            // on ties the same way).  0.0025/px capped at 12 px is far
            // below a real textured match's photometric gain, so it only
            // decides otherwise indistinguishable candidates.
            "bc+=reg(c,m);\n" +
            // Exhaustive coarse search (2026-09-03, FSR 3 style): at the
            // coarsest level's first iteration evaluate every candidate of a
            // 9x9 grid at the coarse step (+-4 steps, +-48 px at 1080p) before
            // the greedy walk, so a 60-px texel cannot stall on a plateau of
            // the aliased cost (sim_solve.py showed non-monotone cost along
            // the ray to the true displacement).  81 objective evaluations
            // on 576 texels per direction.
            "if(uExhaustiveRadius>.5){for(int y=-4;y<=4;y++){for(int x=-4;x<=4;x++){if(abs(float(x))>uExhaustiveRadius||abs(float(y))>uExhaustiveRadius)continue;vec2 f=c+vec2(float(x),float(y))*uUpdateStep;float z=objective(f)+reg(f,m);if(z<bc){bc=z;b=f;}}}c=b;}\n" +
            "for(int y=-1;y<=1;y++){for(int x=-1;x<=1;x++){if(x!=0||y!=0){vec2 f=c+vec2(float(x),float(y))*uUpdateStep;float z=objective(f)+reg(f,m);if(z<bc){bc=z;b=f;}}}}\n" +
            "float w=.18*edge;vec2 smooth=(l+r+d+u)*.25;\n" +
            // On the final 128x72 iteration, replace an isolated vector
            // with the robust median of three or more mutually agreeing
            // neighbours. Each direction remains independent and the
            // unchanged cycle/photometric gates stay authoritative.
            // Smoothing is only a proposal, not permission to corrupt a better
            // image match. Thor regression: exact4px became3.445/2.004px with
            // neighboring wrong basins. Test the packed candidate's objective;
            // preserve the selected motion on ties and failed comparisons.
            "if(uFinalConsensus>.5){float g=step(2.5,support)*edge;smooth=m;w=max(w,.65*g);}vec2 proposed=floor(mix(b,smooth,w)*256.0+.5)/256.0;if(objective(proposed)+.000001<objective(b))b=proposed;gl_FragColor=enc(b);}\n";

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
            // 2026-09-03: a .10 magnitude slope here and in the spatial gate
            // (build 91) was tried against a "dashing sprite holds" reading
            // that turned out to be a tracker artefact; it produced no
            // measurable change and was reverted to the calibrated values.
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
            "float st=2.0+.04*length(fm);float ns=step(distance(fl,fm),st)+step(distance(fr,fm),st)+step(distance(fd,fm),st)+step(distance(fu,fm),st);\n" +
            "float coherentFlat=step(2.5,ns)*step(distance(f,fm),1.5+.03*length(fm))*(1.0-smoothstep(.018,.045,textureEnergy));\n" +
            "float activeGate=step(uActiveRect.x+uAnalysisTexel.x,vTexCoord.x)*step(vTexCoord.x,uActiveRect.z-uAnalysisTexel.x)*step(uActiveRect.y+uAnalysisTexel.y,vTexCoord.y)*step(vTexCoord.y,uActiveRect.w-uAnalysisTexel.y);\n" +
            // A reciprocal, photometrically plausible match is still unsafe
            // in repetitive N64 textures when its local field folds or
            // ripples. Require three neighbours to agree around their robust
            // median and require the center to belong to that same basin.
            // This is evaluated independently in each direction and only
            // removes confidence; it never manufactures or fills motion.
            "float spatialSupport=step(2.5,ns);float spatialAgreement=1.0-smoothstep(1.0+.03*length(fm),2.5+.06*length(fm),distance(f,fm));\n" +
            "float spatialGate=spatialSupport*spatialAgreement;\n" +
            "float photoGate=1.0-smoothstep(.10,.22,pe),textureGate=max(smoothstep(.008,.030,textureEnergy),coherentFlat);\n" +
            "float conf=activeGate*inb*cg*photoGate*textureGate*spatialGate;\n" +
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
            // Hardware LINEAR filtering interpolates RG independently of B.
            // A rejected cell must therefore carry exact zero motion; leaving
            // its arbitrary raw vector in RG lets it contaminate an adjacent
            // accepted sample despite zero confidence.
            "vec2 outn=(f/uSourceSize)/max(uFlowRange,vec2(.00001));vec2 outv=clamp(sign(outn)*sqrt(abs(outn))*127.0/255.0+128.0/255.0,0.0,1.0);\n" +
            // Weak tier (2026-09-02, wiiu-b69 dumps): a match that is active,
            // in bounds, textured and photometrically plausible but failed the
            // reciprocal or spatial check is kept at 40/255 -- below the
            // 48/255 validation threshold the proof counts, so it is never
            // claimed as validated, but the presentation may warp with it
            // one-sided (see the weak floor in the interpolate shader)
            // instead of holding an exact endpoint.  75 percent of a 75-px
            // moment's moving cells were photometrically plausible matches
            // whose reverse solve sat in another basin.
            "float weak=activeGate*inb*step(prerequisiteThreshold,photoGate)*step(prerequisiteThreshold,textureGate)*(1.0-step(48.0/255.0,conf));\n" +
            "conf=max(conf,weak*40.0/255.0);\n" +
            "outv=mix(vec2(128.0/255.0),outv,step(40.0/255.0,conf));\n" +
            "gl_FragColor=vec4(outv,conf,mask/255.0);}\n";

    // Neighbour fill (2026-09-02, wiiu-b67 dumps): a rejected cell whose
    // validated neighbours agree is given their mean vector at the minimum
    // supported confidence, so an isolated cycle/spatial rejection inside a
    // coherent moving region is warped with its surroundings instead of
    // degrading the presentation to an exact endpoint copy.  It requires at
    // least four agreeing validated neighbours (a tolerance that scales with
    // the vector), so it cannot spread motion across an edge into a region
    // that has no validated support of its own; a rejected cell whose
    // neighbours are all rejected stays rejected.  Filled cells carry the
    // prerequisite bits their neighbours already proved.
    private static final String DENSE_FILL_SHADER =
            // uRelaxed=1 (passes 3-4): a cell that failed ONLY the texture gate
            // (active, in bounds, photometrically plausible, but a flat 15x15
            // patch: water, sky, gradients) takes the mean of at least three
            // usable neighbours (validated or weak) at the weak confidence, so
            // motion diffuses into low-contrast regions instead of leaving
            // them as endpoint copies next to moving texture (b75 dumps:
            // 44 percent of moving cells failed the texture gate).
            "precision highp float; uniform sampler2D uField; uniform vec2 uTexel; uniform float uRelaxed; varying vec2 vTexCoord;\n" +
            "vec2 dec(vec4 f){vec2 c=(f.rg*255.0-128.0)/127.0;return sign(c)*c*c;}\n" +
            "vec2 encn(vec2 n){return clamp(sign(n)*sqrt(abs(n))*127.0/255.0+128.0/255.0,0.0,1.0);}\n" +
            // uRelaxed=2 (passes 5-6): occlusion inpainting.  A rejected cell
            // with no support in either direction (the leading edge of a fast
            // sprite, where the busiest pixels of every proof window sit) takes
            // the dominant motion of its 7x7 neighbourhood when at least eight
            // usable cells agree with their median, at the weak confidence.
            // This is the standard motion inpainting every interpolator does
            // for disocclusions; it can produce a boundary artefact, never a
            // duplicated frame.
            "void main(){vec4 c=texture2D(uField,vTexCoord);float relaxed=min(uRelaxed,1.0);float wide=step(1.5,uRelaxed);float thr=mix(48.0/255.0,40.0/255.0,relaxed);if(c.b>=thr){gl_FragColor=c;return;}\n" +
            "float bits=floor(c.a*255.0+.5);float flatOnly=step(.5,relaxed)*step(.5,mod(bits,2.0))*step(.5,mod(floor(bits/2.0),2.0))*step(.5,mod(floor(bits/8.0),2.0))*(1.0-step(.5,mod(floor(bits/16.0),2.0)));\n" +
            "if(wide>.5){vec2 wsum=vec2(0.0);float wn=0.0;vec2 wv[48];float wok[48];int wk=0;\n" +
            " for(int y=-3;y<=3;y++){for(int x=-3;x<=3;x++){if(x==0&&y==0)continue;vec2 uv=vTexCoord+vec2(float(x),float(y))*uTexel;vec4 q=texture2D(uField,clamp(uv,0.0,1.0));\n" +
            "  float v=step(thr,q.b)*step(0.0,uv.x)*step(uv.x,1.0)*step(0.0,uv.y)*step(uv.y,1.0);vec2 d=dec(q);wv[wk]=d;wok[wk]=v;wsum+=d*v;wn+=v;wk++;}}\n" +
            " if(wn<8.0){gl_FragColor=c;return;}vec2 wmean=wsum/wn;float wtol=(2.5+.05*length(wmean)*127.0)/127.0;float wagree=0.0;vec2 asum=vec2(0.0);\n" +
            " for(int i=0;i<48;i++){float a=wok[i]*step(distance(wv[i],wmean),wtol);wagree+=a;asum+=wv[i]*a;}\n" +
            " if(wagree<8.0){gl_FragColor=c;return;}vec2 dom=asum/wagree;gl_FragColor=vec4(encn(dom),40.0/255.0,c.a);return;}\n" +
            "if(uRelaxed>.5&&flatOnly<.5){gl_FragColor=c;return;}\n" +
            "vec2 sum=vec2(0.0);float n=0.0;vec2 vs[8];float ok[8];int k=0;\n" +
            "for(int y=-1;y<=1;y++){for(int x=-1;x<=1;x++){if(x==0&&y==0)continue;vec2 uv=vTexCoord+vec2(float(x),float(y))*uTexel;\n" +
            " vec4 q=texture2D(uField,clamp(uv,0.0,1.0));float v=step(thr,q.b)*step(0.0,uv.x)*step(uv.x,1.0)*step(0.0,uv.y)*step(uv.y,1.0);\n" +
            " vec2 d=dec(q);vs[k]=d;ok[k]=v;sum+=d*v;n+=v;k++;}}\n" +
            "float need=mix(4.0,3.0,uRelaxed);if(n<need){gl_FragColor=c;return;}vec2 mean=sum/n;float tol=(2.0+.04*length(mean)*127.0)/127.0;float agree=0.0;\n" +
            "for(int i=0;i<8;i++){agree+=ok[i]*step(distance(vs[i],mean),tol);}\n" +
            "if(agree<need){gl_FragColor=c;return;}\n" +
            "float outConf=mix(48.0/255.0,40.0/255.0,uRelaxed);float outMask=mix(31.0,bits,uRelaxed);\n" +
            "gl_FragColor=vec4(encn(mean),outConf,outMask/255.0);}\n";

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
            "uniform sampler2D uDenseSeedBackwardTex,uDenseSeedForwardTex;\n" +
            "uniform vec2 uDenseSeedSourceSize;uniform float uDenseSeedEnabled;\n" +
            "uniform sampler2D uDenseCutTex;uniform float uDenseCutEnabled;\n" +
            "float seedUnp(vec2 p){float r=floor(p.x*255.0+.5)*256.0+floor(p.y*255.0+.5);return r>=32768.0?r-65536.0:r;}\n" +
            "vec2 seedDec(vec4 f){return vec2(seedUnp(f.rg),seedUnp(f.ba))/256.0;}\n" +
            "uniform float uPhase;\n" +
            "uniform float uDenseEncoding;\n" +
            "varying vec2 vTexCoord;\n" +
            "vec2 decodeFlow(vec4 field){vec2 legacy=field.rg*2.0-1.0;vec2 dc=(field.rg*255.0-128.0)/127.0;vec2 dense=sign(dc)*dc*dc;return mix(legacy,dense,uDenseEncoding)*uFlowRange;}\n" +
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
            // Dense mode never runs the legacy regional/global pass and the
            // global textures hold the clear colour there, so the four taps
            // and their arithmetic are skipped on that path (wave-uniform
            // branch; the samplers stay bound for the non-dense path).
            " if(uDenseEncoding<0.5){\n" +
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
            " }\n" +
            // The vector itself is no longer shortened merely because the
            // photometric match is imperfect (motion blur makes that common).
            // Cycle consistency gates the full measured displacement instead.
            // Confidence decides whether a correspondence is usable; it must
            // not shorten a source-pixel displacement after that decision.
            // Partial vectors systematically under-warped moderate-confidence
            // motion and then failed the independent full-resolution check.
            // Dense mode never runs the legacy regional/global pass, so the
            // global fallback above is empty there and every unsupported cell
            // used to degrade to the exact nearest endpoint: the two synthetic
            // slots of a 40->120 pan were copies of A and B (wiiu-b61 frame
            // proof, 2026-09-02).  Fall back to the dense global seed (camera
            // motion) instead, so an unmatched cell is still warped along the
            // dominant motion rather than duplicated.  It is admitted at the
            // lowest supported reliability so a validated local vector always
            // wins and ownership stays with the phase.
            // Weak-tier floor: a cell the validation kept at 40/255 (photometric
            // one-sided match) is admitted at the lowest supported reliability
            // so ownership picks that direction instead of an endpoint hold.
            " float currentWeak=uDenseEncoding*step(39.5/255.0,backwardField.b)*(1.0-step(47.5/255.0,backwardField.b));\n" +
            " float previousWeak=uDenseEncoding*step(39.5/255.0,forwardField.b)*(1.0-step(47.5/255.0,forwardField.b));\n" +
            " currentReliability=max(currentReliability,0.04*currentWeak);\n" +
            " previousReliability=max(previousReliability,0.04*previousWeak);\n" +
            // Mirror (2026-09-02, wiiu-b70q frame proof): the first synthetic
            // slot still sat on A while the second warped, because the
            // reverse solve often lands in another basin and the forward
            // field is weak or empty where the backward field is validated.
            // A validated direction lends its negated vector to the other
            // side, so both endpoint samples are warped along the same
            // motion instead of one of them collapsing to an endpoint copy.
            // Any usable direction (validated OR weak) lends its vector: the
            // b75 recording still held one of the two synthetic slots in a
            // strict every-other-window pattern because weak-only cells did
            // not mirror and the empty side collapsed to an endpoint copy.
            " float currentStrong=uDenseEncoding*step(39.5/255.0,backwardField.b);\n" +
            " float previousStrong=uDenseEncoding*step(39.5/255.0,forwardField.b);\n" +
            " vec2 backward0=backward;vec2 forward0=forward;\n" +
            " float mirrorForward=currentStrong*(1.0-previousStrong);\n" +
            " float mirrorBackward=previousStrong*(1.0-currentStrong);\n" +
            " forward=mix(forward0,-backward0,mirrorForward);\n" +
            " backward=mix(backward0,-forward0,mirrorBackward);\n" +
            " previousReliability=max(previousReliability,mirrorForward*max(0.04,0.5*currentReliability));\n" +
            " currentReliability=max(currentReliability,mirrorBackward*max(0.04,0.5*previousReliability));\n" +
            " vec2 seedBackwardPx=seedDec(texture2D(uDenseSeedBackwardTex,vec2(0.5)));\n" +
            " vec2 seedForwardPx=seedDec(texture2D(uDenseSeedForwardTex,vec2(0.5)));\n" +
            " vec2 uDenseSeedBackward=seedBackwardPx/uDenseSeedSourceSize;vec2 uDenseSeedForward=seedForwardPx/uDenseSeedSourceSize;\n" +
            " vec2 uDenseSeedActive=uDenseSeedEnabled*vec2(step(0.25,length(seedBackwardPx)),step(0.25,length(seedForwardPx)));\n" +
            " float backwardFallback=(1.0-step(0.02,currentReliability))*uDenseSeedActive.x;\n" +
            " float forwardFallback=(1.0-step(0.02,previousReliability))*uDenseSeedActive.y;\n" +
            " backward=mix(backward,uDenseSeedBackward,backwardFallback);\n" +
            " forward=mix(forward,uDenseSeedForward,forwardFallback);\n" +
            " currentReliability=max(currentReliability,0.03*backwardFallback);\n" +
            " previousReliability=max(previousReliability,0.03*forwardFallback);\n" +
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
            // A low-contrast region that the motion field says is moving is
            // not a static HUD (the "Select a character" header slid by a
            // few pixels at ~6/255 mean change and was held on both synthetic
            // slots, wiiu-b74q); only a region with no supported motion may
            // be held as chrome.
            " float movingHere=anySupported*step(0.75,max(length(backward*uDenseSeedSourceSize),length(forward*uDenseSeedSourceSize)));\n" +
            // A screen-space glyph over a panning background is static between
            // the endpoints yet sits on moving flow; warping it replaced the
            // glyph with background (the "A Start" prompt in wiiu-p102b was
            // bent in every generated frame).  Keep the hold wherever the warp
            // would swap a static pixel for clearly different content; a
            // low-contrast element that really slid (b74q) still warps because
            // its warped sample looks like the pixel it replaces.
            " float replaceDelta=max(max(abs(rawPrevious.r-a.r),abs(rawPrevious.g-a.g)),abs(rawPrevious.b-a.b));\n" +
            " replaceDelta=max(replaceDelta,max(max(abs(rawCurrent.r-b.r),abs(rawCurrent.g-b.g)),abs(rawCurrent.b-b.b)));\n" +
            " float hudReplace=smoothstep(12.0/255.0,40.0/255.0,replaceDelta);\n" +
            " staticHud*=max(1.0-movingHere,hudReplace);\n" +
            // Equal unwarped pixels alone do not establish a static overlay:
            // an object can cross an empty pixel between the two endpoints.
            // Admit that crossing only when BOTH aligned samples agree and
            // strong reciprocal flow also explains the unwarped endpoints.
            // The latter check keeps a stationary glyph whose camera vector
            // would instead land on background. Weak/filled flow cannot use
            // this exception to defeat HUD protection.
            " vec3 rawPreviousPeer=texture2D(uCurrent,clamp(vTexCoord+forward,vec2(0.0),vec2(1.0))).rgb;\n" +
            " vec3 rawCurrentPeer=texture2D(uPrevious,clamp(vTexCoord+backward,vec2(0.0),vec2(1.0))).rgb;\n" +
            " vec3 rawCycleError=max(abs(rawPrevious-rawPreviousPeer),abs(rawCurrent-rawCurrentPeer));\n" +
            " float rawCorrespondenceError=max(max(rawCycleError.r,rawCycleError.g),rawCycleError.b);\n" +
            " float confirmedCrossing=uDenseEncoding*movingHere*step(48.0/255.0,min(previousReliability,currentReliability))*(1.0-step(6.0/255.0,max(alignmentError,rawCorrespondenceError)));\n" +
            " staticHud*=1.0-confirmedCrossing;\n" +
            // Pop-in guard (2026-09-04, gbc-q1 blinking PRESS START, gb-q1):
            // content that appears or disappears between the endpoints has
            // no physical intermediate; when only weak/filled vectors
            // (reliability at the 0.04 floor) support such a cell, the
            // photometric one-sided match is a fragment of unrelated text
            // and warping it produced garbage.  Hold the exact nearest
            // endpoint there instead; validated (strong) vectors still warp.
            " float popIn=smoothstep(0.30,0.45,endpointDelta);\n" +
            " float weakOnly=anySupported*step(previousReliability,0.06)*step(currentReliability,0.06);\n" +
            " predictionAdmission*=1.0-popIn*weakOnly;\n" +
            " vec3 finalColor=mix(exactEndpoint,selectedPrediction," +
                    "predictionAdmission*(1.0-staticHud));\n" +
            // A hard cut has no intermediate: hold the exact left endpoint
            // for the whole synthetic (the documented contract), never a
            // warp of whatever photometric matches survived across the cut.
            " float cutFraction=texture2D(uDenseCutTex,vec2(0.5)).r;\n" +
            // 0.25, not 0.35: a logo-on-black flash changes only ~30 % of the
            // sample grid (gc-p102b) and its second synthetic slot was a
            // warped logo again; a real pan explained by the seed sits far
            // below either threshold.
            " float hardCut=uDenseCutEnabled*step(0.25,cutFraction);\n" +
            " gl_FragColor=vec4(mix(finalColor,rawPrevious,hardCut),1.0);\n" +
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
            "vec2 decodeFlow(vec4 field){vec2 legacy=field.rg*2.0-1.0;vec2 dc=(field.rg*255.0-128.0)/127.0;vec2 dense=sign(dc)*dc*dc;return mix(legacy,dense,uDenseEncoding)*uFlowRange*uInvert;}\n" +
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
    private final ExternalFrameGenerationTransport.Factory externalTransportFactory;
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
    private final SurfaceRetirement surfaceRetirement = new SurfaceRetirement();
    private final AdaptiveFrameRateController frameRate;
    private volatile FrameGenerationRenderer.StatsListener statsListener;
    private volatile int reportedMeasuredTier;
    private volatile boolean reportedStreamIrregular;
    private volatile long reportedAdmissionAcceptedEndpoints;
    private volatile double reportedPanelClockRatio = 1.0;
    private volatile double qualifiedPhysicalPanelHz;
    private volatile long qualifiedPhysicalPanelObservedNs;
    private long qualifiedPhysicalPanelRefinedNs;
    private final long[] builtinCompositorTiming = new long[3];
    private int builtinCompositorTimingSamples;
    private volatile double reportedEndpointDriftUsPerS;
    private volatile long reportedEndpointOffsetNs;
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
    private EGLSurface eglEndpointSurface = EGL14.EGL_NO_SURFACE;
    private EGLConfig endpointEglConfig;
    private ExternalFrameGenerationTransport externalTransport;
    private FrameGenerationPreparationRequest externalRealPairPreparation;
    /** True only after the shared authority selects a backend-certified path. */
    private volatile boolean externalRatePathActive;
    /**
     * The qualified transport is paying its first live HardwareBuffer private
     * execution while visible output remains endpoint-only Direct.
     */
    private boolean externalRatePathPriming;
    /**
     * The controller has published the generated-rate epoch, but no output is
     * selectable until the first exact midpoint for that epoch is READY.
     */
    private boolean externalRatePathOutputPriming;
    /** First resumed app-owned swap needs a complete predecessor scan. */
    private boolean externalAppOwnedActivationFirstSwapPending;
    private boolean externalPresentationFailed;
    private final com.thorium.lucent.video.RuntimePresentationFailure runtimeFailure =
            new com.thorium.lucent.video.RuntimePresentationFailure();
    private boolean externalTimingRejected;
    private long externalTimingRejectedAtNs;
    private int externalTimingRearms;
    /** A physical-slot miss quarantines generation for this long, then a fresh epoch may re-prime. */
    private static final long EXTERNAL_TIMING_REARM_COOLDOWN_NS = 2_000_000_000L;
    /** Bounded per session; a persistently late backend converges to Direct. */
    private static final int EXTERNAL_TIMING_REARM_LIMIT = 20;

    private void markExternalTimingRejected() {
        externalTimingRejected = true;
        externalTimingRejectedAtNs = System.nanoTime();
    }

    /**
     * Bounded recovery for compositor-timeline external transports (LSFG):
     * the permanent quarantine after one late slot turned a demonstration
     * session Direct for good (lsfg10, 2026-09-03: one slot 2 ms late after
     * fifteen seconds at 40).  After a cooldown with the rate path idle, a
     * fresh scheduler epoch re-primes exactly as at start-up, so no stale
     * endpoint or phase crosses the boundary; the count is bounded so a
     * backend that keeps missing still converges to Direct.
     */
    private void maybeRearmExternalTimingAfterCooldown() {
        if (!externalTimingRejected || externalRatePathActive ||
                externalRatePathPriming || externalRatePathOutputPriming ||
                externalTransport == null ||
                externalTransport.usesAppOwnedPresentation())
            return;
        if (System.nanoTime() - externalTimingRejectedAtNs <
                EXTERNAL_TIMING_REARM_COOLDOWN_NS)
            return;
        if (externalTimingRearms >= EXTERNAL_TIMING_REARM_LIMIT) {
            if (externalTimingRearms == EXTERNAL_TIMING_REARM_LIMIT) {
                ++externalTimingRearms;
                Log.e(TAG, "External generation stays Direct: re-arm limit reached" +
                        " generator=" + generatorId +
                        " limit=" + EXTERNAL_TIMING_REARM_LIMIT);
            }
            return;
        }
        ++externalTimingRearms;
        externalTimingRejected = false;
        frameRate.resetPresentation();
        observedBufferedPresentationEpoch = schedulerPresentationEpoch();
        resetEndpointTimelineForSchedulerEpoch();
        refreshProofEvidencePresentationEpoch();
        resetHealthWindowAfterStreamChange();
        Log.w(TAG, "External generation re-armed after slot miss generator=" +
                generatorId + " rearm=" + externalTimingRearms + "/" +
                EXTERNAL_TIMING_REARM_LIMIT);
    }
    private long externalLastUnsafePairRightSequence;
    private long externalUnsafePairCount;
    private DenseGpuTimer externalSignatureTimer;
    private final PhysicalPresentationCadence externalPhysicalCadence =
            new PhysicalPresentationCadence();
    private final ExternalPresentationLedger externalPresentationLedger =
            new ExternalPresentationLedger();
    private final ExternalPresentationEvidence externalPresentationEvidence =
            new ExternalPresentationEvidence();
    private final AppOwnedExternalPresentationEvidence
            appOwnedExternalPresentationEvidence =
                    new AppOwnedExternalPresentationEvidence();
    private final ExternalGeneratedContentEvidence externalGeneratedContentEvidence =
            new ExternalGeneratedContentEvidence();
    private int externalPhysicalScansPerOutput;
    private long externalPhysicalRefreshDurationNs;
    private final PhysicalPresentationClock externalPhysicalClock =
            new PhysicalPresentationClock();
    private final PhysicalPresentationClock builtInPhysicalClock =
            new PhysicalPresentationClock();
    private long builtInLastCommittedTargetNs;
    private final ExternalPhysicalClockBootstrap externalPhysicalClockBootstrap =
            new ExternalPhysicalClockBootstrap();
    private long externalPhysicalAccountingEpoch;
    private long appOwnedExternalSubmittedCount;
    private long externalClockBoundaryWaits;
    private long externalLookaheadReadinessWaits;
    private long externalBootstrapCapacityWaits;
    private long appOwnedExternalPhysicalEndpointCount;
    private long appOwnedExternalPhysicalGeneratedCount;
    /** Monotonic clean timing-window identity within scheduler epochs. */
    private long appOwnedExternalTimingWindow;
    /** Lifetime physical-outcome baselines captured at timing-window start. */
    private long appOwnedExternalTimingDroppedBaseline;
    private long appOwnedExternalTimingUnavailableBaseline;
    /** Rows already planned before the current epoch's first actual scan. */
    private int externalPhysicalAnchorTailRows;
    private boolean externalPhysicalClockBoundaryCommittedThisCallback;
    /**
     * Submitted physical-slot high-water for this renderer/surface lifetime.
     * Timing epochs may reanchor while an earlier submission is still pending;
     * they must not erase its reservation or reuse that physical scan.
     */
    private long externalLastPlannedPhysicalNs;
    private long externalLastSubmittedCompositorExpectedNs;
    private long externalPhysicalSlotRejectedCount;
    /**
     * First successfully submitted Direct output after a rate-path boundary.
     *
     * <p>A 40-Hz output has three equally valid phases on Thor's measured
     * 120-Hz scan lattice. Basing that divisor lattice directly on an
     * arbitrary completed calibration row can put every selection callback
     * about one millisecond before the preceding request's immutable release
     * gate (physical r127). Bootstrap the rate path on the first safely
     * prequeueable panel scan, then keep every later target an exact output
     * period from that committed phase.</p>
     */
    private long externalDirectOutputPhaseAnchorNs;
    private SurfaceTexture inputTexture;
    private Choreographer choreographer;
    private Object compositorVsyncCallback;
    private static final int MAX_COMPOSITOR_FRAME_TIMELINES = 16;
    private static final int MAX_COMPOSITOR_TIMELINE_DIAGNOSTIC_LOGS = 12;
    private final long[] compositorFrameTimelineVsyncIds =
            new long[MAX_COMPOSITOR_FRAME_TIMELINES];
    private final long[] compositorExpectedPresentationTimesNs =
            new long[MAX_COMPOSITOR_FRAME_TIMELINES];
    private final long[] compositorFrameTimelineDeadlinesNs =
            new long[MAX_COMPOSITOR_FRAME_TIMELINES];
    private final long[] compositorFrameTimelineSourceMetadata = new long[2];
    private int compositorFrameTimelineCount;
    private int compositorFrameTimelineSuppliedCount;
    private long compositorFrameTimelineNativeCallbackSequence;
    private long compositorFrameTimelineNativeFrameTimeNs;
    private long compositorFrameTimelineCallbacks;
    private long compositorFrameTimelineSelected;
    private long compositorFrameTimelineUnavailable;
    private long compositorFrameTimelineCommitted;
    private long compositorFrameTimelineErrorMaxNs;
    private int compositorFrameTimelineDiagnosticLogs;
    private final PresentationClockDiagnostics presentationClockDiagnostics =
            new PresentationClockDiagnostics();
    private final CompositorPredictionLattice compositorPredictionLattice =
            new CompositorPredictionLattice();
    private long compositorFrameTimelineProbeLive;
    private long compositorFrameTimelineProbeNoLive;
    private long compositorFrameTimelineProbeErrorSignedMinNs;
    private long compositorFrameTimelineProbeErrorSignedMaxNs;
    private long compositorFrameTimelineProbeErrorSignedLastNs;
    private int externalTexture;
    /** Private RGBA8 image imported from an app-owned external generator. */
    private int externalGeneratedTexture;
    private final ArrayDeque<AppOwnedPhysicalPending>
            appOwnedPhysicalPending = new ArrayDeque<>();
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
    private final long[] endpointFifoUniqueSequence = new long[ENDPOINT_FIFO_CAPACITY];
    private final int[] endpointFifoSubmission = new int[ENDPOINT_FIFO_CAPACITY];
    private final long[] endpointFifoCandidateLoss = new long[ENDPOINT_FIFO_CAPACITY];
    private int endpointFifoHead;
    private int endpointFifoCount;
    private long endpointSequence;
    private long endpointFifoCoalesced;
    private long endpointCandidateUnavailable;
    private long externalEndpointAdmissionRejected;
    private boolean externalEndpointAdmissionBlocked;
    private long endpointTimestampCorrections;
    private long lastProducerTimestampNs;
    private long lastPresentationEndpointTimestampNs;
    private int lastPresentationEndpointSubmission;
    private long uniqueFrameCount;
    // A signature verdict and a temporal endpoint are related but distinct.
    // Pixel uniqueness alone advances the measured source clock; every
    // classified emulator callback may fund the presentation endpoint clock.
    // This is what lets a repeated 20-FPS image occupy its real 50-ms slot
    // instead of turning the next changed image into a false 100-ms gap.
    private boolean classifiedFrameReady;
    // Diagnostic only: a blind first frame/authority bypass is not a pixel verdict.
    private boolean classifiedPixelVerdictKnown;
    private NativeSourceImageObserver nativeSourceImageObserver;
    // Diagnostic owners mirror six FIFO textures, two physical history
    // textures and one classified candidate. Never select cadence/FG here.
    private static final int NATIVE_HISTORY_BASE = ENDPOINT_FIFO_CAPACITY;
    private static final int NATIVE_ADMISSION_SLOT = NATIVE_HISTORY_BASE + 2;
    private NativeSourceImageLedger nativeEndpointProvenance;
    private long nativeProvenanceTransfers, nativeProvenanceMissing, nativeProvenanceFailures;
    private int classifiedUniqueTexture;
    private long classifiedUniqueTimestampNs;
    private int classifiedUniqueSubmission;
    private long activeLeftSequence;
    private long activeRightSequence;
    private long activeLeftTimestampNs;
    private long activeRightTimestampNs;
    private long activeLeftUniqueSequence;
    private long activeRightUniqueSequence;
    private int activeLeftSubmission;
    private int activeRightSubmission;
    private long activeLeftCandidateLoss;
    private long activeRightCandidateLoss;
    private boolean activePairReady;
    private boolean activePairSyntheticCommitted;
    // Endpoint sequence is lifetime-monotonic; never reset this at a scheduler epoch.
    private final MidpointPairBudget midpointPairBudget = new MidpointPairBudget();
    private long lastPromotedEndpointSequence;
    private long bufferedPairCreatedCount;
    private long bufferedSyntheticSelectedCount;
    private long bufferedSyntheticQuotaSkippedCount;
    private long bufferedSyntheticNotReadyCount;
    private long externalPrequeueDeferredCount;
    private long bufferedPresentationCallbackCount;
    private long bufferedLastSelectedSyntheticPair;
    private long observedBufferedPresentationEpoch;
    private int frameBuffer;
    private int copyProgram;
    private int textureCopyProgram;
    private int externalGeneratedTextureCopyProgram;
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
    private int denseGlobalCostProgram;
    private int denseGlobalReduceProgram;
    private int denseGlobalCutProgram;
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
    // Box-filter ladder per endpoint: /4 and /16 of the history (e.g. 480x270, 120x68).
    private final int[][] denseBoxTextures = new int[2][2];
    private final int[] denseBoxWidths = new int[2];
    private final int[] denseBoxHeights = new int[2];
    private final int[] denseGlobalCoarseCostTextures = new int[2];
    private final int[] denseGlobalFineCostTextures = new int[2];
    private final int[] denseGlobalCoarseSeedTextures = new int[2];
    private final int[] denseGlobalSeedTextures = new int[2];
    private final int[] denseGlobalCutTextures = new int[2];
    private int maxFragmentTextureUnits;
    private final int[] denseFinalTextures = new int[2];
    private final int[] denseValidatedTextures = new int[2];
    private final int[] denseFillTextures = new int[2];
    private int denseFillProgram;
    private final int[] denseLevelWidths = new int[DENSE_LEVELS];
    private final int[] denseLevelHeights = new int[DENSE_LEVELS];
    private int denseAnalysisWidth;
    private int denseAnalysisHeight;
    private boolean denseResourcesReady;
    private boolean denseTemporalGuideReady;
    private long densePromotions;
    private long densePasses;
    private long denseCpuSubmitTotalUs;
    private long denseCpuSubmitMaxUs;
    private long denseCpuSubmitLastUs;
    private long denseGpuCompleteTotalUs;
    private long denseGpuCompleteMaxUs;
    private long denseGpuCompleteLastUs;
    private long denseGpuCompletePairs;
    private long denseGpuCompletionSequence;
    private final GpuPairTimingLedger denseGpuPairLedger = new GpuPairTimingLedger(128);
    private final GpuWorkAdaptationPolicy denseGpuAdaptation = new GpuWorkAdaptationPolicy();
    private final GpuPhysicalHeadroomLedger denseGpuHeadroom = new GpuPhysicalHeadroomLedger(128);
    private final long[] denseGpuFailedPairSequences = new long[128];
    private long denseGpuHeadroomPresentationEpoch;
    private long denseGpuPhysicalVerifiedPairs, denseGpuPhysicalUnknownPairs;
    private long denseGpuPhysicalMarginalPairs, denseGpuPhysicalDeadlineMisses;
    private long denseGpuPhysicalUnboundEvents;
    private long denseGpuPhysicalLastAppMarginNs, denseGpuPhysicalLastCompositorMarginNs;
    private int denseGpuReadyTimestampSupportedMask;
    private String pendingDenseGpuHeadroomReject;
    private DenseGpuTimer denseGpuTimer;
    private PhysicalPresentationTracker physicalPresentationTracker;
    private boolean physicalPresentationUnavailableLogged;
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
    private long denseTrajectorySamples;
    private long denseTrajectoryCells;
    private long denseTrajectoryChangedCells;
    private long denseTrajectoryChangedAnyValidCells;
    private long denseTrajectoryChangedAnyMovingValidCells;
    private long denseTrajectoryChangedBothMovingValidCells;
    private long denseTrajectoryChangedTiles;
    private long denseTrajectoryChangedMovingOwnedTiles;
    private long denseTrajectoryErrors;
    private final long[] denseTrajectoryValidCells = new long[2];
    private final long[] denseTrajectoryMovingValidCells = new long[2];
    private final long[] denseTrajectoryStrongMovingValidCells = new long[2];
    private final long[] denseTrajectoryChangedValidCells = new long[2];
    private final long[] denseTrajectoryChangedMovingValidCells = new long[2];
    private final long[] denseTrajectoryUnchangedMovingValidCells = new long[2];
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
    // Adreno's glReadPixels in latestImageIsUnique has SIGSEGV'd the Thor
    // (Eden/Odyssey). Uniqueness then trusts each producer arrival instead
    // of a CPU readback — a 30 fps submit stays 30→60, and we never take
    // the crashing path.
    private boolean signatureReadbackSafe = true;
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
    private int generationTargetFailureWindows;
    private long pendingDenseHealthPresents;
    private long pendingDenseHealthGenerated;
    private long pendingDenseHealthPromoted;
    private boolean generationLogged;
    private boolean outputFrameRateReassertedAfterSwap;
    private int reportedSourceTenths = -1;
    private int reportedOutputTenths = -1;
    private int reportedTargetTenths = -1;
    private boolean reportedCadenceQualified;
    private String reportedBackendLabel;
    private long statsWindowStartNanos;
    private long statsWindowStartPresents;
    // Source admission is intentionally reported on its own fixed one-second
    // window. The ordinary stats window follows the selected target and is
    // therefore rebased whenever an unqualified Direct source fluctuates.
    // Reusing it hid the exact submission/unique-image loss that determines
    // whether a stream can ever fund interpolation.
    private long sourceDiagWindowStartNanos;
    private long sourceDiagStartHardwareSubmits;
    private long sourceDiagStartSoftwareSubmits;
    private long sourceDiagStartUniqueVerdicts;
    private long sourceDiagStartDuplicateVerdicts;
    private long sourceDiagStartUniqueFrames;
    private long sourceDiagStartEndpoints;
    private long sourceDiagStartCandidateUnavailable;
    private long sourceDiagStartTimestampCorrections;
    private long sourceDiagStartFifoCoalesced;
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
        this(output, inputWidth, inputHeight, outputWidth, outputHeight, refreshHz,
                displayRole, displayId, qualificationProofSwitch,
                densePyramidSwitch, denseV27ReducedAnalysisSwitch,
                denseV28ReducedAnalysisSwitch, null);
    }

    DisplayFrameGenerator(Surface output, int inputWidth, int inputHeight,
                                 int outputWidth, int outputHeight, float refreshHz,
                                 String displayRole, int displayId,
                                 QualificationProofSwitch qualificationProofSwitch,
                                 DensePyramidSwitch densePyramidSwitch,
                                 DenseV27ReducedAnalysisSwitch denseV27ReducedAnalysisSwitch,
                                 DenseV28ReducedAnalysisSwitch denseV28ReducedAnalysisSwitch,
                                 ExternalFrameGenerationTransport.Factory
                                         externalTransportFactory) {
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
        this.externalTransportFactory = externalTransportFactory;
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
        this.requestedEglContextMajor = denseV28ReducedAnalysisRequested ||
                externalTransportFactory != null ? 3 : 2;
        this.qualificationProofEnabled = false;
        this.inputWidth = positive(inputWidth);
        this.inputHeight = positive(inputHeight);
        this.outputWidth = positive(outputWidth);
        this.outputHeight = positive(outputHeight);
        this.refreshHz = sanitizeRefresh(refreshHz);
        frameRate = new AdaptiveFrameRateController(this.refreshHz);
        if (externalTransportFactory == null) frameRate.setGenerationAvailable(false);
        // Both Built-in and LSFG must sample the same exact one-midpoint lattice.
        frameRate.setExactDoubleEndpointLatticeRequired(true);
        thread = new HandlerThread("emufusion-frame-generator");
        thread.start();
        handler = new Handler(thread.getLooper());
        handler.post(this::initialize);
        try {
            long timeoutMs = externalTransportFactory == null ?
                    START_TIMEOUT_MS : EXTERNAL_START_TIMEOUT_MS;
            if (!started.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                RuntimeException failure = new IllegalStateException(
                        "frame generator startup timed out");
                closeAfterStartupFailure(failure);
                throw failure;
            }
        } catch (InterruptedException interrupted) {
            RuntimeException failure = new IllegalStateException(
                    "interrupted starting frame generator", interrupted);
            // Retire on the owner even if the caller was interrupted. Restore
            // its interrupt only after the bounded ownership wait has run.
            try { closeAfterStartupFailure(failure); }
            finally { Thread.currentThread().interrupt(); }
            throw failure;
        }
        if (startupFailure != null) {
            RuntimeException failure = new IllegalStateException(
                    "frame generator startup failed", startupFailure);
            closeAfterStartupFailure(failure);
            throw failure;
        }
        if (inputSurface == null || !inputSurface.isValid()) {
            RuntimeException failure = new IllegalStateException(
                    "frame generator produced no input Surface");
            closeAfterStartupFailure(failure);
            throw failure;
        }
        FrameGenerationRendererRegistry.register(this);
    }

    /** The only Surface an emulator receives. The actual display Surface remains private. */
    @Override public Surface inputSurface() { return inputSurface; }

    @Override public void setNativeSourceImageProvider(NativeSourceImageProvider provider) {
        if (closed.get()) return;
        handler.post(() -> {
            if (closed.get()) return;
            if (nativeSourceImageObserver == null && provider != null)
                nativeSourceImageObserver = new NativeSourceImageObserver(
                        SIGNATURE_CANDIDATE_SLOTS);
            if (nativeEndpointProvenance == null && provider != null)
                nativeEndpointProvenance = new NativeSourceImageLedger(NATIVE_ADMISSION_SLOT + 1);
            if (nativeSourceImageObserver != null)
                nativeSourceImageObserver.setProvider(provider);
        });
    }

    private void clearNativeClassifiedObservation() {
        classifiedPixelVerdictKnown = false;
        if (nativeSourceImageObserver != null)
            nativeSourceImageObserver.clearClassified();
    }

    private void classifyLatestNativeObservation() {
        if (nativeSourceImageObserver != null)
            nativeSourceImageObserver.classifyLatest();
    }

    private void finishNativeClassifiedObservation(boolean unique) {
        releaseNativeEndpointProvenance(NATIVE_ADMISSION_SLOT);
        if (nativeEndpointProvenance != null && nativeSourceImageObserver != null &&
                classifiedFrameReady && classifiedUniqueTexture != 0 && classifiedUniqueSubmission > 0) {
            if (nativeSourceImageObserver.copyClassifiedTo(nativeEndpointProvenance,
                    NATIVE_ADMISSION_SLOT, classifiedUniqueTimestampNs, unique,
                    classifiedPixelVerdictKnown) != NativeSourceImageLedger.Result.SUCCESS)
                ++nativeProvenanceFailures;
        }
        if (nativeSourceImageObserver != null)
            nativeSourceImageObserver.finishClassified(
                    classifiedFrameReady && classifiedUniqueTexture != 0 &&
                            classifiedUniqueSubmission > 0,
                    classifiedUniqueTimestampNs, unique, classifiedPixelVerdictKnown);
    }

    /** Metadata release follows loss/retirement of this exact texture owner. */
    private void releaseNativeEndpointProvenance(int slot) {
        if (nativeEndpointProvenance == null) return;
        long lease = nativeEndpointProvenance.lease(slot);
        if (lease != 0L) nativeEndpointProvenance.release(slot, lease);
    }

    /** Call only after the destination texture copy succeeded; source remains retained. */
    private void copyNativeEndpointProvenance(int source, int destination) {
        if (nativeEndpointProvenance == null) return;
        releaseNativeEndpointProvenance(destination);
        long lease = nativeEndpointProvenance.lease(source);
        if (lease == 0L) { ++nativeProvenanceMissing; return; }
        if (nativeEndpointProvenance.copy(source, lease, destination) ==
                NativeSourceImageLedger.Result.SUCCESS) ++nativeProvenanceTransfers;
        else ++nativeProvenanceFailures;
    }

    /** Timeline reset preserves the classified candidate currently being admitted. */
    private void clearNativeEndpointTimeline(boolean fifo) {
        if (nativeEndpointProvenance == null) return;
        for (int slot = fifo ? 0 : NATIVE_HISTORY_BASE; slot < NATIVE_ADMISSION_SLOT; ++slot)
            releaseNativeEndpointProvenance(slot);
    }

    private String nativeEndpointProvenanceDiagnostic() {
        if (nativeEndpointProvenance == null) return "disabled authority=false";
        int left = NATIVE_HISTORY_BASE + previousIndex, right = NATIVE_HISTORY_BASE + currentIndex;
        long a = nativeEndpointProvenance.lease(left), b = nativeEndpointProvenance.lease(right);
        return "authority=false transfers=" + nativeProvenanceTransfers +
                " missing=" + nativeProvenanceMissing + " failures=" + nativeProvenanceFailures +
                " leftEndpoint=" + activeLeftSequence + " rightEndpoint=" + activeRightSequence +
                " leftStatus=" + nativeEndpointProvenance.observation(left, a) +
                " rightStatus=" + nativeEndpointProvenance.observation(right, b) +
                " leftPixels=" + nativeEndpointProvenance.pixelVerdict(left, a) +
                " rightPixels=" + nativeEndpointProvenance.pixelVerdict(right, b) +
                " leftProvider=" + nativeEndpointProvenance.providerGeneration(left, a) +
                " rightProvider=" + nativeEndpointProvenance.providerGeneration(right, b) +
                " leftRawPts=" + nativeEndpointProvenance.rawTimestampNs(left, a) +
                " rightRawPts=" + nativeEndpointProvenance.rawTimestampNs(right, b) +
                " leftClassifiedJoin=" + nativeEndpointProvenance.classifiedJoin(left, a) +
                " rightClassifiedJoin=" + nativeEndpointProvenance.classifiedJoin(right, b) +
                " leftQueueFrame=" + nativeEndpointProvenance.queueFrameNumber(left, a, 0) +
                " rightQueueFrame=" + nativeEndpointProvenance.queueFrameNumber(right, b, 0) +
                " pair=" + nativeEndpointProvenance.compare(left, a, right, b);
    }

    private void closeNativeSourceImageObserver() {
        clearNativeEndpointTimeline(true);
        releaseNativeEndpointProvenance(NATIVE_ADMISSION_SLOT);
        nativeEndpointProvenance = null;
        if (nativeSourceImageObserver != null) {
            nativeSourceImageObserver.close();
            nativeSourceImageObserver = null;
        }
    }

    @Override public String activeBackendLabel() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport != null)
            return externalRatePathActive ? transport.backendLabel() : "Direct";
        return frameRate.generationAvailable() ? "Built-in" : "Direct";
    }

    @Override public int measuredSourceTier() { return reportedMeasuredTier; }
    private volatile boolean reportedStreamLightlyHeld;
    @Override public boolean sourceStreamLightlyHeld() { return reportedStreamLightlyHeld; }
    private volatile double reportedUniqueHz;
    @Override public double sourceUniqueHz() { return reportedUniqueHz; }
    @Override public boolean sourceStreamIrregular() { return reportedStreamIrregular; }
    private volatile boolean reportedClockAcquisitionInProgress;
    @Override public boolean clockAcquisitionInProgress() {
        return reportedClockAcquisitionInProgress;
    }

    // Mirrors the controller flag for the generator's own pair checks: a
    // doubled lattice span whose submission advanced by one is a dropped
    // adapter frame and is bridged (wiiu-b38 logged ~5 "Buffered endpoint
    // discontinuity" cuts per second on exactly two-period spans).
    private volatile boolean slotLatticeProducer;

    @Override public void setSlotLatticeProducer(boolean value) {
        if (closed.get()) return;
        slotLatticeProducer = value;
        handler.post(() -> {
            if (closed.get()) return;
            frameRate.setSlotLatticeProducer(value);
            Log.i(TAG, "Slot-lattice producer mode generator=" + generatorId +
                    " enabled=" + value);
        });
    }

    @Override public void onCoreClockLocked() {
        if (closed.get()) return;
        handler.post(() -> {
            if (closed.get()) return;
            long previousEpoch = frameRate.bufferedPresentationEpoch();
            frameRate.resetPresentation();
            Log.i(TAG, "Core clock locked to panel; presentation re-primed" +
                    " generator=" + generatorId + " role=" + displayRole +
                    " previousEpoch=" + previousEpoch +
                    " epoch=" + frameRate.bufferedPresentationEpoch());
        });
    }
    @Override public double panelClockRatio() { return reportedPanelClockRatio; }
    @Override public double physicalPanelHz() {
        long observed = qualifiedPhysicalPanelObservedNs;
        long now = System.nanoTime();
        return !closed.get() && observed > 0 && now >= observed &&
                now - observed <= 250_000_000L ? qualifiedPhysicalPanelHz : 0.0;
    }
    @Override public double endpointDriftUsPerSecond() { return reportedEndpointDriftUsPerS; }
    @Override public long endpointOffsetNs() { return reportedEndpointOffsetNs; }

    @Override public void setStatsListener(FrameGenerationRenderer.StatsListener value) {
        statsListener = value;
        if (value != null) handler.post(() -> {
            if (statsListener != value) return;
            // A newly attached overlay has not observed any of this Surface's
            // prior swaps. Start from an explicit unknown output instead of
            // replaying a target or a stale listener's last value.
            reportedSourceTenths = -1;
            reportedOutputTenths = -1;
            reportedTargetTenths = -1;
            reportedCadenceQualified = false;
            reportedBackendLabel = null;
            publishReportedFrameRate(frameRate.sustainedMeasuredSourceHz(), 0.0,
                    frameRate.targetOutputHz(), false);
        });
    }

    @Override public void setRuntimeErrorListener(
            com.thorium.lucent.video.RuntimePresentationFailure.Listener value) {
        if (closed.get()) return;
        handler.post(() -> {
            if (closed.get()) return;
            try { runtimeFailure.setListener(value); }
            catch (RuntimeException callbackFailure) {
                Log.e(TAG, "Runtime display error listener failed", callbackFailure);
            }
        });
    }

    /** Uses the fixed cadence declared by a deterministic legacy core. */
    @Override public void setAuthoritativeSourceHz(double sourceHz) {
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
            if (displayId > 0) {
                // The lower panel is direct-only (the same rule
                // refreshQualificationProofState applies after HEALTH_INTERVAL
                // presents); apply it when the clock arrives so every
                // software submit is a presentation endpoint and a lone
                // endpoint is shown at once instead of waiting for a unique
                // frame to survive an epoch resync.  (Dense was already torn
                // down above; refreshQualificationProofState keeps it off.)
                frameRate.setGenerationAvailable(false);
            }
            resetEndpointFifo();
            sourceSignatureReady = false;
            generationLogged = false;
            resetHealthWindowAfterStreamChange();
            Log.i(TAG, "Authoritative source cadence generator=" + generatorId +
                    " sourceHz=" + sourceHz +
                    " enabled=" + frameRate.usesAuthoritativeSourceRate());
        });
    }

    /**
     * Supplies the hardware producer's stamped core-tick clock.
     *
     * <p>This is transport provenance only. Pixel-classified immutable
     * endpoints remain the sole source-rate authority.</p>
     */
    @Override public void setProducerTimelineHz(double timelineHz) {
        if (closed.get()) return;
        handler.post(() -> {
            if (densePyramidEnabled || denseGpuTimer != null) {
                densePyramidEnabled = false;
                teardownDenseEpoch("producer-timeline-change");
            }
            frameRate.setProducerTimelineHz(timelineHz);
            resetEndpointFifo();
            sourceSignatureReady = false;
            generationLogged = false;
            resetHealthWindowAfterStreamChange();
            Log.i(TAG, "Producer timeline generator=" + generatorId +
                    " timelineHz=" + timelineHz +
                    " sourceAuthority=pixel-unique");
        });
    }

    /** Runs once after the producer's first complete buffer is consumed. */
    @Override public void setFirstSubmittedFrameListener(Runnable value) {
        firstSubmittedFrameListener.set(value);
    }

    private void notifyFirstSubmittedFrame() {
        Runnable callback = firstSubmittedFrameListener.getAndSet(null);
        if (callback != null) callback.run();
    }

    /**
     * Fast path for software libretro frames.
     *
     * <p>Uploading the source-sized image avoids asking Android Canvas to
     * rewrite a 1440x1080 CPU buffer 60 times per second merely so this GPU
     * compositor can read it back. The immutable copy is intentional: the
     * emulation render thread immediately reuses its decode array.
     */
    @Override public boolean submitSoftwareFrame(int[] colors, int frameWidth, int frameHeight,
                                       int left, int top, int right, int bottom,
                                       float contentAspect) {
        return submitSoftwareFrame(colors, frameWidth, frameHeight, left, top,
                right, bottom, contentAspect, 0L);
    }

    @Override public boolean submitSoftwareFrame(int[] colors, int frameWidth, int frameHeight,
                                       int left, int top, int right, int bottom,
                                       float contentAspect, long scheduledTimestampNs) {
        if (closed.get() || colors == null || frameWidth < 1 || frameHeight < 1 ||
                left < 0 || top < 0 || right <= left || bottom <= top ||
                right > frameWidth || bottom > frameHeight ||
                colors.length < (long) frameWidth * frameHeight) return false;
        // Software cores used to be stamped with this thread's arrival time,
        // which carries mailbox hand-off and upload jitter: melonDS's exact
        // 2:1 (30 unique of 60) stream never proved its clock and fell to
        // the 20 tier with generation off (run nds-b51, 2026-09-02).  The
        // producer's scheduled due time is the immutable lattice stamp.
        final long producerTimestampNs = scheduledTimestampNs > 0L ?
                scheduledTimestampNs : System.nanoTime();
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
        handler.post(() -> uploadSoftwareFrameSafely(snapshot, width, height, aspect,
                producerTimestampNs));
        return true;
    }

    private void uploadSoftwareFrameSafely(int[] colors, int width, int height,
                                           float aspect, long producerTimestampNs) {
        // This immutable CPU copy owns no producer Image/Surface queue slot.
        // Drop copies already queued when the first fatal failure was reported.
        if (closed.get() || externalPresentationFailed) return;
        try {
            uploadSoftwareFrame(colors, width, height, aspect, producerTimestampNs);
        } catch (RuntimeException failure) {
            failRuntimePresentation("Unable to consume software emulator frame", failure);
        }
    }

    @Override public void setPanelRefreshHz(float newRefreshHz) {
        if (closed.get()) return;
        final float hz = sanitizeRefresh(newRefreshHz);
        handler.post(() -> {
            if (Math.abs(hz - refreshHz) < 0.5f) return;
            float previous = refreshHz;
            qualifiedPhysicalPanelHz = 0.0;
            qualifiedPhysicalPanelObservedNs = 0L;
            builtInPhysicalClock.reset();
            refreshHz = hz;
            frameRate.setDisplayRefreshHz(hz);
            outputFrameRateReassertedAfterSwap = false;
            requestOutputFrameRate("panel-mode");
            frameRate.resetPresentation();
            resetHealthWindowAfterStreamChange();
            Log.i(TAG, "Frame generator panel mode changed generator=" +
                    generatorId + " role=" + displayRole +
                    " displayId=" + displayId +
                    " previousHz=" + previous + " refreshHz=" + hz +
                    " protocolTiers=" + java.util.Arrays.toString(
                            frameRate.protocolTiers()));
        });
    }

    /** Resizes without replacing the producer Surface or restarting an emulator. */
    @Override public void resize(int newInputWidth, int newInputHeight,
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
            qualifiedPhysicalPanelHz = 0.0;
            qualifiedPhysicalPanelObservedNs = 0L;
            builtInPhysicalClock.reset();
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
        android.os.Trace.beginSection("EmuFusion.consumeFrame");
        try {
            consumeAvailableFrame(ignored);
        } finally {
            android.os.Trace.endSection();
        }
    }

    private void consumeAvailableFrame(SurfaceTexture ignored) {
        // Listener is registered on our Handler, so this already owns EGL.
        if (closed.get() || inputTexture == null) return;
        if (externalPresentationFailed) {
            // Drain the producer queue after a fatal consumption/presentation failure
            // so the emulator is not deadlocked behind an abandoned Surface.
            // No failed endpoint may re-enter classification or presentation.
            try { inputTexture.updateTexImage(); }
            catch (RuntimeException ignoredFailure) {}
            return;
        }
        try {
            // Capture the callback arrival for diagnostics/fallback, then bind
            // the retained image to SurfaceTexture's immutable producer PTS.
            // Arrival time describes Handler scheduling, not when the image
            // exists on the emulator timeline; substituting it makes temporal
            // phase depend on Android callback jitter. A missing PTS is
            // explicitly counted as an unqualified fallback below.
            long producerArrivalNs = System.nanoTime();
            inputTexture.updateTexImage();
            long producerBufferTimestampNs = inputTexture.getTimestamp();
            long producerTimestampNs = producerBufferTimestampNs > 0L ?
                    producerBufferTimestampNs : producerArrivalNs;
            if (producerBufferTimestampNs <= 0L)
                ++endpointTimestampCorrections;
            inputTexture.getTransformMatrix(textureTransform);
            copyExternalTo(latestTexture);
            // Observe the exact consumed buffer, never the arrival-time fallback.
            // This sideband stays diagnostic until the complete image/guest-clock
            // and physical-presentation joins are independently established.
            if (nativeSourceImageObserver != null)
                nativeSourceImageObserver.observeLatest(producerBufferTimestampNs);
            ++submittedFrameCount;
            ++diagHardwareSubmits;
            notifyFirstSubmittedFrame();
            boolean classifiedUnique;
            clearNativeClassifiedObservation();
            if (frameRate.usesAuthoritativeSourceRate()) {
                classifiedFrameReady = true;
                classifiedUniqueTexture = latestTexture;
                classifiedUniqueTimestampNs = producerTimestampNs;
                classifiedUniqueSubmission = submittedFrameCount;
                classifyLatestNativeObservation();
                classifiedUnique = true;
            } else {
                classifiedUnique = latestImageIsUnique(producerTimestampNs);
            }
            finishNativeClassifiedObservation(classifiedUnique);
            consumeClassifiedFrame(classifiedUnique);
        } catch (RuntimeException failure) {
            clearNativeClassifiedObservation();
            failRuntimePresentation("Unable to consume emulator frame", failure);
        }
    }

    @Override public void doFrame(long frameTimeNanos) {
        compositorFrameTimelineCount = 0;
        compositorFrameTimelineSuppliedCount = 0;
        renderFrame(frameTimeNanos);
    }

    private void onVsyncFrame(Choreographer.FrameData frameData) {
        compositorFrameTimelineCount = 0;
        compositorFrameTimelineSuppliedCount = 0;
        ++compositorFrameTimelineCallbacks;
        if (frameData != null && externalTransport == null) {
            Choreographer.FrameTimeline[] timelines =
                    frameData.getFrameTimelines();
            compositorFrameTimelineSuppliedCount = timelines == null ? 0 :
                    timelines.length;
            if (timelines != null &&
                    timelines.length <= MAX_COMPOSITOR_FRAME_TIMELINES) {
                for (Choreographer.FrameTimeline timeline : timelines) {
                    if (timeline == null) continue;
                    int index = compositorFrameTimelineCount++;
                    compositorFrameTimelineVsyncIds[index] =
                            timeline.getVsyncId();
                    compositorExpectedPresentationTimesNs[index] =
                            timeline.getExpectedPresentationTimeNanos();
                    compositorFrameTimelineDeadlinesNs[index] =
                            timeline.getDeadlineNanos();
                }
            }
        }
        renderFrame(frameData == null ? System.nanoTime() :
                frameData.getFrameTimeNanos());
        compositorFrameTimelineCount = 0;
        compositorFrameTimelineSuppliedCount = 0;
    }

    private void postNextFrameCallback() {
        if (choreographer == null) return;
        if (externalTransport != null && Build.VERSION.SDK_INT >= 33) {
            if (compositorVsyncCallback == null)
                compositorVsyncCallback = Api33VsyncCallback.create(this);
            Api33VsyncCallback.post(choreographer, compositorVsyncCallback);
        } else {
            choreographer.postFrameCallback(this);
        }
    }

    private void recordCompositorFrameTimelineProbe(
            CompositorFrameTimeline.Probe probe) {
        if (probe == null || !probe.hasLiveTimeline()) {
            ++compositorFrameTimelineProbeNoLive;
            return;
        }
        long errorNs = probe.signedTargetErrorNs();
        if (compositorFrameTimelineProbeLive == 0L) {
            compositorFrameTimelineProbeErrorSignedMinNs = errorNs;
            compositorFrameTimelineProbeErrorSignedMaxNs = errorNs;
        } else {
            compositorFrameTimelineProbeErrorSignedMinNs = Math.min(
                    compositorFrameTimelineProbeErrorSignedMinNs, errorNs);
            compositorFrameTimelineProbeErrorSignedMaxNs = Math.max(
                    compositorFrameTimelineProbeErrorSignedMaxNs, errorNs);
        }
        compositorFrameTimelineProbeErrorSignedLastNs = errorNs;
        ++compositorFrameTimelineProbeLive;
    }

    private void renderFrame(long frameTimeNanos) {
        android.os.Trace.beginSection("EmuFusion.renderFrame");
        try {
            renderTracedFrame(frameTimeNanos);
        } finally {
            android.os.Trace.endSection();
        }
    }

    private void renderTracedFrame(long frameTimeNanos) {
        if (closed.get() || externalPresentationFailed) return;
        // Register the following physical-vsync callback before any rendering
        // or eglSwapBuffers work.  Some Android EGL drivers block swap until
        // the next scan. Registering only after that wait loses the callback
        // that just occurred and deterministically halves a 120-Hz generated
        // stream even though the GPU work itself is within budget.
        postNextFrameCallback();
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
            if (frameRate.observeDisplayFrameTime(frameTimeNanos)) {
                Log.i(TAG, "Physical panel clock committed" +
                        " generator=" + generatorId +
                        " role=" + displayRole +
                        " displayId=" + displayId +
                        " declaredHz=" + String.format(
                                java.util.Locale.US, "%.6f",
                                frameRate.declaredPanelHz()) +
                        " measuredHz=" + String.format(
                                java.util.Locale.US, "%.6f",
                                frameRate.panelHz()) +
                        " samples=" +
                                frameRate.panelClockSamplesForDiagnostics());
            }
            consumeExternalPresentationDiscontinuities();
            consumeExternalEndpointDiscontinuities();
            pollPhysicalPresentations();
            if (externalTransport == null) {
                frameRate.setGenerationAvailable(builtinClockAdmissionReady(
                        densePyramidEnabled, densePyramidUnavailable, displayId,
                        physicalPanelHz()));
            }
            if (externalTransport != null) {
                if (externalPhysicalClockBoundaryCommittedThisCallback) {
                    externalPhysicalClockBoundaryCommittedThisCallback = false;
                    ++externalClockBoundaryWaits;
                    return;
                }
            }
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
            // Choreographer follows the physical panel. Every selected output
            // is an exact divisor of that callback stream, so successful swaps
            // have invariant scan spacing. Timestamp interpolation remains
            // tied to adjacent retained producer endpoints; there are no
            // alternating scan intervals or catch-up submissions.
            synchronizeBufferedPresentationEpoch();
            if (retryPendingAppOwnedPresentation()) return;
            long presentationEpochBeforePrepare = schedulerPresentationEpoch();
            prepareBufferedPairIfPossible();
            prepareExternalRealPairIfPossible();
            if (schedulerPresentationEpoch() != presentationEpochBeforePrepare) {
                logBufferedEpochBoundary("pair-prepare",
                        presentationEpochBeforePrepare);
                // Pair preparation already replaced the unsafe interval with
                // its safe new REAL endpoint. Adopt that controller epoch in
                // place; clearing the freshly prepared endpoint here hid it
                // and left a selected decision pending into the next callback.
                observedBufferedPresentationEpoch =
                        schedulerPresentationEpoch();
                // Pair preparation can reject a real source discontinuity
                // before presentBuffered() takes its post-swap epoch snapshot.
                // Rebase proof and HEALTH at that exact boundary; otherwise a
                // later record mixes counts from the ended timeline with the
                // replacement epoch identity.
                refreshProofEvidencePresentationEpoch();
                resetHealthWindowAfterStreamChange();
            }
            ++bufferedPresentationCallbackCount;
            // External Vulkan presentation returns through
            // presentExternalBuffered() and therefore never reaches the
            // built-in EGL path's 120-present proof refresh below.  Poll the
            // shell-only qualification switch from this shared callback path
            // at most once per 120 physical callbacks.  r75 otherwise stayed
            // Direct forever after the gameplay owner armed proof.  The
            // bounded cadence avoids Settings.Global I/O on every vsync while
            // activating or disabling the qualification arm within one
            // measured-panel second.
            if (externalTransport != null &&
                    bufferedPresentationCallbackCount % HEALTH_INTERVAL == 0L) {
                refreshQualificationProofState();
                maybeRearmExternalTimingAfterCooldown();
            }
            // Backend certification is rate-path specific. In particular, an
            // Ocarina 20->40 qualification arm must remain dormant during the
            // game's 60-Hz startup/menu transient; success or package presence
            // at 20->40 cannot authorize a cold 60->120 inference deadline.
            // Refusal remains endpoint-only Direct presentation.
            if (externalTransport != null) {
                int candidateSource = frameRate.candidateGeneratedSourceFps();
                int candidateOutput = frameRate.candidateGeneratedOutputFps();
                int candidateScans =
                        frameRate.candidateGeneratedPanelScansPerOutput();
                boolean appOwnedPresentation =
                        externalTransport.usesAppOwnedPresentation();
                boolean physicalAuthorityReady = appOwnedPresentation ?
                        physicalPresentationTracker != null &&
                                physicalPresentationTracker.available() :
                        externalPhysicalClockBootstrap.complete();
                boolean supported = frameRate.panelClockMeasured() &&
                        physicalAuthorityReady &&
                        // Every currently constructible external transport is
                        // an explicit shell-only qualification arm.  Keep it
                        // endpoint-only until the moving-game proof owner arms
                        // this generator.  r74 otherwise generated over the
                        // Ocarina title/intro, suffered one genuine slot miss,
                        // and correctly quarantined itself before the HUD was
                        // ever reached; the later proof could then never test
                        // the gameplay rate path.  This does not weaken the
                        // miss quarantine: once proof is armed, any slot miss
                        // remains permanent for the session.
                        qualificationProofEnabled &&
                        !externalTimingRejected &&
                        candidateScans > 0 &&
                        externalTransport.supportsRatePath(
                                candidateSource, candidateOutput);
                boolean privatePipelineWarm = supported &&
                        externalTransport.privateGenerationPipelineWarm();
                boolean beginPriming = supported &&
                        !externalRatePathActive &&
                        !externalRatePathPriming;
                boolean beginOutputPriming = supported &&
                        !externalRatePathActive &&
                        externalRatePathPriming &&
                        !externalRatePathOutputPriming &&
                        privatePipelineWarm;
                boolean disablePath = !supported &&
                        (externalRatePathActive || externalRatePathPriming);
                if (beginPriming || beginOutputPriming || disablePath) {
                    Log.i(TAG, "External rate-path transition" +
                            " generator=" + generatorId +
                            " lockedSourceFps=" + frameRate.lockedSourceFps() +
                            " candidateSource=" + candidateSource +
                            " presentationSourceHz=" + String.format(
                                    java.util.Locale.US, "%.9f",
                                    frameRate.presentationSourceHz()) +
                            " candidateOutput=" + candidateOutput +
                            " candidateScans=" + candidateScans +
                            " panelMeasured=" +
                                    (frameRate.panelClockMeasured() ? 1 : 0) +
                            " supported=" + (supported ? 1 : 0) +
                            " previousActive=" +
                                    (externalRatePathActive ? 1 : 0) +
                            " previousPriming=" +
                                    (externalRatePathPriming ? 1 : 0) +
                            " previousOutputPriming=" +
                                    (externalRatePathOutputPriming ? 1 : 0) +
                            " privatePipelineWarm=" +
                                    (privatePipelineWarm ? 1 : 0) +
                            " generationAvailable=" +
                                    (frameRate.generationAvailable() ? 1 : 0) +
                            " retentionProof=" +
                                    frameRate.canonicalRetentionProofSummaryForDiagnostics() +
                            " rejectedQualifiedClockHz=" + String.format(
                                    java.util.Locale.US, "%.3f",
                                    frameRate.lastRejectedQualifiedTimestampSourceHzForDiagnostics()) +
                            " rejectedQualifiedProof=" +
                                    frameRate.lastRejectedQualifiedTimestampProofForDiagnostics());
                    // A rate-path boundary is a presentation-session boundary.
                    // Never carry FIFO endpoints, native Images, interpolation
                    // readiness, or controller credit from an unauthorized
                    // startup/menu rate into the newly certified path.
                    // Publish the rate-path identity before resetting the
                    // transport timeline. Qualification backends may pipeline
                    // only already-prepared future-pair evidence while this
                    // exact path is active; startup Direct retains its smaller
                    // endpoint-only deadline workload.
                    if (beginPriming) {
                        // Warm the model and prove a complete endpoint-import
                        // cache rotation while visible output remains Direct.
                        // No generated target is published in this stage.
                        externalTransport.setGeneratedRatePathActive(true);
                        externalRatePathPriming = true;
                        return;
                    }
                    if (beginOutputPriming) {
                        // Publish exactly one fresh generated scheduler epoch,
                        // discard the warm-up pair, and hold its first new
                        // three-endpoint window without presenting. The exact
                        // first midpoint is computed below before 120 becomes
                        // active; this avoids exposing an 8.33-ms slot to a
                        // 13-ms cold/current-pair preparation.
                        frameRate.setGenerationAvailable(true);
                        observedBufferedPresentationEpoch =
                                schedulerPresentationEpoch();
                        invalidateBufferedPairForReprime(false);
                        refreshProofEvidencePresentationEpoch();
                        externalRatePathOutputPriming = true;
                        externalDirectOutputPhaseAnchorNs = 0L;
                        resetHealthWindowAfterStreamChange();
                        return;
                    }
                    externalTransport.setGeneratedRatePathActive(false);
                    externalRatePathPriming = false;
                    externalRatePathOutputPriming = false;
                    externalRatePathActive = false;
                    externalAppOwnedActivationFirstSwapPending = false;
                    externalDirectOutputPhaseAnchorNs = 0L;
                    frameRate.setGenerationAvailable(false);
                    invalidateBufferedPairForReprime(false);
                    resetHealthWindowAfterStreamChange();
                    return;
                }
            }
            // Endpoint buffers reach an external ImageReader asynchronously.
            // The renderer-side FIFO may already own an exact adjacent pair
            // while the external backend does not yet own the corresponding
            // HardwareBuffers.  Do not let the controller select (and commit)
            // a REAL or SYNTHETIC presentation until that ownership transfer
            // is complete.  Skipping this callback cannot create a catch-up
            // burst: no controller slot is selected, and the next successful
            // selection is paced from that later physical callback.  The
            // immutable endpoint pair remains retained for the next attempt.
            if (externalTransport != null &&
                    (activeLeftSequence <= 0L ||
                            activeRightSequence != activeLeftSequence + 1L ||
                            !externalTransport.hasAdjacentPair(
                                    activeLeftSequence,
                                    activeRightSequence))) {
                return;
            }
            if (externalRatePathOutputPriming) {
                if (!primeFirstExternalGeneratedOutput()) return;
                // Output priming deliberately pauses visible swaps. Use that
                // bounded pause to retire every Direct-era physical request
                // before publishing the generated epoch. Otherwise an old
                // compositor-pending Direct row can resolve after activation
                // and incorrectly quarantine a newly proven 60->120 path.
                // The tracker remains strictly fail-closed: a genuine drop or
                // unavailable Direct row is consumed above and rejects the
                // arm before this clean-boundary gate can pass.
                if (externalTransport.usesAppOwnedPresentation() &&
                        (!appOwnedPhysicalPending.isEmpty() ||
                                physicalPresentationTracker == null ||
                                physicalPresentationTracker.pendingCount() != 0))
                    return;
                // The first output is READY for this exact held pair. Expose
                // the generated rate without another controller/timeline
                // reset, then let the ordinary selector present REAL-left.
                externalRatePathOutputPriming = false;
                externalRatePathPriming = false;
                externalRatePathActive = true;
                externalAppOwnedActivationFirstSwapPending =
                        externalTransport.usesAppOwnedPresentation();
                motionEstimateReady = true;
                activePairReady = true;
                resetHealthWindowAfterStreamChange();
                Log.i(TAG, "External rate-path first output ready" +
                        " generator=" + generatorId +
                        " epoch=" + schedulerPresentationEpoch() +
                        " pair=" + activeLeftSequence + "/" +
                                activeRightSequence +
                        " source=" + frameRate.lockedSourceFps() +
                        " output=" + frameRate.outputFps());
            }
            // A newly activated generated path has no pair assessment yet.
            // Hold its first retained pair until the already-buffered third
            // endpoint is backend-prepared; the first exact REAL can then
            // pipeline the next pair's proof without cold-importing on its
            // visible deadline. Once this pair itself is READY, ordinary
            // generated scheduling no longer depends on look-ahead ownership.
            if (externalTransport != null && externalRatePathActive &&
                    !activePairReady &&
                    externalTransport.generationReadiness(
                            activeLeftSequence, activeRightSequence) ==
                            ExternalFrameGenerationTransport.GenerationReadiness.PENDING &&
                    !externalTransport.hasPreparedLookahead(activeRightSequence)) {
                ++externalLookaheadReadinessWaits;
                return;
            }
            // Before VK_GOOGLE display timing has calibrated the physical
            // clock, the generic external planner may retain one endpoint in
            // the transport across several panel callbacks. Do not select or
            // consume another controller slot while that exact zero-wait
            // submission capacity is unavailable. Once bootstrap completes,
            // the proven Direct/generated planners and their explicit
            // DEFERRED handling remain authoritative.
            if (externalTransport != null &&
                    !externalPhysicalClockBootstrap.complete() &&
                    !externalTransport.visibleSubmissionReady()) {
                ++externalBootstrapCapacityWaits;
                return;
            }
            long underrunsBefore = frameRate.bufferedUnderrunCount();
            long presentationEpochBeforeSelection = schedulerPresentationEpoch();
            long deadlineNowNs = System.nanoTime();
            boolean appOwnedExternal = externalTransport != null &&
                    externalTransport.usesAppOwnedPresentation();
            boolean appOwnedClockAvailable = appOwnedExternal &&
                    externalPhysicalClock.available();
            boolean externalClockAvailable = externalTransport != null &&
                    !appOwnedExternal &&
                    externalPhysicalClock.available();
            PhysicalPresentationDeadline deadline = appOwnedExternal ?
                    (appOwnedClockAvailable ?
                            (externalRatePathActive ?
                                    PhysicalPresentationDeadline.
                                            nextAlignedAppOwnedGenerated(
                                            frameTimeNanos,
                                            externalPhysicalClock.trackedPlanningAnchorNs(),
                                            externalPhysicalClock.planningPeriodNs(),
                                            frameRate.panelScansPerOutput(),
                                            deadlineNowNs,
                                            externalLastPlannedPhysicalNs) :
                                    PhysicalPresentationDeadline.nextAlignedOutputDirect(
                                            frameTimeNanos,
                                            externalPhysicalClock.trackedPlanningAnchorNs(),
                                            externalPhysicalClock.planningPeriodNs(),
                                            externalRatePathActive ?
                                                    frameRate.panelScansPerOutput() :
                                                    appOwnedPhysicalScansPerOutput(),
                                            deadlineNowNs,
                                            externalLastPlannedPhysicalNs)) :
                            PhysicalPresentationDeadline.next(
                                    frameTimeNanos,
                                    frameRate.panelPeriodNs(),
                                    deadlineNowNs)) : externalClockAvailable ?
                    (externalRatePathActive ?
                            (externalTransport.requiresCompositorFrameTimeline() ?
                                    PhysicalPresentationDeadline.nextAlignedOutput(
                                            frameTimeNanos,
                                            externalPhysicalClock.anchorNs(),
                                            externalPhysicalClock.planningPeriodNs(),
                                            frameRate.panelScansPerOutput(),
                                            deadlineNowNs,
                                            externalLastPlannedPhysicalNs) :
                                    (modeAlignedSixtyHertzOneScanOutput() ?
                                            PhysicalPresentationDeadline.
                                                    nextAlignedOneScanOutputDirectAfterPredecessor(
                                                    frameTimeNanos,
                                                    externalDirectOutputPhaseAnchorNs > 0L ?
                                                            externalDirectOutputPhaseAnchorNs :
                                                            externalPhysicalClock.anchorNs(),
                                                    externalPhysicalClock.planningPeriodNs(),
                                                    deadlineNowNs,
                                                    externalLastPlannedPhysicalNs) :
                                            PhysicalPresentationDeadline.
                                                    nextAlignedOutputDirect(
                                                    frameTimeNanos,
                                                    externalDirectOutputPhaseAnchorNs > 0L ?
                                                            externalDirectOutputPhaseAnchorNs :
                                                            externalPhysicalClock.anchorNs(),
                                                    externalPhysicalClock.planningPeriodNs(),
                                                    externalDirectOutputPhaseAnchorNs > 0L ?
                                                            frameRate.panelScansPerOutput() : 1,
                                                    deadlineNowNs,
                                                    externalLastPlannedPhysicalNs))) :
                            // Endpoint-only Direct has no private inference or
                            // compositor predecessor token to prepare.  Do not
                            // retain its single native WSI slot for a complete
                            // refresh-derived preparation window: physical
                            // r170 proved that a 30-Hz request held about
                            // 44 ms early remains nativePending when the next
                            // source endpoint arrives and collapses delivered
                            // cadence to about 17 FPS.  Use the same bounded
                            // direct admission on the next safe panel scan as
                            // the generated-path bootstrap.  A divisor of one
                            // here does not relabel Direct as panel-rate output;
                            // the controller still submits only independently
                            // classified source endpoints, while the immutable
                            // content timestamp and physical ledger remain the
                            // cadence authority.
                            (externalTransport.requiresCompositorFrameTimeline() ?
                                    PhysicalPresentationDeadline.nextAlignedOutput(
                                            frameTimeNanos,
                                            externalPhysicalClock.anchorNs(),
                                            externalPhysicalClock.planningPeriodNs(),
                                            1,
                                            deadlineNowNs,
                                            externalLastPlannedPhysicalNs) :
                                    PhysicalPresentationDeadline.nextAlignedOutputDirect(
                                            frameTimeNanos,
                                            externalPhysicalClock.anchorNs(),
                                            externalPhysicalClock.planningPeriodNs(),
                                            1,
                                            deadlineNowNs,
                                            externalLastPlannedPhysicalNs))) :
                    (externalTransport != null ?
                            PhysicalPresentationDeadline.nextExternal(
                                    frameTimeNanos,
                                    frameRate.panelPeriodNs(),
                                    deadlineNowNs) :
                            nextBuiltInDeadline(frameTimeNanos, deadlineNowNs));
            if (!deadline.valid()) {
                Log.e(TAG, "No future physical presentation deadline" +
                        " generator=" + generatorId +
                        " callbackNs=" + frameTimeNanos +
                        " panelPeriodNs=" + frameRate.panelPeriodNs());
                return;
            }
            // Startup may deliver queued source frames faster than real time.
            // Monotonic target selection alone turns that burst into permanent
            // future-slot debt. Keep the retained endpoint unconsumed until its
            // Direct submission window opens; do not retime a committed frame.
            // Generated activation has its own predecessor/ready-output gates.
            if (appOwnedExternal && !externalRatePathActive &&
                    !directExternalSubmissionWindowOpen(
                            deadline.contentPresentationTimeNs(), deadlineNowNs,
                            frameRate.panelPeriodNs(), appOwnedPhysicalScansPerOutput()))
                return;
            CompositorFrameTimeline.Selection compositorTimeline = null;
            if (externalTransport != null &&
                    externalTransport.requiresCompositorFrameTimeline()) {
                java.util.Arrays.fill(
                        compositorFrameTimelineSourceMetadata, 0L);
                compositorFrameTimelineCount =
                        externalTransport.copyCompositorFrameTimelines(
                                compositorFrameTimelineVsyncIds,
                                compositorExpectedPresentationTimesNs,
                                compositorFrameTimelineDeadlinesNs,
                                compositorFrameTimelineSourceMetadata);
                if (compositorFrameTimelineCount < 0 ||
                        compositorFrameTimelineCount >
                                MAX_COMPOSITOR_FRAME_TIMELINES)
                    throw new IllegalStateException(
                            "native compositor frame-timeline count is invalid");
                compositorFrameTimelineSuppliedCount =
                        compositorFrameTimelineCount;
                compositorFrameTimelineNativeCallbackSequence =
                        compositorFrameTimelineSourceMetadata[0];
                compositorFrameTimelineNativeFrameTimeNs =
                        compositorFrameTimelineSourceMetadata[1];
                if (compositorFrameTimelineCount > 0 &&
                        (compositorFrameTimelineNativeCallbackSequence <= 0L ||
                                compositorFrameTimelineNativeFrameTimeNs <= 0L))
                    throw new IllegalStateException(
                            "native compositor frame-timeline identity is invalid");
                if (!compositorPredictionLattice.observe(
                        compositorFrameTimelineNativeFrameTimeNs,
                        compositorExpectedPresentationTimesNs,
                        compositorFrameTimelineCount)) {
                    ++compositorFrameTimelineUnavailable;
                    // A lost scan identity ends the stream, not permission to
                    // shift a divisor phase or repair already-minted requests.
                    if (compositorPredictionLattice.available()) {
                        compositorPredictionLattice.reset();
                        long previousEpoch = schedulerPresentationEpoch();
                        frameRate.resetPresentation();
                        resetEndpointTimelineForSchedulerEpoch();
                        refreshProofEvidencePresentationEpoch();
                        resetHealthWindowAfterStreamChange();
                        Log.w(TAG, "Compositor prediction discontinuity" +
                                " generator=" + generatorId +
                                " previousEpoch=" + previousEpoch +
                                " epoch=" + schedulerPresentationEpoch());
                    }
                    return;
                }
                if (!externalClockAvailable) {
                    // Before the first actual-present timestamp there is no
                    // measured physical phase to match. Adopt Android's
                    // earliest still-meetable timeline as the bootstrap scan;
                    // never widen the strict selector for calibrated output.
                    compositorTimeline =
                            CompositorFrameTimeline.selectEarliestRefreshSafeTarget(
                                    frameRate.panelPeriodNs(), deadlineNowNs,
                                    compositorFrameTimelineVsyncIds,
                                    compositorExpectedPresentationTimesNs,
                                    compositorFrameTimelineDeadlinesNs,
                                    compositorFrameTimelineCount);
                    if (compositorTimeline != null) {
                        deadline = PhysicalPresentationDeadline.
                                fromCompositorTimeline(
                                        compositorTimeline.
                                                expectedPresentationTimeNs(),
                                        compositorTimeline.targetDeadlineNs(),
                                        deadlineNowNs);
                        if (!deadline.valid()) compositorTimeline = null;
                    }
                } else {
                    // The current Android prediction owns a NEW request's
                    // planning phase. Fences independently measure cadence;
                    // they must not supply a stale prediction's slope.
                    int predictionScans = externalRatePathActive ?
                            frameRate.panelScansPerOutput() : 1;
                    deadline = PhysicalPresentationDeadline.nextAlignedOutput(
                            frameTimeNanos,
                            compositorPredictionLattice.anchorNs(predictionScans),
                            compositorPredictionLattice.periodNs(),
                            predictionScans, deadlineNowNs,
                            externalLastPlannedPhysicalNs);
                    if (!deadline.valid()) return;
                    compositorTimeline =
                            CompositorFrameTimeline.selectRefreshSafeTarget(
                            deadline.contentPresentationTimeNs(),
                            externalPhysicalClock.planningPeriodNs(),
                            deadlineNowNs,
                            compositorFrameTimelineVsyncIds,
                            compositorExpectedPresentationTimesNs,
                            compositorFrameTimelineDeadlinesNs,
                            compositorFrameTimelineCount);
                }
                if (compositorTimeline == null) {
                    ++compositorFrameTimelineUnavailable;
                    CompositorFrameTimeline.Probe probe =
                            CompositorFrameTimeline.probe(
                                    deadline.contentPresentationTimeNs(),
                                    deadlineNowNs,
                                    compositorFrameTimelineVsyncIds,
                                    compositorExpectedPresentationTimesNs,
                                    compositorFrameTimelineDeadlinesNs,
                                    compositorFrameTimelineCount);
                    recordCompositorFrameTimelineProbe(probe);
                    if (compositorFrameTimelineDiagnosticLogs <
                            MAX_COMPOSITOR_TIMELINE_DIAGNOSTIC_LOGS) {
                        ++compositorFrameTimelineDiagnosticLogs;
                        Log.w(TAG, "Compositor frame-timeline miss" +
                                " generator=" + generatorId +
                                " sample=" +
                                compositorFrameTimelineDiagnosticLogs +
                                " callbackNs=" + frameTimeNanos +
                                " nowNs=" + deadlineNowNs +
                                " targetNs=" +
                                deadline.contentPresentationTimeNs() +
                                " targetFromCallbackNs=" +
                                (deadline.contentPresentationTimeNs() -
                                        frameTimeNanos) +
                                " targetFromNowNs=" +
                                (deadline.contentPresentationTimeNs() -
                                        deadlineNowNs) +
                                " nativeCallbackSequence=" +
                                compositorFrameTimelineNativeCallbackSequence +
                                " nativeFrameTimeNs=" +
                                compositorFrameTimelineNativeFrameTimeNs +
                                " supplied=" +
                                compositorFrameTimelineSuppliedCount +
                                " copied=" + probe.suppliedCount() +
                                " live=" + probe.liveCount() +
                                " nearestVsyncId=" + probe.vsyncId() +
                                " nearestExpectedNs=" +
                                probe.expectedPresentationTimeNs() +
                                " nearestDeadlineNs=" + probe.deadlineNs() +
                                " nearestErrorNs=" +
                                probe.signedTargetErrorNs());
                        // These are predictions and previously observed values,
                        // not a repaired target or a new cadence-proof baseline.
                        Log.w(TAG, "Compositor clock snapshot" +
                                " generator=" + generatorId +
                                " sample=" + compositorFrameTimelineDiagnosticLogs +
                                " epoch=" + schedulerPresentationEpoch() +
                                " anchorNs=" + externalPhysicalClock.anchorNs() +
                                " lastActualNs=" + externalPhysicalClock.lastActualNs() +
                                " periodNs=" + externalPhysicalClock.planningPeriodNs() +
                                " nominalNs=" + externalPhysicalClock.nominalPeriodNs() +
                                " epochScans=" + externalPhysicalClock.observedScans() +
                                " frequencyScans=" + externalPhysicalClock.frequencyObservedScans() +
                                " frequencyBreaks=" + externalPhysicalClock.frequencyDiscontinuities() +
                                " lastPlannedNs=" + externalLastPlannedPhysicalNs +
                                " predictionPeriodNs=" + compositorPredictionLattice.periodNs() +
                                " predictionOrdinal=" + compositorPredictionLattice.headOrdinal() +
                                " realRows=" + presentationClockDiagnostics.size() +
                                " count=" + compositorFrameTimelineCount +
                                " ids=" + java.util.Arrays.toString(compositorFrameTimelineVsyncIds) +
                                " expected=" + java.util.Arrays.toString(compositorExpectedPresentationTimesNs) +
                                " deadlines=" + java.util.Arrays.toString(compositorFrameTimelineDeadlinesNs));
                        for (int diagnosticRow = 0;
                                diagnosticRow < presentationClockDiagnostics.size(); ++diagnosticRow)
                            Log.w(TAG, "Compositor clock observation" +
                                    " generator=" + generatorId +
                                    " sample=" + compositorFrameTimelineDiagnosticLogs +
                                    " row=" + diagnosticRow + " " +
                                    presentationClockDiagnostics.describe(diagnosticRow));
                    }
                    // Do not consume the controller's divisor-lattice slot.
                    // A desired-present timestamp without the matching API-33
                    // frame-timeline token is exactly the best-effort path that
                    // produced r79's isolated one-scan SurfaceFlinger miss.
                    return;
                }
                ++compositorFrameTimelineSelected;
                compositorFrameTimelineErrorMaxNs = Math.max(
                        compositorFrameTimelineErrorMaxNs,
                        Math.abs(compositorTimeline.signedTargetErrorNs()));
            }
            int presentation = frameRate.selectBufferedPresentation(
                    frameTimeNanos, deadline.contentPresentationTimeNs(),
                    activeLeftSequence, activeLeftTimestampNs,
                    activeLeftUniqueSequence, activeLeftSubmission,
                    activeLeftCandidateLoss,
                    activeRightSequence, activeRightTimestampNs,
                    activeRightUniqueSequence, activeRightSubmission,
                    activeRightCandidateLoss,
                    activePairReady && motionEstimateReady);
            if (schedulerPresentationEpoch() != presentationEpochBeforeSelection)
                logBufferedEpochBoundary("selection",
                        presentationEpochBeforeSelection);
            if (schedulerPresentationEpoch() !=
                    presentationEpochBeforeSelection) {
                // Selection can fail closed and publish a fresh epoch before it
                // has a present to commit. Atomically discard the renderer's
                // matching old pair here; otherwise that pair can remain held
                // forever while the controller correctly refuses to re-prime it.
                synchronizeBufferedPresentationEpoch();
                presentation = AdaptiveFrameRateController.PRESENT_NONE;
            }
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
                FrameGenerationPreparationRequest externalPreparation =
                        buildExternalGeneratedPreparation(
                                presentation, deadline);
                long bufferedPresentsBefore =
                        frameRate.bufferedPresentationCount();
                try {
                    presentBuffered(deadline, compositorTimeline,
                            presentation,
                            frameRate.bufferedSelectedPhase());
                    // Queue the visible REAL first. Private inference is then
                    // ordered behind its WSI submission and cannot consume the
                    // endpoint's physical deadline. A dropped/failed visible
                    // request must not authorize speculative private work.
                    if (externalPreparation != null &&
                            frameRate.bufferedPresentationCount() ==
                                    bufferedPresentsBefore + 1L)
                        submitExternalGeneratedPreparation(
                                externalPreparation);
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
            failRuntimePresentation(externalTransport != null
                    ? "External presentation session failed closed"
                    : "Display-vsync presentation failed", failure);
        }
    }

    /** Renderer-owner only; consume and present failures share the same terminal state. */
    private void failRuntimePresentation(String diagnostic, RuntimeException failure) {
        if (closed.get() || externalPresentationFailed) return;
        // An endpoint export can fail before the transport sets its own fatal
        // state. End classification/submission here regardless of which stage
        // failed. Already-posted vsync callbacks observe this latch and stop.
        // Keep onFrameAvailable's producer drain until the host pauses/stops;
        // closing or rebinding from this thread would violate owner lifetime.
        externalPresentationFailed = true;
        Log.e(TAG, diagnostic, failure);
        try {
            runtimeFailure.report(
                    "The game display stopped. Return to EmuFusion and reopen the game.", failure);
        } catch (RuntimeException callbackFailure) {
            Log.e(TAG, "Runtime display error listener failed", callbackFailure);
        }
    }

    private void consumeExternalEndpointDiscontinuities() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null) return;
        long skipped = transport.consumeEndpointDiscontinuities();
        if (skipped <= 0L) return;
        endpointCandidateUnavailable += skipped;
        long previousEpoch = schedulerPresentationEpoch();
        frameRate.resetPresentation();
        resetEndpointTimelineForSchedulerEpoch();
        refreshProofEvidencePresentationEpoch();
        resetHealthWindowAfterStreamChange();
        Log.w(TAG, "External endpoint carrier discontinuity" +
                " generator=" + generatorId +
                " skipped=" + skipped +
                " previousEpoch=" + previousEpoch +
                " epoch=" + schedulerPresentationEpoch());
    }

    private void consumeExternalPresentationDiscontinuities() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null) return;
        long interruptions = transport.consumePresentationDiscontinuities();
        if (interruptions <= 0L) return;

        // Physical output capacity disappeared long enough that the current
        // cadence/proof epoch cannot be certified. Keep polling the same WSI
        // transport so exact Direct output can recover, but generation is
        // permanently quarantined for this process. No missed slot is counted,
        // retried, or carried across the new scheduler epoch.
        long previousEpoch = schedulerPresentationEpoch();
        markExternalTimingRejected();
        externalRatePathActive = false;
        externalRatePathPriming = false;
        externalRatePathOutputPriming = false;
        externalAppOwnedActivationFirstSwapPending = false;
        externalDirectOutputPhaseAnchorNs = 0L;
        transport.setGeneratedRatePathActive(false);
        long epochBeforeDisable = schedulerPresentationEpoch();
        frameRate.setGenerationAvailable(false);
        // setGenerationAvailable(false) publishes its own epoch only when it
        // actually changes state. Direct startup can encounter the same WSI
        // interruption while generation is already false, so publish exactly
        // one explicit epoch in that case—never two boundaries for one event.
        if (schedulerPresentationEpoch() == epochBeforeDisable)
            frameRate.resetPresentation();
        resetEndpointTimelineForSchedulerEpoch();
        refreshProofEvidencePresentationEpoch();
        resetHealthWindowAfterStreamChange();
        Log.e(TAG, "External presentation transport interrupted" +
                " generator=" + generatorId +
                " interruptions=" + interruptions +
                " previousEpoch=" + previousEpoch +
                " epoch=" + schedulerPresentationEpoch() +
                " generatedQuarantined=1");
    }

    @Override public void close() {
        closeAfterStartupFailure(null);
    }

    private void closeAfterStartupFailure(Throwable originalFailure) {
        if (closed.compareAndSet(false, true)) {
            runtimeFailure.close();
            Surface registered = inputSurface;
            FrameGenerationRendererRegistry.unregister(registered, this);
            // Serialized behind initialize(): a timed-out native open cannot
            // still own output when retirement is acknowledged. Cancellation
            // prevents it from starting the EGL/render path when it returns.
            if (!handler.post(() -> {
                Throwable cleanupFailure = null;
                try { releaseGl(); }
                catch (Throwable failure) { cleanupFailure = failure; }
                finally {
                    surfaceRetirement.complete(cleanupFailure);
                    thread.quitSafely();
                }
            })) surfaceRetirement.complete(new IllegalStateException(
                    "Renderer owner rejected display retirement"));
        }
        long timeoutMs = externalTransportFactory == null ?
                STOP_TIMEOUT_MS : EXTERNAL_STOP_TIMEOUT_MS;
        surfaceRetirement.await(timeoutMs, originalFailure);
    }

    private void initialize() {
        try {
            throwIfStartupCancelled();
            if (externalTransportFactory != null) {
                externalTransport = externalTransportFactory.open(
                        outputSurface, handler, inputWidth, inputHeight);
                throwIfStartupCancelled();
                if (externalTransport == null ||
                        externalTransport.endpointWidth() < 1 ||
                        externalTransport.endpointHeight() < 1 ||
                        !externalTransport.supportsEndpointOnlyPresentation())
                    throw new IllegalStateException(
                            "external transport lacks mandatory Direct passthrough");
                // A fixed-midpoint backend can only fill x2 targets; plan
                // 20->40 / 30->60 / 60->120 for it instead of the built-in
                // x3 tiers (which its supportsRatePath would refuse forever,
                // leaving the session Direct: lsfg4, 2026-09-03).
                frameRate.setMaxGenerationFactor(externalTransport.maxGenerationFactor());
                registerExternalPreparationCapacityListener();
                Log.i(TAG, "External transport generation ceiling generator=" + generatorId +
                        " backend=" + externalTransport.backendLabel() +
                        " maxGenerationFactor=" + externalTransport.maxGenerationFactor());
            }
            initializeEgl();
            throwIfStartupCancelled();
            physicalPresentationTracker = appOwnsVisiblePresentation() ?
                    PhysicalPresentationTracker.create() : null;
            if (physicalPresentationTracker == null &&
                    appOwnsVisiblePresentation()) {
                physicalPresentationUnavailableLogged = true;
                Log.w(TAG, "Physical scanout timestamps unavailable" +
                        " generator=" + generatorId +
                        " extension=EGL_ANDROID_get_frame_timestamps");
            } else {
                Log.i(TAG, "Physical scanout timestamp tracker active" +
                        " generator=" + generatorId +
                        " timestamp=EGL_DISPLAY_PRESENT_TIME_ANDROID");
            }
            initializeGl();
            throwIfStartupCancelled();
            if (externalTransport != null) {
                initializeExternalSignatureClassifier();
                // External backend certification is per exact rate path.
                // Start endpoint-only so an unsupported/preflight rate stays
                // visible Direct instead of claiming generated output.
                frameRate.setExactDoubleEndpointLatticeRequired(true);
                frameRate.setGenerationAvailable(false);
            }
            // NOTE (2026-08-17 audit): a previous session disabled the
            // uniqueness readback for EVERY Adreno GPU here because of one
            // glReadPixels SIGSEGV. That made every producer arrival count
            // as a unique frame — a duplicate-submitting 30 fps source
            // (ARMSX2/KH physically does this) would measure 60 and violate
            // the unique-endpoint contract. The crash mitigation is the
            // glFinish barrier plus the error-triggered degrade in
            // latestImageIsUnique below, never a blanket disable.
            inputTexture = new SurfaceTexture(externalTexture);
            inputTexture.setDefaultBufferSize(inputWidth, inputHeight);
            inputTexture.setOnFrameAvailableListener(this, handler);
            inputSurface = new Surface(inputTexture);
            throwIfStartupCancelled();
            requestOutputFrameRate("initialize");
            choreographer = Choreographer.getInstance();
            healthWindowStartNanos = System.nanoTime();
            updateSchedulerHealthBaseline();
            postNextFrameCallback();
            Log.i(TAG, "Frame generator attached generator=" + generatorId +
                    " role=" + displayRole + " displayId=" + displayId +
                    " proofContract=" + activeProofContract() +
                    " proofSchemaVersion=" + activeProofSchemaVersion() +
                    " output=" + outputWidth + "x" +
                    outputHeight + " input=" + inputWidth + "x" + inputHeight +
                    " requestedGles=" + requestedEglContextMajor +
                    " actualGles=" + actualEglContextMajor + "." +
                    actualEglContextMinor +
                    " externalTransport=" +
                            (externalTransport == null ? 0 : 1) +
                    " displayHz=" + refreshHz +
                    " qualificationProof=" + qualificationProofEnabled);
        } catch (Throwable failure) {
            startupFailure = failure;
            Log.e(TAG, "Frame generator initialization failed", failure);
            // Constructor cancellation queues the single release on this same
            // owner, preserving both the startup error and cleanup evidence.
        } finally {
            started.countDown();
        }
    }

    private void throwIfStartupCancelled() {
        if (closed.get()) throw new IllegalStateException(
                "Frame generator startup was cancelled");
    }

    /** True when this EGL context owns the only visible output Surface. */
    private boolean appOwnsVisiblePresentation() {
        return externalTransport == null ||
                externalTransport.usesAppOwnedPresentation();
    }

    /**
     * External-owned presentation only needs the endpoint window current: all
     * analysis and history copies render to explicit FBOs. Keep that binding for
     * the handler lifetime instead of switching to a 1x1 pbuffer after every
     * export. App-owned presentation still needs its separate visible surface.
     * The surface objects remain distinct and retain their original owners.
     */
    private EGLSurface workingEglSurface() {
        return appOwnsVisiblePresentation() ? eglSurface : eglEndpointSurface;
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
        boolean appOwnedPresentation = appOwnsVisiblePresentation();
        eglDisplay = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        if (eglDisplay == EGL14.EGL_NO_DISPLAY) fail("eglGetDisplay");
        int[] version = new int[2];
        if (!EGL14.eglInitialize(eglDisplay, version, 0, version, 1)) fail("eglInitialize");
        int[] attributes = {
                EGL14.EGL_RENDERABLE_TYPE, requestedEglContextMajor >= 3 ?
                        EGL_OPENGL_ES3_BIT_KHR : EGL_OPENGL_ES2_BIT,
                EGL14.EGL_SURFACE_TYPE, EGL14.EGL_WINDOW_BIT |
                        (externalTransport != null && !appOwnedPresentation ?
                                EGL14.EGL_PBUFFER_BIT : 0),
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
        String contextExtensions = EGL14.eglQueryString(eglDisplay, EGL14.EGL_EXTENSIONS);
        boolean prioritizeExternalPresentation = externalTransport != null &&
                appOwnedPresentation && contextExtensions != null &&
                (" " + contextExtensions + " ").contains(" EGL_IMG_context_priority ");
        if (prioritizeExternalPresentation) {
            // Driver hint only. Never require privileges or change device policy.
            contextAttributes = new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,
                    requestedEglContextMajor, 0x3100 /* PRIORITY_LEVEL_IMG */,
                    0x3101 /* HIGH_IMG */, EGL14.EGL_NONE};
        }
        eglContext = EGL14.eglCreateContext(eglDisplay, configs[0], EGL14.EGL_NO_CONTEXT,
                contextAttributes, 0);
        if (eglContext == EGL14.EGL_NO_CONTEXT && prioritizeExternalPresentation) {
            int priorityError = EGL14.eglGetError();
            Log.w(TAG, "External presentation priority hint refused error=" + priorityError);
            eglContext = EGL14.eglCreateContext(eglDisplay, configs[0], EGL14.EGL_NO_CONTEXT,
                    new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,
                            requestedEglContextMajor, EGL14.EGL_NONE}, 0);
        }
        if (eglContext == EGL14.EGL_NO_CONTEXT) fail("eglCreateContext");
        if (prioritizeExternalPresentation) {
            int[] grantedPriority = new int[1];
            boolean queried = EGL14.eglQueryContext(eglDisplay, eglContext,
                    0x3100 /* PRIORITY_LEVEL_IMG */, grantedPriority, 0);
            if (!queried) EGL14.eglGetError();
            Log.i(TAG, "External presentation GPU priority requested=high queried=" +
                    queried + " granted=" + (queried ? grantedPriority[0] : 0));
        }
        int[] surfaceAttributes = {EGL14.EGL_NONE};
        if (appOwnedPresentation) {
            eglSurface = EGL14.eglCreateWindowSurface(eglDisplay, configs[0],
                    outputSurface, surfaceAttributes, 0);
            if (eglSurface == EGL14.EGL_NO_SURFACE)
                fail("eglCreateWindowSurface");
        } else {
            int[] pbufferAttributes = {
                    EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE};
            eglSurface = EGL14.eglCreatePbufferSurface(
                    eglDisplay, configs[0], pbufferAttributes, 0);
            if (eglSurface == EGL14.EGL_NO_SURFACE)
                fail("eglCreatePbufferSurface");
        }
        // Every external transport still consumes exact classified endpoints
        // through its ImageReader Surface. App-owned presentation changes only
        // who owns the visible output Surface; it does not remove this second
        // producer surface. Creating it only in the legacy pbuffer branch made
        // app-owned RIFE call eglMakeCurrent(EGL_NO_SURFACE) at cold startup.
        if (externalTransport != null) {
            endpointEglConfig = configs[0];
            int[] minimumSwapInterval = new int[1];
            int[] maximumSwapInterval = new int[1];
            boolean intervalRangeKnown = EGL14.eglGetConfigAttrib(eglDisplay,
                    endpointEglConfig, EGL14.EGL_MIN_SWAP_INTERVAL, minimumSwapInterval, 0) &&
                    EGL14.eglGetConfigAttrib(eglDisplay, endpointEglConfig,
                            EGL14.EGL_MAX_SWAP_INTERVAL, maximumSwapInterval, 0);
            Log.i(TAG, "External endpoint swap policy requested=" +
                    externalTransportFactory.endpointSwapInterval() +
                    " rangeKnown=" + intervalRangeKnown +
                    " minimum=" + minimumSwapInterval[0] +
                    " maximum=" + maximumSwapInterval[0]);
            eglEndpointSurface = EGL14.eglCreateWindowSurface(
                    eglDisplay, configs[0], externalTransport.endpointSurface(),
                    surfaceAttributes, 0);
            if (eglEndpointSurface == EGL14.EGL_NO_SURFACE)
                fail("eglCreateWindowSurface(endpoint)");
        }
        EGLSurface workingSurface = workingEglSurface();
        if (!EGL14.eglMakeCurrent(eglDisplay, workingSurface, workingSurface, eglContext))
            fail("eglMakeCurrent");
        if (externalTransport != null) {
            if (appOwnedPresentation &&
                    !EGL14.eglMakeCurrent(eglDisplay, eglEndpointSurface,
                    eglEndpointSurface, eglContext))
                fail("eglMakeCurrent(endpoint)");
            if (!EGL14.eglSwapInterval(eglDisplay, externalTransportFactory.endpointSwapInterval()))
                fail("eglSwapInterval(endpoint)");
            if (appOwnedPresentation &&
                    !EGL14.eglMakeCurrent(eglDisplay, eglSurface, eglSurface,
                    eglContext))
                fail("eglMakeCurrent(output)");
        }
        // The Built-in compositor is already paced by Choreographer.
        // A second implicit EGL-vsync wait makes endpoint swap plus the
        // emulator's own GL context serialize on Adreno: the physical r1 run
        // measured 9.4-ms swap p95 and received only ~76 of 120 callbacks/s
        // even though the isolated motion pair was 4.2 ms. Interval zero does
        // not tear an Android SurfaceFlinger layer; it removes only the
        // producer-side duplicate wait while the buffer queue and compositor
        // remain vsync-owned. Apply the same single pacing authority to normal
        // Built-in output, not only the reduced-analysis qualification path.
        // Actual desired-to-present checks still reject missed/early slots.
        if ((requiresNonblockingBuiltinSwap(externalTransport != null) ||
                denseV28ReducedAnalysisRequested ||
                (externalTransport != null && appOwnedPresentation)) &&
                !EGL14.eglSwapInterval(eglDisplay, 0))
            throw new IllegalStateException(
                    "app compositor requires nonblocking EGL swap");
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
        externalGeneratedTextureCopyProgram = createProgram(
                VERTEX_SHADER, EXTERNAL_GENERATED_TEXTURE_COPY_SHADER);
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
        if (externalTransport != null &&
                externalTransport.usesAppOwnedPresentation()) {
            GLES20.glGenTextures(1, id, 0);
            externalGeneratedTexture = id[0];
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,
                    externalGeneratedTexture);
            textureParameters(GLES20.GL_TEXTURE_2D);
        }
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
        if (nativeSourceImageObserver != null)
            nativeSourceImageObserver.resetImages();
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
        if (closed.get() || externalPresentationFailed) return;
        if (submittedFrameCount == 0 && externalTransportFactory != null &&
                externalTransportFactory.nativeSoftwareGeometry() &&
                externalTransport != null &&
                (externalTransport.endpointWidth() != width ||
                        externalTransport.endpointHeight() != height))
            reopenUnusedSoftwareTransport(width, height);
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
        // A software upload has no consumed native buffer timestamp. Never
        // join it to the previous hardware image or a callback-time substitute.
        if (nativeSourceImageObserver != null)
            nativeSourceImageObserver.observeLatest(0L);
        presentationAspect = aspect;
        ++submittedFrameCount;
        ++diagSoftwareSubmits;
        // The launch curtain lifts on the first submitted frame.  Only the
        // SurfaceTexture path notified it, so every software-fed stream
        // (melonDS: hwSubmits=0, swSubmits=60) ran behind a black curtain
        // for the whole session (run nds-b51, 2026-09-02).
        notifyFirstSubmittedFrame();
        clearNativeClassifiedObservation();
        boolean classifiedUnique;
        if (frameRate.usesAuthoritativeSourceRate()) {
            classifiedFrameReady = true;
            classifiedUniqueTexture = latestTexture;
            classifiedUniqueTimestampNs = producerTimestampNs;
            classifiedUniqueSubmission = submittedFrameCount;
            classifyLatestNativeObservation();
            classifiedUnique = true;
        } else if (densePyramidEnabled &&
                (denseV28ReducedAnalysisRequested || externalSignatureTimer != null)) {
            // Explicit GPU-query qualification retains its GPU classifier.
            // Normal Built-in software frames already own CPU pixels; do not
            // upload then synchronously read them back merely for a signature.
            // CPU verdicts must never be counted as GPU-query proof.
            classifiedUnique = latestImageIsUnique(producerTimestampNs);
        } else {
            // Both Direct and ordinary Built-in use the same CPU signature
            // on the exact submitted image. This changes no solver resolution,
            // endpoint timestamp, interpolation ratio or presentation deadline.
            classifiedPixelVerdictKnown = sourceSignatureReady;
            classifiedUnique = softwareImageIsUnique(colors, width, height);
            classifiedFrameReady = true;
            classifiedUniqueTexture = latestTexture;
            classifiedUniqueTimestampNs = producerTimestampNs;
            classifiedUniqueSubmission = submittedFrameCount;
            classifyLatestNativeObservation();
        }
        finishNativeClassifiedObservation(classifiedUnique);
        consumeClassifiedFrame(classifiedUnique);
    }

    /**
     * Admits the exact classified image into both source-rate evidence and the
     * presentation FIFO.
     *
     * <p>Adaptive systems must not use a second callback-clock sampler to
     * acquire a source rate. Distinct images alone establish that authority.
     * After the clock is independently proven, however, a classified callback
     * whose immutable timestamp occupies its exact next source slot is a real
     * endpoint even when its pixels repeat. Retaining that callback's exact
     * full-resolution candidate is not a fake duplicate: it preserves a frame
     * the emulator actually delivered and prevents a held image from tearing
     * a safe source timeline apart. Fractional host callbacks, late callbacks,
     * and any unproven clock remain excluded.</p>
     */
    private void consumeClassifiedFrame(boolean unique) {
        try {
            if (!classifiedFrameReady) return;
            if (classifiedUniqueTexture == 0 || classifiedUniqueTimestampNs <= 0L ||
                    classifiedUniqueSubmission <= 0) {
                ++endpointCandidateUnavailable;
                return;
            }
            if (!unique) {
                // A scheduler epoch can discard the only retained image while
                // this panel stays static (e.g. the native DS top title screen).
                // Re-seed Direct presentation from this actual submitted image,
                // without counting a new unique frame or qualifying its clock.
                if (lastPresentationEndpointTimestampNs == 0L &&
                        !frameRate.hasSustainableGenerationRate()) {
                    acceptPresentationEndpoint(classifiedUniqueTexture,
                            classifiedUniqueTimestampNs, classifiedUniqueSubmission);
                    return;
                }
                if (!frameRate.hasSustainableGenerationRate() ||
                        !AdaptiveFrameRateController.duplicateOccupiesNextSourceSlot(
                                lastPresentationEndpointTimestampNs,
                                classifiedUniqueTimestampNs,
                                frameRate.presentationSourceHz(),
                                lastPresentationEndpointSubmission,
                                classifiedUniqueSubmission)) return;
                acceptPresentationEndpoint(classifiedUniqueTexture,
                        classifiedUniqueTimestampNs, classifiedUniqueSubmission);
                return;
            }
            if (!observeUniqueFrame(classifiedUniqueTimestampNs,
                    classifiedUniqueSubmission)) return;
            acceptPresentationEndpoint(classifiedUniqueTexture,
                    classifiedUniqueTimestampNs, classifiedUniqueSubmission);
        } finally {
            // Rejected/held/not-ready candidates cannot annotate a later image.
            releaseNativeEndpointProvenance(NATIVE_ADMISSION_SLOT);
        }
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
        clearNativeClassifiedObservation();
        classifiedFrameReady = false;
        classifiedUniqueTexture = 0;
        classifiedUniqueTimestampNs = 0L;
        classifiedUniqueSubmission = 0;
        if (!signatureReadbackSafe) {
            classifiedFrameReady = true;
            classifiedUniqueTexture = latestTexture;
            classifiedUniqueTimestampNs = currentTimestampNs;
            classifiedUniqueSubmission = submittedFrameCount;
            classifyLatestNativeObservation();
            return true;
        }
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
        DenseGpuTimer signatureTimer = externalSignatureTimer != null ?
                externalSignatureTimer :
                (densePyramidEnabled && denseV28ReducedAnalysisRequested ?
                        denseGpuTimer : null);
        if (signatureTimer != null) {
            try {
                int capability = signatureCapability(signatureTimer);
                if (!signatureTimer.signatureSupported() ||
                        capability != DENSE_SIGNATURE_CAP_READY)
                    throw new IllegalStateException("asynchronous signature unavailable" +
                            " capability=0x" + Integer.toHexString(capability));
                if (!denseSignatureBaselineReady) {
                    copyCurrentSignatureToPrevious();
                    denseSignatureBaselineReady = true;
                    classifiedFrameReady = true;
                    classifiedUniqueTexture = latestTexture;
                    classifiedUniqueTimestampNs = currentTimestampNs;
                    classifiedUniqueSubmission = submittedFrameCount;
                    classifyLatestNativeObservation();
                    GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
                    GLES20.glViewport(0, 0, outputWidth, outputHeight);
                    return true;
                }
                long[] row = signatureTimer.pollSignature(denseSignatureSequence);
                if (row.length != 0 && row.length != DenseGpuTimer.SIGNATURE_RESULT_FIELDS)
                    throw new IllegalStateException("malformed asynchronous signature row");
                boolean unique = false;
                int completedCandidate = -1;
                if (row.length != 0) {
                    if (row[0] != DenseGpuTimer.STATUS_OK || row[7] != 1L ||
                            row[6] < 0L || row[6] > 4L ||
                            (row[2] != 0L && row[2] != 1L))
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
                    completedCandidate = findSignatureCandidate(readySequence);
                    if (completedCandidate < 0)
                        throw new IllegalStateException(
                                "signature result has no retained endpoint sequence=" +
                                        readySequence);
                    // Preserve the exact classified candidate for both UNIQUE
                    // and DUPLICATE results.  The latter is a timing endpoint,
                    // not source-rate evidence.  Keep its texture slot reserved
                    // until the current query has retained a different slot;
                    // otherwise the current image overwrites the result before
                    // consumeClassifiedFrame can copy it into the FIFO.
                    classifiedFrameReady = true;
                    classifiedUniqueTexture =
                            signatureCandidateTextures[completedCandidate];
                    classifiedUniqueTimestampNs =
                            signatureCandidateTimestampNs[completedCandidate];
                    classifiedUniqueSubmission =
                            signatureCandidateSubmission[completedCandidate];
                    classifiedPixelVerdictKnown = true;
                    if (nativeSourceImageObserver != null)
                        nativeSourceImageObserver.classifyCandidate(completedCandidate);
                }
                long sequence = ++denseSignatureSequence;
                retainSignatureCandidate(sequence, currentTimestampNs,
                        completedCandidate);
                GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer);
                GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                        GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D,
                        signatureQueryTexture, 0);
                if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                        GLES20.GL_FRAMEBUFFER_COMPLETE)
                    throw new IllegalStateException("signature query framebuffer incomplete");
                GLES20.glViewport(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT);
                drawSignatureDifferenceQuery(signatureTimer, sequence);
                copyCurrentSignatureToPrevious();
                if (completedCandidate >= 0) {
                    signatureCandidateSequence[completedCandidate] = 0L;
                    signatureCandidateTimestampNs[completedCandidate] = 0L;
                    signatureCandidateSubmission[completedCandidate] = 0;
                    if (nativeSourceImageObserver != null)
                        nativeSourceImageObserver.releaseCandidate(completedCandidate);
                }
                GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
                GLES20.glViewport(0, 0, outputWidth, outputHeight);
                checkGl("asynchronous source signature");
                if (denseWallStart != 0L)
                    recordDenseWall(DENSE_WALL_SIGNATURE,
                            System.nanoTime() - denseWallStart);
                // A delayed unique result was committed above while its exact
                // retained texture was still intact. The current image is only
                // a query candidate and must never be accepted by that old bit.
                return unique;
            } catch (RuntimeException failure) {
                ++denseSignatureUnavailable;
                if (externalSignatureTimer != null)
                    throw new IllegalStateException(
                            "external asynchronous signature failed closed", failure);
                rejectDense("async-signature-failure", failure);
                clearSignatureCandidates();
                clearNativeClassifiedObservation();
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
        int beforeRead = GLES20.glGetError();
        if (beforeRead != GLES20.GL_NO_ERROR) {
            signatureReadbackSafe = false;
            Log.e(TAG, "Uniqueness readback degraded before read; error=0x" +
                    Integer.toHexString(beforeRead) + " generator=" +
                    generatorId);
            classifiedFrameReady = true;
            classifiedUniqueTexture = latestTexture;
            classifiedUniqueTimestampNs = currentTimestampNs;
            classifiedUniqueSubmission = submittedFrameCount;
            classifyLatestNativeObservation();
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
            return true;
        }
        GLES20.glFinish();
        GLES20.glReadPixels(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT,
                GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, signaturePixels);
        if (GLES20.glGetError() != GLES20.GL_NO_ERROR) {
            signatureReadbackSafe = false;
            Log.e(TAG, "Uniqueness readback degraded after a GL error;" +
                    " every arrival now counts as unique for this session" +
                    " generator=" + generatorId);
            classifiedFrameReady = true;
            classifiedUniqueTexture = latestTexture;
            classifiedUniqueTimestampNs = currentTimestampNs;
            classifiedUniqueSubmission = submittedFrameCount;
            classifyLatestNativeObservation();
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
            return true;
        }
        for (int index = 0; index < currentSourceSignature.length; ++index)
            currentSourceSignature[index] = signaturePixels.get(index);
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        GLES20.glViewport(0, 0, outputWidth, outputHeight);
        checkGl("source signature");
        if (denseWallStart != 0L)
            recordDenseWall(DENSE_WALL_SIGNATURE,
                    System.nanoTime() - denseWallStart);
        // Bootstrap admits a first endpoint without a prior pixel comparison.
        classifiedPixelVerdictKnown = sourceSignatureReady;
        boolean unique = sourceSignatureIsUnique();
        classifiedFrameReady = true;
        classifiedUniqueTexture = latestTexture;
        classifiedUniqueTimestampNs = currentTimestampNs;
        classifiedUniqueSubmission = submittedFrameCount;
        classifyLatestNativeObservation();
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

    private void drawSignatureDifferenceQuery(
            DenseGpuTimer signatureTimer, long sequence) {
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
            if (signatureTimer == null || !signatureTimer.beginSignature(sequence))
                throw new IllegalStateException("asynchronous signature begin failed" +
                        " sequence=" + sequence +
                        " pending=" + (signatureTimer == null ? -1 :
                                signatureTimer.pendingSignatures()) +
                        " capability=" + signatureCapability(signatureTimer));
            begun = true;
            GLES20.glUseProgram(signatureCompareProgram);
            bindQuad(signatureCompareProgram);
            bindTexture(signatureCompareProgram, "uCurrent", signatureTexture, 0);
            bindTexture(signatureCompareProgram, "uPrevious", signaturePreviousTexture, 1);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        } finally {
            try {
                if (begun) signatureTimer.endSignature();
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
        int byteSum = 0;
        for (int offset = 0; offset < currentSourceSignature.length; offset += 4) {
            int difference = 0;
            for (int channel = 0; channel < 3; ++channel) {
                difference += Math.abs((currentSourceSignature[offset + channel] & 0xff) -
                        (lastSourceSignature[offset + channel] & 0xff));
                byteSum += currentSourceSignature[offset + channel] & 0xff;
            }
            totalDifference += difference;
            if (difference >= 3) ++changedPixels;
        }
        diagLastSignatureByteSum = byteSum;
        diagLastChangedPixels = changedPixels;
        boolean unique = !sourceSignatureReady || changedPixels >= 1 ||
                totalDifference >= 16;
        if (unique) {
            ++diagUniqueVerdicts;
            System.arraycopy(currentSourceSignature, 0, lastSourceSignature, 0,
                    currentSourceSignature.length);
            sourceSignatureReady = true;
        } else {
            ++diagDuplicateVerdicts;
        }
        return unique;
    }

    // Acquisition-starvation diagnostics only (runs nds1-4, 2026-08-17):
    // which ingest path feeds this generator and what the signature sees.
    private long diagSoftwareSubmits;
    private long diagHardwareSubmits;
    private long diagUniqueVerdicts;
    private long diagDuplicateVerdicts;
    private int diagLastSignatureByteSum;
    private int diagLastChangedPixels;

    private int findSignatureCandidate(long sequence) {
        for (int slot = 0; slot < SIGNATURE_CANDIDATE_SLOTS; ++slot)
            if (signatureCandidateSequence[slot] == sequence) return slot;
        return -1;
    }

    private void retainSignatureCandidate(long sequence, long timestampNs,
                                          int reservedSlot) {
        int slot = -1;
        for (int index = 0; index < SIGNATURE_CANDIDATE_SLOTS; ++index) {
            if (index != reservedSlot && signatureCandidateSequence[index] == 0L) {
                slot = index;
                break;
            }
        }
        if (slot < 0) {
            ++endpointCandidateUnavailable;
            throw new IllegalStateException("signature endpoint texture ring full");
        }
        copyTexture(latestTexture, signatureCandidateTextures[slot]);
        if (nativeSourceImageObserver != null)
            nativeSourceImageObserver.retainCandidate(slot);
        signatureCandidateSequence[slot] = sequence;
        signatureCandidateTimestampNs[slot] = timestampNs;
        signatureCandidateSubmission[slot] = submittedFrameCount;
    }

    private void clearSignatureCandidates() {
        if (nativeSourceImageObserver != null)
            nativeSourceImageObserver.clearCandidates();
        java.util.Arrays.fill(signatureCandidateSequence, 0L);
        java.util.Arrays.fill(signatureCandidateTimestampNs, 0L);
        java.util.Arrays.fill(signatureCandidateSubmission, 0);
    }

    /** Records one pixel-distinct image with its immutable producer timestamp. */
    private boolean observeUniqueFrame(long timestampNs, int submissionOrdinal) {
        if (timestampNs <= 0L || timestampNs <= lastProducerTimestampNs) {
            // Never manufacture monotonicity by replacing a broken producer
            // timestamp with System.nanoTime.  The affected interval has no
            // trustworthy phase: discard it, publish a presentation boundary,
            // and require two later timestamped endpoints to re-prime.
            ++endpointCandidateUnavailable;
            ++endpointTimestampCorrections;
            // Signature query IDs and retained candidate textures are one
            // ownership epoch.  A timestamp discontinuity invalidates both;
            // cancel the native ring before resetEndpointFifo clears the Java
            // candidate slots, otherwise a delayed result can later bind to
            // no texture or to a reused sequence number.
            if (densePyramidEnabled || denseGpuTimer != null) {
                densePyramidEnabled = false;
                teardownDenseEpoch("producer-timestamp-discontinuity");
            }
            resetEndpointFifo();
            frameRate.resetPresentation();
            resetHealthWindowAfterStreamChange();
            lastProducerTimestampNs = Math.max(0L, timestampNs);
            return false;
        }
        lastProducerTimestampNs = timestampNs;
        ++uniqueFrameCount;
        lastUniqueSubmissionCount = Math.max(lastUniqueSubmissionCount,
                submissionOrdinal);
        if (!frameRate.onProducerFrame(timestampNs, submissionOrdinal)) {
            // The producer PTS proved that SurfaceTexture coalesced one or
            // more core buffers. Preserve the measured unique-image clock,
            // but make this image the first endpoint of a fresh temporal
            // chain. The completed candidate and every still-pending signature
            // query remain exactly sequence-bound to their retained textures;
            // do NOT clear either side or tear down/re-arm qualification. Only
            // the interpolation interval that crosses the missing carrier
            // buffer is unsafe. The controller already published a new
            // presentation epoch, so synchronizing it here drops the visible
            // endpoint chain, excludes any old-epoch proof atlas on completion,
            // and lets this exact image become the first endpoint afterward.
            ++endpointCandidateUnavailable;
            if (!synchronizeBufferedPresentationEpoch()) {
                // onProducerFrame() is the authority for this boundary and
                // must always advance the scheduler epoch on a transport loss.
                throw new IllegalStateException(
                        "producer transport loss did not publish an epoch");
            }
            lastProducerTimestampNs = timestampNs;
            lastUniqueSubmissionCount = submissionOrdinal;
            Log.w(TAG, "Producer buffer discontinuity generator=" +
                    generatorId + " timestampNs=" + timestampNs +
                    " submission=" + submissionOrdinal +
                    " timelineHz=" +
                    frameRate.producerTimelineHzForDiagnostics() +
                    " discontinuities=" +
                    frameRate.producerTimelineDiscontinuityCountForDiagnostics());
        }
        return true;
    }

    /** Enqueues one selected temporal endpoint for visible presentation. */
    private void acceptPresentationEndpoint(int sourceTexture, long timestampNs,
                                            int submissionOrdinal) {
        if (sourceTexture == 0) return;
        if (timestampNs <= 0L ||
                timestampNs <= lastPresentationEndpointTimestampNs) {
            ++endpointCandidateUnavailable;
            ++endpointTimestampCorrections;
            frameRate.resetPresentation();
            resetEndpointTimelineForSchedulerEpoch();
            resetHealthWindowAfterStreamChange();
            return;
        }
        if (lastPresentationEndpointTimestampNs > 0L &&
                !AdaptiveFrameRateController.endpointSpanContinuous(
                        lastPresentationEndpointTimestampNs, timestampNs,
                        frameRate.presentationSourceHz())) {
            // A loading screen, static hold, save-state transition, or lost
            // carrier interval ends the old presentation timeline before the
            // resumed endpoint can be submitted.  Detecting this only while
            // preparing its later successor is too late for Direct: the lone
            // resumed REAL may already own an old-epoch physical request, and
            // its eventual actual-present row then appears off the old scan
            // lattice (physical TWINE r147: an 8.9-second loading gap).
            //
            // Already-submitted transport rows remain reportable by contract.
            // The first request containing this exact endpoint instead owns a
            // new scheduler epoch, which makes pollPhysicalPresentations()
            // re-anchor the physical clock on that exact REAL.  No synthetic
            // image is allowed across the gap and no timestamp is fabricated.
            long previousTimestampNs = lastPresentationEndpointTimestampNs;
            long previousEpoch = schedulerPresentationEpoch();
            frameRate.resetPresentation();
            observedBufferedPresentationEpoch = schedulerPresentationEpoch();
            resetEndpointTimelineForSchedulerEpoch();
            refreshProofEvidencePresentationEpoch();
            resetHealthWindowAfterStreamChange();
            Log.w(TAG, "Presentation endpoint timestamp discontinuity" +
                    " generator=" + generatorId +
                    " previousTimestampNs=" + previousTimestampNs +
                    " timestampNs=" + timestampNs +
                    " spanNs=" + (timestampNs - previousTimestampNs) +
                    " previousEpoch=" + previousEpoch +
                    " epoch=" + schedulerPresentationEpoch());
        }
        if (externalTransport != null &&
                endpointFifoCount >= ENDPOINT_FIFO_CAPACITY) {
            ++endpointFifoCoalesced;
            frameRate.resetPresentation();
            resetEndpointTimelineForSchedulerEpoch();
            resetHealthWindowAfterStreamChange();
        }
        if (!admitExternalEndpointCandidate()) return;
        // The overflow reset above deliberately clears the old timeline. This
        // exact candidate is the first endpoint of the new one, so publish its
        // immutable timestamp/submission only after that reset; otherwise the
        // next real held callback cannot prove its immediate source slot.
        lastPresentationEndpointTimestampNs = timestampNs;
        lastPresentationEndpointSubmission = submissionOrdinal;
        long acceptedSequence = endpointSequence + 1L;
        if (externalTransport != null)
            publishExternalEndpoint(sourceTexture, acceptedSequence, timestampNs);
        endpointSequence = acceptedSequence;
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
            java.util.Arrays.fill(endpointFifoUniqueSequence, 0L);
            java.util.Arrays.fill(endpointFifoSubmission, 0);
            java.util.Arrays.fill(endpointFifoCandidateLoss, 0L);
            for (int retired = 0; retired < ENDPOINT_FIFO_CAPACITY; ++retired)
                releaseNativeEndpointProvenance(retired);
            slot = 0;
        }
        copyTexture(sourceTexture, endpointFifoTextures[slot]);
        copyNativeEndpointProvenance(NATIVE_ADMISSION_SLOT, slot);
        endpointFifoSequence[slot] = endpointSequence;
        endpointFifoTimestampNs[slot] = timestampNs;
        // This provenance is the accepted source-slot ordinal, not the count
        // of pixel-distinct images. A positively classified repeated callback
        // can occupy one exact proven source slot; using its accepted ordinal
        // keeps that real endpoint adjacent without relabeling it as unique.
        endpointFifoUniqueSequence[slot] = endpointSequence;
        endpointFifoSubmission[slot] = submissionOrdinal;
        endpointFifoCandidateLoss[slot] = endpointCandidateUnavailable;
    }

    /** Reject capacity pressure before identity publication or any EGL export. */
    private boolean admitExternalEndpointCandidate() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null || transport.canAcceptEndpoint()) {
            externalEndpointAdmissionBlocked = false;
            return true;
        }
        ++endpointCandidateUnavailable;
        ++externalEndpointAdmissionRejected;
        // One interruption ends the chain once, not on every callback while old
        // work retires. Submitted physical rows keep their original identities;
        // no future midpoint may bridge the unexported source image.
        if (!externalEndpointAdmissionBlocked) {
            frameRate.resetPresentation();
            observedBufferedPresentationEpoch = schedulerPresentationEpoch();
            resetEndpointTimelineForSchedulerEpoch();
            refreshProofEvidencePresentationEpoch();
            resetHealthWindowAfterStreamChange();
            externalEndpointAdmissionBlocked = true;
            Log.w(TAG, "External endpoint admission pressure generator=" + generatorId +
                    " rejectedTotal=" + externalEndpointAdmissionRejected +
                    " candidateUnavailableTotal=" + endpointCandidateUnavailable);
        }
        return false;
    }

    /**
     * Copies one already-classified immutable endpoint into the external
     * ImageReader without ever giving the backend source-rate authority.
     */
    private void publishExternalEndpoint(
            int sourceTexture, long sequence, long timestampNs) {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null) return;
        if (eglEndpointSurface == EGL14.EGL_NO_SURFACE || sourceTexture == 0 ||
                sequence <= 0L || timestampNs <= 0L)
            throw new IllegalStateException("external endpoint export is invalid");
        transport.expectEndpoint(sequence, timestampNs, nativeEndpointProvenance,
                NATIVE_ADMISSION_SLOT, nativeEndpointProvenance == null ? 0L :
                        nativeEndpointProvenance.lease(NATIVE_ADMISSION_SLOT));
        boolean switchSurface = transport.usesAppOwnedPresentation();
        boolean submitted = false;
        try {
            if (switchSurface &&
                    !EGL14.eglMakeCurrent(eglDisplay, eglEndpointSurface,
                    eglEndpointSurface, eglContext))
                fail("eglMakeCurrent(endpoint-export)");
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            int width = transport.endpointWidth();
            int height = transport.endpointHeight();
            GLES20.glViewport(0, 0, width, height);
            GLES20.glClearColor(0f, 0f, 0f, 1f);
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
            // Native-sized inference consumes raw pixel geometry, not display
            // aspect. NES/SNES pixels are not square: applying their display
            // aspect here crops source columns and applies correction twice.
            boolean nativePixels = externalTransportFactory != null &&
                    externalTransportFactory.nativeSoftwareGeometry() &&
                    width == historyWidth && height == historyHeight;
            if (!nativePixels) {
                float aspect = presentationAspect > 0f ? presentationAspect :
                        (float) historyWidth / Math.max(1, historyHeight);
                int contentWidth = Math.max(1, Math.round(height * aspect));
                GLES20.glViewport((width - contentWidth) / 2, 0,
                        contentWidth, height);
            }
            drawTexture2d(sourceTexture);
            if (Build.VERSION.SDK_INT < 18 ||
                    !EGLExt.eglPresentationTimeANDROID(
                            eglDisplay, eglEndpointSurface, timestampNs))
                fail("eglPresentationTimeANDROID(endpoint)");
            checkGl("render external endpoint");
            if (!EGL14.eglSwapBuffers(eglDisplay, eglEndpointSurface))
                fail("eglSwapBuffers(endpoint)");
            submitted = true;
        } finally {
            boolean restored = !switchSurface || EGL14.eglMakeCurrent(
                    eglDisplay, eglSurface, eglSurface, eglContext);
            if (!submitted) transport.cancelExpectedEndpoint(sequence);
            if (!restored) fail("eglMakeCurrent(offscreen-restore)");
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
        }
    }

    private void resetEndpointFifo() {
        clearNativeEndpointTimeline(true);
        if (externalSignatureTimer != null) {
            externalSignatureTimer.discardPending();
            denseSignatureSequence = 0L;
            denseSignatureBaselineReady = false;
        }
        if (externalTransport != null) externalTransport.resetEndpointTimeline();
        endpointFifoHead = 0;
        endpointFifoCount = 0;
        activeLeftSequence = 0L;
        activeRightSequence = 0L;
        activeLeftTimestampNs = 0L;
        activeRightTimestampNs = 0L;
        activeLeftUniqueSequence = 0L;
        activeRightUniqueSequence = 0L;
        activeLeftSubmission = 0;
        activeRightSubmission = 0;
        activeLeftCandidateLoss = 0L;
        activeRightCandidateLoss = 0L;
        activePairReady = false;
        activePairSyntheticCommitted = false;
        // A temporal guide belongs to one uninterrupted adjacent endpoint
        // chain. Source-mode changes, resizes and explicit FIFO resets must
        // never carry a validated vector field into a newly primed chain.
        denseTemporalGuideReady = false;
        lastPromotedEndpointSequence = 0L;
        bufferedPairCreatedCount = 0L;
        bufferedSyntheticSelectedCount = 0L;
        bufferedSyntheticQuotaSkippedCount = 0L;
        bufferedSyntheticNotReadyCount = 0L;
        bufferedPresentationCallbackCount = 0L;
        bufferedLastSelectedSyntheticPair = 0L;
        lastPresentationEndpointTimestampNs = 0L;
        lastPresentationEndpointSubmission = 0;
        lastProducerTimestampNs = 0L;
        java.util.Arrays.fill(endpointFifoSequence, 0L);
        java.util.Arrays.fill(endpointFifoTimestampNs, 0L);
        java.util.Arrays.fill(endpointFifoUniqueSequence, 0L);
        java.util.Arrays.fill(endpointFifoSubmission, 0);
        java.util.Arrays.fill(endpointFifoCandidateLoss, 0L);
        clearSignatureCandidates();
    }

    private int endpointFifoSlot(int offset) {
        return (endpointFifoHead + offset) % ENDPOINT_FIFO_CAPACITY;
    }

    private void discardEndpointFifoHead() {
        if (endpointFifoCount <= 0) return;
        int slot = endpointFifoHead;
        releaseNativeEndpointProvenance(slot);
        endpointFifoSequence[slot] = 0L;
        endpointFifoTimestampNs[slot] = 0L;
        endpointFifoUniqueSequence[slot] = 0L;
        endpointFifoSubmission[slot] = 0;
        endpointFifoCandidateLoss[slot] = 0L;
        endpointFifoHead = (endpointFifoHead + 1) % ENDPOINT_FIFO_CAPACITY;
        --endpointFifoCount;
    }

    private void consumeEndpointIntoHistory(int historyIndex, boolean left) {
        if (endpointFifoCount <= 0)
            throw new IllegalStateException("endpoint FIFO underflow");
        int slot = endpointFifoHead;
        long sequence = endpointFifoSequence[slot];
        long timestampNs = endpointFifoTimestampNs[slot];
        long uniqueSequence = endpointFifoUniqueSequence[slot];
        int submissionOrdinal = endpointFifoSubmission[slot];
        long candidateLoss = endpointFifoCandidateLoss[slot];
        if (sequence <= 0L)
            throw new IllegalStateException("endpoint FIFO sequence missing");
        if (timestampNs <= 0L)
            throw new IllegalStateException("endpoint FIFO timestamp missing");
        copyTexture(endpointFifoTextures[slot], historyTextures[historyIndex]);
        copyNativeEndpointProvenance(slot, NATIVE_HISTORY_BASE + historyIndex);
        releaseNativeEndpointProvenance(slot);
        endpointFifoSequence[slot] = 0L;
        endpointFifoTimestampNs[slot] = 0L;
        endpointFifoUniqueSequence[slot] = 0L;
        endpointFifoSubmission[slot] = 0;
        endpointFifoCandidateLoss[slot] = 0L;
        endpointFifoHead = (endpointFifoHead + 1) % ENDPOINT_FIFO_CAPACITY;
        --endpointFifoCount;
        if (left) {
            activeLeftSequence = sequence;
            activeLeftTimestampNs = timestampNs;
            activeLeftUniqueSequence = uniqueSequence;
            activeLeftSubmission = submissionOrdinal;
            activeLeftCandidateLoss = candidateLoss;
        } else {
            activeRightSequence = sequence;
            activeRightTimestampNs = timestampNs;
            activeRightUniqueSequence = uniqueSequence;
            activeRightSubmission = submissionOrdinal;
            activeRightCandidateLoss = candidateLoss;
        }
    }

    /**
     * Materializes the exact adjacent endpoint pair consumed by the buffered
     * scheduler. Producer callbacks only append retained textures; they never
     * overwrite either history texture while it owns a visible timeline.
     */
    private void prepareBufferedPairIfPossible() {
        if (externalTransport != null && !activePairReady &&
                activeLeftSequence > 0L &&
                activeRightSequence == activeLeftSequence + 1L &&
                externalTransport.hasAdjacentPair(
                        activeLeftSequence, activeRightSequence)) {
            // A look-ahead preparation attempt can legitimately lose a race
            // with the asynchronous import of its newest endpoint.  Do not
            // make that one NOT_READY result permanent for this pair.  Retry
            // the exact immutable midpoint while the pair is active, before
            // selection can consume its midpoint as an unavailable slot and
            // advance to the following REAL endpoint.  An already-prepared
            // successor matches this same identity and is merely polled.
            if (externalRatePathActive) {
                long midpointNs =
                        AdaptiveFrameRateController.exactMidpointTimestampNs(
                                activeLeftTimestampNs,
                                activeRightTimestampNs);
                if (midpointNs > activeLeftTimestampNs &&
                        midpointNs < activeRightTimestampNs) {
                    FrameGenerationPreparationRequest preparation =
                            FrameGenerationPreparationRequest.between(
                                    generatorId,
                                    schedulerPresentationEpoch(),
                                    activeLeftSequence,
                                    activeLeftTimestampNs,
                                    activeRightSequence,
                                    activeRightTimestampNs,
                                    midpointNs,
                                    externalTransport.endpointWidth(),
                                    externalTransport.endpointHeight(),
                                    FrameGenerationPresentationRequest.
                                            FORMAT_RGBA8_UNORM);
                    submitExternalGeneratedPreparation(preparation);
                    externalTransport.preparationReadiness(preparation);
                }
            }
            ExternalFrameGenerationTransport.GenerationReadiness readiness =
                    externalTransport.generationReadiness(
                            activeLeftSequence, activeRightSequence);
            motionEstimateReady = readiness ==
                    ExternalFrameGenerationTransport.GenerationReadiness.READY;
            activePairReady = motionEstimateReady;
            if (readiness ==
                    ExternalFrameGenerationTransport.GenerationReadiness.UNSAFE &&
                    externalLastUnsafePairRightSequence != activeRightSequence) {
                externalLastUnsafePairRightSequence = activeRightSequence;
                ++externalUnsafePairCount;
                Log.w(TAG, "External interpolation pair rejected" +
                        " generator=" + generatorId +
                        " left=" + activeLeftSequence +
                        " right=" + activeRightSequence);
            }
        }
        if (activeLeftSequence == 0L) {
            // A prior hold or source discontinuity may leave one endpoint that
            // cannot form an interpolation pair with its successor.  Preserve
            // that independently classified REAL instead of dropping it: only
            // the interval is unsafe.  The controller will present the lone
            // endpoint directly and interpolation can re-prime from a later
            // exact adjacent pair.
            while (endpointFifoCount >= 2) {
                int leftSlot = endpointFifoSlot(0);
                int rightSlot = endpointFifoSlot(1);
                long left = endpointFifoSequence[leftSlot];
                long right = endpointFifoSequence[rightSlot];
                if (left > 0L && right == left + 1L &&
                        AdaptiveFrameRateController.endpointSpanContinuous(
                                endpointFifoTimestampNs[leftSlot],
                                endpointFifoTimestampNs[rightSlot],
                                frameRate.presentationSourceHz(),
                                endpointFifoUniqueSequence[leftSlot],
                                endpointFifoUniqueSequence[rightSlot],
                                endpointFifoSubmission[leftSlot],
                                endpointFifoSubmission[rightSlot],
                                endpointFifoCandidateLoss[leftSlot],
                                endpointFifoCandidateLoss[rightSlot],
                                slotLatticeProducer)) break;
                previousIndex = 0;
                currentIndex = 1;
                consumeEndpointIntoHistory(previousIndex, true);
                return;
            }
            boolean generatedTimeline = frameRate.generatesIntermediateFrames();
            if (!generatedTimeline && endpointFifoCount == 1) {
                // Direct presentation does not need a future interpolation
                // interval. Show this exact REAL promptly while its successor
                // is still being classified.
                previousIndex = 0;
                currentIndex = 1;
                consumeEndpointIntoHistory(previousIndex, true);
                return;
            }
            // (2026-09-02, wiiu-b42) Slot-lattice producers deliver through
            // their own swapchain with a few milliseconds of arrival jitter;
            // priming one source period deeper keeps the successor endpoint
            // already retained when a pair rotates, so an interior 120-Hz
            // slot is never left empty (4-8 missed scans per second were the
            // remaining physical-cadence rejections).  Costs one source
            // period of latency on those systems only.
            int requiredPrimeDepth = generatedTimeline ?
                    (externalTransport != null ?
                            Math.min(ENDPOINT_FIFO_CAPACITY,
                                    Math.max(ENDPOINT_FIFO_EXTERNAL_PRIME_DEPTH,
                                            externalLookaheadPairCount() + 2)) :
                            (slotLatticeProducer ?
                                    Math.min(ENDPOINT_FIFO_CAPACITY,
                                            ENDPOINT_FIFO_PRIME_DEPTH + 3) :
                                    ENDPOINT_FIFO_PRIME_DEPTH)) : 2;
            if (endpointFifoCount < requiredPrimeDepth) return;
            previousIndex = 0;
            currentIndex = 1;
            copyBufferedEndpoints(true);
            return;
        }
        if (activeRightSequence == 0L && endpointFifoCount > 0) {
            long next = endpointFifoSequence[endpointFifoHead];
            long nextTimestampNs = endpointFifoTimestampNs[endpointFifoHead];
            long nextUniqueSequence =
                    endpointFifoUniqueSequence[endpointFifoHead];
            int nextSubmission = endpointFifoSubmission[endpointFifoHead];
            long nextCandidateLoss = endpointFifoCandidateLoss[endpointFifoHead];
            boolean sequenceContinuous = next == activeLeftSequence + 1L;
            boolean timestampContinuous =
                    AdaptiveFrameRateController.endpointSpanContinuous(
                            activeLeftTimestampNs, nextTimestampNs,
                            frameRate.presentationSourceHz(),
                            activeLeftUniqueSequence, nextUniqueSequence,
                            activeLeftSubmission, nextSubmission,
                            activeLeftCandidateLoss, nextCandidateLoss,
                            slotLatticeProducer);
            if (!sequenceContinuous || !timestampContinuous) {
                Log.w(TAG, "Buffered endpoint discontinuity" +
                        " generator=" + generatorId +
                        " source=" + frameRate.lockedSourceFps() +
                        " left=" + activeLeftSequence +
                        " next=" + next +
                        " leftTs=" + activeLeftTimestampNs +
                        " nextTs=" + nextTimestampNs +
                        " spanNs=" + (nextTimestampNs - activeLeftTimestampNs) +
                        " leftUnique=" + activeLeftUniqueSequence +
                        " nextUnique=" + nextUniqueSequence +
                        " leftSubmission=" + activeLeftSubmission +
                        " nextSubmission=" + nextSubmission +
                        " leftCandidateLoss=" + activeLeftCandidateLoss +
                        " nextCandidateLoss=" + nextCandidateLoss +
                        " sequenceContinuous=" + sequenceContinuous +
                        " timestampContinuous=" + timestampContinuous +
                        " fifoCount=" + endpointFifoCount +
                        " coalesced=" + endpointFifoCoalesced);
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

    /**
     * Drops only the visible endpoint timeline when the controller publishes a
     * new presentation epoch. Signature-query ownership and lifetime telemetry
     * remain intact; newly arriving producer frames are selected afresh under
     * the new source tier and can form the next exact adjacent pair.
     */
    private void resetEndpointTimelineForSchedulerEpoch() {
        clearNativeEndpointTimeline(true);
        if (externalTransport != null) externalTransport.resetEndpointTimeline();
        if (activePairReady && !activePairSyntheticCommitted)
            ++bufferedSyntheticQuotaSkippedCount;
        endpointFifoHead = 0;
        endpointFifoCount = 0;
        java.util.Arrays.fill(endpointFifoSequence, 0L);
        java.util.Arrays.fill(endpointFifoTimestampNs, 0L);
        java.util.Arrays.fill(endpointFifoUniqueSequence, 0L);
        java.util.Arrays.fill(endpointFifoSubmission, 0);
        java.util.Arrays.fill(endpointFifoCandidateLoss, 0L);
        activeLeftSequence = 0L;
        activeRightSequence = 0L;
        activeLeftTimestampNs = 0L;
        activeRightTimestampNs = 0L;
        activeLeftUniqueSequence = 0L;
        activeRightUniqueSequence = 0L;
        activeLeftSubmission = 0;
        activeRightSubmission = 0;
        activeLeftCandidateLoss = 0L;
        activeRightCandidateLoss = 0L;
        activePairReady = false;
        activePairSyntheticCommitted = false;
        motionEstimateReady = false;
        denseTemporalGuideReady = false;
        lastPresentationEndpointTimestampNs = 0L;
        lastPresentationEndpointSubmission = 0;
    }

    private boolean synchronizeBufferedPresentationEpoch() {
        long epoch = schedulerPresentationEpoch();
        if (epoch == observedBufferedPresentationEpoch) return false;
        observedBufferedPresentationEpoch = epoch;
        resetEndpointTimelineForSchedulerEpoch();
        refreshProofEvidencePresentationEpoch();
        resetHealthWindowAfterStreamChange();
        return true;
    }

    private void copyBufferedEndpoints(boolean initialPair) {
        motionEstimateReady = false;
        activePairReady = false;
        // Endpoint continuity is needed even when no exact doubled cadence
        // exists. Do not time/solve a pair that cannot fund a midpoint.
        boolean builtinCadenceReady = frameRate.generatesIntermediateFrames();
        boolean dense = densePyramidEnabled && builtinCadenceReady;
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
                            frameRate.presentationSourceHz(),
                            activeLeftUniqueSequence, activeRightUniqueSequence,
                            activeLeftSubmission, activeRightSubmission,
                            activeLeftCandidateLoss, activeRightCandidateLoss,
                            slotLatticeProducer))
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
            if (externalTransport != null) {
                ExternalFrameGenerationTransport.GenerationReadiness readiness =
                        externalTransport.generationReadiness(
                                activeLeftSequence, activeRightSequence);
                motionEstimateReady = readiness ==
                        ExternalFrameGenerationTransport.GenerationReadiness.READY;
                if (readiness ==
                        ExternalFrameGenerationTransport.GenerationReadiness.UNSAFE &&
                        externalLastUnsafePairRightSequence != activeRightSequence) {
                    externalLastUnsafePairRightSequence = activeRightSequence;
                    ++externalUnsafePairCount;
                }
            } else if (dense) {
                try {
                    estimateDenseMotion();
                } catch (RuntimeException denseFailure) {
                    rejectDense("buffered-pair-estimator-failure", denseFailure);
                    motionEstimateReady = false;
                }
            } else if (!builtinCadenceReady) {
                // A qualified dense failure has no authorized legacy visual
                // fallback. Keep the exact endpoints available for direct
                // presentation without computing or exposing old motion.
                motionEstimateReady = false;
                denseTemporalGuideReady = false;
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
        // Copy/proof may start as soon as this exact pair exists, including a
        // successor promoted during the preceding successful presentation.
        prepareExternalRealPairIfPossible();
    }

    private void prepareExternalRealPairIfPossible() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null || !transport.supportsPrivateRealPairPreparation() ||
                externalPresentationFailed || activeLeftSequence <= 0L ||
                activeLeftSequence == Long.MAX_VALUE ||
                activeRightSequence != activeLeftSequence + 1L ||
                activeLeftTimestampNs <= 0L || activeRightTimestampNs <= activeLeftTimestampNs)
            return;
        long epoch = schedulerPresentationEpoch();
        if (epoch <= 0L) return;
        FrameGenerationPreparationRequest cached = externalRealPairPreparation;
        if (cached == null || cached.sessionEpoch() != generatorId ||
                cached.presentationEpoch() != epoch ||
                cached.leftSequence() != activeLeftSequence ||
                cached.leftTimestampNs() != activeLeftTimestampNs ||
                cached.rightSequence() != activeRightSequence ||
                cached.rightTimestampNs() != activeRightTimestampNs ||
                cached.outputWidth() != transport.endpointWidth() ||
                cached.outputHeight() != transport.endpointHeight()) {
            cached = FrameGenerationPreparationRequest.between(
                    generatorId, epoch, activeLeftSequence, activeLeftTimestampNs,
                    activeRightSequence, activeRightTimestampNs, activeLeftTimestampNs,
                    transport.endpointWidth(), transport.endpointHeight(),
                    FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
            externalRealPairPreparation = cached;
        }
        // Phase zero is a canonical pair announcement, NOT a predicted next
        // output. The immutable request may later select either exact endpoint.
        // Announcement before imports finish lets their completion retry this
        // same identity without adding another vsync of preparation latency.
        transport.prepareRealPair(cached);
    }

    private void invalidateBufferedPairForReprime() {
        invalidateBufferedPairForReprime(true);
    }

    private void invalidateBufferedPairForReprime(boolean resetController) {
        deferredExternalPreparation = null;
        pendingAppOwnedRequest = null;
        pendingAppOwnedPreparation = null;
        clearNativeEndpointTimeline(externalTransport != null);
        if (externalTransport != null) {
            externalTransport.resetEndpointTimeline();
            endpointFifoHead = 0;
            endpointFifoCount = 0;
            java.util.Arrays.fill(endpointFifoSequence, 0L);
            java.util.Arrays.fill(endpointFifoTimestampNs, 0L);
            java.util.Arrays.fill(endpointFifoUniqueSequence, 0L);
            java.util.Arrays.fill(endpointFifoSubmission, 0);
            java.util.Arrays.fill(endpointFifoCandidateLoss, 0L);
        }
        if (activePairReady && !activePairSyntheticCommitted)
            ++bufferedSyntheticQuotaSkippedCount;
        activeLeftSequence = 0L;
        activeRightSequence = 0L;
        activeLeftTimestampNs = 0L;
        activeRightTimestampNs = 0L;
        activeLeftUniqueSequence = 0L;
        activeRightUniqueSequence = 0L;
        activeLeftSubmission = 0;
        activeRightSubmission = 0;
        activeLeftCandidateLoss = 0L;
        activeRightCandidateLoss = 0L;
        activePairReady = false;
        activePairSyntheticCommitted = false;
        motionEstimateReady = false;
        denseTemporalGuideReady = false;
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
        // Right keeps its texture-indexed metadata; retire only the old left.
        releaseNativeEndpointProvenance(NATIVE_HISTORY_BASE + currentIndex);
        activeLeftSequence = activeRightSequence;
        activeLeftTimestampNs = activeRightTimestampNs;
        activeLeftUniqueSequence = activeRightUniqueSequence;
        activeLeftSubmission = activeRightSubmission;
        activeLeftCandidateLoss = activeRightCandidateLoss;
        activeRightSequence = 0L;
        activeRightTimestampNs = 0L;
        activeRightUniqueSequence = 0L;
        activeRightSubmission = 0;
        activeRightCandidateLoss = 0L;
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
            denseGlobalCostProgram = createProgram(
                    VERTEX_SHADER, DENSE_GLOBAL_COST_SHADER);
            denseGlobalReduceProgram = createProgram(
                    VERTEX_SHADER, DENSE_GLOBAL_REDUCE_SHADER);
            denseGlobalCutProgram = createProgram(
                    VERTEX_SHADER, DENSE_GLOBAL_CUT_SHADER);
            denseSolveProgram = createProgram(VERTEX_SHADER, DENSE_SOLVE_SHADER);
            denseCycleProgram = createProgram(VERTEX_SHADER, DENSE_CYCLE_SHADER);
            denseFillProgram = createProgram(VERTEX_SHADER, DENSE_FILL_SHADER);
            denseQ8ProbeProgram = createProgram(VERTEX_SHADER, DENSE_Q8_PROBE_SHADER);
            proofAtlasHeaderProgram = createProgram(VERTEX_SHADER,
                    PROOF_ATLAS_HEADER_SHADER);
            denseDiagnosticPackProgram = createProgram(VERTEX_SHADER,
                    DENSE_DIAGNOSTIC_PACK_SHADER);
            for (int direction = 0; direction < 2; ++direction) {
                for (int level = 0; level < DENSE_LEVELS; ++level)
                    GLES20.glGenTextures(2, denseFlowTextures[direction][level], 0);
                GLES20.glGenTextures(2, densePyramidTextures[direction], 0);
                GLES20.glGenTextures(2, denseBoxTextures[direction], 0);
            }
            GLES20.glGenTextures(2, denseGlobalCoarseCostTextures, 0);
            GLES20.glGenTextures(2, denseGlobalFineCostTextures, 0);
            GLES20.glGenTextures(2, denseGlobalCoarseSeedTextures, 0);
            GLES20.glGenTextures(2, denseGlobalSeedTextures, 0);
            GLES20.glGenTextures(2, denseGlobalCutTextures, 0);
            GLES20.glGenTextures(2, denseValidatedTextures, 0);
            GLES20.glGenTextures(2, denseFillTextures, 0);
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
                    " passesPerPromotion=" + densePassesPerPromotion() +
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
            denseBoxWidths[0] = Math.max(1, historyWidth / 4);
            denseBoxHeights[0] = Math.max(1, historyHeight / 4);
            denseBoxWidths[1] = Math.max(1, denseBoxWidths[0] / 4);
            denseBoxHeights[1] = Math.max(1, denseBoxHeights[0] / 4);
            allocateDenseTexture(denseBoxTextures[direction][0],
                    denseBoxWidths[0], denseBoxHeights[0], false);
            allocateDenseTexture(denseBoxTextures[direction][1],
                    denseBoxWidths[1], denseBoxHeights[1], false);
            allocateDenseTexture(denseValidatedTextures[direction],
                    denseAnalysisWidth, denseAnalysisHeight, false);
            allocateDenseTexture(denseFillTextures[direction],
                    denseAnalysisWidth, denseAnalysisHeight, false);
            allocateDenseTexture(denseGlobalCoarseCostTextures[direction],
                    9, 9, true);
            allocateDenseTexture(denseGlobalFineCostTextures[direction],
                    5, 5, true);
            allocateDenseTexture(denseGlobalCoarseSeedTextures[direction],
                    1, 1, true);
            allocateDenseTexture(denseGlobalSeedTextures[direction], 1, 1, true);
            allocateDenseTexture(denseGlobalCutTextures[direction], 1, 1, true);
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

    private void initializeExternalSignatureClassifier() {
        if (externalTransport == null) return;
        if (requestedEglContextMajor < 3 || actualEglContextMajor < 3)
            throw new IllegalStateException(
                    "external endpoint classification requires GLES3");
        String extensions = GLES20.glGetString(GLES20.GL_EXTENSIONS);
        int[] range = new int[2];
        int[] precision = new int[1];
        GLES20.glGetShaderPrecisionFormat(GLES20.GL_FRAGMENT_SHADER,
                GLES20.GL_HIGH_FLOAT, range, 0, precision, 0);
        if (extensions == null || !extensions.contains("GL_OES_rgb8_rgba8") ||
                precision[0] < 16)
            throw new IllegalStateException(
                    "external signature requires RGBA8 and fragment highp");
        allocateSignatureQualificationTexture(signatureTexture);
        allocateSignatureQualificationTexture(signaturePreviousTexture);
        allocateSignatureQualificationTexture(signatureQueryTexture);
        externalSignatureTimer = DenseGpuTimer.create();
        if (!externalSignatureTimer.signatureSupported() ||
                signatureCapability(externalSignatureTimer) !=
                        DENSE_SIGNATURE_CAP_READY)
            throw new IllegalStateException(
                    "external asynchronous signature self-test failed");
        denseSignatureBaselineReady = false;
        denseSignatureSequence = 0L;
        clearSignatureCandidates();
    }

    private int signatureCapability(DenseGpuTimer timer) {
        int nativeCapability = timer == null ? 0 : timer.signatureCapability();
        boolean rgba8Ready = timer == externalSignatureTimer || denseResourcesReady;
        return nativeCapability |
                (rgba8Ready ? DENSE_SIGNATURE_CAP_RGBA8 : 0);
    }

    private int denseSignatureCapability() {
        return signatureCapability(denseGpuTimer);
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
        denseTemporalGuideReady = false;
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
                clearTexture(denseFillTextures[direction], denseAnalysisWidth,
                        denseAnalysisHeight, 128f / 255f, 128f / 255f, 0f, 0f);
                clearTexture(denseGlobalCoarseCostTextures[direction], 9, 9,
                        0f, 0f, 0f, 0f);
                clearTexture(denseGlobalFineCostTextures[direction], 5, 5,
                        0f, 0f, 0f, 0f);
                clearTexture(denseGlobalCoarseSeedTextures[direction], 1, 1,
                        0f, 0f, 0f, 0f);
                clearTexture(denseGlobalSeedTextures[direction], 1, 1,
                        0f, 0f, 0f, 0f);
                clearTexture(denseGlobalCutTextures[direction], 1, 1,
                        0f, 0f, 0f, 1f);
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
        // The validated textures still contain the preceding pair until the
        // final validation draws below.  Preserve that ownership explicitly;
        // motionEstimateReady is cleared while copying every new endpoint and
        // therefore cannot represent temporal-guide availability.
        boolean temporalGuide = denseTemporalGuideReady;
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
            if (denseV28ReducedAnalysisRequested) {
                buildDenseGlobalSeed(0, historyTextures[previousIndex],
                        historyTextures[currentIndex]);
                buildDenseGlobalSeed(1, historyTextures[currentIndex],
                        historyTextures[previousIndex]);
            }
            endDenseStage();
            beginDenseStage(DenseGpuTimer.FORWARD_SOLVE);
            solveDenseDirection(0, historyTextures[previousIndex],
                    historyTextures[currentIndex], temporalGuide);
            endDenseStage();
            beginDenseStage(DenseGpuTimer.REVERSE_SOLVE);
            solveDenseDirection(1, historyTextures[currentIndex],
                    historyTextures[previousIndex], temporalGuide);
            endDenseStage();
            beginDenseStage(DenseGpuTimer.VALIDATION);
            // The independently searched fields may still occupy different
            // repeated-texture basins. Give each finalized full-resolution
            // field one reciprocal proposal under ITS OWN image objective
            // before validation. A stricter gain margin prevents a merely
            // tied inverse from manufacturing cycle agreement.
            if (denseV28ReducedAnalysisRequested && denseWorkLevel < 2) {
                refineDenseReciprocalDirection(0, historyTextures[previousIndex],
                        historyTextures[currentIndex]);
                refineDenseReciprocalDirection(1, historyTextures[currentIndex],
                        historyTextures[previousIndex]);
            }
            validateDenseDirection(0, historyTextures[previousIndex],
                    historyTextures[currentIndex]);
            validateDenseDirection(1, historyTextures[currentIndex],
                    historyTextures[previousIndex]);
            fillDenseDirection(0);
            fillDenseDirection(1);
            endDenseStage();
            checkGl("estimate dense bidirectional motion");
            maybeDumpDenseFlow(previousIndex, currentIndex);
            denseTemporalGuideReady = true;
            motionEstimateReady = true;
        } finally {
            if (dither) GLES20.glEnable(GLES20.GL_DITHER);
            if (blend) GLES20.glEnable(GLES20.GL_BLEND);
            if (scissor) GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
        }
        long submitted = System.nanoTime();
        long submitUs = Math.max(0L, (submitted - start) / 1000L);
        ++densePromotions;
        densePasses += densePassesPerPromotion();
        denseCpuSubmitLastUs = submitUs;
        denseCpuSubmitTotalUs += submitUs;
        denseCpuSubmitMaxUs = Math.max(denseCpuSubmitMaxUs, submitUs);
        pollDenseTimers();
    }

    private void beginDenseStage(int stage) {
        if (physicalPresentationTracker != null)
            physicalPresentationTracker.setReadyTimingEnabled(true);
        long sequence = stage == DenseGpuTimer.VISIBLE_WARP ?
                denseWarpSequence + 1L : densePromotions + 1L;
        if (stage == DenseGpuTimer.VISIBLE_WARP &&
                !denseGpuPairLedger.expectWarp(sequence, densePromotions)) {
            ++denseTimerUnavailable;
            throw new IllegalStateException("dense GPU warp has no unique pair owner");
        }
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
        if (pendingDenseGpuHeadroomReject != null) {
            rejectDense(pendingDenseGpuHeadroomReject, null);
            return;
        }
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
                // Expired work is missing evidence, not a zero-cost sample.
                // End ownership rather than leaving a hole that later pairs
                // could silently skip while earning healthy credit.
                rejectDense("stale-timer-result", null);
                return;
            }
            long pairSequence = stage == DenseGpuTimer.VISIBLE_WARP ?
                    denseGpuPairLedger.ownerOfWarp(sequence) : sequence;
            boolean recorded = stage == DenseGpuTimer.VISIBLE_WARP ?
                    denseGpuPairLedger.recordWarp(sequence, elapsedUs) :
                    denseGpuPairLedger.recordEstimatorStage(sequence, stage, elapsedUs);
            if (!recorded) {
                ++denseTimerStale;
                rejectDense("invalid-timer-pair-ownership", null);
                return;
            }
            denseStageTotalUs[stage] += elapsedUs;
            denseStageMaxUs[stage] = Math.max(denseStageMaxUs[stage], elapsedUs);
            int sample = (int) (denseStageSamples[stage]++ & 255L);
            denseStageObservedUs[stage][sample] = elapsedUs;
            if (elapsedUs > denseGpuBudgetUs()) {
                failDenseGpuPairOnce(pairSequence, "async-gpu-stage-over-budget");
                if (denseGpuTimer == null) return;
            }
            // Warp query IDs are independent of endpoint IDs; the ledger
            // binds the actual midpoint warp to its immutable endpoint owner.
            if (stage == DenseGpuTimer.VISIBLE_WARP) {
                int warpSlot = (int) (sequence & 127L);
                denseWarpCompletedSequence[warpSlot] = sequence;
                denseWarpMaxCompletedSequence = Math.max(
                        denseWarpMaxCompletedSequence, sequence);
                if (!consumeCompletedDenseGpuPairs()) return;
                continue;
            }
            int pair = (int) (sequence & 127L);
            if (densePairSequence[pair] != 0L && densePairSequence[pair] != sequence) {
                ++denseTimerStale;
                rejectDense("wrapped-incomplete-timer-pair", null);
                return;
            }
            densePairSequence[pair] = sequence;
            if ((densePairMask[pair] & (1 << stage)) != 0 ||
                    densePairTotalUs[pair] > Long.MAX_VALUE - elapsedUs) {
                ++denseTimerStale;
                rejectDense("invalid-timer-result", null);
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
                densePairSequence[pair] = 0L;
                densePairTotalUs[pair] = 0L;
                densePairMask[pair] = 0;
                if (total > denseGpuBudgetUs()) {
                    failDenseGpuPairOnce(sequence, "async-gpu-pair-over-budget");
                    if (denseGpuTimer == null) return;
                }
            }
            if (!consumeCompletedDenseGpuPairs()) return;
        }
        if (denseGpuTimer == null) return;
        int disjointAfter = denseGpuTimer.takeDisjointCount();
        if (disjointAfter > 0) {
            denseTimerDisjoint += disjointAfter;
            rejectDense("gpu-timer-disjoint", null);
        }
    }

    private void failDenseGpuPairOnce(long pairSequence, String reason) {
        int slot = (int) (pairSequence & 127L);
        if (pairSequence > 0L && denseGpuFailedPairSequences[slot] != pairSequence) {
            denseGpuFailedPairSequences[slot] = pairSequence;
            shedDenseWork(reason);
        } else {
            // The same stage spike, pair sum and warp sum are one failed pair,
            // not three independent failures. They still invalidate recovery.
            denseGpuAdaptation.invalidateRecoveryEvidence();
        }
    }

    private boolean consumeCompletedDenseGpuPairs() {
        long pairSequence;
        while ((pairSequence = denseGpuPairLedger.takeCompletedPair()) > 0L) {
            long totalUs = denseGpuPairLedger.completedTotalUs(pairSequence);
            if (totalUs <= 0L) {
                rejectDense("invalid-timer-pair-total", null);
                return false;
            }
            ++denseGpuCompletePairs;
            denseGpuCompleteLastUs = totalUs;
            denseGpuCompleteTotalUs += totalUs;
            denseGpuCompleteMaxUs = Math.max(denseGpuCompleteMaxUs, totalUs);
            if (!denseGpuHeadroom.recordShader(denseGpuHeadroom.evidenceEpoch(),
                    pairSequence, totalUs, denseGpuBudgetUs())) {
                rejectDense("invalid-timer-physical-join", null);
                return false;
            }
            if (totalUs > denseGpuBudgetUs())
                failDenseGpuPairOnce(pairSequence, "combined-pair-warp-over-budget");
            if (denseGpuTimer == null) return false;
        }
        return consumeDensePhysicalGpuHeadroom();
    }

    private long previousDenseJoinEpoch, previousDenseJoinFrameId;
    private long previousDenseJoinTargetNs, previousDenseJoinActualNs;
    private int denseJoinedGapEvidenceCount;
    private final SubmissionTimingHistory denseSubmissionHistory = new SubmissionTimingHistory();

    private boolean consumeDensePhysicalGpuHeadroom() {
        GpuPhysicalHeadroomLedger.Result result;
        while ((result = denseGpuHeadroom.takeCompleted()) != null) {
            if (result.presentationEpoch != schedulerPresentationEpoch()) {
                denseGpuAdaptation.invalidateRecoveryEvidence();
                if (result.generated()) ++denseGpuPhysicalUnknownPairs;
                continue;
            }
            // Join adjacent owned results, not unrelated rolling averages.
            // Target and actual deltas distinguish a planned scan skip from
            // a late physical presentation. Missing IDs remain explicit.
            if (result.actualNs > 0L) {
                if (frameRate.generatesIntermediateFrames() &&
                        frameRate.panelScansPerOutput() == 1 &&
                        previousDenseJoinEpoch == result.presentationEpoch &&
                        previousDenseJoinActualNs > 0L && result.panelPeriodNs > 0L &&
                        result.actualNs - previousDenseJoinActualNs >
                                result.panelPeriodNs + result.panelPeriodNs / 2L &&
                        denseJoinedGapEvidenceCount < 8) {
                    ++denseJoinedGapEvidenceCount;
                    Log.w(TAG, "Built-in joined physical gap generator=" + generatorId +
                            " previousFrameId=" + previousDenseJoinFrameId +
                            " frameId=" + result.frameId +
                            " previousTargetNs=" + previousDenseJoinTargetNs +
                            " targetNs=" + result.desiredNs +
                            " previousActualNs=" + previousDenseJoinActualNs +
                            " actualNs=" + result.actualNs +
                            " periodNs=" + result.panelPeriodNs +
                            " pair=" + result.pairSequence +
                            " outcome=" + result.outcome + " reason=" + result.reason +
                            " submissions=" + denseSubmissionHistory.describe(
                                    result.presentationEpoch, previousDenseJoinFrameId, result.frameId));
                }
                previousDenseJoinEpoch = result.presentationEpoch;
                previousDenseJoinFrameId = result.frameId;
                previousDenseJoinTargetNs = result.desiredNs;
                previousDenseJoinActualNs = result.actualNs;
            }
            boolean verified = result.outcome ==
                    GpuPhysicalHeadroomLedger.Outcome.VERIFIED_HEADROOM;
            if (result.outcome == GpuPhysicalHeadroomLedger.Outcome.DEADLINE_MISS) {
                ++denseGpuPhysicalDeadlineMisses;
                // Bounded failure-only evidence: distinguish a wrong physical
                // slot from late application rendering before blaming shaders.
                if (denseGpuPhysicalDeadlineMisses <= 4L) {
                    Log.w(TAG, "Dense physical deadline evidence generator=" + generatorId +
                            " frameId=" + result.frameId + " pair=" + result.pairSequence +
                            " warp=" + result.warpSequence + " reason=" + result.reason +
                            " desiredNs=" + result.desiredNs + " actualNs=" + result.actualNs +
                            " deadlineNs=" + result.deadlineNs +
                            " renderCompleteNs=" + result.renderCompleteNs +
                            " latchNs=" + result.latchNs +
                            " compositionStartNs=" + result.startNs +
                            " compositorGpuFinishedNs=" + result.gpuFinishedNs +
                            " timestampSupportedMask=" + result.supportedMask +
                            " panelPeriodNs=" + result.panelPeriodNs +
                            " shaderCostUs=" + result.shaderCostUs +
                            " shaderBudgetUs=" + result.shaderBudgetUs);
                }
                if (result.generated())
                    failDenseGpuPairOnce(result.pairSequence, "physical-pair-deadline-miss");
                else
                    shedDenseWork("physical-pair-deadline-miss");
                if (denseGpuTimer == null) return false;
                continue;
            }
            if (!verified) denseGpuAdaptation.invalidateRecoveryEvidence();
            // Endpoints maintain continuity, but do not count as healthy
            // generated pairs or borrow another pair's shader measurement.
            if (!result.generated()) continue;
            if (verified) ++denseGpuPhysicalVerifiedPairs;
            else if (result.outcome == GpuPhysicalHeadroomLedger.Outcome.MARGINAL_HEADROOM)
                ++denseGpuPhysicalMarginalPairs;
            else ++denseGpuPhysicalUnknownPairs;
            denseGpuPhysicalLastAppMarginNs = result.appMarginNs;
            denseGpuPhysicalLastCompositorMarginNs = result.compositorMarginNs;
            int slot = (int) (result.pairSequence & 127L);
            if (denseGpuFailedPairSequences[slot] == result.pairSequence) {
                denseGpuAdaptation.invalidateRecoveryEvidence();
                continue;
            }
            // This is an exact pair + own warp + successful EGL swap + that
            // frame's driver-rendering/compositor completion join. Delayed
            // observation time and rolling cadence averages are never inputs.
            applyDenseGpuDecision(denseGpuAdaptation.onCompletedPair(
                    ++denseGpuCompletionSequence, result.shaderCostUs,
                    result.shaderBudgetUs, verified), result.reason);
            if (denseGpuTimer == null) return false;
        }
        return true;
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
    private static final int DENSE_TRANSIENT_REJECT_REARM_LIMIT = 32;
    private int denseTransientRejections;
    // Cached shader work level; the session-owned policy is the sole writer.
    // Minimum-work overload has a bounded Direct fallback. Quality recovery
    // requires consecutive complete timing AND independent physical headroom.
    private int denseWorkLevel;

    /** One independent failed pair, never a repeated rolling-window maximum. */
    private void shedDenseWork(String reason) {
        ++denseLoadAnomalies;
        applyDenseGpuDecision(denseGpuAdaptation.onFailure(denseGpuFailure(reason)), reason);
    }

    private void applyDenseGpuDecision(GpuWorkAdaptationPolicy.Decision decision, String reason) {
        denseWorkLevel = denseGpuAdaptation.workLevel();
        if (decision != GpuWorkAdaptationPolicy.Decision.UNCHANGED) {
            Log.w(TAG, "Dense GPU adaptation generator=" + generatorId +
                    " decision=" + decision +
                    " reason=" + reason + " workLevel=" + denseWorkLevel +
                    " anomalies=" + denseLoadAnomalies +
                    " failures=" + denseGpuAdaptation.failureCount() +
                    " minimumWorkFailures=" + denseGpuAdaptation.failuresAtMinimum());
        }
        if (decision == GpuWorkAdaptationPolicy.Decision.DISABLE_GENERATION)
            rejectDense("persistent-gpu-overload", null);
    }
    private long denseLoadAnomalies;

    private static GpuWorkAdaptationPolicy.Failure denseGpuFailure(String reason) {
        if (isOverBudgetDenseRejection(reason))
            return GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET;
        if ("gpu-timer-disjoint".equals(reason) ||
                ("native-timer-status-" + DenseGpuTimer.STATUS_DISJOINT).equals(reason))
            return GpuWorkAdaptationPolicy.Failure.TIMER_DISJOINT;
        if ("surface-cadence-below-reported-output".equals(reason) ||
                "physical-pair-deadline-miss".equals(reason))
            return GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS;
        if ("stale-timer-result".equals(reason) ||
                "zero-timer-result".equals(reason) ||
                "wrapped-incomplete-timer-pair".equals(reason))
            return GpuWorkAdaptationPolicy.Failure.TIMER_MISSING;
        if (reason != null && reason.contains("timer"))
            return GpuWorkAdaptationPolicy.Failure.TIMER_INVALID;
        return GpuWorkAdaptationPolicy.Failure.PIPELINE_FAILURE;
    }

    private static boolean isOverBudgetDenseRejection(String reason) {
        return "async-gpu-pair-over-budget".equals(reason) ||
                "async-gpu-stage-over-budget".equals(reason) ||
                "combined-pair-warp-over-budget".equals(reason);
    }

    /** Recoverable epoch failures, still subject to both session limits.
     * Every failure ends the current timing evidence and presents Direct;
     * a later re-arm cannot erase minimum-work overload or restore quality. */
    private static boolean isTransientDenseRejection(String reason) {
        // Guest speed is never reduced to hide GPU overload. Context, GL,
        // malformed/expired results and ownership failures are not re-armed.
        return "gpu-timer-disjoint".equals(reason) ||
                "surface-cadence-below-reported-output".equals(reason) ||
                "wrapped-incomplete-timer-pair".equals(reason) ||
                "duplicate-warp-timer".equals(reason) ||
                "invalid-timer-result".equals(reason) ||
                "async-gpu-pair-over-budget".equals(reason) ||
                "combined-pair-warp-over-budget".equals(reason) ||
                "async-signature-failure".equals(reason) ||
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
        boolean overBudget = isOverBudgetDenseRejection(reason);
        if (!denseGpuAdaptation.generationDisabled())
            denseGpuAdaptation.onFailure(denseGpuFailure(reason));
        else
            denseGpuAdaptation.invalidateRecoveryEvidence();
        denseWorkLevel = denseGpuAdaptation.workLevel();
        boolean recoverable = !denseGpuAdaptation.generationDisabled() &&
                (isTransientDenseRejection(reason) || overBudget) &&
                ++denseTransientRejections <= DENSE_TRANSIENT_REJECT_REARM_LIMIT;
        if (!recoverable) densePyramidUnavailable = true;
        densePerformanceRejected = true;
        // A rejected qualified renderer has no authorized generation path.
        // The legacy v22 estimator remains useful as diagnostic code, but it
        // must never become a silent visual fallback: that exact transition
        // produced doubled/ghosted PS2 imagery while the badge still claimed
        // an interpolated target. Collapse the controller to truthful
        // endpoint-only output.
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
        if (!recoverable) {
            // Endpoint-only output still owns an intermediate renderer. Once
            // generation cannot recover, retire it through the host's normal
            // producer acknowledgement and rebind the exact Direct Surface.
            // Never close/rebind here on the generator's rendering thread.
            failRuntimePresentation("Built-in generation unavailable; requesting Direct recovery",
                    new IllegalStateException("Permanent frame-generation rejection: " + reason,
                            failure));
            return;
        }
        reportedSourceTenths = -1;
        reportedOutputTenths = -1;
        reportedTargetTenths = -1;
        reportedCadenceQualified = false;
        reportedBackendLabel = null;
        reportStats();
    }

    /** Ends one qualification epoch without allowing its queries or vectors
     * to survive a settings toggle. Cleanup is best-effort and non-throwing:
     * endpoint-only presentation is established before timer teardown, and a
     * native close failure cannot strand generated rendering in the default
     * path. A later enable must create a new native timer and sequence epoch. */
    private void teardownDenseEpoch(String reason) {
        motionEstimateReady = false;
        if (physicalPresentationTracker != null)
            physicalPresentationTracker.setReadyTimingEnabled(false);
        resetDenseGpuEvidenceEpoch();
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

    private void resetDenseGpuEvidenceEpoch() {
        denseGpuPairLedger.beginEvidenceEpoch();
        denseGpuAdaptation.beginEvidenceEpoch();
        denseGpuHeadroom.beginEvidenceEpoch(denseGpuAdaptation.evidenceEpochCount());
        denseGpuHeadroomPresentationEpoch = 0L;
        pendingDenseGpuHeadroomReject = null;
        denseGpuCompletionSequence = 0L;
        java.util.Arrays.fill(denseGpuFailedPairSequences, 0L);
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
        // Box-filter ladder (2026-09-03): history -> /4 -> /16 with exact 4x4
        // boxes, then the 64x36 analysis level from the /16 image and the
        // 32x18 level from the 64x36 one with exact 2x2 boxes.  Every pixel
        // of the source contributes to the coarse levels, so a 60-px
        // coarse texel no longer sees an aliased 2x2 sample of its block.
        // Never destroy detail below the requested search resolution and then
        // enlarge it again. Small native surfaces (e.g. DS 256x192) previously
        // passed through 16x12 on the way to a 96x72 search image.
        int filtered = source;
        int filteredWidth = historyWidth;
        int filteredHeight = historyHeight;
        for (int stage = 0; stage < 2; ++stage) {
            if (denseBoxWidths[stage] < denseLevelWidths[1] ||
                    denseBoxHeights[stage] < denseLevelHeights[1]) break;
            drawDensePyramid(filtered, filteredWidth, filteredHeight,
                    denseBoxTextures[endpoint][stage],
                    denseBoxWidths[stage], denseBoxHeights[stage], 1f);
            filtered = denseBoxTextures[endpoint][stage];
            filteredWidth = denseBoxWidths[stage];
            filteredHeight = denseBoxHeights[stage];
        }
        drawDensePyramid(filtered, filteredWidth, filteredHeight,
                densePyramidTextures[endpoint][0], denseLevelWidths[1], denseLevelHeights[1], 0.5f);
        drawDensePyramid(densePyramidTextures[endpoint][0],
                denseLevelWidths[1], denseLevelHeights[1],
                densePyramidTextures[endpoint][1], denseLevelWidths[2], denseLevelHeights[2], 0.5f);
    }

    private void drawDensePyramid(int source, int sourceWidth, int sourceHeight,
                                  int destination, int width, int height, float tapScale) {
        attachDenseTarget(destination, width, height);
        GLES20.glUseProgram(densePyramidProgram);
        bindQuad(densePyramidProgram);
        bindTexture(densePyramidProgram, "uTexture", source, 0);
        uniform2(densePyramidProgram, "uInputTexel",
                1f / Math.max(1, sourceWidth), 1f / Math.max(1, sourceHeight));
        GLES20.glUniform1f(GLES20.glGetUniformLocation(densePyramidProgram, "uTapScale"), tapScale);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private void buildDenseGlobalSeed(int direction, int reference, int target) {
        float limit = activeFlowLimitPixels();
        float coarse = limit / 4f;
        float fine = Math.max(1f, coarse / 4f);
        drawDenseGlobalCosts(reference, target,
                denseGlobalSeedTextures[direction], false,
                denseGlobalCoarseCostTextures[direction], 9, coarse, limit);
        reduceDenseGlobalCosts(denseGlobalCoarseCostTextures[direction],
                denseGlobalCoarseCostTextures[direction],
                denseGlobalSeedTextures[direction], false,
                denseGlobalCoarseSeedTextures[direction], 9, coarse, limit);
        drawDenseGlobalCosts(reference, target,
                denseGlobalCoarseSeedTextures[direction], true,
                denseGlobalFineCostTextures[direction], 5, fine, limit);
        reduceDenseGlobalCosts(denseGlobalFineCostTextures[direction],
                denseGlobalCoarseCostTextures[direction],
                denseGlobalCoarseSeedTextures[direction], true,
                denseGlobalSeedTextures[direction], 5, fine, limit);
        drawDenseGlobalCut(reference, target, denseGlobalSeedTextures[direction],
                denseGlobalCutTextures[direction]);
    }

    private void drawDenseGlobalCut(int reference, int target, int seed,
                                    int destination) {
        attachDenseTarget(destination, 1, 1);
        GLES20.glUseProgram(denseGlobalCutProgram);
        bindQuad(denseGlobalCutProgram);
        bindTexture(denseGlobalCutProgram, "uReference", reference, 0);
        bindTexture(denseGlobalCutProgram, "uTarget", target, 1);
        bindTexture(denseGlobalCutProgram, "uCenterSeed", seed, 2);
        uniform2(denseGlobalCutProgram, "uSourceSize", historyWidth, historyHeight);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private void drawDenseGlobalCosts(int reference, int target, int center,
                                      boolean useCenter, int destination,
                                      int gridSize, float step, float limit) {
        attachDenseTarget(destination, gridSize, gridSize);
        GLES20.glUseProgram(denseGlobalCostProgram);
        bindQuad(denseGlobalCostProgram);
        bindTexture(denseGlobalCostProgram, "uReference", reference, 0);
        bindTexture(denseGlobalCostProgram, "uTarget", target, 1);
        bindTexture(denseGlobalCostProgram, "uCenterSeed", center, 2);
        uniform2(denseGlobalCostProgram, "uSourceSize", historyWidth, historyHeight);
        uniform2(denseGlobalCostProgram, "uGridSize", gridSize, gridSize);
        uniform2(denseGlobalCostProgram, "uStep", step, step);
        uniform2(denseGlobalCostProgram, "uFlowLimit", limit, limit);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseGlobalCostProgram,
                "uUseCenter"), useCenter ? 1f : 0f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private void reduceDenseGlobalCosts(int costs, int zeroCosts, int center,
                                        boolean useCenter, int destination,
                                        int gridSize, float step, float limit) {
        attachDenseTarget(destination, 1, 1);
        GLES20.glUseProgram(denseGlobalReduceProgram);
        bindQuad(denseGlobalReduceProgram);
        bindTexture(denseGlobalReduceProgram, "uCosts", costs, 0);
        bindTexture(denseGlobalReduceProgram, "uZeroCosts", zeroCosts, 1);
        bindTexture(denseGlobalReduceProgram, "uCenterSeed", center, 2);
        uniform2(denseGlobalReduceProgram, "uGridSize", gridSize, gridSize);
        uniform2(denseGlobalReduceProgram, "uStep", step, step);
        uniform2(denseGlobalReduceProgram, "uFlowLimit", limit, limit);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseGlobalReduceProgram,
                "uUseCenter"), useCenter ? 1f : 0f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private void solveDenseDirection(int direction, int reference, int target,
                                     boolean temporalGuideReady) {
        int prior = 0;
        for (int level = DENSE_LEVELS - 1; level >= 0; --level) {
            int ref = level == 0 ? reference :
                    densePyramidTextures[direction == 0 ? 0 : 1][level - 1];
            int dst = level == 0 ? target :
                    densePyramidTextures[direction == 0 ? 1 : 0][level - 1];
            int width = denseLevelWidths[level];
            int height = denseLevelHeights[level];
            // Both directions perform the same fixed work. The first fine
            // draw expands the independently solved 64x36 field to 128x72;
            // the remaining three draws search locally in that direction's
            // own image domain.
            int iterations = DENSE_LEVEL_ITERATIONS[level];
            if (level == DENSE_LEVELS - 1 && denseWorkLevel > 0)
                iterations = Math.max(4, iterations - 2 * denseWorkLevel);
            for (int iteration = 0; iteration < iterations; ++iteration) {
                int output = denseFlowTextures[direction][level][iteration & 1];
                attachDenseTarget(output, width, height);
                GLES20.glUseProgram(denseSolveProgram);
                bindQuad(denseSolveProgram);
                bindTexture(denseSolveProgram, "uReference", ref, 0);
                bindTexture(denseSolveProgram, "uTarget", dst, 1);
                bindTexture(denseSolveProgram, "uPriorFlow", prior == 0 ?
                        denseFlowTextures[direction][level][1] : prior, 2);
                boolean coarsestFirst = level == DENSE_LEVELS - 1 &&
                        iteration == 0;
                boolean temporalGuide = temporalGuideReady && coarsestFirst;
                bindTexture(denseSolveProgram, "uTemporalFlow",
                        denseValidatedTextures[direction], 3);
                boolean reciprocalGuide = direction == 1 && iteration == 0;
                int reciprocalTexture = reciprocalGuide ?
                        denseFlowTextures[0][level]
                                [(DENSE_LEVEL_ITERATIONS[level] - 1) & 1] :
                        denseValidatedTextures[0];
                bindTexture(denseSolveProgram, "uReciprocalFlow",
                        reciprocalTexture, 4);
                bindTexture(denseSolveProgram, "uGlobalSeed",
                        denseGlobalSeedTextures[direction], 5);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uHasPrior"), prior == 0 ? 0f : 1f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uUseTemporalGuide"), temporalGuide ? 1f : 0f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uUseReciprocalGuide"), reciprocalGuide ? 1f : 0f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uUseGlobalSeed"),
                        denseV28ReducedAnalysisRequested && coarsestFirst ? 1f : 0f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uUseNeighborProposal"), 0f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uReciprocalMargin"), 0.002f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uNeighborMargin"), 0.002f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uCycleObjectiveWeight"), 0f);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uTemporalLimit"), denseMaxFlowPixels());
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
                        "uBypassSearch"), level == 0 && iteration == 0 ? 1f : 0f);
                uniform2(denseSolveProgram, "uAnalysisTexel",
                        1f / width, 1f / height);
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
                uniform2(denseSolveProgram, "uReciprocalTexel",
                        1f / denseLevelWidths[level],
                        1f / denseLevelHeights[level]);
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
                // Derived from the active reach: 4.5px for a 47px reach,
                // ~12px for the 108px reach of a 1080p source.
                float coarsestStep = denseCoarsestStep();
                float step = level == 2 ? coarsestStep :
                        level == 1 ? 2f : 1f;
                uniform2(denseSolveProgram, "uUpdateStep", step, step);
                GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                        "uExhaustiveRadius"), coarsestFirst ? 4f : 0f);
                GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
                prior = output;
            }
        }
        denseFinalTextures[direction] = prior;
    }

    /**
     * Performs one full-resolution current-cost refinement from the finalized
     * opposite field. This is a proposal, not inverse projection: the shader
     * retains the direction's existing solution unless the reciprocal basin
     * improves that direction's photometric/chroma/gradient objective by a
     * strict margin, then still executes its normal local 3x3 search.
     */
    private void refineDenseReciprocalDirection(int direction, int reference,
                                                 int target) {
        int prior = denseFinalTextures[direction];
        int output = prior == denseFlowTextures[direction][0][0] ?
                denseFlowTextures[direction][0][1] :
                denseFlowTextures[direction][0][0];
        attachDenseTarget(output, denseAnalysisWidth, denseAnalysisHeight);
        GLES20.glUseProgram(denseSolveProgram);
        bindQuad(denseSolveProgram);
        bindTexture(denseSolveProgram, "uReference", reference, 0);
        bindTexture(denseSolveProgram, "uTarget", target, 1);
        bindTexture(denseSolveProgram, "uPriorFlow", prior, 2);
        bindTexture(denseSolveProgram, "uTemporalFlow",
                denseValidatedTextures[direction], 3);
        bindTexture(denseSolveProgram, "uReciprocalFlow",
                denseFinalTextures[1 - direction], 4);
        bindTexture(denseSolveProgram, "uGlobalSeed",
                denseGlobalSeedTextures[direction], 5);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uHasPrior"), 1f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uUseTemporalGuide"), 0f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uUseReciprocalGuide"), 1f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uUseGlobalSeed"), 0f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uUseNeighborProposal"), 1f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uReciprocalMargin"), 0.006f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uNeighborMargin"), 0.002f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uCycleObjectiveWeight"), 0.006f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uTemporalLimit"), denseMaxFlowPixels());
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uUseWidePatch"), 0f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uFinalConsensus"), 0f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uBypassSearch"), 0f);
        uniform2(denseSolveProgram, "uAnalysisTexel",
                1f / denseAnalysisWidth, 1f / denseAnalysisHeight);
        uniform2(denseSolveProgram, "uPriorTexel",
                1f / denseAnalysisWidth, 1f / denseAnalysisHeight);
        uniform2(denseSolveProgram, "uReciprocalTexel",
                1f / denseAnalysisWidth, 1f / denseAnalysisHeight);
        uniform2(denseSolveProgram, "uSourceSize", historyWidth, historyHeight);
        uniform2(denseSolveProgram, "uUpdateStep", 1f, 1f);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseSolveProgram,
                "uExhaustiveRadius"), 0f);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        denseFinalTextures[direction] = output;
    }

    /** Two neighbour-fill passes, ping-ponging so the result lands back in the validated texture. */
    private void fillDenseDirection(int direction) {
        if (denseFillProgram == 0) return;
        int source = denseValidatedTextures[direction];
        int scratch = denseFillTextures[direction];
        // Passes 0-1: strict fill of isolated rejections from validated
        // neighbours.  Passes 2-3: relaxed diffusion into flat cells.  Even
        // pass count, so the result lands back in the validated texture.
        // Passes 0-1 strict, 2-3 relaxed (flat cells), 4-5 wide occlusion
        // inpainting.  Even pass count, so the result lands back in the
        // validated texture.
        int passes = denseWorkLevel == 0 ? 6 : denseWorkLevel == 1 ? 2 : 0;
        for (int pass = 0; pass < passes; ++pass) {
            int destination = (pass & 1) == 0 ? scratch : denseValidatedTextures[direction];
            int input = (pass & 1) == 0 ? source : scratch;
            attachDenseTarget(destination, denseAnalysisWidth, denseAnalysisHeight);
            GLES20.glUseProgram(denseFillProgram);
            bindQuad(denseFillProgram);
            bindTexture(denseFillProgram, "uField", input, 0);
            uniform2(denseFillProgram, "uTexel", 1f / denseAnalysisWidth, 1f / denseAnalysisHeight);
            GLES20.glUniform1f(GLES20.glGetUniformLocation(denseFillProgram, "uRelaxed"),
                    pass >= 4 ? 2f : pass >= 2 ? 1f : 0f);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        }
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
        float limit = Math.min(denseMaxFlowPixels(),
                flowLimitPixels(historyWidth, historyHeight));
        uniform2(denseCycleProgram, "uFlowRange", limit / historyWidth,
                limit / historyHeight);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(denseCycleProgram,
                "uValidityBase"),
                2f * Math.max(1f, activeFlowLimitPixels() / DENSE_MAX_FLOW_PIXELS));
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    private float[] denseActiveRect() {
        // The generator's history texture is the engine's game-only surface.
        // GameSurfaceView shapes the Surface layer itself; black pillars live
        // in the parent window and are never present in these textures.
        return new float[]{0f, 0f, 1f, 1f};
    }

    // Diagnostic flow dump (2026-09-02, wiiu-b61 frame proof): a recording of
    // the panel showed the two synthesized slots of a 40->120 pan holding the
    // exact nearest endpoint, i.e. dense reliability below 0.02 across the
    // moving region while the validity counters read healthy.  When the
    // marker file exists, the validated and raw dense fields plus the
    // half-resolution endpoint pyramids are written to the app's files dir
    // for offline inspection.  Bounded to a few dumps per session.
    private static final java.io.File DENSE_FLOW_DUMP_MARKER =
            new java.io.File("/data/local/tmp/lucent-flowdump");
    // Optional diagnostic override; still requires the primary marker and
    // retains the eight-dump limit and 700ms attempt interval. This controls
    // evidence collection only, never runtime generation admission.
    private static final java.io.File DENSE_FLOW_DUMP_LOW_MOTION_MARKER =
            new java.io.File("/data/local/tmp/lucent-flowdump-low-motion");
    private static final java.io.File DENSE_FLOW_DUMP_DIR =
            new java.io.File(android.os.Environment.getExternalStorageDirectory(),
                    "Android/data/com.thorium.preview/files/flowdump");
    private static final int DENSE_FLOW_DUMP_LIMIT = 8;
    // A burst of dumps is re-armed by touching the marker (its mtime is the
    // burst id). By default the coarse endpoint difference must exceed the
    // threshold so a burst lands on a pan, not startup static frames. The
    // explicit low-motion marker permits inspecting subtle local animation.
    private static final float DENSE_FLOW_DUMP_MIN_COARSE_DIFFERENCE = 10f / 255f;
    private java.nio.ByteBuffer denseCoarseReadbackA, denseCoarseReadbackB;

    /** Mean absolute luma difference of the two coarsest (32x18) pyramid levels. */
    private float readDenseCoarseDifference() {
        int w = denseLevelWidths[DENSE_LEVELS - 1], h = denseLevelHeights[DENSE_LEVELS - 1];
        int bytes = w * h * 4;
        if (denseCoarseReadbackA == null || denseCoarseReadbackA.capacity() < bytes) {
            denseCoarseReadbackA = java.nio.ByteBuffer.allocateDirect(bytes).order(java.nio.ByteOrder.nativeOrder());
            denseCoarseReadbackB = java.nio.ByteBuffer.allocateDirect(bytes).order(java.nio.ByteOrder.nativeOrder());
        }
        attachDenseTarget(densePyramidTextures[0][DENSE_LEVELS - 2], w, h);
        denseCoarseReadbackA.clear();
        GLES20.glReadPixels(0, 0, w, h, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, denseCoarseReadbackA);
        attachDenseTarget(densePyramidTextures[1][DENSE_LEVELS - 2], w, h);
        denseCoarseReadbackB.clear();
        GLES20.glReadPixels(0, 0, w, h, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, denseCoarseReadbackB);
        long sum = 0;
        for (int i = 0; i < bytes; i += 4) {
            int la = ((denseCoarseReadbackA.get(i) & 0xff) * 77 + (denseCoarseReadbackA.get(i + 1) & 0xff) * 150 +
                    (denseCoarseReadbackA.get(i + 2) & 0xff) * 29) >> 8;
            int lb = ((denseCoarseReadbackB.get(i) & 0xff) * 77 + (denseCoarseReadbackB.get(i + 1) & 0xff) * 150 +
                    (denseCoarseReadbackB.get(i + 2) & 0xff) * 29) >> 8;
            sum += Math.abs(la - lb);
        }
        return sum / (255f * (bytes / 4));
    }
    private int denseFlowDumpCount;
    private long denseFlowDumpLastNs;
    /** Per-direction dense global seed in source pixels (0 = backward, 1 = forward). */
    private final float[][] denseSeedPx = new float[2][2];
    private long denseFlowDumpBurstId;
    private final java.nio.ByteBuffer denseSeedReadback =
            java.nio.ByteBuffer.allocateDirect(4).order(java.nio.ByteOrder.nativeOrder());

    private float[] readDenseGlobalSeedPixels(int direction) {
        attachDenseTarget(denseGlobalSeedTextures[direction], 1, 1);
        denseSeedReadback.clear();
        GLES20.glReadPixels(0, 0, 1, 1, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE,
                denseSeedReadback);
        int r = denseSeedReadback.get(0) & 0xff, g = denseSeedReadback.get(1) & 0xff;
        int b = denseSeedReadback.get(2) & 0xff, a = denseSeedReadback.get(3) & 0xff;
        int x = r * 256 + g, y = b * 256 + a;
        if (x >= 32768) x -= 65536;
        if (y >= 32768) y -= 65536;
        return new float[] {x / 256f, y / 256f};
    }

    private void maybeDumpDenseFlow(int previousIndex, int currentIndex) {
        long now = System.nanoTime();
        if (!DENSE_FLOW_DUMP_MARKER.exists()) return;
        boolean contiguousCapture = new java.io.File(
                "/data/local/tmp/lucent-flowdump-contiguous").exists();
        if (!contiguousCapture && now - denseFlowDumpLastNs < 700_000_000L) return;
        // This opt-in diagnostic intentionally stalls for readback. Its output
        // is image evidence only; never use it to qualify presentation timing.
        if (contiguousCapture && (activeLeftSequence <= 0L ||
                activeRightSequence != activeLeftSequence + 1L ||
                activeRightTimestampNs <= activeLeftTimestampNs)) return;
        long burst = DENSE_FLOW_DUMP_MARKER.lastModified();
        if (burst != denseFlowDumpBurstId) {
            denseFlowDumpBurstId = burst;
            denseFlowDumpCount = 0;
        }
        if (denseFlowDumpCount >= DENSE_FLOW_DUMP_LIMIT) return;
        // Rate-limit attempts, not only successful dumps. Even a rejected
        // scene performs a synchronous GPU readback below; polling it every
        // promotion contaminates the frame-pacing measurement.
        denseFlowDumpLastNs = now;
        // Trigger on the raw coarsest-pyramid image difference, not on the
        // global seed: the seed reduce zeroes itself unless the pan beats the
        // zero-motion cost by 3.5 percent, which a dark-background pan fails.
        float coarseDifference = readDenseCoarseDifference();
        if (coarseDifference < DENSE_FLOW_DUMP_MIN_COARSE_DIFFERENCE &&
                !DENSE_FLOW_DUMP_LOW_MOTION_MARKER.exists() && !contiguousCapture) {
            Log.i(TAG, "Dense flow dump waiting generator=" + generatorId +
                    " coarseDifference=" + coarseDifference +
                    " required=" + DENSE_FLOW_DUMP_MIN_COARSE_DIFFERENCE);
            return;
        }
        float[] seed = readDenseGlobalSeedPixels(0);
        ++denseFlowDumpCount;
        try {
            DENSE_FLOW_DUMP_DIR.mkdirs();
            java.io.File file = new java.io.File(DENSE_FLOW_DUMP_DIR,
                    "dump-" + generatorId + "-" + (denseFlowDumpBurstId / 1000L % 100000L) +
                    "-" + denseFlowDumpCount + ".bin");
            try (java.io.DataOutputStream out = new java.io.DataOutputStream(
                    new java.io.BufferedOutputStream(new java.io.FileOutputStream(file), 1 << 16))) {
                out.writeInt(0x4c464431); // 'LFD1'
                out.writeFloat(activeFlowLimitPixels());
                out.writeFloat(denseMaxFlowPixels());
                out.writeInt(frameRate.lockedSourceFps());
                out.writeInt(historyWidth);
                out.writeInt(historyHeight);
                out.writeInt(10);
                dumpDensePlane(out, "validated0", denseValidatedTextures[0],
                        denseAnalysisWidth, denseAnalysisHeight);
                dumpDensePlane(out, "validated1", denseValidatedTextures[1],
                        denseAnalysisWidth, denseAnalysisHeight);
                dumpDensePlane(out, "final0", denseFinalTextures[0],
                        denseAnalysisWidth, denseAnalysisHeight);
                dumpDensePlane(out, "final1", denseFinalTextures[1],
                        denseAnalysisWidth, denseAnalysisHeight);
                dumpDensePlane(out, "previousHalf", densePyramidTextures[0][0],
                        denseLevelWidths[1], denseLevelHeights[1]);
                dumpDensePlane(out, "currentHalf", densePyramidTextures[1][0],
                        denseLevelWidths[1], denseLevelHeights[1]);
                // Capture endpoints from the SAME live pair as these fields.
                // Half-resolution pyramids alone cannot prove native edge quality.
                dumpDensePlane(out, "previousFull", historyTextures[previousIndex],
                        historyWidth, historyHeight);
                dumpDensePlane(out, "currentFull", historyTextures[currentIndex],
                        historyWidth, historyHeight);
                dumpDensePlane(out, "seed0", denseGlobalSeedTextures[0], 1, 1);
                dumpDensePlane(out, "seed1", denseGlobalSeedTextures[1], 1, 1);
            }
            try (java.io.PrintWriter metadata = new java.io.PrintWriter(
                    new java.io.File(file.getPath() + ".json"))) {
                metadata.println("{\"leftSequence\":" + activeLeftSequence +
                        ",\"rightSequence\":" + activeRightSequence +
                        ",\"leftSubmission\":" + activeLeftSubmission +
                        ",\"rightSubmission\":" + activeRightSubmission +
                        ",\"leftTimestampNs\":" + activeLeftTimestampNs +
                        ",\"rightTimestampNs\":" + activeRightTimestampNs +
                        ",\"contiguousCapture\":" + contiguousCapture +
                        ",\"timingQualified\":false}");
                if (metadata.checkError()) throw new java.io.IOException("flow metadata write failed");
            }
            Log.i(TAG, "Dense flow dump written generator=" + generatorId +
                    " file=" + file + " analysis=" + denseAnalysisWidth + "x" +
                    denseAnalysisHeight + " limitPx=" + activeFlowLimitPixels() +
                    " lockedFps=" + frameRate.lockedSourceFps() +
                    " seedPx=" + seed[0] + "," + seed[1] +
                    " coarseDifference=" + coarseDifference);
        } catch (java.io.IOException | RuntimeException failure) {
            Log.w(TAG, "Dense flow dump failed generator=" + generatorId, failure);
        }
    }

    private void dumpDensePlane(java.io.DataOutputStream out, String name, int texture,
                                int width, int height) throws java.io.IOException {
        byte[] label = name.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        out.writeInt(label.length);
        out.write(label);
        out.writeInt(width);
        out.writeInt(height);
        java.nio.ByteBuffer pixels = java.nio.ByteBuffer.allocateDirect(width * height * 4)
                .order(java.nio.ByteOrder.nativeOrder());
        attachDenseTarget(texture, width, height);
        GLES20.glReadPixels(0, 0, width, height, GLES20.GL_RGBA,
                GLES20.GL_UNSIGNED_BYTE, pixels);
        byte[] copy = new byte[width * height * 4];
        pixels.rewind();
        pixels.get(copy);
        out.write(copy);
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

    /** Draws the Vulkan-produced app-owned image with the required Y-origin conversion. */
    private void drawExternalGeneratedTexture(int sourceTexture) {
        GLES20.glUseProgram(externalGeneratedTextureCopyProgram);
        bindQuad(externalGeneratedTextureCopyProgram);
        bindTexture(externalGeneratedTextureCopyProgram, "uTexture", sourceTexture, 0);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
    }

    /** Once measured, physical scan phase replaces callback phase for Built-in. */
    private static boolean requiresNonblockingBuiltinSwap(boolean hasExternalTransport) {
        return !hasExternalTransport;
    }

    private static boolean sampleBuiltinCompositorTiming(boolean prepared, boolean dense,
            boolean external, boolean generating, int samples) {
        return prepared && dense && !external && generating && samples >= 0 && samples < 64;
    }

    private long builtinQueueCutoffMisses;
    private long builtinPlanCallbackNs, builtinPlanNowNs;
    private long builtinPlanCompositeDeadlineNs, builtinPlanIntervalNs, builtinPlanLatencyNs;
    private int builtinPlanGapEvidenceCount;

    private PhysicalPresentationDeadline nextBuiltInDeadline(long callbackNs, long nowNs) {
        builtinPlanIntervalNs = 0L;
        PhysicalPresentationTracker tracker = physicalPresentationTracker;
        if (externalTransport == null && densePyramidEnabled && tracker != null &&
                tracker.available() && tracker.compositorTiming(builtinCompositorTiming)) {
            // The observed EGL queue cost was ~0.25ms and first query ~0.56ms.
            // Keep 1ms for queue handoff; actual GPU completion remains checked
            // against this earlier cutoff by the physical evidence ledger.
            long planNowNs = System.nanoTime();
            PhysicalPresentationDeadline egl = PhysicalPresentationDeadline.nextEgl(
                    builtinCompositorTiming[0], builtinCompositorTiming[1],
                    builtinCompositorTiming[2], planNowNs,
                    builtInLastCommittedTargetNs, 1_000_000L);
            // Copy the planning query: the later submission probe reuses its
            // array. Emit only after swap, never inside this admission window.
            builtinPlanCallbackNs = callbackNs;
            builtinPlanNowNs = planNowNs;
            builtinPlanCompositeDeadlineNs = builtinCompositorTiming[0];
            builtinPlanIntervalNs = builtinCompositorTiming[1];
            builtinPlanLatencyNs = builtinCompositorTiming[2];
            // A stale/invalid returned timeline must not fall back to the old
            // two-ms assumption for this callback.
            return egl;
        }
        long periodNs = frameRate.panelPeriodNs();
        if (builtInPhysicalClock.available() &&
                builtInPhysicalClock.nominalPeriodNs() ==
                        Math.max(1L, Math.round(1e9 / frameRate.declaredPanelHz()))) {
            return PhysicalPresentationDeadline.nextAligned(callbackNs,
                    // Use recent physical phase, not the epoch's old phase
                    // multiplied by an independently evolving frequency fit.
                    // The committed-target guard still forbids repeating a scan.
                    builtInPhysicalClock.lastActualNs(), builtInPhysicalClock.planningPeriodNs(),
                    nowNs, builtInLastCommittedTargetNs);
        }
        return PhysicalPresentationDeadline.next(callbackNs, periodNs, nowNs);
    }

    /** Preserve aspect and contain the whole image, including on the lower panel. */
    private void setPresentationViewport() {
        float aspect = presentationAspect > 0f ? presentationAspect :
                (float) outputWidth / outputHeight;
        com.thorium.lucent.video.PresentationGeometry.Rectangle bounds =
                com.thorium.lucent.video.PresentationGeometry.fitInside(
                        outputWidth, outputHeight, aspect);
        // Geometry uses top-left coordinates; OpenGL uses bottom-left.
        GLES20.glViewport(bounds.left, outputHeight - bounds.bottom,
                bounds.width(), bounds.height());
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

    private static boolean builtinClockAdmissionReady(boolean dense, boolean rejected,
                                                      int display, double physicalHz) {
        return dense && !rejected && display == 0 &&
                Double.isFinite(physicalHz) && physicalHz > 0.0;
    }

    private static boolean requiresDenseGpuHeadroomBinding(boolean synthetic, int scans) {
        // Before source-clock qualification, real endpoint swaps have no uniform
        // scan count. They cannot earn recovery credit, but are not a broken GPU
        // binding. A synthetic swap must still fail closed if its scans are zero.
        return synthetic || scans > 0;
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
        // The dense generator is the product path (2026-09-01), so HEALTH
        // records exist before the harness arms proof.  The evidence epoch
        // label describes presentation state, not whether proof is armed;
        // leaving it at 0 pre-arm made every pre-arm window "impossible"
        // for the v36 epoch rule (run n64-tier2).  Enqueue counts remain
        // zero until proof is armed, so the per-epoch budget is unchanged.
        if (!densePyramidEnabled ||
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

    /** True only for the Thor's native 60-Hz mode carrying every-scan output. */
    private boolean modeAlignedSixtyHertzOneScanOutput() {
        return externalTransport != null && externalRatePathActive &&
                !externalTransport.requiresCompositorFrameTimeline() &&
                frameRate.panelScansPerOutput() == 1 &&
                frameRate.panelClockMeasured() && frameRate.panelHz() < 90.0;
    }

    private void presentBuffered(PhysicalPresentationDeadline deadline,
                                 CompositorFrameTimeline.Selection compositorTimeline,
                                 int presentation,
                                 float selectedPhase) {
        if (deadline == null || !deadline.valid())
            throw new IllegalArgumentException(
                    "physical presentation deadline is invalid");
        // selectBufferedPresentation may change the scheduler epoch in this
        // callback. Rebind before deciding whether this presented frame can
        // consume the new epoch's bounded proof budget.
        refreshProofEvidencePresentationEpoch();
        boolean realThisTick = presentation ==
                AdaptiveFrameRateController.PRESENT_REAL;
        long selectedTimestampNs = frameRate.bufferedSelectedTargetSourceNs();
        // Use the same overflow-safe integer midpoint as private preparation.
        // Recomputing from float phase can round an odd span the other way.
        if (!realThisTick) {
            selectedTimestampNs = AdaptiveFrameRateController.exactMidpointTimestampNs(
                    activeLeftTimestampNs, activeRightTimestampNs);
        }
        long presentationEpoch = schedulerPresentationEpoch();
        int requestWidth = externalTransport == null ? historyWidth :
                externalTransport.endpointWidth();
        int requestHeight = externalTransport == null ? historyHeight :
                externalTransport.endpointHeight();
        FrameGenerationPresentationRequest presentationRequest;
        if (activeRightSequence == 0L) {
            if (!realThisTick || selectedTimestampNs != activeLeftTimestampNs)
                throw new IllegalStateException(
                        "unpaired frame-generation request is not the retained endpoint");
            presentationRequest = FrameGenerationPresentationRequest.endpoint(
                    generatorId, presentationEpoch,
                    activeLeftSequence, activeLeftTimestampNs,
                    deadline.contentPresentationTimeNs(),
                    deadline.driverDesiredPresentTimeNs(),
                    deadline.hardCompletionDeadlineNs(),
                    deadline.presentationPipelineScans(),
                    requestWidth, requestHeight,
                    FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        } else {
            presentationRequest = FrameGenerationPresentationRequest.between(
                    generatorId, presentationEpoch,
                    activeLeftSequence, activeLeftTimestampNs,
                    activeRightSequence, activeRightTimestampNs,
                    selectedTimestampNs,
                    deadline.contentPresentationTimeNs(),
                    deadline.driverDesiredPresentTimeNs(),
                    deadline.hardCompletionDeadlineNs(),
                    deadline.presentationPipelineScans(),
                    requestWidth, requestHeight,
                    FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        }
        if (Math.abs(presentationRequest.phase() - selectedPhase) > 0.00001)
            throw new IllegalStateException(
                    "controller phase disagrees with immutable endpoint timestamps");
        if (!realThisTick && !midpointPairBudget.canAdmit(presentationRequest))
            throw new IllegalStateException("midpoint admission rejected: " +
                    midpointPairBudget.lastRejection());
        if (externalTransport != null) {
            boolean requiresCompositorTimeline =
                    externalTransport.requiresCompositorFrameTimeline();
            // Direct WSI needs no speculative release window when the target
            // is provably the first scan after the latest completed physical
            // row. EmuFusion owns this decision from its physical clock; the
            // backend receives only the resulting immutable not-before time.
            // Multi-scan targets and compositor-timeline paths retain their
            // existing guarded windows unchanged.
            if (!requiresCompositorTimeline && externalRatePathActive &&
                    frameRate.panelScansPerOutput() == 1 &&
                    externalPhysicalClock.available()) {
                presentationRequest = modeAlignedSixtyHertzOneScanOutput() ?
                        presentationRequest.
                                withReleaseAfterModeAlignedPredecessorScan(
                                        externalPhysicalClock.
                                                planningPeriodNs()) :
                        presentationRequest.
                                withReleaseAfterImmediatePriorPhysicalScan(
                                        externalPhysicalClock.lastActualNs(),
                                        externalPhysicalClock.
                                                planningPeriodNs());
            }
            if (requiresCompositorTimeline && compositorTimeline == null)
                throw new IllegalStateException(
                        "external presentation lacks a compositor frame timeline");
            if (!requiresCompositorTimeline && compositorTimeline != null)
                throw new IllegalStateException(
                        "direct external presentation received a compositor token");
            if (requiresCompositorTimeline) {
                presentationRequest =
                        presentationRequest.
                                withTargetCompositorFrameTimeline(
                                compositorTimeline.vsyncId(),
                                compositorTimeline.expectedPresentationTimeNs(),
                                compositorTimeline.deadlineNs());
            }
            if (externalTransport.usesAppOwnedPresentation()) {
                if (presentationRequest.isGenerated()) {
                    pendingAppOwnedRequest = presentationRequest;
                    pendingAppOwnedPhase = selectedPhase;
                    pendingAppOwnedPreparation = buildExternalGeneratedPreparation(
                            presentation, deadline);
                }
                presentAppOwnedExternalBuffered(
                        presentationRequest, presentation, selectedPhase);
            } else
                presentExternalBuffered(presentationRequest, presentation);
            return;
        }
        // Unlike a deferred external enqueue, this path is now attempting the
        // actual render. A subsequent shader/swap failure cannot renew budget.
        if (!realThisTick && !midpointPairBudget.admit(presentationRequest))
            throw new IllegalStateException("midpoint render admission rejected");
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
        // densePairMeanDifference is never measured in the cadence path (the
        // synchronous proof readbacks were removed), so this Java hold never
        // fires; the hard-cut hold lives in the interpolate shader
        // (uDenseCutTex, build 92).  Kept only as the documented fallback
        // should a CPU-side pair difference ever be reinstated.
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
            // Fit the complete image at its source display aspect. The clear
            // above supplies any necessary letterboxing or pillarboxing.
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
            if (renderedSynthetic) drawProofMark();
            proofPhase = phase;
            // Admission above permits one exact midpoint for this retained pair.
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
            if (deadline.driverDesiredPresentTimeNs() <= 0L ||
                    !EGLExt.eglPresentationTimeANDROID(
                            eglDisplay, eglSurface,
                            deadline.driverDesiredPresentTimeNs()))
                fail("eglPresentationTimeANDROID");
        }
        long swapStarted = densePyramidEnabled ? System.nanoTime() : 0L;
        PhysicalPresentationTracker physicalTracker = physicalPresentationTracker;
        boolean physicalFramePrepared = physicalTracker != null &&
                physicalTracker.available() && physicalTracker.prepareFrame();
        long densePhysicalFrameId = physicalFramePrepared ? physicalTracker.preparedFrameId() : 0L;
        boolean sampleCompositorTiming = sampleBuiltinCompositorTiming(physicalFramePrepared,
                densePyramidEnabled, externalTransport != null,
                frameRate.generatesIntermediateFrames(), builtinCompositorTimingSamples);
        long compositorQueryStartNs = sampleCompositorTiming ? System.nanoTime() : 0L;
        boolean compositorTimingAvailable = sampleCompositorTiming &&
                physicalTracker.compositorTiming(builtinCompositorTiming);
        long compositorQueryEndNs = sampleCompositorTiming ? System.nanoTime() : 0L;
        if (physicalTracker != null && !physicalTracker.available())
            logPhysicalPresentationFailure(physicalTracker);
        if (externalTransport == null &&
                deadline.hardCompletionDeadlineNs() < deadline.driverDesiredPresentTimeNs() &&
                System.nanoTime() >= deadline.hardCompletionDeadlineNs()) {
            ++builtinQueueCutoffMisses;
            if (builtinQueueCutoffMisses <= 8L) {
                Log.w(TAG, "Built-in queue cutoff missed generator=" + generatorId +
                        " frameId=" + densePhysicalFrameId +
                        " synthetic=" + renderedSynthetic +
                        " targetNs=" + deadline.contentPresentationTimeNs() +
                        " deadlineNs=" + deadline.hardCompletionDeadlineNs() +
                        " observedNs=" + System.nanoTime());
            }
            if (physicalFramePrepared) physicalTracker.cancelPrepared();
            // Do not swap stale content or commit scheduler credit after its
            // prospective EGL queue deadline. The next callback selects anew.
            frameRate.abortBufferedPresentation();
            invalidateBufferedPairForReprime(false);
            return;
        }
        beginFullImageCapture(renderedSynthetic, densePhysicalFrameId, proofPhase);
        long denseSwapEnteredNs = densePyramidEnabled ? System.nanoTime() : 0L;
        if (!EGL14.eglSwapBuffers(eglDisplay, eglSurface)) {
            discardFullImageCapture();
            if (physicalFramePrepared) physicalTracker.cancelPrepared();
            fail("eglSwapBuffers");
        }
        long denseSwapReturnedNs = densePyramidEnabled ? System.nanoTime() : 0L;
        boolean densePhysicalFrameCommitted = physicalFramePrepared && physicalTracker.commitPrepared(
                frameRate.panelScansPerOutput(), frameRate.panelPeriodNs());
        if (densePyramidEnabled && densePhysicalFrameCommitted && externalTransport == null)
            denseSubmissionHistory.record(schedulerPresentationEpoch(), densePhysicalFrameId,
                    deadline.contentPresentationTimeNs(), deadline.hardCompletionDeadlineNs(),
                    denseSwapEnteredNs, denseSwapReturnedNs, renderedSynthetic);
        finishFullImageCapture(densePhysicalFrameCommitted);
        if (sampleCompositorTiming) {
            ++builtinCompositorTimingSamples;
            Log.i(TAG, "Built-in compositor submission generator=" + generatorId +
                    " frameId=" + densePhysicalFrameId + " synthetic=" + renderedSynthetic +
                    " available=" + compositorTimingAvailable +
                    " queryStartNs=" + compositorQueryStartNs +
                    " queryEndNs=" + compositorQueryEndNs +
                    " swapReturnedNs=" + System.nanoTime() +
                    " targetNs=" + deadline.contentPresentationTimeNs() +
                    " requestedNs=" + deadline.driverDesiredPresentTimeNs() +
                    " compositeDeadlineNs=" + (compositorTimingAvailable ? builtinCompositorTiming[0] : 0L) +
                    " compositeIntervalNs=" + (compositorTimingAvailable ? builtinCompositorTiming[1] : 0L) +
                    " compositeLatencyNs=" + (compositorTimingAvailable ? builtinCompositorTiming[2] : 0L));
        }
        if (builtinPlanIntervalNs > 0L && builtInLastCommittedTargetNs > 0L &&
                frameRate.generatesIntermediateFrames() && frameRate.panelScansPerOutput() == 1 &&
                deadline.contentPresentationTimeNs() - builtInLastCommittedTargetNs >
                        builtinPlanIntervalNs + builtinPlanIntervalNs / 2L &&
                builtinPlanGapEvidenceCount < 8) {
            ++builtinPlanGapEvidenceCount;
            Log.w(TAG, "Built-in committed target gap generator=" + generatorId +
                    " frameId=" + densePhysicalFrameId +
                    " previousTargetNs=" + builtInLastCommittedTargetNs +
                    " targetNs=" + deadline.contentPresentationTimeNs() +
                    " callbackNs=" + builtinPlanCallbackNs + " planNowNs=" + builtinPlanNowNs +
                    " compositeDeadlineNs=" + builtinPlanCompositeDeadlineNs +
                    " intervalNs=" + builtinPlanIntervalNs + " latencyNs=" + builtinPlanLatencyNs +
                    " reserveNs=1000000 skippedScans=" + deadline.skippedPanelScans());
        }
        builtInLastCommittedTargetNs = deadline.contentPresentationTimeNs();
        if (physicalFramePrepared && !densePhysicalFrameCommitted)
            logPhysicalPresentationFailure(physicalTracker);
        if (densePyramidEnabled) {
            if (denseGpuHeadroomPresentationEpoch != presentationEpoch) {
                denseGpuHeadroomPresentationEpoch = presentationEpoch;
                denseGpuAdaptation.invalidateRecoveryEvidence();
            }
            if (!densePhysicalFrameCommitted ||
                    !requiresDenseGpuHeadroomBinding(renderedSynthetic,
                            frameRate.panelScansPerOutput())) {
                ++denseGpuPhysicalUnboundEvents;
                denseGpuAdaptation.invalidateRecoveryEvidence();
            } else if (!denseGpuHeadroom.bindSwap(denseGpuHeadroom.evidenceEpoch(),
                    presentationEpoch, densePhysicalFrameId,
                    renderedSynthetic ? densePromotions : 0L,
                    renderedSynthetic ? denseWarpSequence : 0L,
                    deadline.contentPresentationTimeNs(), deadline.hardCompletionDeadlineNs(),
                    frameRate.panelScansPerOutput(), frameRate.panelPeriodNs())) {
                // The visible swap already succeeded. Preserve its controller
                // commit below; reject at the next timer poll before more
                // synthesis, not halfway through this presentation transaction.
                denseGpuAdaptation.invalidateRecoveryEvidence();
                pendingDenseGpuHeadroomReject = "gpu-headroom-binding-failure";
                Log.e(TAG, "Dense GPU swap binding rejected generator=" + generatorId +
                        " presentationEpoch=" + presentationEpoch +
                        " frameId=" + densePhysicalFrameId +
                        " pair=" + (renderedSynthetic ? densePromotions : 0L) +
                        " warp=" + (renderedSynthetic ? denseWarpSequence : 0L) +
                        " desiredNs=" + deadline.contentPresentationTimeNs() +
                        " deadlineNs=" + deadline.hardCompletionDeadlineNs() +
                        " scans=" + frameRate.panelScansPerOutput() +
                        " periodNs=" + frameRate.panelPeriodNs() +
                        " ledger={" + denseGpuHeadroom.bindingState() + "}");
            }
        }
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
        if (endpointAdvance == 1 &&
                frameRate.bufferedRetainedLeftSequence() != activeRightSequence) {
            Log.e(TAG, "Buffered commit ownership mismatch" +
                    " generator=" + generatorId +
                    " presentation=" + presentation +
                    " phase=" + frameRate.bufferedSelectedPhase() +
                    " displayLeft=" + activeLeftSequence +
                    " displayRight=" + activeRightSequence +
                    " controllerLeft=" +
                            frameRate.bufferedRetainedLeftSequence() +
                    " controllerRight=" +
                            frameRate.bufferedRetainedRightSequence() +
                    " expectedAdvance=" +
                            frameRate.bufferedExpectedAdvance() +
                    " credits=" + frameRate.bufferedOutputCredits() +
                    " epoch=" + schedulerPresentationEpoch() +
                    " reason=" + frameRate.bufferedLastEpochReason());
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
            // A window that saw no callback and no present (a reset that
            // coincided with the 120-present boundary) reports nothing; the
            // verifier accepts a zero-work record only as the proof-reset
            // snapshot with zero lifetime counters, and a mid-session one
            // rejected the entire PSP log (run psp-b19).  Fold it into the
            // next window instead of emitting it.
            boolean emptyResetWindow = windowPresents == 0L &&
                    windowPresentationCallbacks == 0L &&
                    (densePromotions > 0L || proofSamples > 0L);
            double actualPresentHz = windowPresents * 1000.0 / windowElapsedMs;
            boolean generationMissesTarget =
                    frameRate.generatesIntermediateFrames() &&
                    FrameGenerationCadence.generationMissesTargetCadence(
                            windowElapsedMs, windowPresents,
                            frameRate.lockedSourceFps(), frameRate.outputFps());
            boolean targetScheduleEligible = denseCadenceTargetEligible(
                    windowElapsedMs, windowPromoted, frameRate.lockedSourceFps(),
                    windowDueNoEndpoint, windowSyntheticQuotaSkipped,
                    windowDuePhaseClamped,
                    windowSyntheticNotReady, windowDuplicatePairSelection,
                    windowPresentationEpoch, lastHealthPresentationEpoch);
            // A missed generated target can convict the presentation path only
            // when every selected slot had the source endpoint/pair evidence
            // needed to produce it. r31's F-Zero course transition had 8--32
            // due-without-endpoint slots in three consecutive windows: the
            // renderer remained comfortably inside budget, yet this formerly
            // accumulated an unconditional target failure and permanently
            // disabled dense generation. Use the same independent scheduling
            // eligibility required by the dense cadence gate so source/menu
            // starvation resets, rather than advances, the failure streak.
            generationTargetFailureWindows =
                    FrameGenerationCadence.advanceCadenceFailureWindows(
                            generationTargetFailureWindows,
                            targetScheduleEligible,
                            generationMissesTarget);
            boolean generationTargetReject = generationMissesTarget &&
                    generationTargetFailureWindows >=
                            DENSE_CADENCE_REJECT_CONSECUTIVE_WINDOWS;
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
            } else if (!emptyResetWindow &&
                    activeProofSchemaVersion() == DENSE_V28_PROOF_SCHEMA_VERSION) {
                try {
                    logSplitHealth(now, windowElapsedMs, windowPresents,
                            windowGenerated, windowPromoted, windowDueSelected,
                            windowDueNoEndpoint, windowDuePhaseClamped,
                            windowRealPriority, windowSyntheticQuotaSkipped,
                            windowPresentationEpoch, windowSyntheticSelected,
                            windowSyntheticPairCreated, windowSyntheticNotReady,
                            windowDuplicatePairSelection);
                } catch (RuntimeException healthTransportFailure) {
                    // The visible swap and buffered endpoint transaction have
                    // already committed above. Evidence transport is allowed
                    // to fail closed, but it must never roll back only the
                    // renderer half of a successful presentation. Doing so
                    // manufactured a one-endpoint controller/renderer split
                    // once per HEALTH interval on physical Thor hardware.
                    Log.e(TAG, "Presentation health transport failed after " +
                            "successful swap", healthTransportFailure);
                }
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
                    " denseGpuBudgetUs=" + denseGpuBudgetUs() +
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
                if (generationTargetReject) {
                    Log.e(TAG, "Frame generation failed its target cadence" +
                            " generator=" + generatorId +
                            " role=" + displayRole +
                            " source=" + frameRate.lockedSourceFps() +
                            " target=" + frameRate.outputFps() +
                            " actual=" + String.format(java.util.Locale.US,
                                    "%.2f", actualPresentHz));
                    if (densePyramidEnabled)
                        rejectDense("presentation-below-direct-source-floor", null);
                    else {
                        frameRate.setGenerationAvailable(false);
                        invalidateBufferedPairForReprime(false);
                    }
                    resetHealthWindowAfterStreamChange();
                }
            }
        }
        reportStats();
    }

    /**
     * Builds and completes the first midpoint inside the already-published
     * generated scheduler epoch. No visible slot is selected while this method
     * returns false, so the active pair and its timestamps cannot move under
     * the private output.
     */
    private boolean primeFirstExternalGeneratedOutput() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null || !externalRatePathPriming ||
                !externalRatePathOutputPriming ||
                !frameRate.generationAvailable() ||
                activeLeftSequence <= 0L ||
                activeRightSequence != activeLeftSequence + 1L ||
                !transport.hasAdjacentPair(
                        activeLeftSequence, activeRightSequence) ||
                !transport.hasPreparedLookahead(activeRightSequence))
            return false;
        long midpointNs =
                AdaptiveFrameRateController.exactMidpointTimestampNs(
                        activeLeftTimestampNs, activeRightTimestampNs);
        if (midpointNs <= activeLeftTimestampNs ||
                midpointNs >= activeRightTimestampNs)
            throw new IllegalStateException(
                    "external output-prime midpoint is not interior");
        FrameGenerationPreparationRequest request =
                FrameGenerationPreparationRequest.between(
                        generatorId, schedulerPresentationEpoch(),
                        activeLeftSequence, activeLeftTimestampNs,
                        activeRightSequence, activeRightTimestampNs,
                        midpointNs,
                        transport.endpointWidth(), transport.endpointHeight(),
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        submitExternalGeneratedPreparation(request);
        ExternalFrameGenerationTransport.PreparationReadiness readiness =
                transport.preparationReadiness(request);
        ExternalFrameGenerationTransport.GenerationReadiness pairReadiness =
                transport.generationReadiness(
                        activeLeftSequence, activeRightSequence);
        if (readiness ==
                    ExternalFrameGenerationTransport.PreparationReadiness.UNSAFE ||
                pairReadiness ==
                    ExternalFrameGenerationTransport.GenerationReadiness.UNSAFE) {
            // A scene cut during the invisible first-output prime is an
            // ordinary discontinuity, not a fatal backend failure. Discard
            // the exact pair and publish one fresh scheduler epoch while the
            // already-proven model/import cache stays warm. No output from
            // either side of the cut can become visible or qualify the new
            // evidence epoch.
            long previousEpoch = schedulerPresentationEpoch();
            invalidateBufferedPairForReprime();
            observedBufferedPresentationEpoch =
                    schedulerPresentationEpoch();
            refreshProofEvidencePresentationEpoch();
            externalDirectOutputPhaseAnchorNs = 0L;
            resetHealthWindowAfterStreamChange();
            Log.i(TAG, "External output-prime pair rejected" +
                    " generator=" + generatorId +
                    " previousEpoch=" + previousEpoch +
                    " epoch=" + schedulerPresentationEpoch() +
                    " pair=" + request.leftSequence() + "/" +
                            request.rightSequence() +
                    " preparationReadiness=" + readiness +
                    " pairReadiness=" + pairReadiness);
            return false;
        }
        if (readiness !=
                ExternalFrameGenerationTransport.PreparationReadiness.READY)
            return false;
        if (pairReadiness !=
                ExternalFrameGenerationTransport.GenerationReadiness.READY)
            return false;
        return transport.privateGenerationPipelineWarm();
    }

    /**
     * Prepares a future fractional output behind the selected visible WSI.
     *
     * <p>A prime REAL leaves A/B active, so its following midpoint uses A/B. A
     * REAL-right decision retires A/B and advances to B/C, so the exact queued
     * successor C is peeked without consuming the FIFO. On an exact 2x path,
     * the successful A/B midpoint also authorizes preparing B/C immediately:
     * REAL B occupies the intervening output slot, giving private inference a
     * complete source interval before the B/C midpoint instead of one panel
     * interval. The immutable request is still submitted only after the
     * current visible WSI command succeeds, so private compute can never sit
     * in front of the frame being shown.</p>
     */
    private FrameGenerationPreparationRequest buildExternalGeneratedPreparation(
            int presentation, PhysicalPresentationDeadline deadline) {
        ExternalFrameGenerationTransport transport = externalTransport;
        boolean prepareAfterReal = presentation ==
                AdaptiveFrameRateController.PRESENT_REAL;
        boolean prepareSuccessorAfterExactDoubleSynthetic = presentation ==
                AdaptiveFrameRateController.PRESENT_SYNTHETIC &&
                frameRate.bufferedPendingExactDoubleSchedule();
        if (transport == null ||
                (!externalRatePathActive && !externalRatePathPriming) ||
                (!prepareAfterReal &&
                        !prepareSuccessorAfterExactDoubleSynthetic) ||
                deadline == null || !deadline.valid() ||
                activeLeftSequence <= 0L ||
                activeRightSequence != activeLeftSequence + 1L ||
                !transport.hasAdjacentPair(
                        activeLeftSequence, activeRightSequence))
            return null;

        long leftSequence = activeLeftSequence;
        long leftTimestampNs = activeLeftTimestampNs;
        long rightSequence = activeRightSequence;
        long rightTimestampNs = activeRightTimestampNs;
        int advance = frameRate.bufferedEndpointAdvanceAfterPresentation();
        if (prepareSuccessorAfterExactDoubleSynthetic && advance != 0)
            return null;
        if (advance == 1 || prepareSuccessorAfterExactDoubleSynthetic) {
            if (endpointFifoCount <= 0) return null;
            int successorSlot = endpointFifoHead;
            long successorSequence = endpointFifoSequence[successorSlot];
            long successorTimestampNs =
                    endpointFifoTimestampNs[successorSlot];
            if (successorSequence != activeRightSequence + 1L ||
                    !AdaptiveFrameRateController.endpointSpanContinuous(
                            activeRightTimestampNs, successorTimestampNs,
                            frameRate.presentationSourceHz(),
                            activeRightUniqueSequence,
                            endpointFifoUniqueSequence[successorSlot],
                            activeRightSubmission,
                            endpointFifoSubmission[successorSlot],
                            activeRightCandidateLoss,
                            endpointFifoCandidateLoss[successorSlot],
                            slotLatticeProducer))
                return null;
            leftSequence = activeRightSequence;
            leftTimestampNs = activeRightTimestampNs;
            rightSequence = successorSequence;
            rightTimestampNs = successorTimestampNs;
        } else if (advance != 0) {
            return null;
        }
        if (!transport.hasAdjacentPair(leftSequence, rightSequence)) return null;

        long outputPeriodNs;
        long preparationLeadNs;
        long nextPhysicalPresentationNs;
        try {
            int preparationScans = externalRatePathPriming ?
                    frameRate.candidateGeneratedPanelScansPerOutput() :
                    frameRate.panelScansPerOutput();
            if (preparationScans <= 0) return null;
            outputPeriodNs = Math.multiplyExact(
                    externalPhysicalClock.planningPeriodNs(),
                    (long) preparationScans);
            preparationLeadNs = Math.multiplyExact(outputPeriodNs,
                    prepareSuccessorAfterExactDoubleSynthetic ? 2L : 1L);
            nextPhysicalPresentationNs = Math.addExact(
                    deadline.contentPresentationTimeNs(), preparationLeadNs);
        } catch (ArithmeticException overflow) {
            return null;
        }
        if (outputPeriodNs <= 0L || nextPhysicalPresentationNs <= 0L)
            return null;
        long targetSourceNs = externalRatePathPriming ?
                AdaptiveFrameRateController.exactMidpointTimestampNs(
                        leftTimestampNs, rightTimestampNs) :
                frameRate.previewBufferedGeneratedTargetSourceNsAfterPendingCommit(
                        nextPhysicalPresentationNs,
                        leftTimestampNs, rightTimestampNs);
        // Exact endpoints use the existing cached-import passthrough. Only a
        // strictly interior sample needs expensive private RIFE preparation.
        if (targetSourceNs <= leftTimestampNs ||
                targetSourceNs >= rightTimestampNs)
            return null;
        return FrameGenerationPreparationRequest.between(
                generatorId, schedulerPresentationEpoch(),
                leftSequence, leftTimestampNs,
                rightSequence, rightTimestampNs,
                targetSourceNs,
                transport.endpointWidth(), transport.endpointHeight(),
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
    }

    private FrameGenerationPreparationRequest deferredExternalPreparation;

    private boolean retryDeferredExternalPreparation() {
        FrameGenerationPreparationRequest request = deferredExternalPreparation;
        if (request == null) return false;
        if (request.presentationEpoch() != schedulerPresentationEpoch() ||
                request.leftSequence() < activeLeftSequence ||
                (request.leftSequence() == activeLeftSequence && activePairSyntheticCommitted)) {
            deferredExternalPreparation = null;
            return false;
        }
        submitExternalGeneratedPreparation(request);
        return true;
    }

    private void registerExternalPreparationCapacityListener() {
        ExternalFrameGenerationTransport registered = externalTransport;
        if (registered == null || !registered.usesAppOwnedPresentation()) return;
        registered.setPreparationCapacityListener(() -> {
            if (closed.get() || externalPresentationFailed ||
                    externalTransport != registered || !externalRatePathActive ||
                    externalLastPlannedPhysicalNs <= 0L ||
                    observedBufferedPresentationEpoch != schedulerPresentationEpoch()) return;
            try {
                if (pendingAppOwnedRequest != null) {
                    // GPU-ready notification is useful precisely when the
                    // selected output was waiting for it. Retry that immutable
                    // request first; its existing deadline/identity checks and
                    // successful-commit path own successor preparation. Never
                    // bypass an unresolved request or replan its slot.
                    retryPendingAppOwnedPresentation();
                    if (pendingAppOwnedRequest != null) return;
                    // Expiration can clear the pending request without a
                    // successful commit to refill future work. Do not lose
                    // this GPU-capacity notification and leave the queue idle
                    // until another display callback. A retry may also have
                    // invalidated the epoch; that cannot authorize refill.
                    if (closed.get() || externalPresentationFailed ||
                            externalTransport != registered || !externalRatePathActive ||
                            externalLastPlannedPhysicalNs <= 0L ||
                            observedBufferedPresentationEpoch != schedulerPresentationEpoch()) return;
                }
                // The previous visible swap is already queued. Continue only
                // immutable future work; transport still captures/waits its GL
                // dependency, and no presentation/credit is committed here.
                if (!retryDeferredExternalPreparation()) prepareExternalLookahead();
            } catch (RuntimeException failure) {
                failRuntimePresentation("External preparation refill failed", failure);
            }
        });
    }

    private void submitExternalGeneratedPreparation(
            FrameGenerationPreparationRequest request) {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null || request == null) return;
        FrameGenerationPreparationRequest earlier = deferredExternalPreparation;
        if (earlier != null && earlier.presentationEpoch() == schedulerPresentationEpoch() &&
                earlier.leftSequence() >= activeLeftSequence &&
                !(earlier.leftSequence() == activeLeftSequence && activePairSyntheticCommitted) &&
                earlier.leftSequence() < request.leftSequence()) {
            // Preserve exact earlier identity across ordinary display-driven
            // submissions too, not only the capacity callback. The existing
            // lookahead walk can revisit later work after this is admitted.
            request = earlier;
        }
        ExternalFrameGenerationTransport.PreparationResult result =
                transport.prepare(request);
        if (result != ExternalFrameGenerationTransport.PreparationResult.SUBMITTED &&
                result !=
                        ExternalFrameGenerationTransport.PreparationResult.ALREADY_READY &&
                result != ExternalFrameGenerationTransport.PreparationResult.NOT_READY)
            throw new IllegalStateException(
                "external transport returned an unknown preparation result");
        // Do not bypass the immediate requested midpoint with farther-future
        // work when it failed admission. A later pair occupying a free bridge
        // cannot satisfy the earlier immutable presentation identity.
        if (result == ExternalFrameGenerationTransport.PreparationResult.NOT_READY) {
            deferredExternalPreparation = request;
            return;
        }
        deferredExternalPreparation = null;
        prepareExternalLookahead();
    }

    /** Prepare immutable future midpoints without consuming or retiming the FIFO. */
    private int externalLookaheadPairCount() {
        if (externalTransport == null) return 0;
        // Candidate 66.7 ms inference lead, rounded to whole source intervals.
        // This remains qualification policy until physical-device acceptance.
        int sourceIntervals = Math.max(1, (int) Math.ceil(frameRate.presentationSourceHz() / 15.0));
        return Math.min(4, Math.min(sourceIntervals, externalTransport.preparationLookaheadPairs()));
    }

    private void prepareExternalLookahead() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null || !transport.usesAppOwnedPresentation() ||
                (!externalRatePathActive && !externalRatePathPriming && !externalRatePathOutputPriming) ||
                activeRightSequence <= 0L) return;
        int sourceFps = externalRatePathActive ? frameRate.presentationSourceFps() : frameRate.candidateGeneratedSourceFps();
        int outputFps = externalRatePathActive ? frameRate.outputFps() : frameRate.candidateGeneratedOutputFps();
        if (sourceFps <= 0 || outputFps != 2 * sourceFps) return;
        int limit = Math.min(endpointFifoCount, externalLookaheadPairCount());
        long left = activeRightSequence, leftNs = activeRightTimestampNs;
        long unique = activeRightUniqueSequence, loss = activeRightCandidateLoss;
        int submission = activeRightSubmission;
        for (int offset = 0; offset < limit; offset++) {
            int slot = endpointFifoSlot(offset);
            long right = endpointFifoSequence[slot], rightNs = endpointFifoTimestampNs[slot];
            if (right != left + 1L || !AdaptiveFrameRateController.endpointSpanContinuous(
                    leftNs, rightNs, frameRate.presentationSourceHz(), unique,
                    endpointFifoUniqueSequence[slot], submission, endpointFifoSubmission[slot],
                    loss, endpointFifoCandidateLoss[slot], slotLatticeProducer) ||
                    !transport.hasAdjacentPair(left, right)) return;
            FrameGenerationPreparationRequest future = FrameGenerationPreparationRequest.between(
                    generatorId, schedulerPresentationEpoch(), left, leftNs, right, rightNs,
                    AdaptiveFrameRateController.exactMidpointTimestampNs(leftNs, rightNs),
                    transport.endpointWidth(), transport.endpointHeight(),
                    FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
            if (transport.prepare(future) == ExternalFrameGenerationTransport.PreparationResult.NOT_READY) return;
            left = right; leftNs = rightNs; unique = endpointFifoUniqueSequence[slot];
            submission = endpointFifoSubmission[slot]; loss = endpointFifoCandidateLoss[slot];
        }
    }

    /**
     * Presents one external image through EmuFusion's own EGL window.
     *
     * <p>The backend may bind only a completed private RGBA8 image. It never
     * sees the output Surface and cannot commit scheduler or delivered-FPS
     * state. The controller decision, EGL timestamp, swap, frame-timestamp ID,
     * endpoint advance, and physical accounting remain in this method.</p>
     */
    private FrameGenerationPresentationRequest pendingAppOwnedRequest;
    private FrameGenerationPreparationRequest pendingAppOwnedPreparation;
    private float pendingAppOwnedPhase;
    private FrameGenerationPresentationRequest scheduledAppOwnedRetry;

    private void scheduleAppOwnedRetry() {
        final FrameGenerationPresentationRequest request = pendingAppOwnedRequest;
        if (request == null || scheduledAppOwnedRetry == request ||
                closed.get() || externalPresentationFailed) return;
        scheduledAppOwnedRetry = request;
        if (!handler.postDelayed(() -> {
            if (scheduledAppOwnedRetry == request) scheduledAppOwnedRetry = null;
            if (closed.get() || externalPresentationFailed ||
                    pendingAppOwnedRequest != request) return;
            try {
                retryPendingAppOwnedPresentation();
            } catch (RuntimeException failure) {
                failRuntimePresentation("App-owned output retry failed", failure);
            }
        }, 1L)) {
            scheduledAppOwnedRetry = null;
            throw new IllegalStateException("Renderer owner rejected output retry");
        }
    }

    private boolean retryPendingAppOwnedPresentation() {
        FrameGenerationPresentationRequest request = pendingAppOwnedRequest;
        if (request == null) return false;
        if (request.presentationEpoch() != schedulerPresentationEpoch()) {
            pendingAppOwnedRequest = null;
            pendingAppOwnedPreparation = null;
            return false;
        }
        FrameGenerationPreparationRequest preparation = pendingAppOwnedPreparation;
        long before = frameRate.bufferedPresentationCount();
        try {
            presentAppOwnedExternalBuffered(request,
                    AdaptiveFrameRateController.PRESENT_SYNTHETIC, pendingAppOwnedPhase);
            if (frameRate.bufferedPresentationCount() == before + 1L && preparation != null)
                submitExternalGeneratedPreparation(preparation);
        } catch (RuntimeException failure) {
            frameRate.abortBufferedPresentation();
            invalidateBufferedPairForReprime(false);
            throw failure;
        }
        // Never select/replan or catch up another output in this callback.
        return true;
    }

    private void presentAppOwnedExternalBuffered(
            FrameGenerationPresentationRequest request, int presentation,
            float selectedPhase) {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null || !transport.usesAppOwnedPresentation() ||
                physicalPresentationTracker == null ||
                !physicalPresentationTracker.available())
            throw new IllegalStateException(
                    "app-owned external presentation authority is unavailable");
        boolean generated = request.isGenerated();
        if (generated) {
            if (presentation != AdaptiveFrameRateController.PRESENT_SYNTHETIC ||
                    !externalRatePathActive || !request.hasAdjacentPair() ||
                    !transport.hasAdjacentPair(
                            request.leftSequence(), request.rightSequence()))
                throw new IllegalStateException(
                        "app-owned generated request lacks its exact authorized pair");
        } else if (presentation != AdaptiveFrameRateController.PRESENT_REAL) {
            throw new IllegalStateException(
                    "app-owned endpoint request was not selected REAL");
        }
        int endpointAdvance = frameRate.bufferedEndpointAdvanceAfterPresentation();
        if (frameRate.bufferedOutputCredits() <= 0 ||
                (endpointAdvance != 0 && endpointAdvance != 1) ||
                (endpointAdvance == 1 &&
                        activeRightSequence != activeLeftSequence + 1L))
            throw new IllegalStateException(
                    "app-owned presentation controller state is not committable");
        long presentationEpochBeforeAdvance = schedulerPresentationEpoch();
        if (request.sessionEpoch() != generatorId ||
                request.presentationEpoch() != presentationEpochBeforeAdvance ||
                request.outputWidth() != transport.endpointWidth() ||
                request.outputHeight() != transport.endpointHeight() ||
                request.outputFormat() !=
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalStateException(
                    "app-owned presentation contract identity changed or expired");
        if (System.nanoTime() >= request.hardCompletionDeadlineNs() ||
                (generated && !PhysicalPresentationDeadline.appOwnedSubmissionHasQueueLead(
                        request.desiredPhysicalPresentTimeNs(),
                        frameRate.panelPeriodNs(), System.nanoTime()))) {
            pendingAppOwnedRequest = null;
            pendingAppOwnedPreparation = null;
            ++bufferedSyntheticNotReadyCount;
            frameRate.dropBufferedPresentationSlot();
            return;
        }
        if (appOwnedPhysicalPending.size() >= 64)
            throw new IllegalStateException(
                    "app-owned physical presentation ledger is full");
        if (!externalPhysicalSlotAvailable(request, frameRate.panelPeriodNs())) {
            pendingAppOwnedRequest = null;
            pendingAppOwnedPreparation = null;
            ++externalPhysicalSlotRejectedCount;
            ++bufferedSyntheticNotReadyCount;
            Log.w(TAG, "App-owned physical slot already reserved; slot dropped" +
                    " generator=" + generatorId +
                    " desiredNs=" + request.desiredPhysicalPresentTimeNs() +
                    " lastSubmittedNs=" + externalLastPlannedPhysicalNs);
            frameRate.dropBufferedPresentationSlot();
            return;
        }

        ExternalFrameGenerationTransport.AppOwnedOutput generatedOutput = null;
        long bindStartedNs = generated ? System.nanoTime() : 0L;
        if (generated) {
            generatedOutput = transport.bindAppOwnedOutput(
                    request, externalGeneratedTexture);
            if (generatedOutput == null) {
                // Retain the exact selected request/decision until a later
                // callback succeeds or its original deadline expires.
                scheduleAppOwnedRetry();
                return;
            }
        }
        long bindWallNs = generated ?
                Math.max(1L, System.nanoTime() - bindStartedNs) : 1L;
        // A ready image does not renew its display slot. Binding may itself
        // consume the predecessor-scan reserve (Thor frame 1340); never turn
        // that into a knowingly late swap or count it as a successful output.
        if (generated && !PhysicalPresentationDeadline.appOwnedSubmissionHasQueueLead(
                request.desiredPhysicalPresentTimeNs(),
                frameRate.panelPeriodNs(), System.nanoTime())) {
            if (generatedOutput != null)
                transport.releaseAppOwnedOutput(generatedOutput, false);
            pendingAppOwnedRequest = null;
            pendingAppOwnedPreparation = null;
            ++bufferedSyntheticNotReadyCount;
            frameRate.dropBufferedPresentationSlot();
            return;
        }
        boolean swapSucceeded = false;
        boolean trackerPrepared = false;
        long frameId = 0L;
        int physicalScansPerOutput = appOwnedPhysicalScansPerOutput();
        long physicalPanelPeriodNs = frameRate.panelPeriodNs();
        if (physicalScansPerOutput <= 0 || physicalPanelPeriodNs <= 0L)
            throw new IllegalStateException(
                    "app-owned physical cadence identity is unavailable");
        long submissionStartedNs = bindStartedNs > 0L ?
                bindStartedNs : System.nanoTime();
        long swapStartedNs = System.nanoTime();
        try {
            if (generated && !midpointPairBudget.admit(request))
                throw new IllegalStateException("app-owned midpoint admission rejected");
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
            GLES20.glClearColor(0f, 0f, 0f, 1f);
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
            setPresentationViewport();
            if (generated) {
                drawExternalGeneratedTexture(generatedOutput.textureId > 0 ?
                        generatedOutput.textureId : externalGeneratedTexture);
            } else {
                drawTexture2d(historyTextures[selectedPhase >= 1f ?
                        currentIndex : previousIndex]);
            }
            if (Build.VERSION.SDK_INT >= 18 &&
                    (request.driverDesiredPresentTimeNs() <= 0L ||
                            !EGLExt.eglPresentationTimeANDROID(
                                    eglDisplay, eglSurface,
                                    request.driverDesiredPresentTimeNs())))
                fail("eglPresentationTimeANDROID(app-owned)");
            trackerPrepared = physicalPresentationTracker.prepareFrame();
            frameId = physicalPresentationTracker.preparedFrameId();
            if (!trackerPrepared || frameId <= 0L)
                throw new IllegalStateException(
                        "app-owned swap has no physical frame ID");
            beginFullImageCapture(generated, frameId, selectedPhase);
            if (!EGL14.eglSwapBuffers(eglDisplay, eglSurface)) {
                physicalPresentationTracker.cancelPrepared();
                trackerPrepared = false;
                fail("eglSwapBuffers(app-owned)");
            }
            swapSucceeded = true;
            if (!physicalPresentationTracker.commitPrepared(
                    physicalScansPerOutput, physicalPanelPeriodNs))
                throw new IllegalStateException(
                        "app-owned physical frame-ID commit failed");
            trackerPrepared = false;
            long swapCompletedNs = System.nanoTime();
            appOwnedPhysicalPending.addLast(new AppOwnedPhysicalPending(
                    frameId, request, generatedOutput, bindWallNs,
                    Math.max(1L, swapCompletedNs - swapStartedNs),
                    submissionStartedNs, swapStartedNs, swapCompletedNs,
                    physicalScansPerOutput, physicalPanelPeriodNs));
            ++appOwnedExternalSubmittedCount;
            if (externalAppOwnedActivationFirstSwapPending)
                externalAppOwnedActivationFirstSwapPending = false;
            // Image-only qualification records the exact displayed generated
            // buffer and retained endpoints, never a replacement interpolation.
            finishFullImageCapture(true);
        } finally {
            if (!swapSucceeded) finishFullImageCapture(false);
            if (trackerPrepared) physicalPresentationTracker.cancelPrepared();
            if (generatedOutput != null)
                transport.releaseAppOwnedOutput(generatedOutput, swapSucceeded);
        }

        if (!outputFrameRateReassertedAfterSwap) {
            outputFrameRateReassertedAfterSwap = true;
            requestOutputFrameRate("first-successful-app-owned-swap");
        }
        recordExternalPhysicalSlot(request);
        frameRate.commitBufferedPresentation(true);
        pendingAppOwnedRequest = null;
        pendingAppOwnedPreparation = null;
        if (generated) {
            ++generatedPresents;
            ++bufferedSyntheticSelectedCount;
            activePairSyntheticCommitted = true;
            bufferedLastSelectedSyntheticPair = activeLeftSequence;
            phaseDiagSum += request.phase();
            phaseDiagMin = Math.min(phaseDiagMin, (float) request.phase());
            phaseDiagMax = Math.max(phaseDiagMax, (float) request.phase());
            ++phaseDiagCount;
            phaseDiagSpanSumNs +=
                    request.rightTimestampNs() - request.leftTimestampNs();
        }
        ++presents;
        commitBufferedEndpointAdvance(presentation, endpointAdvance);
        if (activeLeftSequence > 0L)
            transport.releaseBefore(activeLeftSequence);
        refreshProofEvidencePresentationEpoch();
        if (schedulerPresentationEpoch() != presentationEpochBeforeAdvance)
            resetHealthWindowAfterStreamChange();
    }

    /**
     * Exact panel occupancy for an app-owned EGL swap.
     *
     * <p>The generated-path accessor is deliberately zero while EmuFusion is
     * still presenting Direct endpoints during private-pipeline warm-up. A
     * Direct endpoint nevertheless has a physical cadence identity: the
     * nearest positive panel divisor of the currently selected source clock.
     * Snapshot this value once before the swap so native commit and the Java
     * join row can never observe different controller states.</p>
     */
    private static boolean directExternalSubmissionWindowOpen(
            long targetNs, long nowNs, long periodNs, int scans) {
        if (nowNs < 0L || targetNs <= nowNs || periodNs <= 0L || scans <= 0)
            return false;
        long lead = PhysicalPresentationDeadline.THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS;
        if (periodNs > (Long.MAX_VALUE - lead) / scans) return false;
        return targetNs - nowNs <= lead + periodNs * scans;
    }

    private int appOwnedPhysicalScansPerOutput() {
        int generatedScans = frameRate.panelScansPerOutput();
        if (generatedScans > 0) return generatedScans;
        double sourceHz = frameRate.presentationSourceHz();
        double panelHz = frameRate.panelHz();
        if (!Double.isFinite(sourceHz) || sourceHz <= 0.0 ||
                !Double.isFinite(panelHz) || panelHz <= 0.0)
            return 1;
        double ratio = panelHz / sourceHz;
        if (!Double.isFinite(ratio) || ratio <= 1.0) return 1;
        return Math.max(1, (int) Math.min(1000L, Math.round(ratio)));
    }

    /**
     * Rejects a previously reserved scan before any backend or EGL ownership.
     * Token IDs identify callback proposals, not distinct physical scans: two
     * different tokens may have the same expected presentation timestamp.
     * Half a scan also excludes tiny target shifts caused by phase reanchors.
     */
    private boolean externalPhysicalSlotAvailable(
            FrameGenerationPresentationRequest request, long panelPeriodNs) {
        long desiredNs = request.desiredPhysicalPresentTimeNs();
        if (desiredNs <= 0L || panelPeriodNs <= 0L ||
                externalLastPlannedPhysicalNs < 0L ||
                externalLastSubmittedCompositorExpectedNs < 0L)
            throw new IllegalStateException("invalid external physical slot identity");
        long minimumSeparationNs = Math.max(1L, panelPeriodNs / 2L);
        if (externalLastPlannedPhysicalNs > 0L &&
                (desiredNs <= externalLastPlannedPhysicalNs ||
                        desiredNs - externalLastPlannedPhysicalNs < minimumSeparationNs))
            return false;
        if (request.hasCompositorFrameTimeline()) {
            long expectedNs = request.compositorExpectedPresentationTimeNs();
            if (expectedNs <= 0L)
                throw new IllegalStateException("invalid compositor physical slot identity");
            if (externalLastSubmittedCompositorExpectedNs > 0L &&
                    (expectedNs <= externalLastSubmittedCompositorExpectedNs ||
                            expectedNs - externalLastSubmittedCompositorExpectedNs <
                                    minimumSeparationNs))
                return false;
        }
        return true;
    }

    /** Called only after accepted submission; proposals do not reserve scans. */
    private void recordExternalPhysicalSlot(
            FrameGenerationPresentationRequest request) {
        externalLastPlannedPhysicalNs = request.desiredPhysicalPresentTimeNs();
        if (request.hasCompositorFrameTimeline())
            externalLastSubmittedCompositorExpectedNs =
                    request.compositorExpectedPresentationTimeNs();
    }

    /** Submits exactly one EmuFusion-selected request to the Vulkan backend. */
    private void presentExternalBuffered(
            FrameGenerationPresentationRequest request, int presentation) {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport == null || !request.hasAdjacentPair() ||
                !transport.hasAdjacentPair(
                        request.leftSequence(), request.rightSequence()))
            throw new IllegalStateException(
                    "external presentation lacks its exact adjacent endpoint pair");
        if (request.isGenerated() &&
                presentation != AdaptiveFrameRateController.PRESENT_SYNTHETIC)
            throw new IllegalStateException(
                    "generated external request was not selected synthetic");
        if (request.isGenerated() && !externalRatePathActive)
            throw new IllegalStateException(
                    "unqualified external rate attempted generated output");
        if (request.isGenerated() &&
                !externalPhysicalClockBootstrap.complete())
            throw new IllegalStateException(
                    "external generation attempted before physical-clock bootstrap");
        if (!request.isGenerated() &&
                presentation != AdaptiveFrameRateController.PRESENT_REAL)
            throw new IllegalStateException(
                    "endpoint external request was not selected real");
        // Endpoint-only Direct rows stay identity-joined and contribute to
        // actual physical cadence, but they do not qualify this backend. A
        // generated path replaces the sentinel with its exact panel divisor
        // after a clean presentation-epoch boundary.
        int scansPerOutput = externalRatePathActive ?
                frameRate.panelScansPerOutput() : 1;
        if (scansPerOutput <= 0)
            throw new IllegalStateException(
                    "external presentation has no exact panel divisor");
        int endpointAdvance = frameRate.bufferedEndpointAdvanceAfterPresentation();
        if (frameRate.bufferedOutputCredits() <= 0 ||
                (endpointAdvance != 0 && endpointAdvance != 1) ||
                (endpointAdvance == 1 &&
                        activeRightSequence != activeLeftSequence + 1L))
            throw new IllegalStateException(
                    "external presentation controller state is not committable");
        if (!externalPresentationLedger.canSubmit())
            throw new IllegalStateException(
                    "external physical-presentation ledger is full");
        long presentationEpochBeforeAdvance = schedulerPresentationEpoch();
        if (presentationEpochBeforeAdvance <= 0L)
            throw new IllegalStateException(
                    "external presentation has no valid scheduler epoch");
        if (request.sessionEpoch() != generatorId ||
                request.presentationEpoch() != presentationEpochBeforeAdvance ||
                request.outputWidth() != transport.endpointWidth() ||
                request.outputHeight() != transport.endpointHeight() ||
                request.outputFormat() !=
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalStateException(
                    "external presentation contract identity changed");
        if (transport.requiresCompositorFrameTimeline() !=
                request.hasCompositorFrameTimeline())
            throw new IllegalStateException(
                    "external presentation timing contract changed");
        // The immutable proposal may expire during otherwise valid preflight.
        // No backend ownership has begun, so consume only this missed output
        // slot, exactly like a zero-wait transport NOT_READY. Keep malformed
        // identity/controller failures above fatal and never move the deadline.
        boolean slotAvailable = externalPhysicalSlotAvailable(
                request, frameRate.panelPeriodNs());
        if (!slotAvailable) {
            ++externalPhysicalSlotRejectedCount;
            Log.w(TAG, "External physical slot already reserved; slot dropped" +
                    " generator=" + generatorId +
                    " desiredNs=" + request.desiredPhysicalPresentTimeNs() +
                    " lastSubmittedNs=" + externalLastPlannedPhysicalNs +
                    " compositorExpectedNs=" +
                            request.compositorExpectedPresentationTimeNs() +
                    " lastCompositorExpectedNs=" +
                            externalLastSubmittedCompositorExpectedNs);
        }
        ExternalFrameGenerationTransport.EnqueueResult result =
                !slotAvailable || System.nanoTime() >= request.hardCompletionDeadlineNs()
                        ? ExternalFrameGenerationTransport.EnqueueResult.NOT_READY
                        : transport.enqueue(request);
        if (result == ExternalFrameGenerationTransport.EnqueueResult.DEFERRED) {
            ++externalPrequeueDeferredCount;
            if (externalPrequeueDeferredCount == 1L)
                Log.i(TAG, "External presentation deferred before release gate" +
                        " generator=" + generatorId +
                        " generated=" + (request.isGenerated() ? 1 : 0) +
                        " left=" + request.leftSequence() +
                        " right=" + request.rightSequence() +
                        " desiredNs=" +
                                request.desiredPhysicalPresentTimeNs() +
                        " hardDeadlineNs=" +
                                request.hardCompletionDeadlineNs());
            frameRate.deferBufferedPresentationSlot();
            return;
        }
        if (result == ExternalFrameGenerationTransport.EnqueueResult.NOT_READY) {
            // The transport contract defines zero-wait NOT_READY as one
            // ordinary output-slot underrun. It is not a backend/session
            // failure and must never be retried or caught up. The controller
            // has already consumed this divisor-lattice slot; clear only its
            // uncommitted decision and retain the exact adjacent endpoint pair
            // for a normally paced later slot. Destroying the pair here made
            // one transient native-busy result trigger an endless re-prime
            // loop (physical r49: stable 40 FPS collapsed to ~8 FPS).
            // No presentation, generated-frame, credit, or endpoint-advance
            // counter is committed here.
            ++bufferedSyntheticNotReadyCount;
            Log.w(TAG, "External presentation not ready; slot dropped" +
                    " generator=" + generatorId +
                    " generated=" + (request.isGenerated() ? 1 : 0) +
                    " left=" + request.leftSequence() +
                    " right=" + request.rightSequence() +
                    " desiredNs=" + request.desiredPhysicalPresentTimeNs() +
                    " hardDeadlineNs=" + request.hardCompletionDeadlineNs() +
                    " nowNs=" + System.nanoTime() +
                    " pendingPhysical=" +
                            transport.pendingPhysicalPresentationCount());
            frameRate.dropBufferedPresentationSlot();
            return;
        }
        if (result != ExternalFrameGenerationTransport.EnqueueResult.SUBMITTED)
            throw new IllegalStateException(
                    "external presentation transport returned an unknown result");
        // enqueue is synchronous and this renderer is serialized. The earlier
        // preflight forbids reused pairs before submission; spend only after
        // SUBMITTED so a proven no-op deferral cannot freeze the next callback.
        if (request.isGenerated() && !midpointPairBudget.admit(request))
            throw new IllegalStateException("submitted midpoint admission changed");

        if (request.hasCompositorFrameTimeline())
            ++compositorFrameTimelineCommitted;

        recordExternalPhysicalSlot(request);
        if (externalRatePathActive &&
                !transport.requiresCompositorFrameTimeline() &&
                externalDirectOutputPhaseAnchorNs == 0L)
            externalDirectOutputPhaseAnchorNs =
                    request.desiredPhysicalPresentTimeNs();
        frameRate.commitBufferedPresentation(true);
        externalPresentationLedger.submit(request, scansPerOutput);

        if (request.isGenerated()) {
            ++bufferedSyntheticSelectedCount;
            activePairSyntheticCommitted = true;
            bufferedLastSelectedSyntheticPair = activeLeftSequence;
            phaseDiagSum += request.phase();
            phaseDiagMin = Math.min(phaseDiagMin, (float) request.phase());
            phaseDiagMax = Math.max(phaseDiagMax, (float) request.phase());
            ++phaseDiagCount;
            phaseDiagSpanSumNs +=
                    request.rightTimestampNs() - request.leftTimestampNs();
        }

        commitBufferedEndpointAdvance(presentation, endpointAdvance);
        if (activeLeftSequence > 0L)
            transport.releaseBefore(activeLeftSequence);
        prepareExternalRealPairIfPossible();
        long presentationEpochAfterAdvance = schedulerPresentationEpoch();
        refreshProofEvidencePresentationEpoch();
        if (presentationEpochAfterAdvance != presentationEpochBeforeAdvance)
            resetHealthWindowAfterStreamChange();
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
        denseCadenceFailureWindows = 0;
        generationTargetFailureWindows = 0;
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
        // The first dense window is cut before any present has bound the
        // evidence epoch (run n64-tier4: seq 1 carried epoch 7 / evidence 0
        // and the harness parser rejected the entire log).  Bind it here so
        // every emitted record labels the epoch it actually describes.
        if (schedulerPresentationEpoch() > 0L)
            refreshProofEvidencePresentationEpoch();
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
                " externalEndpointAdmissionRejected=" + externalEndpointAdmissionRejected +
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
        // Diagnostic only, own tag-line so the strict HEALTH grammar is
        // untouched: melonDS's primary never left 1x on nds1/nds2
        // (2026-08-17) and the health record cannot distinguish which
        // acquisition precondition is starving.
        if (!frameRate.tierAcquiredForDiagnostics())
            Log.i(TAG, "Tier acquisition diag generator=" + generatorId +
                    " producerSamples=" + frameRate.producerSamplesForDiagnostics() +
                    " decisionPeriods=" + frameRate.decisionPeriodsForDiagnostics() +
                    " producerHz=" + String.format(java.util.Locale.US, "%.2f",
                            frameRate.measuredProducerHz()) +
                    " submissionHz=" + String.format(java.util.Locale.US, "%.2f",
                            frameRate.measuredSubmissionHz()) +
                    " generationAvailable=" + frameRate.generationAvailable() +
                    " swSubmits=" + diagSoftwareSubmits +
                    " hwSubmits=" + diagHardwareSubmits +
                    " uniqueVerdicts=" + diagUniqueVerdicts +
                    " duplicateVerdicts=" + diagDuplicateVerdicts +
                    " lastSignatureByteSum=" + diagLastSignatureByteSum +
                    " lastSignatureChangedPixels=" + diagLastChangedPixels);
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
                " denseGpuBudgetUs=" + denseGpuBudgetUs() +
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
        // The split base/extension records already sit close to logcat's hard
        // payload limit. Keep exact rational clocks in a third, strictly
        // joined schema44 record rather than risking silent tail truncation.
        String rationalClock = "Presentation health rational-clock" + key +
                " proofEvidencePresentationEpoch=" +
                        proofEvidencePresentationEpoch +
                " rClock=" + Math.max(0L, Math.round(
                        frameRate.presentationSourceHz() * 1000.0)) + "/" +
                        Math.max(0L, Math.round(
                                frameRate.targetOutputHz() * 1000.0)) + "/" +
                        Math.max(0L, Math.round(
                                frameRate.panelHz() * 1000.0)) + "/" +
                        frameRate.panelScansPerOutput() + "/" +
                        (frameRate.uniformOutputQualified() ? 1 : 0) + "/" +
                        Math.max(0L, Math.round(
                                windowPresents * 1_000_000.0 /
                                        Math.max(1L, windowElapsedMs))) + "/" +
                        (frameRate.usesAuthoritativeSourceRate() ?
                                "auth" : "pts");
        // Validate the complete joined transaction before emitting its first
        // line. A too-large extension must not leave an otherwise valid-looking
        // orphan base record for the verifier or runtime collector.
        validateBoundedHealth(base);
        validateBoundedHealth(extension);
        validateBoundedHealth(rationalClock);
        logBoundedHealth(base);
        logBoundedHealth(extension);
        logBoundedHealth(rationalClock);
        // Lifetime render/submission admissions survive scheduler resets.
        // No-op deferrals spend nothing. This is not a physical-present count.
        logBoundedHealth("Midpoint admission health" + key +
                " maxMultiplier=2 admittedAttempts=" + midpointPairBudget.admitted() +
                " rejectedAttempts=" + midpointPairBudget.rejected() +
                " omittedMidpoints=" + frameRate.bufferedMidpointOmittedCount() +
                " lastRejection=" + midpointPairBudget.lastRejection());
        logDenseGpuAdaptation(key);
        logDenseTrajectoryDiagnosis(key);
    }

    private void logDenseGpuAdaptation(String key) {
        String record = "Dense GPU adaptation health" + key +
                " workLevel=" + denseGpuAdaptation.workLevel() +
                " disabled=" + (denseGpuAdaptation.generationDisabled() ? 1 : 0) +
                " completeEstimatorAndOwnWarpPairs=" + denseGpuCompletePairs +
                " pendingPairs=" + denseGpuPairLedger.pendingPairCount() +
                " retiredWithoutWarp=" + denseGpuPairLedger.unpairedEstimateCount() +
                " completeGpuTotalUs=" + denseGpuCompleteTotalUs +
                " completeGpuMaxUs=" + denseGpuCompleteMaxUs +
                " shaderBudgetUs=" + denseGpuBudgetUs() +
                " physicalMarginVerifiedPairs=" + denseGpuPhysicalVerifiedPairs +
                " physicalMarginUnknownPairs=" + denseGpuPhysicalUnknownPairs +
                " physicalMarginMarginalPairs=" + denseGpuPhysicalMarginalPairs +
                " physicalDeadlineMisses=" + denseGpuPhysicalDeadlineMisses +
                " physicalUnboundEvents=" + denseGpuPhysicalUnboundEvents +
                " physicalPending=" + denseGpuHeadroom.pendingCount() +
                " readyTimestampSupportedMask=" + denseGpuReadyTimestampSupportedMask +
                " lastAppReadyMarginNs=" + denseGpuPhysicalLastAppMarginNs +
                " lastCompositorReadyMarginNs=" + denseGpuPhysicalLastCompositorMarginNs +
                " physicalHeadroomUnknownPairs=" + denseGpuAdaptation.physicalHeadroomUnknownPairs() +
                " consecutiveHealthyPairs=" + denseGpuAdaptation.consecutiveHealthyPairs() +
                " failures=" + denseGpuAdaptation.failureCount() +
                " minimumWorkFailures=" + denseGpuAdaptation.failuresAtMinimum() +
                " overloadFailures=" + denseGpuAdaptation.failureCount(
                        GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET) +
                " missingTimers=" + denseGpuAdaptation.failureCount(
                        GpuWorkAdaptationPolicy.Failure.TIMER_MISSING) +
                " invalidTimers=" + denseGpuAdaptation.failureCount(
                        GpuWorkAdaptationPolicy.Failure.TIMER_INVALID) +
                " disjointTimers=" + denseGpuAdaptation.failureCount(
                        GpuWorkAdaptationPolicy.Failure.TIMER_DISJOINT) +
                " reductions=" + denseGpuAdaptation.reductionCount() +
                " restorations=" + denseGpuAdaptation.restorationCount() +
                " disableTransitions=" + denseGpuAdaptation.disableTransitionCount() +
                " evidenceEpochs=" + denseGpuAdaptation.evidenceEpochCount();
        logBoundedHealth(record);
    }

    private void logDenseTrajectoryDiagnosis(String key) {
        if (!densePyramidEnabled || denseTrajectorySamples == 0L) return;
        String record = "Dense flow trajectory diagnostic" + key +
                " proofEvidencePresentationEpoch=" +
                        proofEvidencePresentationEpoch +
                " samples=" + denseTrajectorySamples +
                " cells=" + denseTrajectoryCells +
                " changedCells=" + denseTrajectoryChangedCells +
                " changedAnyValidCells=" +
                        denseTrajectoryChangedAnyValidCells +
                " changedAnyMovingValidCells=" +
                        denseTrajectoryChangedAnyMovingValidCells +
                " changedBothMovingValidCells=" +
                        denseTrajectoryChangedBothMovingValidCells +
                " changedTiles=" + denseTrajectoryChangedTiles +
                " changedMovingOwnedTiles=" +
                        denseTrajectoryChangedMovingOwnedTiles +
                " errors=" + denseTrajectoryErrors +
                denseTrajectoryDirectionTelemetry("Backward", 0) +
                denseTrajectoryDirectionTelemetry("Forward", 1);
        validateBoundedHealth(record);
        Log.i(TAG, record);
    }

    private String denseTrajectoryDirectionTelemetry(String name,
                                                       int direction) {
        return " " + name + "ValidCells=" +
                denseTrajectoryValidCells[direction] +
                " " + name + "MovingValidCells=" +
                denseTrajectoryMovingValidCells[direction] +
                " " + name + "StrongMovingValidCells=" +
                denseTrajectoryStrongMovingValidCells[direction] +
                " " + name + "ChangedValidCells=" +
                denseTrajectoryChangedValidCells[direction] +
                " " + name + "ChangedMovingValidCells=" +
                denseTrajectoryChangedMovingValidCells[direction] +
                " " + name + "UnchangedMovingValidCells=" +
                denseTrajectoryUnchangedMovingValidCells[direction];
    }

    private static void validateBoundedHealth(String record) {
        int bytes = record.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
        if (bytes > HEALTH_LOG_MAX_UTF8_BYTES)
            throw new IllegalStateException("split health record exceeds " +
                    HEALTH_LOG_MAX_UTF8_BYTES + " UTF-8 bytes: " + bytes);
    }

    private static void logBoundedHealth(String record) {
        validateBoundedHealth(record);
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
            // Dense generation is the product path; proof mode only decides
            // whether evidence is captured from it (see captureProof). Owner
            // launches previously fell to the legacy v22 estimator because
            // this arm required the shell proof global (2026-09-01 audit).
            denseRequested = densePyramidSwitch.enabled();
        } catch (RuntimeException ignored) {}
        // Defense in depth for alternate secondary-surface owners: only the
        // default/top display is allowed to activate dense interpolation.
        // The lower panel remains direct and cannot consume the top panel's
        // motion-estimation budget.
        if (displayId > 0) {
            denseRequested = false;
            frameRate.setGenerationAvailable(false);
        }
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
        // The dense generator now runs before proof is armed, so a proof
        // transition finds GPU timer queries in flight.  The counter reset
        // below then makes their sequences exceed the zeroed promotion count
        // and the next poll rejects the pyramid for good ("invalid-timer-
        // result", run n64-tier3 2026-09-01).  Rebuild the dense epoch at the
        // transition instead, exactly as the old arm-time start-up did.
        if (denseRequested && !densePyramidUnavailable &&
                requested != qualificationProofEnabled &&
                (wasDense || denseGpuTimer != null)) {
            teardownDenseEpoch(requested ? "proof-armed" : "proof-disarmed");
            frameRate.resetPresentation();
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
        if (nextDense) frameRate.setGenerationAvailable(externalTransport != null ||
                builtinClockAdmissionReady(true, densePyramidUnavailable, displayId,
                        physicalPanelHz()));
        else if (denseRequested) frameRate.setGenerationAvailable(false);
        if (!nextDense && (wasDense || denseGpuTimer != null))
            teardownDenseEpoch("settings-disabled");
        if (requested == qualificationProofEnabled && nextDense == densePyramidEnabled)
            return;
        qualificationProofEnabled = requested;
        densePyramidEnabled = nextDense;
        if (nextDense) {
            // Product generation may start with qualification capture OFF.
            // Establish ownership outside the proof-only counter reset below.
            if (denseGpuHeadroom.evidenceEpoch() == 0L) resetDenseGpuEvidenceEpoch();
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
            // The candidate-lattice and regional-flow telemetry are proof
            // counters too: the verifier requires latticeRegionSamples ==
            // proofSamples * cells in EVERY health record.  They were not
            // reset with proofSamples, so a proof re-arm after a pacing lift
            // (switch-b59, 2026-09-02: proof 1, lattice 14784) failed the
            // whole segment on "telemetry does not cover every proof region".
            latticeRegionSamples = 0;
            latticeBackwardCoherentRegions = 0;
            latticeForwardCoherentRegions = 0;
            latticeBackwardBoundaryRegions = 0;
            latticeForwardBoundaryRegions = 0;
            latticeBackwardCoherentBoundaryRegions = 0;
            latticeForwardCoherentBoundaryRegions = 0;
            latticeBackwardCoherentRegionCount = 0;
            latticeForwardCoherentRegionCount = 0;
            latticeBackwardBoundaryRegionCount = 0;
            latticeForwardBoundaryRegionCount = 0;
            latticeBackwardCoherentBoundaryRegionCount = 0;
            latticeForwardCoherentBoundaryRegionCount = 0;
            latticeBackwardPeakSupport = 0;
            latticeForwardPeakSupport = 0;
            regionalFlowRegionSamples = 0;
            regionalBackwardSupportedRegions = 0;
            regionalForwardSupportedRegions = 0;
            regionalBackwardNeighborRegions = 0;
            regionalForwardNeighborRegions = 0;
            regionalBackwardConstantNeighborRegions = 0;
            regionalForwardConstantNeighborRegions = 0;
            regionalBackwardGradientNeighborRegions = 0;
            regionalForwardGradientNeighborRegions = 0;
            regionalBackwardAcceptedRegions = 0;
            regionalForwardAcceptedRegions = 0;
            regionalBackwardAcceptedBoundaryRegions = 0;
            regionalForwardAcceptedBoundaryRegions = 0;
            regionalBackwardCycleAcceptedRegions = 0;
            regionalForwardCycleAcceptedRegions = 0;
            regionalBackwardAcceptedRegionCount = 0;
            regionalForwardAcceptedRegionCount = 0;
            regionalBackwardAcceptedBoundaryRegionCount = 0;
            regionalForwardAcceptedBoundaryRegionCount = 0;
            regionalBackwardSupportedRegionCount = 0;
            regionalForwardSupportedRegionCount = 0;
            regionalBackwardNeighborRegionCount = 0;
            regionalForwardNeighborRegionCount = 0;
            regionalBackwardConstantNeighborRegionCount = 0;
            regionalForwardConstantNeighborRegionCount = 0;
            regionalBackwardGradientNeighborRegionCount = 0;
            regionalForwardGradientNeighborRegionCount = 0;
            regionalBackwardCycleAcceptedRegionCount = 0;
            regionalForwardCycleAcceptedRegionCount = 0;
            regionalBackwardPeakSupport = 0;
            regionalForwardPeakSupport = 0;
            regionalBackwardPeakConfidence = 0;
            regionalForwardPeakConfidence = 0;
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
            denseGpuCompletePairs = 0;
            resetDenseGpuEvidenceEpoch();
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
            generationTargetFailureWindows = 0;
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
            denseSignatureReady = 0;
            denseSignatureUnavailable = 0;
            denseSignatureMaxQueueAge = 0;
            // The external source classifier exists independently of the
            // qualification-proof switch. Its native query IDs and retained
            // texture candidates are one live ownership epoch; rebasing only
            // the Java sequence here leaves pending native rows with a larger
            // sequence and deterministically reports age=-1. Preserve that
            // classifier across proof-counter resets. The built-in dense arm
            // still starts a fresh classifier with its fresh timer epoch.
            if (externalSignatureTimer == null) {
                denseSignatureSequence = 0L;
                denseSignatureBaselineReady = false;
                clearSignatureCandidates();
            }
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
            denseTrajectorySamples = 0L;
            denseTrajectoryCells = 0L;
            denseTrajectoryChangedCells = 0L;
            denseTrajectoryChangedAnyValidCells = 0L;
            denseTrajectoryChangedAnyMovingValidCells = 0L;
            denseTrajectoryChangedBothMovingValidCells = 0L;
            denseTrajectoryChangedTiles = 0L;
            denseTrajectoryChangedMovingOwnedTiles = 0L;
            denseTrajectoryErrors = 0L;
            java.util.Arrays.fill(denseTrajectoryValidCells, 0L);
            java.util.Arrays.fill(denseTrajectoryMovingValidCells, 0L);
            java.util.Arrays.fill(denseTrajectoryStrongMovingValidCells, 0L);
            java.util.Arrays.fill(denseTrajectoryChangedValidCells, 0L);
            java.util.Arrays.fill(denseTrajectoryChangedMovingValidCells, 0L);
            java.util.Arrays.fill(denseTrajectoryUnchangedMovingValidCells, 0L);
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
                "fragment-v62-parallel-global-seed" :
                denseV27ReducedAnalysisRequested ? "fragment-192x108-v27" :
                "fragment-256x144-v26";
    }

    private long denseSolveTexelsPerPromotion() {
        long oneDirection = 0L;
        for (int level = 0; level < DENSE_LEVELS; ++level)
            oneDirection += (long) denseLevelWidths[level] * denseLevelHeights[level] *
                    DENSE_LEVEL_ITERATIONS[level];
        long refinement = denseV28ReducedAnalysisRequested ?
                2L * denseLevelWidths[0] * denseLevelHeights[0] : 0L;
        return oneDirection * 2L + refinement;
    }

    private int densePassesPerPromotion() {
        return DENSE_BASE_PASSES_PER_PROMOTION +
                (denseV28ReducedAnalysisRequested ?
                        DENSE_RECIPROCAL_REFINEMENT_PASSES +
                                DENSE_GLOBAL_SEED_PASSES : 0);
    }

    private long denseTotalTexelsPerPromotion() {
        long pyramid = 2L * ((long) denseLevelWidths[1] * denseLevelHeights[1] +
                (long) denseLevelWidths[2] * denseLevelHeights[2]);
        long validation = 2L * denseLevelWidths[0] * denseLevelHeights[0];
        long globalSeed = denseV28ReducedAnalysisRequested ? 216L : 0L;
        return denseSolveTexelsPerPromotion() + pyramid + validation + globalSeed;
    }

    private int activeBackwardFlow() {
        return densePyramidEnabled ? denseValidatedTextures[0] : flowTextures[2];
    }

    private int activeForwardFlow() {
        return densePyramidEnabled ? denseValidatedTextures[1] : reverseFlowTextures[2];
    }

    private float activeFlowLimitPixels() {
        float limit = flowLimitPixels(historyWidth, historyHeight);
        return densePyramidEnabled ? Math.min(denseMaxFlowPixels(), limit) : limit;
    }

    // Recording-side evidence (2026-09-03): while the marker file exists,
    // every presented SYNTHETIC frame carries a magenta square in the window's
    // top-left corner and real frames carry nothing, so a panel capture can
    // label real/generated frames without trusting any log.  Off by default.
    private static final java.io.File PROOF_MARK_MARKER =
            new java.io.File("/data/local/tmp/lucent-proofmark");
    private static final int PROOF_MARK_PX = 32;
    private boolean proofMarkEnabled;
    private int proofMarkPollCountdown;

    private void drawProofMark() {
        if (--proofMarkPollCountdown <= 0) {
            proofMarkPollCountdown = 120;
            proofMarkEnabled = PROOF_MARK_MARKER.exists();
        }
        if (!proofMarkEnabled) return;
        GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
        GLES20.glScissor(0, Math.max(0, outputHeight - PROOF_MARK_PX),
                PROOF_MARK_PX, PROOF_MARK_PX);
        GLES20.glClearColor(1f, 0f, 1f, 1f);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
        GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
        GLES20.glClearColor(0f, 0f, 0f, 1f);
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
        // The dense global seeds are 1x1 Q8.8 textures; sampling them keeps
        // the presentation free of readbacks (a per-pair glReadPixels is a
        // GPU sync point, and the dense timer ring fails closed on stalls).
        boolean seedsReady = densePyramidEnabled && denseV28ReducedAnalysisRequested &&
                denseGlobalSeedTextures[0] != 0;
        bindTexture(interpolateProgram, "uDenseSeedBackwardTex",
                seedsReady ? denseGlobalSeedTextures[0] : historyTextures[currentIndex], 6);
        bindTexture(interpolateProgram, "uDenseSeedForwardTex",
                seedsReady ? denseGlobalSeedTextures[1] : historyTextures[currentIndex], 7);
        uniform2(interpolateProgram, "uDenseSeedSourceSize",
                Math.max(1f, historyWidth), Math.max(1f, historyHeight));
        GLES20.glUniform1f(GLES20.glGetUniformLocation(interpolateProgram,
                "uDenseSeedEnabled"), seedsReady ? 1f : 0f);
        // The cut texture needs a ninth sampler unit; GLES2 only guarantees
        // eight, so the hold is disabled (never mis-bound) on smaller GPUs.
        if (maxFragmentTextureUnits == 0) {
            int[] units = new int[1];
            GLES20.glGetIntegerv(GLES20.GL_MAX_TEXTURE_IMAGE_UNITS, units, 0);
            maxFragmentTextureUnits = Math.max(1, units[0]);
        }
        boolean cutReady = seedsReady && maxFragmentTextureUnits >= 9 &&
                denseGlobalCutTextures[0] != 0;
        bindTexture(interpolateProgram, "uDenseCutTex",
                cutReady ? denseGlobalCutTextures[0] : historyTextures[currentIndex],
                cutReady ? 8 : 7);
        GLES20.glUniform1f(GLES20.glGetUniformLocation(interpolateProgram,
                "uDenseCutEnabled"), cutReady ? 1f : 0f);
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

    private FullResolutionFrameReadback fullImageCapture;
    private int fullImageTexture, fullImageFramebuffer;
    private long fullImageEpoch, fullImageFrameId;
    private String fullImageMetadata;
    private boolean fullImageQueued, fullImageAttempted;

    /** Explicit image-only diagnostic. Its timings are instrumented, never a pacing pass. */
    private void beginFullImageCapture(boolean synthetic, long frameId, float phase) {
        // The explicit one-shot marker is sufficient authority for image
        // diagnostics. Do not arm the separate proof mode: that mode resets
        // epochs and can change the rendering workload we intend to inspect.
        if (fullImageCapture != null || fullImageAttempted || !synthetic ||
                frameId <= 0 ||
                !(new java.io.File("/data/local/tmp/emufusion-full-frame-capture").exists() ||
                  new java.io.File(android.os.Environment.getExternalStorageDirectory(),
                          "Android/data/com.thorium.preview/files/emufusion-full-frame-capture").exists())) return;
        fullImageAttempted = true;
        Log.i(TAG, "Full image capture armed generator=" + generatorId + " frameId=" + frameId);
        try {
            fullImageEpoch = schedulerPresentationEpoch();
            fullImageFrameId = frameId;
            int[] capturedViewport = new int[4];
            GLES20.glGetIntegerv(GLES20.GL_VIEWPORT, capturedViewport, 0);
            fullImageCapture = new FullResolutionFrameReadback(
                    FullResolutionFrameReadback.backendForContext(actualEglContextMajor), outputWidth, outputHeight,
                    fullImageEpoch, frameId);
            int[] names = new int[1];
            GLES20.glGenTextures(1, names, 0);
            fullImageTexture = names[0];
            allocateTexture(fullImageTexture, outputWidth, outputHeight);
            GLES20.glGenFramebuffers(1, names, 0);
            fullImageFramebuffer = names[0];
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            fullImageCapture.enqueue(presents + 1L); // Exact visible G, not a re-render.
            fullImageMetadata = "generator=" + generatorId + "\nepoch=" + fullImageEpoch +
                    "\nphysicalFrameId=" + frameId + "\nleft=" + activeLeftSequence +
                    "\nright=" + activeRightSequence + "\nleftNs=" + activeLeftTimestampNs +
                    "\nrightNs=" + activeRightTimestampNs + "\nphase=" + phase +
                    "\nwidth=" + outputWidth + "\nheight=" + outputHeight +
                    "\nviewport=" + java.util.Arrays.toString(capturedViewport) +
                    "\nformat=RGBA8-bottom-up\ninstrumentedTiming=true\n" +
                    "readback=" + FullResolutionFrameReadback.readbackName(actualEglContextMajor) + "\n" +
                    "presentationOutcome=unresolved-use-physical-frame-log\n";
            fullImageQueued = true;
        } catch (RuntimeException failure) {
            Log.w(TAG, "Full image capture unavailable", failure);
            discardFullImageCapture();
        }
    }

    private void finishFullImageCapture(boolean committed) {
        if (fullImageCapture == null) return;
        boolean captureScissorWasEnabled = GLES20.glIsEnabled(GLES20.GL_SCISSOR_TEST);
        try {
            if (fullImageQueued) {
                if (!committed) { discardFullImageCapture(); return; }
                GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
                GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, fullImageFramebuffer);
                GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,
                        GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D, fullImageTexture, 0);
                if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) !=
                        GLES20.GL_FRAMEBUFFER_COMPLETE)
                    throw new IllegalStateException("full image framebuffer incomplete");
                for (int endpoint = 0; endpoint < 2; ++endpoint) {
                    GLES20.glViewport(0, 0, outputWidth, outputHeight);
                    GLES20.glClearColor(0f, 0f, 0f, 1f);
                    GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
                    setPresentationViewport();
                    // References must be actual retained source images, not
                    // endpoint-phase reconstructions by the shader under test.
                    drawTexture2d(historyTextures[endpoint == 0 ?
                            previousIndex : currentIndex]);
                    fullImageCapture.enqueue(presents + 1L);
                }
                fullImageQueued = false;
            }
            final byte[][] images = fullImageCapture.poll(presents + 1L,
                    schedulerPresentationEpoch(), fullImageFrameId);
            if (images == null) {
                if (fullImageCapture.isClosed()) {
                    Log.w(TAG, "Full image capture discarded before readback completed" +
                            " frameId=" + fullImageFrameId + " captureEpoch=" + fullImageEpoch +
                            " currentEpoch=" + schedulerPresentationEpoch());
                    discardFullImageCapture();
                }
                return;
            }
            final String metadata = fullImageMetadata;
            final String name = "capture-" + generatorId + "-" + fullImageFrameId;
            discardFullImageCapture();
            Thread writer = new Thread(() -> {
                try {
                    java.io.File directory = new java.io.File(
                            new java.io.File(android.os.Environment.getExternalStorageDirectory(),
                                    "Android/data/com.thorium.preview/files/full-frame-capture"), name);
                    if (!directory.mkdirs()) throw new java.io.IOException("capture directory exists/unavailable");
                    String[] labels = {"generated.rgba", "left.rgba", "right.rgba"};
                    for (int i = 0; i < images.length; ++i)
                        try (java.io.FileOutputStream out = new java.io.FileOutputStream(
                                new java.io.File(directory, labels[i]))) { out.write(images[i]); }
                    try (java.io.FileOutputStream out = new java.io.FileOutputStream(
                            new java.io.File(directory, "metadata.txt"))) {
                        out.write(metadata.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                    }
                    Log.i(TAG, "Full image triplet exported " + directory);
                } catch (java.io.IOException failure) { Log.w(TAG, "Full image export failed", failure); }
            }, "EmuFusion-image-export");
            writer.setDaemon(true);
            writer.start();
        } catch (RuntimeException failure) {
            Log.w(TAG, "Full image capture failed", failure);
            discardFullImageCapture();
        } finally {
            if (captureScissorWasEnabled) GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
            else GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, outputWidth, outputHeight);
        }
    }

    private void discardFullImageCapture() {
        if (fullImageCapture != null) fullImageCapture.close();
        fullImageCapture = null;
        fullImageQueued = false;
        if (fullImageTexture != 0) GLES20.glDeleteTextures(1, new int[] {fullImageTexture}, 0);
        if (fullImageFramebuffer != 0) GLES20.glDeleteFramebuffers(1, new int[] {fullImageFramebuffer}, 0);
        fullImageTexture = fullImageFramebuffer = 0;
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
        try {
            // Diagnostic-only CPU accounting over bytes already delivered by
            // the asynchronous atlas. A diagnosis failure must never reject
            // an otherwise valid generated frame or alter qualification.
            accumulateDenseTrajectoryDiagnosis(denseBackward, denseForward);
        } catch (RuntimeException diagnosticFailure) {
            ++denseTrajectoryErrors;
            Log.w(TAG, "Dense flow trajectory diagnosis unavailable generator=" +
                    generatorId, diagnosticFailure);
        }
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

    private void accumulateDenseTrajectoryDiagnosis(byte[] backward,
                                                      byte[] forward) {
        DenseFlowTrajectoryDiagnostics.Sample sample =
                DenseFlowTrajectoryDiagnostics.analyze(proofPrevious,
                        proofCurrent, backward, forward, PROOF_WIDTH,
                        PROOF_HEIGHT);
        ++denseTrajectorySamples;
        denseTrajectoryCells += sample.cells;
        denseTrajectoryChangedCells += sample.changedCells;
        denseTrajectoryChangedAnyValidCells += sample.changedAnyValidCells;
        denseTrajectoryChangedAnyMovingValidCells +=
                sample.changedAnyMovingValidCells;
        denseTrajectoryChangedBothMovingValidCells +=
                sample.changedBothMovingValidCells;
        denseTrajectoryChangedTiles += sample.changedTiles;
        denseTrajectoryChangedMovingOwnedTiles +=
                sample.changedMovingOwnedTiles;
        for (int direction = 0; direction < 2; ++direction) {
            denseTrajectoryValidCells[direction] += sample.validCells[direction];
            denseTrajectoryMovingValidCells[direction] +=
                    sample.movingValidCells[direction];
            denseTrajectoryStrongMovingValidCells[direction] +=
                    sample.strongMovingValidCells[direction];
            denseTrajectoryChangedValidCells[direction] +=
                    sample.changedValidCells[direction];
            denseTrajectoryChangedMovingValidCells[direction] +=
                    sample.changedMovingValidCells[direction];
            denseTrajectoryUnchangedMovingValidCells[direction] +=
                    sample.unchangedMovingValidCells[direction];
        }
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
        double source = frameRate.sustainedMeasuredSourceHz();
        double targetOutput = frameRate.targetOutputHz();
        long now = System.nanoTime();
        reportSourceAdmissionDiagnostic(now);
        // Diagnostic windows follow elapsed time, not a fluctuating target.
        // Resetting this clock on every millihertz change hid 44 seconds of
        // live health rows in the Switch 7c739 test. Physical qualification
        // still uses its own exact cadence/epoch ledgers below; an app-swap
        // average across a rate change is not evidence of uniform scanout.
        if (statsWindowStartNanos == 0L) {
            statsWindowStartNanos = now;
            statsWindowStartPresents = presents;
            publishReportedFrameRate(source, 0.0, targetOutput, false);
            return;
        }
        long elapsedNs = now - statsWindowStartNanos;
        if (elapsedNs < 1_000_000_000L) return;
        long committed = presents - statsWindowStartPresents;
        // Keep successful app-side swaps as diagnostic evidence, but publish
        // only EGL_DISPLAY_PRESENT_TIME_ANDROID as A. A compositor-dropped
        // swap therefore lowers physical cadence instead of being fabricated
        // as delivered output.
        double swapOutput = committed <= 0L ? 0.0 :
                committed * 1_000_000_000.0 / elapsedNs;
        int scansPerOutput = frameRate.panelScansPerOutput();
        long panelPeriodNs = frameRate.panelPeriodNs();
        PhysicalPresentationTracker physicalTracker = physicalPresentationTracker;
        boolean externalPhysical = externalTransport != null;
        boolean externalBackendOwnsPresentation = externalPhysical &&
                !externalTransport.usesAppOwnedPresentation();
        boolean externalAppOwnsPresentation = externalPhysical &&
                externalTransport.usesAppOwnedPresentation();
        int externalCandidateOutput = externalPhysical ?
                frameRate.candidateGeneratedOutputFps() : 0;
        int externalCandidateSource = externalPhysical ?
                frameRate.candidateGeneratedSourceFps() : 0;
        int externalCandidateScans = externalPhysical ?
                frameRate.candidateGeneratedPanelScansPerOutput() : 0;
        boolean externalCandidateSupported = externalPhysical &&
                frameRate.panelClockMeasured() &&
                (externalAppOwnsPresentation ?
                        physicalTracker != null && physicalTracker.available() :
                        externalPhysicalClockBootstrap.complete()) &&
                externalCandidateScans > 0 &&
                externalTransport.supportsRatePath(
                        externalCandidateSource, externalCandidateOutput);
        int physicalScans = externalPhysical ?
                externalPhysicalScansPerOutput : scansPerOutput;
        long physicalPeriod = externalPhysical ?
                externalPhysicalRefreshDurationNs : panelPeriodNs;
        // An app-owned external result is first recorded by the EGL tracker,
        // then joined here to the exact pending request and its scheduler
        // epoch.  The tracker's rolling cadence cannot see that epoch and can
        // therefore span a same-divisor re-prime boundary.  External paths use
        // the joined, epoch-partitioned cadence ledger; only the built-in path
        // reads the tracker's private rolling window directly.
        double physicalOutput = externalPhysical ?
                externalPhysicalCadence.actualHz(physicalScans, physicalPeriod) :
                physicalTracker == null ? 0.0 :
                        physicalTracker.actualHz(scansPerOutput, panelPeriodNs);
        boolean externalTimingIdentity = externalBackendOwnsPresentation ?
                externalPhysicalClockBootstrap.complete() &&
                        externalPresentationEvidence.identityMatches(
                                physicalScans, physicalPeriod,
                                schedulerPresentationEpoch(), 0) :
                externalAppOwnsPresentation &&
                        appOwnedExternalPresentationEvidence.identityMatches(
                                physicalScans, physicalPeriod,
                                schedulerPresentationEpoch());
        // On-time submitted frames do not prove complete output: a generated
        // slot abandoned before submission never enters the physical ledger.
        // Keep this session unqualified after any scheduler underrun.
        boolean externalTimingPassed = frameRate.bufferedUnderrunCount() == 0L &&
                (externalBackendOwnsPresentation ?
                externalPresentationEvidence.timingQualified() :
                externalAppOwnsPresentation &&
                        appOwnedExternalPresentationEvidence.timingQualified());
        boolean externalContentIdentity = externalPhysical &&
                externalGeneratedContentEvidence.identityMatches(
                        schedulerPresentationEpoch());
        boolean externalNumericContentPassed = externalContentIdentity &&
                externalGeneratedContentEvidence.numericProofPassed();
        boolean physicalQualified = frameRate.panelClockMeasured() &&
                (externalPhysical ?
                        externalPhysicalCadence.qualified(
                                physicalScans, physicalPeriod) &&
                        externalTimingIdentity &&
                        externalTimingPassed &&
                        externalNumericContentPassed &&
                        externalPathManuallyCertified() :
                        physicalTracker != null &&
                                physicalTracker.cadenceQualified(
                                        scansPerOutput, panelPeriodNs));
        statsWindowStartNanos = now;
        statsWindowStartPresents = presents;
        CadenceSnapshotLog.write(TAG, generatorId, "App swap cadence" +
                " callbackSamples=" + callbackDeltaSamples +
                " callbackTotalUs=" + callbackDeltaTotalUs +
                " callbackMaxUs=" + callbackDeltaMaxUs +
                " callbackLate=" + callbackLateCount +
                " externalClockBoundaryWaits=" + externalClockBoundaryWaits +
                " externalLookaheadReadinessWaits=" + externalLookaheadReadinessWaits +
                " externalBootstrapCapacityWaits=" + externalBootstrapCapacityWaits +
                " externalEndpointAdmissionRejected=" + externalEndpointAdmissionRejected +
                " externalEndpointAdmissionBlocked=" + (externalEndpointAdmissionBlocked ? 1 : 0) +
                " generator=" + generatorId +
                " role=" + displayRole +
                " displayId=" + displayId +
                " externalBackend=" + (externalRatePathActive ?
                        externalTransport.backendLabel() : "Direct") +
                " source=" + String.format(java.util.Locale.US, "%.3f", source) +
                " target=" + String.format(java.util.Locale.US, "%.3f", targetOutput) +
                " panel=" + String.format(java.util.Locale.US, "%.6f",
                        frameRate.panelHz()) +
                " panelMeasured=" + (frameRate.panelClockMeasured() ? 1 : 0) +
                " swap=" + String.format(java.util.Locale.US, "%.3f", swapOutput) +
                " canonical=" + String.format(java.util.Locale.US, "%.3f",
                        frameRate.provenTimestampSourceHzForDiagnostics()) +
                " uniqueClock=" + String.format(java.util.Locale.US, "%.3f",
                        frameRate.qualifiedUniqueTimestampSourceHzForDiagnostics()) +
                " canonicalCandidate=" + String.format(java.util.Locale.US,
                        "%.3f", frameRate.canonicalReacquireCandidateHzForDiagnostics()) +
                " canonicalEvidenceMs=" +
                        (frameRate.canonicalReacquireEvidenceNsForDiagnostics() /
                                1_000_000L) +
                " canonicalProof=" +
                        frameRate.canonicalProofSummaryForDiagnostics() +
                " schedulerCommitted=" +
                        frameRate.bufferedPresentationCount() +
                " schedulerReal=" + frameRate.bufferedRealCount() +
                " schedulerSynthetic=" + frameRate.bufferedSyntheticCount() +
                " schedulerLeadWaits=" + frameRate.bufferedLeadWaitCount() +
                " schedulerDuplicateWaits=" + frameRate.bufferedDuplicateWaitCount() +
                " schedulerPrimeWaits=" + frameRate.bufferedPrimeWaitCount() +
                " schedulerUnavailable=" +
                        frameRate.bufferedUnavailableSlotCount() +
                " schedulerLastUnavailableReason=" +
                        frameRate.bufferedLastUnavailableReason() +
                " builtinQueueCutoffMisses=" + builtinQueueCutoffMisses +
                " schedulerUnderrun=" + frameRate.bufferedUnderrunCount() +
                " schedulerCredits=" + frameRate.bufferedOutputCredits() +
                " schedulerEpoch=" + schedulerPresentationEpoch() +
                " schedulerEpochReason=" + frameRate.bufferedLastEpochReason() +
                " externalSubmissionDurationOverruns=" + appOwnedExternalPresentationEvidence.submissionDurationOverruns() +
                " schedulerEpochDiagnostic=" + frameRate.bufferedLastMismatchDiagnostic() +
                " activeLeft=" + activeLeftSequence +
                " activeRight=" + activeRightSequence +
                " fifoCount=" + endpointFifoCount +
                " committed=" + committed +
                " elapsedNs=" + elapsedNs +
                " physicalAvailable=" + (externalPhysical ?
                        (externalBackendOwnsPresentation ?
                                (physicalPeriod > 0L ? 1 : 0) :
                                (physicalTracker != null &&
                                        physicalTracker.available() ? 1 : 0)) :
                        (physicalTracker != null && physicalTracker.available() ? 1 : 0)) +
                " physicalBackend=" + (externalBackendOwnsPresentation ?
                        "vulkan" : externalAppOwnsPresentation ?
                                "egl-app-owned" : "egl") +
                " externalAppOwned=" +
                        (externalAppOwnsPresentation ? 1 : 0) +
                " physical=" + String.format(java.util.Locale.US, "%.3f",
                        physicalOutput) +
                " physicalQualified=" + (physicalQualified ? 1 : 0) +
                " physicalProof=" + (physicalTracker != null ?
                        physicalTracker.lastRejection().replace(' ', '_') :
                        "no-tracker") +
                " physicalSamples=" + (externalPhysical ?
                        externalPhysicalCadence.sampleCount() :
                        (physicalTracker == null ? 0 : physicalTracker.sampleCount())) +
                " physicalPresented=" + (externalPhysical ?
                        externalPhysicalCadence.successfulPresents() :
                        (physicalTracker == null ? 0 :
                                physicalTracker.physicallyPresentedCount())) +
                " physicalDropped=" + (externalPhysical ?
                        externalPhysicalCadence.droppedPresents() :
                        (physicalTracker == null ? 0 :
                                physicalTracker.compositorDroppedCount())) +
                " physicalUnavailable=" + (externalPhysical ?
                        externalPhysicalCadence.unavailablePresents() :
                        (physicalTracker == null ? 0 :
                                physicalTracker.unavailablePresentationCount())) +
                " physicalPending=" + (externalPhysical ?
                        (externalBackendOwnsPresentation ?
                                externalTransport.pendingPhysicalPresentationCount() :
                                (physicalTracker == null ? 0 :
                                        physicalTracker.pendingCount())) :
                        (physicalTracker == null ? 0 : physicalTracker.pendingCount())) +
                " externalAnchorTail=" + externalPhysicalAnchorTailRows +
                " externalSubmitted=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalSubmittedCount :
                                externalPresentationLedger.submittedCount()) +
                " externalFrameTimelineCallbacks=" +
                        compositorFrameTimelineCallbacks +
                " externalFrameTimelineMatched=" +
                        compositorFrameTimelineSelected +
                " externalFrameTimelineUnavailable=" +
                        compositorFrameTimelineUnavailable +
                " externalPredictionPeriodNs=" + compositorPredictionLattice.periodNs() +
                " externalPredictionOrdinal=" + compositorPredictionLattice.headOrdinal() +
                " externalFrameTimelineCommitted=" +
                        compositorFrameTimelineCommitted +
                " externalFrameTimelineNativeCallbackSequence=" +
                        compositorFrameTimelineNativeCallbackSequence +
                " externalFrameTimelineNativeFrameTimeNs=" +
                        compositorFrameTimelineNativeFrameTimeNs +
                " externalFrameTimelineErrorMaxNs=" +
                        compositorFrameTimelineErrorMaxNs +
                " externalFrameTimelineProbeLive=" +
                        compositorFrameTimelineProbeLive +
                " externalFrameTimelineProbeNoLive=" +
                        compositorFrameTimelineProbeNoLive +
                " externalFrameTimelineProbeErrorSignedMinNs=" +
                        compositorFrameTimelineProbeErrorSignedMinNs +
                " externalFrameTimelineProbeErrorSignedMaxNs=" +
                        compositorFrameTimelineProbeErrorSignedMaxNs +
                " externalFrameTimelineProbeErrorSignedLastNs=" +
                        compositorFrameTimelineProbeErrorSignedLastNs +
                " externalLockedSourceFps=" +
                        (externalPhysical ? frameRate.lockedSourceFps() : 0) +
                " externalPresentationSourceHz=" + String.format(
                        java.util.Locale.US, "%.9f",
                        externalPhysical ? frameRate.presentationSourceHz() : 0.0) +
                " externalCandidateOutput=" + externalCandidateOutput +
                " externalCandidateSource=" + externalCandidateSource +
                " externalCandidateScans=" + externalCandidateScans +
                " externalCandidateSupported=" +
                        (externalCandidateSupported ? 1 : 0) +
                " externalRatePathActive=" +
                        (externalRatePathActive ? 1 : 0) +
                " externalRatePathPriming=" +
                        (externalRatePathPriming ? 1 : 0) +
                " externalRatePathOutputPriming=" +
                        (externalRatePathOutputPriming ? 1 : 0) +
                " externalGenerationAvailable=" +
                        (frameRate.generationAvailable() ? 1 : 0) +
                " externalPhysicalEndpoint=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPhysicalEndpointCount :
                                externalPresentationLedger.
                                        physicalEndpointCount()) +
                " externalPhysicalGenerated=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPhysicalGeneratedCount :
                                externalPresentationLedger.
                                        physicalGeneratedCount()) +
                " externalPrequeueDeferred=" +
                        externalPrequeueDeferredCount +
                " externalTimingQualified=" +
                        (externalTimingIdentity && externalTimingPassed ? 1 : 0) +
                " externalTimingEpoch=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        presentationEpoch() :
                                externalPresentationEvidence.
                                        presentationEpoch()) +
                " externalTimingWindow=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalTimingWindow : 0L) +
                " externalTimingDroppedBaseline=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalTimingDroppedBaseline : 0L) +
                " externalTimingUnavailableBaseline=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalTimingUnavailableBaseline : 0L) +
                " externalTimingSamples=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        physicalPresents() :
                                externalPresentationEvidence.
                                        physicalPresents()) +
                " externalTimingStartNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        firstActualPresentNs() :
                                externalPresentationEvidence.
                                        firstActualPresentNs()) +
                " externalTimingEndNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        lastActualPresentNs() :
                                externalPresentationEvidence.
                                        lastActualPresentNs()) +
                " externalTimingEndpoint=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        physicalEndpoints() :
                                externalPresentationEvidence.
                                        physicalEndpoints()) +
                " externalTimingGenerated=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        physicalGenerated() :
                                externalPresentationEvidence.
                                        physicalGenerated()) +
                " externalTimingScans=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        targetScansPerOutput() :
                                externalPresentationEvidence.
                                        targetScansPerOutput()) +
                " externalTimingPipelineScans=" +
                        (externalAppOwnsPresentation ? 0 :
                                externalPresentationEvidence.
                                        targetPresentationPipelineScans()) +
                " externalTimingRefreshNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        targetPanelPeriodNs() :
                                externalPresentationEvidence.
                                        targetRefreshDurationNs()) +
                " externalDeadlineMisses=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        submissionDeadlineMisses() :
                                externalPresentationEvidence.deadlineMisses()) +
                " externalDesiredSlotMisses=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        desiredSlotMisses() :
                                externalPresentationEvidence.
                                        desiredSlotMisses()) +
                " externalEarliestPresentMisses=" +
                        (externalAppOwnsPresentation ? 0 :
                                externalPresentationEvidence.
                                        earliestPresentMisses()) +
                " externalEarlyPresentViolations=" +
                        (externalAppOwnsPresentation ? 0 :
                                externalPresentationEvidence.
                                        earlyPresentViolations()) +
                " externalEarlySlotMisses=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        earlyDesiredSlotMisses() :
                                externalPresentationEvidence.
                                        earlyDesiredSlotMisses()) +
                " externalLateSlotMisses=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        lateDesiredSlotMisses() :
                                externalPresentationEvidence.
                                        lateDesiredSlotMisses()) +
                " externalPresentMarginMinNs=" +
                        externalPresentationEvidence.minPresentMarginNs() +
                " externalPresentMarginP05Ns=" +
                        externalPresentationEvidence.presentMarginP05Ns() +
                " externalPresentMarginP50Ns=" +
                        externalPresentationEvidence.presentMarginP50Ns() +
                " externalPresentMarginP95Ns=" +
                        externalPresentationEvidence.presentMarginP95Ns() +
                " externalPresentMarginMaxNs=" +
                        externalPresentationEvidence.maxPresentMarginNs() +
                " externalPresentMarginLastNs=" +
                        externalPresentationEvidence.lastPresentMarginNs() +
                " externalLateSlotMarginMinNs=" +
                        externalPresentationEvidence.minLateSlotPresentMarginNs() +
                " externalLateSlotMarginMaxNs=" +
                        externalPresentationEvidence.maxLateSlotPresentMarginNs() +
                " externalEnqueueMaxNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxBindWallNs() :
                                externalPresentationEvidence.
                                        maxEnqueueWallNs()) +
                " externalGpuMaxNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxGpuWorkNs() :
                                externalPresentationEvidence.maxGpuWorkNs()) +
                " externalCombinedP95Ns=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        criticalP95Ns() :
                                externalPresentationEvidence.combinedP95Ns()) +
                " externalCombinedMaxNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxCriticalWallNs() :
                                externalPresentationEvidence.maxCombinedNs()) +
                " externalBindMaxNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxBindWallNs() : 0L) +
                " externalSwapMaxNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxSwapWallNs() : 0L) +
                " externalGpuBudgetMisses=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        gpuBudgetMisses() : 0L) +
                " externalSlotErrorMaxNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxDesiredSlotErrorNs() :
                                externalPresentationEvidence.
                                        maxDesiredSlotErrorNs()) +
                " externalSlotErrorSignedMinNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        minSignedDesiredSlotErrorNs() :
                                externalPresentationEvidence.
                                        minSignedDesiredSlotErrorNs()) +
                " externalSlotErrorSignedMaxNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxSignedDesiredSlotErrorNs() :
                                externalPresentationEvidence.
                                        maxSignedDesiredSlotErrorNs()) +
                " externalSlotErrorSignedLastNs=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        lastSignedDesiredSlotErrorNs() :
                                externalPresentationEvidence.
                                        lastSignedDesiredSlotErrorNs()) +
                " externalPhysicalClockPeriodNs=" +
                        externalPhysicalClock.planningPeriodNs() +
                " externalPhysicalClockTrackedAnchorNs=" +
                        externalPhysicalClock.trackedPlanningAnchorNs() +
                " externalPhysicalClockScans=" +
                        externalPhysicalClock.observedScans() +
                " externalPhysicalClockFrequencyScans=" +
                        externalPhysicalClock.frequencyObservedScans() +
                " externalPhysicalClockFrequencyDiscontinuities=" +
                        externalPhysicalClock.frequencyDiscontinuities() +
                " externalPhysicalClockCalibrated=" +
                        (externalAppOwnsPresentation ?
                                (externalPhysicalClock.available() ? 1 : 0) :
                                (externalPhysicalClockBootstrap.complete() ? 1 : 0)) +
                " externalPhysicalClockCalibrationPresents=" +
                        (externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        physicalPresents() :
                                externalPhysicalClockBootstrap.
                                        calibrationPresents()) +
                " externalPhaseMin=" + String.format(java.util.Locale.US,
                        "%.6f", externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        minGeneratedPhase() :
                                externalPresentationEvidence.
                                        minGeneratedPhase()) +
                " externalPhaseMax=" + String.format(java.util.Locale.US,
                        "%.6f", externalAppOwnsPresentation ?
                                appOwnedExternalPresentationEvidence.
                                        maxGeneratedPhase() :
                                externalPresentationEvidence.
                                        maxGeneratedPhase()) +
                " externalContentNumericPassed=" +
                        (externalNumericContentPassed ? 1 : 0) +
                " externalContentEpoch=" +
                        externalGeneratedContentEvidence.presentationEpoch() +
                " externalContentProofs=" +
                        externalGeneratedContentEvidence.proofs() +
                " externalContentEndpoints=" +
                        externalGeneratedContentEvidence.endpointProofs() +
                " externalContentGenerated=" +
                        externalGeneratedContentEvidence.generatedProofs() +
                " externalContentMovingGenerated=" +
                        externalGeneratedContentEvidence.movingGeneratedProofs() +
                " externalContentDistinctMovingGenerated=" +
                        externalGeneratedContentEvidence.distinctMovingGeneratedProofs() +
                " externalContentSceneCutRisk=" +
                        externalGeneratedContentEvidence.sceneCutRiskGeneratedProofs() +
                " externalUnsafePairs=" + externalUnsafePairCount +
                " externalContentEndpointFailures=" +
                        externalGeneratedContentEvidence.endpointPassthroughFailures() +
                " externalContentEqualsLeft=" +
                        externalGeneratedContentEvidence.generatedEqualsLeft() +
                " externalContentEqualsRight=" +
                        externalGeneratedContentEvidence.generatedEqualsRight() +
                " externalContentAnalysisMaxNs=" +
                        externalGeneratedContentEvidence.maxAnalysisWallNs() +
                " externalContentEndpointMadMaxPpm=" +
                        externalGeneratedContentEvidence.maxEndpointMadPpm() +
                " externalContentHistogramMaxPpm=" +
                        externalGeneratedContentEvidence.maxEndpointHistogramDistancePpm() +
                " externalContentOutputLeftMadMaxPpm=" +
                        externalGeneratedContentEvidence.maxOutputLeftMadPpm() +
                " externalContentOutputRightMadMaxPpm=" +
                        externalGeneratedContentEvidence.maxOutputRightMadPpm() +
                " externalContentManualPassed=" +
                        (externalPathManuallyCertified() ? 1 : 0));
        if (phaseDiagCount > 0) {
            Log.i(TAG, "Phase diagnostic" +
                    " generator=" + generatorId +
                    " endpointOffsetUs=" + (frameRate.endpointOffsetNs() / 1000L) +
                    " driftUsPerS=" + String.format(java.util.Locale.US, "%.1f",
                            frameRate.endpointDriftUsPerSecond()) +
                    " driftSpanS=" + String.format(java.util.Locale.US, "%.1f",
                            frameRate.endpointDriftSpanSeconds()) +
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
        publishReportedFrameRate(source, physicalOutput, targetOutput,
                physicalQualified);
    }

    private void publishExternalPhysicalClock() {
        double hz = externalPhysicalClock.sustainedFrequencyHz(System.nanoTime());
        if (!(hz > 0.0) ||
                Math.abs(hz / frameRate.declaredPanelHz() - 1.0) > 0.0075) return;
        long actualNs = externalPhysicalClock.lastActualNs();
        if (qualifiedPhysicalPanelHz == 0.0) {
            frameRate.setPhysicalDisplayRefreshHz(hz);
            qualifiedPhysicalPanelHz = hz;
            qualifiedPhysicalPanelRefinedNs = actualNs;
        } else if (actualNs - qualifiedPhysicalPanelRefinedNs >= 5_000_000_000L &&
                Math.abs(hz / qualifiedPhysicalPanelHz - 1.0) >= 0.000005 &&
                frameRate.refinePhysicalDisplayRefreshHz(hz)) {
            qualifiedPhysicalPanelHz = hz;
            qualifiedPhysicalPanelRefinedNs = actualNs;
        }
        // Actual-present evidence only; the core/audio owner reads this pair.
        qualifiedPhysicalPanelObservedNs = actualNs;
    }

    private void pollPhysicalPresentations() {
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport != null && transport.usesAppOwnedPresentation()) {
            // This poll only recycles private generator buffers. The visible
            // Surface and its physical frame IDs belong to the EGL tracker.
            java.util.List<ExternalFrameGenerationTransport.PresentationEvent>
                    backendEvents = transport.poll();
            if (!backendEvents.isEmpty() ||
                    transport.pendingPhysicalPresentationCount() != 0)
                throw new IllegalStateException(
                        "app-owned backend reported a visible presentation");
            pollAppOwnedPhysicalPresentations();
            return;
        }
        if (transport != null) {
            java.util.List<ExternalFrameGenerationTransport.PresentationEvent>
                    completed = transport.poll();
            for (ExternalFrameGenerationTransport.PresentationEvent event : completed) {
                long eventEpoch = event.request.presentationEpoch();
                if (externalPhysicalAccountingEpoch != eventEpoch) {
                    externalPhysicalCadence.reset();
                    // A scheduler epoch may follow a long interval with no
                    // app-owned presents. Thor may stop maintaining the old
                    // child Surface's scan phase while it is idle. A dropped
                    // event can be the first exact evidence of that boundary,
                    // so partition cadence before recording either event kind.
                    // A scheduler epoch changes endpoint/proof ownership, not
                    // the panel oscillator. Preserve the independently learned
                    // period for the same reported physical refresh mode, but
                    // discard the old phase until this epoch's first actual
                    // scan anchors it. r203 otherwise restarted at nominal
                    // 16.666666 ms while Thor was scanning near 16.659 ms;
                    // queue latency let that known drift cross the unchanged
                    // 2% slot gate before the new 500 ms estimate could affect
                    // already-submitted rows.
                    externalPhysicalClock.beginPresentationEpoch();
                    externalPhysicalAccountingEpoch = eventEpoch;
                    externalPhysicalAnchorTailRows = 0;
                }
                if (event.kind ==
                        ExternalFrameGenerationTransport.PresentationEvent.Kind.DROPPED) {
                    ExternalPresentationLedger.Drop drop =
                            externalPresentationLedger.physicallyDropped(
                                    event.request, event.presentId,
                                    event.refreshDurationNs);
                    externalPhysicalCadence.recordDropped(
                            drop.scansPerOutput, drop.refreshDurationNs);
                    if (externalPhysicalAnchorTailRows > 0)
                        --externalPhysicalAnchorTailRows;
                    continue;
                }
                ExternalFrameGenerationTransport.PhysicalPresentation row =
                        event.presentation;
                if (row == null)
                    throw new IllegalStateException(
                            "external presented event has no physical row");
                ExternalPresentationLedger.Commit commit =
                        externalPresentationLedger.physicallyPresented(
                                row.request, row.presentId,
                                row.desiredPresentTimeNs,
                                row.actualPresentTimeNs,
                                row.earliestPresentTimeNs,
                                row.presentMarginNs,
                                row.refreshDurationNs,
                                row.enqueueWallNs,
                                row.gpuWorkNs);
                boolean physicalEpochChanged =
                        externalPresentationEvidence.presentationEpoch() > 0L &&
                        externalPresentationEvidence.presentationEpoch() !=
                                commit.presentationEpoch;
                if (row.request.hasCompositorFrameTimeline())
                    presentationClockDiagnostics.record(row.presentId,
                            row.request.sessionEpoch(), row.request.presentationEpoch(),
                            row.actualPresentTimeNs, row.request.desiredPhysicalPresentTimeNs(),
                            row.request.compositorFrameTimelineVsyncId(),
                            row.request.compositorExpectedPresentationTimeNs(),
                            row.request.compositorFrameTimelineDeadlineNs(),
                            row.refreshDurationNs, System.nanoTime());
                if (!externalPhysicalClock.record(
                            commit.actualPresentTimeNs,
                            commit.refreshDurationNs,
                            commit.request.hasCompositorFrameTimeline() ?
                                    commit.request.
                                            compositorExpectedPresentationTimeNs() :
                                    commit.actualPresentTimeNs)) {
                    boolean endedDirectEpoch = !externalRatePathActive &&
                            !commit.generated &&
                            commit.presentationEpoch !=
                                    schedulerPresentationEpoch();
                    if (!endedDirectEpoch) {
                        throw new IllegalStateException(
                                "external physical scan clock is inconsistent");
                    }
                    // A screen capture, loading hold, or other bounded source
                    // pause can end the scheduler epoch while endpoint-only
                    // requests from the old epoch are already inside Vulkan/
                    // SurfaceFlinger. Their eventual physical rows remain
                    // truthful completions, but a many-second idle interval
                    // is not evidence about the new epoch's scan lattice.
                    // Re-anchor Direct on this independently observed row;
                    // the first completion carrying the new epoch will reset
                    // it again through externalPhysicalAccountingEpoch. Never
                    // forgive this condition for generated content or a live
                    // generated rate path.
                    externalPhysicalClock.reset();
                    if (!externalPhysicalClock.record(
                                commit.actualPresentTimeNs,
                                commit.refreshDurationNs,
                                commit.request.hasCompositorFrameTimeline() ?
                                        commit.request.
                                                compositorExpectedPresentationTimeNs() :
                                        commit.actualPresentTimeNs)) {
                        throw new IllegalStateException(
                                "external stale-epoch physical row cannot re-anchor");
                    }
                    externalDirectOutputPhaseAnchorNs = 0L;
                    Log.w(TAG, "External stale Direct clock re-anchored" +
                            " generator=" + generatorId +
                            " completedEpoch=" + commit.presentationEpoch +
                            " schedulerEpoch=" +
                                    schedulerPresentationEpoch() +
                            " actualNs=" + commit.actualPresentTimeNs);
                }
                publishExternalPhysicalClock();
                for (long dropped = 0L; dropped < commit.droppedBefore; ++dropped)
                    externalPhysicalCadence.recordDropped(
                            commit.scansPerOutput, commit.refreshDurationNs);
                if (externalPhysicalClockBootstrap.calibrationRow(
                        commit.presentationEpoch)) {
                    externalPhysicalClockBootstrap.recordCalibrationPresent(
                            commit.generated, commit.presentationEpoch);
                    if (!externalPhysicalClockBootstrap.complete()) {
                        if (!externalPhysicalCadence.recordPresented(
                                commit.actualPresentTimeNs,
                                commit.scansPerOutput,
                                commit.refreshDurationNs))
                            throw new IllegalStateException(
                                    "external calibration cadence is inconsistent");
                        externalPhysicalScansPerOutput = commit.scansPerOutput;
                        externalPhysicalRefreshDurationNs = commit.refreshDurationNs;
                        ++presents;
                        if (!outputFrameRateReassertedAfterSwap) {
                            outputFrameRateReassertedAfterSwap = true;
                            requestOutputFrameRate(
                                    "first-physical-vulkan-calibration-present");
                        }
                    }
                    continue;
                }
                if (physicalEpochChanged) {
                    // The first returned row after an idle/re-prime boundary
                    // was necessarily planned from the preceding epoch's
                    // physical anchor. Its actual timestamp is the new anchor,
                    // not evidence that the new epoch missed its requested
                    // slot. Only an exact endpoint may establish this boundary;
                    // generated content would have an unauditable phase.
                    if (commit.generated)
                        throw new IllegalStateException(
                                "external epoch anchor cannot be generated");
                    externalPresentationEvidence.beginEpoch(
                            commit.scansPerOutput,
                            commit.refreshDurationNs,
                            commit.presentationEpoch,
                            commit.request.presentationPipelineScans());
                    externalGeneratedContentEvidence.beginEpoch(
                            commit.presentationEpoch);
                    // This exact endpoint is the first physically completed
                    // row in the new rate-path epoch. Preserve its measured
                    // scan as the committed divisor phase instead of falling
                    // back to the arbitrary calibration-row phase.
                    externalDirectOutputPhaseAnchorNs =
                            commit.actualPresentTimeNs;
                    // Every row still pending after this first actual scan was
                    // planned without the new physical phase. Keep those
                    // truthful visible completions, but do not let their old
                    // target timestamps qualify or quarantine the new path.
                    // Newly submitted rows use this actual anchor; FIFO timing
                    // guarantees the captured pending prefix retires first.
                    externalPhysicalAnchorTailRows =
                            externalPresentationLedger.pendingCount();
                    if (!externalPhysicalCadence.recordPresented(
                                    commit.actualPresentTimeNs,
                                    commit.scansPerOutput,
                                    commit.refreshDurationNs))
                        throw new IllegalStateException(
                                "external epoch-anchor cadence is inconsistent");
                    externalPhysicalScansPerOutput = commit.scansPerOutput;
                    externalPhysicalRefreshDurationNs = commit.refreshDurationNs;
                    ++presents;
                    if (!outputFrameRateReassertedAfterSwap) {
                        outputFrameRateReassertedAfterSwap = true;
                        requestOutputFrameRate(
                                "first-physical-vulkan-epoch-anchor");
                    }
                    Log.i(TAG, "External physical clock epoch anchored" +
                            " generator=" + generatorId +
                            " presentId=" + row.presentId +
                            " epoch=" + commit.presentationEpoch +
                            " queuedPreAnchor=" +
                                    externalPhysicalAnchorTailRows +
                            " actualNs=" + commit.actualPresentTimeNs);
                    continue;
                }
                if (externalPhysicalAnchorTailRows > 0) {
                    --externalPhysicalAnchorTailRows;
                    // Re-anchor on each member of the captured prefix. The
                    // last such actual scan is the first phase known not to
                    // depend on a pre-anchor plan.
                    externalDirectOutputPhaseAnchorNs =
                            commit.actualPresentTimeNs;
                    externalPhysicalCadence.reset();
                    if (!externalPhysicalCadence.recordPresented(
                                    commit.actualPresentTimeNs,
                                    commit.scansPerOutput,
                                    commit.refreshDurationNs))
                        throw new IllegalStateException(
                                "external pre-anchor tail cadence is inconsistent");
                    externalPhysicalScansPerOutput = commit.scansPerOutput;
                    externalPhysicalRefreshDurationNs = commit.refreshDurationNs;
                    ++presents;
                    if (!outputFrameRateReassertedAfterSwap) {
                        outputFrameRateReassertedAfterSwap = true;
                        requestOutputFrameRate(
                                "physical-vulkan-pre-anchor-tail");
                    }
                    Log.i(TAG, "External physical pre-anchor row excluded" +
                            " generator=" + generatorId +
                            " presentId=" + row.presentId +
                            " epoch=" + commit.presentationEpoch +
                            " remaining=" + externalPhysicalAnchorTailRows +
                            " actualNs=" + commit.actualPresentTimeNs);
                    continue;
                }
                long timingMissesBefore =
                        externalPresentationEvidence.deadlineMisses() +
                        externalPresentationEvidence.desiredSlotMisses() +
                        externalPresentationEvidence.earliestPresentMisses() +
                        externalPresentationEvidence.earlyPresentViolations();
                externalPresentationEvidence.record(commit,
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS);
                externalGeneratedContentEvidence.record(commit, row.contentProof);
                long timingMissesAfter =
                        externalPresentationEvidence.deadlineMisses() +
                        externalPresentationEvidence.desiredSlotMisses() +
                        externalPresentationEvidence.earliestPresentMisses() +
                        externalPresentationEvidence.earlyPresentViolations();
                boolean currentRatePathEpoch =
                        commit.presentationEpoch == schedulerPresentationEpoch();
                if (externalRatePathActive && currentRatePathEpoch &&
                        timingMissesAfter > timingMissesBefore) {
                    // A physical-slot miss makes every later interpolation
                    // timestamp unsafe even when FIFO cadence remains uniform.
                    // r51 stayed near 40 FPS after slipping one whole panel
                    // scan, but continued showing generated images against the
                    // wrong source-time phase. Permanently quarantine generation
                    // for this session and continue exact endpoint-only Direct
                    // presentation through the already-live Vulkan transport.
                    markExternalTimingRejected();
                    externalRatePathActive = false;
                    externalRatePathPriming = false;
                    externalRatePathOutputPriming = false;
                    externalAppOwnedActivationFirstSwapPending = false;
                    externalDirectOutputPhaseAnchorNs = 0L;
                    transport.setGeneratedRatePathActive(false);
                    frameRate.setGenerationAvailable(false);
                    invalidateBufferedPairForReprime(false);
                    resetHealthWindowAfterStreamChange();
                    Log.e(TAG, "External generation disabled after physical-slot miss" +
                            " generator=" + generatorId +
                            " presentId=" + row.presentId +
                            " generated=" + (commit.generated ? 1 : 0) +
                            " phase=" + String.format(java.util.Locale.US,
                                    "%.6f", commit.request.phase()) +
                            " contentNs=" +
                                    commit.request.desiredPhysicalPresentTimeNs() +
                            " desiredNs=" + row.desiredPresentTimeNs +
                            " timelineVsyncId=" +
                                    commit.request.compositorFrameTimelineVsyncId() +
                            " timelineTokenExpectedNs=" +
                                    commit.request.
                                            compositorTokenExpectedPresentationTimeNs() +
                            " timelineExpectedNs=" +
                                    commit.request.compositorExpectedPresentationTimeNs() +
                            " timelineDeadlineNs=" +
                                    commit.request.compositorFrameTimelineDeadlineNs() +
                            " latchNs=" + row.earliestPresentTimeNs +
                            " actualNs=" + row.actualPresentTimeNs +
                            " presentMarginNs=" + row.presentMarginNs +
                            " enqueueWallNs=" + row.enqueueWallNs +
                            " gpuWorkNs=" + row.gpuWorkNs +
                            " deadlineMisses=" +
                                    externalPresentationEvidence.deadlineMisses() +
                            " desiredSlotMisses=" +
                                    externalPresentationEvidence.desiredSlotMisses());
                }
                if (!externalPhysicalCadence.recordPresented(
                                commit.actualPresentTimeNs,
                                commit.scansPerOutput,
                                commit.refreshDurationNs))
                    throw new IllegalStateException(
                            "external physical-presentation accounting mismatch");
                externalPhysicalScansPerOutput = commit.scansPerOutput;
                externalPhysicalRefreshDurationNs = commit.refreshDurationNs;
                ++presents;
                if (!outputFrameRateReassertedAfterSwap) {
                    outputFrameRateReassertedAfterSwap = true;
                    requestOutputFrameRate("first-physical-vulkan-present");
                }
                if (commit.generated) {
                    ++generatedPresents;
                }
            }
            if (externalPresentationLedger.pendingCount() !=
                    transport.pendingPhysicalPresentationCount())
                throw new IllegalStateException(
                        "external submitted/timing queue conservation mismatch");
            int pending = externalPresentationLedger.pendingCount();
            if (externalPhysicalClockBootstrap.ready(
                    externalPhysicalClock.available(), pending,
                    transport.pendingPhysicalPresentationCount())) {
                externalPhysicalClockBootstrap.commit(
                        externalPhysicalClock.available(), pending,
                        transport.pendingPhysicalPresentationCount());
                externalDirectOutputPhaseAnchorNs = 0L;
                externalPhysicalCadence.reset();
                long previousEpoch = schedulerPresentationEpoch();
                frameRate.resetPresentation();
                observedBufferedPresentationEpoch =
                        schedulerPresentationEpoch();
                resetEndpointTimelineForSchedulerEpoch();
                refreshProofEvidencePresentationEpoch();
                resetHealthWindowAfterStreamChange();
                externalPhysicalClockBoundaryCommittedThisCallback = true;
                Log.i(TAG, "External physical clock calibrated" +
                        " generator=" + generatorId +
                        " calibrationPresents=" +
                        externalPhysicalClockBootstrap.calibrationPresents() +
                        " clockAnchorNs=" + externalPhysicalClock.anchorNs() +
                        " clockPeriodNs=" +
                        externalPhysicalClock.planningPeriodNs() +
                        " excludedTailPending=" + pending +
                        " previousEpoch=" + previousEpoch +
                        " epoch=" + schedulerPresentationEpoch());
            }
            return;
        }
        PhysicalPresentationTracker tracker = physicalPresentationTracker;
        if (tracker == null || !tracker.available()) return;
        tracker.poll();
        // Built-in recovery consumes the exact committed EGL frame owner.
        // Untracked Direct/old-epoch events are never borrowed for headroom.
        PhysicalPresentationTracker.Event denseEvent;
        while ((denseEvent = tracker.takeCompletedEvent()) != null) {
            // Callback phase is not the physical scan phase. Calibrate only
            // from actual PRESENTED events, independently of shader headroom.
            if (denseEvent.kind == PhysicalPresentationTracker.Event.Kind.PRESENTED)
                builtInPhysicalClock.record(denseEvent.actualPresentTimeNs,
                        Math.max(1L, Math.round(1e9 / frameRate.declaredPanelHz())));
            double physicalHz = builtInPhysicalClock.sustainedFrequencyHz(System.nanoTime());
            if (physicalHz > 0.0 && Math.abs(physicalHz / frameRate.declaredPanelHz() - 1.0) <= 0.0075) {
                if (qualifiedPhysicalPanelHz == 0.0) {
                    qualifiedPhysicalPanelHz = physicalHz;
                    frameRate.setPhysicalDisplayRefreshHz(physicalHz);
                    qualifiedPhysicalPanelRefinedNs = builtInPhysicalClock.lastActualNs();
                } else if (builtInPhysicalClock.lastActualNs() -
                        qualifiedPhysicalPanelRefinedNs >= 5_000_000_000L &&
                        Math.abs(physicalHz / qualifiedPhysicalPanelHz - 1.0) >= 0.000005 &&
                        frameRate.refinePhysicalDisplayRefreshHz(physicalHz)) {
                    // Publish only an accepted transition. The guest owner
                    // applies the same rate to pacing and audio; the controller
                    // independently verifies the ensuing source intervals.
                    qualifiedPhysicalPanelHz = physicalHz;
                    qualifiedPhysicalPanelRefinedNs = builtInPhysicalClock.lastActualNs();
                }
                qualifiedPhysicalPanelObservedNs = builtInPhysicalClock.lastActualNs();
            }
            if (!densePyramidEnabled) continue;
            if (!denseGpuHeadroom.ownsFrame(denseEvent.frameId)) {
                ++denseGpuPhysicalUnboundEvents;
                denseGpuAdaptation.invalidateRecoveryEvidence();
                continue;
            }
            int status = denseEvent.kind == PhysicalPresentationTracker.Event.Kind.PRESENTED ?
                    GpuPhysicalHeadroomLedger.PRESENTED :
                    denseEvent.kind == PhysicalPresentationTracker.Event.Kind.DROPPED ?
                            GpuPhysicalHeadroomLedger.DROPPED : GpuPhysicalHeadroomLedger.UNAVAILABLE;
            denseGpuReadyTimestampSupportedMask = denseEvent.readyTimestampSupportedMask;
            if (!denseGpuHeadroom.recordPhysical(denseGpuHeadroom.evidenceEpoch(),
                    denseEvent.frameId, status, denseEvent.actualPresentTimeNs,
                    denseEvent.scansPerOutput, denseEvent.panelPeriodNs,
                    denseEvent.readyTimestampSupportedMask, denseEvent.renderingCompleteTimeNs,
                    denseEvent.compositionLatchTimeNs, denseEvent.compositionStartTimeNs,
                    denseEvent.compositorGpuFinishedTimeNs)) {
                rejectDense("invalid-timer-physical-identity", null);
                continue;
            }
            consumeDensePhysicalGpuHeadroom();
        }
        if (!tracker.available()) denseGpuAdaptation.invalidateRecoveryEvidence();
        if (!tracker.available()) logPhysicalPresentationFailure(tracker);
    }

    private void pollAppOwnedPhysicalPresentations() {
        PhysicalPresentationTracker tracker = physicalPresentationTracker;
        if (tracker == null || !tracker.available()) return;
        // App-owned external generation needs the same exact-frame readiness
        // evidence as the built-in path. Capability bits alone do not enable
        // collection: without this, failure logs contain synthetic -1 defaults.
        // This is not reached by Strict Off's isolated direct SurfaceView.
        tracker.setReadyTimingEnabled(true);
        tracker.poll();
        PhysicalPresentationTracker.Event event;
        while ((event = tracker.takeCompletedEvent()) != null) {
            AppOwnedPhysicalPending pending = appOwnedPhysicalPending.pollFirst();
            if (pending == null || pending.frameId != event.frameId ||
                    pending.scansPerOutput != event.scansPerOutput ||
                    pending.panelPeriodNs != event.panelPeriodNs)
                throw new IllegalStateException(
                        "app-owned physical result does not match its EGL swap");
            if (event.kind ==
                    PhysicalPresentationTracker.Event.Kind.UNAVAILABLE) {
                externalPhysicalCadence.recordUnavailable(
                        event.scansPerOutput, event.panelPeriodNs);
                long eventEpoch = pending.request.presentationEpoch();
                if (externalPhysicalAccountingEpoch != eventEpoch) {
                    externalPhysicalAccountingEpoch = eventEpoch;
                    externalPhysicalClock.beginPresentationEpoch();
                    externalGeneratedContentEvidence.beginEpoch(eventEpoch);
                }
                restartAppOwnedExternalTimingWindow(
                        event.scansPerOutput, event.panelPeriodNs, eventEpoch);
                resetHealthWindowAfterStreamChange();
                Log.w(TAG, "App-owned physical timestamp history expired; " +
                        "evidence window restarted" +
                        " generator=" + generatorId +
                        " frameId=" + event.frameId +
                        " generated=" +
                                (pending.request.isGenerated() ? 1 : 0) +
                        " eventEpoch=" + eventEpoch +
                        " currentEpoch=" + schedulerPresentationEpoch() +
                        " timingWindow=" +
                                appOwnedExternalTimingWindow +
                        " desiredNs=" +
                                pending.request.desiredPhysicalPresentTimeNs() +
                        " swapCompletedNs=" + pending.swapCompletedNs +
                        " resultAgeNs=" + Math.max(0L,
                                System.nanoTime() - pending.swapCompletedNs) +
                        " pendingAfter=" + appOwnedPhysicalPending.size());
                continue;
            }
            if (event.kind != PhysicalPresentationTracker.Event.Kind.PRESENTED) {
                externalPhysicalCadence.recordDropped(
                        event.scansPerOutput, event.panelPeriodNs);
                markExternalTimingRejected();
                externalRatePathActive = false;
                externalRatePathPriming = false;
                externalRatePathOutputPriming = false;
                externalAppOwnedActivationFirstSwapPending = false;
                externalTransport.setGeneratedRatePathActive(false);
                frameRate.setGenerationAvailable(false);
                invalidateBufferedPairForReprime(false);
                resetHealthWindowAfterStreamChange();
                Log.e(TAG, "App-owned physical presentation failed closed" +
                        " generator=" + generatorId +
                        " frameId=" + event.frameId +
                        " result=" + event.kind +
                        " generated=" +
                                (pending.request.isGenerated() ? 1 : 0) +
                        " eventEpoch=" +
                                pending.request.presentationEpoch() +
                        " currentEpoch=" + schedulerPresentationEpoch() +
                        " desiredNs=" +
                                pending.request.desiredPhysicalPresentTimeNs() +
                        " driverDesiredNs=" +
                                pending.request.driverDesiredPresentTimeNs() +
                        " swapCompletedNs=" + pending.swapCompletedNs +
                        " resultAgeNs=" + Math.max(0L,
                                System.nanoTime() - pending.swapCompletedNs) +
                        " scansPerOutput=" + pending.scansPerOutput +
                        " panelPeriodNs=" + pending.panelPeriodNs +
                        " pendingAfter=" + appOwnedPhysicalPending.size());
                continue;
            }
            long eventEpoch = pending.request.presentationEpoch();
            if (pending.request.isGenerated())
                ++appOwnedExternalPhysicalGeneratedCount;
            else
                ++appOwnedExternalPhysicalEndpointCount;
            if (externalPhysicalAccountingEpoch != eventEpoch) {
                externalPhysicalAccountingEpoch = eventEpoch;
                externalPhysicalCadence.reset();
                externalPhysicalClock.beginPresentationEpoch();
                restartAppOwnedExternalTimingWindow(
                        event.scansPerOutput, event.panelPeriodNs, eventEpoch);
                externalGeneratedContentEvidence.beginEpoch(eventEpoch);
            }
            long timingMissesBefore =
                    appOwnedExternalPresentationEvidence.
                            submissionDeadlineMisses() +
                    appOwnedExternalPresentationEvidence.desiredSlotMisses() +
                    appOwnedExternalPresentationEvidence.gpuBudgetMisses();
            appOwnedExternalPresentationEvidence.record(
                    pending.request, event.frameId,
                    event.actualPresentTimeNs,
                    event.scansPerOutput, event.panelPeriodNs,
                    pending.bindWallNs, pending.swapWallNs,
                    pending.swapCompletedNs,
                    pending.generatedOutput == null ? 0L :
                            pending.generatedOutput.gpuWorkNs);
            if (pending.generatedOutput != null)
                externalGeneratedContentEvidence.recordAppOwnedGenerated(
                        eventEpoch, event.frameId, pending.request,
                        pending.generatedOutput.contentProof);
            long timingMissesAfter =
                    appOwnedExternalPresentationEvidence.
                            submissionDeadlineMisses() +
                    appOwnedExternalPresentationEvidence.desiredSlotMisses() +
                    appOwnedExternalPresentationEvidence.gpuBudgetMisses();
            boolean cadenceConsistent =
                    externalPhysicalCadence.recordPresented(
                            event.actualPresentTimeNs,
                            event.scansPerOutput, event.panelPeriodNs);
            long priorPhysicalActualNs = externalPhysicalClock.lastActualNs();
            boolean clockConsistent = externalPhysicalClock.record(
                    event.actualPresentTimeNs, event.panelPeriodNs);
            if (!clockConsistent && !externalRatePathActive &&
                    !pending.request.isGenerated() &&
                    priorPhysicalActualNs > 0L &&
                    event.actualPresentTimeNs > priorPhysicalActualNs &&
                    externalPhysicalClock.nominalPeriodNs() ==
                            event.panelPeriodNs) {
                // A Direct-only title/menu pause may leave no app swaps for
                // seconds. The panel oscillator continues, but accumulated
                // nominal-vs-measured drift can move the first resumed row
                // beyond the strict quarter-scan continuity residual. That
                // independently returned row is a safe new planning anchor;
                // retain the measured oscillator period and let the physical
                // cadence ring keep the real visible gap. Never do this once
                // generated output is active or for a generated row: those
                // paths must remain fatal on any phase discontinuity.
                externalPhysicalClock.beginPresentationEpoch();
                clockConsistent = externalPhysicalClock.record(
                        event.actualPresentTimeNs, event.panelPeriodNs);
                if (clockConsistent)
                    Log.i(TAG, "App-owned Direct physical clock re-anchored" +
                            " generator=" + generatorId +
                            " priorActualNs=" + priorPhysicalActualNs +
                            " actualNs=" + event.actualPresentTimeNs +
                            " gapNs=" +
                                    (event.actualPresentTimeNs -
                                            priorPhysicalActualNs));
            }
            if (!cadenceConsistent || !clockConsistent)
                throw new IllegalStateException(
                        "app-owned physical cadence is inconsistent");
            publishExternalPhysicalClock();
            externalPhysicalScansPerOutput = event.scansPerOutput;
            externalPhysicalRefreshDurationNs = event.panelPeriodNs;
            if (externalRatePathActive &&
                    eventEpoch == schedulerPresentationEpoch() &&
                    timingMissesAfter > timingMissesBefore) {
                long submissionBudgetMisses = appOwnedExternalPresentationEvidence.submissionDeadlineMisses();
                long physicalSlotMisses = appOwnedExternalPresentationEvidence.desiredSlotMisses();
                long inferenceBudgetMisses = appOwnedExternalPresentationEvidence.gpuBudgetMisses();
                markExternalTimingRejected();
                externalRatePathActive = false;
                externalRatePathPriming = false;
                externalRatePathOutputPriming = false;
                externalAppOwnedActivationFirstSwapPending = false;
                externalTransport.setGeneratedRatePathActive(false);
                frameRate.setGenerationAvailable(false);
                invalidateBufferedPairForReprime(false);
                resetHealthWindowAfterStreamChange();
                Log.e(TAG, "App-owned external timing failed closed" +
                        " generator=" + generatorId +
                        " submissionBudgetMisses=" + submissionBudgetMisses +
                        " physicalSlotMisses=" + physicalSlotMisses +
                        " inferenceBudgetMisses=" + inferenceBudgetMisses +
                        " frameId=" + event.frameId +
                        " generated=" +
                                (pending.request.isGenerated() ? 1 : 0) +
                        " desiredNs=" +
                                pending.request.desiredPhysicalPresentTimeNs() +
                        " driverDesiredNs=" +
                                pending.request.driverDesiredPresentTimeNs() +
                        " hardDeadlineNs=" +
                                pending.request.hardCompletionDeadlineNs() +
                        " actualNs=" + event.actualPresentTimeNs +
                        " actualMinusDesiredNs=" +
                                (event.actualPresentTimeNs -
                                        pending.request.
                                                desiredPhysicalPresentTimeNs()) +
                        " submissionStartedNs=" +
                                pending.submissionStartedNs +
                        " swapStartedNs=" + pending.swapStartedNs +
                        " swapCompletedNs=" + pending.swapCompletedNs +
                        " submissionLeadToDesiredNs=" +
                                (pending.request.
                                        desiredPhysicalPresentTimeNs() -
                                        pending.submissionStartedNs) +
                        " swapLeadToDesiredNs=" +
                                (pending.request.
                                        desiredPhysicalPresentTimeNs() -
                                        pending.swapCompletedNs) +
                        " completionReserveNs=" +
                                (pending.request.hardCompletionDeadlineNs() -
                                        pending.swapCompletedNs) +
                        " resultAgeNs=" + Math.max(0L,
                                System.nanoTime() - pending.swapCompletedNs) +
                        " left=" + pending.request.leftSequence() +
                        " right=" + pending.request.rightSequence() +
                        " targetSourceNs=" +
                                pending.request.presentationTimestampNs() +
                        " phaseBits=" + Long.toUnsignedString(
                                Double.doubleToRawLongBits(
                                        pending.request.phase())) +
                        " bindWallNs=" + pending.bindWallNs +
                        " swapWallNs=" + pending.swapWallNs +
                        " readyTimestampSupportedMask=" + event.readyTimestampSupportedMask +
                        " renderingCompleteNs=" + event.renderingCompleteTimeNs +
                        " compositionLatchNs=" + event.compositionLatchTimeNs +
                        " compositionStartNs=" + event.compositionStartTimeNs +
                        " compositorGpuFinishedNs=" + event.compositorGpuFinishedTimeNs +
                        " gpuWorkNs=" +
                                (pending.generatedOutput == null ? 0L :
                                        pending.generatedOutput.gpuWorkNs));
            }
        }
        maybeRecoverAppOwnedDirectPhysicalTiming();
        if (!tracker.available()) logPhysicalPresentationFailure(tracker);
    }

    private void restartAppOwnedExternalTimingWindow(
            int scansPerOutput, long panelPeriodNs, long presentationEpoch) {
        if (appOwnedExternalTimingWindow == Long.MAX_VALUE)
            throw new IllegalStateException(
                    "app-owned timing-window sequence overflow");
        appOwnedExternalPresentationEvidence.restartWindow(
                scansPerOutput, panelPeriodNs, presentationEpoch);
        externalGeneratedContentEvidence.restartWindow(presentationEpoch);
        ++appOwnedExternalTimingWindow;
        appOwnedExternalTimingDroppedBaseline =
                externalPhysicalCadence.droppedPresents();
        appOwnedExternalTimingUnavailableBaseline =
                externalPhysicalCadence.unavailablePresents();
    }

    /**
     * Re-arms an app-owned qualification only after an independently clean
     * Direct physical epoch.
     *
     * <p>An explicit compositor drop or a proven physical-slot miss must fail
     * closed immediately, but it must not permanently disable safe Direct
     * re-prime for the rest of the game. Finite timestamp-history expiry is
     * handled separately by restarting only the evidence window because it
     * does not prove that a frame was dropped. Recovery from an actual timing
     * failure is intentionally stricter than ordinary fallback: no generated
     * path may be active, both the Java
     * request ledger and native timestamp queue must be empty, the measured
     * physical clock must be live, and the current exact scan divisor must
     * have at least two clean seconds of physically presented rows. A fresh
     * scheduler epoch then prevents old endpoint/proof ownership from crossing
     * the recovery boundary. Any failure after generated activation remains
     * fatal for that active qualification window.</p>
     */
    private void maybeRecoverAppOwnedDirectPhysicalTiming() {
        PhysicalPresentationTracker tracker = physicalPresentationTracker;
        if (!externalTimingRejected || externalRatePathActive ||
                externalRatePathPriming || externalTransport == null ||
                !externalTransport.usesAppOwnedPresentation() ||
                tracker == null || !tracker.available() ||
                !appOwnedPhysicalPending.isEmpty() ||
                tracker.pendingCount() != 0 ||
                externalPhysicalScansPerOutput <= 0 ||
                externalPhysicalRefreshDurationNs <= 0L ||
                !externalPhysicalClock.available() ||
                !externalPhysicalCadence.qualified(
                        externalPhysicalScansPerOutput,
                        externalPhysicalRefreshDurationNs))
            return;
        long previousEpoch = schedulerPresentationEpoch();
        externalTimingRejected = false;
        frameRate.resetPresentation();
        observedBufferedPresentationEpoch = schedulerPresentationEpoch();
        resetEndpointTimelineForSchedulerEpoch();
        refreshProofEvidencePresentationEpoch();
        resetHealthWindowAfterStreamChange();
        Log.i(TAG, "App-owned Direct physical timing recovered" +
                " generator=" + generatorId +
                " samples=" + tracker.sampleCount() +
                " scansPerOutput=" + externalPhysicalScansPerOutput +
                " panelPeriodNs=" + externalPhysicalRefreshDurationNs +
                " previousEpoch=" + previousEpoch +
                " epoch=" + schedulerPresentationEpoch());
    }

    /**
     * Numeric proof can reject a path but can never certify moving-video
     * quality.  A future immutable per-system/path certification manifest may
     * implement this; qualification builds remain explicitly unqualified
     * until the required physical and manual inspection has occurred.
     */
    private boolean externalPathManuallyCertified() { return false; }

    private void logPhysicalPresentationFailure(
            PhysicalPresentationTracker tracker) {
        if (physicalPresentationUnavailableLogged) return;
        physicalPresentationUnavailableLogged = true;
        Log.e(TAG, "Physical scanout timestamp tracker failed closed" +
                " generator=" + generatorId +
                " nativeStatus=" +
                        (tracker == null ? 0 : tracker.lastNativeFailure()) +
                " actualAvailable=0");
        publishReportedFrameRate(frameRate.sustainedMeasuredSourceHz(), 0.0,
                frameRate.targetOutputHz(), false);
    }

    private void reportSourceAdmissionDiagnostic(long now) {
        if (sourceDiagWindowStartNanos == 0L) {
            sourceDiagWindowStartNanos = now;
            sourceDiagStartHardwareSubmits = diagHardwareSubmits;
            sourceDiagStartSoftwareSubmits = diagSoftwareSubmits;
            sourceDiagStartUniqueVerdicts = diagUniqueVerdicts;
            sourceDiagStartDuplicateVerdicts = diagDuplicateVerdicts;
            sourceDiagStartUniqueFrames = uniqueFrameCount;
            sourceDiagStartEndpoints = endpointSequence;
            sourceDiagStartCandidateUnavailable = endpointCandidateUnavailable;
            sourceDiagStartTimestampCorrections = endpointTimestampCorrections;
            sourceDiagStartFifoCoalesced = endpointFifoCoalesced;
            return;
        }
        long elapsedNs = now - sourceDiagWindowStartNanos;
        if (elapsedNs < 1_000_000_000L) return;
        long hardware = diagHardwareSubmits - sourceDiagStartHardwareSubmits;
        long software = diagSoftwareSubmits - sourceDiagStartSoftwareSubmits;
        long unique = diagUniqueVerdicts - sourceDiagStartUniqueVerdicts;
        long duplicate = diagDuplicateVerdicts - sourceDiagStartDuplicateVerdicts;
        long uniqueFrames = uniqueFrameCount - sourceDiagStartUniqueFrames;
        long endpoints = endpointSequence - sourceDiagStartEndpoints;
        reportedAdmissionAcceptedEndpoints = endpoints;
        long unavailable = endpointCandidateUnavailable -
                sourceDiagStartCandidateUnavailable;
        long timestampCorrections = endpointTimestampCorrections -
                sourceDiagStartTimestampCorrections;
        long coalesced = endpointFifoCoalesced - sourceDiagStartFifoCoalesced;
        double seconds = elapsedNs / 1_000_000_000.0;
        Log.i(TAG, "Source admission diagnostic" +
                " generator=" + generatorId +
                " elapsedNs=" + elapsedNs +
                " hwSubmits=" + hardware +
                " swSubmits=" + software +
                " uniqueVerdicts=" + unique +
                " duplicateVerdicts=" + duplicate +
                " uniqueFrames=" + uniqueFrames +
                " acceptedEndpoints=" + endpoints +
                " hardwareHz=" + String.format(java.util.Locale.US,
                        "%.3f", hardware / seconds) +
                " uniqueHz=" + String.format(java.util.Locale.US,
                        "%.3f", uniqueFrames / seconds) +
                " endpointHz=" + String.format(java.util.Locale.US,
                        "%.3f", endpoints / seconds) +
                " sustainedSourceHz=" + String.format(java.util.Locale.US,
                        "%.3f", frameRate.sustainedMeasuredSourceHz()) +
                " qualifiedUniqueClockHz=" + String.format(
                        java.util.Locale.US, "%.3f",
                        frameRate.qualifiedUniqueTimestampSourceHzForDiagnostics()) +
                " candidateUnavailable=" + unavailable +
                " timestampCorrections=" + timestampCorrections +
                " fifoCoalesced=" + coalesced +
                " changedPixels=" + diagLastChangedPixels +
                " signatureByteSum=" + diagLastSignatureByteSum +
                " timestampProof=" +
                        frameRate.canonicalProofSummaryForDiagnostics() +
                " retentionProof=" +
                        frameRate.canonicalRetentionProofSummaryForDiagnostics());
        if (nativeSourceImageObserver != null)
            Log.i(TAG, "Native source-image observation generator=" + generatorId +
                    " " + nativeSourceImageObserver.diagnostic());
        if (nativeEndpointProvenance != null)
            Log.i(TAG, "Native endpoint provenance generator=" + generatorId +
                    " " + nativeEndpointProvenanceDiagnostic() + " external=" +
                    (externalTransport == null ? "none" : externalTransport.sourceProvenanceDiagnostic()));
        sourceDiagWindowStartNanos = now;
        sourceDiagStartHardwareSubmits = diagHardwareSubmits;
        sourceDiagStartSoftwareSubmits = diagSoftwareSubmits;
        sourceDiagStartUniqueVerdicts = diagUniqueVerdicts;
        sourceDiagStartDuplicateVerdicts = diagDuplicateVerdicts;
        sourceDiagStartUniqueFrames = uniqueFrameCount;
        sourceDiagStartEndpoints = endpointSequence;
        sourceDiagStartCandidateUnavailable = endpointCandidateUnavailable;
        sourceDiagStartTimestampCorrections = endpointTimestampCorrections;
        sourceDiagStartFifoCoalesced = endpointFifoCoalesced;
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
                " leftTs=" + activeLeftTimestampNs +
                " rightTs=" + activeRightTimestampNs +
                " pairReady=" + activePairReady +
                " motionReady=" + motionEstimateReady +
                " fifoCount=" + endpointFifoCount +
                " fifoHead=" + fifoHeadSequence +
                " targetSourceNs=" + frameRate.bufferedSelectedTargetSourceNs() +
                " controllerPrimed=" + frameRate.bufferedPrimed() +
                " controllerLeft=" + frameRate.bufferedRetainedLeftSequence() +
                " controllerRight=" + frameRate.bufferedRetainedRightSequence() +
                " expectedAdvance=" + frameRate.bufferedExpectedAdvance() +
                " credits=" + frameRate.bufferedOutputCredits() +
                " minimumReprime=" + frameRate.bufferedMinimumReprimeSequence() +
                " unavailable=" + frameRate.bufferedUnavailableSlotCount() +
                " underruns=" + frameRate.bufferedUnderrunCount() +
                " coalesced=" + endpointFifoCoalesced);
    }

    private void logBufferedEpochBoundary(String stage, long previousEpoch) {
        Log.w(TAG, "Buffered presentation epoch reset" +
                " generator=" + generatorId +
                " stage=" + stage +
                " reason=" + frameRate.bufferedLastEpochReason() +
                " previousEpoch=" + previousEpoch +
                " epoch=" + frameRate.bufferedPresentationEpoch() +
                " source=" + frameRate.lockedSourceFps() +
                " output=" + frameRate.outputFps() +
                " left=" + activeLeftSequence +
                " right=" + activeRightSequence +
                " leftTs=" + activeLeftTimestampNs +
                " rightTs=" + activeRightTimestampNs +
                " pairReady=" + activePairReady +
                " motionReady=" + motionEstimateReady +
                " fifoCount=" + endpointFifoCount +
                " expectedAdvance=" + frameRate.bufferedExpectedAdvance() +
                " credits=" + frameRate.bufferedOutputCredits() +
                " diagnostic=" + frameRate.bufferedLastMismatchDiagnostic() +
                " minimumReprime=" + frameRate.bufferedMinimumReprimeSequence());
    }

    private void publishReportedFrameRate(double source, double output,
                                          double targetOutput,
                                          boolean cadenceQualified) {
        int sourceTenths = (int) Math.max(0L, Math.round(source * 10.0));
        int outputTenths = (int) Math.max(0L, Math.round(output * 10.0));
        int targetTenths = (int) Math.max(0L, Math.round(targetOutput * 10.0));
        String backendLabel = activeBackendLabel();
        reportedMeasuredTier = frameRate.tierAcquiredForDiagnostics() &&
                !frameRate.usesAuthoritativeSourceRate() ?
                frameRate.lockedSourceFps() : 0;
        // A core that runs at full speed while its game updates every Nth
        // frame (Ocarina: 60 submissions, 20 unique) is an exact duplicate
        // schedule and must never be paced down.  A core whose unique clock
        // is an irregular fraction of its submission clock (Dolphin tonight:
        // 60 calls, 57.8 unique with 4 percent held frames) is failing its
        // clock and is the pacing case.
        double submission = frameRate.measuredSubmissionHz();
        // The MEASURED unique-image rate, not presentationSourceHz(): the
        // latter keeps the previously qualified clock (PSP run psp-b52b: a
        // 30-fps section still reported the earlier 60-Hz lattice, so
        // 60/60 = 1 read as irregular and the probe paced a regular 2:1
        // stream down to 40).
        double unique = frameRate.measuredProducerHz();
        boolean irregular = false;
        if (submission > 1.0 && unique > 1.0) {
            double ratio = submission / unique;
            long nearest = Math.round(ratio);
            // 0.06 (was 0.02): melonDS's exact 2:1 schedule measured 2.03
            // on one-second buckets and the load-hold probe paced the DS
            // down to 20 (run nds-b50b, 2026-09-02).  A genuinely
            // irregular stream (Dolphin 60/57.8 = 1.04, Flycast 60/53 =
            // 1.13) is nowhere near an integer ratio.
            irregular = nearest < 2L || Math.abs(ratio - nearest) > 0.06;
        }
        // A stream that accepted no endpoints in the admission window (DS on
        // melonDS, run nds-b51: 60 submits, 0 unique) has no delivery rate
        // to downgrade to; the probe must never pace it (it paced the DS to
        // 20 against a static top screen).
        if (reportedAdmissionAcceptedEndpoints <= 0L) irregular = false;
        // A core submitting on its 60-Hz lattice with fewer than ~10 percent
        // held frames (Metroid Prime on Dolphin: 60 submits, 55-58 unique at
        // ANY pace) keeps that lattice through the bridged held-frame proof;
        // pacing it to 40 only trades 60->120 x2 for a 37.5-unique 40 lattice
        // (gc-b50b, gc-b52).  Leave it to the canonical acquisition.
        // Wii U run wiiu-b56b (2026-09-02): NES Remix hovered 52-59 unique of
        // 60 for an hour, unqualified, straddling this threshold, so the
        // host's evidence streak reset every few seconds and the downgrade
        // probe never re-fired after its lift.  The light-hold band is now
        // reported separately; the host demands a much longer unqualified
        // streak for it instead of ignoring it.
        boolean lightlyHeld = irregular && submission >= 59.0 && unique >= 55.0;
        if (lightlyHeld) irregular = false;
        reportedStreamLightlyHeld = lightlyHeld;
        reportedStreamIrregular = irregular;
        reportedUniqueHz = unique;
        reportedClockAcquisitionInProgress =
                frameRate.canonicalReacquireEvidenceNsForDiagnostics() > 0L ||
                frameRate.canonicalReacquireCandidateHzForDiagnostics() > 0.0;
        reportedPanelClockRatio = frameRate.panelClockRatio();
        reportedEndpointDriftUsPerS = frameRate.endpointDriftUsPerSecond();
        reportedEndpointOffsetNs = frameRate.endpointOffsetNs();
        if (sourceTenths == reportedSourceTenths &&
                outputTenths == reportedOutputTenths &&
                targetTenths == reportedTargetTenths &&
                cadenceQualified == reportedCadenceQualified &&
                backendLabel.equals(reportedBackendLabel)) return;
        reportedSourceTenths = sourceTenths;
        reportedOutputTenths = outputTenths;
        reportedTargetTenths = targetTenths;
        reportedCadenceQualified = cadenceQualified;
        reportedBackendLabel = backendLabel;
        FrameGenerationRenderer.StatsListener callback = statsListener;
        if (callback != null) callback.onFrameRate(source, targetOutput, output,
                cadenceQualified);
        Log.i(TAG, "Frame rate committed source=" +
                String.format(java.util.Locale.US, "%.1f", source) +
                " target=" + String.format(java.util.Locale.US, "%.3f",
                        targetOutput) +
                " actual=" + String.format(java.util.Locale.US, "%.3f",
                        output) +
                " cadenceQualified=" + (cadenceQualified ? 1 : 0) +
                " backend=" + backendLabel + " FPS");
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

    private void reopenUnusedSoftwareTransport(int width, int height) {
        if (submittedFrameCount != 0 || !externalTransport.usesAppOwnedPresentation() ||
                !appOwnedPhysicalPending.isEmpty())
            throw new IllegalStateException("Native geometry requires an unused private transport");
        // No endpoint has been exported. Drain constructor GPU work before
        // destroying its EGL producer and ImageReader; keep the emulator's
        // input Surface and the visible output Surface unchanged.
        externalTransport.close();
        externalTransport = null;
        if (!EGL14.eglDestroySurface(eglDisplay, eglEndpointSurface))
            fail("eglDestroySurface(native-geometry)");
        eglEndpointSurface = EGL14.EGL_NO_SURFACE;
        try {
            externalTransport = externalTransportFactory.open(outputSurface, handler, width, height);
        } catch (Exception failure) {
            throw new IllegalStateException("Native software transport initialization failed", failure);
        }
        if (!externalTransport.usesAppOwnedPresentation() ||
                externalTransport.endpointWidth() != width || externalTransport.endpointHeight() != height)
            throw new IllegalStateException("Native software transport geometry mismatch");
        registerExternalPreparationCapacityListener();
        eglEndpointSurface = EGL14.eglCreateWindowSurface(eglDisplay, endpointEglConfig,
                externalTransport.endpointSurface(), new int[]{EGL14.EGL_NONE}, 0);
        if (eglEndpointSurface == EGL14.EGL_NO_SURFACE) fail("eglCreateWindowSurface(native-geometry)");
        if (!EGL14.eglMakeCurrent(eglDisplay, eglEndpointSurface, eglEndpointSurface, eglContext) ||
                !EGL14.eglSwapInterval(eglDisplay, externalTransportFactory.endpointSwapInterval()) ||
                !EGL14.eglMakeCurrent(eglDisplay, eglSurface, eglSurface, eglContext))
            fail("eglConfigureSurface(native-geometry)");
        Log.i(TAG, "External native software geometry width=" + width + " height=" + height);
    }

    private void releaseGl() {
        discardFullImageCapture();
        closeNativeSourceImageObserver();
        RuntimeException transportCloseFailure = null;
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
        EGLSurface workingSurface = workingEglSurface();
        if (eglDisplay != EGL14.EGL_NO_DISPLAY && eglContext != EGL14.EGL_NO_CONTEXT &&
                workingSurface != EGL14.EGL_NO_SURFACE)
            EGL14.eglMakeCurrent(eglDisplay, workingSurface, workingSurface, eglContext);
        ExternalFrameGenerationTransport transport = externalTransport;
        if (transport != null && transport.usesAppOwnedPresentation()) {
            // The native private pool owns EGLImages and GL completion fences
            // created by this exact context. Retire it while that context is
            // current; waiting here is an explicit teardown boundary, never a
            // live presentation-path GPU wait.
            try {
                transport.close();
            } catch (RuntimeException failure) {
                transportCloseFailure = failure;
            } finally {
                externalTransport = null;
            }
        }
        if (physicalPresentationTracker != null) {
            physicalPresentationTracker.close();
            physicalPresentationTracker = null;
        }
        appOwnedPhysicalPending.clear();
        if (externalSignatureTimer != null) {
            externalSignatureTimer.discardPending();
            externalSignatureTimer.close();
            externalSignatureTimer = null;
        }
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
        if (externalGeneratedTexture != 0)
            GLES20.glDeleteTextures(1, new int[]{externalGeneratedTexture}, 0);
        if (copyProgram != 0) GLES20.glDeleteProgram(copyProgram);
        if (textureCopyProgram != 0) GLES20.glDeleteProgram(textureCopyProgram);
        if (externalGeneratedTextureCopyProgram != 0)
            GLES20.glDeleteProgram(externalGeneratedTextureCopyProgram);
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
            if (denseBoxTextures[direction][0] != 0)
                GLES20.glDeleteTextures(2, denseBoxTextures[direction], 0);
        }
        if (denseValidatedTextures[0] != 0)
            GLES20.glDeleteTextures(2, denseValidatedTextures, 0);
            GLES20.glDeleteTextures(2, denseFillTextures, 0);
        if (denseGlobalCoarseCostTextures[0] != 0)
            GLES20.glDeleteTextures(2, denseGlobalCoarseCostTextures, 0);
        if (denseGlobalFineCostTextures[0] != 0)
            GLES20.glDeleteTextures(2, denseGlobalFineCostTextures, 0);
        if (denseGlobalCoarseSeedTextures[0] != 0)
            GLES20.glDeleteTextures(2, denseGlobalCoarseSeedTextures, 0);
        if (denseGlobalSeedTextures[0] != 0)
            GLES20.glDeleteTextures(2, denseGlobalSeedTextures, 0);
            GLES20.glDeleteTextures(2, denseGlobalCutTextures, 0);
        if (densePyramidProgram != 0) GLES20.glDeleteProgram(densePyramidProgram);
        if (denseGlobalCostProgram != 0)
            GLES20.glDeleteProgram(denseGlobalCostProgram);
        if (denseGlobalReduceProgram != 0)
            GLES20.glDeleteProgram(denseGlobalReduceProgram);
        if (denseGlobalCutProgram != 0)
            GLES20.glDeleteProgram(denseGlobalCutProgram);
        if (denseSolveProgram != 0) GLES20.glDeleteProgram(denseSolveProgram);
        if (denseCycleProgram != 0) GLES20.glDeleteProgram(denseCycleProgram);
        if (denseFillProgram != 0) GLES20.glDeleteProgram(denseFillProgram);
        if (denseQ8ProbeProgram != 0) GLES20.glDeleteProgram(denseQ8ProbeProgram);
        if (proofAtlasHeaderProgram != 0)
            GLES20.glDeleteProgram(proofAtlasHeaderProgram);
        if (denseDiagnosticPackProgram != 0)
            GLES20.glDeleteProgram(denseDiagnosticPackProgram);
        if (eglDisplay != EGL14.EGL_NO_DISPLAY) {
            EGL14.eglMakeCurrent(eglDisplay, EGL14.EGL_NO_SURFACE,
                    EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
            if (eglEndpointSurface != EGL14.EGL_NO_SURFACE)
                EGL14.eglDestroySurface(eglDisplay, eglEndpointSurface);
            if (eglSurface != EGL14.EGL_NO_SURFACE)
                EGL14.eglDestroySurface(eglDisplay, eglSurface);
            if (eglContext != EGL14.EGL_NO_CONTEXT)
                EGL14.eglDestroyContext(eglDisplay, eglContext);
            EGL14.eglTerminate(eglDisplay);
        }
        transport = externalTransport;
        externalTransport = null;
        if (transport != null) {
            try {
                transport.close();
            } catch (RuntimeException failure) {
                if (transportCloseFailure == null)
                    transportCloseFailure = failure;
                else
                    transportCloseFailure.addSuppressed(failure);
            }
        }
        eglEndpointSurface = EGL14.EGL_NO_SURFACE;
        eglSurface = EGL14.EGL_NO_SURFACE;
        eglContext = EGL14.EGL_NO_CONTEXT;
        eglDisplay = EGL14.EGL_NO_DISPLAY;
        Log.i(TAG, "Frame generator detached presents=" + presents +
                " generated=" + generatedPresents + " real=" + realFrameCount +
                " submitted=" + submittedFrameCount);
        if (transportCloseFailure != null) throw transportCloseFailure;
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

    private static final class AppOwnedPhysicalPending {
        final long frameId;
        final FrameGenerationPresentationRequest request;
        final ExternalFrameGenerationTransport.AppOwnedOutput generatedOutput;
        final long bindWallNs;
        final long swapWallNs;
        final long submissionStartedNs;
        final long swapStartedNs;
        final long swapCompletedNs;
        final int scansPerOutput;
        final long panelPeriodNs;

        AppOwnedPhysicalPending(
                long frameId, FrameGenerationPresentationRequest request,
                ExternalFrameGenerationTransport.AppOwnedOutput generatedOutput,
                long bindWallNs, long swapWallNs,
                long submissionStartedNs, long swapStartedNs,
                long swapCompletedNs,
                int scansPerOutput, long panelPeriodNs) {
            if (frameId <= 0L || request == null || bindWallNs <= 0L ||
                    swapWallNs <= 0L || submissionStartedNs <= 0L ||
                    swapStartedNs < submissionStartedNs ||
                    swapCompletedNs < swapStartedNs ||
                    scansPerOutput <= 0 ||
                    panelPeriodNs <= 0L ||
                    request.isGenerated() != (generatedOutput != null) ||
                    (generatedOutput != null &&
                            generatedOutput.request != request))
                throw new IllegalArgumentException(
                        "app-owned physical row identity is invalid");
            this.frameId = frameId;
            this.request = request;
            this.generatedOutput = generatedOutput;
            this.bindWallNs = bindWallNs;
            this.swapWallNs = swapWallNs;
            this.submissionStartedNs = submissionStartedNs;
            this.swapStartedNs = swapStartedNs;
            this.swapCompletedNs = swapCompletedNs;
            this.scansPerOutput = scansPerOutput;
            this.panelPeriodNs = panelPeriodNs;
        }
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
