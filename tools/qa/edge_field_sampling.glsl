uniform vec2 uDenseFieldSize;
vec4 edgeField(sampler2D field,vec2 uv){
    vec2 p=uv*uDenseFieldSize-.5;
    vec2 base=floor(p),f=fract(p);
    vec2 lo=(base+.5)/uDenseFieldSize,hi=(base+1.5)/uDenseFieldSize;
    vec4 a=texture2D(field,clamp(lo,0.0,1.0));
    vec4 b=texture2D(field,clamp(vec2(hi.x,lo.y),0.0,1.0));
    vec4 c=texture2D(field,clamp(vec2(lo.x,hi.y),0.0,1.0));
    vec4 d=texture2D(field,clamp(hi,0.0,1.0));
    vec2 va=decodeFlow(a)*uDenseSeedSourceSize;
    vec2 vb=decodeFlow(b)*uDenseSeedSourceSize;
    vec2 vc=decodeFlow(c)*uDenseSeedSourceSize;
    vec2 vd=decodeFlow(d)*uDenseSeedSourceSize;
    float spread=max(max(length(va-vb),length(va-vc)),max(length(vd-vb),length(vd-vc)));
    vec4 nearest=mix(mix(a,b,step(.5,f.x)),mix(c,d,step(.5,f.x)),step(.5,f.y));
    return spread>2.0?nearest:texture2D(field,uv);
}
