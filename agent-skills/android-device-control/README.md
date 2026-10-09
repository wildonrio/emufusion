# Installing the Android Device Control skill

This folder is a portable copy of the Codex `android-device-control` skill used
to inspect and operate the Android devices during EmuFusion development. It does
not contain device IDs, RustDesk passwords, ADB keys, account credentials, or
API keys.

## Install from the EmuFusion repository

Clone or update the repository, then copy the complete skill directory into
your personal Codex skills folder:

```sh
git clone https://github.com/wildonrio/emufusion.git
cd emufusion
mkdir -p "$HOME/.codex/skills"
cp -R agent-skills/android-device-control "$HOME/.codex/skills/"
chmod +x "$HOME/.codex/skills/android-device-control/scripts/androidctl"
chmod +x "$HOME/.codex/skills/android-device-control/scripts/rustdeskctl"
```

If the repository is already cloned:

```sh
git pull --ff-only
mkdir -p "$HOME/.codex/skills"
cp -R agent-skills/android-device-control "$HOME/.codex/skills/"
```

Restart or reload Codex after installation so its skill catalog is refreshed.
The skill should then appear as `android-device-control`.

## Use without installing

An AI working directly in the EmuFusion checkout can read
`agent-skills/android-device-control/SKILL.md` and run the bundled controller:

```sh
./agent-skills/android-device-control/scripts/androidctl doctor
./agent-skills/android-device-control/scripts/androidctl devices
```

## Runtime dependencies

- Android SDK Platform-Tools (`adb`) for USB or wireless debugging.
- `scrcpy` for optional live mirroring.
- The official RustDesk desktop application for the low-setup remote-support
  workflow.

The scripts also look for the Codex-managed ADB installation at
`~/.codex/tools/android-platform-tools/adb` and Android Studio's standard SDK
location.
