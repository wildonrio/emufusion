#include "../eden_coupled_clock.h"
#include "../eden_clocked_audio.h"
#include <cassert>
#include <iostream>
#include <thread>
#include <vector>
using namespace Lucent::Trial;
int main() {
    CoupledClock clock;
    int64_t raw = 1000000000000LL;
    auto read = [&] { return raw; };
    assert(clock.Now(read) == raw && clock.Rate() == 1.0);
    assert(!clock.SetRate(0.99, read) && !clock.SetRate(NAN, read));
    assert(clock.SetRate(0.999667, read));
    assert(clock.Now(read) == raw);
    raw += 1000000000;
    assert(clock.Now(read) == raw - 333000);
    auto before = clock.Now(read);
    assert(clock.SetRate(1.0075, read) && clock.Now(read) == before);
    raw += 1000000000;
    assert(clock.Now(read) == before + 1007500000);
    assert(clock.HostWaitNs(1007500000) == 1000000000);
    before = clock.Now(read);
    assert(clock.SetRate(1.0, read) && clock.Now(read) == before);
    raw += 1000000000;
    assert(clock.Now(read) == before + 1000000000);
    clock.Reset();
    assert(clock.Now(read) == raw);
    std::atomic<int64_t> counter{raw};
    auto concurrent_raw = [&] { return counter.fetch_add(1000); };
    std::vector<std::thread> readers;
    for (int t = 0; t < 4; ++t) readers.emplace_back([&] {
        int64_t previous = 0;
        for (int i = 0; i < 100000; ++i) {
            auto value = clock.Now(concurrent_raw);
            assert(value >= previous); previous = value;
        }
    });
    for (int i = 0; i < 10000; ++i) assert(clock.SetRate(i & 1 ? .999667 : 1.000333, concurrent_raw));
    for (auto& reader : readers) reader.join();
    for (double ratio : {1.0, .999667, .9925, 1.0075}) {
        ClockedStereoAudio audio;
        uint64_t pulled = 0;
        std::array<int16_t,480> output{};
        for (int b = 0; b < 10000; ++b) {
            audio.Render(output.data(),240,ratio,[&](int16_t* to,size_t frames) {
                pulled += frames;
                for (size_t f=0; f<frames; ++f) {to[2*f]=12000;to[2*f+1]=-7000;}
            });
            for (size_t f=0; f<240; ++f) assert(output[2*f]==12000 && output[2*f+1]==-7000);
        }
        assert(std::abs(static_cast<double>(pulled) - 2400000*ratio) <= 2.001);
        if (ratio == 1.0) assert(pulled == 2400000);
    }
    // Changing rate retains fractional phase and the same sample sequence.
    ClockedStereoAudio ramp;
    uint64_t source_index=0;
    double expected_position=0;
    std::array<int16_t,480> output{};
    for (int b=0;b<20;++b) {
        const double rate = b<10 ? .999667 : 1.000333;
        ramp.Render(output.data(),240,rate,[&](int16_t* to,size_t frames) {
            for(size_t f=0;f<frames;++f,++source_index) {
                to[2*f]=static_cast<int16_t>(source_index);
                to[2*f+1]=-static_cast<int16_t>(source_index);
            }
        });
        for(size_t f=0;f<240;++f) {
            assert(std::abs(output[2*f] - std::lround(expected_position+f*rate)) <= 1);
            assert(output[2*f+1] == -output[2*f]);
        }
        expected_position += 240*rate;
    }
    // Exercise tiny and maximum blocks at both rate bounds, including return
    // to identity after interpolation has acquired a fractional phase.
    ClockedStereoAudio variable;
    uint64_t total_pulled=0;
    double expected_pulled=0;
    for (int b=0;b<20000;++b) {
        const size_t frames=static_cast<size_t>(b%240)+1;
        const double rate=b%3==0 ? .9925 : b%3==1 ? 1.0075 : 1.0;
        variable.Render(output.data(),frames,rate,[&](int16_t* to,size_t count) {
            total_pulled+=count;
            for(size_t f=0;f<count;++f) {to[2*f]=32767;to[2*f+1]=-32768;}
        });
        expected_pulled+=frames*rate;
        assert(std::abs(static_cast<double>(total_pulled)-expected_pulled)<=2.001);
        for(size_t f=0;f<frames;++f) assert(output[2*f]==32767 && output[2*f+1]==-32768);
    }
    for(double invalid : std::array<double,5>{0.0, .9924, 1.0076, INFINITY, NAN}) {
        bool called=false;
        assert(variable.Render(output.data(),240,invalid,[&](int16_t*,size_t){called=true;})==0);
        assert(!called);
    }
    std::cout << "Coupled clock continuity/concurrency and fractional audio tests passed\n";
}
