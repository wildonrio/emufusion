// SPDX-License-Identifier: CC0-1.0
// EmuFusion-owned PSP smoke fixture. It contains no Sony code, data, or media.

#include <pspdebug.h>
#include <pspkernel.h>

// SceModuleInfo.modname holds at most 27 characters.
PSP_MODULE_INFO("EmuFusion PSP Smoke Fixture", 0, 1, 0);
PSP_MAIN_THREAD_ATTR(THREAD_ATTR_USER | THREAD_ATTR_VFPU);

static int exit_callback(int arg1, int arg2, void *common) {
    (void)arg1;
    (void)arg2;
    (void)common;
    sceKernelExitGame();
    return 0;
}

static int callback_thread(SceSize args, void *argp) {
    (void)args;
    (void)argp;
    const int callback = sceKernelCreateCallback("exit", exit_callback, NULL);
    sceKernelRegisterExitCallback(callback);
    sceKernelSleepThreadCB();
    return 0;
}

int main(void) {
    pspDebugScreenInit();
    const int thread = sceKernelCreateThread(
        "callbacks", callback_thread, 0x11, 0xFA0, 0, NULL);
    if (thread >= 0) {
        sceKernelStartThread(thread, 0, NULL);
    }

    pspDebugScreenSetTextColor(0x00FFFFFF);
    pspDebugScreenPrintf("EMUFUSION PPSSPP SMOKE FIXTURE\n");
    pspDebugScreenPrintf("FRAME AND INPUT PROBE READY\n");
    sceKernelSleepThreadCB();
    return 0;
}
