#include "../include/lucent_surface_fit.h"

#include <stdio.h>
#include <stdlib.h>

#define CHECK(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "%s\n", message); return EXIT_FAILURE; } \
} while (0)

static bool contained(const lucent_surface_rect *rect,
                      uint32_t width, uint32_t height) {
    return rect->width && rect->height && rect->width <= width &&
            rect->height <= height && rect->x <= width - rect->width &&
            rect->y <= height - rect->height;
}

int main(void) {
    lucent_surface_rect rect;
    CHECK(lucent_surface_fit(1080, 1240, 1240, 1080, 4.0 / 3.0, &rect) &&
          rect.x == 0 && rect.y == 86 && rect.width == 1080 && rect.height == 1068,
          "Thor lower image was fitted in producer rather than logical coordinates");
    double composed_width = (double)rect.width * 1240.0 / 1080.0;
    double composed_height = (double)rect.height * 1080.0 / 1240.0;
    CHECK(fabs(composed_height - composed_width * 3.0 / 4.0) <= 1.0,
          "Thor composed lower image is not 4:3 within one physical pixel");
    CHECK(lucent_surface_fit(1920, 1080, 1920, 1080, 4.0 / 3.0, &rect) &&
          rect.x == 240 && rect.y == 0 && rect.width == 1440 && rect.height == 1080,
          "ordinary 4:3 fit changed");
    CHECK(lucent_surface_fit(1920, 1080, 1920, 1080, 5.0 / 3.0, &rect) &&
          rect.x == 60 && rect.y == 0 && rect.width == 1800 && rect.height == 1080,
          "ordinary 5:3 top-screen fit changed");
    CHECK(lucent_surface_fit(1920, 1080, 1920, 1080, 16.0 / 9.0, &rect) &&
          rect.x == 0 && rect.y == 0 && rect.width == 1920 && rect.height == 1080,
          "ordinary 16:9 fit changed");
    CHECK(lucent_surface_fit(1080, 1240, 1080, 1240, 4.0 / 3.0, &rect) &&
          rect.x == 0 && rect.y == 215 && rect.width == 1080 && rect.height == 810,
          "portrait logical View was incorrectly treated as landscape");
    CHECK(lucent_surface_fit(1000, 1000, 1000, 1000, 1.0, &rect) &&
          rect.x == 0 && rect.y == 0 && rect.width == 1000 && rect.height == 1000,
          "square fit changed");
    CHECK(lucent_surface_fit(1240, 1080, 1080, 1240, 3.0 / 4.0, &rect) &&
          contained(&rect, 1240, 1080), "portrait logical crop exceeded producer");
    const uint32_t sizes[][4] = {
        {1081, 1241, 1241, 1081}, {1239, 1079, 1079, 1239},
        {1919, 1079, 1919, 1079}, {1, 1, 1, 1}, {3, 7, 7, 3},
        {UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX}
    };
    const double aspects[] = {4.0 / 3.0, 5.0 / 3.0, 16.0 / 9.0, 3.0 / 4.0, 1.0};
    for (unsigned i = 0; i < sizeof(sizes) / sizeof(sizes[0]); ++i) {
        for (unsigned j = 0; j < sizeof(aspects) / sizeof(aspects[0]); ++j) {
            CHECK(lucent_surface_fit(sizes[i][0], sizes[i][1], sizes[i][2],
                                    sizes[i][3], aspects[j], &rect) &&
                  contained(&rect, sizes[i][0], sizes[i][1]),
                  "odd or boundary dimensions escaped the producer image");
            CHECK(sizes[i][0] - rect.width - rect.x <= rect.x + 1u &&
                  sizes[i][1] - rect.height - rect.y <= rect.y + 1u,
                  "rounded fit is not centered within one producer pixel");
        }
    }
    CHECK(!lucent_surface_fit(0, 1240, 1240, 1080, 4.0 / 3.0, &rect) &&
          !lucent_surface_fit(1080, 0, 1240, 1080, 4.0 / 3.0, &rect) &&
          !lucent_surface_fit(1080, 1240, 0, 1080, 4.0 / 3.0, &rect) &&
          !lucent_surface_fit(1080, 1240, 1240, 0, 4.0 / 3.0, &rect) &&
          !lucent_surface_fit(1080, 1240, 1240, 1080, 0.0, &rect) &&
          !lucent_surface_fit(1080, 1240, 1240, 1080, -1.0, &rect) &&
          !lucent_surface_fit(1080, 1240, 1240, 1080, NAN, &rect) &&
          !lucent_surface_fit(1080, 1240, 1240, 1080, INFINITY, &rect) &&
          !lucent_surface_fit(1080, 1240, 1240, 1080, 4.0 / 3.0, NULL),
          "invalid geometry or aspect was accepted");
    puts("logical View to producer surface geometry passed");
    return EXIT_SUCCESS;
}
