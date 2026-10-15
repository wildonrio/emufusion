"""GPU dense inverse search (DIS) optical flow as GLSL ES 3.00 passes.

Method: Kroeger et al., "Fast Optical Flow using Dense Inverse Search"
(ECCV 2016), implemented from the paper's description. Per pyramid level,
coarse to fine: every 8x8 patch on a 3-px grid aligns itself to the target
image by inverse-compositional Gauss-Newton (6 iterations, mean-normalised
intensities, starting from the coarser level's flow and keeping the start if
the result is worse); a densification pass gives every pixel the
photometric-error-weighted mean of the patch flows that cover it.

All passes work in GL texel coordinates (no orientation conversion needed:
the method is coordinate-free). Flows are RGBA16F (u, v in pixels of their
level). Shared by DenseInverseSearchFlow.java (via the generated
DenseInverseSearchShaders.java) and the desktop harness (dis_eval.py).
"""

PATCH = 8
STRIDE = 3
ITERATIONS = 6

HEADER = "#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n"

VERTEX = (
    "#version 300 es\n"
    "void main(){vec2 p=vec2(gl_VertexID==1?3.0:-1.0,gl_VertexID==2?3.0:-1.0);"
    "gl_Position=vec4(p,0.0,1.0);}\n")

VERTEX_QUAD = (
    "#version 300 es\n"
    "in vec2 aPosition;in vec2 aTexCoord;out vec2 vTexCoord;\n"
    "void main(){gl_Position=vec4(aPosition,0.0,1.0);vTexCoord=aTexCoord;}\n")

# Luma of the history image box-filtered by uDivisor (1, 2 or 4) into R8.
GRAY = (HEADER +
        "uniform sampler2D uIn0;uniform vec2 uTexel;uniform int uDivisor;\n"
        "layout(location=0) out vec4 o0;\n"
        "float l(vec2 c){return dot(texture(uIn0,c).rgb,vec3(0.299,0.587,0.114));}\n"
        "void main(){vec2 c=gl_FragCoord.xy*float(uDivisor)*uTexel;float y;\n"
        " if(uDivisor==1)y=l(c);\n"
        " else if(uDivisor==2)y=l(c);\n"  # one bilinear tap at a 2x2 block's shared corner
        " else y=0.25*(l(c+vec2(-uTexel.x,-uTexel.y))+l(c+vec2(uTexel.x,-uTexel.y))+"
        "l(c+vec2(-uTexel.x,uTexel.y))+l(c+vec2(uTexel.x,uTexel.y)));\n"
        " o0=vec4(y,0.0,0.0,1.0);}\n")

# 2x2 mean (edge-clamped) for the next pyramid level.
DOWN = (HEADER +
        "uniform sampler2D uIn0;uniform ivec2 uIn;\n"
        "layout(location=0) out vec4 o0;\n"
        "float f(ivec2 q){return texelFetch(uIn0,clamp(q,ivec2(0),uIn-1),0).r;}\n"
        "void main(){ivec2 p=ivec2(gl_FragCoord.xy)*2;"
        "o0=vec4(0.25*(f(p)+f(p+ivec2(1,0))+f(p+ivec2(0,1))+f(p+ivec2(1,1))),0.0,0.0,1.0);}\n")

# Per level and real frame: intensity and its central-difference gradient in
# one RGBA16F texel, so the patch search keeps no per-pixel arrays (on Adreno
# a 64-entry template array spilled registers and the search ran 5x slower).
GRAD = (HEADER +
    "uniform sampler2D uIn0;uniform ivec2 uSize;\n"
    "layout(location=0) out vec4 o0;\n"
    "float f(ivec2 q){return texelFetch(uIn0,clamp(q,ivec2(0),uSize-1),0).r;}\n"
    "void main(){ivec2 q=ivec2(gl_FragCoord.xy);\n"
    " o0=vec4(f(q),0.5*(f(q+ivec2(1,0))-f(q-ivec2(1,0))),0.5*(f(q+ivec2(0,1))-f(q-ivec2(0,1))),0.0);}\n")


# At the coarsest level (no coarser flow) every whole-pixel start within this
# radius is scored by mean-normalised SSD and Gauss-Newton starts from the best:
# motion beyond its reach from zero (a sprite moving 48 px per frame is 3 px at
# the coarsest level) was lost. A non-zero start must beat zero motion's error
# by COARSE_BIAS (repetitive texture). Offline over 28 games 0.6% better with
# the cut threshold below (SM3DW 0.347 -> 0.326, PS3 0.612 -> 0.578, N64 0.539
# -> 0.511, Mega Drive 0.539 -> 0.521; Game Gear 0.196 -> 0.204); synthetic
# 48 px sprite over a flat background 0.662 -> 0.020 of a cross-fade.
COARSE_RADIUS = 2
COARSE_BIAS = 0.8


def coarse_search_block():
    if COARSE_RADIUS is None:
        return ""
    R = int(COARSE_RADIUS)
    init = " if(uHasCoarse<0.5){float best=1e30;\n" if COARSE_BIAS is None else (
        " if(uHasCoarse<0.5){float best;{float a=0.0,aa=0.0,at=0.0;for(int y=0;y<P;++y)for(int x=0;x<P;++x){ivec2 q=o+ivec2(x,y);\n"
        "   float w=tg(vec2(q)+0.5),t=r(q).x;a+=w;aa+=w*w;at+=w*t;}\n"
        f"   best={float(COARSE_BIAS)}*(aa-a*a/N+(stt-st*st/N)-2.0*(at-a*st/N));}}\n")
    return (init +
            f"  for(int dy=-{R};dy<={R};++dy)for(int dx=-{R};dx<={R};++dx){{vec2 c=vec2(float(dx),float(dy));\n"
            "   float a=0.0,aa=0.0,at=0.0;for(int y=0;y<P;++y)for(int x=0;x<P;++x){ivec2 q=o+ivec2(x,y);\n"
            "    float w=tg(vec2(q)+0.5+c),t=r(q).x;a+=w;aa+=w*w;at+=w*t;}\n"
            "   float e=aa-a*a/N+(stt-st*st/N)-2.0*(at-a*st/N);if(e<best){best=e;u0=c;}}}\n")


def patch_search_shader():
    return (HEADER +
    f"#define P {PATCH}\n#define S {STRIDE}\n#define ITERS {ITERATIONS}\n"
    "uniform sampler2D uRef,uTarget,uCoarse;\n"
    "uniform ivec2 uSize;uniform float uHasCoarse;\n"
    "layout(location=0) out vec4 o0;\n"
    "vec3 r(ivec2 q){return texelFetch(uRef,clamp(q,ivec2(0),uSize-1),0).xyz;}\n"
    "float tg(vec2 p){return texture(uTarget,p/vec2(uSize)).r;}\n"
    "void main(){\n"
    " ivec2 o=ivec2(gl_FragCoord.xy)*S;\n"
    " vec2 centre=vec2(o)+0.5*float(P);\n"
    # Start: the coarser level's dense flow at the patch centre, in this level's pixels.
    " vec2 u0=uHasCoarse>0.5?2.0*texture(uCoarse,centre/vec2(uSize)).xy:vec2(0.0);\n"
    " float st=0.0,stt=0.0;vec2 g0=vec2(0.0),g1=vec2(0.0);mat2 h=mat2(0.0);\n"
    " for(int y=0;y<P;++y)for(int x=0;x<P;++x){vec3 v=r(o+ivec2(x,y));\n"
    "  st+=v.x;stt+=v.x*v.x;g0+=v.yz;g1+=v.yz*v.x;h+=mat2(v.y*v.y,v.y*v.z,v.y*v.z,v.z*v.z);}\n"
    " const float N=float(P*P);float m0=st/N;\n" + coarse_search_block() +
    # Mean-normalised: subtract the patch means from both sides.
    " mat2 hn=h-mat2(g0.x*g0.x,g0.x*g0.y,g0.x*g0.y,g0.y*g0.y)/N+mat2(1e-4,0.0,0.0,1e-4);\n"
    " mat2 hi=inverse(hn);\n"
    " vec2 u=u0;\n"
    " for(int k=0;k<ITERS;++k){vec2 s1=vec2(0.0);float sw=0.0;\n"
    "  for(int y=0;y<P;++y)for(int x=0;x<P;++x){ivec2 q=o+ivec2(x,y);float w=tg(vec2(q)+0.5+u);s1+=r(q).yz*w;sw+=w;}\n"
    "  vec2 b=s1-(sw/N)*g0-g1+m0*g0;u-=hi*b;}\n"
    # Keep the start when the search made the patch match worse. Mean-
    # normalised SSD from running sums: one pass over the patch.
    " float a0=0.0,a00=0.0,at0=0.0,a1=0.0,a11=0.0,at1=0.0;\n"
    " for(int y=0;y<P;++y)for(int x=0;x<P;++x){ivec2 q=o+ivec2(x,y);vec2 c=vec2(q)+0.5;float t=r(q).x;\n"
    "  float w0=tg(c+u0),w1=tg(c+u);a0+=w0;a00+=w0*w0;at0+=w0*t;a1+=w1;a11+=w1*w1;at1+=w1*t;}\n"
    " float tt=stt-st*st/N;\n"
    " float e0=a00-a0*a0/N+tt-2.0*(at0-a0*st/N),e1=a11-a1*a1/N+tt-2.0*(at1-a1*st/N);\n"
    " if(e1>e0||any(isnan(u))){u=u0;e1=e0;}\n"
    " o0=vec4(u,e1,1.0);}\n")


# Every pixel: photometric-error-weighted mean of the covering patches' flows.
# Endpoint densification: synthesis 22 keeps 1/max(1, e) at one pixel; the
# per-phase route's instance uses DENSIFY_SHARP (the five-tap error squared).
DENSIFY_POWER = 1
DENSIFY_CROSS = False


def weight_line(power):
    if power == 1:
        return "  float w=1.0/max(1.0,d);"
    if power == 2:
        return "  float m=max(1.0,d);float w=1.0/(m*m);"
    return f"  float w=pow(max(1.0,d),-{float(power)});"


def densify_shader():
    if DENSIFY_CROSS:
        err = ("  float d=0.0;for(int k=0;k<5;++k){ivec2 o=k==0?ivec2(0):k==1?ivec2(1,0):k==2?ivec2(-1,0):"
               "k==3?ivec2(0,1):ivec2(0,-1);\n"
               "   d+=abs(texture(uTarget,(vec2(p+o)+0.5+u)/vec2(uSize)).r-texelFetch(uRef,clamp(p+o,ivec2(0),uSize-1),0).r);}"
               "d*=255.0/5.0;\n")
    else:
        err = "  float d=abs(texture(uTarget,(vec2(p)+0.5+u)/vec2(uSize)).r-i0)*255.0;\n"
    weight = weight_line(DENSIFY_POWER)
    return (HEADER +
    f"#define P {PATCH}\n#define S {STRIDE}\n"
    "uniform sampler2D uRef,uTarget,uPatches;\n"
    "uniform ivec2 uSize,uGrid;\n"
    "layout(location=0) out vec4 o0;\n"
    "void main(){ivec2 p=ivec2(gl_FragCoord.xy);float i0=texelFetch(uRef,p,0).r;\n"
    " ivec2 hi=min(p/S,uGrid-1);ivec2 lo=max((p-P+S)/S,ivec2(0));lo=min(lo,hi);\n"
    " vec2 acc=vec2(0.0);float wsum=0.0;\n"
    " for(int gy=lo.y;gy<=hi.y;++gy)for(int gx=lo.x;gx<=hi.x;++gx){\n"
    "  vec2 u=texelFetch(uPatches,ivec2(gx,gy),0).xy;\n" + err + weight +
    "acc+=w*u;wsum+=w;}\n"
    " o0=vec4(acc/max(wsum,1e-6),0.0,1.0);}\n")

# Output on the generator's quad. The source of x in A is the fixed point of
# p = x - t*F_AC(p) (motion sampled where the content comes from; two steps,
# 1-3% better than sampling at x on the captured hold-out set), likewise in C;
# both samples blend by the phase weights. (Weighting each side by how well
# the other frame's pixel matched its correspondence scored worse.)
GENERATE = (HEADER +
    "uniform sampler2D uFrameA,uFrameC,uFlowAC,uFlowCA;uniform float uT;uniform vec2 uFlowSize;\n"
    "in vec2 vTexCoord;layout(location=0) out vec4 o0;\n"
    "vec2 fac(vec2 p){return texture(uFlowAC,p).xy/uFlowSize;}\n"
    "vec2 fca(vec2 p){return texture(uFlowCA,p).xy/uFlowSize;}\n"
    "void main(){vec2 u=vTexCoord;\n"
    " vec2 p=u-uT*fac(u),q=u-(1.0-uT)*fca(u);\n"
    " p=u-uT*fac(p);q=u-(1.0-uT)*fca(q);p=u-uT*fac(p);q=u-(1.0-uT)*fca(q);\n"
    " o0=vec4((1.0-uT)*texture(uFrameA,p).rgb+uT*texture(uFrameC,q).rgb,1.0);}\n")


# Synthesis 22: DIS motion for the hand-written synthesis. Each analysis cell
# (the solver's grid) gets the 4x4-sample mean of the DIS flow over its
# footprint, in source pixels, clamped to the solver's limit and packed like
# the solver's raw output (signed Q8.8 per component in two bytes). (Their
# vector median scored identically on the Thor: at half the analysis
# resolution the field is already smooth across a cell.)
TO_RAW = (HEADER +
    "uniform sampler2D uFlow;uniform vec2 uScale;uniform float uLimit;uniform ivec2 uOut;\n"
    "layout(location=0) out vec4 o0;\n"
    "vec2 p16(float v){float r=mod(floor(v*256.0+.5)+65536.0,65536.0);return vec2(floor(r/256.0),mod(r,256.0))/255.0;}\n"
    "void main(){vec2 cell=1.0/vec2(uOut);vec2 c=gl_FragCoord.xy*cell;vec2 s=vec2(0.0);\n"
    " for(int y=0;y<4;++y)for(int x=0;x<4;++x)s+=texture(uFlow,c+(vec2(float(x),float(y))-1.5)*0.25*cell).xy;\n"
    " vec2 v=clamp(s/16.0*uScale,-uLimit,uLimit);o0=vec4(p16(v.x),p16(v.y));}\n")


def phase_search_shader():
    """Per-phase symmetric refinement (the REA-studied method: motion estimated at
    the output time). For each 8x8 patch of the output grid at time t, Gauss-
    Newton on A(x - t*v) = C(x + (1-t)*v) (mean-normalised), starting from the
    better of the two DIS proposals at the patch centre; keeps the start when
    the match got worse. Output: v (A->C motion through x at time t, pixels of
    the flow level) and the final SSD."""
    return (HEADER +
    f"#define P {PATCH}\n#define S {STRIDE}\n#define ITERS {ITERATIONS}\n"
    "uniform sampler2D uGradA,uGradC,uFlowAC,uFlowCA;uniform ivec2 uSize;uniform float uT;\n"
    "layout(location=0) out vec4 o0;\n"
    "vec3 ga(vec2 p){return texture(uGradA,p/vec2(uSize)).xyz;}\n"
    "vec3 gc(vec2 p){return texture(uGradC,p/vec2(uSize)).xyz;}\n"
    "vec2 fac(vec2 p){return texture(uFlowAC,p/vec2(uSize)).xy;}\n"
    "vec2 fca(vec2 p){return texture(uFlowCA,p/vec2(uSize)).xy;}\n"
    "float ssd(vec2 o,vec2 v){float sa=0.0,sc=0.0,saa=0.0,scc=0.0,sac=0.0;\n"
    " for(int y=0;y<P;++y)for(int x=0;x<P;++x){vec2 q=o+vec2(float(x),float(y))+0.5;float a=ga(q-uT*v).x,c=gc(q+(1.0-uT)*v).x;\n"
    "  sa+=a;sc+=c;saa+=a*a;scc+=c*c;sac+=a*c;}\n"
    " const float N=float(P*P);return (saa-sa*sa/N)+(scc-sc*sc/N)-2.0*(sac-sa*sc/N);}\n"
    "void main(){vec2 o=vec2(ivec2(gl_FragCoord.xy)*S);vec2 x=o+0.5*float(P);\n"
    # Proposals: A's flow at its fixed-point source, and C's (negated) at its own.
    " vec2 p=x-uT*fac(x);p=x-uT*fac(p);p=x-uT*fac(p);vec2 q=x-(1.0-uT)*fca(x);q=x-(1.0-uT)*fca(q);q=x-(1.0-uT)*fca(q);\n"
    " vec2 v1=fac(p),v2=-fca(q);float e1=ssd(o,v1),e2=ssd(o,v2);vec2 v0=e2<e1?v2:v1;float e0=min(e1,e2);\n"
    " vec2 v=v0;const float N=float(P*P);\n"
    " for(int k=0;k<ITERS;++k){float sa=0.0,sc=0.0;vec2 sj=vec2(0.0);mat2 h=mat2(0.0);vec2 b=vec2(0.0);vec2 jsa=vec2(0.0),jsc=vec2(0.0);\n"
    "  for(int y=0;y<P;++y)for(int xx=0;xx<P;++xx){vec2 q2=o+vec2(float(xx),float(y))+0.5;vec3 A=ga(q2-uT*v),C=gc(q2+(1.0-uT)*v);\n"
    "   vec2 j=(1.0-uT)*C.yz+uT*A.yz;float r=C.x-A.x;sa+=A.x;sc+=C.x;sj+=j;h+=mat2(j.x*j.x,j.x*j.y,j.x*j.y,j.y*j.y);b+=j*r;}\n"
    # Mean-normalised residual: r_i - mean(r); its Jacobian j_i - mean(j).
    "  float mr=(sc-sa)/N;mat2 hn=h-mat2(sj.x*sj.x,sj.x*sj.y,sj.x*sj.y,sj.y*sj.y)/N+mat2(1e-4,0.0,0.0,1e-4);\n"
    "  vec2 bn=b-sj*mr;v-=inverse(hn)*bn;}\n"
    " float e=ssd(o,v);if(e>e0||any(isnan(v))){v=v0;e=e0;}\n"
    " o0=vec4(v,e,1.0);}\n")


# The per-phase densification weighs each patch by 1/max(1, e)^2 of its
# five-tap (cross) error: sharper motion edges than 1/max(1, e) at one pixel.
PHASE_DENSIFY_POWER = 2
PHASE_DENSIFY_CROSS = True


def phase_densify_shader():
    if PHASE_DENSIFY_CROSS:
        err = ("  float d=0.0;for(int k=0;k<5;++k){vec2 o=k==0?vec2(0.0):k==1?vec2(1.0,0.0):k==2?vec2(-1.0,0.0):"
               "k==3?vec2(0.0,1.0):vec2(0.0,-1.0);\n"
               "   d+=abs(texture(uGrayC,(x+o+(1.0-uT)*v)/vec2(uSize)).r-texture(uGrayA,(x+o-uT*v)/vec2(uSize)).r);}"
               "d*=255.0/5.0;\n")
    else:
        err = "  float d=abs(texture(uGrayC,(x+(1.0-uT)*v)/vec2(uSize)).r-texture(uGrayA,(x-uT*v)/vec2(uSize)).r)*255.0;\n"
    weight = weight_line(PHASE_DENSIFY_POWER)
    return (HEADER +
    f"#define P {PATCH}\n#define S {STRIDE}\n"
    "uniform sampler2D uGrayA,uGrayC,uPatches;uniform ivec2 uSize,uGrid;uniform float uT;\n"
    "layout(location=0) out vec4 o0;\n"
    "void main(){ivec2 p=ivec2(gl_FragCoord.xy);vec2 x=vec2(p)+0.5;\n"
    " ivec2 hi=min(p/S,uGrid-1);ivec2 lo=max((p-P+S)/S,ivec2(0));lo=min(lo,hi);\n"
    " vec2 acc=vec2(0.0);float wsum=0.0;\n"
    " for(int gy=lo.y;gy<=hi.y;++gy)for(int gx=lo.x;gx<=hi.x;++gx){\n"
    "  vec2 v=texelFetch(uPatches,ivec2(gx,gy),0).xy;\n" + err + weight +
    "acc+=w*v;wsum+=w;}\n"
    " o0=vec4(acc/max(wsum,1e-6),0.0,1.0);}\n")


# The field choice. Measured on full-size 1080p captures and not adopted:
# requiring the chosen neighbour to explain the pixel (within 8 or 16 grey
# levels) and a soft choice weighting the candidates by exp(-(e - min)/sigma)
# (sigma 2 or 4 grey levels) were within 0.3% of the hard choice.
def field_choice_glsl():
    return ("  if(us>=uChoiceSpread){vec2 bv=v;float be=wc(u,v)-2.0/255.0;\n"
            "   for(int y=-1;y<=1;++y)for(int x=-1;x<=1;++x){\n"
            "    vec2 k=texelFetch(uPhaseFlow,clamp(ub+ivec2(x,y),ivec2(0),um),0).xy/uFlowSize;float e=wc(u,k);\n"
            "    if(e<be){be=e;bv=k;}}\n"
            "   v=bv;}}\n")


# Output from the per-phase field: A at x - t*v, C at x + (1-t)*v.
def generate_phase_shader():
    return (HEADER +
    "uniform sampler2D uFrameA,uFrameC,uPhaseFlow;uniform float uT;uniform vec2 uFlowSize;\n"
    "in vec2 vTexCoord;layout(location=0) out vec4 o0;\n"
    # Synthesis 15's static-structure mask (fixed text whose colours change
    # with what is behind it keeps its local rank pattern at zero motion):
    # where a warp of two sampling steps or more covers a marked pixel, the
    # zero-motion blend replaces it.
    "uniform sampler2D uStructureMask;uniform float uStructure,uStructureMinMotionPx;uniform vec2 uHistorySize;\n"
    # Where the endpoints agree at zero motion by 8 grey levels more than the
    # warp's two samples agree (mean over a five-tap cross), the pixel did not
    # move (fixed text over moving fire, a static border the motion would
    # drag): zero-motion blend. Paired Thor hold-out, God of War II 0.620 ->
    # 0.505; offline over 28 captured games 0.8% better on average.
    # The global pass's cut/fade verdict (1x1, as synthesis 15 reads it): a
    # hard cut holds the left endpoint, a fitted fade is the temporal blend.
    "uniform sampler2D uCut;uniform float uCutEnabled;\n" +
    ("uniform sampler2D uBounds;\n" if CONTENT_BOUNDS else "") +
    # The phase field is coarser than the image (a 1080p source's is 1/8 of
    # it), so its bilinear lookup smears motion across object outlines.
    # Where the 3x3 neighbouring field vectors differ from it by
    # uChoiceSpread history pixels or more, the pixel takes the neighbour
    # whose two warp samples agree best; the bilinear vector keeps ties
    # within 2 grey levels. On full-size 1080p captures: NSMBU Deluxe 0.391
    # -> 0.376, Double Dash 0.600 -> 0.594, Ocarina 0.715 -> 0.712 of a
    # cross-fade, Link's Awakening within 0.2%. Zero disables it (QA).
    "uniform float uChoiceSpread;\n"
    "float md(vec3 x){return max(max(x.r,x.g),x.b);}\n"
    "float wc(vec2 u,vec2 k){return md(abs(texture(uFrameA,u-uT*k).rgb-texture(uFrameC,u+(1.0-uT)*k).rgb));}\n"
    "void main(){vec2 u=vTexCoord;vec2 v=texture(uPhaseFlow,u).xy/uFlowSize;\n"
    " if(uChoiceSpread>0.0){ivec2 um=ivec2(uFlowSize)-1,ub=ivec2(floor(u*uFlowSize));float us=0.0;\n"
    "  for(int y=-1;y<=1;++y)for(int x=-1;x<=1;++x)\n"
    "   us=max(us,length((texelFetch(uPhaseFlow,clamp(ub+ivec2(x,y),ivec2(0),um),0).xy/uFlowSize-v)*uHistorySize));\n"
    + field_choice_glsl() +
    ("" if not (CONTENT_BOUNDS and EDGE_EXTRAPOLATE_PX > 0) else
     " {vec4 eb=texture(uBounds,vec2(0.5));" + f"vec2 em={float(EDGE_EXTRAPOLATE_PX)}/uHistorySize;\n"
     "  vec2 ui=clamp(u,eb.xz+em,eb.yw-em);if(ui!=u)v=texture(uPhaseFlow,ui).xy/uFlowSize;}\n") +
    " vec3 aw=texture(uFrameA,u-uT*v).rgb,cw=texture(uFrameC,u+(1.0-uT)*v).rgb;\n"
    " vec3 a0=texture(uFrameA,u).rgb,c0=texture(uFrameC,u).rgb;\n"
    " vec3 w=(1.0-uT)*aw+uT*cw;\n"
    # Motion under one source pixel is taken as zero: a sub-pixel warp only
    # blurs sharp content (DS, NSMBU Deluxe, 3DS); offline over 28 games 1.7%
    # better on average (NSMBU Deluxe -15%, 3DS -8%, Star Fox 64 -6%); two
    # pixels breaks real 1-2 px scrolling (Game Boy, NES).
    " if(length(v*uHistorySize)<1.0)w=(1.0-uT)*a0+uT*c0;else\n"
    " {float eM=md(abs(aw-cw)),e0=md(abs(a0-c0));\n"
    + ("  {vec2 dx" if not SKIP_FLAT_CROSS else "  if(max(eM,e0)>2.0/255.0){vec2 dx") + "=vec2(1.0/uHistorySize.x,0.0),dy=vec2(0.0,1.0/uHistorySize.y);\n"
    "   eM+=md(abs(texture(uFrameA,u-uT*v+dx).rgb-texture(uFrameC,u+(1.0-uT)*v+dx).rgb))"
    "+md(abs(texture(uFrameA,u-uT*v-dx).rgb-texture(uFrameC,u+(1.0-uT)*v-dx).rgb))"
    "+md(abs(texture(uFrameA,u-uT*v+dy).rgb-texture(uFrameC,u+(1.0-uT)*v+dy).rgb))"
    "+md(abs(texture(uFrameA,u-uT*v-dy).rgb-texture(uFrameC,u+(1.0-uT)*v-dy).rgb));\n"
    "   e0+=md(abs(texture(uFrameA,u+dx).rgb-texture(uFrameC,u+dx).rgb))+md(abs(texture(uFrameA,u-dx).rgb-texture(uFrameC,u-dx).rgb))"
    "+md(abs(texture(uFrameA,u+dy).rgb-texture(uFrameC,u+dy).rgb))+md(abs(texture(uFrameA,u-dy).rgb-texture(uFrameC,u-dy).rgb));\n"
    "   eM*=0.2;e0*=0.2;}\n"
    "  if(e0+8.0/255.0<eM)w=(1.0-uT)*a0+uT*c0;}\n"
    " if(uStructure>0.5&&length(v*uHistorySize)>=uStructureMinMotionPx){\n"
    "  w=mix(w,(1.0-uT)*a0+uT*c0,texture(uStructureMask,u).r);}\n"
    + ("" if not CONTENT_BOUNDS else
       " {vec4 bb=texture(uBounds,vec2(0.5));vec2 lo=bb.xz,hi=bb.yw;\n"
       "  if(any(lessThan(u,lo))||any(greaterThan(u,hi)))w=(1.0-uT)*a0+uT*c0;\n"
       "  else{vec2 pa=u-uT*v,pc=u+(1.0-uT)*v;\n"
       f"   vec2 mg={float(BORDER_MARGIN_PX)}/uHistorySize;\n"
       "   bool oa=any(lessThan(pa,lo-mg))||any(greaterThan(pa,hi+mg));\n"
       "   bool oc=any(lessThan(pc,lo-mg))||any(greaterThan(pc,hi+mg));\n"
       "   if(oa&&!oc)w=cw;else if(oc&&!oa)w=aw;}}\n") +
    " vec4 ct=texture(uCut,vec2(0.5));\n"
    f" w=mix(mix(w,a0,uCutEnabled*step({CUT_THRESHOLD},ct.r)),(1.0-uT)*a0+uT*c0,uCutEnabled*step(0.5,ct.g));\n"
    " o0=vec4(w,1.0);}\n")


# Cut/fade verdict after DIS (1x1; read like the generator's global pass: r =
# cut evidence, g = fade). On the same 12x8 luma grid, the fraction whose
# luminance differs by more than 0.12 at zero motion and along A's DIS flow,
# the smaller one: a single global translation cannot explain a camera turn
# or flight forward, and Star Fox 64 / Sonic Adventure turns held the left
# frame as a "cut". The fade is the global pass's zero-motion fit
# current = gain * previous + offset.
# The five-tap comparison is skipped where both one-pixel mismatches are under
# 2 grey levels (flat, unchanged areas): 16 fewer full-resolution reads there,
# offline over 28 games identical within 0.1%.
SKIP_FLAT_CROSS = True

# Offline experiments: a fade's fitted gain range and the share of samples a
# fade must change (both off: a step to or from black is a cut or a fade's
# last step, and bounding it won Dread but lost Wind Waker HD and Barbie).
FADE_GAIN = None        # (min, max)
FADE_COVERAGE = None    # fraction of samples with |C - A| > 1 grey level
# Two flat frames that differ are a fade: the gain fit is undefined there, so a
# fade between solid-colour screens fell to the cut rule and held the left frame
# (synthetic flat fades 31x a cross-fade's error -> rounding; Mega Man 11's
# save-notice dimming 1.691 -> 1.653; nothing worse over 28 games).
FLAT_FADE = True
# A cut is 60% of the 12x8 grid unexplained along DIS. 0.25 held animated sea
# in Link's Awakening and a Mario Kart Wii turn (0.5: Link's Awakening 1.302 ->
# 1.182, Mario Kart Wii 0.752 -> 0.692); one sea pair still sat at 0.45-0.53
# and flipped with small flow changes, while the captured cuts score 0.72+.
CUT_THRESHOLD = 0.6


# Offline experiment: the cut counts use colour (largest channel change of a
# 4-tap box on the history images) instead of analysis luma, so a cut
# between two scenes of similar brightness is not missed.
COLOUR_CUT = False
# Offline experiment: grid samples black in both frames (letter/pillarbox
# bars) leave the cut share's count and its denominator.
CUT_SKIP_BLACK = False
# Offline experiment (re-measured on full-size captures): the picture
# rectangle inside letter/pillarbox bars (rows and columns black in both
# frames, scanned from each side on the analysis luma) as normalised (left,
# right, bottom, top); outside it the zero-motion blend, inside it a pixel
# takes one side where the other side's warp source lies in the bars.
CONTENT_BOUNDS = False
BORDER_MARGIN_PX = 0.0
# With CONTENT_BOUNDS: within EDGE_EXTRAPOLATE_PX history pixels of the
# picture's edge the field is read that far inside (content arriving at an
# edge has no match in one frame; a pan moves the edge like its neighbours).
EDGE_EXTRAPOLATE_PX = 0.0

BOUNDS = (HEADER +
    "uniform sampler2D uGrayA,uGrayC;uniform ivec2 uSize;\n"
    "layout(location=0) out vec4 o0;\n"
    "float colMax(int x){float m=0.0;for(int k=0;k<24;++k){vec2 q=(vec2(float(x),float(k)*float(uSize.y)/24.0)+0.5)/vec2(uSize);\n"
    " m=max(m,max(texture(uGrayA,q).r,texture(uGrayC,q).r));}return m;}\n"
    "float rowMax(int y){float m=0.0;for(int k=0;k<32;++k){vec2 q=(vec2(float(k)*float(uSize.x)/32.0,float(y))+0.5)/vec2(uSize);\n"
    " m=max(m,max(texture(uGrayA,q).r,texture(uGrayC,q).r));}return m;}\n"
    "void main(){const float T=6.0/255.0;int l=0,r=uSize.x-1,b=0,t=uSize.y-1;\n"
    " for(int x=0;x<uSize.x/2;++x){if(colMax(x)>T)break;l=x+1;}\n"
    " for(int x=uSize.x-1;x>=uSize.x/2;--x){if(colMax(x)>T)break;r=x-1;}\n"
    " for(int y=0;y<uSize.y/2;++y){if(rowMax(y)>T)break;b=y+1;}\n"
    " for(int y=uSize.y-1;y>=uSize.y/2;--y){if(rowMax(y)>T)break;t=y-1;}\n"
    " o0=vec4(float(l)/float(uSize.x),float(r+1)/float(uSize.x),float(b)/float(uSize.y),float(t+1)/float(uSize.y));}\n")


def cut_shader():
    if COLOUR_CUT:
        return colour_cut_shader()
    if CUT_SKIP_BLACK:
        return skip_black_cut_shader()
    extra = ""
    if FADE_GAIN is not None:
        extra += f"*step({FADE_GAIN[0]},g)*step(g,{FADE_GAIN[1]})"
    if FADE_COVERAGE is not None:
        extra += f"*step({FADE_COVERAGE * 96.0:.1f},nc)"
    return (HEADER +
    "uniform sampler2D uGrayA,uGrayC,uFlowAC;uniform vec2 uFlowSize;\n"
    "layout(location=0) out vec4 o0;\n"
    "void main(){float n0=0.0,n1=0.0," + ("nc=0.0," if FADE_COVERAGE is not None else "") + "sa=0.0,sb=0.0,saa=0.0,sab=0.0,sbb=0.0,d=0.0;const float n=96.0;\n"
    " for(int y=0;y<8;++y)for(int x=0;x<12;++x){vec2 uv=vec2((float(x)+0.5)/12.0,(float(y)+0.5)/8.0);\n"
    "  float a=texture(uGrayA,uv).r,b=texture(uGrayC,uv).r;n0+=step(0.12,abs(b-a));" +
    ("nc+=step(1.0/255.0,abs(b-a));" if FADE_COVERAGE is not None else "") + "\n"
    "  vec2 q=uv+texture(uFlowAC,uv).xy/uFlowSize;\n"
    "  if(all(greaterThanEqual(q,vec2(0.0)))&&all(lessThanEqual(q,vec2(1.0))))n1+=step(0.12,abs(texture(uGrayC,q).r-a));\n"
    "  sa+=a;sb+=b;saa+=a*a;sab+=a*b;sbb+=b*b;d+=abs(b-a);}\n"
    " float fade=0.0,va=n*saa-sa*sa;\n"
    " if(va>=n*n*0.0009){float g=(n*sab-sa*sb)/va,o=(sb-g*sa)/n,rms=sqrt(max(0.0,(sbb-g*sab-o*sb)/n)),change=d/n;\n"
    "  fade=step(0.015,change)*step(rms,0.25*change)*step(rms,0.02)" + extra + ";}\n" +
    (" else fade=step(n*sbb-sb*sb,n*n*0.0009)*step(0.015,d/n);\n" if FLAT_FADE else "") +
    " o0=vec4(min(n0,n1)/n,fade,0.0,1.0);}\n")


def colour_cut_shader():
    """cut_shader with colour counts; the fade fit stays on luma."""
    text = cut_shader_luma()
    text = text.replace("uniform sampler2D uGrayA,uGrayC,uFlowAC;uniform vec2 uFlowSize;\n",
                        "uniform sampler2D uGrayA,uGrayC,uFlowAC,uFrameA,uFrameC;uniform vec2 uFlowSize,uTexel;\n"
                        "vec3 bx(sampler2D t,vec2 p){return 0.25*(texture(t,p+uTexel*vec2(-1.0,-1.0)).rgb+"
                        "texture(t,p+uTexel*vec2(1.0,-1.0)).rgb+texture(t,p+uTexel*vec2(-1.0,1.0)).rgb+"
                        "texture(t,p+uTexel*vec2(1.0,1.0)).rgb);}\n"
                        "float cd(vec3 x){return max(max(x.r,x.g),x.b);}\n")
    old0 = "n0+=step(0.12,abs(b-a));"
    old1 = "n1+=step(0.12,abs(texture(uGrayC,q).r-a));"
    assert old0 in text and old1 in text
    text = text.replace(old0, "vec3 ca=bx(uFrameA,uv);n0+=step(0.12,cd(abs(bx(uFrameC,uv)-ca)));")
    text = text.replace(old1, "n1+=step(0.12,cd(abs(bx(uFrameC,q)-ca)));")
    return text


def skip_black_cut_shader():
    global CUT_SKIP_BLACK
    saved = CUT_SKIP_BLACK
    CUT_SKIP_BLACK = False
    try:
        text = cut_shader()
    finally:
        CUT_SKIP_BLACK = saved
    pairs = [("float n0=0.0,n1=0.0,", "float n0=0.0,n1=0.0,nk=0.0,"),
             ("n0+=step(0.12,abs(b-a));", "float k=step(4.0/255.0,max(a,b));nk+=k;n0+=k*step(0.12,abs(b-a));"),
             ("n1+=step(0.12,abs(texture(uGrayC,q).r-a));", "n1+=k*step(0.12,abs(texture(uGrayC,q).r-a));"),
             (" o0=vec4(min(n0,n1)/n,fade,0.0,1.0);}", " o0=vec4(min(n0,n1)/max(nk,1.0),fade,0.0,1.0);}")]
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new)
    return text


def cut_shader_luma():
    global COLOUR_CUT
    saved = COLOUR_CUT
    COLOUR_CUT = False
    try:
        return cut_shader()
    finally:
        COLOUR_CUT = saved


def shaders():
    return {'VERTEX': VERTEX, 'VERTEX_QUAD': VERTEX_QUAD, 'GRAY': GRAY, 'DOWN': DOWN, 'GRAD': GRAD,
            'PATCH_SEARCH': patch_search_shader(), 'DENSIFY': densify_shader(), 'GENERATE': GENERATE,
            'TO_RAW': TO_RAW, 'PHASE_SEARCH': phase_search_shader(), 'PHASE_DENSIFY': phase_densify_shader(),
            'GENERATE_PHASE': generate_phase_shader(), 'CUT': cut_shader(),
            'DENSIFY_SHARP': sharp_densify_shader(), **({'BOUNDS': BOUNDS} if CONTENT_BOUNDS else {})}


def sharp_densify_shader():
    """The per-phase route's endpoint densification: each patch weighted by
    1/max(1, e)^2 of its five-tap (cross) error. With the per-phase one, 2.2%
    better offline over 28 captured games; paired Thor hold-out 1-7% better."""
    global DENSIFY_POWER, DENSIFY_CROSS
    saved = DENSIFY_POWER, DENSIFY_CROSS
    DENSIFY_POWER, DENSIFY_CROSS = 2, True
    try:
        return densify_shader()
    finally:
        DENSIFY_POWER, DENSIFY_CROSS = saved


def levels_for(width, height, finest):
    """Pyramid sizes from the analysis image down while both sides stay >= 2 patches."""
    sizes = [(width, height)]
    while min((sizes[-1][0] + 1) // 2, (sizes[-1][1] + 1) // 2) >= 2 * PATCH:
        sizes.append(((sizes[-1][0] + 1) // 2, (sizes[-1][1] + 1) // 2))
    return sizes, finest


def grid(size):
    return (max(1, (size[0] - PATCH) // STRIDE + 1), max(1, (size[1] - PATCH) // STRIDE + 1))


def java_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def java_source():
    lines = ["package com.thorium.preview.game;", "", "/**",
             " * Generated by tools/learned_framegen/dis_gles.py; do not edit, change the generator.",
             " * GPU dense inverse search (Kroeger et al., ECCV 2016), our own implementation.", " */",
             "final class DenseInverseSearchShaders {", "    private DenseInverseSearchShaders() {}", ""]
    for name, text in shaders().items():
        lines.append(f"    static final String {name} = new StringBuilder({len(text)})")
        for i in range(0, len(text), 2000):
            lines.append("            .append(" + java_string(text[i:i + 2000]) + ")")
        lines.append("            .toString();")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


if __name__ == '__main__':
    import sys
    from pathlib import Path
    Path(sys.argv[1]).write_text(java_source())
