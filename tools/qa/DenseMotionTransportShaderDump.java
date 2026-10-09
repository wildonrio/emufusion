package com.thorium.preview.game;

public final class DenseMotionTransportShaderDump {
    public static void main(String[] args) {
        if("compute".equals(args[0])) { System.out.print(DenseMotionTransportShaders.COMPACT);return; }
        if("compact-vertex".equals(args[0])) { System.out.print(DenseMotionTransportShaders.compactVertex());return; }
        System.out.print("vertex".equals(args[0])
                ? DenseMotionTransportShaders.instancedVertex()
                : DenseMotionTransportShaders.instancedFragment());
    }
}
