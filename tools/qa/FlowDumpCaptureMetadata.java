package com.thorium.preview.game;

import java.io.*;
import java.lang.reflect.Field;

/** Diagnostic APK overlay only. No mutation of renderer fields or settings. */
public final class FlowDumpCaptureMetadata {
    private static long value(Object owner,String name) {
        try {Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return ((Number)f.get(owner)).longValue();}
        catch(ReflectiveOperationException e){throw new IllegalStateException("Capture identity unavailable",e);}
    }
    public static boolean burst(Object owner) {
        if(!new File("/data/local/tmp/lucent-flowdump-contiguous").exists())return false;
        long left=value(owner,"activeLeftSequence"),right=value(owner,"activeRightSequence");
        return left>0 && right==left+1 && value(owner,"activeRightTimestampNs")>value(owner,"activeLeftTimestampNs");
    }
    public static void write(Object owner,File dump) throws IOException {
        try(PrintWriter out=new PrintWriter(new File(dump.getPath()+".json"))) {
            out.print("{");boolean comma=false;
            for(String suffix:new String[]{"Sequence","Submission","TimestampNs"}) {
                for(String side:new String[]{"Left","Right"}) {
                    if(comma)out.print(",");comma=true;
                    out.print("\""+side.toLowerCase()+suffix+"\":"+value(owner,"active"+side+suffix));
                }
            }
            out.println(",\"contiguousCapture\":"+burst(owner)+",\"timingQualified\":false}");
            if(out.checkError())throw new IOException("Capture metadata write failed");
        }
    }
}
