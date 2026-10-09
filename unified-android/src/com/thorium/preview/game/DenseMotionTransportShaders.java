package com.thorium.preview.game;

/** Shared experimental transport shaders. Not enabled by the renderer yet.
 * Requires vertex texture sampling, a depth attachment, nearest flow sampling,
 * and four support-corner vertices per source cell. Camera-relative priority is
 * not a general depth solution. Host image QA compiles these exact strings.
 */
final class DenseMotionTransportShaders {
    private DenseMotionTransportShaders() {}

    /** Four strip vertices per instance, no per-pixel CPU vertex allocation.
     * gridSize describes the SOURCE pixel grid, not the reduced flow texture.
     * size remains the destination raster dimensions used by the footprint.
     */
    static String instancedVertex() {
        return "#version 300 es\n" + VERTEX
                .replace("attribute vec2 aSourceUv,aCorner,aExtraRadius;", "uniform ivec2 gridSize;")
                .replace("varying ", "out ")
                .replace("texture2D(", "texture(")
                .replace("void main(){", "void main(){\n"
                        + " vec2 aSourceUv=(vec2(float(gl_InstanceID%gridSize.x),float(gl_InstanceID/gridSize.x))+vec2(.5))/vec2(gridSize);\n"
                        + " vec2 aExtraRadius=vec2(0.);\n"
                        + " vec2 aCorner=vec2(float(gl_VertexID&1),float((gl_VertexID>>1)&1))*2.-1.;\n");
    }

    static String instancedFragment() {
        return "#version 300 es\n" + FRAGMENT
                .replace("varying ", "in ")
                .replace("void main(){", "out vec4 transportColor;\nvoid main(){")
                .replace("gl_FragColor", "transportColor");
    }

    static int instanceCount(int sourceWidth, int sourceHeight) {
        if (sourceWidth <= 0 || sourceHeight <= 0
                || (long) sourceWidth * sourceHeight > Integer.MAX_VALUE) {
            throw new IllegalArgumentException("Invalid source grid");
        }
        return sourceWidth * sourceHeight;
    }

    /** Consumer of COMPACT nodes. Caller must issue shader-storage and command
     * barriers before glDrawArraysIndirect, with command initialized to {4,0,0,0}.
     * Node storage must hold sourceWidth*sourceHeight vec4 records (worst case).
     * Experimental GLES3.1 path; not connected to the renderer.
     */
    static String compactVertex() {
        return "#version 310 es\n" + VERTEX
                .replace("attribute vec2 aSourceUv,aCorner,aExtraRadius;",
                        "layout(std430,binding=1) readonly buffer Nodes { vec4 nodes[]; };")
                .replace("varying ", "out ")
                .replace("texture2D(", "texture(")
                .replace("void main(){", "void main(){\n"
                        + " vec4 node=nodes[gl_InstanceID];\n"
                        + " vec2 aSourceUv=(node.xy+vec2(node.z*.5))/sourceSize;\n"
                        + " vec2 aExtraRadius=vec2((node.z-1.)*.5);\n"
                        + " vec2 aCorner=vec2(float(gl_VertexID&1),float((gl_VertexID>>1)&1))*2.-1.;\n");
    }

    static final String COMPACT =
            "#version 310 es\nprecision highp float;precision highp int;\n" +
            "layout(local_size_x=8,local_size_y=8) in;\n" +
            "uniform highp sampler2D field,rawField;uniform ivec2 sourceGrid;\n" +
            "layout(std430,binding=0) buffer Command { uint count;uint instanceCount;uint first;uint baseInstance; };\n" +
            "layout(std430,binding=1) writeonly buffer Nodes { vec4 nodes[]; };\n" +
            "shared vec4 fields[64];shared vec4 raws[64];\n" +
            "shared int mergeable[192];\n" +
            "void main(){\n" +
            " ivec2 local=ivec2(gl_LocalInvocationID.xy),origin=ivec2(gl_WorkGroupID.xy)*8;\n" +
            " ivec2 pixel=origin+local;int index=local.y*8+local.x;\n" +
            " bool valid=all(lessThan(pixel,sourceGrid));\n" +
            " vec2 uv=(vec2(pixel)+vec2(.5))/vec2(sourceGrid);\n" +
            " fields[index]=valid?textureLod(field,uv,0.):vec4(0.);\n" +
            " raws[index]=valid?textureLod(rawField,uv,0.):vec4(0.);\n" +
            " barrier();\n" +
            " int level=0;\n" +
            " for(int side=2;side<=8;side*=2){\n" +
            "  bool same=all(equal((local/side)*side,local)) && all(lessThan(pixel+ivec2(side-1),sourceGrid));\n" +
            "  int childSide=side/2;\n" +
            "  for(int y=0;y<2 && same;y++)for(int x=0;x<2 && same;x++){\n" +
            "   int i=(local.y+y*childSide)*8+local.x+x*childSide;\n" +
            "   same=all(equal(fields[index],fields[i])) && all(equal(raws[index],raws[i]));\n" +
            "   if(side>2)same=same && mergeable[(level-1)*64+i]!=0;\n" +
            "  }\n" +
            "  mergeable[level*64+index]=same?1:0;barrier();level++;\n" +
            " }\n" +
            " barrier();if(!valid)return;\n" +
            " int selected=1;ivec2 corner=local;level=2;\n" +
            " for(int side=8;side>=2;side/=2){\n" +
            "  ivec2 start=(local/side)*side;\n" +
            "  if(mergeable[level*64+start.y*8+start.x]!=0){selected=side;corner=start;break;}\n" +
            "  level--;\n" +
            " }\n" +
            " if(all(equal(local,corner))){uint slot=atomicAdd(instanceCount,1u);nodes[slot]=vec4(vec2(origin+corner),float(selected),0.);}\n" +
            "}\n";

    static final String VERTEX =
            "precision highp float;\n" +
            "attribute vec2 aSourceUv,aCorner,aExtraRadius;\n" +
            "uniform sampler2D field,rawField,cameraSeed;\n" +
            "uniform float phase,useRaw,useCameraSeed;\n" +
            "uniform vec2 size,camera,flowRange,sourceSize;\n" +
            "varying vec4 flow;varying vec2 center,radius;\n" +
            "float unpackRaw(vec2 p){float n=floor(p.x*255.+.5)*256.+floor(p.y*255.+.5);return n>=32768.?n-65536.:n;}\n" +
            "void main(){\n" +
            " flow=texture2D(field,aSourceUv);\n" +
            " vec2 c=(flow.rg*255.-128.)/127.;\n" +
            " vec2 v=sign(c)*c*c*flowRange;\n" +
            " if(useRaw>.5){vec4 raw=texture2D(rawField,aSourceUv);v=vec2(unpackRaw(raw.rg),unpackRaw(raw.ba))/256./sourceSize;vec2 n=v/flowRange;flow.rg=(vec2(128.)+127.*sign(n)*sqrt(abs(n)))/255.;}\n" +
            " vec2 q=aSourceUv+phase*v;\n" +
            " center=q*size;\n" +
            " radius=vec2(1.)+aExtraRadius;\n" +
            " vec2 cameraMotion=camera;\n" +
            " if(useCameraSeed>.5){vec4 seed=texture2D(cameraSeed,vec2(.5));cameraMotion=vec2(unpackRaw(seed.rg),unpackRaw(seed.ba))/256./sourceSize;}\n" +
            " gl_Position=vec4((q+aCorner*radius/size)*2.-1.,.5-min(length(v-cameraMotion),.5),1.);\n" +
            "}\n";

    /** Exact 2/4/8 tile classifier. Mixed or partial tiles cannot merge. */
    static final String CLASSIFY =
            "precision highp float;\n" +
            "uniform sampler2D field,rawField;uniform vec2 sourceSize;uniform float tileSide;\n" +
            "void main(){\n" +
            " vec2 base=floor(gl_FragCoord.xy)*tileSide;\n" +
            " vec2 uv=(base+vec2(.5))/sourceSize;\n" +
            " vec4 f=texture2D(field,uv),r=texture2D(rawField,uv);\n" +
            " bool same=(tileSide==2. || tileSide==4. || tileSide==8.) && all(lessThan(base+vec2(tileSide-1.),sourceSize));\n" +
            " for(int y=0;y<8;y++)for(int x=0;x<8;x++){\n" +
            "  if(float(x)>=tileSide || float(y)>=tileSide)continue;\n" +
            "  vec2 q=uv+vec2(float(x),float(y))/sourceSize;\n" +
            "  same=same && all(equal(f,texture2D(field,q))) && all(equal(r,texture2D(rawField,q)));\n" +
            " }\n" +
            " gl_FragColor=vec4(same?1.:0.,0.,0.,1.);\n" +
            "}\n";

    static final String FRAGMENT =
            "precision highp float;\n" +
            "varying vec4 flow;varying vec2 center,radius;\n" +
            "void main(){\n" +
            " vec2 support=max(vec2(0.),radius-abs(gl_FragCoord.xy-center));\n" +
            " if(flow.b<48./255. || support.x*support.y<0.00001)discard;\n" +
            " gl_FragColor=flow;\n" +
            "}\n";
}
