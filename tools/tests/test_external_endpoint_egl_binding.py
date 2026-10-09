"""Execute actual EGL setup/export/retirement against recording platform leaves.

These tests prove binding ownership and preserved export ordering, not Android
driver stability, physical scanout, useful generated pixels, or guest clocks.
The full production methods are compiled unchanged; only Android/GL and unrelated
resource leaves are stubbed. No fake success result is used as device evidence.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"


class ExternalEndpointEglBindingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        signatures = [
            "private boolean appOwnsVisiblePresentation()",
            "private void initializeEgl()",
            "private void publishExternalEndpoint(",
            "private void releaseGl()",
        ]
        # The pre-fix implementation has no helper. Retaining it verbatim lets
        # the behavior tests fail on its real bindings, not missing-symbol noise.
        if "private EGLSurface workingEglSurface()" in source:
            signatures.append("private EGLSurface workingEglSurface()")
        actual = "\n".join(method(source, signature) for signature in signatures)
        release = method(source, "private void releaseGl()")
        scalar_names = sorted(set(re.findall(r"if \((\w+) != 0\)", release)))
        scalars = "\n".join("int " + name + ";" for name in scalar_names)
        fixture = r'''
import java.util.*;
public class EglBindingFixture {
    static final List<String> trace = new ArrayList<>();
    static void check(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason + " trace=" + trace);
    }
    static class EGLDisplay {}
    static class EGLContext {}
    static class EGLConfig {}
    static class EGLSurface {
        final String name; boolean destroyed;
        EGLSurface(String value) { name=value; }
        public String toString() { return name; }
    }
    static class Surface {
        final String name;
        Surface(String value) { name=value; }
        void release() { trace.add("surface-release:"+name); }
    }
    static class EGL14 {
        static final EGLDisplay EGL_NO_DISPLAY=new EGLDisplay();
        static final EGLContext EGL_NO_CONTEXT=new EGLContext();
        static final EGLSurface EGL_NO_SURFACE=new EGLSurface("none");
        static final int EGL_DEFAULT_DISPLAY=0,EGL_RENDERABLE_TYPE=1,
            EGL_SURFACE_TYPE=2,EGL_WINDOW_BIT=4,EGL_PBUFFER_BIT=8,EGL_RED_SIZE=9,
            EGL_GREEN_SIZE=10,EGL_BLUE_SIZE=11,EGL_ALPHA_SIZE=12,EGL_NONE=13,
            EGL_CONTEXT_CLIENT_VERSION=14,EGL_WIDTH=15,EGL_HEIGHT=16;
        static EGLSurface current=EGL_NO_SURFACE;
        static EGLContext context=EGL_NO_CONTEXT;
        static String failAt="";
        static int binds, swaps, destroys;
        static EGLDisplay eglGetDisplay(int ignored) { return new EGLDisplay(); }
        static boolean eglInitialize(EGLDisplay d,int[] a,int b,int[] c,int e){return true;}
        static boolean eglChooseConfig(EGLDisplay d,int[] a,int b,EGLConfig[] c,
                int e,int f,int[] count,int g) { c[0]=new EGLConfig();count[0]=1;return true; }
        static EGLContext eglCreateContext(EGLDisplay d,EGLConfig c,EGLContext x,int[] a,int b){
            return new EGLContext();
        }
        static EGLSurface eglCreateWindowSurface(EGLDisplay d,EGLConfig c,Surface s,int[] a,int b){
            trace.add("create:"+s.name);return new EGLSurface(s.name);
        }
        static EGLSurface eglCreatePbufferSurface(EGLDisplay d,EGLConfig c,int[] a,int b){
            trace.add("create:pbuffer");return new EGLSurface("pbuffer");
        }
        static boolean eglMakeCurrent(EGLDisplay d,EGLSurface draw,EGLSurface read,EGLContext c){
            ++binds;trace.add("bind:"+draw);
            check(draw==read && !draw.destroyed,"invalid EGL binding");
            if (failAt.equals("bind:"+draw)) return false;
            current=draw;context=c;return true;
        }
        static boolean eglSwapInterval(EGLDisplay d,int interval){
            trace.add("interval:"+current+":"+interval);return true;
        }
        static boolean eglSwapBuffers(EGLDisplay d,EGLSurface surface){
            check(current==surface,"swap is not current surface");
            trace.add("swap:"+surface);++swaps;return !failAt.equals("swap");
        }
        static boolean eglDestroySurface(EGLDisplay d,EGLSurface s){
            check(!s.destroyed && current!=s,"duplicate/current surface destroy");
            s.destroyed=true;++destroys;trace.add("destroy:"+s);return true;
        }
        static boolean eglDestroyContext(EGLDisplay d,EGLContext c){
            check(context!=c,"destroy current context");trace.add("destroy-context");return true;
        }
        static boolean eglTerminate(EGLDisplay d){trace.add("terminate");return true;}
    }
    static class EGLExt {
        static long timestamp;
        static boolean eglPresentationTimeANDROID(EGLDisplay d,EGLSurface s,long value){
            check(EGL14.current==s,"timestamp on noncurrent export surface");
            timestamp=value;trace.add("pts:"+value);return !EGL14.failAt.equals("timestamp");
        }
    }
    static class GLES20 {
        static final int GL_FRAMEBUFFER=1,GL_COLOR_BUFFER_BIT=2;
        static void glBindFramebuffer(int target,int name){trace.add("fbo:"+name);}
        static void glViewport(int x,int y,int width,int height){trace.add("viewport:"+x+":"+y+":"+width+":"+height);}
        static void glClearColor(float r,float g,float b,float a){}
        static void glClear(int bits){trace.add("clear");}
        static void glGetIntegerv(int name,int[] values,int offset){values[offset]=name==GL_MAJOR_VERSION?3:0;}
        static void glDeleteFramebuffers(int n,int[] names,int o){deleting();}
        static void glDeleteTextures(int n,int[] names,int o){deleting();}
        static void glDeleteProgram(int name){deleting();}
        static void deleting(){check(EGL14.context!=EGL14.EGL_NO_CONTEXT,"GL deletion without context");trace.add("gl-delete");}
    }
    static class Build { static class VERSION { static final int SDK_INT=33; } }
    static class Log { static void i(String tag,String value){trace.add("log");} }
    static class Lease {long lease(int slot){return 7L;}}
    static class ExternalFrameGenerationTransport {
        final boolean appOwned;boolean closed;long sequence,timestamp;
        ExternalFrameGenerationTransport(boolean value){appOwned=value;}
        boolean usesAppOwnedPresentation(){return appOwned;}
        Surface endpointSurface(){return new Surface("endpoint");}
        int endpointWidth(){return 1920;}
        int endpointHeight(){return 1080;}
        void expectEndpoint(long seq,long pts,Lease values,int slot,long lease){
            sequence=seq;timestamp=pts;trace.add("expect:"+seq+":"+pts+":"+lease);
        }
        void cancelExpectedEndpoint(long seq){check(seq==sequence,"cancel wrong endpoint");trace.add("cancel:"+seq);}
        void close(){
            if(appOwned)check(EGL14.current.name.equals("output"),"RIFE close lost its visible context");
            closed=true;trace.add("transport-close");
        }
    }
    static class Closable {
        final String name;Closable(String value){name=value;}
        void close(){check(EGL14.context!=EGL14.EGL_NO_CONTEXT,"timer close without context");trace.add("close:"+name);}
        void discardPending(){}
        void recycle(){}
    }
    static class SurfaceTexture {void setOnFrameAvailableListener(Object o){} void release(){}}
    static class Choreographer {void removeFrameCallback(Object o){}}
    static final int EGL_OPENGL_ES3_BIT_KHR=64,EGL_OPENGL_ES2_BIT=4,
        GL_MAJOR_VERSION=3,GL_MINOR_VERSION=4,NATIVE_ADMISSION_SLOT=8,
        SIGNATURE_CANDIDATE_SLOTS=6,ENDPOINT_FIFO_CAPACITY=6,DENSE_LEVELS=3;
    static final String TAG="test";
    EGLDisplay eglDisplay=EGL14.EGL_NO_DISPLAY;
    EGLContext eglContext=EGL14.EGL_NO_CONTEXT;
    EGLSurface eglSurface=EGL14.EGL_NO_SURFACE,eglEndpointSurface=EGL14.EGL_NO_SURFACE;
    final Surface outputSurface=new Surface("output");Surface inputSurface;
    ExternalFrameGenerationTransport externalTransport;
    Lease nativeEndpointProvenance=new Lease();
    int requestedEglContextMajor=3,actualEglContextMajor,actualEglContextMinor;
    boolean denseV28ReducedAnalysisRequested;
    int outputWidth=1920,outputHeight=1080,historyWidth=1280,historyHeight=720;
    float presentationAspect=16f/9f;
    Choreographer choreographer;SurfaceTexture inputTexture;
    Closable physicalPresentationTracker,externalSignatureTimer,denseGpuTimer,softwareUploadBitmap;
    final List<Object> appOwnedPhysicalPending=new ArrayList<>();
    int presents,generatedPresents,realFrameCount,submittedFrameCount;
    final int[] historyTextures=new int[2],signatureCandidateTextures=new int[6],
        endpointFifoTextures=new int[6],flowTextures=new int[3],reverseFlowTextures=new int[3],
        globalCandidateTextures=new int[2],globalCandidateWinnerTextures=new int[2],
        globalFlowTextures=new int[2],denseValidatedTextures=new int[2],denseFillTextures=new int[2],
        denseGlobalCoarseCostTextures=new int[2],denseGlobalFineCostTextures=new int[2],
        denseGlobalCoarseSeedTextures=new int[2],denseGlobalSeedTextures=new int[2],denseGlobalCutTextures=new int[2];
    final int[][][] denseFlowTextures=new int[2][3][2];
    final int[][] densePyramidTextures=new int[2][2],denseBoxTextures=new int[2][2];
    void fail(String where){throw new IllegalStateException(where);}
    void checkGl(String where){if(EGL14.failAt.equals("render"))throw new IllegalStateException(where);}
    void drawTexture2d(int source){check(EGL14.current==eglEndpointSurface,"render outside endpoint surface");trace.add("draw:"+source);}
    void closeNativeSourceImageObserver(){}
    SCALAR_FIELDS
    PRODUCTION_METHODS
    static EglBindingFixture initialized(boolean appOwned){
        EglBindingFixture t=new EglBindingFixture();
        t.externalTransport=new ExternalFrameGenerationTransport(appOwned);t.initializeEgl();return t;
    }
    static void initCase(boolean appOwned){
        EglBindingFixture t=initialized(appOwned);
        check(EGL14.current==(appOwned?t.eglSurface:t.eglEndpointSurface),"wrong working surface after initialize");
        check(t.eglSurface!=t.eglEndpointSurface,"surface handles must not alias");
        check(trace.contains("interval:endpoint:0"),"endpoint lost zero swap interval");
        check(EGL14.swaps==0,"setup submitted an unannounced endpoint");
    }
    static void exportCase(boolean appOwned,String failure){
        EglBindingFixture t=initialized(appOwned);
        // Isolate export behavior even on the pre-fix setup implementation.
        EGL14.current=appOwned?t.eglSurface:t.eglEndpointSurface;
        trace.clear();EGL14.binds=0;EGL14.swaps=0;EGL14.failAt=failure;
        RuntimeException caught=null;
        try{t.publishExternalEndpoint(42,19,123456789123L);}catch(RuntimeException ex){caught=ex;}
        check((caught==null)==failure.isEmpty(),"failure propagation changed");
        check(EGL14.binds==(appOwned?2:0),"unnecessary export surface transition");
        check(EGL14.current==(appOwned?t.eglSurface:t.eglEndpointSurface),"export restored wrong working surface");
        check(trace.get(0).equals("expect:19:123456789123:7"),"identity not announced first");
        check(trace.contains("draw:42") && trace.contains("clear"),"endpoint rendering skipped");
        check(trace.contains("viewport:0:0:1920:1080"),"endpoint geometry changed");
        check(EGLExt.timestamp==123456789123L,"endpoint timestamp changed");
        check(trace.contains("cancel:19")==!failure.isEmpty(),"expected endpoint cancellation changed");
        check(EGL14.swaps==((failure.equals("timestamp")||failure.equals("render"))?0:1),"swap count changed");
        check(t.externalTransport.timestamp==EGLExt.timestamp,"announced and exported PTS differ");
        check(trace.indexOf("draw:42")<trace.indexOf("pts:123456789123"),"timestamp precedes endpoint rendering");
        if(EGL14.swaps>0)check(trace.indexOf("pts:123456789123")<trace.indexOf("swap:endpoint"),"swap precedes endpoint timestamp");
    }
    static void bindFailureCase(boolean restore){
        EglBindingFixture t=initialized(true);trace.clear();EGL14.binds=0;EGL14.swaps=0;
        EGL14.failAt=restore?"bind:output":"bind:endpoint";
        RuntimeException caught=null;
        try{t.publishExternalEndpoint(42,19,123456789123L);}catch(RuntimeException ex){caught=ex;}
        check(caught!=null,"failed make-current swallowed");
        check(EGL14.binds==2,"app-owned failed bind did not attempt restore exactly once");
        check(trace.contains("cancel:19")==!restore,"cancel must track submitted image, not restore success");
        check(EGL14.swaps==(restore?1:0),"failed bind changed submission ownership");
        check(EGL14.current==(restore?t.eglEndpointSurface:t.eglSurface),"unexpected context after failed bind");
    }
    static void builtInCase(){
        EglBindingFixture t=new EglBindingFixture();t.initializeEgl();
        check(EGL14.current==t.eglSurface && t.eglEndpointSurface==EGL14.EGL_NO_SURFACE,"built-in output routing changed");
        check(!trace.contains("create:pbuffer") && !trace.contains("create:endpoint"),"built-in created external surface");
        t.releaseGl();check(EGL14.destroys==1,"built-in surface not retired once");
    }
    static void releaseCase(boolean appOwned){
        EglBindingFixture t=initialized(appOwned);ExternalFrameGenerationTransport transport=t.externalTransport;
        EGLSurface endpoint=t.eglEndpointSurface,working=t.eglSurface;
        t.externalSignatureTimer=new Closable("signature");t.denseGpuTimer=new Closable("dense");
        t.frameBuffer=12;trace.clear();EGL14.binds=0;t.releaseGl();
        check(trace.get(0).equals("bind:"+(appOwned?"output":"endpoint")),"retirement rebound unnecessary pbuffer");
        check(trace.indexOf("close:signature")<trace.indexOf("bind:none"),"timer retired after unbind");
        check(EGL14.destroys==2 && endpoint.destroyed && working.destroyed,"distinct surfaces not each destroyed once");
        check(transport.closed && t.externalTransport==null,"transport not closed");
        check(t.eglDisplay==EGL14.EGL_NO_DISPLAY && t.eglContext==EGL14.EGL_NO_CONTEXT &&
              t.eglEndpointSurface==EGL14.EGL_NO_SURFACE && t.eglSurface==EGL14.EGL_NO_SURFACE,"stale EGL handles");
        if(appOwned)check(trace.indexOf("transport-close")<trace.indexOf("bind:none"),"RIFE native close after unbind");
        else check(trace.indexOf("transport-close")>trace.indexOf("terminate"),"external retirement ordering changed");
    }
    public static void main(String[] args){
        boolean appOwned=args[1].equals("app");
        if(args[0].equals("init"))initCase(appOwned);
        else if(args[0].equals("release"))releaseCase(appOwned);
        else if(args[0].equals("bind-failure"))bindFailureCase(args[2].equals("restore"));
        else if(args[0].equals("built-in"))builtInCase();
        else exportCase(appOwned,args.length>2?args[2]:"");
    }
}
'''.replace("SCALAR_FIELDS", scalars).replace("PRODUCTION_METHODS", actual)
        cls.tmp = tempfile.TemporaryDirectory(prefix="emufusion-egl-binding-host-")
        cls.addClassCleanup(cls.tmp.cleanup)
        fixture_path = Path(cls.tmp.name) / "EglBindingFixture.java"
        fixture_path.write_text(fixture)
        subprocess.run([str(JAVA / "javac"), str(fixture_path)], check=True,
                       capture_output=True, text=True)

    def run_case(self, *args):
        run = subprocess.run([str(JAVA / "java"), "-cp", self.tmp.name,
                              "EglBindingFixture", *args], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_external_setup_keeps_endpoint_current(self):
        self.run_case("init", "external")

    def test_app_owned_setup_keeps_visible_output_current(self):
        self.run_case("init", "app")

    def test_external_export_never_switches_surface(self):
        for failure in ("", "timestamp", "render", "swap"):
            with self.subTest(failure=failure):
                self.run_case("export", "external", failure)

    def test_app_owned_export_preserves_switch_restore_and_cancellation(self):
        for failure in ("", "timestamp", "render", "swap"):
            with self.subTest(failure=failure):
                self.run_case("export", "app", failure)

    def test_external_retirement_preserves_endpoint_context_and_distinct_handles(self):
        self.run_case("release", "external")

    def test_app_owned_retirement_closes_native_before_context(self):
        self.run_case("release", "app")

    def test_app_owned_bind_failures_keep_submission_and_cancellation_distinct(self):
        for where in ("export", "restore"):
            with self.subTest(where=where):
                self.run_case("bind-failure", "app", where)

    def test_non_external_renderer_preserves_visible_surface_lifetime(self):
        self.run_case("built-in", "app")


if __name__ == "__main__":
    unittest.main()
