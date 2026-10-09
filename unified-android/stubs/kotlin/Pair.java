package kotlin;

/**
 * Eden's overlay model is Kotlin and its JNI cache resolves {@code kotlin/Pair}
 * with the field names the Kotlin compiler emits. Lucent has no Kotlin runtime,
 * so this supplies the shape Eden reads: two Object fields and the two-argument
 * constructor.
 *
 * <p>Declaring a type in the {@code kotlin} package is deliberate and narrow.
 * It exists only so Eden's {@code JNI_OnLoad} resolves; if Lucent ever links
 * the real Kotlin standard library this file must be deleted, because the two
 * definitions would collide.
 */
public final class Pair {
    public Object first;
    public Object second;

    public Pair(Object first, Object second) {
        this.first = first;
        this.second = second;
    }
}
