package com.thorium.emufusion.navigation;

import static com.thorium.emufusion.navigation.RightStickViewRouter.Direction;

public final class RightStickViewRouterTest {
    private static void expect(Direction expected, Direction actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected " + expected + ", got " + actual);
    }

    public static void main(String[] args) {
        RightStickViewRouter router = new RightStickViewRouter();
        expect(Direction.NONE, router.update(0.30f, 0.0f), "dead zone");
        expect(Direction.UP, router.update(0.1f, -0.9f), "up");
        expect(Direction.UP, router.update(0.1f, -0.40f), "release hysteresis");
        expect(Direction.NONE, router.update(0.1f, -0.20f), "released");
        expect(Direction.LEFT, router.update(-0.91f, 0.80f), "dominant horizontal");
        expect(Direction.RIGHT, router.update(0.95f, 0.0f), "direct reversal");
        expect(Direction.NONE, router.update(0.0f, 0.0f), "return neutral");
        expect(Direction.DOWN, router.update(0.0f, 1.0f), "down");
        System.out.println("RightStickViewRouterTest passed");
    }
}
