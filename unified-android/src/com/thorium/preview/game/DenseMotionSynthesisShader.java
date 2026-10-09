package com.thorium.preview.game;

/** Experimental shared synthesis builder; renderer activation remains separate. */
final class DenseMotionSynthesisShader {
    private DenseMotionSynthesisShader() {}

    static final String LAYER_HELPER = "\nvec2 decodeEndpoint(vec4 field){return mix(decodeFlow(field),seedDec(field)/uDenseSeedSourceSize,uEndpointPacked);}\nfloat cleanLayer(sampler2D motion,vec2 uv,vec2 expectedMotion){\n vec2 pixel=uv*uDenseSeedSourceSize-vec2(.5);\n vec2 base=floor(pixel),fraction=fract(pixel);\n float clean=1.;\n for(int y=0;y<2;y++)for(int x=0;x<2;x++){\n  vec2 offset=vec2(float(x),float(y));\n  vec2 weight=mix(vec2(1.)-fraction,fraction,offset);\n  vec2 tap=(base+offset+vec2(.5))/uDenseSeedSourceSize;\n  vec2 actual=decodeEndpoint(texture2D(motion,clamp(tap,vec2(0.),vec2(1.))));\n  float mismatch=step(.75,length((actual-expectedMotion)*uDenseSeedSourceSize));\n  clean*=1.-step(.00001,weight.x*weight.y)*mismatch;\n }\n return clean;\n}\n";
    static final String LAYER_CORRECTION = "\n float cleanA=cleanLayer(uEndpointForward,previousUv,forward);\n float cleanB=cleanLayer(uEndpointBackward,currentUv,backward);\n vec4 unfilteredA=a,unfilteredB=b;\n a=mix(unfilteredA,unfilteredB,(1.-cleanA)*cleanB*previousGate*currentGate);\n b=mix(unfilteredB,unfilteredA,(1.-cleanB)*cleanA*previousGate*currentGate);\n";
    static final String HOLE_CORRECTION = "\n vec2 backgroundCameraForward=uEndpointCameraForward;\n vec2 backgroundCameraBackward=uEndpointCameraBackward;\n if(uDenseSeedEnabled>.5){backgroundCameraForward=seedDec(texture2D(uDenseSeedForwardTex,vec2(.5)))/uDenseSeedSourceSize;backgroundCameraBackward=seedDec(texture2D(uDenseSeedBackwardTex,vec2(.5)))/uDenseSeedSourceSize;}\n\n float uncovered=(1.0-anySupported)*step(0.0001,uPhase)*(1.0-step(0.9999,uPhase));\n vec2 backgroundA=vTexCoord-backgroundCameraForward*uPhase;\n vec2 backgroundB=vTexCoord-backgroundCameraBackward*(1.-uPhase);\n float visibleA=cleanLayer(uEndpointForward,backgroundA,backgroundCameraForward);\n float visibleB=cleanLayer(uEndpointBackward,backgroundB,backgroundCameraBackward);\n visibleA*=step(0.,min(backgroundA.x,backgroundA.y))*(1.-step(1.,max(backgroundA.x,backgroundA.y)));\n visibleB*=step(0.,min(backgroundB.x,backgroundB.y))*(1.-step(1.,max(backgroundB.x,backgroundB.y)));\n vec3 exposedA=texture2D(uPrevious,clamp(backgroundA,vec2(0.),vec2(1.))).rgb;\n vec3 exposedB=texture2D(uCurrent,clamp(backgroundB,vec2(0.),vec2(1.))).rgb;\n float backgroundWeight=visibleB*(1.-visibleA)+visibleA*visibleB*uPhase;\n finalColor=mix(finalColor,mix(exposedA,exposedB,backgroundWeight),uncovered*max(visibleA,visibleB));\n";
    static final String MATCH_0 = "varying vec2 vTexCoord;";
    static final String REPLACEMENT_0 = "varying vec2 vTexCoord;\nuniform sampler2D uEndpointForward,uEndpointBackward;uniform vec2 uEndpointCameraForward,uEndpointCameraBackward;uniform float uEndpointPacked;";
    static final String MATCH_1 = "void main(){";
    static final String REPLACEMENT_1 = "\nvec2 decodeEndpoint(vec4 field){return mix(decodeFlow(field),seedDec(field)/uDenseSeedSourceSize,uEndpointPacked);}\nfloat cleanLayer(sampler2D motion,vec2 uv,vec2 expectedMotion){\n vec2 pixel=uv*uDenseSeedSourceSize-vec2(.5);\n vec2 base=floor(pixel),fraction=fract(pixel);\n float clean=1.;\n for(int y=0;y<2;y++)for(int x=0;x<2;x++){\n  vec2 offset=vec2(float(x),float(y));\n  vec2 weight=mix(vec2(1.)-fraction,fraction,offset);\n  vec2 tap=(base+offset+vec2(.5))/uDenseSeedSourceSize;\n  vec2 actual=decodeEndpoint(texture2D(motion,clamp(tap,vec2(0.),vec2(1.))));\n  float mismatch=step(.75,length((actual-expectedMotion)*uDenseSeedSourceSize));\n  clean*=1.-step(.00001,weight.x*weight.y)*mismatch;\n }\n return clean;\n}\nvoid main(){";
    static final String MATCH_2 = " vec3 rawPrevious=texture2D(uPrevious,vTexCoord).rgb;\n";
    static final String REPLACEMENT_2 = "\n float cleanA=cleanLayer(uEndpointForward,previousUv,forward);\n float cleanB=cleanLayer(uEndpointBackward,currentUv,backward);\n vec4 unfilteredA=a,unfilteredB=b;\n a=mix(unfilteredA,unfilteredB,(1.-cleanA)*cleanB*previousGate*currentGate);\n b=mix(unfilteredB,unfilteredA,(1.-cleanB)*cleanA*previousGate*currentGate);\n vec3 rawPrevious=texture2D(uPrevious,vTexCoord).rgb;\n";
    static final String MATCH_3 = " if(uDenseEncoding<0.5){\n";
    static final String REPLACEMENT_3 = " previousReliability=forwardField.b;currentReliability=backwardField.b;\n if(uDenseEncoding<0.5){\n";
    static final String MATCH_4 = " float previousGate=step(0.02,previousReliability);\n";
    static final String REPLACEMENT_4 = " previousReliability=forwardField.b;currentReliability=backwardField.b;\n forward=decodeFlow(forwardField);backward=decodeFlow(backwardField);\n float previousGate=step(0.02,previousReliability);\n";
    static final String MATCH_5 = " float popIn=smoothstep(0.30,0.45,endpointDelta);\n";
    static final String REPLACEMENT_5 = "\n vec2 endpointF=decodeEndpoint(texture2D(uEndpointForward,vTexCoord));\n vec2 endpointB=decodeEndpoint(texture2D(uEndpointBackward,vTexCoord));\n float endpointMoving=step(0.75,min(length(endpointF*uDenseSeedSourceSize),length(endpointB*uDenseSeedSourceSize)));\n float transportedDifferent=step(0.75,max(length((endpointF-forward)*uDenseSeedSourceSize),length((endpointB-backward)*uDenseSeedSourceSize)));\n float layeredCrossing=endpointMoving*transportedDifferent*step(48.0/255.0,min(previousReliability,currentReliability))*(1.0-step(6.0/255.0,alignmentError));\n staticHud*=1.0-layeredCrossing;\n float popIn=smoothstep(0.30,0.45,endpointDelta);\n";
    static final String MATCH_6 = " float cutFraction=texture2D(uDenseCutTex,vec2(0.5)).r;\n";
    static final String REPLACEMENT_6 = "\n vec2 backgroundCameraForward=uEndpointCameraForward;\n vec2 backgroundCameraBackward=uEndpointCameraBackward;\n if(uDenseSeedEnabled>.5){backgroundCameraForward=seedDec(texture2D(uDenseSeedForwardTex,vec2(.5)))/uDenseSeedSourceSize;backgroundCameraBackward=seedDec(texture2D(uDenseSeedBackwardTex,vec2(.5)))/uDenseSeedSourceSize;}\n\n float uncovered=(1.0-anySupported)*step(0.0001,uPhase)*(1.0-step(0.9999,uPhase));\n vec2 backgroundA=vTexCoord-backgroundCameraForward*uPhase;\n vec2 backgroundB=vTexCoord-backgroundCameraBackward*(1.-uPhase);\n float visibleA=cleanLayer(uEndpointForward,backgroundA,backgroundCameraForward);\n float visibleB=cleanLayer(uEndpointBackward,backgroundB,backgroundCameraBackward);\n visibleA*=step(0.,min(backgroundA.x,backgroundA.y))*(1.-step(1.,max(backgroundA.x,backgroundA.y)));\n visibleB*=step(0.,min(backgroundB.x,backgroundB.y))*(1.-step(1.,max(backgroundB.x,backgroundB.y)));\n vec3 exposedA=texture2D(uPrevious,clamp(backgroundA,vec2(0.),vec2(1.))).rgb;\n vec3 exposedB=texture2D(uCurrent,clamp(backgroundB,vec2(0.),vec2(1.))).rgb;\n float backgroundWeight=visibleB*(1.-visibleA)+visibleA*visibleB*uPhase;\n finalColor=mix(finalColor,mix(exposedA,exposedB,backgroundWeight),uncovered*max(visibleA,visibleB));\n float cutFraction=texture2D(uDenseCutTex,vec2(0.5)).r;\n";

    static String build(String base) {
        base = replaceOnce(base, MATCH_0, REPLACEMENT_0);
        // At an endpoint there is no interpolation to perform. Layer cleanup
        // and disocclusion repair must never alter the real source image.
        base = replaceOnce(base, MATCH_1, REPLACEMENT_1 +
                "\n if(uPhase<=0.0){gl_FragColor=texture2D(uPrevious,vTexCoord);return;}\n" +
                " if(uPhase>=1.0){gl_FragColor=texture2D(uCurrent,vTexCoord);return;}\n");
        base = replaceOnce(base, MATCH_2, REPLACEMENT_2);
        base = replaceOnce(base, MATCH_3, REPLACEMENT_3);
        base = replaceOnce(base, MATCH_4, REPLACEMENT_4);
        base = replaceOnce(base, MATCH_5, REPLACEMENT_5);
        base = replaceOnce(base, MATCH_6, REPLACEMENT_6);
        return base;
    }

    private static String replaceOnce(String source, String match, String replacement) {
        int at = source.indexOf(match);
        if (at < 0 || source.indexOf(match, at + match.length()) >= 0) {
            throw new IllegalArgumentException("Synthesis shader contract changed");
        }
        return source.substring(0, at) + replacement + source.substring(at + match.length());
    }
}
