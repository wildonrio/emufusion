#!/usr/bin/env python3
"""Isolate the retirement candidate plus rate-limited render-boundary samples."""
import argparse
import hashlib
from pathlib import Path
from prepare_flip_retirement import prepare


def instrument(payload):
    text = prepare(payload)  # Pins original source and retains the reviewed candidate.
    changes = []

    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise ValueError('missing or ambiguous render-progress anchor: ' + old)
        text = text.replace(old, new, 1)
        changes.append((old, new))

    replace('#include "stdafx.h"', '#include "stdafx.h"\n#include <android/log.h>\n'
            '#include "lucent_render_progress.h"')
    replace('void VKGSRender::reinitialize_swapchain()\n{',
            'void VKGSRender::reinitialize_swapchain()\n{\n'
            '\tLUCENT_RENDER_PROGRESS("reinit.begin lost=%d unavailable=%d", surface_lost, swapchain_unavailable);')
    replace('    surface_lost=false;\n}\n\nvoid VKGSRender::present',
            '    surface_lost=false;\n'
            '\tLUCENT_RENDER_PROGRESS("reinit.end unavailable=%d", swapchain_unavailable);\n'
            '}\n\nvoid VKGSRender::present')
    replace('void VKGSRender::flip(const rsx::display_flip_info_t& info)\n{',
            'void VKGSRender::flip(const rsx::display_flip_info_t& info)\n{\n'
            '\tLUCENT_RENDER_PROGRESS("flip.begin guest=%d skip=%d draws=%u unavailable=%d lost=%d", '
            'info.emu_flip, info.skip_frame, info.stats.draw_calls, swapchain_unavailable, surface_lost);')
    replace('\n\tif (info.emu_flip)\n\t{\n\t\tevaluate_cpu_usage_reduction_limits();',
            '\n\tLUCENT_RENDER_PROGRESS("flip.source guest=%d source=%d width=%u height=%u buffer=%u", '
            'info.emu_flip, image_to_flip != nullptr, buffer_width, buffer_height, info.buffer);\n'
            '\tif (info.emu_flip)\n\t{\n\t\tevaluate_cpu_usage_reduction_limits();')
    replace('\t\tswitch (VkResult error = m_swapchain->present(ctx->present_wait_semaphore, ctx->present_image))',
            '\t\tLUCENT_RENDER_PROGRESS("present.begin image=%u", ctx->present_image);\n'
            '\t\tconst VkResult error = m_swapchain->present(ctx->present_wait_semaphore, ctx->present_image);\n'
            '\t\tLUCENT_RENDER_PROGRESS("present.end result=%d", static_cast<int>(error));\n'
            '\t\tswitch (error)')
    replace('\tqueue_swap_request();\n\n\tm_frame_stats.flip_time',
            '\tqueue_swap_request();\n'
            '\tLUCENT_RENDER_PROGRESS("flip.queued guest=%d source=%d", info.emu_flip, image_to_flip != nullptr);\n'
            '\n\tm_frame_stats.flip_time')
    return text, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    text, _ = instrument(args.source.read_bytes())
    with args.output.open('x') as stream:
        stream.write(text)
    print('Output SHA256:', hashlib.sha256(text.encode()).hexdigest())


if __name__ == '__main__':
    main()
