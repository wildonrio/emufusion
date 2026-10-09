package com.thorium.lucent.video;

public final class FrameGenerationBackendPolicyTest {
    public static void main(String[] args) {
        offAlwaysMeansDirect();
        lsfgWinsOnlyAfterEveryGatePasses();
        builtInIsTheAutomaticFallback();
        directIsTheLastResort();
        System.out.println("FrameGenerationBackendPolicyTest passed");
    }

    private static void offAlwaysMeansDirect() {
        assertBackend(FrameGenerationBackendPolicy.Backend.DIRECT,
                FrameGenerationBackendPolicy.select(false,
                        FrameGenerationBackendPolicy.Assessment.ready(),
                        FrameGenerationBackendPolicy.Assessment.ready()));
    }

    private static void lsfgWinsOnlyAfterEveryGatePasses() {
        assertBackend(FrameGenerationBackendPolicy.Backend.LSFG,
                FrameGenerationBackendPolicy.select(true,
                        FrameGenerationBackendPolicy.Assessment.ready(),
                        FrameGenerationBackendPolicy.Assessment.ready()));
        boolean[] gates = {true, true, true, true, true};
        for (int failed = 0; failed < gates.length; ++failed) {
            boolean[] value = gates.clone();
            value[failed] = false;
            FrameGenerationBackendPolicy.Assessment incomplete =
                    new FrameGenerationBackendPolicy.Assessment(
                            value[0], value[1], value[2], value[3], value[4],
                            "failed gate " + failed);
            assertBackend(FrameGenerationBackendPolicy.Backend.BUILT_IN,
                    FrameGenerationBackendPolicy.select(true, incomplete,
                            FrameGenerationBackendPolicy.Assessment.ready()));
        }
    }

    private static void builtInIsTheAutomaticFallback() {
        assertBackend(FrameGenerationBackendPolicy.Backend.BUILT_IN,
                FrameGenerationBackendPolicy.select(true,
                        FrameGenerationBackendPolicy.Assessment.unavailable(
                                "no lawful in-process LSFG runtime"),
                        FrameGenerationBackendPolicy.Assessment.ready()));
    }

    private static void directIsTheLastResort() {
        assertBackend(FrameGenerationBackendPolicy.Backend.DIRECT,
                FrameGenerationBackendPolicy.select(true,
                        FrameGenerationBackendPolicy.Assessment.unavailable("LSFG"),
                        FrameGenerationBackendPolicy.Assessment.unavailable("built-in")));
    }

    private static void assertBackend(FrameGenerationBackendPolicy.Backend expected,
                                      FrameGenerationBackendPolicy.Selection actual) {
        if (actual == null || actual.backend != expected)
            throw new AssertionError("expected " + expected + " but got " +
                    (actual == null ? "null" : actual.backend));
    }
}
