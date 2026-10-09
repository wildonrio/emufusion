#ifndef LUCENT_SURFACE_FIT_H
#define LUCENT_SURFACE_FIT_H

#include <math.h>
#include <stdbool.h>
#include <stdint.h>

typedef struct lucent_surface_rect {
    uint32_t x;
    uint32_t y;
    uint32_t width;
    uint32_t height;
} lucent_surface_rect;

/* Contain the complete image in logical View coordinates, then undo the
 * compositor's independent producer-to-View scale on each axis. This does
 * not rotate pixels: orientation belongs to the Android SurfaceControl.
 * Keeping producer and logical extents separate also handles ordinary
 * surfaces, where both extents are equal. */
static inline bool lucent_surface_fit(
        uint32_t producer_width, uint32_t producer_height,
        uint32_t logical_width, uint32_t logical_height,
        double aspect, lucent_surface_rect *rect) {
    double width;
    double height;
    double mapped_width;
    double mapped_height;
    if (!rect || !producer_width || !producer_height ||
            !logical_width || !logical_height || !isfinite(aspect) ||
            aspect <= 0.0) return false;
    width = logical_width;
    height = width / aspect;
    if (height > logical_height) {
        height = logical_height;
        width = height * aspect;
    }
    mapped_width = width * producer_width / logical_width;
    mapped_height = height * producer_height / logical_height;
    rect->width = mapped_width >= producer_width ? producer_width :
            (uint32_t)(mapped_width + 0.5);
    rect->height = mapped_height >= producer_height ? producer_height :
            (uint32_t)(mapped_height + 0.5);
    if (!rect->width) rect->width = 1u;
    if (!rect->height) rect->height = 1u;
    rect->x = (producer_width - rect->width) / 2u;
    rect->y = (producer_height - rect->height) / 2u;
    return true;
}

#endif
