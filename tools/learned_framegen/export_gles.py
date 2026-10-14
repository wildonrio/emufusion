"""Export a trained PhaseNet as GLSL ES 3.00 fragment shaders (weights baked in).

usage: python3 -m tools.learned_framegen.export_gles CHECKPOINT [--java OUT.java] [--glsl-dir DIR]

Every pass draws a full-screen triangle into 1-4 render targets. RGBA8
targets reproduce the network's clip-and-quantise activation; fields and
logits are RGBA16F. All passes address textures in the network's top-origin
pixel coordinates (row 0 = top of the image): GL texture row 0 is the bottom,
so each fetch maps y -> size.y - 1 - y and each filtered sample maps
v -> 1 - v. This keeps PyTorch's kernel orientation, stride-2 alignment and
vector signs without transforming any weight.

Pass interfaces (uniform names) are fixed here and in LearnedFrameEstimator:
  mip        uIn0, uIn (ivec2), uOut (ivec2)
  conv_*     uIn0..uIn{n-1}, uIn, uOut
  corr       uA0..3, uB0..3 (features), uCoarse (RGBA16F), uHasCoarse, uT, uOut
  head*_out  uIn0..3, uCoarse, uHasCoarse, uIn, uOut         (residual field)
  vis_in     uA0..3, uB0..3, uLow1, uLow2, uOut               (correlations + 1x1)
  vis_out    uIn0..1, uPrev (RGBA16F), uHasPrev, uIn, uOut    (residual logits)
  generate   uFrameA, uFrameB, uF1, uF2, uW, uT, uQ0 (vec2); vertex shader VERTEX_QUAD
"""
import argparse
from pathlib import Path

import numpy as np
import torch

from .model import OFFSETS, PhaseNet

VERTEX = (
    "#version 300 es\n"
    "void main(){vec2 p=vec2(gl_VertexID==1?3.0:-1.0,gl_VertexID==2?3.0:-1.0);"
    "gl_Position=vec4(p,0.0,1.0);}\n")

HEADER = "#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n"

# Top-origin helpers shared by the passes.
HELPERS = (
    "ivec2 here(ivec2 size){ivec2 p=ivec2(gl_FragCoord.xy);return ivec2(p.x,size.y-1-p.y);}\n"
    "vec4 fetch(sampler2D t,ivec2 q,ivec2 size){q=clamp(q,ivec2(0),size-1);"
    "return texelFetch(t,ivec2(q.x,size.y-1-q.y),0);}\n"
    # p: continuous top-origin pixel coordinates (texel centres at +0.5).
    "vec4 at(sampler2D t,vec2 p,vec2 size){vec2 u=p/size;return texture(t,vec2(u.x,1.0-u.y));}\n")


def f(x):
    v = float(x)
    if v == 0.0:
        return "0.0"
    return repr(round(v, 7)) if abs(v) >= 1e-4 else f"{v:.6e}"


def mat4_literal(w):
    """w[out4, in4] -> mat4 whose product with an input vec4 gives the four outputs."""
    cols = [w[:, i] for i in range(4)]  # GLSL mat4 constructor is column-major
    return "mat4(" + ",".join(f(v) for col in cols for v in col) + ")"


def padded(weight, bias, cin, cout):
    """Pad a conv weight (cout, cin, k, k) and bias to multiples of four channels."""
    k = weight.shape[-1]
    w = np.zeros((cout, cin, k, k), np.float64)
    w[:weight.shape[0], :weight.shape[1]] = weight
    b = np.zeros(cout, np.float64)
    b[:bias.shape[0]] = bias
    return w, b


def conv_body(weight, bias, inputs, outputs, stride, emit):
    """Accumulators a0..; returns code computing them from uIn0.. for a 3x3 conv."""
    w, b = padded(weight, bias, inputs * 4, outputs * 4)
    k = w.shape[-1]
    r = k // 2
    lines = [f" ivec2 P=here(uOut)*{stride};"]
    for j in range(outputs):
        lines.append(f" vec4 a{j}=vec4({','.join(f(v) for v in b[4 * j:4 * j + 4])});")
    for ky in range(k):
        for kx in range(k):
            dy, dx = ky - r, kx - r
            for i in range(inputs):
                lines.append(f" {{vec4 x=fetch(uIn{i},P+ivec2({dx},{dy}),uIn);")
                for j in range(outputs):
                    block = w[4 * j:4 * j + 4, 4 * i:4 * i + 4, ky, kx]
                    if np.any(block):
                        lines.append(f"  a{j}+={mat4_literal(block)}*x;")
                lines.append(" }")
    return "\n".join(lines) + "\n"


def conv_shader(layer, inputs, outputs, stride=1):
    weight = layer.weight.detach().double().numpy()
    bias = layer.bias.detach().double().numpy()
    decl = "".join(f"uniform sampler2D uIn{i};\n" for i in range(inputs))
    outs = "".join(f"layout(location={j}) out vec4 o{j};\n" for j in range(outputs))
    body = conv_body(weight, bias, inputs, outputs, stride, None)
    store = "".join(f" o{j}=a{j};\n" for j in range(outputs))
    return (HEADER + decl + "uniform ivec2 uIn,uOut;\n" + outs + HELPERS +
            "void main(){\n" + body + store + "}\n")


def mip_shader():
    return (HEADER + "uniform sampler2D uIn0;\nuniform ivec2 uIn,uOut;\n"
            "layout(location=0) out vec4 o0;\n" + HELPERS +
            "void main(){ivec2 P=here(uOut)*2;\n"
            " o0=0.25*(fetch(uIn0,P,uIn)+fetch(uIn0,P+ivec2(1,0),uIn)+fetch(uIn0,P+ivec2(0,1),uIn)"
            "+fetch(uIn0,P+ivec2(1,1),uIn));}\n")


FEATURE_DECL = "".join(f"uniform sampler2D uA{i};\n" for i in range(4)) + \
    "".join(f"uniform sampler2D uB{i};\n" for i in range(4))


def coarse_lookup(name):
    """Upsampled coarse field at x + offset, rescaled to this level's texels."""
    return (f"vec4 {name}At(vec2 p){{vec2 cs=vec2(textureSize({name},0));vec2 r=vec2(uOut)/cs;"
            f"vec2 u=p/vec2(uOut);return texture({name},vec2(u.x,1.0-u.y))*vec4(r,r);}}\n")


def corr_shader(head):
    scale = head.affine.weight.detach().double().numpy().reshape(9)
    shift = head.affine.bias.detach().double().numpy().reshape(9)
    code = [HEADER, FEATURE_DECL,
            "uniform sampler2D uCoarse;\nuniform float uHasCoarse,uT;\nuniform ivec2 uOut;\n",
            "layout(location=0) out vec4 o0;\nlayout(location=1) out vec4 o1;\nlayout(location=2) out vec4 o2;\n",
            HELPERS, coarse_lookup("uCoarse"),
            "void main(){vec2 S=vec2(uOut);ivec2 P=here(uOut);vec2 x=vec2(P)+0.5;\n",
            " vec4 c=uHasCoarse>0.5?uCoarseAt(x):vec4(0.0);\n",
            " vec2 pa=x+2.0*uT*c.xy;vec2 pb=clamp(x+2.0*(1.0-uT)*c.zw,vec2(0.5),S-0.5);\n",
            " vec4 a0=at(uA0,pa,S),a1=at(uA1,pa,S),a2=at(uA2,pa,S),a3=at(uA3,pa,S);\n",
            " float v[12];v[9]=0.0;v[10]=0.0;v[11]=0.0;\n"]
    for i, (dx, dy) in enumerate(OFFSETS):
        code.append(f" {{vec2 q=pb+vec2({dx}.0,{dy}.0);float r=dot(a0,at(uB0,q,S))+dot(a1,at(uB1,q,S))"
                    f"+dot(a2,at(uB2,q,S))+dot(a3,at(uB3,q,S));v[{i}]=r*{f(scale[i])}+{f(shift[i])};}}\n")
    code.append(" o0=vec4(v[0],v[1],v[2],v[3]);o1=vec4(v[4],v[5],v[6],v[7]);o2=vec4(v[8],0.0,0.0,0.0);}\n")
    return "".join(code)


def head_out_shader(layer):
    """16 -> 2 increment; field = up(coarse) + (d, -d), stored RGBA16F."""
    weight = layer.weight.detach().double().numpy()
    bias = layer.bias.detach().double().numpy()
    body = conv_body(weight, bias, 4, 1, 1, None)
    return (HEADER + "".join(f"uniform sampler2D uIn{i};\n" for i in range(4)) +
            "uniform sampler2D uCoarse;\nuniform float uHasCoarse;\nuniform ivec2 uIn,uOut;\n"
            "layout(location=0) out vec4 o0;\n" + HELPERS + coarse_lookup("uCoarse") +
            "void main(){\n" + body +
            " vec4 c=uHasCoarse>0.5?uCoarseAt(vec2(P)+0.5):vec4(0.0);\n"
            " o0=c+vec4(a0.xy,-a0.xy);}\n")


def vis_in_shader(vis):
    scale = vis.affine.weight.detach().double().numpy().reshape(36)
    shift = vis.affine.bias.detach().double().numpy().reshape(36)
    w = vis.c0.weight.detach().double().numpy()[:, :, 0, 0]  # (8, 36)
    b = vis.c0.bias.detach().double().numpy()
    code = [HEADER, FEATURE_DECL,
            "uniform sampler2D uLow1,uLow2;\nuniform float uT;\nuniform ivec2 uOut;\n",
            "layout(location=0) out vec4 o0;\nlayout(location=1) out vec4 o1;\n",
            HELPERS, coarse_lookup("uLow1"), coarse_lookup("uLow2"),
            "float q8(float v){return floor(clamp(v,0.0,1.0)*255.0+0.5)/255.0;}\n",
            "void main(){vec2 S=vec2(uOut);ivec2 P=here(uOut);vec2 x=vec2(P)+0.5;float v[36];\n",
            " vec4 na0[9],na1[9],na2[9],na3[9],nb0[9],nb1[9],nb2[9],nb3[9];\n"]
    for i, (dx, dy) in enumerate(OFFSETS):
        code.append(f" na0[{i}]=fetch(uA0,P+ivec2({dx},{dy}),uOut);na1[{i}]=fetch(uA1,P+ivec2({dx},{dy}),uOut);"
                    f"na2[{i}]=fetch(uA2,P+ivec2({dx},{dy}),uOut);na3[{i}]=fetch(uA3,P+ivec2({dx},{dy}),uOut);\n"
                    f" nb0[{i}]=fetch(uB0,P+ivec2({dx},{dy}),uOut);nb1[{i}]=fetch(uB1,P+ivec2({dx},{dy}),uOut);"
                    f"nb2[{i}]=fetch(uB2,P+ivec2({dx},{dy}),uOut);nb3[{i}]=fetch(uB3,P+ivec2({dx},{dy}),uOut);\n")
    for block, low in ((0, "uLow1"), (18, "uLow2")):
        code.append(
            f" {{vec4 h={low}At(x);vec2 q=-2.0*(1.0-uT)*h.zw;vec2 ta=q+2.0*uT*{low}At(x+q).xy;\n"
            f"  vec2 q2=-2.0*uT*h.xy;vec2 tb=q2+2.0*(1.0-uT)*{low}At(x+q2).zw;\n"
            "  vec4 s0=at(uA0,x+ta,S),s1=at(uA1,x+ta,S),s2=at(uA2,x+ta,S),s3=at(uA3,x+ta,S);\n"
            "  vec4 r0=at(uB0,x+tb,S),r1=at(uB1,x+tb,S),r2=at(uB2,x+tb,S),r3=at(uB3,x+tb,S);\n"
            "  for(int i=0;i<9;++i){\n"
            f"   v[{block}+i]=dot(s0,nb0[i])+dot(s1,nb1[i])+dot(s2,nb2[i])+dot(s3,nb3[i]);\n"
            f"   v[{block + 9}+i]=dot(r0,na0[i])+dot(r1,na1[i])+dot(r2,na2[i])+dot(r3,na3[i]);}}}}\n")
    for i in range(36):
        code.append(f" v[{i}]=q8(v[{i}]*{f(scale[i])}+{f(shift[i])});\n")
    for j in range(2):
        terms = []
        for o in range(4 * j, 4 * j + 4):
            s = f(b[o]) + "".join(f"+v[{i}]*{f(w[o, i])}" for i in range(36) if w[o, i] != 0)
            terms.append(s)
        code.append(f" o{j}=vec4({','.join(terms)});\n")
    code.append("}\n")
    return "".join(code)


def vis_out_shader(layer):
    weight = layer.weight.detach().double().numpy()
    bias = layer.bias.detach().double().numpy()
    body = conv_body(weight, bias, 2, 1, 1, None)
    return (HEADER + "uniform sampler2D uIn0,uIn1,uPrev;\nuniform float uHasPrev;\nuniform ivec2 uIn,uOut;\n"
            "layout(location=0) out vec4 o0;\n" + HELPERS + coarse_lookup("uPrev") +
            "void main(){\n" + body.replace("vec4 x=fetch(uIn", "vec4 x=fetch(uIn") +
            " vec4 prev=uHasPrev>0.5?texture(uPrev,vec2((vec2(P)+0.5).x/float(uOut.x),"
            "1.0-(vec2(P)+0.5).y/float(uOut.y))):vec4(0.0);\n"
            " o0=a0+prev;}\n")


# The output pass draws the generator's own destination quad (aPosition,
# aTexCoord), so letterboxing and placement match the other synthesis paths.
VERTEX_QUAD = (
    "#version 300 es\n"
    "in vec2 aPosition;in vec2 aTexCoord;out vec2 vTexCoord;\n"
    "void main(){gl_Position=vec4(aPosition,0.0,1.0);vTexCoord=aTexCoord;}\n")


def generate_shader():
    """Four candidates, logits read at each source, softmax times the phase weights."""
    return (HEADER +
            "uniform sampler2D uFrameA,uFrameB,uF1,uF2,uW;\nuniform float uT;\nuniform vec2 uQ0;\n"
            "in vec2 vTexCoord;\nlayout(location=0) out vec4 o0;\n"
            "vec4 tap(sampler2D t,vec2 u){return texture(t,vec2(u.x,1.0-u.y));}\n"
            "void main(){vec2 u=vec2(vTexCoord.x,1.0-vTexCoord.y);\n"
            " vec4 g1=tap(uF1,u)/vec4(uQ0,uQ0),g2=tap(uF2,u)/vec4(uQ0,uQ0);\n"
            " vec2 p0=u+2.0*uT*g1.xy,p1=u+2.0*(1.0-uT)*g1.zw,p2=u+2.0*uT*g2.xy,p3=u+2.0*(1.0-uT)*g2.zw;\n"
            " vec4 l=vec4(tap(uW,p0).x,tap(uW,p1).y,tap(uW,p2).z,tap(uW,p3).w);\n"
            " vec4 e=exp(l-max(max(l.x,l.y),max(l.z,l.w)));\n"
            " vec4 w=e*vec4(1.0-uT,uT,1.0-uT,uT);w/=dot(w,vec4(1.0))+1e-8;\n"
            " vec3 c=w.x*tap(uFrameA,p0).rgb+w.y*tap(uFrameB,p1).rgb+w.z*tap(uFrameA,p2).rgb+w.w*tap(uFrameB,p3).rgb;\n"
            " o0=vec4(c,1.0);}\n")


def shaders(model):
    e, h1, h2, v = model.encoder, model.head1, model.head2, model.visibility
    return {
        'VERTEX': VERTEX,
        'VERTEX_QUAD': VERTEX_QUAD,
        'MIP': mip_shader(),
        'ENC0': conv_shader(e.c0, 1, 2, 2),
        'ENC1': conv_shader(e.c1, 2, 2),
        'ENC2': conv_shader(e.c2, 2, 4, 2),
        'ENC3': conv_shader(e.c3, 4, 4),
        'CORR': corr_shader(h1),
        'H1C1': conv_shader(h1.c1, 3, 4), 'H1C2': conv_shader(h1.c2, 4, 4),
        'H1C3': conv_shader(h1.c3, 4, 4), 'H1OUT': head_out_shader(h1.c4),
        'H2C1': conv_shader(h2.c1, 3, 4), 'H2C2': conv_shader(h2.c2, 4, 4),
        'H2C3': conv_shader(h2.c3, 4, 4), 'H2OUT': head_out_shader(h2.c4),
        'VIS0': vis_in_shader(v),
        'VIS1': conv_shader(v.c1, 2, 2), 'VIS2': conv_shader(v.c2, 2, 2),
        'VIS3': conv_shader(v.c3, 2, 2), 'VISOUT': vis_out_shader(v.c4),
        'GENERATE': generate_shader(),
    }


def java_class(sources, checkpoint_name):
    lines = ["package com.thorium.preview.game;", "",
             "/**",
             " * Generated by tools/learned_framegen/export_gles.py from " + checkpoint_name + ".",
             " * Do not edit: retrain/re-export instead. Our own trained weights.",
             " */",
             "final class LearnedFrameShaders {",
             "    private LearnedFrameShaders() {}", ""]
    for name, src in sources.items():
        parts = [src[i:i + 2000] for i in range(0, len(src), 2000)]
        lines.append(f"    static final String {name} = new StringBuilder({len(src)})")
        for part in parts:
            lines.append("            .append(" + java_string(part) + ")")
        lines.append("            .toString();")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def java_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('checkpoint')
    parser.add_argument('--java')
    parser.add_argument('--glsl-dir')
    parser.add_argument('--levels', type=int, default=5)
    args = parser.parse_args()
    model = PhaseNet(levels=args.levels)
    model.load_state_dict(torch.load(args.checkpoint, map_location='cpu'))
    model.eval()
    sources = shaders(model)
    if args.glsl_dir:
        out = Path(args.glsl_dir); out.mkdir(parents=True, exist_ok=True)
        for name, src in sources.items():
            (out / f"{name}.{'vert' if name.startswith('VERTEX') else 'frag'}").write_text(src)
    if args.java:
        Path(args.java).write_text(java_class(sources, Path(args.checkpoint).name))
    print({k: len(v) for k, v in sources.items()})


if __name__ == '__main__':
    main()
