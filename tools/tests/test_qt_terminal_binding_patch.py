"""Run the Qt smali transformation against pinned/minimal lifecycle fixtures."""

import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "unified-android/tools/patch_qt_terminal_retirement.py"
SPEC = importlib.util.spec_from_file_location("qt_terminal_binding_patch", PATCHER)
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)
QT = "Lorg/qtproject/qt5/android/QtActivityDelegate;"
HOST = "Lcom/thorium/preview/game/InWindowGameHost;"
THREAD = f""".method static synthetic access$100({PATCH.QT_THREAD})Ljava/lang/Thread;
    .locals 0
    iget-object p0, p0, {PATCH.QT_THREAD}->m_qtThread:Ljava/lang/Thread;
    return-object p0
.end method
"""

# Exact terminal instructions from the packaged Qt 5 delegate, including its
# original register format and configuration-handoff branch.
DELEGATE = f""".class public {QT}
.super Ljava/lang/Object;
.field private m_quitApp:Z
.field private m_activity:Landroid/app/Activity;
.method public onDestroy()V
    .locals 1

    .line 956
    iget-boolean v0, p0, {QT}->m_quitApp:Z
    if-eqz v0, :cond_0
    .line 957
    invoke-static {{}}, Lorg/qtproject/qt5/android/QtNative;->terminateQt()V
    const/4 v0, 0x0
    .line 958
    invoke-static {{v0, v0}}, Lorg/qtproject/qt5/android/QtNative;->setActivity(Landroid/app/Activity;{QT})V
    .line 959
    sget-object v0, Lorg/qtproject/qt5/android/QtNative;->m_qtThread:Lorg/qtproject/qt5/android/QtThread;
    invoke-virtual {{v0}}, Lorg/qtproject/qt5/android/QtThread;->exit()V
    const/4 v0, 0x0
    .line 960
    invoke-static {{v0}}, Ljava/lang/System;->exit(I)V
    :cond_0
    return-void
.end method
.method public untouched()V
    .locals 0
    return-void
.end method
"""

REQUIRED = {
    "onStart()V": (0, "V"),
    "onResume()V": (0, "V"),
    "onPause()V": (0, "V"),
    "onStop()V": (0, "V"),
    "onDestroy()V": (0, "V"),
    "onSaveInstanceState(Landroid/os/Bundle;)V": (1, "V"),
    "onRestoreInstanceState(Landroid/os/Bundle;)V": (1, "V"),
    "onWindowFocusChanged(Z)V": (1, "V"),
    "dispatchKeyEvent(Landroid/view/KeyEvent;)Z": (1, "Z"),
    "onRequestPermissionsResult(I[Ljava/lang/String;[I)V": (3, "V"),
}
VARIANTS = {
    "onCreateDialog(ILandroid/os/Bundle;)Landroid/app/Dialog;": (2, "L"),
    "onArray([J)[Landroid/view/View;": (1, "["),
    "onWide(JD[J[[D)J": (6, "J"),
    "onDouble(D)D": (2, "D"),
    "onPrimitive(IF)I": (2, "I"),
}

# This real framework override is different from the others: the pinned Qt
# wrapper has no Android-super fallback, but still invokes the global delegate.
PERMISSIONS = """.method public onRequestPermissionsResult(I[Ljava/lang/String;[I)V
    .locals 3
    sget-object v0, Lorg/qtproject/qt5/android/bindings/QtApplication;->m_delegateObject:Ljava/lang/Object;
    if-eqz v0, :cond_0
    sget-object v0, Lorg/qtproject/qt5/android/bindings/QtApplication;->onRequestPermissionsResult:Ljava/lang/reflect/Method;
    if-eqz v0, :cond_0
    sget-object v0, Lorg/qtproject/qt5/android/bindings/QtApplication;->onRequestPermissionsResult:Ljava/lang/reflect/Method;
    const/4 v1, 0x3
    new-array v1, v1, [Ljava/lang/Object;
    const/4 v2, 0x0
    invoke-static {p1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object p1
    aput-object p1, v1, v2
    const/4 p1, 0x1
    aput-object p2, v1, p1
    const/4 p1, 0x2
    aput-object p3, v1, p1
    invoke-static {v0, v1}, Lorg/qtproject/qt5/android/bindings/QtApplication;->invokeDelegateMethod(Ljava/lang/reflect/Method;[Ljava/lang/Object;)Ljava/lang/Object;
    :cond_0
    return-void
.end method
"""


def return_ops(kind):
    if kind == "V":
        return "return-void"
    if kind in ("L", "["):
        return "move-result-object v0\n    return-object v0"
    if kind in ("J", "D"):
        return "move-result-wide v0\n    return-wide v0"
    return "move-result v0\n    return v0"


def framework_method(signature, words, kind):
    return f""".method public {signature}
    .locals 2
    .line 123
    const/4 v0, 0x0
    invoke-static {{v0}}, Lorg/qtproject/qt5/android/bindings/QtApplication;->invokeDelegate([Ljava/lang/Object;)Lorg/qtproject/qt5/android/bindings/QtApplication$InvokeResult;
    move-result-object v0
    :fixture_normal_body
    invoke-super/range {{p0 .. p{words}}}, Landroid/app/Activity;->{signature}
    {return_ops(kind)}
.end method
"""


def binding_fixture():
    methods = {**REQUIRED, **VARIANTS}
    return (".class public Lorg/qtproject/qt5/android/bindings/QtActivity;\n"
            ".super Landroid/app/Activity;\n" +
            "".join(PERMISSIONS if signature.startswith("onRequestPermissionsResult(")
                    else framework_method(signature, *shape)
                    for signature, shape in methods.items()) +
            ".method public super_onResume()V\n    .locals 0\n"
            "    invoke-super {p0}, Landroid/app/Activity;->onResume()V\n"
            "    return-void\n.end method\n")


def method(source, signature):
    matches = [m for m in PATCH.METHOD.finditer(source)
               if m.group(1).split()[-1] == signature]
    if len(matches) != 1:
        raise AssertionError("Expected unique method " + signature)
    return matches[0].group(2)


def instructions(body):
    return [line.strip() for line in body.splitlines()
            if line.strip() and not line.strip().startswith((".line", "#"))]


class QtTerminalBindingPatchTest(unittest.TestCase):
    def test_original_cleanup_and_join_sequence_is_preserved_with_managed_exit_hook(self):
        original = instructions(method(DELEGATE, "onDestroy()V"))
        result = PATCH.patch_delegate(DELEGATE)
        helper = instructions(method(result,
            "lucentCompleteTerminalShutdown(Landroid/app/Activity;)V"))
        first = "invoke-static {}, Lorg/qtproject/qt5/android/QtNative;->terminateQt()V"
        hook = f"invoke-static {{p1, v1}}, {HOST}->finishQtTerminalProcess(Landroid/app/Activity;Ljava/lang/Thread;)Z"
        pos = helper.index(hook)
        self.assertEqual([hook, "move-result v1", "if-nez v1, :cond_0"], helper[pos:pos + 3])
        without_hook = helper[:pos] + helper[pos + 3:]
        capture = f"invoke-static {{v0}}, {PATCH.QT_THREAD}->access$100({PATCH.QT_THREAD})Ljava/lang/Thread;"
        captured = without_hook.index(capture)
        self.assertEqual("move-result-object v1", without_hook[captured + 1])
        without_hook = without_hook[:captured] + without_hook[captured + 2:]
        self.assertEqual(original[original.index(first):], without_hook[without_hook.index(first):])
        self.assertLess(helper.index("invoke-virtual {v0}, Lorg/qtproject/qt5/android/QtThread;->exit()V"), pos)
        self.assertLess(pos, helper.index("invoke-static {v0}, Ljava/lang/System;->exit(I)V"))
        self.assertNotIn("killProcess", method(result, "onDestroy()V"))
        self.assertEqual(method(DELEGATE, "untouched()V"), method(result, "untouched()V"))
        self.assertEqual(1, result.count(".field private lucent_terminal_started:Z"))

    def test_owner_and_one_shot_guards_precede_all_terminal_work(self):
        helper = method(PATCH.patch_delegate(DELEGATE),
                        "lucentCompleteTerminalShutdown(Landroid/app/Activity;)V")
        ordered = ["if-ne v1, p1, :cond_0", "if-nez v1, :cond_0",
                   "if-eqz v0, :cond_0", "->lucent_terminal_started:Z",
                   "->terminateQt()V"]
        # The field has a read and a write; specifically require the latch write
        # after all guards and before terminateQt, not merely its declaration.
        ordered[3] = f"iput-boolean v1, p0, {QT}->lucent_terminal_started:Z"
        positions = [helper.index(item) for item in ordered]
        self.assertEqual(sorted(positions), positions)
        self.assertIn(".locals 2", helper)

    def test_config_handoff_bypasses_callback_and_accepted_terminal_does_not_run_inline(self):
        wrapper = method(PATCH.patch_delegate(DELEGATE), "onDestroy()V")
        self.assertLess(wrapper.index("if-eqz v0, :lucent_destroy_return"),
                        wrapper.index("new-instance v2"))
        self.assertIn(f"invoke-direct {{v2, p0, v1}}, {PATCH.CALLBACK}-><init>", wrapper)
        self.assertIn(f"{HOST}->requestQtTerminalShutdown(Landroid/app/Activity;Ljava/lang/Runnable;)Z", wrapper)
        self.assertLess(wrapper.index("if-nez v0, :lucent_destroy_return"),
                        wrapper.index("->lucentCompleteTerminalShutdown"))
        self.assertNotIn("->terminateQt", wrapper)
        self.assertEqual(["return-void"], instructions(wrapper.rsplit("    :lucent_destroy_return\n", 1)[1]))

    def test_callback_captures_concrete_delegate_and_owner_without_global_lookup(self):
        source = PATCH.callback_source()
        self.assertIn(f".field private final delegate:{QT}", source)
        self.assertIn(".field private final owner:Landroid/app/Activity;", source)
        self.assertIn(f"iput-object p1, p0, {PATCH.CALLBACK}->delegate:{QT}", source)
        self.assertIn(f"iput-object p2, p0, {PATCH.CALLBACK}->owner:Landroid/app/Activity;", source)
        run = method(source, "run()V")
        self.assertIn(f"invoke-virtual {{v0, v1}}, {QT}->lucentCompleteTerminalShutdown(Landroid/app/Activity;)V", run)
        self.assertNotIn("invokeDelegate", source)
        self.assertNotIn("sget-object", source)

    def test_replacement_uses_direct_android_super_with_exact_argument_and_return_shapes(self):
        original = binding_fixture()
        result, guarded = PATCH.patch_binding(original)
        self.assertEqual(set(REQUIRED) | set(VARIANTS), set(guarded))
        for signature, (words, kind) in {**REQUIRED, **VARIANTS}.items():
            with self.subTest(signature=signature):
                body = method(result, signature)
                fast, normal = body.split("    :lucent_qt_delegate_allowed\n", 1)
                self.assertIn(f"{HOST}->shouldSkipQtDelegate(Landroid/app/Activity;)Z", fast)
                self.assertIn("if-eqz v0, :lucent_qt_delegate_allowed", fast)
                self.assertIn(f"invoke-super/range {{p0 .. p{words}}}, Landroid/app/Activity;->{signature}", fast)
                self.assertIn(return_ops(kind), fast)
                self.assertNotIn("invokeDelegate", fast)
                original_body = re.sub(r"^    \.locals \d+\n", "",
                                       method(original, signature), count=1)
                self.assertEqual(original_body, normal)
        self.assertEqual(method(original, "super_onResume()V"), method(result, "super_onResume()V"))

    def test_wide_arguments_and_array_elements_have_correct_word_counts(self):
        for descriptor, expected in [("", 0), ("J", 2), ("D", 2), ("[J", 1),
                                     ("[[D", 1), ("JD[J[[D", 6),
                                     ("ILandroid/os/Bundle;", 2)]:
            self.assertEqual(expected, PATCH.argument_words(descriptor), descriptor)

    def test_changed_terminal_or_repeated_inputs_are_rejected(self):
        for label, changed in [
                ("terminal", DELEGATE.replace("terminateQt()V", "differentTerminal()V")),
                ("locals-anchor", DELEGATE.replace("    .locals 1", "  .locals 1")),
                ("latch-anchor", DELEGATE.replace("    if-eqz v0", "  if-eqz v0"))]:
            with self.subTest(change=label):
                with self.assertRaises(ValueError):
                    PATCH.patch_delegate(changed)
        with self.assertRaises(ValueError):
            PATCH.patch_delegate(PATCH.patch_delegate(DELEGATE))
        binding, _ = PATCH.patch_binding(binding_fixture())
        with self.assertRaises(ValueError):
            PATCH.patch_binding(binding)

    def test_missing_binding_override_or_changed_register_format_is_rejected(self):
        for changed in [binding_fixture().replace("onStop()V", "notOnStop()V"),
                        binding_fixture().replace("    .locals 2", "    .registers 5", 1)]:
            with self.assertRaises(ValueError):
                PATCH.patch_binding(changed)

    def test_cli_validates_both_inputs_before_any_generated_write(self):
        with tempfile.TemporaryDirectory(prefix="lucent-qt-patch-") as temp:
            qt = Path(temp) / "org/qtproject/qt5/android"
            (qt / "bindings").mkdir(parents=True)
            delegate = qt / "QtActivityDelegate.smali"
            binding = qt / "bindings/QtActivity.smali"
            invalid = binding_fixture().replace("onStop()V", "notOnStop()V")
            delegate.write_text(DELEGATE)
            (qt / "QtThread.smali").write_text(THREAD)
            binding.write_text(invalid)
            result = subprocess.run([sys.executable, str(PATCHER), temp],
                                    capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(DELEGATE, delegate.read_text())
            self.assertEqual(invalid, binding.read_text())
            self.assertFalse((qt / "LucentTerminalShutdown.smali").exists())

    def test_actual_backing_thread_accessor_is_pinned(self):
        PATCH.validate_qt_thread(THREAD)
        for source in (THREAD.replace("access$100", "access$101"),
                       THREAD.replace("m_qtThread", "differentThread"), ""):
            with self.assertRaises(ValueError):
                PATCH.validate_qt_thread(source)


if __name__ == "__main__":
    unittest.main()
