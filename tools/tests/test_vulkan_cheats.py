"""Run the production Vulkan Java wrapper against a recording JNI boundary.

This checks Java dispatch/lifecycle, not real core behavior; the landscape AVD
run exercises the packaged Android JNI/core implementation separately.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA_HOME = Path(os.environ.get(
    "JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"))

HARNESS = r'''
package com.thorium.preview;
import java.io.File;
import java.util.*;
public class VulkanCheatsHarness {
    static final List<String> calls = new ArrayList<>();
    static boolean failReset;
    public static void record(String event) { calls.add(event); }
    static void expect(String... events) {
        if (!calls.equals(Arrays.asList(events))) throw new AssertionError(calls);
        calls.clear();
    }
    public static void main(String[] args) throws Exception {
        File root = new File(args[0]);
        File core = new File(root, "core.so");
        if (!core.createNewFile()) throw new AssertionError("fixture exists");
        ExperimentalVulkanLibretroHost host = new ExperimentalVulkanLibretroHost(
                core, root, new File(root, "system"), new File(root, "save"));
        host.applyCheats(Collections.emptyList());
        expect("reset");
        host.applyCheats(Arrays.asList(" AAAA-BBBB ", null, " ", "1111:22"));
        expect("reset", "0:AAAA-BBBB", "1:1111:22");
        host.applyCheats(null);
        expect("reset");
        failReset = true;
        try { host.applyCheats(Arrays.asList("AAAA")); throw new AssertionError(); }
        catch (IllegalStateException expected) {}
        expect();
        failReset = false;
        host.reset();
        expect("game-reset");
        failReset = true;
        try { host.reset(); throw new AssertionError("reset failure swallowed"); }
        catch (IllegalStateException expected) {}
        expect();
        failReset = false;
        try { host.applyCheats(Arrays.asList("FAIL", "must-not-run"));
              throw new AssertionError(); }
        catch (IllegalStateException expected) {}
        expect("reset");
        host.close();
        expect("close");
        host.close();
        try { host.applyCheats(Collections.emptyList()); throw new AssertionError(); }
        catch (IllegalStateException expected) {}
        try { host.reset(); throw new AssertionError("closed host accepted reset"); }
        catch (IllegalStateException expected) {}
        expect();
        System.out.println("Vulkan cheat dispatch: empty, null, slots, errors, closed PASS");
    }
}
'''

JNI = r'''
#include <jni.h>
#include <stdio.h>
#include <string.h>
#define NAME(x) Java_com_thorium_preview_ExperimentalVulkanLibretroHost_##x
static void fail(JNIEnv *env) {
    (*env)->ThrowNew(env, (*env)->FindClass(env, "java/lang/IllegalStateException"),
                    "injected native failure");
}
static void record(JNIEnv *env, const char *event) {
    jclass c = (*env)->FindClass(env, "com/thorium/preview/VulkanCheatsHarness");
    jmethodID method = (*env)->GetStaticMethodID(env, c, "record", "(Ljava/lang/String;)V");
    jstring text = (*env)->NewStringUTF(env, event);
    (*env)->CallStaticVoidMethod(env, c, method, text);
    (*env)->DeleteLocalRef(env, text);
}
JNIEXPORT jlong JNICALL NAME(nativeCreateVulkan)(JNIEnv *e, jclass c,
        jstring core, jstring root, jstring system, jstring save, jboolean wide) {
    (void)e; (void)c; (void)core; (void)root; (void)system; (void)save; (void)wide;
    return 41;
}
JNIEXPORT void JNICALL NAME(nativeCheatResetVulkan)(JNIEnv *e, jclass c, jlong h) {
    (void)c;
    jclass test = (*e)->FindClass(e, "com/thorium/preview/VulkanCheatsHarness");
    jfieldID field = (*e)->GetStaticFieldID(e, test, "failReset", "Z");
    if (h != 41 || (*e)->GetStaticBooleanField(e, test, field)) { fail(e); return; }
    record(e, "reset");
}
JNIEXPORT void JNICALL NAME(nativeResetVulkan)(JNIEnv *e, jclass c, jlong h) {
    (void)c;
    jclass test = (*e)->FindClass(e, "com/thorium/preview/VulkanCheatsHarness");
    jfieldID field = (*e)->GetStaticFieldID(e, test, "failReset", "Z");
    if (h != 41 || (*e)->GetStaticBooleanField(e, test, field)) { fail(e); return; }
    record(e, "game-reset");
}
JNIEXPORT void JNICALL NAME(nativeCheatSetVulkan)(JNIEnv *e, jclass c, jlong h,
        jint index, jboolean enabled, jstring code) {
    (void)c;
    const char *text = (*e)->GetStringUTFChars(e, code, NULL);
    if (!text) return;
    if (h != 41 || !enabled || strcmp(text, "FAIL") == 0) fail(e);
    else { char event[256]; snprintf(event, sizeof(event), "%d:%s", index, text);
           record(e, event); }
    (*e)->ReleaseStringUTFChars(e, code, text);
}
JNIEXPORT void JNICALL NAME(nativeDestroyVulkan)(JNIEnv *e, jclass c, jlong h) {
    (void)c; if (h != 41) fail(e); else record(e, "close");
}
'''


class VulkanCheatsTest(unittest.TestCase):
    def test_production_wrapper_dispatches_cheats_and_preserves_failures(self):
        env = dict(os.environ, JAVA_TOOL_OPTIONS=
                   "-Djava.awt.headless=true -Dapple.awt.UIElement=true")
        with tempfile.TemporaryDirectory(prefix="vulkan-cheats-") as folder:
            folder = Path(folder)
            harness = folder / "VulkanCheatsHarness.java"
            harness.write_text(HARNESS)
            native = folder / "jni.c"
            native.write_text(JNI)
            platform = "darwin" if sys.platform == "darwin" else "linux"
            lib = folder / ("liblucent_vulkan_host.dylib" if platform == "darwin"
                            else "liblucent_vulkan_host.so")
            subprocess.run(["clang", "-dynamiclib" if platform == "darwin" else "-shared",
                            "-fPIC", "-Wall", "-Wextra", "-Werror",
                            "-I" + str(JAVA_HOME / "include"),
                            "-I" + str(JAVA_HOME / "include" / platform),
                            str(native), "-o", str(lib)], check=True, capture_output=True)
            sources = ["native/tests/java/android/view/Surface.java",
                       "native/tests/java/android/os/Build.java",
                       "native/tests/java/android/util/Log.java",
                       "src/com/thorium/lucent/video/NativeSourceImageProvider.java",
                       "src/com/thorium/lucent/video/RuntimePresentationFailure.java",
                       "src/com/thorium/preview/game/FrameGenerationRenderer.java",
                       "src/com/thorium/preview/game/FrameGenerationRendererRegistry.java",
                       "src/com/thorium/preview/LibretroHost.java",
                       "src/com/thorium/preview/PendingHostInput.java",
                       "src/com/thorium/preview/ExperimentalGlesLibretroHost.java",
                       "src/com/thorium/preview/ExperimentalVulkanLibretroHost.java"]
            subprocess.run([str(JAVA_HOME / "bin/javac"), "--release", "8", "-d", str(folder),
                            *[str(ROOT / "unified-android" / s) for s in sources],
                            str(harness)], env=env, check=True)
            subprocess.run([str(JAVA_HOME / "bin/java"), "-cp", str(folder),
                            "-Djava.library.path=" + str(folder),
                            "com.thorium.preview.VulkanCheatsHarness", str(folder)],
                           env=env, check=True, capture_output=True, timeout=15)

    def test_render_loop_and_android_jni_connect_real_core_api(self):
        loop = (ROOT / "unified-android/src/com/thorium/preview/ExperimentalGlesRenderLoop.java").read_text()
        vulkan = loop.split("createVulkan(", 1)[1]
        self.assertIn("nativeHost.applyCheats(codes);", vulkan)
        self.assertNotIn("Vulkan session exposes no live cheat bridge", vulkan)
        self.assertIn("nativeHost.reset();", vulkan)
        self.assertNotIn("Vulkan session exposes no reset", vulkan)
        jni = (ROOT / "unified-android/native/lucent_libretro_vulkan_jni.c").read_text()
        for symbol in ("nativeCheatResetVulkan", "nativeCheatSetVulkan",
                       "lucent_retro_cheat_reset", "lucent_retro_cheat_set",
                       "nativeResetVulkan", "lucent_retro_reset"):
            self.assertIn(symbol, jni)


if __name__ == "__main__":
    unittest.main()
