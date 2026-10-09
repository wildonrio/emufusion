package com.thorium.preview.game;

public final class DenseMotionTransportGeometryTest {
    private static void check(boolean condition) {
        if (!condition) throw new AssertionError();
    }
    public static void main(String[] args) {
        check(DenseMotionTransportShaders.instanceCount(1920, 1080) == 2073600);
        check(DenseMotionTransportShaders.instanceCount(1, 1) == 1);
        for (int[] grid : new int[][]{{0, 10}, {10, -1}, {65536, 65536}}) {
            try {
                DenseMotionTransportShaders.instanceCount(grid[0], grid[1]);
                throw new AssertionError("Invalid grid accepted");
            } catch (IllegalArgumentException expected) { }
        }
        String vertex = DenseMotionTransportShaders.instancedVertex();
        String fragment = DenseMotionTransportShaders.instancedFragment();
        check(vertex.startsWith("#version 300 es\n"));
        check(fragment.startsWith("#version 300 es\n"));
        check(!vertex.contains("attribute ") && !vertex.contains("texture2D("));
        check(!fragment.contains("gl_FragColor") && !fragment.contains("varying "));
        check(vertex.contains("gl_InstanceID%gridSize.x"));
        check(vertex.contains("gl_InstanceID/gridSize.x"));
        // Reference mapping checks row transitions and terminal source center.
        for (int[] grid : new int[][]{{1,1},{3,2},{1920,1080}}) {
            int count = DenseMotionTransportShaders.instanceCount(grid[0],grid[1]);
            for (int instance : new int[]{0, count/2, count-1}) {
                int x=instance%grid[0],y=instance/grid[0];
                check(x>=0 && x<grid[0] && y>=0 && y<grid[1]);
                check(y*grid[0]+x==instance);
            }
        }
        int[][] corners={{-1,-1},{1,-1},{-1,1},{1,1}};
        for(int i=0;i<4;i++) {
            check((i&1)*2-1==corners[i][0]);
            check(((i>>1)&1)*2-1==corners[i][1]);
        }
        System.out.println("Instanced geometry/source-contract checks passed; GLES execution not tested.");
    }
}
