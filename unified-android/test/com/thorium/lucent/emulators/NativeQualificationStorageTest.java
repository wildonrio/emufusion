package com.thorium.lucent.emulators;

public final class NativeQualificationStorageTest {
    private static void check(boolean ok) {
        if (!ok) throw new AssertionError();
    }

    private static void rejects(NativeQualificationStorage.EdenProcessRoot root, String value) {
        boolean rejected = false;
        try { root.claim(value); }
        catch (IllegalArgumentException | IllegalStateException expected) { rejected = true; }
        check(rejected);
    }

    public static void main(String[] args) {
        String a = "qa-0123456789abcdef0123456789abcdef";
        String b = "qa-fedcba9876543210fedcba9876543210";
        check(NativeQualificationStorage.supports("eden", "switch"));
        check(NativeQualificationStorage.supports("aps3e", "ps3"));
        check(!NativeQualificationStorage.supports("eden", "ps3"));
        check(!NativeQualificationStorage.supports("cemu", "wiiu"));
        check(!NativeQualificationStorage.supports(null, null));
        NativeQualificationStorage.EdenProcessRoot normal = new NativeQualificationStorage.EdenProcessRoot();
        normal.claim(null);
        normal.claim("");
        rejects(normal, a);
        normal.claim("");
        NativeQualificationStorage.EdenProcessRoot qa = new NativeQualificationStorage.EdenProcessRoot();
        qa.claim(a);
        qa.claim(a);
        rejects(qa, "");
        rejects(qa, b);
        qa.claim(a);
        NativeQualificationStorage.EdenProcessRoot fresh = new NativeQualificationStorage.EdenProcessRoot();
        rejects(fresh, "../engine-system");
        rejects(fresh, a + "/..");
        fresh.claim(b);
        fresh.claim(b);
        System.out.println("NativeQualificationStorageTest passed");
    }
}
