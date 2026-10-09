package com.emufusion.rifebenchmark;

import android.graphics.PixelFormat;
import android.hardware.HardwareBuffer;
import android.media.Image;
import android.media.ImageReader;
import android.media.ImageWriter;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Two isolated inference slots; measures saturation, not presentation. */
public final class NativeRifePipelineProbe {
    private static final int WIDTH = Integer.getInteger("emufusion.probe.width", 256);
    private static final int HEIGHT = Integer.getInteger("emufusion.probe.height", 192);
    private static String allowedCpus() throws Exception {
        for(String line:Files.readAllLines(Paths.get("/proc/thread-self/status")))
            if(line.startsWith("Cpus_allowed_list:")) return line;
        throw new IllegalStateException("worker affinity status missing");
    }
    private static byte[] readTexture(int texture) {
        int[] fbo=new int[1]; android.opengl.GLES20.glGenFramebuffers(1,fbo,0);
        android.opengl.GLES20.glBindFramebuffer(android.opengl.GLES20.GL_FRAMEBUFFER,fbo[0]);
        android.opengl.GLES20.glFramebufferTexture2D(android.opengl.GLES20.GL_FRAMEBUFFER,
            android.opengl.GLES20.GL_COLOR_ATTACHMENT0,android.opengl.GLES20.GL_TEXTURE_2D,texture,0);
        if(android.opengl.GLES20.glCheckFramebufferStatus(android.opengl.GLES20.GL_FRAMEBUFFER)!=android.opengl.GLES20.GL_FRAMEBUFFER_COMPLETE)
            throw new IllegalStateException("held framebuffer incomplete");
        java.nio.ByteBuffer pixels=java.nio.ByteBuffer.allocateDirect(WIDTH*HEIGHT*4);
        android.opengl.GLES20.glReadPixels(0,0,WIDTH,HEIGHT,android.opengl.GLES20.GL_RGBA,android.opengl.GLES20.GL_UNSIGNED_BYTE,pixels);
        if(android.opengl.GLES20.glGetError()!=android.opengl.GLES20.GL_NO_ERROR) throw new IllegalStateException("held readback failed");
        byte[] bytes=new byte[WIDTH*HEIGHT*4]; pixels.get(bytes);
        android.opengl.GLES20.glBindFramebuffer(android.opengl.GLES20.GL_FRAMEBUFFER,0);
        android.opengl.GLES20.glDeleteFramebuffers(1,fbo,0);
        return bytes;
    }
    public static void main(String[] args) throws Exception {
        if(Boolean.getBoolean("emufusion.probe.workerCpu")) {
            final Throwable[] failure=new Throwable[1];
            Thread worker=new Thread(() -> {
                try {
                    Class.forName("com.emufusion.rifebenchmark.NativeRifeBridge");
                    String originalCpus=allowedCpus();
                    RuntimeException sentinel=new RuntimeException("expected worker scope exception");
                    try {
                        NativeRifeBridge.runPreparationWorker(() -> { throw sentinel; });
                        throw new IllegalStateException("worker exception swallowed");
                    } catch(RuntimeException expected) {
                        if(expected!=sentinel) throw expected;
                    }
                    String exceptionCpus=allowedCpus();
                    if(!originalCpus.equals(exceptionCpus))
                        throw new IllegalStateException("exception changed worker affinity: "+originalCpus+" -> "+exceptionCpus);
                    System.out.println("WORKER_EXCEPTION_RESTORATION=verified");
                    NativeRifeBridge.runPreparationWorker(() -> {
                        try { runProbe(args); }
                        catch(Exception error) { throw new RuntimeException(error); }
                    });
                    String completedCpus=allowedCpus();
                    if(!originalCpus.equals(completedCpus))
                        throw new IllegalStateException("completion changed worker affinity: "+originalCpus+" -> "+completedCpus);
                    System.out.println("WORKER_NORMAL_RESTORATION=verified");
                } catch(Throwable error) { failure[0]=error; }
            },"EmuFusion-RIFE-probe-worker");
            worker.start();
            worker.join();
            if(failure[0]!=null) {
                failure[0].printStackTrace(System.err);
                throw new IllegalStateException("worker probe failed",failure[0]);
            }
            return;
        }
        runProbe(args);
    }

    private static void runProbe(String[] args) throws Exception {
        String root=args[0];
        boolean paced=args.length>1 && args[1].equals("paced");
        int analysisWidth=args.length>2 ? Integer.parseInt(args[2]) : WIDTH;
        if (WIDTH < 1 || WIDTH > 1920 || HEIGHT < 1 || HEIGHT > 1080)
            throw new IllegalArgumentException("endpoint geometry");
        if (analysisWidth < 1 || analysisWidth > WIDTH ||
                (long) analysisWidth * HEIGHT % WIDTH != 0)
            throw new IllegalArgumentException("analysis aspect ratio");
        int analysisHeight=analysisWidth*HEIGHT/WIDTH;
        boolean alternate=args.length>3 && args[3].equals("alternate");
        int contextCount=args.length>4 ? Integer.parseInt(args[4]) : 2;
        if(contextCount!=1 && contextCount!=2) throw new IllegalArgumentException("context count");
        int inputHz=args.length>5 ? Integer.parseInt(args[5]) : 60;
        if(inputHz!=30 && inputHz!=60) throw new IllegalArgumentException("input Hz");
        long arrivalPeriod=Math.round(1_000_000_000.0/inputHz);
        boolean shared=args.length>6 && args[6].equals("shared");
        boolean recycle=args.length>7 && args[7].equals("recycle");
        boolean verifyUploads=!(args.length>8 && args[8].equals("no-readback"));
        boolean asyncProducer=args.length>9 && args[9].equals("async-producer");
        boolean queuedProducer=args.length>10 && args[10].equals("queued");
        boolean adjacent=args.length>10 && args[10].equals("adjacent");
        boolean adjacentQueued=args.length>11 && args[11].equals("adjacent-queued");
        boolean independentInputs=Boolean.getBoolean("emufusion.probe.independentInputs");
        if(independentInputs && (!adjacentQueued || !paced)) throw new IllegalArgumentException("independent inputs require paced adjacent queue");
        int jobs=args.length>12 ? Integer.parseInt(args[12]) : 140;
        boolean holdOutputs=args.length>13 && args[13].equals("hold-output");
        boolean verifyHeld=args.length>14 && args[14].equals("verify-held");
        if(jobs<140 || jobs>2420) throw new IllegalArgumentException("job bound");
        long usage=HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE | HardwareBuffer.USAGE_GPU_COLOR_OUTPUT;
        try(ImageReader reader=ImageReader.newInstance(WIDTH,HEIGHT,PixelFormat.RGBA_8888,recycle ? 9 : 5,usage);
            NativeRifeGpuInputs producer=new NativeRifeGpuInputs(reader);
            Image left=producer.upload(reader,Files.readAllBytes(Paths.get(root,"left.rgba")),1_000_000_000L);
            Image right=producer.upload(reader,Files.readAllBytes(Paths.get(root,"right.rgba")),1_033_333_334L);
            Image following=Files.exists(Paths.get(root,"following.rgba")) ? producer.upload(reader,Files.readAllBytes(Paths.get(root,"following.rgba")),1_050_000_001L) : null;
            Image alternateLeft=alternate ? producer.upload(reader,Files.readAllBytes(Paths.get(root,"alternate-left.rgba")),2_000_000_000L) : null;
            Image alternateRight=alternate ? producer.upload(reader,Files.readAllBytes(Paths.get(root,"alternate-right.rgba")),2_033_333_334L) : null;
            NativeRifeBridge first=new NativeRifeBridge(root,0,1);
            NativeRifeBridge second=contextCount==2 ? (shared ? new NativeRifeBridge(first) : new NativeRifeBridge(root,0,1)) : null) {
            System.out.println("MODEL_CAPABILITIES="+first.capabilitiesJson());
            NativeRifeBridge[] bridges=contextCount==2 ? new NativeRifeBridge[]{first,second} : new NativeRifeBridge[]{first};
            Image[] lefts={left,alternateLeft}, rights={right,alternateRight};
            Image[] ownedLeft=new Image[2], ownedRight=new Image[2];
            byte[][] leftBytes={Files.readAllBytes(Paths.get(root,"left.rgba")),alternate ? Files.readAllBytes(Paths.get(root,"alternate-left.rgba")) : null};
            byte[][] rightBytes={Files.readAllBytes(Paths.get(root,"right.rgba")),alternate ? Files.readAllBytes(Paths.get(root,"alternate-right.rgba")) : null};
            int cacheHits=0;
            boolean[] imported={false,false};
            java.util.ArrayList<Image> streamImages=new java.util.ArrayList<>();
            Image latestStreamImage=left;
            byte[][] streamBytes={leftBytes[0],rightBytes[0],rightBytes[1]};
            for(NativeRifeBridge bridge:bridges) {
                System.out.println("TRANSPORT="+bridge.createPrivateOutputTransport(WIDTH,HEIGHT));
                try(HardwareBuffer a=left.getHardwareBuffer(); HardwareBuffer b=right.getHardwareBuffer()) {
                    bridge.prepareHardwareBufferEndpoint(a,WIDTH,HEIGHT);
                    bridge.prepareHardwareBufferEndpoint(b,WIDTH,HEIGHT);
                }
                if(following!=null) try(HardwareBuffer next=following.getHardwareBuffer()) {
                    bridge.prepareHardwareBufferEndpoint(next,WIDTH,HEIGHT);
                }
                if(alternate) try(HardwareBuffer a=alternateLeft.getHardwareBuffer(); HardwareBuffer b=alternateRight.getHardwareBuffer()) {
                    bridge.prepareHardwareBufferEndpoint(a,WIDTH,HEIGHT);
                    bridge.prepareHardwareBufferEndpoint(b,WIDTH,HEIGHT);
                }
            }
            long middle=left.getTimestamp()+(right.getTimestamp()-left.getTimestamp())/2;
            // Explicitly model the app's invisible private-output warm-up.
            // Keep this outside the arrival clock, report its complete cost,
            // and retain the default cold run as a separate diagnostic.
            if(Boolean.getBoolean("emufusion.probe.prewarm")) {
                long warmStart=System.nanoTime();
                long warmDeadline=warmStart+5_000_000_000L;
                for(int slot=0;slot<bridges.length;slot++) {
                    NativeRifeBridge warmBridge=bridges[slot];
                    long identity=9000000L+slot;
                    if(warmBridge.prepareHardwareBufferRifeOutput(left,right,null,
                            WIDTH,HEIGHT,analysisWidth,analysisHeight,middle,identity)!=1)
                        throw new IllegalStateException("prewarm submission failed");
                    while(warmBridge.pollPreparedHardwareBufferRifeOutput(identity)==null) {
                        if(System.nanoTime()>warmDeadline)
                            throw new IllegalStateException("prewarm deadline");
                        Thread.sleep(1);
                    }
                    if(!warmBridge.discardPreparedHardwareBufferRifeOutput(identity))
                        throw new IllegalStateException("prewarm retirement failed");
                }
                System.out.println("PREWARM,contexts="+bridges.length+",elapsedNs="+
                        (System.nanoTime()-warmStart));
            }
            long[] active={0,0}, start={0,0}, record={0,0};
            long[] firstAttempt={0,0}, fenceRetries={0,0};
            long[] uploadStart={0,0}, acquiredAt={0,0}, importDuration={0,0};
            long deadline=System.nanoTime()+55_000_000_000L;
            int submitted=0, completed=0;
            long proofAnalysisTotalNs=0, proofAnalysisMaxNs=0, proofAnalysisSamples=0;
            int produced=0;
            java.util.HashMap<Long,Image> sourceQueue=new java.util.HashMap<>();
            java.util.HashMap<Long,Long> queuedAt=new java.util.HashMap<>(), receivedAt=new java.util.HashMap<>();
            sourceQueue.put(0L,left);
            long origin=System.nanoTime();
            int traceBudget=32;
            long pendingUploadTimestamp=0L;
            java.util.ArrayList<long[]> heldOutputs=new java.util.ArrayList<>();
            int heldMaximum=0, lateReady=0;
            java.util.HashMap<Long,byte[]> heldPixels=new java.util.HashMap<>();
            int heldVerified=0;
            while(completed<jobs || !heldOutputs.isEmpty()) {
                if(System.nanoTime()>deadline) throw new IllegalStateException("probe deadline");
                boolean progress=false;
                java.util.Iterator<long[]> held=heldOutputs.iterator();
                while(held.hasNext()) {
                    long[] output=held.next();
                    if(System.nanoTime()<output[3]) continue;
                    if(verifyHeld) {
                        if(!java.util.Arrays.equals(heldPixels.remove(output[0]),readTexture((int)output[2])))
                            throw new IllegalStateException("held output overwritten "+output[0]);
                        heldVerified++;
                    }
                    bridges[(int)output[1]].releaseBoundHardwareBufferRifeOutput(output[0],false);
                    bridges[(int)output[1]].pollBoundHardwareBufferRifeOutputs();
                    android.opengl.GLES20.glDeleteTextures(1,new int[]{(int)output[2]},0);
                    held.remove(); progress=true;
                }
                if(queuedProducer || adjacentQueued) {
                    if(traceBudget>0) { System.out.println("STAGE acquire begin active="+active[0]+","+active[1]); traceBudget--; }
                    Image acquired;
                    while((acquired=reader.acquireNextImage())!=null) {
                        if(acquired.getTimestamp()!=pendingUploadTimestamp) {
                            acquired.close(); throw new IllegalStateException("unexpected queued upload timestamp");
                        }
                        pendingUploadTimestamp=0L;
                        if(independentInputs) {
                            long sequence=(acquired.getTimestamp()-1_000_000_000L)/arrivalPeriod;
                            if(sequence<1 || sequence>produced || sourceQueue.containsKey(sequence))
                                throw new IllegalStateException("independent source identity");
                            sourceQueue.put(sequence,acquired);
                            receivedAt.put(sequence,System.nanoTime());
                            latestStreamImage=acquired; streamImages.add(acquired);
                            progress=true; continue;
                        }
                        if(adjacentQueued) {
                            boolean matched=false;
                            for(int index=0;index<contextCount;index++) if(active[index]<0 &&
                                    acquired.getTimestamp()==1_000_000_000L-active[index]*arrivalPeriod && ownedRight[index]==null) {
                                ownedRight[index]=acquired; latestStreamImage=acquired;
                                acquiredAt[index]=System.nanoTime();
                                streamImages.add(acquired); matched=true; break;
                            }
                            if(!matched) { acquired.close(); throw new IllegalStateException("unmatched adjacent endpoint"); }
                            progress=true; continue;
                        }
                        if(traceBudget>0) { System.out.println("STAGE acquired timestamp="+acquired.getTimestamp()); traceBudget--; }
                        boolean matched=false;
                        for(int index=0;index<contextCount;index++) if(active[index]<0) {
                            long timestamp=3_000_000_000L-active[index]*40_000_000L;
                            if(acquired.getTimestamp()==timestamp && ownedLeft[index]==null) {
                                ownedLeft[index]=acquired; matched=true; break;
                            }
                            if(acquired.getTimestamp()==timestamp+33_333_334L && ownedRight[index]==null) {
                                ownedRight[index]=acquired; matched=true; break;
                            }
                        }
                        if(!matched) { acquired.close(); throw new IllegalStateException("unmatched producer image"); }
                        progress=true;
                    }
                    if(traceBudget>0) { System.out.println("STAGE acquire end"); traceBudget--; }
                }
                if(independentInputs && produced<jobs && produced-submitted<1 && pendingUploadTimestamp==0L &&
                        System.nanoTime()>=origin+produced*arrivalPeriod) {
                    long sequence=++produced;
                    queuedAt.put(sequence,System.nanoTime());
                    pendingUploadTimestamp=1_000_000_000L+sequence*arrivalPeriod;
                    producer.upload(reader,streamBytes[(int)(sequence%3)],pendingUploadTimestamp,false,false,true);
                    progress=true;
                }
                for(int slot=0;slot<contextCount;++slot) {
                    if(active[slot]>0) {
                        NativeRifeBridge.PreparedOutput output=bridges[slot].pollPreparedHardwareBufferRifeOutput(active[slot]);
                        if(output!=null) {
                            long end=System.nanoTime();
                            int pair=adjacent ? (int)((active[slot]-1)%3) : (alternate ? (int)((active[slot]-1)/2%2) : 0);
                            NativeRifeBridge.ContentProof proof=output.contentProof;
                            if(active[slot]>20) {
                                proofAnalysisTotalNs+=proof.analysisWallNs;
                                proofAnalysisMaxNs=Math.max(proofAnalysisMaxNs,proof.analysisWallNs);
                                proofAnalysisSamples++;
                            }
                            System.out.println("CONTENT,"+active[slot]+","+slot+","+pair+","+proof.leftChecksum+","+proof.rightChecksum+","+proof.outputChecksum);
                            if(holdOutputs) {
                                int[] texture=new int[1]; android.opengl.GLES20.glGenTextures(1,texture,0);
                                if(!bridges[slot].bindPreparedHardwareBufferRifeOutput(active[slot],texture[0]))
                                    throw new IllegalStateException("ready output bind failed");
                                if(verifyHeld) heldPixels.put(active[slot],readTexture(texture[0]));
                                long due=origin+(active[slot]-1)*arrivalPeriod+66_666_668L;
                                if(active[slot]>20 && end>due) lateReady++;
                                if(verifyHeld) due=Math.max(due,System.nanoTime()+33_333_334L);
                                heldOutputs.add(new long[]{active[slot],slot,texture[0],due});
                                heldMaximum=Math.max(heldMaximum,heldOutputs.size());
                                if(heldMaximum>6) throw new IllegalStateException("ready queue exceeded output pool");
                            } else if(!bridges[slot].discardPreparedHardwareBufferRifeOutput(active[slot]))
                                throw new IllegalStateException("completed output not retired");
                            if(recycle) {
                                if(!adjacent) { ownedLeft[slot].close(); ownedRight[slot].close(); }
                                ownedLeft[slot]=null; ownedRight[slot]=null;
                                if(adjacent) {
                                    java.util.Iterator<Image> images=streamImages.iterator();
                                    while(images.hasNext()) {
                                        Image candidate=images.next();
                                        if(candidate!=latestStreamImage && candidate!=ownedLeft[0] && candidate!=ownedLeft[1] &&
                                                candidate!=ownedRight[0] && candidate!=ownedRight[1] &&
                                                (!independentInputs || candidate.getTimestamp()<1_000_000_000L+submitted*arrivalPeriod)) {
                                            if(independentInputs) sourceQueue.remove((candidate.getTimestamp()-1_000_000_000L)/arrivalPeriod);
                                            candidate.close(); images.remove();
                                        }
                                    }
                                }
                            }
                            System.out.println("PIPE,"+active[slot]+","+slot+","+start[slot]+","+record[slot]+","+end+","+output.gpuWorkNs);
                            active[slot]=0; completed++; progress=true;
                        }
                    }
                    long arrival=origin+submitted*arrivalPeriod;
                    if(active[slot]==0 && submitted<jobs && (!paced || System.nanoTime()>=arrival) &&
                            (!independentInputs || slot==submitted%contextCount) &&
                            (independentInputs ? sourceQueue.containsKey((long)submitted+1) : (!adjacentQueued || pendingUploadTimestamp==0L))) {
                        long sequence=submitted+1;
                        int pair=alternate ? submitted/2%2 : 0;
                        Image inputLeft=lefts[pair], inputRight=rights[pair];
                        if(independentInputs) {
                            ownedLeft[slot]=sourceQueue.get(sequence-1);
                            ownedRight[slot]=sourceQueue.get(sequence);
                            if(ownedLeft[slot]==null || ownedRight[slot]==null) throw new IllegalStateException("missing adjacent input");
                            uploadStart[slot]=queuedAt.remove(sequence);
                            acquiredAt[slot]=receivedAt.remove(sequence);
                            importDuration[slot]=0;
                        } else if(adjacent) {
                            uploadStart[slot]=System.nanoTime();
                            acquiredAt[slot]=0; importDuration[slot]=0;
                            ownedLeft[slot]=latestStreamImage;
                            ownedRight[slot]=producer.upload(reader,streamBytes[(int)(sequence%3)],
                                1_000_000_000L+sequence*arrivalPeriod,false,false,adjacentQueued);
                            if(adjacentQueued) pendingUploadTimestamp=1_000_000_000L+sequence*arrivalPeriod;
                            else { latestStreamImage=ownedRight[slot]; streamImages.add(latestStreamImage); }
                        } else if(recycle && !queuedProducer) {
                            long timestamp=3_000_000_000L+sequence*40_000_000L;
                            inputLeft=ownedLeft[slot]=producer.upload(reader,leftBytes[pair],timestamp,verifyUploads,!asyncProducer,queuedProducer);
                            inputRight=ownedRight[slot]=producer.upload(reader,rightBytes[pair],timestamp+33_333_334L,verifyUploads,!asyncProducer,queuedProducer);
                            imported[slot]=false;
                        }
                        if(paced) System.out.println("ARRIVAL,"+sequence+","+arrival);
                        // Negative identity owns uploaded Images but no submitted GPU job.
                        active[slot]=-sequence; submitted++; progress=true;
                        firstAttempt[slot]=0; fenceRetries[slot]=0;
                        imported[slot]=false;
                    }
                    if(active[slot]<0) {
                        long sequence=-active[slot];
                        int pair=alternate ? (int)((sequence-1)/2%2) : 0;
                        Image inputLeft=recycle ? ownedLeft[slot] : lefts[pair];
                        Image inputRight=recycle ? ownedRight[slot] : rights[pair];
                        if(queuedProducer && (inputLeft==null || inputRight==null) && pendingUploadTimestamp==0L) {
                            long timestamp=3_000_000_000L+sequence*40_000_000L;
                            boolean uploadLeft=inputLeft==null;
                            pendingUploadTimestamp=timestamp+(uploadLeft ? 0L : 33_333_334L);
                            producer.upload(reader,uploadLeft ? leftBytes[pair] : rightBytes[pair],
                                pendingUploadTimestamp,false,false,true);
                            progress=true;
                        }
                        if(inputLeft==null || inputRight==null) continue;
                        if(recycle && !imported[slot]) {
                            long importBegin=System.nanoTime();
                            if(queuedProducer) System.out.println("STAGE import "+sequence);
                            try(HardwareBuffer a=inputLeft.getHardwareBuffer(); HardwareBuffer b=inputRight.getHardwareBuffer()) {
                                if(bridges[slot].isHardwareBufferEndpointPrepared(a,WIDTH,HEIGHT)) cacheHits++;
                                if(bridges[slot].isHardwareBufferEndpointPrepared(b,WIDTH,HEIGHT)) cacheHits++;
                                bridges[slot].prepareHardwareBufferEndpoint(a,WIDTH,HEIGHT);
                                bridges[slot].prepareHardwareBufferEndpoint(b,WIDTH,HEIGHT);
                            }
                            imported[slot]=true;
                            importDuration[slot]=System.nanoTime()-importBegin;
                            if(queuedProducer) System.out.println("STAGE imported "+sequence);
                        }
                        long inputMiddle=inputLeft.getTimestamp()+(inputRight.getTimestamp()-inputLeft.getTimestamp())/2;
                        start[slot]=System.nanoTime();
                        if(firstAttempt[slot]==0) firstAttempt[slot]=start[slot];
                        if(queuedProducer && traceBudget>0) { System.out.println("STAGE prepare "+sequence); traceBudget--; }
                        int accepted=bridges[slot].prepareHardwareBufferRifeOutput(inputLeft,inputRight,
                                Boolean.getBoolean("emufusion.probe.timeFollowing") ? following : null,
                                WIDTH,HEIGHT,analysisWidth,analysisHeight,inputMiddle,sequence);
                        if(accepted==0 && asyncProducer) { fenceRetries[slot]++; continue; }
                        if(accepted!=1) throw new IllegalStateException("idle slot did not accept work");
                        record[slot]=System.nanoTime()-start[slot];
                        System.out.println("INPUT_READINESS,"+sequence+","+slot+","+fenceRetries[slot]+","+(start[slot]-firstAttempt[slot]));
                        if(adjacentQueued) System.out.println("INPUT_STAGES,"+sequence+","+(acquiredAt[slot]-uploadStart[slot])+","+importDuration[slot]+","+(start[slot]-acquiredAt[slot]));
                        active[slot]=sequence; progress=true;
                    }
                }
                if(!progress) Thread.sleep(0,100000);
            }
            System.out.println("PIPELINE_COMPLETED="+completed);
            System.out.println("CONTENT_ANALYSIS,samples="+proofAnalysisSamples+
                    ",totalNs="+proofAnalysisTotalNs+",maxNs="+proofAnalysisMaxNs);
            if(holdOutputs) System.out.println("HELD_OUTPUTS,"+heldMaximum+","+lateReady);
            if(verifyHeld) System.out.println("HELD_PIXELS_VERIFIED="+heldVerified);
            for(Image image:streamImages) image.close();
            if(recycle) System.out.println("RECYCLED_IMPORT_HITS="+cacheHits);
            NativeRifeBridge captureBridge=first;
            if(shared) {
                first.close();
                captureBridge=second;
                System.out.println("SURVIVING_MODEL_CAPABILITIES="+second.capabilitiesJson());
            }
            // Separate image-evidence job: excluded from every PIPE timing row.
            // Capture identity is scoped to a drained context, never a timed row.
            if(captureBridge.prepareHardwareBufferRifeOutput(left,right,following,WIDTH,HEIGHT,analysisWidth,analysisHeight,middle,141)!=1)
                throw new IllegalStateException("capture job rejected");
            long captureDeadline=System.nanoTime()+5_000_000_000L;
            while(captureBridge.pollPreparedHardwareBufferRifeOutput(141)==null) {
                if(System.nanoTime()>captureDeadline) throw new IllegalStateException("capture timeout");
                Thread.sleep(1);
            }
            int[] texture=new int[1], fbo=new int[1];
            android.opengl.GLES20.glGenTextures(1,texture,0);
            if(!captureBridge.bindPreparedHardwareBufferRifeOutput(141,texture[0]))
                throw new IllegalStateException("capture bind failed");
            android.opengl.GLES20.glGenFramebuffers(1,fbo,0);
            android.opengl.GLES20.glBindFramebuffer(android.opengl.GLES20.GL_FRAMEBUFFER,fbo[0]);
            android.opengl.GLES20.glFramebufferTexture2D(android.opengl.GLES20.GL_FRAMEBUFFER,
                android.opengl.GLES20.GL_COLOR_ATTACHMENT0,android.opengl.GLES20.GL_TEXTURE_2D,texture[0],0);
            if(android.opengl.GLES20.glCheckFramebufferStatus(android.opengl.GLES20.GL_FRAMEBUFFER)!=android.opengl.GLES20.GL_FRAMEBUFFER_COMPLETE)
                throw new IllegalStateException("capture framebuffer incomplete");
            java.nio.ByteBuffer pixels=java.nio.ByteBuffer.allocateDirect(WIDTH*HEIGHT*4);
            android.opengl.GLES20.glReadPixels(0,0,WIDTH,HEIGHT,android.opengl.GLES20.GL_RGBA,android.opengl.GLES20.GL_UNSIGNED_BYTE,pixels);
            if(android.opengl.GLES20.glGetError()!=android.opengl.GLES20.GL_NO_ERROR)
                throw new IllegalStateException("capture readback failed");
            byte[] raw=new byte[WIDTH*HEIGHT*4]; pixels.get(raw);
            Files.write(Paths.get(root,"private-output-storage.rgba"),raw);
            // Vulkan storage rows are top-down; export the established bottom-up format.
            byte[] bottomUp=new byte[raw.length];
            for(int y=0;y<HEIGHT;++y) System.arraycopy(raw,y*WIDTH*4,bottomUp,(HEIGHT-1-y)*WIDTH*4,WIDTH*4);
            Files.write(Paths.get(root,"generated.rgba"),bottomUp);
            android.opengl.GLES20.glBindFramebuffer(android.opengl.GLES20.GL_FRAMEBUFFER,0);
            captureBridge.releaseBoundHardwareBufferRifeOutput(141,false);
            captureBridge.pollBoundHardwareBufferRifeOutputs();
            android.opengl.GLES20.glDeleteFramebuffers(1,fbo,0);
            android.opengl.GLES20.glDeleteTextures(1,texture,0);
            System.out.println("POST_TIMING_CAPTURE=141");
            // Exercise teardown with submitted GPU reads while Images are still owned.
            long closingSequence=jobs+2L;
            if(captureBridge.prepareHardwareBufferRifeOutput(left,right,null,WIDTH,HEIGHT,analysisWidth,analysisHeight,middle,closingSequence)!=1)
                throw new IllegalStateException("shutdown job rejected");
            boolean pendingAtClose=captureBridge.pollPreparedHardwareBufferRifeOutput(closingSequence)==null;
            long closeStart=System.nanoTime();
            org.json.JSONObject drain=new org.json.JSONObject(captureBridge.closePresentationSurface());
            if(!drain.getBoolean("closed")) throw new IllegalStateException("shutdown GPU drain failed");
            System.out.println("INFLIGHT_CLOSE,"+pendingAtClose+","+(System.nanoTime()-closeStart));
        }
    }
}
