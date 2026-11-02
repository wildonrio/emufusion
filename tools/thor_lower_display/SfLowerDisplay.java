import android.graphics.Rect;
import android.os.IBinder;
import android.view.SurfaceControl;
import java.lang.reflect.Method;

/**
 * Shell-uid helper for tools/thor_lower_display_repair.py (run with app_process, never
 * packaged in the app).
 *
 *   size PHYSICAL_ID WIDTH HEIGHT    SurfaceFlinger display size (framebuffer and display
 *                                    space) for one physical display.
 *   client-frame LAYER_STACK HOLD_MS Show a 2x2, 2%-alpha effect layer that requests
 *                                    background blur, so SurfaceFlinger GPU-composes at
 *                                    least one frame and the HWC receives the resized
 *                                    framebuffer as its client target. Removed afterwards.
 */
public class SfLowerDisplay {
    public static void main(String[] args) throws Exception {
        if (args.length == 4 && args[0].equals("size")) {
            setSize(Long.parseUnsignedLong(args[1]), Integer.parseInt(args[2]),
                    Integer.parseInt(args[3]));
        } else if (args.length == 3 && args[0].equals("client-frame")) {
            clientFrame(Integer.parseInt(args[1]), Long.parseLong(args[2]));
        } else {
            System.err.println("usage: size PHYSICAL_ID W H | client-frame LAYER_STACK HOLD_MS");
            System.exit(2);
        }
    }

    private static void setSize(long physicalId, int width, int height) throws Exception {
        Method get = SurfaceControl.class.getMethod("getPhysicalDisplayToken", long.class);
        IBinder token = (IBinder) get.invoke(null, physicalId);
        if (token == null) throw new IllegalStateException("no display token for " + physicalId);
        SurfaceControl.Transaction t = new SurfaceControl.Transaction();
        SurfaceControl.Transaction.class
                .getMethod("setDisplaySize", IBinder.class, int.class, int.class)
                .invoke(t, token, width, height);
        t.apply();
        System.out.println("display size " + physicalId + " " + width + "x" + height);
    }

    private static void clientFrame(int layerStack, long holdMs) throws Exception {
        SurfaceControl.Builder builder =
                new SurfaceControl.Builder().setName("emufusion-lower-display-repair");
        Method effect;
        try {
            effect = SurfaceControl.Builder.class.getMethod("setEffectLayer");
        } catch (NoSuchMethodException older) {
            effect = SurfaceControl.Builder.class.getMethod("setColorLayer");
        }
        effect.invoke(builder);
        SurfaceControl layer = builder.build();
        Class<?> tc = SurfaceControl.Transaction.class;
        SurfaceControl.Transaction t = new SurfaceControl.Transaction();
        tc.getMethod("setLayerStack", SurfaceControl.class, int.class).invoke(t, layer, layerStack);
        t.setLayer(layer, Integer.MAX_VALUE);
        t.setCrop(layer, new Rect(0, 0, 2, 2));
        tc.getMethod("setColor", SurfaceControl.class, float[].class)
                .invoke(t, layer, new float[] {0f, 0f, 0f});
        t.setAlpha(layer, 0.02f);
        tc.getMethod("setBackgroundBlurRadius", SurfaceControl.class, int.class)
                .invoke(t, layer, 1);
        t.setVisibility(layer, true);
        t.apply();
        try {
            Thread.sleep(holdMs);
        } finally {
            SurfaceControl.Transaction done = new SurfaceControl.Transaction();
            done.reparent(layer, null);
            done.apply();
            layer.release();
        }
        System.out.println("client frame on layer stack " + layerStack);
    }
}
