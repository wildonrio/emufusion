#include "../include/lucent_presentation_resume.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    lucent_presentation_resume state = {0};
    int64_t interval = 16666667;
    /* Replay the measured Thor double-PowerOn wake. IDs1-3 were unqueryable. */
    assert(!lucent_presentation_resume_observe(&state, 1, -2, 17280500000000, interval));
    assert(!lucent_presentation_resume_observe(&state, 2, -1, 17280500000000, interval));
    assert(!lucent_presentation_resume_observe(&state, 4, 17280746926531, 17280750968042, interval));
    assert(!lucent_presentation_resume_observe(&state, 5, 17280980398093, 17280991644864, interval));
    assert(!lucent_presentation_resume_observe(&state, 6, 17280997073301, 17281008416167, interval));
    assert(lucent_presentation_resume_observe(&state, 7, 17281013747625, 17281024812781, interval));
    assert(!lucent_presentation_resume_observe(&state, 7, 17281013747625, 17281024812781, interval));
    /* A missing ID, stale completion, future timestamp or long hold resets readiness. */
    assert(!lucent_presentation_resume_observe(&state, 9, 17281047096114, 17281058242208, interval));
    assert(!lucent_presentation_resume_observe(&state, 10, 17281063768927, 17282063768927, interval));
    assert(!lucent_presentation_resume_observe(&state, 11, 17283063768927, 17282063768927, interval));
    state = (lucent_presentation_resume){0};
    interval = 8333333; /* 120Hz does not reuse a 60Hz threshold. */
    assert(!lucent_presentation_resume_observe(&state, 1, 1000000000, 1001000000, interval));
    assert(!lucent_presentation_resume_observe(&state, 2, 1008333333, 1009333333, interval));
    assert(lucent_presentation_resume_observe(&state, 3, 1016666666, 1017666666, interval));
    assert(!lucent_presentation_resume_observe(&state, 4, 1033333333, 1034333333, interval));
    assert(lucent_presentation_resume_observe(&state, 5, 1050000000, 1051000000, interval));
    puts("presentation resume policy passed: actual double-stall trace, missing/stale IDs, 60/120Hz");
    return 0;
}
