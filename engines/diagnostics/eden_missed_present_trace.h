// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <algorithm>
#include "common/logging.h"
#include "common/lucent_source_image.h"
#include "vulkan/vulkan_core.h"

namespace Lucent::Trial {
// Isolated diagnosis only: value copies of existing provenance, no FG pipeline,
// waits, pixel readbacks or per-frame log writes. Caller owns synchronization.
class MissedPresentTrace {
    struct Row {
        uint32_t id{};
        uint64_t submit{}, composition{}, composition_ns{}, queue_epoch{}, queue_frame{};
        uint32_t layers{}, flags{};
        int64_t period{};
        uint64_t desired{}, actual{}, earliest{}, margin{};
    };
public:
    void Submit(uint32_t id, uint64_t now, int64_t period,
                const lucent_source_composition_v1* source) {
        auto& row = rows[id % rows.size()];
        row = {}; row.id=id; row.submit=now; row.period=period;
        if (!source) return;
        row.composition=source->header.composition_ordinal;
        row.composition_ns=source->header.observed_monotonic_ns;
        row.layers=source->retained_layer_count;
        // Log primary non-overlay provenance only. Multi-layer composition is
        // explicitly identified; this is not pixel-change/guest-retirement proof.
        for (uint32_t i=0; i<source->retained_layer_count && i<LUCENT_SOURCE_IMAGE_MAX_LAYERS; ++i) {
            const auto& layer=source->layers[i];
            if (layer.flags & LUCENT_SOURCE_LAYER_OVERLAY) continue;
            row.queue_epoch=layer.queue_epoch; row.queue_frame=layer.queue_frame_number;
            row.flags=layer.flags; break;
        }
    }
    void Feedback(const VkPastPresentationTimingGOOGLE& t, uint64_t now) {
        if (!t.presentID || t.presentID<=last_id || !t.actualPresentTime || t.actualPresentTime>now) return;
        auto& row=rows[t.presentID % rows.size()];
        const bool found=row.id==t.presentID;
        if (found) {
            row.desired=t.desiredPresentTime; row.actual=t.actualPresentTime;
            row.earliest=t.earliestPresentTime; row.margin=t.presentMargin;
        }
        if (found && last_actual && row.period>0 && t.actualPresentTime>last_actual &&
            t.actualPresentTime-last_actual>static_cast<uint64_t>(row.period)*3/2) {
            ++misses;
            if (!last_log || now-last_log>=1000000000ULL) {
                last_log=now;
                LOG_INFO(Render_Vulkan, "Miss trace TRIAL count={} priorId={} id={} priorActualNs={} actualNs={} queryNs={}",
                         misses,last_id,t.presentID,last_actual,t.actualPresentTime,now);
                const uint32_t begin=last_id>2 ? last_id-2 : 1;
                const uint32_t end=std::min(t.presentID,begin+7);
                for (uint32_t id=begin; id<=end; ++id) {
                    const auto& r=rows[id%rows.size()];
                    if (r.id!=id) continue;
                    LOG_INFO(Render_Vulkan, "Miss row TRIAL id={} submitNs={} composition={} composeNs={} queueEpoch={} queueFrame={} layers={} flags={} periodNs={} desiredNs={} actualNs={} earliestNs={} marginNs={}",
                             r.id,r.submit,r.composition,r.composition_ns,r.queue_epoch,r.queue_frame,r.layers,r.flags,
                             r.period,r.desired,r.actual,r.earliest,r.margin);
                }
            }
        }
        last_id=t.presentID; last_actual=t.actualPresentTime;
    }
private:
    std::array<Row,128> rows{};
    uint32_t last_id{};
    uint64_t last_actual{},last_log{},misses{};
};
} // namespace Lucent::Trial
