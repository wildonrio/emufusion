#!/usr/bin/env python3
"""Compile the production Java source set and execute focused privacy/update checks.

No APK build, install, upload, device read, or publication. Uses the same source
exclusions/dependencies as unified-android/build.sh, in a disposable class folder.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get('JAVA_HOME',
    '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home')) / 'bin'
SDK = Path(os.environ.get('ANDROID_SDK_ROOT',
    '/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk'))
DEPS = ROOT / 'unified-android/build/deps'
EXCLUDED = {
    'com/thorium/preview/MainActivity.java',
    'com/thorium/launchbridge/LaunchActivity.java',
    'com/thorium/launchbridge/RomFileProvider.java',
    'com/thorium/launchbridge/StopButtonService.java',
    'com/thorium/preview/game/InternalGameLaunchActivity.java',
    'com/thorium/preview/game/LucentGameActivity.java',
    'com/thorium/preview/game/QualificationLaunchActivity.java',
    'com/thorium/preview/game/SessionReturnRouter.java',
}

def main():
    sources = subprocess.check_output(['rg', '--files', 'android-companion/src',
        'android-launch-bridge/src', 'unified-android/src', 'unified-android/stubs',
        '-g', '*.java'], cwd=ROOT, text=True).splitlines()
    sources = [source for source in sources
               if not any(source.endswith('/' + tail) for tail in EXCLUDED)]
    dependencies = [SDK / 'platforms/android-36/android.jar',
        DEPS / 'commons-compress-1.21.jar', DEPS / 'xz-1.9.jar',
        DEPS / 'nv-websocket-client-2.14.jar',
        DEPS / 'webrtc-android-150.7871.01/classes.jar']
    for dependency in dependencies:
        if not dependency.is_file():
            raise SystemExit('Missing compile dependency: ' + str(dependency))
    env = dict(os.environ, JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true')
    with tempfile.TemporaryDirectory(prefix='emufusion-feedback-compile-') as classes:
        subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
            '-encoding', 'UTF-8', '-classpath', os.pathsep.join(map(str, dependencies)),
            '-d', classes, *sources], cwd=ROOT, env=env, check=True, timeout=90)
    print('Current unified Java source compile PASS (%d files)' % len(sources), flush=True)
    subprocess.run(['/usr/bin/python3', '-m', 'unittest',
        'tools.tests.test_voice_feedback', 'tools.tests.test_automatic_app_updates',
        'tools.tests.test_update_check_flow', 'tools.tests.test_cheat_catalog_updates',
        'tools.tests.test_private_diagnostics_receiver'],
        cwd=ROOT, env=env, check=True, timeout=90)

if __name__ == '__main__':
    main()
