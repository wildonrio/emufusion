package com.thorium.preview;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.os.Build;
import java.util.List;

/** Matches a local, unfinished session to an OS-confirmed exit. Never reads traces. */
final class PrivateDiagnosticsExitRecovery {
    interface History { String bucket(int pid, long started, long before); }

    static final class Marker {
        final int build, pid;
        final String system;
        final long started;

        private Marker(int build, String system, int pid, long started) {
            this.build = build;
            this.system = system;
            this.pid = pid;
            this.started = started;
        }

        static Marker create(int build, String system, int pid, long started) {
            if (pid <= 0 || started <= 0 ||
                    PrivateDiagnosticReport.create(build, system, "engine_ready", "ok") == null) return null;
            return new Marker(build, system, pid, started);
        }

        String key() { return build + "|" + system + "|" + pid + "|" + started; }

        static Marker parse(String key) {
            if (key == null || key.length() > 100) return null;
            String[] parts = key.split("\\|", -1);
            if (parts.length != 4) return null;
            for (int index : new int[]{0, 2, 3}) {
                if (!parts[index].matches("[1-9][0-9]{0,18}")) return null;
            }
            try {
                return create(Integer.parseInt(parts[0]), parts[1],
                        Integer.parseInt(parts[2]), Long.parseLong(parts[3]));
            } catch (NumberFormatException ignored) { return null; }
        }

        PrivateDiagnosticReport recover(History history, long before) {
            if (before <= started) return null; // Clock reversal/ambiguous time: do not guess.
            String bucket;
            try { bucket = history.bucket(pid, started, before); }
            catch (RuntimeException ignored) { return null; }
            if (!"java".equals(bucket) && !"native".equals(bucket) &&
                    !"anr".equals(bucket) && !"out_of_memory".equals(bucket)) return null;
            // PID and wall time are local matching data, NOT report fields. No
            // device identifier, game title, path, stack, or process name is sent.
            return PrivateDiagnosticReport.create(build, system, "unexpected_exit", bucket);
        }
    }

    static History android(Context context) {
        Context app = context.getApplicationContext();
        return (pid, started, before) -> Build.VERSION.SDK_INT >= 30
                ? Api30.bucket(app, pid, started, before) : null;
    }

    private static final class Api30 {
        static String bucket(Context app, int pid, long started, long before) {
            ActivityManager manager = (ActivityManager) app.getSystemService(Context.ACTIVITY_SERVICE);
            if (manager == null) return null;
            List<ApplicationExitInfo> entries = manager.getHistoricalProcessExitReasons(
                    app.getPackageName(), pid, 8);
            ApplicationExitInfo latest = null;
            String ownProcess = app.getApplicationInfo().processName;
            for (ApplicationExitInfo entry : entries) {
                if (entry.getPid() != pid || !ownProcess.equals(entry.getProcessName()) ||
                        entry.getTimestamp() < started || entry.getTimestamp() >= before) continue;
                if (latest == null || entry.getTimestamp() > latest.getTimestamp()) latest = entry;
            }
            if (latest == null) return null;
            switch (latest.getReason()) {
                case ApplicationExitInfo.REASON_CRASH: return "java";
                case ApplicationExitInfo.REASON_CRASH_NATIVE: return "native";
                case ApplicationExitInfo.REASON_ANR: return "anr";
                case ApplicationExitInfo.REASON_LOW_MEMORY: return "out_of_memory";
                // SIGKILL, force stop, update, reboot and intentional frontend
                // restart are not evidence of an engine crash.
                default: return null;
            }
        }
    }
}
