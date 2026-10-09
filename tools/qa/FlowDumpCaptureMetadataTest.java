package com.thorium.preview.game;
import java.io.*;
import java.nio.file.*;
public final class FlowDumpCaptureMetadataTest {
    static final class Owner {
        private long activeLeftSequence=41,activeRightSequence=42;
        private int activeLeftSubmission=100,activeRightSubmission=101;
        private long activeLeftTimestampNs=1000,activeRightTimestampNs=2000;
    }
    public static void main(String[] args) throws Exception {
        Path directory=Files.createTempDirectory("flow-metadata-test-");
        Path file=directory.resolve("sample.bin.json");
        try {
            FlowDumpCaptureMetadata.write(new Owner(),directory.resolve("sample.bin").toFile());
            String result=new String(Files.readAllBytes(file),"UTF-8");
            for(String expected:new String[]{"\"leftSequence\":41","\"rightSequence\":42",
                "\"leftSubmission\":100","\"rightSubmission\":101",
                "\"leftTimestampNs\":1000","\"rightTimestampNs\":2000","\"timingQualified\":false"})
                if(!result.contains(expected))throw new AssertionError(result);
            System.out.println("METADATA_FIELD_IDENTITY_PASS");
        } finally {Files.deleteIfExists(file);Files.delete(directory);}
    }
}
