#include "../eden_coupled_clock_native.h"
#include <cassert>
#include <iostream>
using namespace Lucent::Trial;

void Correct() {
    g_coupled_clock_allowed.store(true);
    ObserveDisplayClock(1e9 / (120.0 * 1.00025));
    assert(std::abs(g_coupled_clock.Rate() - 1.00025) < 1e-9);
}

int main() {
    g_coupled_clock.Reset();
    Correct();
    Common::test_time_ns += 1000000000;
    const auto before = GuestClockNs();
    ResetDisplayClock();
    assert(g_coupled_clock.Rate() == 1.0 && GuestClockNs() == before);
    Common::test_time_ns += 1000000000;
    assert(GuestClockNs() == before + 1000000000);
    for (const double refresh : {0.0, -1.0, double(NAN), double(INFINITY),
                                 1e-300, 1e300, 1e9/90, 1e9/144, 1e9/50, 1e9/121.5}) {
        Correct();
        const auto epoch = GuestClockNs();
        ObserveDisplayClock(refresh);
        assert(g_coupled_clock.Rate() == 1.0 && GuestClockNs() == epoch);
    }
    Correct();
    g_coupled_clock_allowed.store(false);
    ObserveDisplayClock(1e9 / 120.03);
    assert(g_coupled_clock.Rate() == 1.0);
    g_coupled_clock_allowed.store(true);
    ObserveDisplayClock(1e9 / 59.985);
    assert(std::abs(g_coupled_clock.Rate() - .99975) < 1e-9);
    std::cout << "Display clock loss/unsupported/disallowed recovery preserves guest epoch\n";
}
