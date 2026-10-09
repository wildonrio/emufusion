import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

/** Silent, fixed-rate AudioTrack control. No emulator core or app installation. */
public final class AudioSinkProbe {
    private static final int RATE = 48000;
    private static final int FRAMES_PER_TICK = 800;

    private static void report(AudioTrack track, long started, long written,
                               int tick, long maxLate) {
        long elapsed = System.nanoTime() - started;
        long head = Integer.toUnsignedLong(track.getPlaybackHeadPosition());
        System.out.println("{\"tick\":" + tick + ",\"elapsedNs\":" + elapsed
                + ",\"writtenFrames\":" + written + ",\"playbackHead\":" + head
                + ",\"underruns\":" + track.getUnderrunCount()
                + ",\"maxProducerLateNs\":" + maxLate + "}");
        System.out.flush();
    }

    public static void main(String[] args) throws Exception {
        int ticks = args.length == 0 ? 600 : Integer.parseInt(args[0]);
        if (ticks < 60 || ticks > 5400) throw new IllegalArgumentException("Unbounded probe");
        int minimum = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IllegalStateException("No valid minimum buffer");
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_GAME)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .setAudioFormat(new AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO).build())
                .setBufferSizeInBytes(Math.max(minimum, RATE / 2 * 4))
                .setTransferMode(AudioTrack.MODE_STREAM).build();
        try {
            if (track.getState() != AudioTrack.STATE_INITIALIZED)
                throw new IllegalStateException("AudioTrack not initialized");
            // Always silent. Enabling the host sink must not play game sounds.
            short[] silence = new short[FRAMES_PER_TICK * 2];
            long written = 0;
            for (int i = 0; i < 30; i++) {
                int accepted = track.write(silence, 0, silence.length, AudioTrack.WRITE_NON_BLOCKING);
                if (accepted != silence.length)
                    throw new IllegalStateException("Could not prime: " + accepted);
                written += accepted / 2;
            }
            System.out.println("{\"rate\":" + RATE + ",\"bufferFrames\":"
                    + track.getBufferSizeInFrames() + ",\"silenceOnly\":true}");
            long started = System.nanoTime();
            long maxLate = 0;
            track.play();
            report(track, started, written, 0, maxLate);
            for (int tick = 1; tick <= ticks; tick++) {
                long deadline = started + tick * 1_000_000_000L / 60;
                long left;
                while ((left = deadline - System.nanoTime()) > 0)
                    Thread.sleep(left / 1_000_000L, (int) (left % 1_000_000L));
                maxLate = Math.max(maxLate, System.nanoTime() - deadline);
                int offset = 0;
                while (offset < silence.length) {
                    int count = track.write(silence, offset, silence.length - offset,
                            AudioTrack.WRITE_BLOCKING);
                    if (count <= 0) throw new IllegalStateException("PCM write failed: " + count);
                    offset += count;
                    written += count / 2;
                }
                if (tick % 120 == 0) report(track, started, written, tick, maxLate);
            }
        } finally {
            System.out.println("{\"lifecycle\":\"stopping\"}");
            try {
                track.stop();
                System.out.println("{\"lifecycle\":\"stopped\"}");
            } finally {
                track.release();
                System.out.println("{\"lifecycle\":\"released\"}");
            }
        }
        // app_process starts Android service/Binder threads, unlike a plain JVM.
        // Exit explicitly only after confirming normal AudioTrack teardown.
        System.out.flush();
        System.exit(0);
    }
}
