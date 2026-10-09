precision highp float;
varying vec2 vTexCoord;
uniform sampler2D uLeft;
uniform sampler2D uRight;
uniform sampler2D uFollowing;
uniform sampler2D uGenerated;
uniform vec2 uTexel;
uniform bool uHasFollowing;
uniform bool uMaskOnly;
vec3 bytes(vec3 v) { return floor(v * 255.0 + 0.5); }
float delta(vec3 a, vec3 b) {
    vec3 d=abs(a-b); return max(d.x,max(d.y,d.z));
}
void main() {
    vec4 generated=texture2D(uGenerated,vTexCoord);
    vec3 left=bytes(texture2D(uLeft,vTexCoord).rgb);
    if (uMaskOnly && !uHasFollowing) { gl_FragColor=vec4(0.0); return; }
    if (!uMaskOnly && (!uHasFollowing || delta(left,bytes(generated.rgb))<=1.0)) {
        gl_FragColor=generated; return;
    }
    for (int y=-2;y<=2;++y) for (int x=-2;x<=2;++x) {
        vec2 pos=vTexCoord+vec2(float(x),float(y))*uTexel;
        vec3 a=bytes(texture2D(uLeft,pos).rgb);
        if (delta(a,bytes(texture2D(uRight,pos).rgb))>1.0 ||
            delta(a,bytes(texture2D(uFollowing,pos).rgb))>1.0) {
            gl_FragColor=uMaskOnly ? vec4(0.0) : generated; return;
        }
    }
    gl_FragColor=uMaskOnly ? vec4(1.0) : vec4(left/255.0,generated.a);
}
