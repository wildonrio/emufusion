/* Standalone host-only Android diagnostic regression. No core or device needed.
 * Compile with the fake-android include directory and -pthread -ldl.
 * Include the host implementation to exercise its actual private callback with
 * an in-memory host; the log shim records only the new input evidence. */
#define _XOPEN_SOURCE 700
#define __ANDROID__ 1
#define LUCENT_FAKE_ANDROID_LOG_H
#define ANDROID_LOG_DEBUG 3
#define ANDROID_LOG_INFO 4
#define ANDROID_LOG_WARN 5
#define ANDROID_LOG_ERROR 6

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static unsigned applied_logs;
static unsigned transition_logs;
static unsigned sample_logs;
static unsigned released_callback_logs;
static unsigned pointer_applied_logs;
static unsigned pointer_callback_logs;
static unsigned pointer_release_logs;
static char last_pointer_callback[1024];

static int __android_log_print(int priority, const char *tag,
                               const char *format, ...) {
    char message[1024];
    va_list arguments;
    (void)priority;
    (void)tag;
    va_start(arguments, format);
    vsnprintf(message, sizeof(message), format, arguments);
    va_end(arguments);
    if (strstr(message, "marker=input-applied")) ++applied_logs;
    if (strstr(message, "marker=input-consumed")) {
        if (strstr(message, "kind=transition")) {
            ++transition_logs;
            if (strstr(message, "result=0 ")) ++released_callback_logs;
        }
        if (strstr(message, "kind=held-sample")) ++sample_logs;
    }
    if (strstr(message, "marker=pointer-applied")) ++pointer_applied_logs;
    if (strstr(message, "marker=pointer-consumed")) {
        ++pointer_callback_logs;
        if (strstr(message, "pressed=0 ")) ++pointer_release_logs;
        memcpy(last_pointer_callback, message, sizeof(message));
    }
    return 0;
}

#include "../lucent_libretro_host.c"

#define CHECK(value, message) do { \
    if (!(value)) { fprintf(stderr, "%s\n", message); return 1; } \
} while (0)

int main(void) {
    lucent_retro_host host = {0};
    unsigned iteration;
    active_host = &host;

    /* The software path and invalid input must remain quiet and unchanged. */
    CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_START,
                                        true), "software press failed");
    CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                               RETRO_DEVICE_ID_JOYPAD_START) == 1,
          "software callback changed");
    CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_START,
                                        false), "software release failed");
    CHECK(!lucent_retro_set_joypad_button(&host, MAX_PORTS, 3, true),
          "invalid port accepted");
    CHECK(!lucent_retro_set_joypad_button(&host, 0, MAX_JOYPAD_BUTTONS, true),
          "invalid button accepted");
    CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0, 999) == 0,
          "invalid callback ID changed");
    CHECK(applied_logs + transition_logs + sample_logs == 0,
          "software input or invalid input generated diagnostics");

    host.hw_negotiated = true;
    host.run_sequence = 1;
    for (iteration = 0; iteration < 1000; ++iteration) {
        CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                                   RETRO_DEVICE_ID_JOYPAD_START) == 0,
              "idle callback changed");
    }
    CHECK(transition_logs + sample_logs == 0, "idle polls consumed log budget");

    CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_START,
                                        true), "Start press failed");
    CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_START,
                                        true), "repeated Start press failed");
    CHECK(applied_logs == 1, "unchanged setter state consumed log budget");
    for (iteration = 0; iteration < 1000; ++iteration) {
        CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                                   RETRO_DEVICE_ID_JOYPAD_START) == 1,
              "held Start callback changed");
    }
    CHECK(transition_logs == 1 && sample_logs == 1,
          "repeated same-frame callbacks generated excess samples");

    for (iteration = 0; iteration < 1000; ++iteration) {
        ++host.run_sequence;
        CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                                   RETRO_DEVICE_ID_JOYPAD_START) == 1,
              "sample exhaustion changed held input");
    }
    CHECK(sample_logs == 32, "held callback sample budget was not 32");
    CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_START,
                                        false), "Start release failed");
    CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                               RETRO_DEVICE_ID_JOYPAD_START) == 0,
          "released Start callback changed");
    CHECK(released_callback_logs == 1,
          "sample exhaustion hid the release callback");

    for (iteration = 0; iteration < 1000; ++iteration) {
        bool pressed = (iteration & 1u) == 0;
        ++host.run_sequence;
        CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_A,
                                            pressed), "A transition failed");
        CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                                   RETRO_DEVICE_ID_JOYPAD_A) == (pressed ? 1 : 0),
              "budget exhaustion changed A state");
    }
    CHECK(applied_logs == 16 && transition_logs == 16 && sample_logs == 32,
          "per-host input log limits were not enforced");

    /* A new host can produce fresh evidence; MASK reads preserve the full
     * signed libretro bitmask, not just the two buttons being diagnosed. */
    memset(&host, 0, sizeof(host));
    applied_logs = transition_logs = sample_logs = released_callback_logs = 0;
    host.hw_negotiated = true;
    host.run_sequence = 1;
    CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_R3,
                                        true), "untracked R3 press failed");
    CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                               RETRO_DEVICE_ID_JOYPAD_MASK) == (int16_t)0x8000u,
          "untracked mask bits changed");
    CHECK(applied_logs + transition_logs + sample_logs == 0,
          "untracked mask bits generated diagnostics");
    CHECK(lucent_retro_set_joypad_button(&host, 0, RETRO_DEVICE_ID_JOYPAD_A,
                                        true), "mask A press failed");
    CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                               RETRO_DEVICE_ID_JOYPAD_MASK) == (int16_t)0x8100u,
          "tracked mask return value changed");
    CHECK(applied_logs == 1 && transition_logs == 1,
          "mask callback did not record A transition");
    CHECK(input_state_callback(0, RETRO_DEVICE_JOYPAD, 0,
                               RETRO_DEVICE_ID_JOYPAD_A) == 1,
          "individual A read after mask read changed");
    CHECK(transition_logs == 1, "mask and individual reads duplicated a transition");

    memset(&host, 0, sizeof(host));
    CHECK(lucent_retro_set_pointer(&host, 0, 10922, 28891, true),
          "software pointer press failed");
    CHECK(input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                               RETRO_DEVICE_ID_POINTER_PRESSED) == 1,
          "software pointer callback changed");
    CHECK(lucent_retro_set_pointer(&host, 0, 10922, 28891, false),
          "software pointer release failed");
    CHECK(input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                               RETRO_DEVICE_ID_POINTER_PRESSED) == 0,
          "software pointer release callback changed");
    CHECK(pointer_applied_logs + pointer_callback_logs == 0,
          "software pointer generated diagnostics");

    host.hw_negotiated = true;
    host.run_sequence = 42;
    for (iteration = 0; iteration < 1000; ++iteration)
        CHECK(input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                                   RETRO_DEVICE_ID_POINTER_PRESSED) == 0,
              "idle pointer callback changed");
    CHECK(pointer_callback_logs == 0, "idle pointer polls consumed budget");
    CHECK(lucent_retro_set_pointer(&host, 0, 10922, 28891, true),
          "hardware pointer press failed");
    for (iteration = 0; iteration < 1000; ++iteration) {
        CHECK(lucent_retro_set_pointer(&host, 0, 10922, 28891, true),
              "held pointer update failed");
        CHECK(input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                                   RETRO_DEVICE_ID_POINTER_X) == 10922 &&
              input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                                   RETRO_DEVICE_ID_POINTER_Y) == 28891 &&
              input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                                   RETRO_DEVICE_ID_POINTER_PRESSED) == 1,
              "pointer tuple changed");
    }
    CHECK(pointer_applied_logs == 1 && pointer_callback_logs == 1,
          "held pointer polls or setters consumed release budget");
    CHECK(strstr(last_pointer_callback, "run=42 port=0 index=0 x=10922 y=28891 pressed=1 "),
          "pointer callback did not snapshot the delivered coordinate tuple");
    CHECK(lucent_retro_set_pointer(&host, 0, -32767, 32766, false),
          "hardware pointer release failed");
    CHECK(input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                               RETRO_DEVICE_ID_POINTER_PRESSED) == 0,
          "hardware pointer release callback changed");
    CHECK(pointer_release_logs == 1 && pointer_callback_logs == 2,
          "held pointer polling hid the release");
    for (iteration = 0; iteration < 1000; ++iteration) {
        bool pressed = (iteration & 1u) == 0;
        ++host.run_sequence;
        CHECK(lucent_retro_set_pointer(&host, 0, -32767, 32766, pressed),
              "pointer budget stress update failed");
        CHECK(input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                                   RETRO_DEVICE_ID_POINTER_X) == -32767 &&
              input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                                   RETRO_DEVICE_ID_POINTER_Y) == 32766 &&
              input_state_callback(0, RETRO_DEVICE_POINTER, 0,
                                   RETRO_DEVICE_ID_POINTER_PRESSED) == (pressed ? 1 : 0),
              "pointer budget exhaustion changed return values");
    }
    CHECK(pointer_applied_logs == 12 && pointer_callback_logs == 12 &&
          pointer_release_logs == 6,
          "pointer diagnostics exceeded twelve records per boundary");
    active_host = NULL;
    puts("input trace host tests passed");
    return 0;
}
