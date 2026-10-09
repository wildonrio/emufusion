// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>

namespace Lucent::Trial {
// Per-stream stereo state. Consume fractional guest samples while delivering
// the unchanged 48-kHz device quantum. Retain lookahead/phase across blocks and
// pause; a stream's destruction naturally retires its state.
class ClockedStereoAudio {
public:
    template<class Pull>
    size_t Render(int16_t* output, size_t frames, double ratio, Pull pull) {
        if (!frames || frames > 240 || !std::isfinite(ratio) || ratio < 0.9925 || ratio > 1.0075)
            return 0;
        if (!active && ratio == 1.0) {
            pull(output, frames); // Exact default bypass; no extra consumed sample.
            return frames;
        }
        active = true;
        const auto required = static_cast<size_t>(std::floor(phase + (frames - 1) * ratio)) + 2;
        const auto added = required > buffered ? required - buffered : 0;
        if (added) pull(samples.data() + buffered * 2, added);
        buffered += added;
        for (size_t i = 0; i < frames; ++i) {
            const double pos = phase + i * ratio;
            const auto index = static_cast<size_t>(pos);
            const double fraction = pos - index;
            for (size_t channel = 0; channel < 2; ++channel) {
                const double a = samples[index * 2 + channel];
                const double b = samples[(index + 1) * 2 + channel];
                output[i * 2 + channel] = static_cast<int16_t>(std::lround(a + (b - a) * fraction));
            }
        }
        const double advanced = phase + frames * ratio;
        const auto consumed = static_cast<size_t>(std::floor(advanced));
        phase = advanced - consumed;
        buffered -= consumed;
        std::memmove(samples.data(), samples.data() + consumed * 2, buffered * 2 * sizeof(int16_t));
        return added;
    }
private:
    std::array<int16_t, 512> samples{};
    size_t buffered{};
    double phase{};
    bool active{};
};
} // namespace Lucent::Trial
