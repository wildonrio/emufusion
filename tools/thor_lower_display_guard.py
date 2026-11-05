#!/usr/bin/env python3
"""Run the daemon that keeps the Thor lower screen from staying squeezed (no root).

Trigger (firmware SurfaceFlinger; disassembled and reproduced 2026-11-05, evidence in
docs/qa/thor-lower-display-2026-11-05): setActiveModeInHwcIfNeeded also calls
initiateModeChange on the lower display with the upper panel's mode, and that call logs
"Trying to initiate a mode change to invalid mode" but does not return: it stores the
upper's 1080x1920 mode as the lower display's upcoming mode. When such a change is still
pending and the lower panel has just powered on first, it is SurfaceFlinger's active display;
updateInternalStateWithChangedMode then sees a resolution change on it and recreates it
with a 1080x1920 framebuffer on its 1080x1240 panel. SurfaceFlinger logs "Dispatching display
hotplug event displayId=<lower>" at that moment. The app cannot prevent this (the firmware
does it for any upper-panel mode change) or repair it (ACCESS_SURFACE_FLINGER is
signature-only; shell has it).

LowerDisplayGuard therefore runs as a detached shell-uid process, started here over adb. It
survives USB unplug, waits on display power and hotplug events with no polling, and repairs
the framebuffer when it is wrong. A device reboot ends it: `watch` (launchd on the Mac, see
`install-launchd`) starts it again the next time the Thor is on USB. It is not an app, so
nothing is installed and app data is untouched.

usage: thor_lower_display_guard.py start|stop|status|watch|install-launchd|uninstall-launchd
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import thor_lower_display_repair as repair_tool  # noqa: E402

JAVA_DIR = HERE / "thor_lower_display"
JAVA_SOURCES = [JAVA_DIR / name for name in
                ("LowerDisplayGuard.java", "LowerDisplayState.java", "SfLowerDisplay.java")]
STUBS = JAVA_DIR / "stubs"
NAME = "emufusion-lower-display-guard"
DEVICE_DEX = f"/data/local/tmp/{NAME}.dex"
DEVICE_SCRIPT = f"/data/local/tmp/{NAME}.sh"
DEVICE_LOG = f"/data/local/tmp/{NAME}.log"
# A crash or a system_server restart comes back after a pause; a second copy (exit 3) stops.
SUPERVISOR = f"""#!/system/bin/sh
while :; do
  CLASSPATH={DEVICE_DEX} app_process /system/bin --nice-name={NAME} LowerDisplayGuard
  [ "$?" = 3 ] && exit 0
  sleep 5
done
"""
LAUNCH_LABEL = "com.emufusion.thor-lower-display-guard"
LAUNCH_PLIST = Path.home() / "Library/LaunchAgents" / f"{LAUNCH_LABEL}.plist"
# launchd must not depend on which branch this shared worktree has checked out.
LAUNCH_HOME = Path.home() / ".local/share/emufusion-thor-lower-display-guard"
BOOT_TIMEOUT_S = 240


def build_dex(workdir):
    classes = workdir / "classes"
    classes.mkdir()
    android_jar = sorted((repair_tool.SDK / "platforms").glob("android-*/android.jar"))[-1]
    d8 = sorted((repair_tool.SDK / "build-tools").glob("*/d8"))[-1]
    subprocess.run([str(repair_tool.JAVA_HOME / "bin/javac"), "-source", "8", "-target", "8", "-nowarn",
                    "-cp", str(android_jar), "-sourcepath", str(STUBS), "-d", str(classes),
                    *map(str, JAVA_SOURCES)],
                   check=True, capture_output=True, text=True)
    # Only the top-level classes: the stub stays out, the device supplies the real class.
    subprocess.run([str(d8), "--min-api", "26", "--lib", str(android_jar), "--classpath", str(classes),
                    "--output", str(workdir), *map(str, classes.glob("*.class"))],
                   check=True, capture_output=True, text=True,
                   env=dict(os.environ, JAVA_HOME=str(repair_tool.JAVA_HOME)))
    return workdir / "classes.dex"


def wait_for_boot(device):
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if device.run("shell", "getprop sys.boot_completed", check=False).strip() == "1":
            return True
        time.sleep(3)
    return False


def install_files(device):
    workdir = Path(tempfile.mkdtemp(prefix="thor-lower-guard-"))
    try:
        dex = build_dex(workdir)
        digest = hashlib.sha256(dex.read_bytes()).hexdigest()
        current = device.run("shell", f"sha256sum {DEVICE_DEX} 2>/dev/null", check=False).split()
        changed = not current or current[0] != digest
        if changed:
            device.run("push", str(dex), DEVICE_DEX)
        script = workdir / "guard.sh"
        script.write_text(SUPERVISOR)
        device.run("push", str(script), DEVICE_SCRIPT)
        device.run("shell", f"chmod 755 {DEVICE_SCRIPT}")
        return changed
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def launch(device):
    # setsid: its own session with no controlling terminal, so ending this adb shell
    # (or unplugging USB) does not hang it up.
    device.run("shell", f"setsid {DEVICE_SCRIPT} </dev/null >/dev/null 2>&1 &", check=False)
    for _ in range(20):
        time.sleep(0.5)
        if device.run("shell", f"pidof {NAME}", check=False).strip():
            return True
    return False


def guard_pids(device):
    """Supervisor and guard pids. Not pkill -f: its pattern would match its own adb shell."""
    pids = []
    for line in device.run("shell", "ps -A -o PID,NAME,ARGS", check=False).splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and (
                fields[1] == NAME or (fields[1] == "sh" and DEVICE_SCRIPT in fields[2])):
            pids.append(fields[0])
    return pids


def stop(device):
    pids = guard_pids(device)
    if pids:
        device.run("shell", "kill " + " ".join(pids), check=False)


def start(device):
    if not wait_for_boot(device):
        print("Thor did not finish booting")
        return 1
    running = bool(device.run("shell", f"pidof {NAME}", check=False).strip())
    try:
        changed = install_files(device)
    except (OSError, subprocess.CalledProcessError, IndexError) as failed:
        # No toolchain here: the copy already on the device is still good.
        print(f"cannot rebuild the guard ({failed}); using the copy on the device")
        changed = False
    if running and changed:
        stop(device)
        running = False
        time.sleep(1)
    if running:
        print("guard already running")
        return 0
    if launch(device):
        print("guard started")
        return 0
    print("guard failed to start")
    return 1


def status(device):
    pid = device.run("shell", f"pidof {NAME}", check=False).strip()
    print("guard", f"running pid {pid}" if pid else "NOT RUNNING")
    print(device.run("shell", f"ps -A -o USER,PID,PPID,PGID,TTY,ELAPSED,RSS,TIME,NAME,ARGS | grep -E '{NAME}|ELAPSED'"
                              " | grep -v grep", check=False).rstrip())
    print(device.run("shell", f"tail -n 8 {DEVICE_LOG} 2>/dev/null", check=False).rstrip())
    return 0 if pid else 2


def watch(device):
    """launchd entry point: start the guard whenever the Thor appears. Blocks on adb, no polling.

    `adb track-devices` reports every transport change, including a reconnect too brief for
    `adb wait-for-disconnect` to notice.
    """
    while True:
        tracker = subprocess.Popen([device.base[0], "track-devices"], stdout=subprocess.PIPE, text=True)
        connected = f"{device.base[2]}\tdevice"
        online = False
        for line in tracker.stdout:
            now_online = connected in line
            if now_online and not online:
                ensure_running(device)
            online = now_online
        tracker.wait()
        time.sleep(5)


def ensure_running(device):
    try:
        if not wait_for_boot(device):
            print("Thor did not finish booting", flush=True)
        elif device.run("shell", f"pidof {NAME}", check=False).strip():
            print("guard already running", flush=True)
        else:
            start(device)
            sys.stdout.flush()
    except (RuntimeError, subprocess.SubprocessError) as failed:
        print(f"start failed: {failed}", flush=True)


def plist_text():
    python = "/usr/bin/python3"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  Starts the Thor lower-display guard whenever the Thor is on USB (a Thor reboot ends it).
  Waits on adb; it does not poll. Source: tools/thor_lower_display_guard.py in emufusion.
  Stop: launchctl bootout gui/$(id -u) {LAUNCH_PLIST}
  Log:  ~/Library/Logs/thor-lower-display-guard.log
-->
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-u</string>
    <string>{LAUNCH_HOME}/thor_lower_display_guard.py</string>
    <string>watch</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>{Path.home()}/Library/Logs/thor-lower-display-guard.log</string>
  <key>StandardErrorPath</key><string>{Path.home()}/Library/Logs/thor-lower-display-guard.log</string>
</dict>
</plist>
"""


def install_launchd():
    shutil.rmtree(LAUNCH_HOME, ignore_errors=True)
    (LAUNCH_HOME / "thor_lower_display").mkdir(parents=True)
    shutil.copy2(HERE / "thor_lower_display_guard.py", LAUNCH_HOME)
    shutil.copy2(HERE / "thor_lower_display_repair.py", LAUNCH_HOME)
    for source in JAVA_DIR.glob("*.java"):
        shutil.copy2(source, LAUNCH_HOME / "thor_lower_display")
    shutil.copytree(STUBS, LAUNCH_HOME / "thor_lower_display/stubs")
    LAUNCH_PLIST.write_text(plist_text())
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LAUNCH_LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(LAUNCH_PLIST)], check=True)
    print(f"launchd job {LAUNCH_LABEL} loaded from {LAUNCH_PLIST}")
    return 0


def uninstall_launchd():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_LABEL}"], capture_output=True)
    LAUNCH_PLIST.unlink(missing_ok=True)
    shutil.rmtree(LAUNCH_HOME, ignore_errors=True)
    print("launchd job removed")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["start", "stop", "status", "watch",
                                            "install-launchd", "uninstall-launchd"])
    parser.add_argument("--adb", type=Path, default=repair_tool.DEFAULT_ADB)
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", repair_tool.DEFAULT_SERIAL))
    args = parser.parse_args(argv)
    if args.command == "install-launchd":
        return install_launchd()
    if args.command == "uninstall-launchd":
        return uninstall_launchd()
    if args.command == "watch":
        watch(repair_tool.Device(args.adb, args.serial))
        return 0
    device = repair_tool.Device(args.adb, args.serial)
    if args.command == "start":
        return start(device)
    if args.command == "stop":
        stop(device)
        print("guard stopped" if not device.run("shell", f"pidof {NAME}", check=False).strip()
              else "guard still running")
        return 0
    return status(device)


if __name__ == "__main__":
    sys.exit(main())
