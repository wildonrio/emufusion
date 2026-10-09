precision highp float;
varying vec2 vTexCoord;
uniform sampler2D uLeft;
uniform sampler2D uGenerated;
uniform sampler2D uMask;
void main() {
    vec4 generated=texture2D(uGenerated,vTexCoord);
    vec3 left=floor(texture2D(uLeft,vTexCoord).rgb*255.0+0.5);
    vec3 delta=abs(left-floor(generated.rgb*255.0+0.5));
    if (texture2D(uMask,vTexCoord).r>0.5 && max(delta.x,max(delta.y,delta.z))>1.0)
        gl_FragColor=vec4(left/255.0,generated.a);
    else gl_FragColor=generated;
}
