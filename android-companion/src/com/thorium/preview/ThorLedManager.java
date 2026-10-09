package com.thorium.preview;

import android.content.Context;
import android.os.IBinder;
import android.os.Parcel;
import android.provider.Settings;
import android.util.Log;

import java.lang.reflect.Method;
import java.util.Locale;

/**
 * Static-color controller for the AYN Thor/Odin joystick rings.
 *
 * The stock firmware exposes its privileged LED writer through PServerBinder.
 * The four segment nodes are also used by the GPLv3 Bifrost project
 * (https://github.com/Pollux-MoonBench/Bifrost). EmuFusion uses the exact static
 * value format shipped in the device's OdinSettings.apk and periodically
 * reasserts it; it does not capture the screen or run an animation loop.
 */
final class ThorLedManager {
    private static final String TAG = "LucentLeds";
    private static final String DEVICE_BRIGHTNESS_SETTING =
            "led_light_brightness_percent";
    private final Context context;
    private IBinder vendorBinder;
    private String lastColor = "";
    private int lastBrightness = -1;

    ThorLedManager(Context context) {
        this.context = context.getApplicationContext();
        connectVendorService();
    }

    private void connectVendorService() {
        try {
            Class<?> serviceManager = Class.forName("android.os.ServiceManager");
            Method getService = serviceManager.getDeclaredMethod("getService", String.class);
            vendorBinder = (IBinder) getService.invoke(null, "PServerBinder");
        } catch (Exception error) {
            vendorBinder = null;
            Log.i(TAG, "AYN LED service is not available on this device");
        }
    }

    boolean available() {
        if (vendorBinder == null || !vendorBinder.isBinderAlive()) connectVendorService();
        return vendorBinder != null;
    }

    synchronized boolean setColor(String requested, int requestedBrightness) {
        if (!available()) return false;
        String color = requested == null ? "" : requested.trim();
        if (color.startsWith("#")) color = color.substring(1);
        if (!color.matches("(?i)[0-9a-f]{6}")) return false;
        color = color.toLowerCase(Locale.US);

        float brightnessFactor = requestedBrightness < 0 ?
                deviceBrightnessFactor() :
                Math.max(0, Math.min(255, requestedBrightness)) / 255.0f;
        int brightness = Math.round(brightnessFactor * 255.0f);

        // Match the exact implementation in the Thor's installed
        // OdinSettings.apk: brightness is applied by scaling each RGB channel,
        // and the driver receives `segment-R:G:B` (not a fourth field).
        int red = Math.round(Integer.parseInt(color.substring(0, 2), 16) * brightnessFactor);
        int green = Math.round(Integer.parseInt(color.substring(2, 4), 16) * brightnessFactor);
        int blue = Math.round(Integer.parseInt(color.substring(4, 6), 16) * brightnessFactor);
        String value = red + ":" + green + ":" + blue;
        String command = "echo 1-" + value + " > /sys/class/sn3112l/led/brightness" +
                " && echo 2-" + value + " > /sys/class/sn3112l/led/brightness" +
                " && echo 1-" + value + " > /sys/class/sn3112r/led/brightness" +
                " && echo 2-" + value + " > /sys/class/sn3112r/led/brightness";

        Parcel data = Parcel.obtain();
        Parcel reply = Parcel.obtain();
        try {
            data.writeStringArray(new String[]{command, "1"});
            vendorBinder.transact(0, data, reply, IBinder.FLAG_ONEWAY);
            lastColor = color;
            lastBrightness = brightness;
            return true;
        } catch (Exception error) {
            Log.w(TAG, "Unable to update AYN joystick LEDs", error);
            return false;
        } finally {
            data.recycle();
            reply.recycle();
        }
    }

    synchronized int appliedBrightness() {
        return lastBrightness;
    }

    synchronized int rememberedDeviceBrightness() {
        return Math.round(deviceBrightnessFactor() * 255.0f);
    }

    private float deviceBrightnessFactor() {
        try {
            float value = Settings.System.getFloat(context.getContentResolver(),
                    DEVICE_BRIGHTNESS_SETTING, 0.5f);
            return Math.max(0.0f, Math.min(1.0f, value));
        } catch (Exception error) {
            Log.w(TAG, "Unable to read AYN LED brightness; using 10%", error);
            return 0.10f;
        }
    }
}
