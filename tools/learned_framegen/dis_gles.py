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
    " const float N=float(P*P);float m0=st/N;\n"
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
def densify_shader():
    return (HEADER +
    f"#define P {PATCH}\n#define S {STRIDE}\n"
    "uniform sampler2D uRef,uTarget,uPatches;\n"
    "uniform ivec2 uSize,uGrid;\n"
    "layout(location=0) out vec4 o0;\n"
    "void main(){ivec2 p=ivec2(gl_FragCoord.xy);float i0=texelFetch(uRef,p,0).r;\n"
    " ivec2 hi=min(p/S,uGrid-1);ivec2 lo=max((p-P+S)/S,ivec2(0));lo=min(lo,hi);\n"
    " vec2 acc=vec2(0.0);float wsum=0.0;\n"
    " for(int gy=lo.y;gy<=hi.y;++gy)for(int gx=lo.x;gx<=hi.x;++gx){\n"
    "  vec2 u=texelFetch(uPatches,ivec2(gx,gy),0).xy;\n"
    "  float d=abs(texture(uTarget,(vec2(p)+0.5+u)/vec2(uSize)).r-i0)*255.0;\n"
    "  float w=1.0/max(1.0,d);acc+=w*u;wsum+=w;}\n"
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
# the solver's raw output (signed Q8.8 per component in two bytes).
TO_RAW = (HEADER +
    "uniform sampler2D uFlow;uniform vec2 uScale;uniform float uLimit;uniform ivec2 uOut;\n"
    "layout(location=0) out vec4 o0;\n"
    "vec2 p16(float v){float r=mod(floor(v*256.0+.5)+65536.0,65536.0);return vec2(floor(r/256.0),mod(r,256.0))/255.0;}\n"
    "void main(){vec2 cell=1.0/vec2(uOut);vec2 c=gl_FragCoord.xy*cell;vec2 s=vec2(0.0);\n"
    " for(int y=0;y<4;++y)for(int x=0;x<4;++x)s+=texture(uFlow,c+(vec2(float(x),float(y))-1.5)*0.25*cell).xy;\n"
    " vec2 v=clamp(s/16.0*uScale,-uLimit,uLimit);o0=vec4(p16(v.x),p16(v.y));}\n")


def shaders():
    return {'VERTEX': VERTEX, 'VERTEX_QUAD': VERTEX_QUAD, 'GRAY': GRAY, 'DOWN': DOWN, 'GRAD': GRAD,
            'PATCH_SEARCH': patch_search_shader(), 'DENSIFY': densify_shader(), 'GENERATE': GENERATE,
            'TO_RAW': TO_RAW}


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
