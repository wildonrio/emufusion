precision highp float;
uniform sampler2D uCosts;
uniform sampler2D uExcluded;
uniform float uExclude;
uniform float uSize,uRows;
varying vec2 vTexCoord;
float cost(vec4 p){vec2 b=floor(p.rg*255.0+.5);return b.x*256.0+b.y;}
float unpack(vec2 p){float q=dot(floor(p*255.0+.5),vec2(256.0,1.0));return (q>=32768.0?q-65536.0:q)/256.0;}
vec2 pack(float v){float q=mod(v*256.0+65536.0,65536.0);return vec2(floor(q/256.0),mod(q,256.0))/255.0;}
void main(){
    float radius=floor(uSize*.5),best=65536.0;
    vec2 bestXY=vec2(radius);
    vec4 selected=vec4(1.0);
    float row=floor(vTexCoord.y*uSize);
    for(int i=0;i<241;i++){
        if(float(i)<uSize){
            vec4 p;
            vec2 xy;
            if(uRows>.5){
                p=texture2D(uCosts,vec2(.5,(float(i)+.5)/uSize));
                xy=floor(p.ba*255.0+.5);
            }else{
                p=texture2D(uCosts,vec2((float(i)+.5)/uSize,(row+.5)/uSize));
                xy=vec2(float(i),row);
            }
            float z=cost(p);
            if(uExclude>.5&&uRows<.5){vec4 excluded=texture2D(uExcluded,vec2(.5));vec2 f=vec2(unpack(excluded.rg),unpack(excluded.ba));if(length(xy-radius-f)<=3.0)z=65536.0;}
            if(z<best||(z==best&&dot(xy-radius,xy-radius)<dot(bestXY-radius,bestXY-radius))){best=z;bestXY=xy;selected=p;}
        }
    }
    if(uRows>.5){vec2 flow=bestXY-radius;gl_FragColor=vec4(pack(flow.x),pack(flow.y));}
    else gl_FragColor=vec4(selected.rg,bestXY/255.0);
}
