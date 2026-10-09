package com.thorium.lucent.video;

/**
 * CPU-side diagnosis of the dense flow already copied by the asynchronous
 * qualification atlas. This never participates in rendering or acceptance;
 * it distinguishes broad confidence on stationary vectors from validated
 * motion that actually owns changed endpoint pixels.
 */
public final class DenseFlowTrajectoryDiagnostics {
    private static final int VALID_CONFIDENCE_BYTE = 48;
    private static final int ACTIVE_FLOW_BYTE_DELTA = 2;
    private static final int STRONG_FLOW_BYTE_DELTA = 8;
    private static final int CHANGED_ENDPOINT_RGB_SUM = 36;
    private static final int TILE_COLUMNS = 6;
    private static final int TILE_ROWS = 3;

    public static final class Sample {
        public final long cells;
        public final long changedCells;
        public final long changedAnyValidCells;
        public final long changedAnyMovingValidCells;
        public final long changedBothMovingValidCells;
        public final long changedTiles;
        public final long changedMovingOwnedTiles;
        public final long[] validCells = new long[2];
        public final long[] movingValidCells = new long[2];
        public final long[] strongMovingValidCells = new long[2];
        public final long[] changedValidCells = new long[2];
        public final long[] changedMovingValidCells = new long[2];
        public final long[] unchangedMovingValidCells = new long[2];

        private Sample(long cells, long changedCells,
                       long changedAnyValidCells,
                       long changedAnyMovingValidCells,
                       long changedBothMovingValidCells,
                       long changedTiles, long changedMovingOwnedTiles,
                       long[][] direction) {
            this.cells = cells;
            this.changedCells = changedCells;
            this.changedAnyValidCells = changedAnyValidCells;
            this.changedAnyMovingValidCells = changedAnyMovingValidCells;
            this.changedBothMovingValidCells = changedBothMovingValidCells;
            this.changedTiles = changedTiles;
            this.changedMovingOwnedTiles = changedMovingOwnedTiles;
            for (int index = 0; index < 2; ++index) {
                validCells[index] = direction[index][0];
                movingValidCells[index] = direction[index][1];
                strongMovingValidCells[index] = direction[index][2];
                changedValidCells[index] = direction[index][3];
                changedMovingValidCells[index] = direction[index][4];
                unchangedMovingValidCells[index] = direction[index][5];
            }
        }
    }

    private DenseFlowTrajectoryDiagnostics() {}

    public static Sample analyze(byte[] previous, byte[] current,
                                 byte[] backward, byte[] forward,
                                 int width, int height) {
        int pixels = checkedPixels(previous, current, backward, forward,
                width, height);
        long changed = 0;
        long changedAnyValid = 0;
        long changedAnyMoving = 0;
        long changedBothMoving = 0;
        long[][] direction = new long[2][6];
        boolean[] changedTile = new boolean[TILE_COLUMNS * TILE_ROWS];
        boolean[] ownedTile = new boolean[changedTile.length];
        byte[][] fields = {backward, forward};
        for (int pixel = 0; pixel < pixels; ++pixel) {
            int offset = pixel * 4;
            int endpointSpan = 0;
            for (int channel = 0; channel < 3; ++channel)
                endpointSpan += Math.abs((previous[offset + channel] & 0xff) -
                        (current[offset + channel] & 0xff));
            boolean isChanged = endpointSpan >= CHANGED_ENDPOINT_RGB_SUM;
            boolean anyValid = false;
            boolean anyMoving = false;
            boolean bothMoving = true;
            for (int index = 0; index < fields.length; ++index) {
                byte[] field = fields[index];
                boolean valid = (field[offset + 2] & 0xff) >=
                        VALID_CONFIDENCE_BYTE;
                int flowDelta = Math.max(
                        Math.abs((field[offset] & 0xff) - 128),
                        Math.abs((field[offset + 1] & 0xff) - 128));
                boolean moving = valid && flowDelta > ACTIVE_FLOW_BYTE_DELTA;
                if (valid) ++direction[index][0];
                if (moving) ++direction[index][1];
                if (valid && flowDelta > STRONG_FLOW_BYTE_DELTA)
                    ++direction[index][2];
                if (isChanged && valid) ++direction[index][3];
                if (isChanged && moving) ++direction[index][4];
                if (!isChanged && moving) ++direction[index][5];
                anyValid |= valid;
                anyMoving |= moving;
                bothMoving &= moving;
            }
            if (!isChanged) continue;
            ++changed;
            if (anyValid) ++changedAnyValid;
            if (anyMoving) ++changedAnyMoving;
            if (bothMoving) ++changedBothMoving;
            int x = pixel % width;
            int y = pixel / width;
            int tileX = Math.min(TILE_COLUMNS - 1,
                    x * TILE_COLUMNS / width);
            int tileY = Math.min(TILE_ROWS - 1,
                    y * TILE_ROWS / height);
            int tile = tileY * TILE_COLUMNS + tileX;
            changedTile[tile] = true;
            if (anyMoving) ownedTile[tile] = true;
        }
        return new Sample(pixels, changed, changedAnyValid,
                changedAnyMoving, changedBothMoving, countTrue(changedTile),
                countTrue(ownedTile), direction);
    }

    private static int checkedPixels(byte[] previous, byte[] current,
                                     byte[] backward, byte[] forward,
                                     int width, int height) {
        if (width <= 0 || height <= 0 || width > Integer.MAX_VALUE / height)
            throw new IllegalArgumentException("invalid diagnostic geometry");
        int pixels = width * height;
        if (pixels > Integer.MAX_VALUE / 4)
            throw new IllegalArgumentException("diagnostic geometry overflow");
        int bytes = pixels * 4;
        if (previous == null || current == null || backward == null ||
                forward == null || previous.length != bytes ||
                current.length != bytes || backward.length != bytes ||
                forward.length != bytes)
            throw new IllegalArgumentException("diagnostic payload mismatch");
        return pixels;
    }

    private static long countTrue(boolean[] values) {
        long result = 0;
        for (boolean value : values) if (value) ++result;
        return result;
    }
}
