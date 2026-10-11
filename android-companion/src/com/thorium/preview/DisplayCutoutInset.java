package com.thorium.preview;

import android.content.Context;
import android.graphics.Point;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.view.Display;
import android.view.DisplayCutout;

/**
 * Depth of the main display's camera cutout band as a fraction of its long
 * side, for the theme's safe inset (/capabilities). The library window runs
 * under the cutout (FullDisplayWindow.extendIntoCutout) so a phone held
 * sideways has no black band, which means the theme must keep its text clear
 * of the punch hole itself. 0 on devices without a cutout, such as the Thor.
 */
final class DisplayCutoutInset {
    private DisplayCutoutInset() {}

    static double fraction(Context context) {
        if (context == null || Build.VERSION.SDK_INT < 29) return 0.0;
        try {
            DisplayManager manager = (DisplayManager) context.getSystemService(Context.DISPLAY_SERVICE);
            Display display = manager == null ? null : manager.getDisplay(Display.DEFAULT_DISPLAY);
            DisplayCutout cutout = display == null ? null : display.getCutout();
            if (cutout == null) return 0.0;
            int depth = Math.max(Math.max(cutout.getSafeInsetTop(), cutout.getSafeInsetBottom()),
                    Math.max(cutout.getSafeInsetLeft(), cutout.getSafeInsetRight()));
            Point size = new Point();
            display.getRealSize(size);
            int longSide = Math.max(size.x, size.y);
            return depth <= 0 || longSide <= 0 ? 0.0 : Math.min(0.12, depth / (double) longSide);
        } catch (RuntimeException unavailable) {
            return 0.0;
        }
    }
}
