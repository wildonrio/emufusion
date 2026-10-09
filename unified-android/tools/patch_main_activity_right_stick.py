#!/usr/bin/env python3
"""Add EmuFusion in-window gameplay hooks to the inherited Qt activity class."""

from __future__ import annotations

import argparse
from pathlib import Path


METHODS = r'''

# EmuFusion keeps the inherited Qt activity class because Qt binds its delegate to
# the exact Java class. These hooks keep emulation inside that same Activity and
# Window while delegating the implementation to ordinary Java.
.method protected onCreateHook(Landroid/os/Bundle;)V
    .locals 1

    invoke-static {p0, p1}, Lcom/thorium/preview/game/InWindowGameHost;->onCreate(Landroid/app/Activity;Landroid/os/Bundle;)V

    invoke-static {p0}, Lcom/thorium/preview/game/InWindowGameHost;->shouldSkipQtDelegate(Landroid/app/Activity;)Z

    move-result v0

    if-nez v0, :lucent_skip_retiring_qt_bootstrap

    invoke-super {p0, p1}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onCreateHook(Landroid/os/Bundle;)V

    :lucent_skip_retiring_qt_bootstrap
    return-void
.end method

.method protected onSaveInstanceState(Landroid/os/Bundle;)V
    .locals 0

    invoke-super {p0, p1}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onSaveInstanceState(Landroid/os/Bundle;)V

    invoke-static {p0, p1}, Lcom/thorium/preview/game/InWindowGameHost;->onSaveInstanceState(Landroid/app/Activity;Landroid/os/Bundle;)V

    return-void
.end method

.method protected onNewIntent(Landroid/content/Intent;)V
    .locals 0

    invoke-super {p0, p1}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onNewIntent(Landroid/content/Intent;)V

    invoke-virtual {p0, p1}, Lorg/pegasus_frontend/android/MainActivity;->setIntent(Landroid/content/Intent;)V

    invoke-static {p0, p1}, Lcom/thorium/preview/game/InWindowGameHost;->handleIntent(Landroid/app/Activity;Landroid/content/Intent;)Z

    return-void
.end method

.method protected onResume()V
    .locals 0

    invoke-super {p0}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onResume()V

    invoke-static {p0}, Lcom/thorium/preview/game/InWindowGameHost;->onResume(Landroid/app/Activity;)V

    return-void
.end method

.method protected onPause()V
    .locals 0

    invoke-static {p0}, Lcom/thorium/preview/game/InWindowGameHost;->onPause(Landroid/app/Activity;)V

    invoke-super {p0}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onPause()V

    return-void
.end method

.method protected onDestroy()V
    .locals 0

    invoke-static {p0}, Lcom/thorium/preview/game/InWindowGameHost;->onDestroy(Landroid/app/Activity;)V

    invoke-super {p0}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onDestroy()V

    return-void
.end method

.method public dispatchKeyEvent(Landroid/view/KeyEvent;)Z
    .locals 1

    invoke-static {p0, p1}, Lcom/thorium/preview/game/InWindowGameHost;->dispatchKeyEvent(Landroid/app/Activity;Landroid/view/KeyEvent;)Z

    move-result v0

    if-eqz v0, :lucent_call_qt_key

    const/4 v0, 0x1

    return v0

    :lucent_call_qt_key
    invoke-super {p0, p1}, Lorg/qtproject/qt5/android/bindings/QtActivity;->dispatchKeyEvent(Landroid/view/KeyEvent;)Z

    move-result v0

    return v0
.end method

.method public onBackPressed()V
    .locals 1

    invoke-static {p0}, Lcom/thorium/preview/game/InWindowGameHost;->onBackPressed(Landroid/app/Activity;)Z

    move-result v0

    if-eqz v0, :lucent_call_qt_back

    return-void

    :lucent_call_qt_back
    invoke-super {p0}, Lorg/qtproject/qt5/android/bindings/QtActivity;->onBackPressed()V

    return-void
.end method

.method public dispatchGenericMotionEvent(Landroid/view/MotionEvent;)Z
    .locals 1

    invoke-static {p0, p1}, Lcom/thorium/preview/game/InWindowGameHost;->dispatchGenericMotionEvent(Landroid/app/Activity;Landroid/view/MotionEvent;)Z

    move-result v0

    if-nez v0, :lucent_motion_handled

    invoke-static {p0, p1}, Lcom/thorium/lucent/navigation/RightStickMotionBridge;->dispatch(Landroid/app/Activity;Landroid/view/MotionEvent;)Z

    move-result v0

    if-eqz v0, :lucent_call_qt

    :lucent_motion_handled
    const/4 v0, 0x1

    return v0

    :lucent_call_qt
    invoke-super {p0, p1}, Lorg/qtproject/qt5/android/bindings/QtActivity;->dispatchGenericMotionEvent(Landroid/view/MotionEvent;)Z

    move-result v0

    return v0
.end method
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("smali", type=Path)
    args = parser.parse_args()
    source = args.smali.read_text(encoding="utf-8")
    for signature in (
            ".method public dispatchGenericMotionEvent(Landroid/view/MotionEvent;)Z",
            ".method public dispatchKeyEvent(Landroid/view/KeyEvent;)Z",
            ".method protected onCreateHook(Landroid/os/Bundle;)V",
            ".method protected onSaveInstanceState(Landroid/os/Bundle;)V",
            ".method protected onNewIntent(Landroid/content/Intent;)V"):
        if signature in source:
            raise SystemExit(f"refusing duplicate EmuFusion activity hook: {args.smali}")
    start_tail = '''    sput v0, Lorg/pegasus_frontend/android/MainActivity;->m_icon_density:I

    return-void
.end method'''
    replacement = '''    sput v0, Lorg/pegasus_frontend/android/MainActivity;->m_icon_density:I

    invoke-static {}, Lcom/thorium/preview/game/InWindowGameHost;->isQtTerminalShutdownPending()Z

    move-result v0

    if-nez v0, :lucent_skip_retiring_qt_start

    invoke-static {p0}, Lcom/thorium/preview/game/InWindowGameHost;->onStart(Landroid/app/Activity;)V

    invoke-static {p0}, Lcom/thorium/preview/FullDisplayWindow;->apply(Landroid/app/Activity;)V

    invoke-static {p0}, Lcom/thorium/preview/BootVideoOverlay;->begin(Landroid/app/Activity;)V

    invoke-static {p0}, Lcom/thorium/preview/LegalNoticeOverlay;->begin(Landroid/app/Activity;)V

    :lucent_skip_retiring_qt_start
    return-void
.end method'''
    if source.count(start_tail) != 1:
        raise SystemExit(f"could not locate exact MainActivity.onStart tail: {args.smali}")
    source = source.replace(start_tail, replacement)
    am_entry = '''.method public static launchAmCommand([Ljava/lang/String;)Ljava/lang/String;
    .locals 2
'''
    am_intercept = am_entry + '''
    invoke-static {p0}, Lcom/thorium/preview/InProcessGameLaunchCommand;->tryLaunch([Ljava/lang/String;)Z

    move-result v0

    if-eqz v0, :lucent_normal_am_launch

    const/4 v0, 0x0

    return-object v0

    :lucent_normal_am_launch
'''
    if source.count(am_entry) != 1:
        raise SystemExit(f"could not locate exact MainActivity.launchAmCommand entry: {args.smali}")
    source = source.replace(am_entry, am_intercept)
    args.smali.write_text(source.rstrip() + METHODS + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
