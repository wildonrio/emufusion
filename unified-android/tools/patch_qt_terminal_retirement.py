#!/usr/bin/env python3
"""Serialize the pinned Qt terminal path after EmuFusion native retirement.

Only a retiring Main process takes the new path. Configuration handoff and
ordinary Qt activity behavior remain unchanged. A replacement Main that arrives
before terminal cleanup completes uses Android superclass callbacks, never the
old process-global Qt delegate. The callback captures the actual old delegate.
"""

import argparse
from pathlib import Path
import re

QT = "Lorg/qtproject/qt5/android/QtActivityDelegate;"
HOST = "Lcom/thorium/preview/game/InWindowGameHost;"
CALLBACK = "Lorg/qtproject/qt5/android/LucentTerminalShutdown;"
QT_THREAD = "Lorg/qtproject/qt5/android/QtThread;"
MARKER = "lucent_terminal_retirement"
METHOD = re.compile(r"^\.method ([^\n]+)\n(.*?)^\.end method", re.M | re.S)


def patch_delegate(source):
    if MARKER in source or "lucentCompleteTerminalShutdown" in source:
        raise ValueError("Qt terminal retirement already applied")
    matches = [m for m in METHOD.finditer(source) if m.group(1) == "public onDestroy()V"]
    if len(matches) != 1:
        raise ValueError("expected exactly one Qt delegate onDestroy")
    match = matches[0]
    body = match.group(2)
    compact = re.sub(r"^\s*\.line \d+\s*$", "", body, flags=re.M)
    compact = "\n".join(line.strip() for line in compact.splitlines() if line.strip())
    expected = f""".locals 1
iget-boolean v0, p0, {QT}->m_quitApp:Z
if-eqz v0, :cond_0
invoke-static {{}}, Lorg/qtproject/qt5/android/QtNative;->terminateQt()V
const/4 v0, 0x0
invoke-static {{v0, v0}}, Lorg/qtproject/qt5/android/QtNative;->setActivity(Landroid/app/Activity;{QT})V
sget-object v0, Lorg/qtproject/qt5/android/QtNative;->m_qtThread:Lorg/qtproject/qt5/android/QtThread;
invoke-virtual {{v0}}, Lorg/qtproject/qt5/android/QtThread;->exit()V
const/4 v0, 0x0
invoke-static {{v0}}, Ljava/lang/System;->exit(I)V
:cond_0
return-void"""
    if compact != expected:
        raise ValueError("pinned Qt terminal body changed; review before patching")
    # Validation above ignores layout, but the two insertions below use exact
    # anchors. Reject formatting drift instead of silently omitting a guard.
    exit_anchor = "    invoke-static {v0}, Ljava/lang/System;->exit(I)V"
    join_anchor = f"    invoke-virtual {{v0}}, {QT_THREAD}->exit()V"
    if (body.count("    .locals 1\n") != 1 or
            body.count("    if-eqz v0, :cond_0\n") != 1 or
            body.count(exit_anchor) != 1 or body.count(join_anchor) != 1):
        raise ValueError("pinned Qt terminal insertion anchors changed")
    wrapper = f""".method public onDestroy()V
    .locals 3
    # {MARKER}: Android Activity.super.onDestroy has already run.
    iget-boolean v0, p0, {QT}->m_quitApp:Z
    if-eqz v0, :lucent_destroy_return
    iget-object v1, p0, {QT}->m_activity:Landroid/app/Activity;
    new-instance v2, {CALLBACK}
    invoke-direct {{v2, p0, v1}}, {CALLBACK}-><init>({QT}Landroid/app/Activity;)V
    invoke-static {{v1, v2}}, {HOST}->requestQtTerminalShutdown(Landroid/app/Activity;Ljava/lang/Runnable;)Z
    move-result v0
    if-nez v0, :lucent_destroy_return
    invoke-virtual {{p0, v1}}, {QT}->lucentCompleteTerminalShutdown(Landroid/app/Activity;)V
    :lucent_destroy_return
    return-void
.end method
"""
    guard = f"""    .locals 2
    iget-object v1, p0, {QT}->m_activity:Landroid/app/Activity;
    if-ne v1, p1, :cond_0
    iget-boolean v1, p0, {QT}->lucent_terminal_started:Z
    if-nez v1, :cond_0
"""
    helper = body.replace("    .locals 1\n", guard, 1)
    helper = helper.replace("    if-eqz v0, :cond_0", f"""    if-eqz v0, :cond_0
    const/4 v1, 0x1
    iput-boolean v1, p0, {QT}->lucent_terminal_started:Z""", 1)
    # Only the managed Main retirement uses Android's terminal process exit.
    # Its host disables Qt's earlier libc exit before terminateQt, so this is
    # reached after QtThread.exit; the host verifies the captured backing
    # thread really stopped (Qt catches InterruptedException). Unmanaged behavior
    # retains the original System.exit call below.
    helper = helper.replace(join_anchor, join_anchor + f"""
    invoke-static {{v0}}, {QT_THREAD}->access$100({QT_THREAD})Ljava/lang/Thread;
    move-result-object v1""", 1)
    helper = helper.replace(exit_anchor, f"""    invoke-static {{p1, v1}}, {HOST}->finishQtTerminalProcess(Landroid/app/Activity;Ljava/lang/Thread;)Z
    move-result v1
    if-nez v1, :cond_0
{exit_anchor}""", 1)
    helper = ".method public lucentCompleteTerminalShutdown(Landroid/app/Activity;)V\n" + helper + ".end method\n"
    fields = ".field private m_quitApp:Z"
    if source.count(fields) != 1:
        raise ValueError("Qt quit flag declaration changed")
    result = source[:match.start()] + wrapper + helper + source[match.end():]
    return result.replace(fields, fields + "\n.field private lucent_terminal_started:Z", 1)


def argument_words(descriptor):
    words = 0
    for token in re.findall(r"\[*L[^;]+;|\[*[ZBSCIJFD]", descriptor):
        words += 2 if token in ("J", "D") else 1
    return words


def patch_binding(source):
    if MARKER in source:
        raise ValueError("Qt rejected-owner forwarding guard already applied")
    guarded = []

    def rewrite(match):
        signature, body = match.groups()
        name_descriptor = signature.split()[-1]
        if " static " in " " + signature + " " or not name_descriptor.startswith(("on", "dispatch")):
            return match.group(0)
        # Patch only real framework overrides that the pinned wrapper already
        # forwards to Android Activity with this exact name and descriptor.
        target = "Landroid/app/Activity;->" + name_descriptor
        # Qt's permission override forwards only to the global delegate, with
        # no superclass fallback. It is nevertheless an Android framework
        # callback and must not reach the retiring owner's native Qt state.
        permission_callback = name_descriptor == "onRequestPermissionsResult(I[Ljava/lang/String;[I)V"
        if (target not in body and not permission_callback) or "invokeDelegate" not in body:
            return match.group(0)
        params, result = name_descriptor.split("(", 1)[1].split(")", 1)
        local = re.search(r"^    \.locals (\d+)\n", body, re.M)
        if local is None:
            raise ValueError("framework override register format changed: " + signature)
        locals_needed = max(int(local.group(1)), 2 if result in ("J", "D") else 1)
        words = argument_words(params)
        call = f"invoke-super/range {{p0 .. p{words}}}, {target}"
        if result == "V":
            returns = "return-void"
        elif result.startswith(("L", "[")):
            returns = "move-result-object v0\n    return-object v0"
        elif result in ("J", "D"):
            returns = "move-result-wide v0\n    return-wide v0"
        else:
            returns = "move-result v0\n    return v0"
        guard = f"""    .locals {locals_needed}
    # {MARKER}: never forward a replacement owner into the old delegate.
    invoke-static/range {{p0 .. p0}}, {HOST}->shouldSkipQtDelegate(Landroid/app/Activity;)Z
    move-result v0
    if-eqz v0, :lucent_qt_delegate_allowed
    {call}
    {returns}
    :lucent_qt_delegate_allowed
"""
        guarded.append(name_descriptor)
        body = body[:local.start()] + guard + body[local.end():]
        return ".method " + signature + "\n" + body + ".end method"

    result = METHOD.sub(rewrite, source)
    required = {"onStart()V", "onResume()V", "onPause()V", "onStop()V",
                "onDestroy()V", "onSaveInstanceState(Landroid/os/Bundle;)V",
                "onRestoreInstanceState(Landroid/os/Bundle;)V", "onWindowFocusChanged(Z)V",
                "dispatchKeyEvent(Landroid/view/KeyEvent;)Z",
                "onRequestPermissionsResult(I[Ljava/lang/String;[I)V"}
    if not required.issubset(guarded):
        raise ValueError("missing expected framework forwarding: " + repr(required - set(guarded)))
    return result, guarded


def callback_source():
    return f""".class public final {CALLBACK}
.super Ljava/lang/Object;
.implements Ljava/lang/Runnable;
.field private final delegate:{QT}
.field private final owner:Landroid/app/Activity;
.method public constructor <init>({QT}Landroid/app/Activity;)V
    .locals 0
    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V
    iput-object p1, p0, {CALLBACK}->delegate:{QT}
    iput-object p2, p0, {CALLBACK}->owner:Landroid/app/Activity;
    return-void
.end method
.method public run()V
    .locals 2
    iget-object v0, p0, {CALLBACK}->delegate:{QT}
    iget-object v1, p0, {CALLBACK}->owner:Landroid/app/Activity;
    invoke-virtual {{v0, v1}}, {QT}->lucentCompleteTerminalShutdown(Landroid/app/Activity;)V
    return-void
.end method
"""


def validate_qt_thread(source):
    signature = f"static synthetic access$100({QT_THREAD})Ljava/lang/Thread;"
    matches = [m for m in METHOD.finditer(source) if m.group(1) == signature]
    if len(matches) != 1:
        raise ValueError("Qt backing-thread accessor changed")
    body = re.sub(r"^\s*\.line \d+\s*$", "", matches[0].group(2), flags=re.M)
    compact = "\n".join(line.strip() for line in body.splitlines() if line.strip())
    if compact != f".locals 0\niget-object p0, p0, {QT_THREAD}->m_qtThread:Ljava/lang/Thread;\nreturn-object p0":
        raise ValueError("Qt backing-thread accessor body changed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("smali_root", type=Path)
    args = parser.parse_args()
    qt = args.smali_root / "org/qtproject/qt5/android"
    delegate = qt / "QtActivityDelegate.smali"
    binding = qt / "bindings/QtActivity.smali"
    callback = qt / "LucentTerminalShutdown.smali"
    if callback.exists():
        raise SystemExit("refusing to overwrite existing Qt terminal callback")
    # Validate every input before writing generated build files.
    validate_qt_thread((qt / "QtThread.smali").read_text())
    patched_delegate = patch_delegate(delegate.read_text())
    patched_binding, guarded = patch_binding(binding.read_text())
    delegate.write_text(patched_delegate)
    binding.write_text(patched_binding)
    callback.write_text(callback_source())
    print("Qt terminal retirement: preserves Qt cleanup/join, managed process exit; guarded", len(guarded), "framework overrides")


if __name__ == "__main__":
    main()
