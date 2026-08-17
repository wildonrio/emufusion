package com.thorium.lucent.emulators;

final class NativeAdapterStopPolicyTest {
    public static void main(String[] args) {
        if (!NativeAdapterStopPolicy.reportsQuickResume("cemu", true))
            throw new AssertionError("cemu must keep adapter Quick Resume");
        if (NativeAdapterStopPolicy.reportsQuickResume("eden", false))
            throw new AssertionError("eden must stay false");
        if (NativeAdapterStopPolicy.reportsQuickResume("aps3e", true))
            throw new AssertionError("aps3e must not advertise Quick Resume");
        if (!NativeAdapterStopPolicy.destroyNativeHostOnStop("cemu"))
            throw new AssertionError("cemu must still destroy its host");
        if (NativeAdapterStopPolicy.destroyNativeHostOnStop("aps3e"))
            throw new AssertionError("aps3e must not Kill/join on Stop");
        System.out.println("NativeAdapterStopPolicyTest passed");
    }
}
