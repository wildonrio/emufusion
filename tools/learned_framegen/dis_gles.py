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

# Offline experiment (2026-10-23): GRAY with every sample clamped inside the
# picture rectangle (BOUNDS), so letter/pillarbox bars become the picture's own
# edge pixels. The bars' static, high-contrast edge otherwise pulls patches
# near the picture's edge to zero motion (Ocarina gameplay: error 1.0 of a
# cross-fade at the edge falling to 0.4 128 px inside).
CLAMP_TO_CONTENT = False
GRAY_CLAMP = (HEADER +
        "uniform sampler2D uIn0,uBounds;uniform vec2 uTexel;uniform int uDivisor;\n"
        "layout(location=0) out vec4 o0;\n"
        "vec4 bb;\n"
        "float l(vec2 c){c=clamp(c,bb.xz+2.0*uTexel,bb.yw-2.0*uTexel);return dot(texture(uIn0,c).rgb,vec3(0.299,0.587,0.114));}\n"
        "void main(){bb=texture(uBounds,vec2(0.5));vec2 c=gl_FragCoord.xy*float(uDivisor)*uTexel;float y;\n"
        " if(uDivisor<=2)y=l(c);\n"
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
    "uniform sampler2D uGradA,uGradC,uFlowAC,uFlowCA;uniform ivec2 uSize;uniform float uT;\n" +
    ("uniform float uGlobal;\n" if PHASE_GLOBAL_GRID and PHASE_GLOBAL_DISCRETE_ONLY else "") +
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
    + "".join(f" {{vec2 c=fac(x+vec2({dx:.1f},{dy:.1f}));float ec=ssd(o,c);if(ec<e0){{e0=ec;v0=c;}}}}\n"
              for d in PHASE_PROPAGATE for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d))) +
    (" if(uGlobal>0.5){\n" if PHASE_GLOBAL_GRID and PHASE_GLOBAL_DISCRETE_ONLY else "") +
    "".join(f" {{vec2 c=fac(vec2(uSize)*vec2({(i + 0.5) / PHASE_GLOBAL_GRID[0]:.4f},{(j + 0.5) / PHASE_GLOBAL_GRID[1]:.4f}));"
            f"float ec=ssd(o,c);if(ec<e0*{1.0 + PHASE_GLOBAL_TIE:.3f}+1e-6){{e0=min(e0,ec);v0=c;}}}}\n"
            for j in range(PHASE_GLOBAL_GRID[1] if PHASE_GLOBAL_GRID else 0)
            for i in range(PHASE_GLOBAL_GRID[0] if PHASE_GLOBAL_GRID else 0)) +
    (" }\n" if PHASE_GLOBAL_GRID and PHASE_GLOBAL_DISCRETE_ONLY else "") +
    " vec2 v=v0;const float N=float(P*P);\n"
    " for(int k=0;k<ITERS;++k){float sa=0.0,sc=0.0;vec2 sj=vec2(0.0);mat2 h=mat2(0.0);vec2 b=vec2(0.0);vec2 jsa=vec2(0.0),jsc=vec2(0.0);\n"
    "  for(int y=0;y<P;++y)for(int xx=0;xx<P;++xx){vec2 q2=o+vec2(float(xx),float(y))+0.5;vec3 A=ga(q2-uT*v),C=gc(q2+(1.0-uT)*v);\n"
    "   vec2 j=(1.0-uT)*C.yz+uT*A.yz;float r=C.x-A.x;sa+=A.x;sc+=C.x;sj+=j;h+=mat2(j.x*j.x,j.x*j.y,j.x*j.y,j.y*j.y);b+=j*r;}\n"
    # Mean-normalised residual: r_i - mean(r); its Jacobian j_i - mean(j).
    "  float mr=(sc-sa)/N;mat2 hn=h-mat2(sj.x*sj.x,sj.x*sj.y,sj.x*sj.y,sj.y*sj.y)/N+mat2(1e-4,0.0,0.0,1e-4);\n"
    "  vec2 bn=b-sj*mr;v-=inverse(hn)*bn;}\n"
    " float e=ssd(o,v);if(e>e0||any(isnan(v))){v=v0;e=e0;}\n"
    " o0=vec4(v,e,1.0);}\n")


# Replay-bench experiment (2026-10-24): the per-phase search also starts from
# A's flow this many analysis pixels away in each axis direction when that
# matches the patch better (PatchMatch-style propagation: motion found where
# the image is distinctive reaches repeating tiles and fast scrolls).
# Default since 3.2.99 (8 and 16 px): replay bench over nine games, paired,
# 0.590 -> 0.588 of a cross-fade (SNES 0.349, Link's Awakening -0.007); with
# whole-pixel warps, 0.592 -> 0.577.
PHASE_PROPAGATE = (8, 16)
# ... and from A's flow at a fixed grid of points across the frame (scene-wide
# motions: a camera scroll found anywhere reaches every patch), taken on ties
# within PHASE_GLOBAL_TIE (a repeating tile matches its aliases equally well).
PHASE_GLOBAL_GRID = ()
PHASE_GLOBAL_TIE = 0.0
# ... only where uGlobal is set (the pixel-art systems: uDiscrete's sources).
# Experiment 2026-10-25: those scroll whole screens of repeating tiles by
# whole pixels (Game Gear's striped columns and tile fields, 89% of frames
# with invented content), where a patch's own search locks onto an alias.
PHASE_GLOBAL_DISCRETE_ONLY = False


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


# Offline experiment (2026-10-23): edge-aware smoothing of the per-phase
# field, the role of DIS's variational refinement (Kroeger et al. step 3, not
# implemented here before). Each iteration replaces a vector by the weighted
# mean of itself and its four neighbours: its own (data) weight falls with its
# five-tap warp error, each neighbour's weight with the difference of the
# phase-warped guide image (edge-aware). Off when PHASE_SMOOTH_ITERS is 0.
PHASE_SMOOTH_ITERS = 0
# The zero-motion selection margin in grey levels (shipped 8; offline experiment).
ZERO_MOTION_MARGIN = 8.0
# Offline experiment: zero motion must also fit within this many grey levels (0: no cap).
ZERO_MOTION_MAX = 0.0
# Offline experiment: the five-tap comparison's offset in history pixels (shipped 1).
ZERO_MOTION_SPREAD = 1.0
PHASE_SMOOTH_LAMBDA = 4.0
PHASE_SMOOTH_SIGMA = 6.0


def phase_smooth_shader():
    return (HEADER +
    "uniform sampler2D uField,uData,uGrayA,uGrayC;uniform ivec2 uSize;uniform float uT,uLambda,uSigma;\n"
    "layout(location=0) out vec4 o0;\n"
    "float gA(vec2 q){return texture(uGrayA,q/vec2(uSize)).r;}\n"
    "float gC(vec2 q){return texture(uGrayC,q/vec2(uSize)).r;}\n"
    "float guide(ivec2 q){vec2 x=vec2(q)+0.5;vec2 v=texelFetch(uData,clamp(q,ivec2(0),uSize-1),0).xy;\n"
    " return 0.5*(gA(x-uT*v)+gC(x+(1.0-uT)*v));}\n"
    "void main(){ivec2 p=ivec2(gl_FragCoord.xy);vec2 x=vec2(p)+0.5;\n"
    " vec2 vd=texelFetch(uData,p,0).xy;float e=0.0;\n"
    " for(int k=0;k<5;++k){vec2 o=k==0?vec2(0.0):k==1?vec2(1.0,0.0):k==2?vec2(-1.0,0.0):k==3?vec2(0.0,1.0):vec2(0.0,-1.0);\n"
    "  e+=abs(gC(x+o+(1.0-uT)*vd)-gA(x+o-uT*vd));}\n"
    " e*=255.0/5.0;float wd=uLambda/(1.0+e);float g0=guide(p);\n"
    " vec2 acc=wd*vd;float ws=wd;\n"
    " for(int k=0;k<4;++k){ivec2 o=k==0?ivec2(1,0):k==1?ivec2(-1,0):k==2?ivec2(0,1):ivec2(0,-1);ivec2 q=p+o;\n"
    "  if(any(lessThan(q,ivec2(0)))||any(greaterThanEqual(q,uSize)))continue;\n"
    "  float w=exp(-abs(guide(q)-g0)*255.0/uSigma);acc+=w*texelFetch(uField,q,0).xy;ws+=w;}\n"
    " o0=vec4(acc/ws,0.0,1.0);}\n")


# The field choice. Measured on full-size 1080p captures and not adopted:
# requiring the chosen neighbour to explain the pixel (within 8 or 16 grey
# levels) and a soft choice weighting the candidates by exp(-(e - min)/sigma)
# (sigma 2 or 4 grey levels) were within 0.3% of the hard choice.
# Grey levels a neighbour must beat the bilinear vector by (shipped 2).
FIELD_CHOICE_MARGIN = 2.0
# Replay-bench experiment (2026-10-25): candidates from field cells up to
# FIELD_CHOICE_RADIUS away (shipped 1: the 3x3 neighbours), each judged by its
# two warp samples' mismatch over FIELD_CHOICE_TAPS taps (1, or 5: the pixel
# and its four history-pixel neighbours). A thin occluder (a kart's frame
# bars, 6-12 px at 1080p, under one 8-px field cell) takes its body's motion
# from two cells away.
FIELD_CHOICE_RADIUS = 1
FIELD_CHOICE_TAPS = 1
# Replay-bench experiment (2026-10-25), not adopted: a second stage only where
# the chosen vector's two samples still differ by FIELD_CHOICE_OUTER_T grey
# levels -- the 16 cells two away, each judged over five taps (a kart's frame
# bars take their body's motion two cells away). Device replay bench, paired:
# invented area full-size 0.096 -> 0.089% of the frame, eval 3-D 0.062 ->
# 0.053%, train games 0.560 -> 0.500%, error unchanged; but on the Thor it
# cost Wind Waker HD 3.1 -> 4.4 ms of GPU per pair (worst pair 6.3 -> 11.8
# ms): it triggers on only a few percent of pixels, but a GPU wave pays for
# any pixel that branches into it. 0 disables.
FIELD_CHOICE_OUTER_T = 0.0


def field_choice_glsl():
    r = int(FIELD_CHOICE_RADIUS)
    cost = "wc(u,v)" if FIELD_CHOICE_TAPS == 1 else "wc5(u,v)"
    each = "wc(u,k)" if FIELD_CHOICE_TAPS == 1 else "wc5(u,k)"
    return (f"  if(us>=uChoiceSpread){{vec2 bv=v;float be={cost}-{float(FIELD_CHOICE_MARGIN)}/255.0;\n"
            f"   for(int y=-{r};y<={r};++y)for(int x=-{r};x<={r};++x){{\n"
            f"    vec2 k=texelFetch(uPhaseFlow,clamp(ub+ivec2(x,y),ivec2(0),um),0).xy/uFlowSize;float e={each};\n"
            "    if(e<be){be=e;bv=k;}}\n" +
            ("   v=bv;}}\n" if FIELD_CHOICE_OUTER_T <= 0 else
             "   v=bv;\n"
             f"   if(be+{float(FIELD_CHOICE_MARGIN)}/255.0>{float(FIELD_CHOICE_OUTER_T)}/255.0){{float b5=wc5(u,v)-{float(FIELD_CHOICE_MARGIN)}/255.0;\n"
             "    for(int y=-2;y<=2;++y)for(int x=-2;x<=2;++x){if(max(abs(x),abs(y))<2)continue;\n"
             "     vec2 k=texelFetch(uPhaseFlow,clamp(ub+ivec2(x,y),ivec2(0),um),0).xy/uFlowSize;float e=wc5(u,k);\n"
             "     if(e<b5){b5=e;bv=k;}}\n"
             "    v=bv;}}}\n"))


def wc5_glsl():
    """Five-tap warp mismatch of a candidate (FIELD_CHOICE_TAPS 5)."""
    if FIELD_CHOICE_TAPS == 1 and FIELD_CHOICE_OUTER_T <= 0:
        return ""
    return ("float wc5(vec2 u,vec2 k){vec2 dx=vec2(1.0/uHistorySize.x,0.0),dy=vec2(0.0,1.0/uHistorySize.y);\n"
            " return 0.2*(wc(u,k)+wc(u+dx,k)+wc(u-dx,k)+wc(u+dy,k)+wc(u-dy,k));}\n")


# Output from the per-phase field: A at x - t*v, C at x + (1-t)*v.
def _generate_phase_shader_text():
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
    "uniform float uChoiceSpread;\n" +
    ("uniform float uDiscrete;\n" if DISCRETE_UNIFORM else "") +
    ("uniform sampler2D uLate;\n" if LATE_SHARE > 0 else "") +
    ("uniform sampler2D uFlowAC,uFlowCA;\n" if OCCLUSION_SIDE_T > 0 else "") +
    "float md(vec3 x){return max(max(x.r,x.g),x.b);}\n"
    "float wc(vec2 u,vec2 k){return md(abs(texture(uFrameA,u-uT*k).rgb-texture(uFrameC,u+(1.0-uT)*k).rgb));}\n"
    + wc5_glsl() +
    "void main(){vec2 u=vTexCoord;vec2 v=texture(uPhaseFlow,u).xy/uFlowSize;\n" +
    (" if(uChoiceSpread>0.0){ivec2 um=ivec2(uFlowSize)-1,ub=ivec2(floor(u*uFlowSize));float us=0.0;\n"
     if NEITHER_SPREAD_PX <= 0 else
     " float us=0.0;if(uChoiceSpread>0.0){ivec2 um=ivec2(uFlowSize)-1,ub=ivec2(floor(u*uFlowSize));\n") +
    "  for(int y=-1;y<=1;++y)for(int x=-1;x<=1;++x)\n"
    "   us=max(us,length((texelFetch(uPhaseFlow,clamp(ub+ivec2(x,y),ivec2(0),um),0).xy/uFlowSize-v)*uHistorySize));\n"
    + field_choice_glsl() +
    ("" if not (CONTENT_BOUNDS and EDGE_EXTRAPOLATE_PX > 0) else
     " {vec4 eb=texture(uBounds,vec2(0.5));" + f"vec2 em={float(EDGE_EXTRAPOLATE_PX)}/uHistorySize;\n"
     "  vec2 ui=clamp(u,eb.xz+em,eb.yw-em);if(ui!=u){vec2 ke=texture(uPhaseFlow,ui).xy/uFlowSize;\n" +
     ("   if(wc(u,ke)<wc(u,v)-2.0/255.0)v=ke;}}\n" if EDGE_CANDIDATE else "   v=ke;}}\n")) +
    " vec3 aw=texture(uFrameA,u-uT*v).rgb,cw=texture(uFrameC,u+(1.0-uT)*v).rgb;\n" +
    ("" if not PIXEL_SNAP else
     # Pixel art moves in whole pixels: sample both frames at texel centres
     # along the motion rounded to whole pixels (the real middle frame is on
     # the grid; a half-pixel bilinear sample blurs every edge).
     (" if(uDiscrete>0.5){\n" if DISCRETE_UNIFORM else
      f" if(uHistorySize.x<={PIXEL_SNAP[0]:.1f}&&uHistorySize.y<={PIXEL_SNAP[1]:.1f}){{\n") +
     "  vec2 vp=floor(v*uHistorySize+0.5),ap=floor(uT*vp+0.5),q=floor(u*uHistorySize)+0.5;\n"
     "  aw=texture(uFrameA,(q-ap)/uHistorySize).rgb;cw=texture(uFrameC,(q+vp-ap)/uHistorySize).rgb;}\n") +
    " vec3 a0=texture(uFrameA,u).rgb,c0=texture(uFrameC,u).rgb;\n"
    " vec3 w=(1.0-uT)*aw+uT*cw;\n"
    + (" vec3 pa=aw,pc=cw;\n" if PIXEL_PICK_T > 0 else "") +
    # Motion under one source pixel is taken as zero: a sub-pixel warp only
    # blurs sharp content (DS, NSMBU Deluxe, 3DS); offline over 28 games 1.7%
    # better on average (NSMBU Deluxe -15%, 3DS -8%, Star Fox 64 -6%); two
    # pixels breaks real 1-2 px scrolling (Game Boy, NES).
    (f" if(length(v*uHistorySize)<{float(SUBPIXEL_ZERO_PX)})w=(1.0-uT)*a0+uT*c0;else\n" if PIXEL_PICK_T <= 0 else
     f" if(length(v*uHistorySize)<{float(SUBPIXEL_ZERO_PX)}){{w=(1.0-uT)*a0+uT*c0;pa=a0;pc=c0;}}else\n") +
    " {float eM=md(abs(aw-cw)),e0=md(abs(a0-c0));\n"
    + ("  {vec2 dx" if not SKIP_FLAT_CROSS else "  if(max(eM,e0)>2.0/255.0){vec2 dx") + f"=vec2({float(ZERO_MOTION_SPREAD)}/uHistorySize.x,0.0),dy=vec2(0.0,{float(ZERO_MOTION_SPREAD)}/uHistorySize.y);\n"
    + (
    "   eM+=md(abs(texture(uFrameA,u-uT*v+dx).rgb-texture(uFrameC,u+(1.0-uT)*v+dx).rgb))"
    "+md(abs(texture(uFrameA,u-uT*v-dx).rgb-texture(uFrameC,u+(1.0-uT)*v-dx).rgb))"
    "+md(abs(texture(uFrameA,u-uT*v+dy).rgb-texture(uFrameC,u+(1.0-uT)*v+dy).rgb))"
    "+md(abs(texture(uFrameA,u-uT*v-dy).rgb-texture(uFrameC,u+(1.0-uT)*v-dy).rgb));\n"
    "   e0+=md(abs(texture(uFrameA,u+dx).rgb-texture(uFrameC,u+dx).rgb))+md(abs(texture(uFrameA,u-dx).rgb-texture(uFrameC,u-dx).rgb))"
    "+md(abs(texture(uFrameA,u+dy).rgb-texture(uFrameC,u+dy).rgb))+md(abs(texture(uFrameA,u-dy).rgb-texture(uFrameC,u-dy).rgb));\n"
    "   eM*=0.2;e0*=0.2;}\n" if not DECISION_DEMEAN else
    # Brightness-invariant: each five-tap difference less its mean, so a
    # lighting change between the frames (Star Fox 64's cast relit between
    # frames) does not make the warp / zero-motion choice random per pixel.
    "   vec3 m1=texture(uFrameA,u-uT*v+dx).rgb-texture(uFrameC,u+(1.0-uT)*v+dx).rgb,"
    "m2=texture(uFrameA,u-uT*v-dx).rgb-texture(uFrameC,u+(1.0-uT)*v-dx).rgb,"
    "m3=texture(uFrameA,u-uT*v+dy).rgb-texture(uFrameC,u+(1.0-uT)*v+dy).rgb,"
    "m4=texture(uFrameA,u-uT*v-dy).rgb-texture(uFrameC,u+(1.0-uT)*v-dy).rgb,m0=aw-cw;\n"
    "   vec3 mm=0.2*(m0+m1+m2+m3+m4);eM=0.2*(md(abs(m0-mm))+md(abs(m1-mm))+md(abs(m2-mm))+md(abs(m3-mm))+md(abs(m4-mm)));\n"
    "   vec3 z1=texture(uFrameA,u+dx).rgb-texture(uFrameC,u+dx).rgb,z2=texture(uFrameA,u-dx).rgb-texture(uFrameC,u-dx).rgb,"
    "z3=texture(uFrameA,u+dy).rgb-texture(uFrameC,u+dy).rgb,z4=texture(uFrameA,u-dy).rgb-texture(uFrameC,u-dy).rgb,z0=a0-c0;\n"
    "   vec3 zm=0.2*(z0+z1+z2+z3+z4);e0=0.2*(md(abs(z0-zm))+md(abs(z1-zm))+md(abs(z2-zm))+md(abs(z3-zm))+md(abs(z4-zm)));}\n")
    + (f"  if(e0+{float(ZERO_MOTION_MARGIN)}/255.0<eM){{w=(1.0-uT)*a0+uT*c0;pa=a0;pc=c0;}}"
       if ZERO_MOTION_MAX <= 0 and PIXEL_PICK_T > 0 else
       f"  if(e0+{float(ZERO_MOTION_MARGIN)}/255.0<eM)w=(1.0-uT)*a0+uT*c0;" if ZERO_MOTION_MAX <= 0 else
     f"  if(e0+{float(ZERO_MOTION_MARGIN)}/255.0<eM&&e0<{float(ZERO_MOTION_MAX)}/255.0)w=(1.0-uT)*a0+uT*c0;")
    + ("" if GHOST_SIDE_T <= 0 else
       f"\n  {{float gk=smoothstep({0.5*float(GHOST_SIDE_T)}/255.0,{float(GHOST_SIDE_T)}/255.0,min(eM,e0))*"
       f"smoothstep({0.5*float(GHOST_MIN_MOTION_PX)},{float(GHOST_MIN_MOTION_PX)}+0.001,length(v*uHistorySize));\n"
       "   vec3 side=uT>=0.5?(eM<=e0?cw:c0):(eM<=e0?aw:a0);w=mix(w,side,gk);}")
    + ("" if OCCLUSION_SIDE_T <= 0 else
       # Where the two warp samples disagree, each is checked against its own
       # frame's DIS flow at the point it samples: a sample whose frame moves
       # differently there lies on another layer (occluded at this phase).
       f"\n  if(eM>{float(OCCLUSION_SIDE_T)}/255.0){{vec2 vp=v*uFlowSize;\n"
       "   float da=length(texture(uFlowAC,u-uT*v).xy-vp),dc=length(-texture(uFlowCA,u+(1.0-uT)*v).xy-vp);\n"
       f"   if(abs(da-dc)>{float(OCCLUSION_SIDE_MARGIN)})w=da<dc?aw:cw;}}")
    + ("" if NEITHER_BLEND_T <= 0 else
       (("\n  if(uDiscrete<0.5)" if DISCRETE_UNIFORM else "\n  if(uHistorySize.x>400.0||uHistorySize.y>300.0)")
        if NEITHER_LARGE_ONLY else "\n ") +
       (f"w=mix(w,(1.0-uT)*a0+uT*c0,smoothstep({0.5*float(NEITHER_BLEND_T)}/255.0,"
        f"{float(NEITHER_BLEND_T)}/255.0,min(eM,e0))" +
        ("" if NEITHER_SPREAD_PX <= 0 else
         f"*smoothstep({0.5*float(NEITHER_SPREAD_PX)},{float(NEITHER_SPREAD_PX)},us)") + ");"
        if NEITHER_EDGE is None else
        f"{{float nk=smoothstep({0.5*float(NEITHER_BLEND_T)}/255.0,{float(NEITHER_BLEND_T)}/255.0,min(eM,e0))" +
        ("" if NEITHER_SPREAD_PX <= 0 else
         f"*smoothstep({0.5*float(NEITHER_SPREAD_PX)},{float(NEITHER_SPREAD_PX)},us)") + ";\n"
        "   if(nk>0.0){vec2 nx=vec2(1.0/uHistorySize.x,0.0),ny=vec2(0.0,1.0/uHistorySize.y);\n"
        "    float ng=max(max(md(abs(texture(uFrameA,u+nx).rgb-texture(uFrameA,u-nx).rgb)),"
        "md(abs(texture(uFrameA,u+ny).rgb-texture(uFrameA,u-ny).rgb))),"
        "max(md(abs(texture(uFrameC,u+nx).rgb-texture(uFrameC,u-nx).rgb)),"
        "md(abs(texture(uFrameC,u+ny).rgb-texture(uFrameC,u-ny).rgb))));\n"
        f"    w=mix(w,(1.0-uT)*a0+uT*c0,nk*(1.0-smoothstep({float(NEITHER_EDGE[0])}/255.0,"
        f"{float(NEITHER_EDGE[1])}/255.0,ng)));}}}}"))
    + ("" if DISAGREE_BLEND_T <= 0 else
       f"\n  w=mix(w,(1.0-uT)*a0+uT*c0,smoothstep({0.5*float(DISAGREE_BLEND_T)}/255.0,"
       f"{float(DISAGREE_BLEND_T)}/255.0,eM));")
    + "}\n"
    + ("" if PIXEL_PICK_T <= 0 or not PIXEL_SNAP else
       # Pixel art changes in discrete states (a palette step, a sprite's
       # next pose, a coin's next turn): two samples that disagree are two
       # states, and their blend is a colour or ghost the game never drew.
       # Take the nearer frame's sample (the newer one at the midpoint).
       ("" if PIXEL_PICK_ALL else " if(uDiscrete>0.5)" if DISCRETE_UNIFORM else
        f" if(uHistorySize.x<={PIXEL_SNAP[0]:.1f}&&uHistorySize.y<={PIXEL_SNAP[1]:.1f})") +
       f" w=mix(w,uT>=0.5?pc:pa,smoothstep({0.5*float(PIXEL_PICK_T)}/255.0,{float(PIXEL_PICK_T)}/255.0,md(abs(pa-pc))));\n")
    + ("" if not EDGE_OUTSIDE_SIDE else
       # Content entering or leaving the picture: a warp sample outside the
       # image only has the clamped edge (a smear); take the other frame's.
       " {vec2 pa=u-uT*v,pc=u+(1.0-uT)*v;\n"
       "  bool oa=any(lessThan(pa,vec2(0.0)))||any(greaterThan(pa,vec2(1.0)));\n"
       "  bool oc=any(lessThan(pc,vec2(0.0)))||any(greaterThan(pc,vec2(1.0)));\n"
       "  if(oa&&!oc)w=cw;else if(oc&&!oa)w=aw;}\n") +
    " if(uStructure>0.5&&length(v*uHistorySize)>=uStructureMinMotionPx){\n"
    "  w=mix(w,(1.0-uT)*a0+uT*c0,texture(uStructureMask,u).r);}\n"
    + ("" if not CONTENT_BOUNDS else
       " {vec4 bb=texture(uBounds,vec2(0.5));vec2 lo=bb.xz,hi=bb.yw;\n"
       "  if(any(lessThan(u,lo))||any(greaterThan(u,hi)))w=(1.0-uT)*a0+uT*c0;\n"
       "  else{vec2 pa=u-uT*v,pc=u+(1.0-uT)*v;\n"
       f"   vec2 mg={float(BORDER_MARGIN_PX)}/uHistorySize;\n"
       "   bool oa=any(lessThan(pa,lo-mg))||any(greaterThan(pa,hi+mg));\n"
       "   bool oc=any(lessThan(pc,lo-mg))||any(greaterThan(pc,hi+mg));\n"
       "   if(oa&&!oc)w=cw;else if(oc&&!oa)w=aw;\n" +
       ("" if EDGE_ONE_SIDED_PX <= 0 else
        "   else if(!oa&&!oc){vec2 hs=uHistorySize;\n"
        "    float de=min(min(u.x-lo.x,hi.x-u.x)*hs.x,min(u.y-lo.y,hi.y-u.y)*hs.y);\n"
        f"    if(de<{float(EDGE_ONE_SIDED_PX)}&&md(abs(aw-cw))>{float(EDGE_ONE_SIDED_T)}/255.0){{\n"
        "     float da=min(min(pa.x-lo.x,hi.x-pa.x)*hs.x,min(pa.y-lo.y,hi.y-pa.y)*hs.y);\n"
        "     float dc=min(min(pc.x-lo.x,hi.x-pc.x)*hs.x,min(pc.y-lo.y,hi.y-pc.y)*hs.y);\n"
        "     w=da>dc?aw:cw;}}\n") +
       ("" if EDGE_HOLD_PX <= 0 else
        "   {vec2 hs=uHistorySize;float de=min(min(u.x-lo.x,hi.x-u.x)*hs.x,min(u.y-lo.y,hi.y-u.y)*hs.y);\n"
        f"    float k=(1.0-smoothstep({0.5*float(EDGE_HOLD_PX)},{float(EDGE_HOLD_PX)},de))*"
        f"smoothstep({float(EDGE_HOLD_T)*0.5}/255.0,{float(EDGE_HOLD_T)}/255.0,md(abs(aw-cw)));\n"
        "    w=mix(w,uT<=0.5?a0:c0,k);}\n") +
       "  }}\n") +
    ("" if LATE_SHARE <= 0 or LATE_NEAR <= 0 else
     (f" w=mix(w,uT>=0.5?c0:a0,step(uDiscrete>0.5?{LATE_NEAR_DISCRETE}:{LATE_NEAR},"
      if DISCRETE_UNIFORM else f" w=mix(w,uT>=0.5?c0:a0,step({LATE_NEAR},") +
     "texture(uLate,vec2(0.5)).r));\n") +
    ("" if LATE_SHARE <= 0 else
     f" w=mix(w,(1.0-uT)*a0+uT*c0,step({LATE_SHARE},texture(uLate,vec2(0.5)).r));\n") +
    " vec4 ct=texture(uCut,vec2(0.5));\n"
    + ("" if FLASH_BLEND_LO <= 0 else
       f" w=mix(w,(1.0-uT)*a0+uT*c0,uCutEnabled*smoothstep({FLASH_BLEND_LO},{CUT_THRESHOLD},ct.r));\n") +
    f" w=mix(mix(w,a0,uCutEnabled*step({CUT_THRESHOLD},ct.r)),(1.0-uT)*a0+uT*c0,uCutEnabled*step(0.5,ct.g));\n"
    + ("" if not (FLASH_MEAN > 0 and FLASH_HOLD) else
       " w=mix(w,uT>=0.5?c0:a0,uCutEnabled*step(0.5,ct.b));\n") +
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
# Replay-bench experiment (2026-10-25): frames whose unexplained share (the
# cut evidence) is between FLASH_BLEND_LO and the cut threshold fade toward
# the temporal blend (a light flash over half the picture is warped into
# shards otherwise; Ocarina). 0 disables.
FLASH_BLEND_LO = 0.0
# Default since 3.2.105: a light flash -- the picture's mean luma changes by
# FLASH_MEAN or more, neither a scene cut nor a fitted fade -- shows the
# nearer real frame (the newer one at the midpoint): Ocarina's dungeon flash
# (mean luma +0.325; no other eval triplet changes it by more than 0.052) was
# warped into shards. Replay bench: Ocarina invented area 1.00 -> 0.05% of
# the frame, every other game bit-identical. Its temporal blend instead
# (FLASH_HOLD off) is a grey found in neither frame (1.06 -> 1.17%).
FLASH_MEAN = 0.1
FLASH_HOLD = True
# Since 3.2.111: a frame-level verdict after the per-phase motion -- on a
# LATE_GRID of samples, the share where neither the phase field's warp nor
# zero motion matches (largest channel difference over 32 grey levels) --
# and at LATE_SHARE or more the frame is the temporal blend (a one-frame
# dissolve) instead of a warp of nothing: missed hard cuts (Sonic
# Adventure's sky to Big, 67%), title dissolves (NSMBU Deluxe, 74%) and
# full-screen bursts. Over 500 replay triplets the share's median is 0.3%,
# its 95th percentile 10.4%; ~1% of frames reach 50%. The cut, fade and
# flash verdicts still override it. 0 disables.
LATE_SHARE = 0.5
LATE_GRID = (32, 18)
# Since 3.2.112 (owner, 2026-10-26: "no more artifacts"): from LATE_NEAR up
# to LATE_SHARE the frame is the nearer real frame (the newer one at the
# midpoint) -- content the game drew, one uneven step -- instead of a warp
# that leaves that much of the picture unexplained. Over 411 replay triplets
# (3.2.111 generator, full/eval/train/320x180 sets) frames at 0.10 or more
# are 5.6% of all and hold 60% of the invented area (Sonic Adventure's and
# Sonic Superstars' transitions, Mario Kart Wii's cut, Star Fox 64 and Wii U
# frames); 9 of the 411 were gated while already clean. 0 disables.
LATE_NEAR = 0.1
# Pixel art (uDiscrete): most of a 2-D frame is static or matches the warp,
# so a shredded sprite or a repeating wall leaves only a few percent of the
# grid unexplained. Over the 74 2-D replay triplets frames at 0.05 or more
# are 13.5% and hold 49% of the invented area -- Game Gear 6 of 14 (its
# lava bars and checkered walls, bosses), Mega Drive 2 of 10 -- while SNES,
# Game Boy and Master System frames never reach it; 3 clean frames gated.
LATE_NEAR_DISCRETE = 0.05


def late_verdict_shader():
    gw, gh = LATE_GRID
    return (HEADER +
    "uniform sampler2D uFrameA,uFrameC,uPhaseFlow;uniform float uT;uniform vec2 uFlowSize;\n"
    "layout(location=0) out vec4 o0;\n"
    "float md(vec3 x){return max(max(x.r,x.g),x.b);}\n"
    "void main(){float n=0.0;\n"
    f" for(int y=0;y<{gh};++y)for(int x=0;x<{gw};++x){{vec2 u=(vec2(float(x),float(y))+0.5)/vec2({float(gw)},{float(gh)});\n"
    "  vec2 v=texture(uPhaseFlow,u).xy/uFlowSize;\n"
    "  float eM=md(abs(texture(uFrameA,u-uT*v).rgb-texture(uFrameC,u+(1.0-uT)*v).rgb));\n"
    "  float e0=md(abs(texture(uFrameA,u).rgb-texture(uFrameC,u).rgb));\n"
    "  n+=step(32.0/255.0,min(eM,e0));}\n"
    f" o0=vec4(n/{float(gw * gh)},0.0,0.0,1.0);}}\n")


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
# Instead, offer that inside vector as one more field-choice candidate
# (taken only where its two warp samples agree better by 2 grey levels).
EDGE_CANDIDATE = False
# Offline experiment (2026-10-23): within EDGE_ONE_SIDED_PX history pixels of
# the picture's edge, where the two warp samples disagree by more than
# EDGE_ONE_SIDED_T grey levels (no correspondence: content entering or leaving
# view), take the sample whose source lies deeper inside the picture instead of
# blending both (sharp instead of a blurred/blotched mix). Needs CONTENT_BOUNDS.
# Offline experiment (2026-10-23): instead, fade toward the nearer real frame
# (unwarped) within EDGE_HOLD_PX of the edge where the warp samples disagree:
# the band then updates at the source rate but stays crisp and stable.
# Offline experiment (2026-10-23): clamp the generation pass's frame samples to
# the picture rectangle (needs CONTENT_BOUNDS).
CLAMP_WARP_SAMPLES = False
# Offline experiment (2026-10-23): where neither the warp nor zero motion
# explains a pixel (both five-tap mismatches over GHOST_SIDE_T grey levels:
# a sprite changing pose, a flash), fade toward one side -- the nearer frame,
# the newer one at the midpoint -- instead of a translucent 50/50 ghost.
GHOST_SIDE_T = 0.0
# ... only where the warp moves at least this many history pixels (a moving sprite).
GHOST_MIN_MOTION_PX = 0.0
EDGE_HOLD_PX = 0.0
EDGE_HOLD_T = 32.0
# Replay-bench experiments (2026-10-24): the warp length under which a pixel
# takes the zero-motion blend; where neither the warp nor zero motion explains
# a pixel (both five-tap mismatches over NEITHER_BLEND_T grey levels: a glow,
# a flash), fade to the zero-motion blend instead of keeping the warp; or fade
# to it wherever the warp's own samples disagree by DISAGREE_BLEND_T.
SUBPIXEL_ZERO_PX = 1.0
# A warp sample outside the image (content entering or leaving the picture)
# gives way to the other frame's sample.
EDGE_OUTSIDE_SIDE = False
# The warp / zero-motion comparison on five-tap differences less their mean
# (brightness-invariant). Needs SKIP_FLAT_CROSS.
DECISION_DEMEAN = False
# Small (pixel-art) histories, up to (width, height), the generator's small
# sources: whole-pixel warps (default since 3.2.99). Replay bench, paired:
# Mega Drive 0.520 -> 0.453 of a cross-fade, SNES 0.353 -> 0.322, NES 0.563
# -> 0.548; 3-D sources unaffected. Generated frames stay as crisp as the real
# ones instead of blurring every edge by half a pixel; with whole-pixel
# placement forgiven, solid artifacts are unchanged or fewer.
PIXEL_SNAP = (400, 300)
# Since 3.2.104 the pixel-art rules (whole-pixel warps, PIXEL_PICK_T, and no
# local cut) follow uDiscrete, set for the fixed-clock legacy consoles
# (InWindowGameHost.authoritativeVideoHz), not the history size: 3-D at
# 320x180 with whole-pixel warps scored Link's Awakening 1.316 of a
# cross-fade, 0.941 without; Mario 3D World 0.870 / 0.673, Wind Waker HD
# 0.520 / 0.368, Ocarina 0.701 / 0.579 -- PS1, DS and 3DS 3-D games are that small.
DISCRETE_UNIFORM = True
# Default since 3.2.104: for pixel-art systems, where the two samples a pixel
# blends differ by PIXEL_PICK_T grey levels, take the nearer frame's sample
# (the newer one at the midpoint) instead of their blend, a colour or ghost
# the game never drew (0 disables). Replay bench, paired, frames with content
# found in neither real frame: NES 82 -> 3%, Mega Drive 98 -> 78% (area 3.4 ->
# 0.7% of the frame), SNES 76 -> 41%, Game Boy 60 -> 25%; hold-out NES 0.572
# -> 0.387 of a cross-fade, Mega Drive 0.444 -> 0.392, SNES 0.327 -> 0.308.
# On 3-D content (any size) it is much worse: Link's Awakening 0.725 -> 1.171.
PIXEL_PICK_T = 24.0
# ... for every history size, not just the small ones.
PIXEL_PICK_ALL = False
# Where the warp's five-tap mismatch exceeds OCCLUSION_SIDE_T grey levels, take
# the sample whose own frame's DIS flow at its source agrees with the output
# vector by OCCLUSION_SIDE_MARGIN field pixels more than the other's does.
OCCLUSION_SIDE_T = 0.0
OCCLUSION_SIDE_MARGIN = 1.0
# Default since 3.2.100 with the two settings below: a local cut. Where
# neither the warp nor zero motion explains a pixel and the field around it
# is incoherent (no real correspondence: Star Fox 64's cast jumping to a new
# pose, Ocarina's glows), the blend replaces a shredded warp. All 1,400 moving
# triplets, larger sources: solid artifact area Star Fox 64 0.78 -> 0.49% of
# the frame, Ocarina 0.16 -> 0.07%, Wind Waker HD 0.042 -> 0.031%; average
# error +0.002 to +0.009 of a cross-fade. Pixel-art sources keep their
# whole-pixel warps (NES +0.034 with it).
NEITHER_BLEND_T = 32.0
# ... only where the neighbouring field vectors also spread by this many
# history pixels (the field is incoherent: no real correspondence there).
NEITHER_SPREAD_PX = 6.0
# ... and only for histories larger than the small (pixel-art) sources.
NEITHER_LARGE_ONLY = True
# Since 3.2.106 the local cut blends only where both real frames are smooth
# at the pixel: their largest neighbour difference (two history pixels
# apart) fades it out between NEITHER_EDGE grey levels; None blends
# everywhere. A blend of two smooth areas (a glow, a light ray, a lighting
# change) is no ghost, but at an object's outline it is a second,
# translucent copy -- content found in neither real frame. The
# cross-fade-relative "solid artifact" score that adopted the blend counts
# a pixel only where it is worse than the cross-fade, so it could not see
# those ghosts. Replay bench, paired, frames with content found in neither
# real frame: full-size captures (Double Dash, NSMBU Deluxe, Ocarina, Link's
# Awakening) 30 -> 15% (blend removed entirely; area 0.151 -> 0.061% of the
# frame); removing it entirely also turned smooth glows into faint blocks
# (Double Dash error 0.704 -> 0.747 of a cross-fade), which the edge test
# keeps blended.
NEITHER_EDGE = (2.0, 8.0)
DISAGREE_BLEND_T = 0.0
EDGE_ONE_SIDED_PX = 0.0
EDGE_ONE_SIDED_T = 24.0

# Bar threshold (grey levels) for BOUNDS; bars are pure black.
BOUNDS_T = 6.0
def bounds_shader():
    return (HEADER +
    "uniform sampler2D uGrayA,uGrayC;uniform ivec2 uSize;\n"
    "layout(location=0) out vec4 o0;\n"
    "float colMax(int x){float m=0.0;for(int k=0;k<24;++k){vec2 q=(vec2(float(x),float(k)*float(uSize.y)/24.0)+0.5)/vec2(uSize);\n"
    " m=max(m,max(texture(uGrayA,q).r,texture(uGrayC,q).r));}return m;}\n"
    "float rowMax(int y){float m=0.0;for(int k=0;k<32;++k){vec2 q=(vec2(float(k)*float(uSize.x)/32.0,float(y))+0.5)/vec2(uSize);\n"
    " m=max(m,max(texture(uGrayA,q).r,texture(uGrayC,q).r));}return m;}\n"
    f"void main(){{const float T={float(BOUNDS_T)}/255.0;int l=0,r=uSize.x-1,b=0,t=uSize.y-1;\n"
    " for(int x=0;x<uSize.x/2;++x){if(colMax(x)>T)break;l=x+1;}\n"
    " for(int x=uSize.x-1;x>=uSize.x/2;--x){if(colMax(x)>T)break;r=x-1;}\n"
    " for(int y=0;y<uSize.y/2;++y){if(rowMax(y)>T)break;b=y+1;}\n"
    " for(int y=uSize.y-1;y>=uSize.y/2;--y){if(rowMax(y)>T)break;t=y-1;}\n"
    " o0=vec4(float(l)/float(uSize.x),float(r+1)/float(uSize.x),float(b)/float(uSize.y),float(t+1)/float(uSize.y));}\n")


def generate_phase_shader():
    text = _generate_phase_shader_text()
    if not (CONTENT_BOUNDS and CLAMP_WARP_SAMPLES):
        return text
    # Every frame sample is clamped to the picture's outermost pixel centres,
    # so a warp landing within a pixel of a letter/pillarbox bar never blends
    # in its black (Ocarina: the first picture column 17% too dark).
    text = text.replace("texture(uFrameA,", "tA(").replace("texture(uFrameC,", "tC(")
    helpers = ("vec2 gLo,gHi;\n"
               "vec4 tA(vec2 p){return texture(uFrameA,clamp(p,gLo,gHi));}\n"
               "vec4 tC(vec2 p){return texture(uFrameC,clamp(p,gLo,gHi));}\n")
    text = text.replace("float md(vec3 x)", helpers + "float md(vec3 x)", 1)
    text = text.replace("void main(){vec2 u=vTexCoord;",
                        "void main(){{vec4 gb=texture(uBounds,vec2(0.5));gLo=gb.xz+0.5/uHistorySize;"
                        "gHi=gb.yw-0.5/uHistorySize;}vec2 u=vTexCoord;", 1)
    return text


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
    ("" if FLASH_MEAN <= 0 else
     f" float flash=step({FLASH_MEAN},abs(sb-sa)/n)*step(min(n0,n1)/n,{CUT_THRESHOLD - 0.001})" +
     ("*(1.0-fade);\n" if FLASH_HOLD else ";\n") +
     (" fade=max(fade,flash);\n" if not FLASH_HOLD else "")) +
    (" o0=vec4(min(n0,n1)/n,fade,flash,1.0);}\n" if FLASH_MEAN > 0 and FLASH_HOLD else
     " o0=vec4(min(n0,n1)/n,fade,0.0,1.0);}\n"))


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
            'TO_RAW': TO_RAW, 'PHASE_SEARCH': phase_search_shader(), 'PHASE_DENSIFY': phase_densify_shader(), 'PHASE_SMOOTH': phase_smooth_shader(), 'GRAY_CLAMP': GRAY_CLAMP, 'BOUNDS_ANY': bounds_shader(),
            'GENERATE_PHASE': generate_phase_shader(), 'CUT': cut_shader(), 'LATE_VERDICT': late_verdict_shader(),
            'DENSIFY_SHARP': sharp_densify_shader(), 'BOUNDS': bounds_shader()}


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


# Offline experiments the device does not compile (measured, not adopted).
OFFLINE_ONLY_SHADERS = ('PHASE_SMOOTH', 'GRAY_CLAMP', 'BOUNDS_ANY')


def java_source():
    lines = ["package com.thorium.preview.game;", "", "/**",
             " * Generated by tools/learned_framegen/dis_gles.py; do not edit, change the generator.",
             " * GPU dense inverse search (Kroeger et al., ECCV 2016), our own implementation.", " */",
             "final class DenseInverseSearchShaders {", "    private DenseInverseSearchShaders() {}", ""]
    for name, text in shaders().items():
        if name in OFFLINE_ONLY_SHADERS:
            continue
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
