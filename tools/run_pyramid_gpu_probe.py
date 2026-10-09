"""Build/run a standalone headless GLES2 pyramid diagnostic on the exact Thor."""
import json
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/qa/pyramid-detail-2026-09-16'
JAVA=Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
SDK=Path('/Users/tyleryoung/Library/Android/sdk')
ADB=['/Users/tyleryoung/.codex/tools/android-platform-tools/adb','-s','427c87b2']


def run(*args):
    return subprocess.run([str(x) for x in args],check=True,text=True,capture_output=True).stdout


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
    block=source.split('private static final String DENSE_PYRAMID_SHADER =',1)[1].split('// Direction-specific',1)[0]
    shader=''.join(json.loads(x) for x in re.findall(r'"(?:\\.|[^"\\])*"',block))
    (OUT/'pyramid.glsl').write_text(shader)
    for name in ('classes','dex'):(OUT/name).mkdir(exist_ok=True)
    run(JAVA/'javac','-cp',SDK/'platforms/android-35/android.jar','-d',OUT/'classes',ROOT/'tools/qa/DensePyramidDeviceTest.java')
    run(JAVA/'jar','cf',OUT/'classes.jar','-C',OUT/'classes','.')
    run(SDK/'build-tools/36.0.0/d8','--lib',SDK/'platforms/android-35/android.jar','--output',OUT/'dex',OUT/'classes.jar')
    run(JAVA/'jar','cf',OUT/'probe.jar','-C',OUT/'dex','classes.dex')
    remote=run(*ADB,'shell','mktemp -d /data/local/tmp/emufusion-pyramid-XXXXXX').strip()
    (OUT/'remote.txt').write_text(remote+'\n')
    run(*ADB,'push',OUT/'probe.jar',OUT/'pyramid.glsl',remote+'/')
    result=subprocess.run(ADB+['shell',f'CLASSPATH={remote}/probe.jar app_process / com.thorium.preview.game.DensePyramidDeviceTest {remote}/pyramid.glsl'],text=True,capture_output=True,timeout=30)
    (OUT/'device.log').write_text(result.stdout+result.stderr)
    print(result.stdout+result.stderr)
    result.check_returncode()


if __name__=='__main__':main()
