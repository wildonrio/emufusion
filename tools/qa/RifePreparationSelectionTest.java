import java.lang.reflect.*;
import java.util.LinkedHashMap;
import com.thorium.lucent.video.FrameGenerationPreparationRequest;
import com.thorium.lucent.video.FrameGenerationPresentationRequest;

/** Executes actual transport selection methods without initializing Android/JNI.
 * Constructor bypass is test-only; no GPU/reset behavior is simulated as passed.
 */
public final class RifePreparationSelectionTest {
    static Class<?> transport;
    static Object instance;
    static Field field(String name) throws Exception {
        Field f=transport.getDeclaredField(name); f.setAccessible(true); return f;
    }
    static FrameGenerationPreparationRequest request(long left) {
        return FrameGenerationPreparationRequest.between(1,1,left,left*1000,
            left+1,(left+1)*1000,left*1000+500,256,192,
            FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
    }
    static Object prepared(FrameGenerationPreparationRequest request) throws Exception {
        Class<?> type=Class.forName("com.thorium.preview.game.RifePresentationTransport$PreparedPresentation");
        Constructor<?> ctor=type.getDeclaredConstructors()[0]; ctor.setAccessible(true);
        return ctor.newInstance(null,request,request.rightSequence(),0L,0L,1L);
    }
    static void check(boolean value,String message) {
        if(!value) throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        transport=Class.forName("com.thorium.preview.game.RifePresentationTransport");
        Class<?> unsafeType=Class.forName("sun.misc.Unsafe");
        Field singleton=unsafeType.getDeclaredField("theUnsafe"); singleton.setAccessible(true);
        instance=unsafeType.getMethod("allocateInstance",Class.class).invoke(singleton.get(null),transport);
        field("appOwnedPresentation").setBoolean(instance,true);
        field("retained").set(instance,new LinkedHashMap<>());
        field("boundAppOwnedOutputs").set(instance,new LinkedHashMap<>());
        LinkedHashMap<Long,Object> ready=new LinkedHashMap<>();
        field("readyOutputs").set(instance,ready);
        Method select=transport.getDeclaredMethod("retireStalePreparation",FrameGenerationPreparationRequest.class);
        select.setAccessible(true);
        Object a=prepared(request(1)), b=prepared(request(2)), c=prepared(request(3));
        field("preparedPresentation").set(instance,a);
        check((Boolean)select.invoke(instance,request(2)),"second pair rejected");
        check(field("preparedPresentation").get(instance)==null && field("queuedPreparation").get(instance)==a,"first pair lost");
        field("preparedPresentation").set(instance,b);
        check(!(Boolean)select.invoke(instance,request(3)),"third pair must backpressure");
        check(field("preparedPresentation").get(instance)==b && field("queuedPreparation").get(instance)==a,"backpressure mutated jobs");
        check((Boolean)select.invoke(instance,request(1)),"first pair cannot be selected");
        check(field("preparedPresentation").get(instance)==a && field("queuedPreparation").get(instance)==b,"selection mismatched ownership");
        field("preparedPresentation").set(instance,null); // Simulate consumer transfer, not native completion.
        check((Boolean)select.invoke(instance,request(3)),"free slot not usable");
        field("preparedPresentation").set(instance,c);
        Method references=transport.getDeclaredMethod("nativeReferences",long.class); references.setAccessible(true);
        check((Boolean)references.invoke(instance,2L),"queued left endpoint released");
        check((Boolean)references.invoke(instance,4L),"selected right endpoint released");
        check(!(Boolean)references.invoke(instance,9L),"unrelated endpoint retained");
        Object future=prepared(request(8)); ready.put(9L,future);
        Method cached=transport.getDeclaredMethod("hasReadyOutput",FrameGenerationPreparationRequest.class); cached.setAccessible(true);
        check((Boolean)cached.invoke(instance,request(8)),"ready cache lost exact request");
        check(!(Boolean)cached.invoke(instance,request(7)),"ready cache returned wrong pair");
        check((Boolean)references.invoke(instance,9L),"cached endpoint released before consumption");
        Method choose=transport.getDeclaredMethod("choosePreparationSlot",int.class,int.class,boolean.class,boolean.class);
        choose.setAccessible(true);
        check((Integer)choose.invoke(null,3,0,false,false)==1,"full primary blocks free secondary");
        check((Integer)choose.invoke(null,0,3,false,false)==0,"full secondary blocks free primary");
        check((Integer)choose.invoke(null,3,3,false,false)==-1,"exhausted output pools accepted work");
        check((Integer)choose.invoke(null,0,0,true,true)==-1,"busy inference slots accepted work");
        check((Integer)choose.invoke(null,0,2,true,false)==1,"queued primary job overwritten");
        check((Integer)choose.invoke(null,3,0,false,true)==-1,"busy secondary selected despite full primary");
        check((Integer)choose.invoke(null,2,1,false,false)==1,"output pressure not balanced");
        System.out.println("PASS actual transport: selection, backpressure, queued endpoint ownership");
    }
}
