/*
 * Original EmuFusion PC Engine qualification cartridge.
 *
 * Copyright 2026 EmuFusion contributors
 * SPDX-License-Identifier: GPL-3.0-only
 *
 * This deliberately tiny program presents a visible frame, emits a steady PSG
 * tone, and changes the background palette while button I is held. It contains
 * no firmware, commercial game code, or third-party artwork. The reproducible
 * QA build uses the zlib-licensed cc65 PCE target, not HuC or its SDK runtime.
 */

#include <conio.h>
#include <joystick.h>
#include <pce.h>

#define PSG_CHANNEL        (*(volatile unsigned char*)0x0800)
#define PSG_GLOBAL_PAN     (*(volatile unsigned char*)0x0801)
#define PSG_FREQUENCY_LOW  (*(volatile unsigned char*)0x0802)
#define PSG_FREQUENCY_HIGH (*(volatile unsigned char*)0x0803)
#define PSG_CONTROL        (*(volatile unsigned char*)0x0804)
#define PSG_CHANNEL_PAN    (*(volatile unsigned char*)0x0805)
#define PSG_WAVE_DATA      (*(volatile unsigned char*)0x0806)

static void start_tone(void)
{
    unsigned char index;

    PSG_GLOBAL_PAN = 0xff;
    PSG_CHANNEL = 0;
    PSG_CONTROL = 0;
    for (index = 0; index < 32; ++index) {
        PSG_WAVE_DATA = index < 16 ? 0x1f : 0x00;
    }
    PSG_FREQUENCY_LOW = 0x80;
    PSG_FREQUENCY_HIGH = 0x02;
    PSG_CHANNEL_PAN = 0xff;
    PSG_CONTROL = 0x9f;
}

int main(void)
{
    unsigned char previous = 0xff;

    joy_install(joy_static_stddrv);
    bgcolor(COLOR_BLUE);
    bordercolor(COLOR_BLUE);
    textcolor(COLOR_WHITE);
    clrscr();
    gotoxy(18, 11);
    cputs("LUCENT PC ENGINE QA");
    gotoxy(21, 14);
    cputs("HOLD BUTTON I");
    start_tone();

    for (;;) {
        unsigned char current = joy_read(JOY_1);
        if (current != previous) {
            bgcolor(JOY_BTN_I(current) ? COLOR_RED : COLOR_BLUE);
            bordercolor(JOY_BTN_I(current) ? COLOR_RED : COLOR_BLUE);
            previous = current;
        }
        waitvsync();
    }
}
