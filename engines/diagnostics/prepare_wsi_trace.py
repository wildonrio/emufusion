#!/usr/bin/env python3
"""Generate an isolated logging-only VKPresent translation unit.

Refuse changed inputs and existing outputs. Never modify the source tree.
The extra logging is intentionally diagnostic overhead, not performance proof.
"""
import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = "b50eaf61cea6c6d6d1928777b48f8a9e5db8639d3b32815871c10ea66cb756f9"


def instrument(payload):
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA:
        raise ValueError("VKPresent source changed: review the new code before preparing a trace")
    text = payload.decode()

    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise ValueError("ambiguous or missing trace anchor: " + old[:100])
        text = text.replace(old, new, 1)

    replace('#include "stdafx.h"', '#include "stdafx.h"\n#include <android/log.h>\n'
            '#define LUCENT_WSI_EVENT(...) __android_log_print(ANDROID_LOG_INFO, "LucentWsiTrace", __VA_ARGS__)')
    replace('void VKGSRender::reinitialize_swapchain()\n{',
            'void VKGSRender::reinitialize_swapchain()\n{\n'
            '\tLUCENT_WSI_EVENT("reinit.enter lost=%d unavailable=%d window=%p", '
            'surface_lost, swapchain_unavailable, m_frame->handle());')
    replace('\t// NOTE: This operation will create a hard sync point\n\tclose_and_submit_command_buffer();',
            '\t// NOTE: This operation will create a hard sync point\n'
            '\tLUCENT_WSI_EVENT("reinit.submit.begin");\n\tclose_and_submit_command_buffer();\n'
            '\tLUCENT_WSI_EVENT("reinit.submit.end");')
    replace('\t\t// Release present image by presenting it\n\t\tframe_context_cleanup(&ctx);',
            '\t\t// Release present image by presenting it\n'
            '\t\tLUCENT_WSI_EVENT("reinit.cleanup.begin image=%u", ctx.present_image);\n'
            '\t\tframe_context_cleanup(&ctx);\n\t\tLUCENT_WSI_EVENT("reinit.cleanup.end");')
    replace('\t// Drain all the queues\n\t_vkDeviceWaitIdle(*m_device);',
            '\t// Drain all the queues\n\tLUCENT_WSI_EVENT("reinit.idle.begin");\n'
            '\tconst auto lucent_idle_result = _vkDeviceWaitIdle(*m_device);\n'
            '\tLUCENT_WSI_EVENT("reinit.idle.end result=%d", static_cast<int>(lucent_idle_result));')
    replace('        m_swapchain->create(handle);',
            '        LUCENT_WSI_EVENT("reinit.surface.begin window=%p", handle);\n'
            '        m_swapchain->create(handle);\n'
            '        LUCENT_WSI_EVENT("reinit.surface.end");')
    replace('\tif (!m_swapchain->init(m_swapchain_dims.width, m_swapchain_dims.height))',
            '\tLUCENT_WSI_EVENT("reinit.swapchain.begin width=%u height=%u", '
            'm_swapchain_dims.width, m_swapchain_dims.height);\n'
            '\tif (!m_swapchain->init(m_swapchain_dims.width, m_swapchain_dims.height))')
    replace('\t\trsx_log.warning("Swapchain initialization failed.',
            '\t\tLUCENT_WSI_EVENT("reinit.swapchain.failed");\n'
            '\t\trsx_log.warning("Swapchain initialization failed.')
    replace('\t// Prepare new swapchain images for use',
            '\tLUCENT_WSI_EVENT("reinit.swapchain.end");\n\t// Prepare new swapchain images for use')
    replace('\tclose_and_submit_command_buffer(&resize_fence);\n\tvk::wait_for_fence(&resize_fence);',
            '\tLUCENT_WSI_EVENT("reinit.resize-submit.begin");\n'
            '\tclose_and_submit_command_buffer(&resize_fence);\n'
            '\tLUCENT_WSI_EVENT("reinit.resize-wait.begin");\n'
            '\tvk::wait_for_fence(&resize_fence);\n'
            '\tLUCENT_WSI_EVENT("reinit.resize-wait.end");')
    replace('    surface_lost=false;\n}\n\nvoid VKGSRender::present',
            '    surface_lost=false;\n\tLUCENT_WSI_EVENT("reinit.exit");\n}\n\nvoid VKGSRender::present')
    replace('\t// Partial CS flush\n\tctx->swap_command_buffer->flush();',
            '\t// Partial CS flush\n'
            '\tLUCENT_WSI_EVENT("present.flush.begin image=%u unavailable=%d", ctx->present_image, swapchain_unavailable);\n'
            '\tctx->swap_command_buffer->flush();\n'
            '\tLUCENT_WSI_EVENT("present.flush.end");')
    replace('\t\tswitch (VkResult error = m_swapchain->present(ctx->present_wait_semaphore, ctx->present_image))',
            '\t\tLUCENT_WSI_EVENT("present.call.begin image=%u", ctx->present_image);\n'
            '\t\tconst VkResult error = m_swapchain->present(ctx->present_wait_semaphore, ctx->present_image);\n'
            '\t\tLUCENT_WSI_EVENT("present.call.end result=%d", static_cast<int>(error));\n'
            '\t\tswitch (error)')
    replace('void VKGSRender::flip(const rsx::display_flip_info_t& info)\n{',
            'void VKGSRender::flip(const rsx::display_flip_info_t& info)\n{\n'
            '\tLUCENT_WSI_EVENT("flip.enter skip=%d unavailable=%d lost=%d window=%p", '
            'info.skip_frame, swapchain_unavailable, surface_lost, m_frame->handle());')
    acquire = 'm_swapchain->acquire_next_swapchain_image(m_current_frame->acquire_signal_semaphore, timeout, &m_current_frame->present_image)'
    replace('\twhile (VkResult status = ' + acquire + ')\n\t{',
            '\tLUCENT_WSI_EVENT("acquire.begin timeout=%llu", static_cast<unsigned long long>(timeout));\n'
            '\tVkResult lucent_last_acquire_result = VK_SUCCESS;\n'
            '\twhile (VkResult status = ' + acquire + ')\n\t{\n'
            '\t\tif (status != lucent_last_acquire_result) {\n'
            '\t\t\tLUCENT_WSI_EVENT("acquire.result result=%d image=%u", '
            'static_cast<int>(status), m_current_frame->present_image);\n'
            '\t\t\tlucent_last_acquire_result = status;\n\t\t}')
    replace('\t// Confirm that the driver did not silently fail',
            '\tLUCENT_WSI_EVENT("acquire.complete image=%u", m_current_frame->present_image);\n'
            '\t// Confirm that the driver did not silently fail')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    payload = args.source.read_bytes()
    output = instrument(payload)
    # Exclusive creation also refuses a racing writer or a symlink target.
    with args.output.open('x') as stream:
        stream.write(output)
    print('Input SHA256:', hashlib.sha256(payload).hexdigest())
    print('Output SHA256:', hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
