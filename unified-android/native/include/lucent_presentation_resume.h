#ifndef LUCENT_PRESENTATION_RESUME_H
#define LUCENT_PRESENTATION_RESUME_H
#include <stdbool.h>
#include <stdint.h>

/* Lifecycle readiness, not a gameplay/FG cadence qualification. Never accept
 * a single frame: Thor can scan one out between two display power-on stalls. */
typedef struct lucent_presentation_resume {
    uint64_t last_id;
    int64_t last_present_ns;
    unsigned last_hold;
    unsigned regular_intervals;
} lucent_presentation_resume;

static inline bool lucent_presentation_resume_observe(
        lucent_presentation_resume *state, uint64_t id, int64_t present_ns,
        int64_t observed_ns, int64_t interval_ns) {
    if (id <= state->last_id || present_ns <= 0 || interval_ns < 1000000 ||
            interval_ns > 100000000) return false;
    int64_t delta = present_ns - state->last_present_ns;
    bool recent = observed_ns >= present_ns &&
            observed_ns - present_ns <= interval_ns * 4;
    /* The caller may run at a divisor (e.g.60Hz callbacks on a120Hz panel).
     * Uniform holds are ready too; changing holds or long stalls are not. */
    unsigned hold = delta > 0 && delta <= interval_ns * 4 + interval_ns / 4 ?
            (unsigned)((delta + interval_ns / 2) / interval_ns) : 0;
    int64_t error = delta - (int64_t)hold * interval_ns;
    bool regular = recent && id == state->last_id + 1 &&
            state->last_present_ns > 0 && hold >= 1 && hold <= 4 &&
            error >= -interval_ns / 4 && error <= interval_ns / 4;
    state->regular_intervals = regular ?
            (hold == state->last_hold ? state->regular_intervals + 1 : 1) : 0;
    state->last_hold = regular ? hold : 0;
    state->last_id = id;
    state->last_present_ns = recent ? present_ns : 0;
    return state->regular_intervals >= 2;
}
#endif
